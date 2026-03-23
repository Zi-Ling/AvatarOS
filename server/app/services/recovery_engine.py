"""
RecoveryEngine — 恢复引擎

服务启动时扫描并恢复中断的任务。按中断类型分叉恢复语义：
  - expired running → 自动接管继续执行
  - waiting_approval → 仅重推审批，不继续执行
  - paused → 保持暂停，仅验证 Checkpoint 可用性
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.long_task_models import TaskSession, Checkpoint

logger = logging.getLogger(__name__)


class RecoveryEngine:
    """恢复引擎 — 服务启动时扫描并恢复中断的任务"""

    def __init__(self):
        self.worker_id = str(uuid.uuid4())

    # ── 启动扫描 ─────────────────────────────────────────────────

    async def scan_and_recover(self) -> list[str]:
        """
        启动扫描：
        1. 查找 waiting_approval / paused 状态的任务
        2. 查找 running 且 Lease 过期的任务
        3. 对每个任务按状态分叉执行恢复流程
        Returns: 已恢复的 task_session_id 列表
        """
        from app.services.task_session_store import TaskSessionStore

        recovered: list[str] = []

        # 查找 Lease 过期的 running 任务
        expired = TaskSessionStore.find_expired_leases()
        for task in expired:
            try:
                if await self.recover_task(task):
                    recovered.append(task.id)
            except Exception as e:
                logger.error(f"[RecoveryEngine] Failed to recover expired task {task.id}: {e}")

        # 查找 waiting_approval / paused 任务
        non_terminal = TaskSessionStore.load_non_terminal()
        for task in non_terminal:
            if task.id in {t.id for t in expired}:
                continue  # 已处理
            if task.status in ("waiting_approval", "paused"):
                try:
                    if await self.recover_task(task):
                        recovered.append(task.id)
                except Exception as e:
                    logger.error(f"[RecoveryEngine] Failed to recover {task.status} task {task.id}: {e}")

        logger.info(f"[RecoveryEngine] Scan complete: recovered {len(recovered)} tasks")
        return recovered

    # ── 恢复单个任务 ─────────────────────────────────────────────

    async def recover_task(self, task_session: 'TaskSession') -> bool:
        """
        恢复单个任务 — 按中断类型分叉恢复语义：
          expired running → 自动接管继续执行
          waiting_approval → 仅重推审批
          paused → 保持暂停，验证 Checkpoint
        """
        status = task_session.status
        logger.info(f"[RecoveryEngine] Recovering task {task_session.id} (status={status})")

        if status == "executing":
            return await self._recover_expired_running(task_session)
        elif status == "waiting_approval":
            return await self._recover_waiting_approval(task_session)
        elif status == "paused":
            return await self._recover_paused(task_session)

        logger.warning(f"[RecoveryEngine] Unexpected status for recovery: {status}")
        return False

    # ── 恢复 Lease 过期的 running 任务 ──────────────────────────

    async def _recover_expired_running(self, task_session: 'TaskSession') -> bool:
        """
        1. 加载最近 Checkpoint → 验证 checksum
        2. 重建 Execution Frontier
        3. 获取新 Lease
        4. 记录恢复链路
        """
        from app.services.checkpoint_store import CheckpointStore
        from app.services.task_session_store import TaskSessionStore

        checkpoint = CheckpointStore.get_latest_valid(task_session.id)
        if not checkpoint:
            logger.error(f"[RecoveryEngine] No checkpoint for task {task_session.id}, cannot recover")
            return False

        if not self._verify_checkpoint_integrity(checkpoint):
            logger.error(f"[RecoveryEngine] Checkpoint integrity check failed for task {task_session.id}")
            return False

        # 获取新 Lease
        acquired = TaskSessionStore.acquire_lease(task_session.id, self.worker_id)
        if not acquired:
            logger.warning(f"[RecoveryEngine] Could not acquire lease for task {task_session.id}")
            return False

        # 记录恢复链路
        self._record_recovery_chain(task_session, "expired_running_recovery")

        # 重建上下文
        context = await self._rebuild_context(checkpoint)
        logger.info(
            f"[RecoveryEngine] Recovered expired running task {task_session.id}, "
            f"checkpoint={checkpoint.id}, frontier_nodes={len(context.get('completed_nodes', {}))}"
        )
        return True

    # ── 恢复 waiting_approval 任务 ──────────────────────────────

    async def _recover_waiting_approval(self, task_session: 'TaskSession') -> bool:
        """仅重推 pending 审批请求到前端，不继续执行。"""
        await self._repush_pending_approvals(task_session.id)
        logger.info(f"[RecoveryEngine] Re-pushed pending approvals for task {task_session.id}")
        return True

    # ── 恢复 paused 任务 ────────────────────────────────────────

    async def _recover_paused(self, task_session: 'TaskSession') -> bool:
        """验证 Checkpoint 可用性，保持暂停状态。"""
        from app.services.checkpoint_store import CheckpointStore

        checkpoint = CheckpointStore.get_latest_valid(task_session.id)
        if checkpoint:
            valid = self._verify_checkpoint_integrity(checkpoint)
            logger.info(
                f"[RecoveryEngine] Paused task {task_session.id}: "
                f"checkpoint={'valid' if valid else 'INVALID'}"
            )
        else:
            logger.warning(f"[RecoveryEngine] Paused task {task_session.id}: no checkpoint found")
        return True

    # ── 审批通过后恢复 ──────────────────────────────────────────

    async def resume_from_approval(self, task_id: str, request_id: str) -> bool:
        """
        审批通过后恢复任务执行：
        1. 加载最近 Checkpoint + 验证
        2. 获取新 Lease
        3. 转换状态 waiting_approval → executing
        4. 记录恢复链路
        """
        from app.services.checkpoint_store import CheckpointStore
        from app.services.task_session_store import TaskSessionStore

        checkpoint = CheckpointStore.get_latest_valid(task_id)
        if not checkpoint:
            logger.error(f"[RecoveryEngine] No checkpoint for approval resume: {task_id}")
            return False

        if not self._verify_checkpoint_integrity(checkpoint):
            logger.error(f"[RecoveryEngine] Checkpoint integrity failed for approval resume: {task_id}")
            return False

        acquired = TaskSessionStore.acquire_lease(task_id, self.worker_id)
        if not acquired:
            logger.warning(f"[RecoveryEngine] Could not acquire lease for approval resume: {task_id}")
            return False

        try:
            TaskSessionStore.transition(
                task_id, "executing",
                last_transition_reason=f"approval_approved:{request_id}",
            )
        except Exception as e:
            logger.error(f"[RecoveryEngine] State transition failed for approval resume: {e}")
            TaskSessionStore.release_lease(task_id, self.worker_id)
            return False

        task = TaskSessionStore.get(task_id)
        if task:
            self._record_recovery_chain(task, f"approval_resume:{request_id}")

        context = await self._rebuild_context(checkpoint)
        logger.info(f"[RecoveryEngine] Resumed task {task_id} after approval {request_id}")
        return True

    # ── 审批拒绝后处理 ──────────────────────────────────────────

    async def handle_approval_rejection(self, task_id: str, request_id: str) -> bool:
        """
        审批拒绝后：
        1. 触发 Effect Ledger 补偿流程
        2. 转换状态 waiting_approval → cancelled
        """
        from app.services.task_session_store import TaskSessionStore
        from app.services.effect_ledger_store import EffectLedgerStore

        # 补偿已提交的副作用
        committed_effects = EffectLedgerStore.get_by_task(task_id)
        for effect in committed_effects:
            if effect.status == "committed":
                try:
                    EffectLedgerStore.compensate(
                        effect.id,
                        compensation_details=f"approval_rejected:{request_id}",
                    )
                except Exception as e:
                    logger.warning(f"[RecoveryEngine] Effect compensation failed: {e}")

        try:
            TaskSessionStore.transition(
                task_id, "cancelled",
                last_transition_reason=f"approval_rejected:{request_id}",
            )
        except Exception as e:
            logger.error(f"[RecoveryEngine] State transition to cancelled failed: {e}")
            return False

        logger.info(f"[RecoveryEngine] Task {task_id} cancelled after approval rejection {request_id}")
        return True

    # ── 用户显式恢复暂停任务 ────────────────────────────────────

    async def resume_from_pause(self, task_id: str) -> bool:
        """
        用户显式恢复暂停任务：
        1. 加载最近 Checkpoint + 验证
        2. 获取新 Lease
        3. 转换状态 paused → executing
        """
        from app.services.checkpoint_store import CheckpointStore
        from app.services.task_session_store import TaskSessionStore

        checkpoint = CheckpointStore.get_latest_valid(task_id)
        if not checkpoint:
            logger.error(f"[RecoveryEngine] No checkpoint for pause resume: {task_id}")
            return False

        if not self._verify_checkpoint_integrity(checkpoint):
            logger.error(f"[RecoveryEngine] Checkpoint integrity failed for pause resume: {task_id}")
            return False

        acquired = TaskSessionStore.acquire_lease(task_id, self.worker_id)
        if not acquired:
            logger.warning(f"[RecoveryEngine] Could not acquire lease for pause resume: {task_id}")
            return False

        try:
            TaskSessionStore.transition(
                task_id, "executing",
                last_transition_reason="user_resume_from_pause",
            )
        except Exception as e:
            logger.error(f"[RecoveryEngine] State transition failed for pause resume: {e}")
            TaskSessionStore.release_lease(task_id, self.worker_id)
            return False

        task = TaskSessionStore.get(task_id)
        if task:
            self._record_recovery_chain(task, "pause_resume")

        context = await self._rebuild_context(checkpoint)
        logger.info(f"[RecoveryEngine] Resumed paused task {task_id}")
        return True

    # ── 内部辅助方法 ─────────────────────────────────────────────

    async def _rebuild_context(self, checkpoint: 'Checkpoint') -> dict:
        """从 Checkpoint 重建执行上下文。"""
        from app.avatar.runtime.graph.models.execution_frontier import ExecutionFrontier

        context: dict = {
            "checkpoint_id": checkpoint.id,
            "task_session_id": checkpoint.task_session_id,
            "completed_nodes": {},
        }

        # 重建 Execution Frontier
        if checkpoint.execution_frontier_json:
            frontier = ExecutionFrontier.from_json(checkpoint.execution_frontier_json)
            context["frontier"] = frontier
            context["completed_nodes"] = frontier.completed_nodes

        # 加载步骤状态
        if checkpoint.step_states_json:
            try:
                context["step_states"] = json.loads(checkpoint.step_states_json)
            except (json.JSONDecodeError, TypeError):
                context["step_states"] = []

        # 加载 Effect Ledger 快照
        if checkpoint.effect_ledger_snapshot_json:
            try:
                context["effect_ledger"] = json.loads(checkpoint.effect_ledger_snapshot_json)
            except (json.JSONDecodeError, TypeError):
                context["effect_ledger"] = []

        # 加载 pending requests
        if checkpoint.pending_requests_json:
            try:
                context["pending_requests"] = json.loads(checkpoint.pending_requests_json)
            except (json.JSONDecodeError, TypeError):
                context["pending_requests"] = []

        return context

    async def _repush_pending_approvals(self, task_session_id: str) -> None:
        """重新推送 pending 审批请求到前端。"""
        from app.services.approval_service import get_approval_service

        service = get_approval_service()
        pending = service.get_pending_by_task(task_session_id)

        if not pending:
            logger.info(f"[RecoveryEngine] No pending approvals for task {task_session_id}")
            return

        # 通过 SocketManager 重新推送
        try:
            from app.io.manager import get_socket_manager
            sm = get_socket_manager()
            for approval in pending:
                await sm.emit("approval_request", approval)
            logger.info(
                f"[RecoveryEngine] Re-pushed {len(pending)} pending approvals "
                f"for task {task_session_id}"
            )
        except Exception as e:
            logger.warning(f"[RecoveryEngine] Failed to re-push approvals: {e}")

    def _verify_checkpoint_integrity(self, checkpoint: 'Checkpoint') -> bool:
        """验证 Checkpoint 数据完整性（checksum 校验）。"""
        if not checkpoint.checksum:
            return True  # 无 checksum 的旧 checkpoint 跳过校验

        try:
            data_for_hash = (
                f"{checkpoint.execution_frontier_json or ''}|"
                f"{checkpoint.step_states_json or ''}|"
                f"{checkpoint.effect_ledger_snapshot_json or ''}|"
                f"{checkpoint.pending_requests_json or ''}"
            )
            computed = hashlib.sha256(data_for_hash.encode("utf-8")).hexdigest()

            if computed != checkpoint.checksum:
                logger.error(
                    f"[RecoveryEngine] Checksum mismatch for checkpoint {checkpoint.id}: "
                    f"expected={checkpoint.checksum}, computed={computed}"
                )
                return False
            return True
        except Exception as e:
            logger.warning(f"[RecoveryEngine] Checksum verification error: {e}")
            return False

    def _record_recovery_chain(self, task_session: 'TaskSession', reason: str) -> None:
        """记录恢复链路到 TaskSession.recovery_chain_json。"""
        from datetime import datetime, timezone

        try:
            chain = []
            if task_session.recovery_chain_json:
                chain = json.loads(task_session.recovery_chain_json)

            chain.append({
                "worker_id": self.worker_id,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            # 保留最近 10 条恢复记录
            if len(chain) > 10:
                chain = chain[-10:]

            from app.services.task_session_store import TaskSessionStore
            from sqlmodel import Session, text
            from app.db.database import engine

            with Session(engine) as db:
                db.exec(
                    text(
                        "UPDATE task_sessions SET recovery_chain_json=:chain "
                        "WHERE id=:sid"
                    ).bindparams(
                        chain=json.dumps(chain, ensure_ascii=False),
                        sid=task_session.id,
                    )
                )
                db.commit()
        except Exception as e:
            logger.warning(f"[RecoveryEngine] Failed to record recovery chain: {e}")
