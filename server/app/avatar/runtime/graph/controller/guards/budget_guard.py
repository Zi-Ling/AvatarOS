"""
BudgetGuard — Planner budget check, usage tracking, and default limits.

Extracted from GraphController to keep budget logic self-contained.

Design: A single unified budget for all tasks. The planner naturally uses
fewer steps for simple tasks and more for complex ones — no pre-classification
needed. This follows the industry-standard approach (OpenAI, Anthropic, Google)
where the LLM itself decides how many steps to take.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.graph_patch import GraphPatch

logger = logging.getLogger(__name__)


class BudgetGuard:
    """
    Tracks planner usage (tokens, calls, cost) and enforces budget limits.

    Two layers of budget:
    1. Explicit limits — caller-provided max_planner_tokens / max_planner_calls / max_planner_cost.
    2. Effective defaults — if caller provides None, BudgetGuard applies unified defaults.

    Usage is reset per-task via reset().
    """

    # ── Unified defaults ────────────────────────────────────────────────
    # Single budget for all tasks. The planner naturally self-regulates:
    # simple tasks finish in 1-3 steps, complex tasks use more.
    DEFAULT_MAX_CALLS = 15
    DEFAULT_MAX_COST = 0.20

    def __init__(
        self,
        *,
        max_planner_tokens: Optional[int] = None,
        max_planner_calls: Optional[int] = None,
        max_planner_cost: Optional[float] = None,
    ):
        # Caller-provided explicit limits (may be None)
        self._explicit_tokens = max_planner_tokens
        self._explicit_calls = max_planner_calls
        self._explicit_cost = max_planner_cost

        # Effective limits (with defaults applied)
        self.effective_max_calls = (
            max_planner_calls if max_planner_calls is not None
            else self.DEFAULT_MAX_CALLS
        )
        self.effective_max_cost = (
            max_planner_cost if max_planner_cost is not None
            else self.DEFAULT_MAX_COST
        )

        # Accumulated usage — reset per task
        self._usage: Dict[str, Any] = {
            'total_tokens': 0,
            'total_calls': 0,
            'total_cost': 0.0,
        }

    # ── Public API ──────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset usage counters for a new task."""
        self._usage = {'total_tokens': 0, 'total_calls': 0, 'total_cost': 0.0}
        self.effective_max_calls = (
            self._explicit_calls if self._explicit_calls is not None
            else self.DEFAULT_MAX_CALLS
        )
        self.effective_max_cost = (
            self._explicit_cost if self._explicit_cost is not None
            else self.DEFAULT_MAX_COST
        )

    def track(self, patch: 'GraphPatch') -> None:
        """Record usage from a single planner invocation."""
        metadata = patch.metadata or {}
        self._usage['total_tokens'] += metadata.get('tokens_used', 0)
        self._usage['total_calls'] += 1
        self._usage['total_cost'] += metadata.get('cost', 0.0)
        logger.debug(
            f"[BudgetGuard] usage: tokens={self._usage['total_tokens']}, "
            f"calls={self._usage['total_calls']}, "
            f"cost=${self._usage['total_cost']:.4f}"
        )

    def check(self) -> Optional[str]:
        """
        Check all budget limits. Returns error message if any exceeded, else None.
        """
        # Explicit token limit
        if self._explicit_tokens and self._usage['total_tokens'] >= self._explicit_tokens:
            return (
                f"Token limit exceeded: {self._usage['total_tokens']} >= "
                f"{self._explicit_tokens}"
            )
        # Effective call limit
        if self._usage['total_calls'] >= self.effective_max_calls:
            return (
                f"Call budget exceeded: "
                f"{self._usage['total_calls']} >= {self.effective_max_calls}"
            )
        # Effective cost limit
        if self._usage['total_cost'] >= self.effective_max_cost:
            return (
                f"Cost budget exceeded: "
                f"${self._usage['total_cost']:.4f} >= ${self.effective_max_cost:.4f}"
            )
        # Explicit call limit (if different from effective)
        if self._explicit_calls and self._usage['total_calls'] >= self._explicit_calls:
            return (
                f"Explicit call limit exceeded: {self._usage['total_calls']} >= "
                f"{self._explicit_calls}"
            )
        # Explicit cost limit
        if self._explicit_cost and self._usage['total_cost'] >= self._explicit_cost:
            return (
                f"Explicit cost limit exceeded: ${self._usage['total_cost']:.4f} >= "
                f"${self._explicit_cost:.4f}"
            )
        return None

    def get_usage(self) -> Dict[str, Any]:
        """Return a copy of current usage stats."""
        return {
            **self._usage,
            'effective_max_calls': self.effective_max_calls,
            'effective_max_cost': self.effective_max_cost,
        }
