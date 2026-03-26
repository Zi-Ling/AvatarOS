"""
DAGExecutorMixin – one-shot DAG planning and execution extracted from
GraphController.

Mixed back into GraphController via multiple inheritance.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, TYPE_CHECKING
import logging

from app.avatar.runtime.graph.controller.synthesis.dag_repair import DagRepairHelper

if TYPE_CHECKING:
    from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult

logger = logging.getLogger(__name__)


class DAGExecutorMixin:
    """DAG (one-shot) execution mode for GraphController."""

    async def _execute_dag_mode(
        self,
        intent: str,
        env_context: Dict[str, Any],
        config: Dict[str, Any],
    ) -> 'ExecutionResult':
        """Execute in DAG mode (one-shot planning with auto-repair)."""
        from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
        from app.avatar.runtime.graph.lifecycle.execution_lifecycle import ExecutionLifecycle
        from app.services.session_store import ExecutionSessionStore

        max_planning_attempts = 3
        planning_attempt = 0

        _evo_trace_id: Optional[str] = None
        _session_id = env_context.get("session_id", "")

        # ── Create execution session + lifecycle (same as ReAct mode) ───
        _lifecycle: Optional[ExecutionLifecycle] = None
        try:
            _workspace_path = env_context.get("workspace_path") or (
                str(self.guard.config.workspace_root)
                if self.guard and self.guard.config.workspace_root else ""
            )
            _exec_session = ExecutionSessionStore.create(
                goal=intent,
                run_id=env_context.get("run_id"),
                task_id=env_context.get("task_id"),
                request_id=env_context.get("request_id"),
                trace_id=env_context.get("trace_id"),
                conversation_id=_session_id,
                workspace_path=_workspace_path,
            )
            _lifecycle = ExecutionLifecycle(_exec_session.id)
            await _lifecycle.on_session_start()
        except Exception as _lc_err:
            logger.warning(f"[GraphController] DAG lifecycle setup failed: {_lc_err}")

        if self._evolution_pipeline:
            try:
                _evo_trace = self._evolution_pipeline._trace_collector.create_trace(
                    task_id=env_context.get("task_id", "dag-unknown"),
                    session_id=_session_id,
                    goal=intent,
                    task_type=env_context.get("task_type", "dag"),
                )
                _evo_trace_id = _evo_trace.trace_id
            except Exception as _evo_err:
                logger.debug(f"[GraphController] DAG evolution trace creation failed: {_evo_err}")

        _final_result: Optional['ExecutionResult'] = None
        try:
            while planning_attempt < max_planning_attempts:
                planning_attempt += 1
                logger.info(f"Planning complete graph (DAG mode, attempt {planning_attempt}/{max_planning_attempts})")
                patch = await self.planner.plan_complete_graph(intent, env_context)

                repair_result = DagRepairHelper.auto_repair_dag(patch)
                if repair_result['repaired']:
                    logger.info(f"Auto-repaired DAG: {repair_result['repairs']}")
                    patch = repair_result['patch']

                if self.guard:
                    _empty_graph = ExecutionGraph(goal=intent, nodes={}, edges={})
                    validation = await self.guard.validate(patch, _empty_graph, context=env_context)
                    if not validation.approved:
                        logger.error(f"Patch validation failed: {validation.violations}")
                        if planning_attempt < max_planning_attempts:
                            logger.warning(f"Requesting new plan (attempt {planning_attempt + 1})")
                            continue
                        from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                        graph = ExecutionGraph(goal=intent, nodes={}, edges={})
                        graph.status = GraphStatus.FAILED
                        _final_result = self._make_error_result(
                            graph,
                            error_message=f"Validation failed after {max_planning_attempts} attempts: {validation.violations}"
                        )
                        return _final_result

                graph = ExecutionGraph(goal=intent, nodes={}, edges={})
                self._apply_patch(patch, graph)
                _final_result = await self.runtime.execute_graph(graph)
                return _final_result

            logger.error(f"Failed to plan valid DAG after {max_planning_attempts} attempts")
            from app.avatar.runtime.graph.models.execution_graph import GraphStatus
            graph = ExecutionGraph(goal=intent, nodes={}, edges={})
            graph.status = GraphStatus.FAILED
            _final_result = self._make_error_result(
                graph, error_message=f"Failed to plan valid DAG after {max_planning_attempts} attempts"
            )
            return _final_result
        finally:
            # ── Emit task.completed via EventBus ────────────────────────
            if _final_result and _final_result.graph and _final_result.graph.nodes:
                self._emit_task_completed(_final_result.graph, env_context)

            # ── Session lifecycle: transition to terminal state ──────────
            if _lifecycle is not None and _final_result is not None:
                from app.avatar.runtime.graph.models.step_node import NodeStatus as _DagNS
                _dag_graph = _final_result.graph
                _fs = _final_result.final_status
                if _fs == "success":
                    _lc_status, _rs = "completed", "success"
                elif _fs == "partial_success":
                    _lc_status, _rs = "completed", "partial_success"
                else:
                    _lc_status, _rs = "failed", "failed"
                _err_msg = _final_result.error_message if hasattr(_final_result, 'error_message') else None
                try:
                    # Ensure session is in 'running' before transitioning to terminal
                    await _lifecycle.on_execution_started()
                    await _lifecycle.on_session_end(
                        lifecycle_status=_lc_status,
                        result_status=_rs,
                        total_nodes=len(_dag_graph.nodes) if _dag_graph else 0,
                        completed_nodes=sum(
                            1 for n in _dag_graph.nodes.values() if n.status == _DagNS.SUCCESS
                        ) if _dag_graph and _dag_graph.nodes else 0,
                        failed_nodes=sum(
                            1 for n in _dag_graph.nodes.values() if n.status == _DagNS.FAILED
                        ) if _dag_graph and _dag_graph.nodes else 0,
                        error_message=_err_msg,
                    )
                except Exception as _lc_end_err:
                    logger.warning(f"[GraphController] DAG on_session_end failed: {_lc_end_err}")

            # ── Evolution pipeline ──────────────────────────────────────
            if self._evolution_pipeline and _evo_trace_id and _final_result:
                try:
                    from app.avatar.evolution.outcome_classifier import SubGoalResult
                    _evo_decision = f"dag_mode, final_status={_final_result.final_status}"
                    await self._evolution_pipeline.on_task_finished_v2(
                        task_id=env_context.get("task_id", "dag-unknown"),
                        session_id=_session_id,
                        goal=intent,
                        task_type=env_context.get("task_type", "dag"),
                        sub_goals=[SubGoalResult(name=intent, satisfied=_final_result.success)],
                        decision_basis=_evo_decision,
                    )
                except Exception as _evo_err:
                    logger.debug(f"[GraphController] DAG evolution pipeline failed (non-blocking): {_evo_err}")
