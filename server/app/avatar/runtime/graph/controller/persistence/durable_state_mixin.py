"""
DurableStateMixin — 持久化状态机钩子。

GraphController 的最小侵入面，通过 6 个钩子方法注入持久化逻辑：
  - _durable_before_step: 幂等检查 + Attempt_ID 分配 + Frontier 更新
  - _durable_after_step: 持久化结果 + Frontier 更新 + routine checkpoint
  - _durable_before_side_effect: Effect Ledger 注册 + pre_effect checkpoint
  - _durable_after_side_effect: Effect Ledger 更新 + post_effect checkpoint
  - _durable_on_interrupt: state_transition checkpoint + Frontier 持久化
  - _durable_on_resume: 从 Checkpoint 加载 Frontier + 恢复 runtime state

复用 LongTaskMixin 的 _lt_persist_step_results 和 _lt_create_routine_checkpoint。
"""
from __future__ import annotations

import logging
import uuid
import json
import hashlib
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_frontier import ExecutionFrontier

logger = logging.getLogger(__name__)


@dataclass
class DurableContext:
    """持久化状态机运行时上下文"""
    task_session_id: str
    worker_id: str
    frontier: Optional['ExecutionFrontier'] = None
    has_committed_state: bool = False
    step_count: int = 0

    @staticmethod
    def from_env(env_context: dict, worker_id: Optional[str] = None) -> Optional['DurableContext']:
        tsid = env_context.get("task_session_id")
        if not tsid:
            return None
        wid = worker_id or str(uuid.uuid4())
        from app.avatar.runtime.graph.models.execution_frontier import ExecutionFrontier
        return DurableContext(task_session_id=tsid, worker_id=wid, frontier=ExecutionFrontier())


class DurableStateMixin:
    """持久化状态机钩子 — GraphController 的最小侵入面"""

    # ── before_step ──────────────────────────────────────────────

    async def _durable_before_step(
        self, node_id: str, capability_name: str, input_params: str, ctx: DurableContext
    ) -> Optional[Dict[str, Any]]:
        """
        before_step 钩子：
        1. 生成 Idempotency_Key
        2. 检查幂等：已成功则返回缓存结果
        3. 分配 Attempt_ID
        4. 更新 Execution Frontier（标记为 running）
        
        Returns:
            已有成功结果时返回 dict（跳过执行），否则返回 None（继续执行）
        """
        try:
            from app.services.step_state_store import StepStateStore

            idem_key = StepStateStore.generate_idempotency_key(
                ctx.task_session_id, node_id, input_params
            )
            existing = StepStateStore.get_by_idempotency_key(ctx.task_session_id, idem_key)

            if existing and existing.status == "success":
                logger.info(f"[Durable] Idempotent skip: {node_id} key={idem_key}")
                if ctx.frontier:
                    ctx.frontier.on_node_completed(
                        node_id, existing.input_hash or "", 
                        existing.ended_at.isoformat() if existing.ended_at else None,
                    )
                return {"output_json": existing.output_json, "skipped": True}

            attempt_id = str(uuid.uuid4())
            if ctx.frontier:
                ctx.frontier.on_node_started(node_id, ctx.worker_id, attempt_id)

            return None

        except Exception as e:
            logger.warning(f"[Durable] before_step error (non-fatal): {e}")
            if self._can_fallback(ctx):
                return None
            raise

    # ── after_step ───────────────────────────────────────────────

    async def _durable_after_step(
        self, node_id: str, output_digest: str, ctx: DurableContext
    ) -> None:
        """
        after_step 钩子：
        1. 更新 Execution Frontier（标记为 completed）
        2. 增量计数，达到阈值时创建 routine checkpoint
        """
        try:
            if ctx.frontier:
                ctx.frontier.on_node_completed(node_id, output_digest)

            ctx.step_count += 1
            ctx.has_committed_state = True

            # 每 5 步创建一次 routine checkpoint
            if ctx.step_count % 5 == 0:
                await self._durable_create_checkpoint(ctx, "routine", f"periodic:step_{ctx.step_count}")

        except Exception as e:
            logger.warning(f"[Durable] after_step error: {e}")
            if not self._can_fallback(ctx):
                raise

    # ── before_side_effect ───────────────────────────────────────

    async def _durable_before_side_effect(
        self, node_id: str, effect_type: str, ctx: DurableContext,
        target_path: Optional[str] = None, metadata_json: Optional[str] = None,
    ) -> str:
        """
        before_side_effect 钩子：
        1. 注册 Effect Ledger 条目（prepared 状态）
        2. 创建 pre_effect checkpoint
        Returns: effect_entry_id
        """
        from app.services.effect_ledger_store import EffectLedgerStore

        entry = EffectLedgerStore.prepare(
            task_session_id=ctx.task_session_id,
            step_id=node_id,
            effect_type=effect_type,
            target_path=target_path,
            metadata_json=metadata_json,
        )
        ctx.has_committed_state = True

        await self._durable_create_checkpoint(ctx, "pre_effect", f"before_effect:{entry.id}")
        return entry.id

    # ── after_side_effect ────────────────────────────────────────

    async def _durable_after_side_effect(
        self, effect_entry_id: str, success: bool, ctx: DurableContext,
        content_hash: Optional[str] = None, remote_receipt: Optional[str] = None,
    ) -> None:
        """
        after_side_effect 钩子：
        1. 更新 Effect Ledger（committed/unknown）
        2. 创建 post_effect checkpoint
        """
        from app.services.effect_ledger_store import EffectLedgerStore

        if success:
            EffectLedgerStore.commit(effect_entry_id, content_hash=content_hash, remote_receipt=remote_receipt)
        else:
            EffectLedgerStore.mark_unknown(effect_entry_id)

        await self._durable_create_checkpoint(ctx, "post_effect", f"after_effect:{effect_entry_id}")

    # ── on_interrupt ─────────────────────────────────────────────

    async def _durable_on_interrupt(self, reason: str, ctx: DurableContext) -> None:
        """
        on_interrupt 钩子（暂停/等待审批时）：
        1. 创建 state_transition checkpoint（含 Frontier + pending requests）
        2. 停止心跳
        """
        await self._durable_create_checkpoint(ctx, "state_transition", f"interrupt:{reason}")
        self._stop_heartbeat(ctx)

    # ── on_resume ────────────────────────────────────────────────

    async def _durable_on_resume(self, ctx: DurableContext) -> Dict[str, Any]:
        """
        on_resume 钩子：
        1. 从 Checkpoint 加载 Execution Frontier
        2. 恢复 runtime state
        3. 启动心跳
        Returns: 恢复上下文
        """
        from app.services.checkpoint_store import CheckpointStore
        from app.avatar.runtime.graph.models.execution_frontier import ExecutionFrontier

        checkpoint = CheckpointStore.get_latest_valid(ctx.task_session_id)
        if checkpoint and checkpoint.execution_frontier_json:
            ctx.frontier = ExecutionFrontier.from_json(checkpoint.execution_frontier_json)
        else:
            ctx.frontier = ExecutionFrontier()

        self._start_heartbeat(ctx)

        return {
            "frontier": ctx.frontier,
            "checkpoint_id": checkpoint.id if checkpoint else None,
        }

    # ── on_approval_needed ───────────────────────────────────────

    async def _durable_on_approval_needed(
        self, ctx: DurableContext, request_info: dict
    ) -> None:
        """
        审批中断流程（真正的 durable interrupt）：
        1. 创建审批请求并推送到前端
        2. 持久化 Frontier + Checkpoint
        3. 转换任务状态到 waiting_approval
        4. raise DurableInterruptSignal 退出执行流程
        """
        from app.services.approval_service import get_approval_service
        from app.services.task_session_store import TaskSessionStore
        from app.avatar.runtime.graph.controller.persistence.durable_interrupt import DurableInterruptSignal

        service = get_approval_service()
        service.request_approval_and_interrupt(**request_info)

        await self._durable_on_interrupt("approval_needed", ctx)

        TaskSessionStore.transition(
            ctx.task_session_id, "waiting_approval",
            last_transition_reason="approval_needed",
        )

        raise DurableInterruptSignal(
            reason="waiting_approval",
            task_id=ctx.task_session_id,
        )

    # ── Checkpoint 创建 ──────────────────────────────────────────

    async def _durable_create_checkpoint(
        self, ctx: DurableContext, importance: str, reason: str
    ) -> None:
        """创建包含 Frontier 和 Effect Ledger 快照的 Checkpoint。"""
        try:
            from app.services.checkpoint_store import CheckpointStore
            from app.services.step_state_store import StepStateStore
            from app.services.effect_ledger_store import EffectLedgerStore
            from app.services.approval_service import get_approval_service

            step_states = StepStateStore.get_by_task_session(ctx.task_session_id)
            effects = EffectLedgerStore.get_by_task(ctx.task_session_id)
            pending_approvals = get_approval_service().get_pending_by_task(ctx.task_session_id)

            frontier_json = ctx.frontier.to_json() if ctx.frontier else None
            steps_json = json.dumps([{"id": s.id, "status": s.status} for s in step_states], ensure_ascii=False)
            effects_json = json.dumps([{"id": e.id, "status": e.status, "effect_type": e.effect_type} for e in effects], ensure_ascii=False)
            pending_json = json.dumps(pending_approvals, ensure_ascii=False) if pending_approvals else None

            # 计算 checksum
            data_for_hash = f"{frontier_json}|{steps_json}|{effects_json}|{pending_json}"
            checksum = hashlib.sha256(data_for_hash.encode("utf-8")).hexdigest()

            CheckpointStore.create(
                task_session_id=ctx.task_session_id,
                importance=importance,
                reason=reason,
                graph_snapshot_json="{}",
                step_states_json=steps_json,
                artifact_refs_json="[]",
                checksum=checksum,
                graph_version=0,
                execution_frontier_json=frontier_json,
                idempotency_metadata_json=None,
                effect_ledger_snapshot_json=effects_json,
                pending_requests_json=pending_json,
            )
            ctx.has_committed_state = True

        except Exception as e:
            logger.error(f"[Durable] Checkpoint creation failed: {e}")
            raise

    # ── 心跳管理 ─────────────────────────────────────────────────

    def _start_heartbeat(self, ctx: DurableContext) -> None:
        """启动心跳定时器"""
        try:
            from app.services.heartbeat_manager import HeartbeatManager
            if not hasattr(self, '_heartbeat_mgr') or self._heartbeat_mgr is None:
                self._heartbeat_mgr = HeartbeatManager(ctx.task_session_id, ctx.worker_id)
                self._heartbeat_mgr.start()
        except Exception as e:
            logger.warning(f"[Durable] Heartbeat start failed: {e}")

    def _stop_heartbeat(self, ctx: DurableContext) -> None:
        """停止心跳定时器"""
        if hasattr(self, '_heartbeat_mgr') and self._heartbeat_mgr:
            self._heartbeat_mgr.stop()
            self._heartbeat_mgr = None

    # ── 回退逻辑 ─────────────────────────────────────────────────

    def _can_fallback(self, ctx: DurableContext) -> bool:
        """
        判断是否允许回退到旧路径。
        仅在 durable 路径未提交任何状态时允许。
        """
        return not ctx.has_committed_state

    async def _handle_durable_error(self, error: Exception, ctx: DurableContext) -> None:
        """
        处理 durable 路径内部错误：
        - 未提交状态 → 回退到旧路径，记录回退原因
        - 已提交状态 → 标记任务 failed，不回退
        """
        if self._can_fallback(ctx):
            logger.warning(f"[Durable] Error before commit, falling back: {error}")
        else:
            logger.error(f"[Durable] Error after commit, cannot fallback: {error}")
            from app.services.task_session_store import TaskSessionStore
            TaskSessionStore.transition(
                ctx.task_session_id, "failed",
                last_transition_reason=f"durable_error_after_commit: {error}",
            )
            raise
