"""
ExecutionNarrative — real-time user-facing execution summary.

Translates internal execution state into human-readable narrative.
Pushed via WebSocket as 'execution_narrative_update' events.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Verdict translation
# ---------------------------------------------------------------------------

VERDICT_TRANSLATIONS: Dict[str, str] = {
    "PASS": "验证通过",
    "passed": "验证通过",
    "FAIL": "验证失败",
    "failed": "验证失败",
    "UNCERTAIN": "结果不确定，需人工确认",
    "uncertain": "结果不确定，需人工确认",
    "partial_success": "部分完成",
    "PARTIAL_SUCCESS": "部分完成",
    "completed": "已完成",
    "repair_exhausted": "修复次数已耗尽",
}


# ---------------------------------------------------------------------------
# ExecutionNarrative dataclass
# ---------------------------------------------------------------------------

@dataclass
class ExecutionNarrative:
    """
    User-facing execution narrative.
    Updated after each step completion and after CompletionGate verdict.
    """
    goal: str
    completed: List[str] = field(default_factory=list)      # completed sub-goal descriptions
    remaining: List[str] = field(default_factory=list)      # remaining sub-goal descriptions
    verification_result: Optional[str] = None               # translated verdict string
    final_artifacts: List[Dict[str, Any]] = field(default_factory=list)
    repair_hint: Optional[str] = None                       # shown during repair loop
    session_id: Optional[str] = None
    task_id: Optional[str] = None


# ---------------------------------------------------------------------------
# NarrativeManager — manages lifecycle and WebSocket push
# ---------------------------------------------------------------------------

class NarrativeManager:
    """
    Manages ExecutionNarrative updates and WebSocket push.

    Usage:
        manager = NarrativeManager(session_id, task_id, socket_manager)
        await manager.on_step_completed("已生成分析报告")
        await manager.on_verdict("PASS", artifacts=[...])
        await manager.on_repair_triggered("正在重新生成文件")
    """

    MAX_PUSH_RETRIES = 3

    def __init__(
        self,
        session_id: str,
        task_id: str,
        goal: str,
        sub_goals: Optional[List[str]] = None,
        socket_manager: Optional[Any] = None,
    ) -> None:
        self.narrative = ExecutionNarrative(
            goal=goal,
            remaining=list(sub_goals or []),
            session_id=session_id,
            task_id=task_id,
        )
        self._socket_manager = socket_manager

    async def on_step_completed(self, description: str) -> None:
        """Called after each step completes successfully."""
        self.narrative.completed.append(description)
        # Remove from remaining if present
        if description in self.narrative.remaining:
            self.narrative.remaining.remove(description)
        self.narrative.repair_hint = None
        await self._push()

    async def on_verdict(
        self,
        verdict: str,
        artifacts: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Called after CompletionGate returns a verdict."""
        self.narrative.verification_result = VERDICT_TRANSLATIONS.get(verdict, verdict)
        if artifacts:
            self.narrative.final_artifacts = artifacts
        self.narrative.repair_hint = None
        await self._push()

    async def on_repair_triggered(self, repair_hint: str) -> None:
        """
        Called when repair loop is triggered.
        Shows user-friendly hint without exposing strategy names.
        """
        self.narrative.repair_hint = f"正在尝试修复：{repair_hint}"
        await self._push()

    def to_dict(self) -> Dict[str, Any]:
        n = self.narrative
        return {
            "goal": n.goal,
            "completed": n.completed,
            "remaining": n.remaining,
            "verification_result": n.verification_result,
            "final_artifacts": n.final_artifacts,
            "repair_hint": n.repair_hint,
            "session_id": n.session_id,
            "task_id": n.task_id,
        }

    async def _push(self) -> None:
        """Push narrative update via WebSocket. Retries 3 times, then silently fails."""
        if self._socket_manager is None:
            return
        payload = self.to_dict()
        for attempt in range(self.MAX_PUSH_RETRIES):
            try:
                await self._socket_manager.emit(
                    "execution_narrative_update",
                    payload,
                    room=self.narrative.session_id,
                )
                return
            except Exception as exc:
                logger.warning(
                    f"[NarrativeManager] push attempt {attempt + 1} failed: {exc}"
                )
                if attempt < self.MAX_PUSH_RETRIES - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))
        # Silent failure after retries — does not affect main flow
        logger.debug("[NarrativeManager] push failed after retries, silently continuing")
