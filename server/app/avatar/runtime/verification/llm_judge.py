"""
LLMJudge — semantic verification via LLM for UNCERTAIN gate decisions.

Security:
- goal and reason fields are length-truncated before prompt construction
- Special characters are escaped to prevent prompt injection
- Max prompt size enforced at 2000 chars

Integration:
- Uses the same LLM client as GraphPlanner (passed in constructor)
- Falls back gracefully if LLM is unavailable
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

_MAX_GOAL_CHARS = 300
_MAX_REASON_CHARS = 500
_MAX_PROMPT_CHARS = 2000

# Characters that could break prompt structure
_INJECTION_PATTERN = re.compile(r'[<>{}|\\`]')


def _sanitize(text: str, max_chars: int) -> str:
    """Truncate and escape potentially dangerous characters."""
    text = text[:max_chars]
    text = _INJECTION_PATTERN.sub("", text)
    return text.strip()


class LLMJudge:
    """
    LLM-based semantic judge for UNCERTAIN verification decisions.

    Returns "pass" or "fail" based on LLM assessment of whether
    the goal has been achieved given the verification evidence.
    """

    def __init__(self, llm_client: Any) -> None:
        self._llm = llm_client

    async def judge(self, prompt: str) -> str:
        """
        Ask the LLM to judge whether the task is complete.

        Args:
            prompt: Pre-built prompt from CompletionGate (already contains
                    verification results summary).

        Returns:
            "pass" if LLM judges task complete, "fail" otherwise.

        Raises:
            Exception if LLM call fails (caller handles per risk_level).
        """
        safe_prompt = prompt[:_MAX_PROMPT_CHARS]
        full_prompt = (
            f"{safe_prompt}\n\n"
            "Based on the verification results above, has the task been completed successfully?\n"
            "Answer with exactly one word: 'pass' or 'fail'."
        )

        response = await self._call_llm(full_prompt)
        verdict = response.strip().lower()
        if "pass" in verdict:
            return "pass"
        return "fail"

    async def judge_goal(self, goal: str, evidence_summary: str) -> str:
        """
        Judge task completion from goal + evidence summary.

        Args:
            goal: Original task goal (will be sanitized).
            evidence_summary: Summary of verification evidence (will be sanitized).

        Returns:
            "pass" or "fail".
        """
        safe_goal = _sanitize(goal, _MAX_GOAL_CHARS)
        safe_evidence = _sanitize(evidence_summary, _MAX_REASON_CHARS)

        prompt = (
            f"Task goal: {safe_goal}\n\n"
            f"Verification evidence:\n{safe_evidence}\n\n"
            "Has the task been completed successfully? Answer: pass or fail."
        )
        return await self.judge(prompt)

    async def _call_llm(self, prompt: str) -> str:
        """Call the underlying LLM client."""
        try:
            # Support both sync .call() and async .acall() / .agenerate()
            if hasattr(self._llm, "acall"):
                return await self._llm.acall(prompt)
            elif hasattr(self._llm, "agenerate"):
                result = await self._llm.agenerate([prompt])
                return result.generations[0][0].text
            elif hasattr(self._llm, "call"):
                import asyncio
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, self._llm.call, prompt)
            else:
                raise ValueError(f"LLM client {type(self._llm)} has no supported call method")
        except Exception as exc:
            logger.error(f"[LLMJudge] LLM call failed: {exc}")
            raise
