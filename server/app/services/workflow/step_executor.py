"""
步骤执行器：StepExecutor 抽象 + Skill/TaskSession 实现。

包含：
- StepRunResult: 步骤执行结果
- StepExecutor ABC: 统一执行接口
- OutputContractValidator: 输出契约校验
- CompletionWaiter ABC + PollingCompletionWaiter: TaskSession 完成等待
- SkillStepExecutor: 直接调用 Skill
- TaskSessionStepExecutor: 委托 TaskSession
"""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from app.services.workflow.models import StepOutputDef, WorkflowStepDef

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 执行结果
# ---------------------------------------------------------------------------

@dataclass
class StepRunResult:
    """步骤执行的标准化结果。"""
    success: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: float = 0.0
    child_task_session_id: Optional[str] = None


# ---------------------------------------------------------------------------
# 输出契约校验器
# ---------------------------------------------------------------------------

class OutputContractValidator:
    """
    校验步骤输出是否符合 step_def.outputs 声明的契约。

    规则：
    1. required=True 的 key 必须存在于 outputs 中
    2. 每个 output 的值类型必须匹配声明的 type
    3. 不合格 → 将 result 转为 failure，阻止脏数据传给下游
    """

    # 类型名 → Python 类型集合的映射
    _TYPE_MAP: dict[str, tuple[type, ...]] = {
        "string": (str,),
        "number": (int, float),
        "boolean": (bool,),
        "json": (dict, list),
        "file_path": (str,),
        "binary": (bytes, str),
    }

    def validate(
        self, step_def: WorkflowStepDef, result: StepRunResult
    ) -> StepRunResult:
        """校验输出契约，不合格则将 result 转为 failure。"""
        if not result.success:
            return result  # 已经失败，不再校验

        errors: list[str] = []
        for out_def in step_def.outputs:
            self._check_output(out_def, result.outputs, errors)

        if errors:
            msg = f"Output contract violation: {'; '.join(errors)}"
            logger.warning(f"[OutputContractValidator] {msg}")
            return StepRunResult(
                success=False,
                outputs=result.outputs,
                error=msg,
                duration_ms=result.duration_ms,
                child_task_session_id=result.child_task_session_id,
            )
        return result

    def _check_output(
        self,
        out_def: StepOutputDef,
        outputs: dict[str, Any],
        errors: list[str],
    ) -> None:
        """检查单个输出字段。"""
        if out_def.key not in outputs:
            if out_def.required:
                errors.append(f"missing required key '{out_def.key}'")
            return

        value = outputs[out_def.key]
        if value is None:
            if out_def.required:
                errors.append(f"key '{out_def.key}' is None but required")
            return

        expected_types = self._TYPE_MAP.get(out_def.type)
        if expected_types and not isinstance(value, expected_types):
            errors.append(
                f"key '{out_def.key}' type mismatch: "
                f"expected {out_def.type}, got {type(value).__name__}"
            )


# ---------------------------------------------------------------------------
# StepExecutor ABC
# ---------------------------------------------------------------------------

class StepExecutor(ABC):
    """步骤执行抽象接口。子类实现具体的执行逻辑。"""

    @abstractmethod
    async def execute(
        self,
        step_def: WorkflowStepDef,
        resolved_inputs: dict[str, Any],
        instance_id: str,
    ) -> StepRunResult:
        """执行步骤，返回标准化结果。"""


# ---------------------------------------------------------------------------
# CompletionWaiter ABC + 轮询实现
# ---------------------------------------------------------------------------

class CompletionWaiter(ABC):
    """TaskSession 完成等待抽象，支持轮询和事件驱动两种实现。"""

    @abstractmethod
    async def wait_for_completion(
        self, task_session_id: str, timeout: float
    ) -> str:
        """等待 TaskSession 进入终态，返回最终 status。"""


class PollingCompletionWaiter(CompletionWaiter):
    """轮询 TaskSession 状态直到终态（第一期默认实现）。"""

    _TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

    def __init__(self, task_session_store, poll_interval: float = 2.0):
        self._store = task_session_store
        self._poll_interval = poll_interval

    async def wait_for_completion(
        self, task_session_id: str, timeout: float
    ) -> str:
        deadline = time.monotonic() + timeout
        while True:
            ts = self._store.get(task_session_id)
            if ts and ts.status in self._TERMINAL_STATUSES:
                return ts.status
            if time.monotonic() >= deadline:
                return "timeout"
            await asyncio.sleep(self._poll_interval)


# ---------------------------------------------------------------------------
# SkillStepExecutor
# ---------------------------------------------------------------------------

class SkillStepExecutor(StepExecutor):
    """
    直接调用 Skill 执行步骤。

    流程：
    1. 从 SkillRegistry 获取 skill 实例
    2. 构造 SkillInput（从 resolved_inputs）
    3. 调用 skill.run(context, params)
    4. 从 SkillOutput 提取 outputs（按 step_def.outputs 声明的 key）
    5. OutputContractValidator 校验
    6. 返回 StepRunResult
    """

    def __init__(self, skill_registry, output_validator: OutputContractValidator):
        self._registry = skill_registry
        self._validator = output_validator

    async def execute(
        self,
        step_def: WorkflowStepDef,
        resolved_inputs: dict[str, Any],
        instance_id: str,
    ) -> StepRunResult:
        start = time.monotonic()
        try:
            # 1. 获取 skill 实例
            skill = self._registry.get_instance(step_def.capability_name)

            # 2. 构造 SkillInput
            input_model = skill.spec.input_model
            params = input_model(**resolved_inputs)

            # 3. 构造最小 SkillContext
            from app.avatar.skills.context import SkillContext
            ctx = SkillContext()

            # 4. 执行
            output = await skill.run(ctx, params)

            # 5. 提取 outputs
            raw = output.model_dump() if hasattr(output, "model_dump") else {}
            outputs = self._extract_outputs(step_def, raw)

            duration = (time.monotonic() - start) * 1000
            result = StepRunResult(
                success=output.success if hasattr(output, "success") else True,
                outputs=outputs,
                error=None if (hasattr(output, "success") and output.success) else getattr(output, "message", None),
                duration_ms=duration,
            )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            logger.exception(f"[SkillStepExecutor] step={step_def.step_id} failed")
            result = StepRunResult(
                success=False, outputs={}, error=str(exc), duration_ms=duration
            )

        return self._validator.validate(step_def, result)

    @staticmethod
    def _extract_outputs(
        step_def: WorkflowStepDef, raw: dict[str, Any]
    ) -> dict[str, Any]:
        """按 step_def.outputs 声明的 key 从 skill 原始输出中提取。"""
        declared_keys = {o.key for o in step_def.outputs}
        return {k: v for k, v in raw.items() if k in declared_keys}


# ---------------------------------------------------------------------------
# TaskSessionStepExecutor
# ---------------------------------------------------------------------------

class TaskSessionStepExecutor(StepExecutor):
    """
    委托给 TaskSession 执行步骤。

    流程：
    1. 创建子 TaskSession（goal = step_def.goal）
    2. 启动 TaskSession 执行（通过 avatar_runtime）
    3. 通过 CompletionWaiter 等待终态
    4. 从 TaskSession 收集输出
    5. OutputContractValidator 校验
    6. 返回 StepRunResult（含 child_task_session_id）
    """

    def __init__(
        self,
        task_session_store,
        avatar_runtime,
        completion_waiter: CompletionWaiter,
        output_validator: OutputContractValidator,
    ):
        self._store = task_session_store
        self._runtime = avatar_runtime
        self._waiter = completion_waiter
        self._validator = output_validator

    async def execute(
        self,
        step_def: WorkflowStepDef,
        resolved_inputs: dict[str, Any],
        instance_id: str,
    ) -> StepRunResult:
        start = time.monotonic()
        child_id: Optional[str] = None
        try:
            # 1. 创建子 TaskSession
            goal = step_def.goal or ""
            if resolved_inputs:
                # 将输入参数附加到 goal 的 config 中
                import json as _json
                config = _json.dumps({"workflow_inputs": resolved_inputs})
            else:
                config = None

            ts = self._store.create(goal=goal, config_json=config)
            child_id = ts.id

            # 2. 启动执行（fire-and-forget，runtime 异步处理）
            if hasattr(self._runtime, "start_task_session"):
                await self._runtime.start_task_session(ts.id)
            elif hasattr(self._runtime, "run_task"):
                await self._runtime.run_task(ts.id)

            # 3. 等待终态
            final_status = await self._waiter.wait_for_completion(
                ts.id, timeout=step_def.timeout_seconds
            )

            # 4. 收集输出
            duration = (time.monotonic() - start) * 1000
            if final_status == "completed":
                outputs = self._collect_outputs(ts.id, step_def)
                result = StepRunResult(
                    success=True,
                    outputs=outputs,
                    duration_ms=duration,
                    child_task_session_id=child_id,
                )
            elif final_status == "timeout":
                result = StepRunResult(
                    success=False,
                    outputs={},
                    error=f"TaskSession {child_id} timed out after {step_def.timeout_seconds}s",
                    duration_ms=duration,
                    child_task_session_id=child_id,
                )
            else:
                result = StepRunResult(
                    success=False,
                    outputs={},
                    error=f"TaskSession {child_id} ended with status: {final_status}",
                    duration_ms=duration,
                    child_task_session_id=child_id,
                )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            logger.exception(f"[TaskSessionStepExecutor] step={step_def.step_id} failed")
            result = StepRunResult(
                success=False,
                outputs={},
                error=str(exc),
                duration_ms=duration,
                child_task_session_id=child_id,
            )

        return self._validator.validate(step_def, result)

    def _collect_outputs(
        self, task_session_id: str, step_def: WorkflowStepDef
    ) -> dict[str, Any]:
        """从已完成的 TaskSession 收集输出，按 step_def.outputs 声明的 key 提取。"""
        ts = self._store.get(task_session_id)
        if not ts:
            return {}

        # TaskSession 的产物存储在 result_json 或 artifacts 中
        raw: dict[str, Any] = {}
        if hasattr(ts, "result_json") and ts.result_json:
            import json as _json
            try:
                raw = _json.loads(ts.result_json) if isinstance(ts.result_json, str) else ts.result_json
            except (ValueError, TypeError):
                pass

        declared_keys = {o.key for o in step_def.outputs}
        return {k: v for k, v in raw.items() if k in declared_keys}
