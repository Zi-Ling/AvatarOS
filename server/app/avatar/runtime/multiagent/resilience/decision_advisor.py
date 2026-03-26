"""DecisionAdvisor — dual-layer decision model for SupervisorRuntime.

Layer 1 (Rule Engine): deterministic, fast, reproducible — handles 95% of decisions.
Layer 2 (LLM Advisor): event-triggered, schema-constrained — only for high-entropy
situations that rules cannot resolve (split_task, replan_subgraph).

The Runtime is always the final authority. LLM outputs are validated against
schema + policy + budget before execution. LLM never directly mutates state.

All thresholds from MultiAgentConfig.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

from app.avatar.runtime.multiagent.config import MultiAgentConfig

logger = logging.getLogger(__name__)


# ── Advisory action types ───────────────────────────────────────────

class AdvisoryAction(str, Enum):
    """Actions the advisor can recommend. Runtime decides whether to execute."""
    SPLIT_TASK = "split_task"
    REPLAN_SUBGRAPH = "replan_subgraph"
    REROUTE_ROLE = "reroute_role"         # phase 2
    ROLE_MIX_SUGGESTION = "role_mix"      # phase 2
    NO_ADVICE = "no_advice"


@dataclass
class Advisory:
    """A structured, schema-constrained recommendation from the advisor.

    The Runtime validates this before execution — the advisor has no
    direct mutation authority.
    """
    action: AdvisoryAction
    node_id: str = ""
    confidence: float = 0.0               # 0-1, advisor's self-assessed confidence
    reason: str = ""
    proposed_changes: Dict[str, Any] = field(default_factory=dict)
    # For split_task: list of {goal, role, expected_output}
    sub_tasks: List[Dict[str, Any]] = field(default_factory=list)
    # For reroute_role: suggested new role
    suggested_role: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "node_id": self.node_id,
            "confidence": self.confidence,
            "reason": self.reason,
            "proposed_changes": self.proposed_changes,
            "sub_tasks": self.sub_tasks,
            "suggested_role": self.suggested_role,
        }



# ── Advisor context (what the advisor sees) ─────────────────────────

@dataclass
class AdvisorContext:
    """Structured context passed to the advisor at decision points.

    Contains only what's needed for the specific decision — not the
    entire graph state. This keeps LLM token usage minimal.
    """
    node_id: str = ""
    node_description: str = ""
    node_role: str = ""
    failure_count: int = 0
    error_messages: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    upstream_summaries: Dict[str, str] = field(default_factory=dict)
    # Graph-level context (only for replan)
    pending_node_count: int = 0
    failed_node_count: int = 0
    completed_node_count: int = 0
    stalled: bool = False


# ── Abstract advisor interface ──────────────────────────────────────

class DecisionAdvisor(ABC):
    """Abstract interface for decision advisors.

    Implementations:
    - RuleOnlyAdvisor: deterministic rules, no LLM (default)
    - LLMDecisionAdvisor: calls LLM for split/replan decisions
    """

    @abstractmethod
    async def advise_split(self, ctx: AdvisorContext) -> Advisory:
        """Should this failed task be split into sub-tasks?

        Called when: retry_same, reroute, review_first all exhausted.
        """
        ...

    @abstractmethod
    async def advise_replan(self, ctx: AdvisorContext) -> Advisory:
        """Should the remaining graph be re-decomposed?

        Called when: graph is stalled (no progress for N rounds),
        or multiple tasks failing with related errors.
        """
        ...



# ── RuleOnlyAdvisor (default, no LLM) ──────────────────────────────

class RuleOnlyAdvisor(DecisionAdvisor):
    """Deterministic advisor — uses heuristics, never calls LLM.

    Split heuristic: if description is long (> threshold chars) or has
    multiple acceptance criteria, recommend split.

    Replan heuristic: if failed_node_count > threshold fraction of total,
    recommend replan.
    """

    def __init__(self, config: Optional[MultiAgentConfig] = None) -> None:
        self._cfg = config or MultiAgentConfig()

    async def advise_split(self, ctx: AdvisorContext) -> Advisory:
        # Heuristic: split if description is complex or many criteria
        desc_len = len(ctx.node_description)
        criteria_count = len(ctx.acceptance_criteria)

        if desc_len > self._cfg.intent_summary_max_chars or criteria_count > self._cfg.advisor_split_criteria_threshold:
            return Advisory(
                action=AdvisoryAction.SPLIT_TASK,
                node_id=ctx.node_id,
                confidence=0.6,
                reason=(
                    f"Task appears complex (desc={desc_len} chars, "
                    f"criteria={criteria_count}), suggesting split"
                ),
                sub_tasks=[
                    {"goal": f"Part 1 of: {ctx.node_description[:100]}", "role": ctx.node_role},
                    {"goal": f"Part 2 of: {ctx.node_description[:100]}", "role": ctx.node_role},
                ],
            )

        return Advisory(
            action=AdvisoryAction.NO_ADVICE,
            node_id=ctx.node_id,
            confidence=0.8,
            reason="Task not complex enough to warrant split",
        )

    async def advise_replan(self, ctx: AdvisorContext) -> Advisory:
        total = ctx.pending_node_count + ctx.failed_node_count + ctx.completed_node_count
        if total == 0:
            return Advisory(action=AdvisoryAction.NO_ADVICE, confidence=1.0)

        failure_ratio = ctx.failed_node_count / total
        if failure_ratio > self._cfg.advisor_replan_failure_ratio or ctx.stalled:
            return Advisory(
                action=AdvisoryAction.REPLAN_SUBGRAPH,
                confidence=0.5,
                reason=(
                    f"High failure ratio ({failure_ratio:.0%}) or stalled graph, "
                    f"suggesting replan"
                ),
            )

        return Advisory(
            action=AdvisoryAction.NO_ADVICE,
            confidence=0.8,
            reason=f"Failure ratio ({failure_ratio:.0%}) within acceptable range",
        )



# ── LLM client protocol ─────────────────────────────────────────────

class LLMClient(Protocol):
    """Minimal LLM client interface."""
    async def chat(
        self, messages: List[Dict[str, str]], temperature: float = 0.3,
    ) -> Any: ...


# ── LLMDecisionAdvisor ──────────────────────────────────────────────

_SPLIT_SYSTEM_PROMPT = (
    "You are a task decomposition advisor. A task has failed multiple times "
    "and cannot be completed as-is. Analyze the task and suggest how to split "
    "it into 2-4 smaller, independent sub-tasks.\n\n"
    "Output a JSON object:\n"
    '{{"should_split": true/false, "confidence": 0.0-1.0, "reason": "...", '
    '"sub_tasks": [{{"goal": "...", "role": "researcher|executor|writer", '
    '"expected_output": {{"type": "...", "description": "..."}}}}]}}\n\n'
    "Rules:\n"
    "- Only recommend split if the task is genuinely decomposable\n"
    "- Each sub-task must be independently completable\n"
    "- Preserve the original task's acceptance criteria across sub-tasks\n"
    "- Return ONLY the JSON object"
)

_REPLAN_SYSTEM_PROMPT = (
    "You are a task graph advisor. The current execution graph is stalled "
    "with multiple failures. Analyze the situation and recommend whether "
    "to re-decompose the remaining work.\n\n"
    "Output a JSON object:\n"
    '{{"should_replan": true/false, "confidence": 0.0-1.0, "reason": "...", '
    '"suggested_approach": "..."}}\n\n'
    "Rules:\n"
    "- Only recommend replan if the current decomposition is fundamentally wrong\n"
    "- If individual tasks are failing due to transient issues, don't replan\n"
    "- Return ONLY the JSON object"
)


class LLMDecisionAdvisor(DecisionAdvisor):
    """LLM-powered advisor for split and replan decisions.

    Only called when rules cannot resolve the situation. Outputs are
    schema-validated before being returned to the Runtime.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        config: Optional[MultiAgentConfig] = None,
    ) -> None:
        self._llm = llm_client
        self._cfg = config or MultiAgentConfig()
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    async def advise_split(self, ctx: AdvisorContext) -> Advisory:
        user_msg = (
            f"Task ID: {ctx.node_id}\n"
            f"Description: {ctx.node_description}\n"
            f"Role: {ctx.node_role}\n"
            f"Failure count: {ctx.failure_count}\n"
            f"Errors: {'; '.join(ctx.error_messages[-3:])}\n"
            f"Acceptance criteria: {ctx.acceptance_criteria}\n"
        )
        if ctx.upstream_summaries:
            upstream_lines = [
                f"- {k}: {v}" for k, v in list(ctx.upstream_summaries.items())[:5]
            ]
            user_msg += f"Upstream results:\n" + "\n".join(upstream_lines)

        try:
            self._call_count += 1
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": _SPLIT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=self._cfg.decompose_temperature,
            )
            raw = self._strip_fences(response.content)
            data = json.loads(raw)

            if not data.get("should_split", False):
                return Advisory(
                    action=AdvisoryAction.NO_ADVICE,
                    node_id=ctx.node_id,
                    confidence=data.get("confidence", 0.5),
                    reason=data.get("reason", "LLM advises no split"),
                )

            sub_tasks = data.get("sub_tasks", [])
            if not sub_tasks or not isinstance(sub_tasks, list):
                return Advisory(
                    action=AdvisoryAction.NO_ADVICE,
                    node_id=ctx.node_id,
                    confidence=0.3,
                    reason="LLM returned no valid sub_tasks",
                )

            # Validate sub-task schema
            validated = []
            for st in sub_tasks[:self._cfg.max_subtasks]:
                if not isinstance(st, dict) or not st.get("goal"):
                    continue
                role = st.get("role", ctx.node_role)
                if role not in ("researcher", "executor", "writer"):
                    role = ctx.node_role
                validated.append({
                    "goal": st["goal"],
                    "role": role,
                    "expected_output": st.get("expected_output", {}),
                })

            if not validated:
                return Advisory(
                    action=AdvisoryAction.NO_ADVICE,
                    node_id=ctx.node_id,
                    confidence=0.3,
                    reason="LLM sub_tasks failed validation",
                )

            return Advisory(
                action=AdvisoryAction.SPLIT_TASK,
                node_id=ctx.node_id,
                confidence=data.get("confidence", 0.7),
                reason=data.get("reason", "LLM recommends split"),
                sub_tasks=validated,
            )

        except Exception as exc:
            logger.warning("[LLMDecisionAdvisor] split advice failed: %s", exc)
            return Advisory(
                action=AdvisoryAction.NO_ADVICE,
                node_id=ctx.node_id,
                confidence=0.0,
                reason=f"LLM call failed: {exc}",
            )

    async def advise_replan(self, ctx: AdvisorContext) -> Advisory:
        user_msg = (
            f"Graph status:\n"
            f"- Pending: {ctx.pending_node_count}\n"
            f"- Failed: {ctx.failed_node_count}\n"
            f"- Completed: {ctx.completed_node_count}\n"
            f"- Stalled: {ctx.stalled}\n"
        )
        if ctx.error_messages:
            user_msg += f"Recent errors: {'; '.join(ctx.error_messages[-5:])}\n"

        try:
            self._call_count += 1
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": _REPLAN_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=self._cfg.decompose_temperature,
            )
            raw = self._strip_fences(response.content)
            data = json.loads(raw)

            if data.get("should_replan", False):
                return Advisory(
                    action=AdvisoryAction.REPLAN_SUBGRAPH,
                    confidence=data.get("confidence", 0.5),
                    reason=data.get("reason", "LLM recommends replan"),
                    proposed_changes={
                        "suggested_approach": data.get("suggested_approach", ""),
                    },
                )

            return Advisory(
                action=AdvisoryAction.NO_ADVICE,
                confidence=data.get("confidence", 0.5),
                reason=data.get("reason", "LLM advises no replan"),
            )

        except Exception as exc:
            logger.warning("[LLMDecisionAdvisor] replan advice failed: %s", exc)
            return Advisory(
                action=AdvisoryAction.NO_ADVICE,
                confidence=0.0,
                reason=f"LLM call failed: {exc}",
            )

    @staticmethod
    def _strip_fences(text: str) -> str:
        raw = text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if "```" in raw:
                raw = raw[:raw.rfind("```")]
        return raw.strip()
