# server/app/avatar/runtime/graph/managers/resume_manager.py
"""
ResumeManager — 恢复管理器

三层一致性校验：
1. graph_version 校验 — checkpoint 中的版本与当前最新版本一致
2. checkpoint_checksum 校验 — 数据完整性
3. artifact_integrity 校验 — 引用的 artifact 文件存在且 content_hash 匹配

校验通过后计算 runnable set，生成结构化 resume_report。
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from app.db.long_task_models import Checkpoint

logger = logging.getLogger(__name__)


class ResumeManager:
    """恢复管理器。"""

    def __init__(
        self,
        checkpoint_manager,
        step_state_store,
        plan_graph_store,
        artifact_store,
        task_session_store,
        event_stream=None,
    ):
        self._checkpoint_manager = checkpoint_manager
        self._step_state_store = step_state_store
        self._plan_graph_store = plan_graph_store
        self._artifact_store = artifact_store
        self._task_session_store = task_session_store
        self._event_stream = event_stream

    async def resume(self, task_session_id: str) -> dict:
        """
        执行三层校验 → 计算 runnable set → 返回 resume_report。

        如果当前 checkpoint 校验失败，回退到上一个有效 checkpoint。
        如果所有 checkpoint 都无效，抛出异常。
        """
        logger.info(f"[ResumeManager] Starting resume for {task_session_id}")

        # 获取当前 graph version
        latest_snapshot = self._plan_graph_store.get_latest_snapshot(task_session_id)
        current_graph_version = latest_snapshot.graph_version if latest_snapshot else 0

        # 尝试从最新 checkpoint 开始校验
        checkpoint = self._checkpoint_manager.get_latest_valid_checkpoint(task_session_id)
        validation_attempts = []

        while checkpoint is not None:
            validation_result = self._validate_checkpoint(
                checkpoint, current_graph_version
            )
            validation_attempts.append({
                "checkpoint_id": checkpoint.id,
                "graph_version": checkpoint.graph_version,
                "validation": validation_result,
            })

            if validation_result["all_passed"]:
                # 校验通过，计算 runnable set
                step_states = self._step_state_store.get_by_task_session(
                    task_session_id
                )
                runnable_set = self.compute_runnable_set(step_states)

                # 生成 resume report
                skipped = [s.id for s in step_states if s.status == "skipped"]
                stale = [s.id for s in step_states if s.status == "stale"]
                completed = [s.id for s in step_states if s.status == "success"]

                resume_report = {
                    "task_session_id": task_session_id,
                    "checkpoint_id": checkpoint.id,
                    "checkpoint_graph_version": checkpoint.graph_version,
                    "validation_attempts": validation_attempts,
                    "runnable_set": runnable_set,
                    "skipped_steps": skipped,
                    "stale_steps": stale,
                    "completed_steps": completed,
                    "resume_reason": (
                        f"Resuming from checkpoint {checkpoint.id} "
                        f"(importance={checkpoint.importance})"
                    ),
                }

                logger.info(
                    f"[ResumeManager] Resume validated for {task_session_id}, "
                    f"runnable_set={runnable_set}"
                )

                if self._event_stream:
                    try:
                        self._event_stream.emit("resume_attempt", {
                            "checkpoint_id": checkpoint.id,
                            "validation_attempts": len(validation_attempts),
                            "runnable_set": runnable_set,
                            "stale_steps": stale,
                            "skipped_steps": skipped,
                        })
                    except Exception as e:
                        logger.debug(f"[ResumeManager] Event emission failed: {e}")

                return resume_report

            # 校验失败，尝试上一个 checkpoint
            logger.warning(
                f"[ResumeManager] Checkpoint {checkpoint.id} validation failed, "
                f"trying previous checkpoint"
            )
            # Get all checkpoints and find the one before current
            all_checkpoints = self._checkpoint_manager._checkpoint_store.get_by_task_session(
                task_session_id
            )
            found_current = False
            checkpoint = None
            for cp in all_checkpoints:
                if found_current and not cp.is_deleted:
                    checkpoint = cp
                    break
                if cp.id == validation_attempts[-1]["checkpoint_id"]:
                    found_current = True

        # 所有 checkpoint 都无效
        error_msg = (
            f"All checkpoints invalid for {task_session_id}. "
            f"Attempted {len(validation_attempts)} checkpoints."
        )
        logger.error(f"[ResumeManager] {error_msg}")
        raise RuntimeError(error_msg)

    def _validate_checkpoint(
        self, checkpoint: Checkpoint, current_graph_version: int
    ) -> dict:
        """执行三层校验，返回每层结果。"""
        layer1 = self.validate_graph_version(checkpoint, current_graph_version)
        layer2 = self.validate_checkpoint_checksum(checkpoint)
        layer3 = self.validate_artifact_integrity(checkpoint)

        return {
            "graph_version_valid": layer1,
            "checksum_valid": layer2,
            "artifact_integrity_valid": layer3,
            "all_passed": layer1 and layer2 and layer3,
        }

    def validate_graph_version(
        self, checkpoint: Checkpoint, current_graph_version: int
    ) -> bool:
        """第一层：graph_version 校验。"""
        valid = checkpoint.graph_version <= current_graph_version
        if not valid:
            logger.warning(
                f"[ResumeManager] Graph version mismatch: "
                f"checkpoint={checkpoint.graph_version}, "
                f"current={current_graph_version}"
            )
        return valid

    def validate_checkpoint_checksum(self, checkpoint: Checkpoint) -> bool:
        """第二层：checkpoint 数据完整性校验（重算 checksum 并比较）。"""
        recomputed = hashlib.sha256(
            (
                checkpoint.graph_snapshot_json
                + checkpoint.step_states_json
                + checkpoint.artifact_refs_json
            ).encode("utf-8")
        ).hexdigest()

        valid = recomputed == checkpoint.checksum
        if not valid:
            logger.warning(
                f"[ResumeManager] Checksum mismatch for checkpoint {checkpoint.id}: "
                f"stored={checkpoint.checksum}, recomputed={recomputed}"
            )
        return valid

    def validate_artifact_integrity(self, checkpoint: Checkpoint) -> bool:
        """第三层：artifact 文件存在性 + content_hash 校验。"""
        try:
            artifact_refs = json.loads(checkpoint.artifact_refs_json)
        except (json.JSONDecodeError, TypeError):
            # 空或无效 JSON — 如果没有 artifact refs，视为通过
            return True

        if not artifact_refs:
            return True

        for ref in artifact_refs:
            artifact_id = ref.get("id")
            expected_hash = ref.get("content_hash")
            if artifact_id is None:
                continue

            record = self._artifact_store.get(artifact_id)
            if record is None:
                logger.warning(
                    f"[ResumeManager] Artifact {artifact_id} not found in store"
                )
                return False

            if expected_hash and record.content_hash != expected_hash:
                logger.warning(
                    f"[ResumeManager] Artifact {artifact_id} content_hash mismatch: "
                    f"expected={expected_hash}, actual={record.content_hash}"
                )
                return False

        return True

    def compute_runnable_set(self, step_states: list) -> list[str]:
        """
        计算可运行步骤集。

        条件：步骤状态为 ready 或 stale 的步骤。
        在完整集成中，还需检查所有前置依赖是否为 success。
        """
        runnable = []
        for step in step_states:
            if step.status in ("ready", "stale"):
                runnable.append(step.id)
        return runnable
