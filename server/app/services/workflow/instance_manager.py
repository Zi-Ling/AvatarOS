"""
工作流实例管理器：生命周期管理 + 核心执行循环。

职责：
- create_and_run: 创建实例并启动执行
- _execution_loop: DAG 驱动的异步执行循环
- _execute_step: 单步执行 + attempt 记录 + failure_policy
- pause / resume / cancel / retry / rerun: 生命周期操作
- _collect_instance_outputs: 终点节点输出聚合
- _resolve_step_inputs: 按优先级解析步骤输入
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.db.database import engine
from app.services.workflow.models import (
    InstanceStatus,
    StepExecutorType,
    StepFailurePolicy,
    StepRunStatus,
    WorkflowEdgeDef,
    WorkflowInstance,
    WorkflowStepAttempt,
    WorkflowStepDef,
    WorkflowStepRun,
    WorkflowTemplateVersion,
    VALID_INSTANCE_TRANSITIONS,
    VALID_STEP_RUN_TRANSITIONS,
    INSTANCE_TERMINAL_STATUSES,
    STEP_RUN_TERMINAL_STATUSES,
    _now,
    _uuid,
)
from app.services.workflow.dag_scheduler import WorkflowDAGScheduler
from app.services.workflow.param_resolver import ParamResolver
from app.services.workflow.step_executor import (
    StepExecutor,
    StepRunResult,
)

logger = logging.getLogger(__name__)


class InstanceManager:
    """工作流实例生命周期管理。"""

    def __init__(
        self,
        dag_scheduler: WorkflowDAGScheduler,
        param_resolver: ParamResolver,
        skill_executor: StepExecutor,
        task_session_executor: StepExecutor,
        trigger_manager=None,
        max_parallel: int = 5,
        browser_automation_executor: StepExecutor | None = None,
        native_adapter_executor: StepExecutor | None = None,
        routed_executor: StepExecutor | None = None,
        event_bus=None,
    ):
        self._scheduler = dag_scheduler
        self._param_resolver = param_resolver
        self._executors: dict[str, StepExecutor] = {
            StepExecutorType.SKILL.value: skill_executor,
            StepExecutorType.TASK_SESSION.value: task_session_executor,
        }
        if browser_automation_executor is not None:
            self._executors[StepExecutorType.BROWSER_AUTOMATION.value] = browser_automation_executor
        if native_adapter_executor is not None:
            self._executors[StepExecutorType.NATIVE_ADAPTER.value] = native_adapter_executor
        if routed_executor is not None:
            self._executors[StepExecutorType.ROUTED.value] = routed_executor
        self._trigger_manager = trigger_manager  # 向后兼容，优先用 event_bus
        self._event_bus = event_bus
        self._max_parallel = max_parallel
        # instance_id → asyncio.Event，用于 pause 信号
        self._pause_flags: dict[str, asyncio.Event] = {}
        # instance_id → bool，用于 cancel 信号
        self._cancel_flags: dict[str, bool] = {}
        # 保护 _pause_flags / _cancel_flags 的并发访问
        self._flags_lock = asyncio.Lock()

    def set_trigger_manager(self, tm) -> None:
        """延迟注入 TriggerManager（向后兼容，推荐用 EventBus）。"""
        self._trigger_manager = tm

    def _publish_workflow_completed(self, instance: WorkflowInstance) -> None:
        """通过 EventBus 发布工作流完成事件，解耦 TriggerManager。"""
        if self._event_bus:
            try:
                from app.avatar.runtime.events.types import Event, EventType
                event = Event(
                    type=EventType.WORKFLOW_INSTANCE_COMPLETED,
                    source="instance_manager",
                    payload={
                        "instance_id": instance.id,
                        "template_id": instance.template_id,
                        "outputs": instance.outputs or {},
                    },
                )
                self._event_bus.publish(event)
            except Exception as exc:
                logger.warning(f"[InstanceManager] Failed to publish completion event: {exc}")
        elif self._trigger_manager:
            # 向后兼容：没有 EventBus 时直接调用
            import asyncio
            try:
                asyncio.create_task(self._trigger_manager.on_workflow_completed(instance))
            except Exception as exc:
                logger.warning(f"[InstanceManager] trigger chain error: {exc}")

    # ------------------------------------------------------------------
    # create_and_run
    # ------------------------------------------------------------------

    async def create_and_run(
        self,
        template_version_id: str,
        params: dict[str, Any],
        trigger_id: Optional[str] = None,
        parent_instance_id: Optional[str] = None,
    ) -> WorkflowInstance:
        """创建实例并启动执行循环。"""
        # 1. 加载版本
        with Session(engine) as db:
            version = db.get(WorkflowTemplateVersion, template_version_id)
            if not version:
                raise ValueError(f"Version not found: {template_version_id}")
            # 在 session 关闭前提取所有需要的属性
            steps_raw: list[dict] = version.steps or []
            edges_raw: list[dict] = version.edges or []
            param_defs_raw: list[dict] = version.parameters or []
            global_policy = version.global_failure_policy or "fail_fast"
            version_template_id = version.template_id

        # 2. 解析 Pydantic 模型
        from app.services.workflow.models import WorkflowParamDef
        steps = [WorkflowStepDef(**s) for s in steps_raw]
        edges = [WorkflowEdgeDef(**e) for e in edges_raw]
        param_defs = [WorkflowParamDef(**p) for p in param_defs_raw]

        # 3. 参数解析
        resolved_steps = self._param_resolver.resolve(steps, param_defs, params)

        # 4. 创建 Instance
        now = _now()
        instance = WorkflowInstance(
            id=_uuid(),
            template_id=version_template_id,
            template_version_id=template_version_id,
            status=InstanceStatus.CREATED.value,
            params=params,
            trigger_id=trigger_id,
            parent_instance_id=parent_instance_id,
            created_at=now,
            updated_at=now,
        )

        # 5. 为每个 step 创建 StepRun
        step_runs: list[WorkflowStepRun] = []
        for step in resolved_steps:
            sr = WorkflowStepRun(
                id=_uuid(),
                instance_id=instance.id,
                step_id=step.step_id,
                status=StepRunStatus.PENDING.value,
                executor_type=step.executor_type,
            )
            step_runs.append(sr)

        instance_id = instance.id  # 在 session 关闭前捕获

        with Session(engine, expire_on_commit=False) as db:
            db.add(instance)
            for sr in step_runs:
                db.add(sr)
            db.commit()

        # 6. 转 running，启动执行循环
        self._transition_instance(instance_id, InstanceStatus.RUNNING.value)

        asyncio.create_task(
            self._execution_loop(
                instance_id, resolved_steps, edges, global_policy
            )
        )
        return instance

    # ------------------------------------------------------------------
    # _execution_loop
    # ------------------------------------------------------------------

    async def _execution_loop(
        self,
        instance_id: str,
        steps: list[WorkflowStepDef],
        edges: list[WorkflowEdgeDef],
        global_policy: str,
    ) -> None:
        """DAG 驱动的异步执行循环。"""
        logger.info(f"[InstanceManager] Execution loop started: {instance_id}")
        try:
            while True:
                # 检查 cancel
                if self._cancel_flags.get(instance_id):
                    break

                # 检查 pause
                if instance_id in self._pause_flags:
                    # pause 模式：等待所有 running 完成后转 paused
                    running = self._get_running_steps(instance_id)
                    if not running:
                        self._transition_instance(instance_id, InstanceStatus.PAUSED.value)
                        logger.info(f"[InstanceManager] Instance paused: {instance_id}")
                        return
                    # 等待 running 步骤完成
                    await asyncio.sleep(1.0)
                    continue

                # 加载当前 step_runs 状态
                step_runs = self._load_step_runs(instance_id)
                step_outputs = self._collect_step_outputs(step_runs)

                # 获取 ready steps
                ready_ids, newly_skipped = self._scheduler.get_ready_steps(
                    steps, edges, step_runs, step_outputs, self._max_parallel
                )

                # 处理 newly_skipped 步骤
                for skipped_id in newly_skipped:
                    sr = step_runs.get(skipped_id)
                    if sr:
                        self._transition_step_run(sr.id, StepRunStatus.SKIPPED.value)

                running_count = sum(
                    1 for sr in step_runs.values()
                    if sr.status == StepRunStatus.RUNNING.value
                )

                if not ready_ids and running_count == 0:
                    # 没有 ready 也没有 running → 检查是否全部完成
                    all_terminal = all(
                        sr.status in STEP_RUN_TERMINAL_STATUSES
                        for sr in step_runs.values()
                    )
                    if all_terminal:
                        has_failed = any(
                            sr.status == StepRunStatus.FAILED.value
                            for sr in step_runs.values()
                        )
                        if has_failed:
                            self._transition_instance(instance_id, InstanceStatus.FAILED.value)
                        else:
                            # 收集输出
                            outputs = self._collect_instance_outputs(steps, edges, step_runs)
                            self._finalize_instance(instance_id, InstanceStatus.COMPLETED.value, outputs)
                            # 通过 EventBus 发布完成事件（解耦 TriggerManager）
                            inst = self._get_instance(instance_id)
                            if inst:
                                self._publish_workflow_completed(inst)
                        break
                    # 有非终态但无 ready 也无 running → 异常，标记 failed
                    logger.error(f"[InstanceManager] Deadlock detected: {instance_id}")
                    self._transition_instance(instance_id, InstanceStatus.FAILED.value)
                    break

                if not ready_ids:
                    # 有 running 但没有新 ready → 等待
                    await asyncio.sleep(0.5)
                    continue

                # 并行启动 ready steps
                tasks = []
                for step_id in ready_ids:
                    step_def = self._find_step_def(steps, step_id)
                    if not step_def:
                        continue
                    resolved_inputs = self._resolve_step_inputs(
                        step_id, steps, edges, step_runs, step_outputs
                    )
                    tasks.append(
                        self._execute_step(
                            instance_id, step_id, step_def,
                            resolved_inputs, global_policy
                        )
                    )

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as exc:
            logger.exception(f"[InstanceManager] Execution loop error: {instance_id}")
            self._transition_instance(instance_id, InstanceStatus.FAILED.value)

    # ------------------------------------------------------------------
    # _execute_step
    # ------------------------------------------------------------------

    async def _execute_step(
        self,
        instance_id: str,
        step_id: str,
        step_def: WorkflowStepDef,
        resolved_inputs: dict[str, Any],
        global_policy: str,
    ) -> None:
        """执行单个步骤，含 attempt 记录和 failure_policy 处理。"""
        step_run = self._get_step_run(instance_id, step_id)
        if not step_run:
            return

        # 转 running
        self._transition_step_run(step_run.id, StepRunStatus.RUNNING.value)
        self._update_step_run_fields(step_run.id, inputs=resolved_inputs, started_at=_now())

        executor = self._executors.get(step_def.executor_type)
        if not executor:
            self._transition_step_run(step_run.id, StepRunStatus.FAILED.value)
            self._update_step_run_fields(
                step_run.id, error=f"Unknown executor: {step_def.executor_type}", ended_at=_now()
            )
            return

        # 确定 failure_policy
        policy_str = step_def.failure_policy or global_policy
        try:
            policy = StepFailurePolicy(policy_str)
        except ValueError:
            policy = StepFailurePolicy.FAIL_FAST

        max_attempts = step_def.retry_max if policy == StepFailurePolicy.RETRY else 1

        result: Optional[StepRunResult] = None
        for attempt_num in range(1, max_attempts + 1):
            # 创建 attempt 记录
            attempt_id = _uuid()
            attempt_start = _now()
            self._create_attempt(attempt_id, step_run.id, attempt_num, attempt_start)

            try:
                result = await asyncio.wait_for(
                    executor.execute(step_def, resolved_inputs, instance_id),
                    timeout=step_def.timeout_seconds,
                )
            except asyncio.TimeoutError:
                result = StepRunResult(
                    success=False, outputs={},
                    error=f"Step timed out after {step_def.timeout_seconds}s",
                )
            except Exception as exc:
                result = StepRunResult(success=False, outputs={}, error=str(exc))

            # 更新 attempt
            attempt_end = _now()
            self._update_attempt(
                attempt_id,
                status="success" if result.success else "failed",
                outputs=result.outputs,
                error=result.error,
                ended_at=attempt_end,
                duration_ms=result.duration_ms,
            )

            if result.success:
                break

            # 失败但还有重试机会
            if attempt_num < max_attempts and policy == StepFailurePolicy.RETRY:
                self._update_step_run_fields(step_run.id, retry_count=attempt_num)
                logger.info(
                    f"[InstanceManager] Retrying step {step_id} "
                    f"(attempt {attempt_num}/{max_attempts})"
                )
                continue

            # 最后一次尝试也失败了
            break

        if not result:
            result = StepRunResult(success=False, outputs={}, error="No execution result")

        now = _now()
        if result.success:
            self._transition_step_run(step_run.id, StepRunStatus.SUCCESS.value)
            self._update_step_run_fields(
                step_run.id,
                outputs=result.outputs,
                ended_at=now,
                duration_ms=result.duration_ms,
                child_task_session_id=result.child_task_session_id,
            )
        else:
            self._transition_step_run(step_run.id, StepRunStatus.FAILED.value)
            self._update_step_run_fields(
                step_run.id,
                error=result.error,
                outputs=result.outputs,
                ended_at=now,
                duration_ms=result.duration_ms,
                child_task_session_id=result.child_task_session_id,
            )
            # fail_fast → 取消所有 pending 步骤
            if policy == StepFailurePolicy.FAIL_FAST:
                self._cancel_pending_steps(instance_id)

    # ------------------------------------------------------------------
    # 生命周期操作：pause / resume / cancel / retry / rerun
    # ------------------------------------------------------------------

    async def pause(self, instance_id: str) -> None:
        """暂停：冻结调度，不强杀 running step。"""
        inst = self._get_instance(instance_id)
        if not inst or inst.status != InstanceStatus.RUNNING.value:
            raise ValueError(f"Cannot pause instance in status: {inst.status if inst else 'not found'}")
        async with self._flags_lock:
            self._pause_flags[instance_id] = asyncio.Event()

    async def resume(self, instance_id: str) -> None:
        """恢复执行循环。"""
        inst = self._get_instance(instance_id)
        if not inst or inst.status != InstanceStatus.PAUSED.value:
            raise ValueError(f"Cannot resume instance in status: {inst.status if inst else 'not found'}")

        async with self._flags_lock:
            self._pause_flags.pop(instance_id, None)
        self._transition_instance(instance_id, InstanceStatus.RUNNING.value)

        # 重新加载版本数据并启动执行循环
        version = self._load_version(inst.template_version_id)
        if version:
            steps, edges, global_policy = self._parse_version(version, inst.params)
            asyncio.create_task(
                self._execution_loop(instance_id, steps, edges, global_policy)
            )

    async def cancel(self, instance_id: str) -> None:
        """取消实例：pending→cancelled，task_session 步骤级联取消。"""
        inst = self._get_instance(instance_id)
        if not inst or inst.status in INSTANCE_TERMINAL_STATUSES:
            raise ValueError(f"Cannot cancel instance in status: {inst.status if inst else 'not found'}")

        async with self._flags_lock:
            self._cancel_flags[instance_id] = True
        self._cancel_pending_steps(instance_id)
        self._transition_instance(instance_id, InstanceStatus.CANCELLED.value)
        async with self._flags_lock:
            self._cancel_flags.pop(instance_id, None)
            self._pause_flags.pop(instance_id, None)

    async def retry(self, instance_id: str) -> None:
        """
        原地重试：
        1. failed 步骤 → pending
        2. 重新计算 skipped 下游（前驱恢复后重新参与调度）
        3. 已 success 的步骤保留（断点续跑）
        4. 重新进入执行循环
        """
        inst = self._get_instance(instance_id)
        if not inst or inst.status not in (InstanceStatus.FAILED.value, InstanceStatus.CANCELLED.value):
            raise ValueError(f"Cannot retry instance in status: {inst.status if inst else 'not found'}")

        step_runs = self._load_step_runs(instance_id)

        # 重置 failed → pending
        for sr in step_runs.values():
            if sr.status == StepRunStatus.FAILED.value:
                self._transition_step_run(sr.id, StepRunStatus.PENDING.value)

        # 重新计算 skipped：如果前驱被重置为 pending，下游 skipped 也应重置
        version = self._load_version(inst.template_version_id)
        if version:
            edges = [WorkflowEdgeDef(**e) for e in (version.edges or [])]
            # 重新加载 step_runs（已更新 failed→pending）
            step_runs = self._load_step_runs(instance_id)
            for sr in step_runs.values():
                if sr.status == StepRunStatus.SKIPPED.value:
                    # 检查是否有前驱被重置为 pending（意味着可能重新满足）
                    predecessors = [
                        e.source_step_id for e in edges
                        if e.target_step_id == sr.step_id and not e.optional
                    ]
                    has_pending_pred = any(
                        step_runs.get(pid) and step_runs[pid].status == StepRunStatus.PENDING.value
                        for pid in predecessors
                    )
                    if has_pending_pred:
                        self._transition_step_run(sr.id, StepRunStatus.PENDING.value)

        self._transition_instance(instance_id, InstanceStatus.RUNNING.value)

        if version:
            steps, edges, global_policy = self._parse_version(version, inst.params)
            asyncio.create_task(
                self._execution_loop(instance_id, steps, edges, global_policy)
            )

    async def rerun(self, instance_id: str) -> WorkflowInstance:
        """基于原 version_id 和 params 创建新实例。"""
        inst = self._get_instance(instance_id)
        if not inst:
            raise ValueError(f"Instance not found: {instance_id}")
        return await self.create_and_run(
            template_version_id=inst.template_version_id,
            params=inst.params or {},
            trigger_id=inst.trigger_id,
            parent_instance_id=inst.parent_instance_id,
        )

    # ------------------------------------------------------------------
    # _resolve_step_inputs
    # ------------------------------------------------------------------

    def _resolve_step_inputs(
        self,
        step_id: str,
        steps: list[WorkflowStepDef],
        edges: list[WorkflowEdgeDef],
        step_runs: dict[str, WorkflowStepRun],
        step_outputs: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """
        按优先级解析步骤输入：edge 映射 > 静态参数 > 模板参数。
        """
        step_def = self._find_step_def(steps, step_id)
        if not step_def:
            return {}

        # 从静态参数开始
        resolved = dict(step_def.params)

        # edge 映射覆盖（最高优先级）
        for edge in edges:
            if edge.target_step_id != step_id:
                continue
            source_outputs = step_outputs.get(edge.source_step_id, {})
            if edge.source_output_key in source_outputs:
                resolved[edge.target_param_key] = source_outputs[edge.source_output_key]

        return resolved

    # ------------------------------------------------------------------
    # _collect_instance_outputs
    # ------------------------------------------------------------------

    def _collect_instance_outputs(
        self,
        steps: list[WorkflowStepDef],
        edges: list[WorkflowEdgeDef],
        step_runs: dict[str, WorkflowStepRun],
    ) -> dict[str, Any]:
        """
        收集实例级汇总输出。
        规则：终点节点（无下游 edge 的步骤）的 outputs 聚合。
        格式：{"<step_id>": {outputs}, ...}
        """
        # 找出有下游 edge 的步骤
        has_downstream = {e.source_step_id for e in edges}
        # 终点节点 = 所有步骤 - 有下游的步骤
        all_step_ids = {s.step_id for s in steps}
        terminal_ids = all_step_ids - has_downstream

        outputs: dict[str, Any] = {}
        for sid in terminal_ids:
            sr = step_runs.get(sid)
            if sr and sr.status == StepRunStatus.SUCCESS.value and sr.outputs:
                outputs[sid] = sr.outputs
        return outputs

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _get_instance(instance_id: str) -> Optional[WorkflowInstance]:
        with Session(engine) as db:
            return db.get(WorkflowInstance, instance_id)

    @staticmethod
    def _load_step_runs(instance_id: str) -> dict[str, WorkflowStepRun]:
        """加载实例的所有 step_runs，返回 {step_id: StepRun}。"""
        with Session(engine) as db:
            runs = db.exec(
                select(WorkflowStepRun).where(
                    WorkflowStepRun.instance_id == instance_id
                )
            ).all()
            return {sr.step_id: sr for sr in runs}

    @staticmethod
    def _get_step_run(instance_id: str, step_id: str) -> Optional[WorkflowStepRun]:
        with Session(engine) as db:
            runs = db.exec(
                select(WorkflowStepRun).where(
                    WorkflowStepRun.instance_id == instance_id,
                    WorkflowStepRun.step_id == step_id,
                )
            ).all()
            return runs[0] if runs else None

    @staticmethod
    def _get_running_steps(instance_id: str) -> list[WorkflowStepRun]:
        with Session(engine) as db:
            return list(db.exec(
                select(WorkflowStepRun).where(
                    WorkflowStepRun.instance_id == instance_id,
                    WorkflowStepRun.status == StepRunStatus.RUNNING.value,
                )
            ).all())

    @staticmethod
    def _collect_step_outputs(
        step_runs: dict[str, WorkflowStepRun],
    ) -> dict[str, dict[str, Any]]:
        """收集所有已完成步骤的 outputs。"""
        return {
            sid: sr.outputs
            for sid, sr in step_runs.items()
            if sr.status == StepRunStatus.SUCCESS.value and sr.outputs
        }

    @staticmethod
    def _find_step_def(
        steps: list[WorkflowStepDef], step_id: str
    ) -> Optional[WorkflowStepDef]:
        for s in steps:
            if s.step_id == step_id:
                return s
        return None

    @staticmethod
    def _load_version(version_id: str) -> Optional[WorkflowTemplateVersion]:
        with Session(engine) as db:
            return db.get(WorkflowTemplateVersion, version_id)

    def _parse_version(
        self, version: WorkflowTemplateVersion, params: dict[str, Any]
    ) -> tuple[list[WorkflowStepDef], list[WorkflowEdgeDef], str]:
        """解析版本数据为 Pydantic 模型。"""
        from app.services.workflow.models import WorkflowParamDef
        steps = [WorkflowStepDef(**s) for s in (version.steps or [])]
        edges = [WorkflowEdgeDef(**e) for e in (version.edges or [])]
        param_defs = [WorkflowParamDef(**p) for p in (version.parameters or [])]
        global_policy = version.global_failure_policy or "fail_fast"
        resolved_steps = self._param_resolver.resolve(steps, param_defs, params)
        return resolved_steps, edges, global_policy

    # ------------------------------------------------------------------
    # 状态转换辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _transition_instance(instance_id: str, new_status: str) -> None:
        with Session(engine) as db:
            inst = db.get(WorkflowInstance, instance_id)
            if not inst:
                return
            allowed = VALID_INSTANCE_TRANSITIONS.get(inst.status, set())
            if new_status not in allowed:
                logger.warning(
                    f"[InstanceManager] Invalid instance transition: "
                    f"{inst.status} → {new_status}"
                )
                return
            inst.status = new_status
            inst.updated_at = _now()
            if new_status == InstanceStatus.RUNNING.value and not inst.started_at:
                inst.started_at = _now()
            if new_status in INSTANCE_TERMINAL_STATUSES:
                inst.completed_at = _now()
            db.add(inst)
            db.commit()

    @staticmethod
    def _finalize_instance(
        instance_id: str, new_status: str, outputs: dict[str, Any]
    ) -> None:
        """完成实例：设置状态 + 写入 outputs。"""
        with Session(engine) as db:
            inst = db.get(WorkflowInstance, instance_id)
            if not inst:
                return
            allowed = VALID_INSTANCE_TRANSITIONS.get(inst.status, set())
            if new_status not in allowed:
                return
            inst.status = new_status
            inst.outputs = outputs
            inst.completed_at = _now()
            inst.updated_at = _now()
            db.add(inst)
            db.commit()

    @staticmethod
    def _transition_step_run(step_run_id: str, new_status: str) -> None:
        with Session(engine) as db:
            sr = db.get(WorkflowStepRun, step_run_id)
            if not sr:
                return
            allowed = VALID_STEP_RUN_TRANSITIONS.get(sr.status, set())
            if new_status not in allowed:
                logger.warning(
                    f"[InstanceManager] Invalid step transition: "
                    f"{sr.status} → {new_status} (step_run={step_run_id})"
                )
                return
            sr.status = new_status
            db.add(sr)
            db.commit()

    @staticmethod
    def _update_step_run_fields(step_run_id: str, **kwargs) -> None:
        with Session(engine) as db:
            sr = db.get(WorkflowStepRun, step_run_id)
            if not sr:
                return
            for k, v in kwargs.items():
                if hasattr(sr, k) and v is not None:
                    setattr(sr, k, v)
            db.add(sr)
            db.commit()

    @staticmethod
    def _cancel_pending_steps(instance_id: str) -> None:
        """将所有 pending 步骤标记为 cancelled。"""
        with Session(engine) as db:
            runs = db.exec(
                select(WorkflowStepRun).where(
                    WorkflowStepRun.instance_id == instance_id,
                    WorkflowStepRun.status == StepRunStatus.PENDING.value,
                )
            ).all()
            for sr in runs:
                sr.status = StepRunStatus.CANCELLED.value
            db.add_all(runs)
            db.commit()

    # ------------------------------------------------------------------
    # Attempt 记录辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _create_attempt(
        attempt_id: str,
        step_run_id: str,
        attempt_number: int,
        started_at: datetime,
    ) -> None:
        attempt = WorkflowStepAttempt(
            id=attempt_id,
            step_run_id=step_run_id,
            attempt_number=attempt_number,
            status="running",
            started_at=started_at,
        )
        with Session(engine) as db:
            db.add(attempt)
            db.commit()

    @staticmethod
    def _update_attempt(
        attempt_id: str,
        status: str,
        outputs: dict[str, Any],
        error: Optional[str],
        ended_at: datetime,
        duration_ms: float,
    ) -> None:
        with Session(engine) as db:
            attempt = db.get(WorkflowStepAttempt, attempt_id)
            if not attempt:
                return
            attempt.status = status
            attempt.outputs = outputs
            attempt.error = error
            attempt.ended_at = ended_at
            attempt.duration_ms = duration_ms
            db.add(attempt)
            db.commit()

    # ------------------------------------------------------------------
    # 进程恢复
    # ------------------------------------------------------------------

    async def recover_running_instances(self) -> list[str]:
        """
        进程重启后恢复 running 实例。

        - skill 步骤：标 failed
        - task_session 步骤：检查子 TaskSession 状态后决定
        """
        recovered: list[str] = []
        with Session(engine) as db:
            instances = db.exec(
                select(WorkflowInstance).where(
                    WorkflowInstance.status == InstanceStatus.RUNNING.value
                )
            ).all()

        for inst in instances:
            step_runs = self._load_step_runs(inst.id)
            for sr in step_runs.values():
                if sr.status != StepRunStatus.RUNNING.value:
                    continue

                if sr.executor_type == StepExecutorType.SKILL.value:
                    # skill 步骤无法确定结果，标 failed
                    self._transition_step_run(sr.id, StepRunStatus.FAILED.value)
                    self._update_step_run_fields(
                        sr.id, error="Process recovered: skill step marked failed",
                        ended_at=_now()
                    )
                elif sr.executor_type == StepExecutorType.BROWSER_AUTOMATION.value:
                    # browser_automation 步骤无法确定结果，标 failed
                    self._transition_step_run(sr.id, StepRunStatus.FAILED.value)
                    self._update_step_run_fields(
                        sr.id, error="Process recovered: browser_automation step marked failed",
                        ended_at=_now()
                    )
                elif sr.executor_type in (
                    StepExecutorType.NATIVE_ADAPTER.value,
                    StepExecutorType.ROUTED.value,
                ):
                    # native_adapter / routed 步骤无法确定结果，标 failed
                    self._transition_step_run(sr.id, StepRunStatus.FAILED.value)
                    self._update_step_run_fields(
                        sr.id, error=f"Process recovered: {sr.executor_type} step marked failed",
                        ended_at=_now()
                    )
                elif sr.executor_type == StepExecutorType.TASK_SESSION.value:
                    # 检查子 TaskSession 状态
                    self._recover_task_session_step(sr)

            # 重新进入执行循环
            version = self._load_version(inst.template_version_id)
            if version:
                steps, edges, global_policy = self._parse_version(
                    version, inst.params or {}
                )
                asyncio.create_task(
                    self._execution_loop(inst.id, steps, edges, global_policy)
                )
                recovered.append(inst.id)

        return recovered

    def _recover_task_session_step(self, sr: WorkflowStepRun) -> None:
        """恢复 task_session 类型步骤：检查子 TaskSession 状态。"""
        if not sr.child_task_session_id:
            self._transition_step_run(sr.id, StepRunStatus.FAILED.value)
            self._update_step_run_fields(
                sr.id, error="Process recovered: no child task session",
                ended_at=_now()
            )
            return

        from app.services.task_session_store import TaskSessionStore
        ts = TaskSessionStore.get(sr.child_task_session_id)
        if not ts:
            self._transition_step_run(sr.id, StepRunStatus.FAILED.value)
            self._update_step_run_fields(
                sr.id, error="Process recovered: child task session not found",
                ended_at=_now()
            )
            return

        if ts.status == "completed":
            self._transition_step_run(sr.id, StepRunStatus.SUCCESS.value)
            self._update_step_run_fields(sr.id, ended_at=_now())
        elif ts.status in ("failed", "cancelled"):
            self._transition_step_run(sr.id, StepRunStatus.FAILED.value)
            self._update_step_run_fields(
                sr.id, error=f"Child TaskSession {ts.status}", ended_at=_now()
            )
        else:
            # running/paused → 保守标 failed
            self._transition_step_run(sr.id, StepRunStatus.FAILED.value)
            self._update_step_run_fields(
                sr.id,
                error=f"Process recovered: child TaskSession in {ts.status}",
                ended_at=_now()
            )

    # ------------------------------------------------------------------
    # 事件流推送
    # ------------------------------------------------------------------

    @staticmethod
    async def _emit_workflow_event(event_type: str, data: dict[str, Any]) -> None:
        """通过 SocketManager 推送工作流事件到前端。"""
        try:
            from app.io.manager import SocketManager
            sm = SocketManager.get_instance()
            await sm.emit(event_type, data)
        except Exception as exc:
            logger.debug(f"[InstanceManager] Event emission failed: {exc}")
