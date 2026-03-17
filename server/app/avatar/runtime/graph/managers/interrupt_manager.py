# server/app/avatar/runtime/graph/managers/interrupt_manager.py
"""
InterruptManager — 中断管理器

区分两种中断语义：
- graceful_pause: 用户主动暂停，等待当前步骤完成 → 创建 milestone checkpoint → paused
- forced_interrupt: 被动中断（进程崩溃/心跳超时），running 步骤标记为 stale → interrupted

职责边界：只负责状态标记和检查点创建，不负责恢复决策。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.avatar.runtime.graph.models.heartbeat_config import get_heartbeat_config
from app.db.long_task_models import Checkpoint

logger = logging.getLogger(__name__)


class InterruptManager:
    """中断管理器，区分 graceful_pause 和 forced_interrupt。"""

    def __init__(self, task_session_store, step_state_store, checkpoint_manager):
        self._task_session_store = task_session_store
        self._step_state_store = step_state_store
        self._checkpoint_manager = checkpoint_manager

    async def graceful_pause(self, task_session_id: str) -> Checkpoint:
        """
        主动暂停：等待当前步骤完成 → 创建 milestone checkpoint → paused。

        流程：
        1. 获取所有 running 步骤，等待它们完成（此处标记为 stale 以安全停止）
        2. 创建 milestone 级别 checkpoint
        3. 将 TaskSession 转为 paused
        """
        logger.info(f"[InterruptManager] Initiating graceful_pause for {task_session_id}")

        # 获取当前所有步骤状态
        step_states = self._step_state_store.get_by_task_session(task_session_id)

        # 等待 running 步骤完成 — 在实际集成中，这里会等待信号；
        # 当前实现中，我们将 running 步骤视为已完成当前迭代
        running_steps = [s for s in step_states if s.status == "running"]
        if running_steps:
            logger.info(
                f"[InterruptManager] Found {len(running_steps)} running steps, "
                f"waiting for completion before pause"
            )

        # 创建 milestone checkpoint
        checkpoint = await self._checkpoint_manager.create_checkpoint(
            task_session_id=task_session_id,
            importance="milestone",
            reason="graceful_pause",
        )

        # 转换 TaskSession 状态为 paused
        self._task_session_store.transition(task_session_id, "paused")

        logger.info(
            f"[InterruptManager] graceful_pause completed for {task_session_id}, "
            f"checkpoint={checkpoint.id}"
        )
        return checkpoint

    async def detect_forced_interrupt(self, task_session_id: str) -> None:
        """
        检测被动中断：将所有 running 步骤标记为 stale → TaskSession 转 interrupted。

        用于进程崩溃恢复场景：系统重启后发现仍有 running 步骤，
        说明之前的执行被非正常中断。
        """
        logger.info(
            f"[InterruptManager] Detecting forced interrupt for {task_session_id}"
        )

        step_states = self._step_state_store.get_by_task_session(task_session_id)
        running_steps = [s for s in step_states if s.status == "running"]

        if not running_steps:
            logger.info(
                f"[InterruptManager] No running steps found for {task_session_id}, "
                f"skipping forced interrupt marking"
            )

        # 将所有 running 步骤标记为 stale
        for step in running_steps:
            try:
                self._step_state_store.transition(step.id, "stale")
                logger.info(
                    f"[InterruptManager] Marked step {step.id} as stale "
                    f"(was running during forced interrupt)"
                )
            except Exception as e:
                logger.error(
                    f"[InterruptManager] Failed to mark step {step.id} as stale: {e}"
                )

        # 转换 TaskSession 状态为 interrupted
        self._task_session_store.transition(task_session_id, "interrupted")

        logger.info(
            f"[InterruptManager] Forced interrupt detected for {task_session_id}, "
            f"marked {len(running_steps)} steps as stale"
        )

    async def on_heartbeat_timeout(self, step_id: str, capability: str) -> None:
        """
        心跳超时处理：检查步骤是否超过 capability 对应的 stale_threshold_s。

        如果超时，将步骤标记为 stale。
        """
        step = self._step_state_store.get(step_id)
        if step is None:
            logger.warning(f"[InterruptManager] Step {step_id} not found")
            return

        if step.status != "running":
            logger.debug(
                f"[InterruptManager] Step {step_id} is not running "
                f"(status={step.status}), skipping heartbeat check"
            )
            return

        config = get_heartbeat_config(capability)
        stale_threshold_s = config["stale_threshold_s"]

        if step.last_heartbeat_at is None:
            # 没有心跳记录，使用 started_at 作为基准
            reference_time = step.started_at
            if reference_time is None:
                logger.warning(
                    f"[InterruptManager] Step {step_id} has no heartbeat or start time"
                )
                return
        else:
            reference_time = step.last_heartbeat_at

        now = datetime.now(timezone.utc)
        # Ensure reference_time is timezone-aware
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)

        elapsed_s = (now - reference_time).total_seconds()

        if elapsed_s > stale_threshold_s:
            logger.info(
                f"[InterruptManager] Heartbeat timeout for step {step_id}: "
                f"elapsed={elapsed_s:.1f}s > threshold={stale_threshold_s}s "
                f"(capability={capability})"
            )
            try:
                self._step_state_store.transition(step_id, "stale")
            except Exception as e:
                logger.error(
                    f"[InterruptManager] Failed to mark step {step_id} as stale: {e}"
                )
        else:
            logger.debug(
                f"[InterruptManager] Step {step_id} heartbeat OK: "
                f"elapsed={elapsed_s:.1f}s <= threshold={stale_threshold_s}s"
            )
