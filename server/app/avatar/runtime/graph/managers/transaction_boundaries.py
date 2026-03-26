# server/app/avatar/runtime/graph/managers/transaction_boundaries.py
"""
关键事务边界封装。

采用"核心状态原子提交 + checkpoint 异步补写"两阶段策略：
- 核心状态变更（step_state + graph_patch）在同一 SQLModel Session 事务中原子提交
- checkpoint 创建作为异步后续操作，失败时记录 warning 但不回滚核心状态
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.db.database import engine
from app.db.long_task_models import StepState, PatchLogEntry

logger = logging.getLogger(__name__)


class TransactionBoundaries:
    """关键事务边界封装，确保核心状态原子提交。"""

    def __init__(
        self,
        step_state_store,
        plan_graph_store,
        artifact_store,
        checkpoint_manager,
        task_session_store,
    ):
        self._step_state_store = step_state_store
        self._plan_graph_store = plan_graph_store
        self._artifact_store = artifact_store
        self._checkpoint_manager = checkpoint_manager
        self._task_session_store = task_session_store

    async def step_completion_transaction(
        self,
        step_id: str,
        new_status: str,
        artifact_data: dict | None = None,
        graph_patch: dict | None = None,
    ) -> dict:
        """
        步骤完成事务：

        Phase 1 (atomic): step_state → new_status + artifact_register + graph_patch(status_change)
        Phase 2 (async, best-effort): checkpoint_create(if needed)

        Returns dict with transaction result.
        """
        logger.info(
            f"[TransactionBoundaries] step_completion_transaction: "
            f"step={step_id} → {new_status}"
        )

        result = {"step_id": step_id, "new_status": new_status}

        # Phase 1: Atomic core state commit
        try:
            with Session(engine) as db:
                # 1. Update step state
                step = db.get(StepState, step_id)
                if step is None:
                    raise ValueError(f"StepState {step_id} not found")

                now = datetime.now(timezone.utc)
                step.status = new_status
                step.updated_at = now
                if new_status in ("success", "failed", "cancelled", "skipped"):
                    step.ended_at = now

                task_session_id = step.task_session_id

                # 2. Register artifact if provided
                artifact_record = None
                if artifact_data:
                    from app.db.long_task_models import ArtifactVersionRecord

                    # Auto-link parent_version_id to previous version of same path
                    parent_id = None
                    new_version = artifact_data.get("version", 1)
                    artifact_path = artifact_data["artifact_path"]
                    existing = db.exec(
                        select(ArtifactVersionRecord)
                        .where(ArtifactVersionRecord.task_session_id == task_session_id)
                        .where(ArtifactVersionRecord.artifact_path == artifact_path)
                        .order_by(ArtifactVersionRecord.version.desc())
                    ).first()
                    if existing:
                        parent_id = existing.id
                        new_version = existing.version + 1

                    # Determine version_source
                    version_source = artifact_data.get("version_source", "initial")
                    if new_version > 1 and version_source == "initial":
                        version_source = "iteration"

                    artifact_record = ArtifactVersionRecord(
                        task_session_id=task_session_id,
                        artifact_path=artifact_path,
                        artifact_kind=artifact_data.get("artifact_kind", "file"),
                        producer_step_id=step_id,
                        version=new_version,
                        content_hash=artifact_data["content_hash"],
                        size=artifact_data.get("size", 0),
                        mtime=artifact_data.get("mtime", 0.0),
                        parent_version_id=parent_id,
                        version_source=version_source,
                    )
                    db.add(artifact_record)

                # 3. Append graph patch if provided
                if graph_patch:
                    patch_entry = PatchLogEntry(
                        task_session_id=task_session_id,
                        graph_version=graph_patch.get("graph_version", 0),
                        operation=graph_patch.get("operation", "status_change"),
                        operation_params_json=json.dumps(
                            graph_patch.get("params", {"step_id": step_id, "new_status": new_status}),
                            ensure_ascii=False,
                        ),
                        change_reason="status_update",
                        change_source="system",
                    )
                    db.add(patch_entry)

                db.add(step)
                db.commit()

                result["phase1"] = "committed"
                result["task_session_id"] = task_session_id
                if artifact_record:
                    db.refresh(artifact_record)
                    result["artifact_id"] = artifact_record.id

                logger.info(
                    f"[TransactionBoundaries] Phase 1 committed for step {step_id}"
                )

        except Exception as e:
            logger.error(
                f"[TransactionBoundaries] Phase 1 FAILED for step {step_id}: {e}"
            )
            raise

        # Phase 2: Best-effort checkpoint creation
        try:
            if new_status == "success" and graph_patch:
                await self._checkpoint_manager.create_checkpoint(
                    task_session_id=result["task_session_id"],
                    importance="routine",
                    reason=f"step_completion:{step_id}",
                )
                result["phase2"] = "checkpoint_created"
            else:
                result["phase2"] = "skipped"
        except Exception as e:
            logger.warning(
                f"[TransactionBoundaries] Phase 2 checkpoint creation failed "
                f"for step {step_id} (non-fatal): {e}"
            )
            result["phase2"] = f"failed:{e}"

        return result

    async def change_merge_transaction(
        self,
        task_session_id: str,
        merge_fn,
    ) -> dict:
        """
        变更合并事务：

        Phase 1 (atomic): plan_merge → graph_version++
        Phase 2 (async, best-effort): checkpoint_create(merge)

        Args:
            task_session_id: The task session to merge changes into.
            merge_fn: Callable that performs the merge within the session.
                      Should accept a SQLModel Session and return a merge result dict.

        Returns dict with transaction result.
        """
        logger.info(
            f"[TransactionBoundaries] change_merge_transaction for {task_session_id}"
        )

        result = {"task_session_id": task_session_id}

        # Phase 1: Atomic merge + version increment
        try:
            with Session(engine) as db:
                merge_result = merge_fn(db)
                db.commit()
                result["phase1"] = "committed"
                result["merge_result"] = merge_result
                logger.info(
                    f"[TransactionBoundaries] Phase 1 merge committed "
                    f"for {task_session_id}"
                )
        except Exception as e:
            logger.error(
                f"[TransactionBoundaries] Phase 1 merge FAILED "
                f"for {task_session_id}: {e}"
            )
            raise

        # Phase 2: Best-effort checkpoint creation
        try:
            await self._checkpoint_manager.create_checkpoint(
                task_session_id=task_session_id,
                importance="merge",
                reason="change_merge_completed",
            )
            result["phase2"] = "checkpoint_created"
        except Exception as e:
            logger.warning(
                f"[TransactionBoundaries] Phase 2 checkpoint creation failed "
                f"for {task_session_id} (non-fatal): {e}"
            )
            result["phase2"] = f"failed:{e}"

        return result

    async def resume_transaction(
        self,
        task_session_id: str,
        checkpoint_id: str,
        restore_fn,
    ) -> dict:
        """
        恢复事务：

        Atomic: checkpoint_validate → step_states_restore → graph_restore
                → task_session_transition(resuming → executing)

        Args:
            task_session_id: The task session to resume.
            checkpoint_id: The checkpoint to restore from.
            restore_fn: Callable that performs the restore within the session.
                        Should accept a SQLModel Session and return a restore result dict.

        Returns dict with transaction result.
        """
        logger.info(
            f"[TransactionBoundaries] resume_transaction for {task_session_id} "
            f"from checkpoint {checkpoint_id}"
        )

        result = {
            "task_session_id": task_session_id,
            "checkpoint_id": checkpoint_id,
        }

        try:
            with Session(engine) as db:
                # 1. Validate and restore from checkpoint
                restore_result = restore_fn(db)

                # 2. Transition task_session: resuming → executing
                from app.db.long_task_models import TaskSession
                session = db.get(TaskSession, task_session_id)
                if session is None:
                    raise ValueError(f"TaskSession {task_session_id} not found")

                if session.status != "resuming":
                    raise ValueError(
                        f"TaskSession {task_session_id} is not in resuming state "
                        f"(current: {session.status})"
                    )

                session.status = "executing"
                session.updated_at = datetime.now(timezone.utc)
                db.add(session)

                db.commit()

                result["status"] = "committed"
                result["restore_result"] = restore_result
                logger.info(
                    f"[TransactionBoundaries] Resume transaction committed "
                    f"for {task_session_id}"
                )

        except Exception as e:
            logger.error(
                f"[TransactionBoundaries] Resume transaction FAILED "
                f"for {task_session_id}: {e}"
            )
            raise

        return result
