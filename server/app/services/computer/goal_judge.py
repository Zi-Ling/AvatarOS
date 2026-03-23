# app/services/computer/goal_judge.py
"""GoalJudge — 任务级目标达成判定器."""

from __future__ import annotations

import json
import logging
from typing import Any

from .models import ActionHistoryEntry, GoalJudgeResult, GUIState

logger = logging.getLogger(__name__)

_GOAL_JUDGE_PROMPT = (
    "You are evaluating whether a user's goal has been achieved.\n"
    "Goal: {goal}\n\n"
    "Current screen state:\n"
    "- App: {app_name}\n"
    "- Window: {window_title}\n"
    "- Layout: {layout}\n"
    "- Key text: {extracted_text}\n\n"
    "Action history (last {history_count} steps):\n{history}\n\n"
    "Return a JSON object:\n"
    '{{"goal_achieved": true/false, "confidence": 0.0-1.0, '
    '"reason": "...", "remaining_steps_hint": "..." or null}}\n'
    "Return ONLY valid JSON."
)


class GoalJudge:
    """任务级目标达成判定器."""

    def __init__(self, llm_client: Any) -> None:
        self._llm = llm_client

    async def evaluate(
        self,
        goal: str,
        current_gui_state: GUIState,
        action_history: list[ActionHistoryEntry],
        screenshot_b64: str,
    ) -> GoalJudgeResult:
        """LLM 评估整体目标是否已达成."""
        history_lines = []
        for entry in action_history[-10:]:
            status = "✓" if entry.success else "✗"
            history_lines.append(
                f"  [{status}] Step {entry.step_index}: "
                f"{entry.action_type.value} → {entry.target_description}"
            )

        prompt = _GOAL_JUDGE_PROMPT.format(
            goal=goal,
            app_name=current_gui_state.app_name,
            window_title=current_gui_state.window_title,
            layout=current_gui_state.dominant_layout.value,
            extracted_text=current_gui_state.extracted_text[:500],
            history_count=len(history_lines),
            history="\n".join(history_lines) or "  (none)",
        )

        try:
            response = await self._llm.chat_with_vision(
                prompt=prompt, image_b64=screenshot_b64,
            )
            text = getattr(response, "content", str(response)).strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(
                    lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
                )
            data = json.loads(text)
            return GoalJudgeResult(
                goal_achieved=bool(data.get("goal_achieved", False)),
                confidence=float(data.get("confidence", 0.0)),
                reason=str(data.get("reason", "")),
                remaining_steps_hint=data.get("remaining_steps_hint"),
            )
        except Exception as e:
            logger.error("GoalJudge evaluation failed: %s", e)
            return GoalJudgeResult(
                goal_achieved=False,
                confidence=0.0,
                reason=f"Evaluation error: {e}",
            )
