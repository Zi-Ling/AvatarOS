"""
DagRepairHelper — Auto-repair for DAG patches and planner repair invocation.

Extracted from GraphController.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.models.graph_patch import GraphPatch
    from app.avatar.runtime.graph.planner.graph_planner import GraphPlanner

logger = logging.getLogger(__name__)


class DagRepairHelper:
    """
    Auto-repair simple errors in DAG patches and invoke planner for recovery.
    """

    @staticmethod
    def auto_repair_dag(patch: 'GraphPatch') -> Dict[str, Any]:
        """
        Auto-repair simple errors in a DAG patch.

        Fixes:
        - Duplicate node IDs (rename duplicates)
        - Invalid field references (remove invalid edges)
        - Missing edges (log only)

        Returns dict with keys: repaired (bool), repairs (list), patch (GraphPatch).
        """
        from app.avatar.runtime.graph.models.graph_patch import PatchOperation, GraphPatch as GP

        repairs: List[str] = []
        repaired = False
        node_ids: set = set()
        node_id_counter: Dict[str, int] = {}
        node_outputs: Dict[str, List[str]] = {}
        new_actions = []

        for action in patch.actions:
            if action.operation == PatchOperation.ADD_NODE and action.node:
                original_id = action.node.id
                if original_id in node_ids:
                    if original_id not in node_id_counter:
                        node_id_counter[original_id] = 1
                    node_id_counter[original_id] += 1
                    new_id = f"{original_id}_{node_id_counter[original_id]}"
                    action.node.id = new_id
                    repairs.append(f"Renamed duplicate node '{original_id}' to '{new_id}'")
                    repaired = True
                node_ids.add(action.node.id)
                node_outputs[action.node.id] = ['output']
                new_actions.append(action)

            elif action.operation == PatchOperation.ADD_EDGE and action.edge:
                src = action.edge.source_node
                tgt = action.edge.target_node
                sf = action.edge.source_field

                if src not in node_ids:
                    repairs.append(f"Removed edge with invalid source '{src}' (target: {tgt})")
                    repaired = True
                    continue
                if tgt not in node_ids:
                    repairs.append(f"Removed edge with invalid target '{tgt}' (source: {src})")
                    repaired = True
                    continue
                if sf not in node_outputs.get(src, []):
                    if 'output' in node_outputs.get(src, []):
                        action.edge.source_field = 'output'
                        repairs.append(f"Fixed field '{sf}' to 'output' for {src} → {tgt}")
                        repaired = True
                    else:
                        repairs.append(f"Removed edge with invalid field '{sf}' from '{src}'")
                        repaired = True
                        continue
                new_actions.append(action)
            else:
                new_actions.append(action)

        if repaired:
            logger.info(f"[DagRepair] {len(repairs)} repairs made")
            for r in repairs:
                logger.debug(f"  - {r}")

        repaired_patch = GP(
            actions=new_actions,
            reasoning=patch.reasoning,
            metadata=patch.metadata,
        )
        return {'repaired': repaired, 'repairs': repairs, 'patch': repaired_patch}

    @staticmethod
    async def invoke_planner_for_repair(
        planner: 'GraphPlanner',
        graph: 'ExecutionGraph',
        failed_node_id: str,
        error_message: str,
        env_context: Dict[str, Any],
        recovery_attempts: Dict[str, int],
    ) -> Optional['GraphPatch']:
        """
        Invoke planner for error recovery with attempt tracking.
        Returns recovery patch or None if limit exceeded.
        """
        current = recovery_attempts.get(failed_node_id, 0)
        max_attempts = 3
        if current >= max_attempts:
            logger.error(
                f"Recovery limit exceeded for {failed_node_id}: {current} >= {max_attempts}"
            )
            return None

        recovery_attempts[failed_node_id] = current + 1
        logger.info(
            f"Planner repair for {failed_node_id} (attempt {current + 1}/{max_attempts})"
        )

        try:
            patch = await planner.plan_repair(
                graph, failed_node_id, error_message, env_context,
            )
            logger.info(f"Recovery patch: {len(patch.actions)} actions")
            return patch
        except Exception as e:
            logger.error(f"Planner repair failed for {failed_node_id}: {e}", exc_info=True)
            return None
