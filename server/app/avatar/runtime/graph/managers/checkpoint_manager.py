# server/app/avatar/runtime/graph/managers/checkpoint_manager.py
"""
CheckpointManager — 检查点管理器

四级重要性：routine / milestone / merge / pre_risky
- 创建检查点（含 graph_snapshot、step_states、artifact_refs、checksum）
- 从检查点恢复
- 保留策略：routine 最多保留 M 个，milestone/merge/pre_risky 永久保留
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from app.db.long_task_models import Checkpoint

logger = logging.getLogger(__name__)

# 永久保留的 checkpoint 重要性等级
_PERMANENT_IMPORTANCES = {"milestone", "merge", "pre_risky"}


class CheckpointManager:
    """检查点管理器。"""

    def __init__(self, checkpoint_store, step_state_store, plan_graph_store, event_stream=None):
        self._checkpoint_store = checkpoint_store
        self._step_state_store = step_state_store
        self._plan_graph_store = plan_graph_store
        self._event_stream = event_stream

    @staticmethod
    def _compute_checksum(
        graph_snapshot_json: str,
        step_states_json: str,
        artifact_refs_json: str,
    ) -> str:
        """SHA-256 of (graph_snapshot_json + step_states_json + artifact_refs_json)."""
        payload = (graph_snapshot_json + step_states_json + artifact_refs_json).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    async def create_checkpoint(
        self,
        task_session_id: str,
        importance: str,
        reason: str,
    ) -> Checkpoint:
        """
        创建检查点。

        收集当前 graph snapshot、所有 step states、artifact refs，
        计算 checksum 后持久化。
        """
        logger.info(
            f"[CheckpointManager] Creating {importance} checkpoint "
            f"for {task_session_id}: {reason}"
        )

        # 获取最新 graph snapshot
        snapshot = self._plan_graph_store.get_latest_snapshot(task_session_id)
        graph_snapshot_json = snapshot.graph_json if snapshot else "{}"
        graph_version = snapshot.graph_version if snapshot else 0

        # 获取所有 step states
        step_states = self._step_state_store.get_by_task_session(task_session_id)
        step_states_data = []
        for s in step_states:
            step_states_data.append({
                "id": s.id,
                "status": s.status,
                "capability_name": s.capability_name,
                "retry_count": s.retry_count,
                "error_message": s.error_message,
                "input_snapshot_json": s.input_snapshot_json,
                "output_json": s.output_json,
                "side_effect_summary_json": s.side_effect_summary_json,
            })
        step_states_json = json.dumps(step_states_data, ensure_ascii=False)

        # Artifact refs — 占位，实际集成时从 ArtifactStore 获取
        artifact_refs_json = "[]"

        checksum = self._compute_checksum(
            graph_snapshot_json, step_states_json, artifact_refs_json
        )

        checkpoint = self._checkpoint_store.create(
            task_session_id=task_session_id,
            importance=importance,
            reason=reason,
            graph_snapshot_json=graph_snapshot_json,
            step_states_json=step_states_json,
            artifact_refs_json=artifact_refs_json,
            checksum=checksum,
            graph_version=graph_version,
        )

        logger.info(
            f"[CheckpointManager] Created checkpoint {checkpoint.id} "
            f"(importance={importance}, graph_version={graph_version})"
        )

        if self._event_stream:
            try:
                self._event_stream.emit("checkpoint_created", {
                    "checkpoint_id": checkpoint.id,
                    "importance": importance,
                    "reason": reason,
                    "graph_version": graph_version,
                })
            except Exception as e:
                logger.debug(f"[CheckpointManager] Event emission failed: {e}")

        return checkpoint

    async def restore_from_checkpoint(self, checkpoint_id: str) -> dict:
        """
        从检查点恢复任务状态。

        返回 dict 包含 graph_snapshot、step_states、artifact_refs。
        """
        checkpoint = self._checkpoint_store.get(checkpoint_id)
        if checkpoint is None:
            raise ValueError(f"Checkpoint {checkpoint_id} not found")

        if checkpoint.is_deleted:
            raise ValueError(f"Checkpoint {checkpoint_id} has been deleted")

        logger.info(
            f"[CheckpointManager] Restoring from checkpoint {checkpoint_id} "
            f"(importance={checkpoint.importance}, graph_version={checkpoint.graph_version})"
        )

        return {
            "checkpoint_id": checkpoint.id,
            "task_session_id": checkpoint.task_session_id,
            "graph_version": checkpoint.graph_version,
            "graph_snapshot": json.loads(checkpoint.graph_snapshot_json),
            "step_states": json.loads(checkpoint.step_states_json),
            "artifact_refs": json.loads(checkpoint.artifact_refs_json),
            "importance": checkpoint.importance,
            "reason": checkpoint.reason,
        }

    async def apply_retention_policy(
        self, task_session_id: str, max_routine: int = 10
    ) -> int:
        """
        执行保留策略：soft-delete 多余的 routine checkpoint。

        - milestone / merge / pre_risky 永久保留
        - routine 最多保留 max_routine 个（按创建时间降序保留最新的）

        返回被 soft-delete 的 checkpoint 数量。
        """
        all_checkpoints = self._checkpoint_store.get_by_task_session(task_session_id)

        # 筛出未删除的 routine checkpoints（已按 created_at desc 排序）
        routine_checkpoints = [
            cp for cp in all_checkpoints
            if cp.importance == "routine" and not cp.is_deleted
        ]

        deleted_count = 0
        if len(routine_checkpoints) > max_routine:
            # 保留最新的 max_routine 个，soft-delete 其余
            to_delete = routine_checkpoints[max_routine:]
            for cp in to_delete:
                self._checkpoint_store.soft_delete(cp.id)
                deleted_count += 1

        if deleted_count > 0:
            logger.info(
                f"[CheckpointManager] Retention policy: soft-deleted {deleted_count} "
                f"routine checkpoints for {task_session_id}"
            )

        return deleted_count

    def get_latest_valid_checkpoint(
        self, task_session_id: str
    ) -> Optional[Checkpoint]:
        """获取最近的有效（未删除）检查点。"""
        return self._checkpoint_store.get_latest_valid(task_session_id)
