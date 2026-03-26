# server/app/avatar/runtime/graph/managers/delivery_gate.py
"""
DeliveryGate — 交付门禁

综合检查：goal coverage + artifact completeness + blocker count。
从 Artifact Graph 筛出可交付产物，生成交付包。
failed/cancelled 时仍生成包含部分产物和未完成原因的交付包。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class DeliveryGate:
    """交付门禁。"""

    def __init__(self, artifact_dep_graph, step_state_store, event_stream=None):
        self._artifact_dep_graph = artifact_dep_graph
        self._step_state_store = step_state_store
        self._event_stream = event_stream

    async def evaluate(self, task_session_id: str) -> dict:
        """
        综合检查：goal coverage + artifact completeness + blocker count。
        Supports both step-level (ReAct) and subtask-level (multi-agent) evaluation.

        Returns:
            {"passed": bool, "reasons": list[str]}
        """
        reasons = []
        step_states = self._step_state_store.get_by_task_session(task_session_id)

        # ── Multi-agent subtask evaluation ──────────────────────────────
        # If a SubtaskGraph snapshot exists, also verify subtask-level outputs.
        try:
            from app.avatar.runtime.multiagent.persistence.graph_persistence import load_subtask_graph
            snapshot = load_subtask_graph(task_session_id)
            if snapshot and snapshot["graph"].nodes:
                graph = snapshot["graph"]
                subtask_total = len(graph.nodes)
                subtask_completed = sum(
                    1 for n in graph.nodes.values() if n.status == "completed"
                )
                subtask_failed = sum(
                    1 for n in graph.nodes.values() if n.status == "failed"
                )
                if subtask_failed > 0:
                    reasons.append(
                        f"Multi-agent: {subtask_failed}/{subtask_total} subtask(s) failed"
                    )
                if subtask_completed < subtask_total and subtask_failed == 0:
                    pending = subtask_total - subtask_completed
                    reasons.append(
                        f"Multi-agent: {pending}/{subtask_total} subtask(s) not completed"
                    )
                # Verify subtask results have expected outputs
                results = snapshot.get("results", {})
                for nid, node in graph.nodes.items():
                    if node.status == "completed" and node.output_contract:
                        expected_type = node.output_contract.get("type")
                        if expected_type == "artifact":
                            node_result = results.get(nid, {})
                            if not node_result.get("artifact_paths"):
                                reasons.append(
                                    f"Subtask {nid}: expected artifact output but none produced"
                                )
        except Exception as _ma_err:
            logger.debug("[DeliveryGate] Multi-agent evaluation skipped: %s", _ma_err)

        if not step_states:
            # If no step states but multi-agent reasons exist, use those
            if reasons:
                return {"passed": False, "reasons": reasons}
            reasons.append("No steps found for task session")
            return {"passed": False, "reasons": reasons}

        # Goal coverage: check that all steps are in terminal states
        total = len(step_states)
        completed = sum(1 for s in step_states if s.status == "success")
        failed = sum(1 for s in step_states if s.status == "failed")
        stale = sum(1 for s in step_states if s.status == "stale")
        blocked = sum(1 for s in step_states if s.status == "blocked")

        # Blocker count: failed + blocked steps
        blocker_count = failed + blocked
        if blocker_count > 0:
            reasons.append(
                f"{blocker_count} blocker(s): {failed} failed, {blocked} blocked"
            )

        # Stale artifacts check
        if stale > 0:
            reasons.append(f"{stale} step(s) are stale")

        # Artifact completeness: check deliverable artifacts
        deliverables = self._artifact_dep_graph.get_deliverable_artifacts(
            task_session_id
        )

        # Goal coverage ratio
        if total > 0:
            coverage = completed / total
            if coverage < 1.0:
                non_complete = total - completed
                reasons.append(
                    f"Goal coverage {coverage:.0%}: "
                    f"{non_complete} step(s) not completed"
                )

        passed = len(reasons) == 0

        logger.info(
            f"[DeliveryGate] Evaluation for {task_session_id}: "
            f"passed={passed}, reasons={reasons}"
        )

        if self._event_stream:
            try:
                self._event_stream.emit("delivery_gate_result", {
                    "passed": passed,
                    "reasons": reasons,
                    "completed": completed,
                    "total": total,
                })
            except Exception as e:
                logger.debug(f"[DeliveryGate] Event emission failed: {e}")

        return {"passed": passed, "reasons": reasons}

    async def generate_delivery_package(
        self, task_session_id: str, terminal_status: str = "completed"
    ) -> dict:
        """
        生成交付包。

        对于 failed/cancelled：包含部分产物 + 未完成原因。
        """
        step_states = self._step_state_store.get_by_task_session(task_session_id)
        deliverables = self._artifact_dep_graph.get_deliverable_artifacts(
            task_session_id
        )

        completed_steps = [s for s in step_states if s.status == "success"]
        incomplete_steps = [
            s for s in step_states
            if s.status not in ("success", "skipped", "cancelled")
        ]

        # Build incomplete reasons
        incomplete_items = []
        for step in incomplete_steps:
            incomplete_items.append({
                "step_id": step.id,
                "capability": step.capability_name,
                "status": step.status,
                "reason": step.error_message or f"Step is {step.status}",
            })

        package = {
            "task_session_id": task_session_id,
            "terminal_status": terminal_status,
            "deliverable_artifact_ids": deliverables,
            "completed_step_count": len(completed_steps),
            "total_step_count": len(step_states),
            "incomplete_items": incomplete_items,
        }

        if terminal_status in ("failed", "cancelled"):
            package["partial"] = True
            package["termination_reason"] = (
                f"Task {terminal_status}. "
                f"{len(incomplete_items)} step(s) not completed."
            )
        else:
            package["partial"] = False

        logger.info(
            f"[DeliveryGate] Generated delivery package for {task_session_id}: "
            f"status={terminal_status}, artifacts={len(deliverables)}, "
            f"completed={len(completed_steps)}/{len(step_states)}"
        )
        return package
