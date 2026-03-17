# server/app/avatar/runtime/graph/managers/startup_recovery.py
"""
系统启动恢复逻辑。

策略可配 + 默认安全：
- auto_resume: 自动恢复
- prompt_user: 提示用户决定（默认，安全优先）
- skip: 跳过恢复
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class StartupRecovery:
    """系统启动时的 TaskSession 恢复管理。"""

    def __init__(
        self,
        task_session_store,
        interrupt_manager,
        resume_manager,
        recovery_policy: str = "prompt_user",
    ):
        self._task_session_store = task_session_store
        self._interrupt_manager = interrupt_manager
        self._resume_manager = resume_manager
        self._recovery_policy = recovery_policy  # auto_resume / prompt_user / skip

    async def recover_on_startup(self) -> dict:
        """
        系统启动时恢复逻辑：

        1. 加载所有非终态 TaskSession
        2. executing → interrupted (running steps → stale)
        3. 根据策略决定是否触发恢复
        """
        logger.info(
            f"[StartupRecovery] Starting recovery with policy={self._recovery_policy}"
        )

        non_terminal = self._task_session_store.load_non_terminal()
        recovery_report = {
            "total": len(non_terminal),
            "interrupted": [],
            "policy": self._recovery_policy,
            "auto_resumed": [],
            "errors": [],
        }

        # Step 1: Mark executing sessions as interrupted
        for session in non_terminal:
            if session.status == "executing":
                try:
                    await self._interrupt_manager.detect_forced_interrupt(session.id)
                    recovery_report["interrupted"].append(session.id)
                    logger.info(
                        f"[StartupRecovery] Marked {session.id} as interrupted"
                    )
                except Exception as e:
                    logger.error(
                        f"[StartupRecovery] Failed to interrupt {session.id}: {e}"
                    )
                    recovery_report["errors"].append(
                        {"session_id": session.id, "error": str(e)}
                    )

        # Step 2: Apply recovery policy
        if self._recovery_policy == "auto_resume":
            for session_id in recovery_report["interrupted"]:
                try:
                    await self._resume_manager.resume(session_id)
                    recovery_report["auto_resumed"].append(session_id)
                    logger.info(
                        f"[StartupRecovery] Auto-resumed {session_id}"
                    )
                except Exception as e:
                    logger.error(
                        f"[StartupRecovery] Auto-resume failed for {session_id}: {e}"
                    )
                    recovery_report["errors"].append(
                        {"session_id": session_id, "error": str(e)}
                    )
        elif self._recovery_policy == "skip":
            logger.info(
                "[StartupRecovery] Skip policy — no auto-resume"
            )
        else:  # prompt_user (default)
            logger.info(
                f"[StartupRecovery] {len(recovery_report['interrupted'])} "
                f"sessions need user decision"
            )

        logger.info(
            f"[StartupRecovery] Recovery complete: "
            f"total={recovery_report['total']}, "
            f"interrupted={len(recovery_report['interrupted'])}, "
            f"auto_resumed={len(recovery_report['auto_resumed'])}, "
            f"errors={len(recovery_report['errors'])}"
        )
        return recovery_report
