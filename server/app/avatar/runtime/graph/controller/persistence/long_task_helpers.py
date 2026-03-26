"""
Long-task runtime helpers for GraphController.

Handles persisting step results, creating checkpoints, recording patches,
saving snapshots, and running the delivery gate for long-running tasks.

Extracted from graph_controller.py to keep the controller focused on
orchestration logic.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.events.task_event_stream import TaskEventStream

logger = logging.getLogger(__name__)


class LongTaskContext:
    """
    长任务运行时上下文，封装所有长任务相关的 store/manager 引用。
    仅在 env_context 中包含 task_session_id 时激活。
    """

    def __init__(self, task_session_id: str, event_stream: Optional['TaskEventStream'] = None):
        self.task_session_id = task_session_id
        self.event_stream = event_stream
        self.graph_version = 0
        self.step_count_since_checkpoint = 0
        self.patch_count_since_snapshot = 0
        self.checkpoint_interval = 5
        self.snapshot_interval = 20

    @staticmethod
    def from_env(env_context: dict) -> Optional['LongTaskContext']:
        """从 env_context 中提取长任务上下文，无 task_session_id 则返回 None。"""
        tsid = env_context.get("task_session_id")
        if not tsid:
            return None
        event_stream = env_context.get("_task_event_stream")
        return LongTaskContext(tsid, event_stream)


class LongTaskMixin:
    """Mixin providing long-task helper methods for GraphController."""

    async def _lt_persist_step_results(
        self, graph: 'ExecutionGraph', lt_ctx: 'LongTaskContext'
    ) -> None:
        """
        持久化步骤执行结果到 StepStateStore + ArtifactStore。
        """
        try:
            from app.services.step_state_store import StepStateStore
            from app.services.artifact_store import ArtifactStore
            from app.avatar.runtime.graph.models.step_node import NodeStatus
            from app.db.long_task_models import StepState
            import json
            import hashlib

            for node in graph.nodes.values():
                if node.status not in (NodeStatus.SUCCESS, NodeStatus.FAILED):
                    continue

                existing = StepStateStore.get(str(node.id))
                if existing and existing.status == node.status.value:
                    continue

                step_state = StepState(
                    id=str(node.id),
                    task_session_id=lt_ctx.task_session_id,
                    graph_version=lt_ctx.graph_version,
                    status=node.status.value,
                    capability_name=node.capability_name,
                    input_snapshot_json=json.dumps(node.params, ensure_ascii=False) if node.params else None,
                    output_json=json.dumps(node.result, ensure_ascii=False) if hasattr(node, 'result') and node.result else None,
                )
                StepStateStore.upsert(step_state)

                if node.status == NodeStatus.SUCCESS:
                    output_contract = node.metadata.get("output_contract") if node.metadata else None
                    if output_contract:
                        artifacts = output_contract if isinstance(output_contract, list) else [output_contract]
                        for art in artifacts:
                            if isinstance(art, dict) and art.get("path"):
                                content = json.dumps(art, ensure_ascii=False)
                                content_hash = hashlib.sha256(content.encode()).hexdigest()
                                ArtifactStore.register_artifact(
                                    task_session_id=lt_ctx.task_session_id,
                                    artifact_path=art["path"],
                                    artifact_kind=art.get("kind", "file"),
                                    producer_step_id=str(node.id),
                                    content_hash=content_hash,
                                    size=len(content),
                                    mtime=0.0,
                                )

        except Exception as e:
            logger.warning(f"[GraphController] Long-task step persist failed: {e}")

    async def _lt_create_routine_checkpoint(self, lt_ctx: 'LongTaskContext') -> None:
        """创建 routine 级别 checkpoint。"""
        try:
            from app.services.checkpoint_store import CheckpointStore
            from app.services.step_state_store import StepStateStore
            from app.services.plan_graph_store import PlanGraphStore
            from app.avatar.runtime.graph.managers.checkpoint_manager import CheckpointManager

            cp_mgr = CheckpointManager(
                CheckpointStore, StepStateStore, PlanGraphStore,
                event_stream=lt_ctx.event_stream,
            )
            await cp_mgr.create_checkpoint(
                task_session_id=lt_ctx.task_session_id,
                importance="routine",
                reason=f"periodic:step_count",
            )
        except Exception as e:
            logger.warning(f"[GraphController] Routine checkpoint failed (non-fatal): {e}")

    def _lt_record_patch(
        self, lt_ctx: 'LongTaskContext', action, graph: 'ExecutionGraph'
    ) -> None:
        """记录 PatchLogEntry 并在达到阈值时保存 snapshot。"""
        try:
            from app.services.plan_graph_store import PlanGraphStore
            import json

            operation = action.operation.value if hasattr(action.operation, 'value') else str(action.operation)
            params = {}
            if action.node:
                params["node_id"] = str(action.node.id)
                params["capability"] = action.node.capability_name
            elif action.node_id:
                params["node_id"] = action.node_id
            elif action.edge:
                params["source"] = action.edge.source_node
                params["target"] = action.edge.target_node

            PlanGraphStore.append_patch(
                task_session_id=lt_ctx.task_session_id,
                graph_version=lt_ctx.graph_version,
                operation=operation,
                operation_params_json=json.dumps(params, ensure_ascii=False),
                change_reason="initial_plan",
                change_source="planner",
            )

            lt_ctx.patch_count_since_snapshot += 1
            if lt_ctx.graph_version == 1:
                self._lt_save_snapshot(lt_ctx, graph, "initial_plan")
                lt_ctx.patch_count_since_snapshot = 0
            elif lt_ctx.patch_count_since_snapshot >= lt_ctx.snapshot_interval:
                self._lt_save_snapshot(lt_ctx, graph, "periodic")
                lt_ctx.patch_count_since_snapshot = 0

        except Exception as e:
            logger.warning(f"[GraphController] Patch log recording failed: {e}")

    def _lt_save_snapshot(
        self, lt_ctx: 'LongTaskContext', graph: 'ExecutionGraph', reason: str
    ) -> None:
        """保存 PlanGraphSnapshot。"""
        try:
            from app.services.plan_graph_store import PlanGraphStore
            import json

            graph_data = {
                "goal": graph.goal,
                "nodes": {
                    nid: {
                        "id": str(n.id),
                        "capability_name": n.capability_name,
                        "status": n.status.value if hasattr(n.status, 'value') else str(n.status),
                        "params": n.params,
                    }
                    for nid, n in graph.nodes.items()
                },
                "edges": {
                    eid: {
                        "source": e.source_node,
                        "target": e.target_node,
                    }
                    for eid, e in graph.edges.items()
                },
            }
            PlanGraphStore.save_snapshot(
                task_session_id=lt_ctx.task_session_id,
                graph_version=lt_ctx.graph_version,
                graph_json=json.dumps(graph_data, ensure_ascii=False),
                snapshot_reason=reason,
                change_source="system",
            )
        except Exception as e:
            logger.warning(f"[GraphController] Snapshot save failed: {e}")

    async def _lt_run_delivery_gate(self, lt_ctx: 'LongTaskContext') -> Optional[dict]:
        """运行 DeliveryGate 检查。"""
        try:
            from app.avatar.runtime.graph.managers.delivery_gate import DeliveryGate
            from app.avatar.runtime.graph.artifact_dep_graph import ArtifactDependencyGraph
            from app.services.step_state_store import StepStateStore

            dep_graph = ArtifactDependencyGraph(event_stream=lt_ctx.event_stream)
            gate = DeliveryGate(dep_graph, StepStateStore, event_stream=lt_ctx.event_stream)
            return await gate.evaluate(lt_ctx.task_session_id)
        except Exception as e:
            logger.warning(f"[GraphController] DeliveryGate check failed: {e}")
            return None
