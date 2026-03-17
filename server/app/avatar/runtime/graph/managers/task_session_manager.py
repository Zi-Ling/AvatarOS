# server/app/avatar/runtime/graph/managers/task_session_manager.py
"""
TaskSessionManager — 长任务生命周期的顶层编排者

协调 InterruptManager、ResumeManager、PlanMergeEngine、
CheckpointManager、DeliveryGate 等组件，管理 TaskSession 生命周期。
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from app.db.long_task_models import TaskSession

logger = logging.getLogger(__name__)


class TaskSessionManager:
    """长任务生命周期管理器。"""

    def __init__(
        self,
        task_session_store,
        task_scheduler,
        interrupt_manager,
        resume_manager,
        plan_merge_engine,
        checkpoint_manager,
        delivery_gate,
    ):
        self._task_session_store = task_session_store
        self._task_scheduler = task_scheduler
        self._interrupt_manager = interrupt_manager
        self._resume_manager = resume_manager
        self._plan_merge_engine = plan_merge_engine
        self._checkpoint_manager = checkpoint_manager
        self._delivery_gate = delivery_gate

    async def create_task_session(
        self, goal: str, config: Optional[dict] = None
    ) -> TaskSession:
        """创建新的长任务会话。"""
        config_json = json.dumps(config, ensure_ascii=False) if config else None
        session = self._task_session_store.create(
            goal=goal, config_json=config_json
        )
        logger.info(
            f"[TaskSessionManager] Created task session {session.id}: {goal}"
        )
        return session

    async def start_execution(self, task_session_id: str) -> dict:
        """
        启动执行：transition to planning → executing，入队调度。

        Returns execution context dict.
        """
        session = self._task_session_store.get(task_session_id)
        if session is None:
            raise ValueError(f"TaskSession {task_session_id} not found")

        # Transition: created → planning → executing
        if session.status == "created":
            self._task_session_store.transition(task_session_id, "planning")
            self._task_session_store.transition(task_session_id, "executing")
        elif session.status == "resuming":
            self._task_session_store.transition(task_session_id, "executing")
        else:
            self._task_session_store.transition(task_session_id, "executing")

        # Enqueue for scheduling
        await self._task_scheduler.enqueue(
            task_session_id=task_session_id,
            task_type="long_task",
            priority_class="user_explicit",
        )

        logger.info(
            f"[TaskSessionManager] Started execution for {task_session_id}"
        )
        return {
            "task_session_id": task_session_id,
            "status": "executing",
        }

    async def handle_pause(self, task_session_id: str) -> None:
        """处理暂停请求，委托给 InterruptManager。"""
        logger.info(f"[TaskSessionManager] Handling pause for {task_session_id}")
        await self._interrupt_manager.graceful_pause(task_session_id)

    async def handle_resume(self, task_session_id: str) -> None:
        """处理恢复请求，委托给 ResumeManager。"""
        logger.info(f"[TaskSessionManager] Handling resume for {task_session_id}")

        session = self._task_session_store.get(task_session_id)
        if session is None:
            raise ValueError(f"TaskSession {task_session_id} not found")

        # Transition to resuming
        self._task_session_store.transition(task_session_id, "resuming")

        try:
            resume_report = await self._resume_manager.resume(task_session_id)
            # Transition resuming → executing
            self._task_session_store.transition(task_session_id, "executing")
            logger.info(
                f"[TaskSessionManager] Resume completed for {task_session_id}, "
                f"runnable_set={resume_report.get('runnable_set', [])}"
            )
        except RuntimeError as e:
            # All checkpoints invalid → transition to failed
            logger.error(
                f"[TaskSessionManager] Resume failed for {task_session_id}: {e}"
            )
            self._task_session_store.transition(task_session_id, "failed")
            raise

    async def handle_change_request(
        self, task_session_id: str, change: str
    ) -> dict:
        """处理变更请求，委托给 PlanMergeEngine。"""
        logger.info(
            f"[TaskSessionManager] Handling change request for {task_session_id}"
        )

        # Parse the change request
        parsed = await self._plan_merge_engine.parse_change_request(change)

        # Attempt merge
        result = await self._plan_merge_engine.merge(task_session_id, parsed)

        logger.info(
            f"[TaskSessionManager] Change request result for {task_session_id}: "
            f"status={result.get('status')}"
        )
        return result

    async def handle_cancel(self, task_session_id: str) -> None:
        """取消任务。"""
        logger.info(f"[TaskSessionManager] Cancelling {task_session_id}")
        self._task_session_store.transition(task_session_id, "cancelled")
        await self._task_scheduler.release_slot(task_session_id)

    def _get_isolation_context(self, task_session_id: str) -> dict:
        """
        获取任务隔离上下文。

        每个 TaskSession 独立：
        - workspace 目录
        - Plan_Graph
        - Artifact 命名空间
        - event stream（不交叉）
        - task-local memory（不共享）
        """
        return {
            "workspace_prefix": f"task_{task_session_id}",
            "graph_namespace": task_session_id,
            "artifact_namespace": task_session_id,
            "event_stream_id": f"events_{task_session_id}",
            "memory_scope": f"memory_{task_session_id}",
        }

    async def finalize(self, task_session_id: str) -> dict:
        """
        通过 DeliveryGate 检查后生成交付包。

        对于 failed/cancelled：仍生成包含部分产物和原因的交付包。
        """
        session = self._task_session_store.get(task_session_id)
        if session is None:
            raise ValueError(f"TaskSession {task_session_id} not found")

        terminal_status = session.status

        if terminal_status not in ("completed", "failed", "cancelled"):
            # Run delivery gate evaluation
            gate_result = await self._delivery_gate.evaluate(task_session_id)

            if gate_result["passed"]:
                self._task_session_store.transition(task_session_id, "completed")
                terminal_status = "completed"
            else:
                logger.warning(
                    f"[TaskSessionManager] Delivery gate failed for "
                    f"{task_session_id}: {gate_result['reasons']}"
                )
                # Don't transition — return gate result for caller to decide
                return {
                    "task_session_id": task_session_id,
                    "delivery_gate": gate_result,
                    "package": None,
                }

        # Generate delivery package (works for all terminal statuses)
        package = await self._delivery_gate.generate_delivery_package(
            task_session_id, terminal_status
        )

        # Release scheduler slot
        await self._task_scheduler.release_slot(task_session_id)

        logger.info(
            f"[TaskSessionManager] Finalized {task_session_id} "
            f"with status={terminal_status}"
        )
        return {
            "task_session_id": task_session_id,
            "terminal_status": terminal_status,
            "package": package,
        }
