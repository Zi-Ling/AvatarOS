"""
ReactPostExecutionMixin — post-node-execution logic for the ReAct loop.

Handles everything that happens AFTER runtime.execute_ready_nodes():
- Evolution step recording
- Long-task step persistence
- Narrative step.end / step.failed / artifact.created events
- Long-task routine checkpoints
- Execution cost budget check
- Circuit breaker (consecutive failure detection)
- TaskRuntimeState update
- DeliverableState tracking
- Progress guard
- Uncovered sub-goals check

Also handles the finally block:
- Lifecycle status computation
- Narrative task lifecycle events
- Session end
- Evolution pipeline finalization

Extracted from graph_controller._execute_react_mode.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.graph.controller.react_state import ReactLoopState

logger = logging.getLogger(__name__)


class ReactPostExecutionMixin:
    """Mixin providing post-execution logic for GraphController."""

    async def _record_evolution_steps(self, s: 'ReactLoopState') -> None:
        """Record completed/failed nodes to evolution trace."""
        if not self._evolution_pipeline or not s.evo_trace_id:
            return
        from app.avatar.runtime.graph.models.step_node import NodeStatus
        try:
            for _n in s.graph.nodes.values():
                if _n.status in (NodeStatus.SUCCESS, NodeStatus.FAILED):
                    _node_meta = _n.metadata or {}
                    if _node_meta.get("_evo_recorded"):
                        continue
                    _step_status = "success" if _n.status == NodeStatus.SUCCESS else "failed"
                    _step_output = _n.outputs if _n.status == NodeStatus.SUCCESS else None
                    _step_error = _n.error_message if _n.status == NodeStatus.FAILED else None
                    _step_duration = int(_node_meta.get("duration_ms", 0))
                    self._evolution_pipeline._trace_collector.record_step(
                        trace_id=s.evo_trace_id,
                        step_id=_n.id,
                        skill_name=_n.capability_name,
                        input_params=_n.params,
                        output=_step_output,
                        status=_step_status,
                        duration_ms=_step_duration,
                        error=_step_error,
                    )
                    _n.metadata = _node_meta
                    _n.metadata["_evo_recorded"] = True
        except Exception as _evo_step_err:
            logger.debug(f"[GraphController] Evolution step recording failed: {_evo_step_err}")

    async def _emit_step_narrative_events(self, s: 'ReactLoopState') -> None:
        """Emit narrative events for nodes that were pending this round."""
        from app.avatar.runtime.graph.models.step_node import NodeStatus
        from app.avatar.runtime.narrative.models import TranslationContext as _TC
        try:
            for _n in s.graph.nodes.values():
                if _n.id not in s.pending_node_ids:
                    continue
                if _n.status == NodeStatus.SUCCESS:
                    await s.narrative_manager.on_event(
                        "step.end",
                        step_id=str(_n.id),
                        context=_TC(
                            skill_name=_n.capability_name,
                            output_summary=self._summarize_output(_n),
                            semantic_label=self._get_semantic_label(_n),
                        ),
                    )
                    _oc = _n.metadata.get("output_contract") if _n.metadata else None
                    if _oc is not None:
                        _artifacts = _oc if isinstance(_oc, list) else [_oc]
                        for _art in _artifacts:
                            _art_dict = _art if isinstance(_art, dict) else (
                                getattr(_art, "__dict__", {}) if hasattr(_art, "__dict__") else {}
                            )
                            _art_path = _art_dict.get("path")
                            if _art_path:
                                _art_kind = _art_dict.get("kind", "file")
                                _art_label = _art_dict.get("semantic_label") or _art_path.rsplit("/", 1)[-1]
                                await s.narrative_manager.on_event(
                                    "artifact.created",
                                    step_id=str(_n.id),
                                    context=_TC(
                                        artifact_type=_art_kind,
                                        artifact_label=_art_label,
                                    ),
                                )
                elif _n.status == NodeStatus.FAILED:
                    await s.narrative_manager.on_event(
                        "step.failed",
                        step_id=str(_n.id),
                        context=_TC(
                            skill_name=_n.capability_name,
                            error_message=_n.error_message or "未知错误",
                            semantic_label=self._get_semantic_label(_n),
                        ),
                    )
                    if _n.can_retry():
                        await s.narrative_manager.on_event(
                            "retry.triggered",
                            step_id=str(_n.id),
                            context=_TC(
                                skill_name=_n.capability_name,
                                retry_count=_n.retry_count,
                                reason=_n.error_message or "执行失败",
                            ),
                        )
        except Exception as _ne:
            logger.debug(f"[GraphController] Narrative step events failed: {_ne}")

    def _check_circuit_breaker(self, s: 'ReactLoopState', result: Any) -> Optional[str]:
        """
        Check circuit breaker after node execution.

        Returns:
            "abort" — circuit breaker tripped, s.final_result set
            None    — no issue
        """
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        _this_round_has_new_success = any(
            nid in s.pending_node_ids and n.status == NodeStatus.SUCCESS
            for nid, n in s.graph.nodes.items()
        )
        if result.final_status in ("failed", "partial_success") and not _this_round_has_new_success:
            s.consecutive_failures += 1
            logger.info(
                f"[ReAct] Node(s) failed — "
                f"consecutive_failures={s.consecutive_failures}/{s.MAX_CONSECUTIVE_FAILURES}"
            )
            if s.consecutive_failures >= s.MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    f"[CircuitBreaker] {s.consecutive_failures} consecutive failures — "
                    f"force-terminating"
                )
                s.error_message = (
                    f"Circuit breaker: {s.consecutive_failures} consecutive failures"
                )
                s.final_result = self._make_error_result(s.graph, error_message=s.error_message)
                return "abort"
        elif _this_round_has_new_success:
            s.consecutive_failures = 0
        return None

    def _check_execution_cost(self, s: 'ReactLoopState') -> Optional[str]:
        """
        Check execution cost budget.

        Returns:
            "abort" — cost exceeded, s.final_result set
            None    — within budget
        """
        if not self.max_execution_cost:
            return None
        from app.avatar.runtime.graph.context.execution_context import ExecutionContext
        if not hasattr(s.graph, '_context'):
            s.graph._context = ExecutionContext(graph_id=s.graph.id)
        current_cost = self.runtime.get_execution_cost(s.graph, s.graph._context)
        if current_cost >= self.max_execution_cost:
            s.error_message = (
                f"Execution cost exceeded: ${current_cost:.4f} >= "
                f"${self.max_execution_cost:.4f}"
            )
            logger.error(f"[GraphController] {s.error_message}")
            from app.avatar.runtime.graph.models.execution_graph import GraphStatus
            s.graph.status = GraphStatus.FAILED
            s.final_result = self._make_error_result(s.graph, error_message=s.error_message)
            return "abort"
        return None

    def _update_task_runtime_state(self, s: 'ReactLoopState') -> None:
        """Update TaskRuntimeState with completed nodes."""
        if s.task_runtime_state is None:
            return
        from app.avatar.runtime.graph.models.step_node import NodeStatus
        try:
            from app.avatar.runtime.task.runtime_state import UpdateSource
            for _rn in s.graph.nodes.values():
                if _rn.status == NodeStatus.SUCCESS:
                    s.task_runtime_state.add_completed_item(
                        item_id=_rn.id,
                        description=f"{_rn.capability_name}: {(_rn.metadata or {}).get('description', 'completed')}",
                        update_source=UpdateSource.NODE_STATUS_AGGREGATION,
                    )
        except Exception as _trs_upd_err:
            logger.debug(f"[TaskRuntimeState] Update failed: {_trs_upd_err}")

    def _update_deliverable_states(self, s: 'ReactLoopState') -> None:
        """Track deliverable satisfaction from node outputs."""
        if not s.deliverables:
            return
        from app.avatar.runtime.graph.models.step_node import NodeStatus
        try:
            from app.avatar.runtime.verification.models import DeliverableState
            _del_states: Dict[str, Any] = s.env_context.get("deliverable_states", {})
            if not _del_states:
                for _d in s.deliverables:
                    _del_states[_d.id] = DeliverableState(deliverable_id=_d.id)
                s.env_context["deliverable_states"] = _del_states

            for _rn in s.graph.nodes.values():
                if _rn.status != NodeStatus.SUCCESS:
                    continue
                _node_outputs = _rn.outputs or {}
                _node_paths: List[str] = []
                for _ov in _node_outputs.values():
                    if isinstance(_ov, str) and "." in _ov:
                        _node_paths.append(_ov)
                    elif isinstance(_ov, dict):
                        _p = _ov.get("path") or _ov.get("file_path") or ""
                        if _p:
                            _node_paths.append(_p)
                    elif isinstance(_ov, list):
                        for _item in _ov:
                            if isinstance(_item, dict):
                                _p = _item.get("path") or _item.get("file_path") or ""
                                if _p:
                                    _node_paths.append(_p)

                for _d in s.deliverables:
                    _ds = _del_states.get(_d.id)
                    if _ds and _ds.status == "pending":
                        for _np in _node_paths:
                            if _np.lower().endswith(f".{_d.format.lower()}"):
                                _ds.status = "satisfied"
                                _ds.matched_path = _np
                                _ds.producing_step_id = str(_rn.id)
                                _ds.evidence = f"node:{_rn.id}:{_np}"
                                break
        except Exception as _ds_err:
            logger.debug(f"[DeliverableState] Update failed: {_ds_err}")

    def _check_uncovered_after_success(self, s: 'ReactLoopState', result: Any) -> Optional[str]:
        """
        After successful node execution, check if sub-goals remain uncovered.

        Returns:
            "continue" — uncovered goals found, hint injected
            None       — all covered or result wasn't success
        """
        if result.final_status != "success":
            return None
        uncovered = self._goal_tracker.get_uncovered_sub_goals(s.sub_goals, s.graph)
        if uncovered:
            logger.warning(
                f"[GoalTracker] Success but {len(uncovered)} uncovered: {uncovered}"
            )
            s.env_context = dict(s.env_context)
            s.env_context["uncovered_sub_goals"] = uncovered
            s.env_context["goal_tracker_hint"] = (
                f"The following sub-goals are NOT yet completed: {uncovered}. "
                f"You MUST complete them before finishing."
            )
            return "continue"
        logger.debug("[ReAct] Node(s) succeeded, continuing loop for Planner FINISH decision")
        return None
