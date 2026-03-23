# app/avatar/runtime/graph/lifecycle/execution_lifecycle.py
"""
ExecutionLifecycle — 执行生命周期协调层

职责：
- 统一处理 session create/transition/snapshot/trace
- controller 只调这层，不直接碰 SessionStore 和 StepTraceStore
- 接口层 async，内部存储层当前同步（SQLite/SQLModel）

controller 发出的领域事件：
  on_session_start()       — ReAct 循环开始前
  on_plan_generated()      — 每次 planner 产出有效 plan 后
  on_policy_evaluated()    — guard validate 后
  on_execution_started()   — 第一个节点开始执行时（planned -> running）
  on_node_completed()      — 节点成功（原子增量统计）
  on_node_failed()         — 节点失败（原子增量统计）
  on_session_end()         — 所有出口统一收口
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ExecutionLifecycle:
    """
    执行生命周期协调层。

    每次 ReAct 执行创建一个实例，持有 session_id 和 trace_store 引用。
    所有方法 async，内部调用同步 store（后续可无缝升级为 async DB）。
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._planner_invocation_index = 0
        self._execution_started = False  # 是否已 transition 到 running

        from app.avatar.runtime.graph.storage.step_trace_store import get_step_trace_store
        self._trace = get_step_trace_store()

    # ------------------------------------------------------------------
    # Session 启动（created -> planned 在首个有效 plan 后触发）
    # ------------------------------------------------------------------

    async def on_session_start(self) -> None:
        """session 创建后立即调用，记录 session_created 事件。"""
        try:
            self._trace.record_session_event(
                session_id=self.session_id,
                event_type="session_created",
                payload={"session_id": self.session_id},
            )
        except Exception as e:
            logger.warning(f"[Lifecycle] on_session_start trace failed: {e}")

    # ------------------------------------------------------------------
    # Planner 产出有效 plan（首次触发 created/running -> planned）
    # ------------------------------------------------------------------

    async def on_plan_generated(
        self,
        planner_input: Any,
        planner_output: Any,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        latency_ms: Optional[int] = None,
    ) -> None:
        """
        每次 planner 产出有效 plan 后调用。
        首次调用时触发 created -> planned 状态转换。
        """
        from app.services.session_store import ExecutionSessionStore, InvalidTransitionError

        self._planner_invocation_index += 1

        # 首次 plan：created -> planned
        if self._planner_invocation_index == 1:
            try:
                ExecutionSessionStore.transition(self.session_id, "planned")
            except InvalidTransitionError as e:
                logger.warning(f"[Lifecycle] planned transition failed: {e}")

        # 写 PlannerInvocation 记录
        try:
            ExecutionSessionStore.record_planner_invocation(
                session_id=self.session_id,
                invocation_index=self._planner_invocation_index,
                planner_input=planner_input,
                planner_output=planner_output,
                tokens_used=tokens_used,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
            )
        except Exception as e:
            logger.warning(f"[Lifecycle] record_planner_invocation failed: {e}")

        # trace event
        try:
            self._trace.record_session_event(
                session_id=self.session_id,
                event_type="plan_generated",
                payload={
                    "invocation_index": self._planner_invocation_index,
                    "tokens_used": tokens_used,
                    "cost_usd": cost_usd,
                    "actions_count": (
                        len(planner_output.get("actions", []))
                        if isinstance(planner_output, dict) and isinstance(planner_output.get("actions"), (list, tuple, str))
                        else 0
                    ),
                },
            )
        except Exception as e:
            logger.warning(f"[Lifecycle] plan_generated trace failed: {e}")

    # ------------------------------------------------------------------
    # Policy 评估结果
    # ------------------------------------------------------------------

    async def on_policy_evaluated(
        self,
        approved: bool,
        violations: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
        requires_approval: Optional[List[str]] = None,
    ) -> None:
        """guard validate 后调用，记录完整 policy decision。"""
        try:
            self._trace.record_session_event(
                session_id=self.session_id,
                event_type="policy_decision",
                payload={
                    "approved": approved,
                    "violations": violations or [],
                    "warnings": warnings or [],
                    "requires_approval": requires_approval or [],
                },
            )
        except Exception as e:
            logger.warning(f"[Lifecycle] on_policy_evaluated trace failed: {e}")

    # ------------------------------------------------------------------
    # 第一个节点开始执行（planned -> running）
    # ------------------------------------------------------------------

    async def on_execution_started(self) -> None:
        """第一个节点开始执行时调用，触发 planned -> running。"""
        if self._execution_started:
            return
        self._execution_started = True

        from app.services.session_store import ExecutionSessionStore, InvalidTransitionError
        try:
            ExecutionSessionStore.transition(self.session_id, "running")
            self._trace.record_session_event(
                session_id=self.session_id,
                event_type="session_running",
                payload={},
            )
        except InvalidTransitionError as e:
            logger.warning(f"[Lifecycle] running transition failed: {e}")

    # ------------------------------------------------------------------
    # 节点完成/失败（原子增量统计）
    # ------------------------------------------------------------------

    async def on_node_completed(self, node_id: str, step_type: Optional[str] = None) -> None:
        try:
            from app.services.session_store import ExecutionSessionStore
            ExecutionSessionStore.increment_node_stat(self.session_id, "completed_nodes")
        except Exception as e:
            logger.warning(f"[Lifecycle] on_node_completed stat failed: {e}")

    async def on_node_failed(self, node_id: str, error: Optional[str] = None) -> None:
        try:
            from app.services.session_store import ExecutionSessionStore
            ExecutionSessionStore.increment_node_stat(self.session_id, "failed_nodes")
        except Exception as e:
            logger.warning(f"[Lifecycle] on_node_failed stat failed: {e}")

    # ------------------------------------------------------------------
    # 统一出口
    # ------------------------------------------------------------------

    async def on_session_end(
        self,
        lifecycle_status: str,
        result_status: str,
        total_nodes: int = 0,
        completed_nodes: int = 0,
        failed_nodes: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        """
        所有出口统一收口。

        lifecycle_status: completed / failed / cancelled
        result_status:    success / partial_success / failed / unknown / cancelled
        """
        from app.services.session_store import ExecutionSessionStore, InvalidTransitionError

        # 最终 reconcile 节点统计
        try:
            ExecutionSessionStore.reconcile_node_stats(
                self.session_id,
                total_nodes=total_nodes,
                completed_nodes=completed_nodes,
                failed_nodes=failed_nodes,
            )
        except Exception as e:
            logger.warning(f"[Lifecycle] reconcile_node_stats failed: {e}")

        # lifecycle transition
        try:
            kwargs: Dict[str, Any] = {"result_status": result_status}
            if error_message:
                kwargs["error_message"] = error_message
            ExecutionSessionStore.transition(self.session_id, lifecycle_status, **kwargs)
        except InvalidTransitionError as e:
            logger.warning(f"[Lifecycle] on_session_end transition failed: {e}")

        # trace event
        event_type = f"session_{lifecycle_status}"  # session_completed / session_failed / session_cancelled
        try:
            self._trace.record_session_event(
                session_id=self.session_id,
                event_type=event_type,
                payload={
                    "lifecycle_status": lifecycle_status,
                    "result_status": result_status,
                    "total_nodes": total_nodes,
                    "completed_nodes": completed_nodes,
                    "failed_nodes": failed_nodes,
                    "error_message": error_message,
                },
            )
        except Exception as e:
            logger.warning(f"[Lifecycle] {event_type} trace failed: {e}")
