"""RepairLoop — 5 repair actions for failed subtasks.

Actions (tried in config-defined order):
1. retry_same   — retry on the same worker
2. reroute      — assign to a different worker
3. split        — decompose into smaller sub-tasks (advisor-assisted)
4. review_first — send to reviewer before re-execution
5. replan       — re-decompose the remaining graph (advisor-assisted)

split and replan are the two DecisionAdvisor call points. When a
DecisionAdvisor is attached, these actions consult the advisor for
structured recommendations. Without an advisor, they use simple
heuristics (always viable, metadata carries error context).

All limits from MultiAgentConfig.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.avatar.runtime.multiagent.config import MultiAgentConfig
from app.avatar.runtime.multiagent.resilience.health_monitor import AgentHealthMonitor, HealthStatus

logger = logging.getLogger(__name__)


class RepairAction(str, Enum):
    RETRY_SAME = "retry_same"
    REROUTE = "reroute"
    SPLIT = "split"
    REVIEW_FIRST = "review_first"
    REPLAN = "replan"


@dataclass
class RepairDecision:
    """Result of repair evaluation."""
    action: RepairAction
    node_id: str
    worker_id: str = ""
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class RepairLoop:
    """Evaluates failed tasks and decides on repair actions.

    Optionally accepts a DecisionAdvisor for split/replan decisions.
    The advisor is only consulted when those specific actions are reached
    in the repair order — not every round.
    """

    def __init__(
        self,
        config: Optional[MultiAgentConfig] = None,
        health_monitor: Optional[AgentHealthMonitor] = None,
        decision_advisor: Optional[Any] = None,  # DecisionAdvisor
    ) -> None:
        self._cfg = config or MultiAgentConfig()
        self._health = health_monitor
        self._advisor = decision_advisor
        # Per-node repair attempt counts
        self._attempts: Dict[str, int] = {}
        # Per-node action history
        self._history: Dict[str, List[RepairAction]] = {}
        # Per-node error messages (for advisor context)
        self._errors: Dict[str, List[str]] = {}
        # Pending advisory results (from async advisor calls)
        self._pending_advisories: Dict[str, Any] = {}

    def evaluate(
        self,
        node_id: str,
        worker_id: str,
        error_message: str = "",
    ) -> Optional[RepairDecision]:
        """Decide the next repair action for a failed node.

        Returns None if all repair options exhausted.
        """
        attempts = self._attempts.get(node_id, 0)
        if attempts >= self._cfg.repair_max_actions_per_task:
            logger.info(
                "[RepairLoop] Node %s exhausted repair budget (%d/%d)",
                node_id, attempts, self._cfg.repair_max_actions_per_task,
            )
            return None

        # Track errors for advisor context
        if error_message:
            self._errors.setdefault(node_id, []).append(error_message)

        past_actions = self._history.get(node_id, [])

        # Walk through configured action order, skip already-tried actions
        for action_name in self._cfg.repair_action_order:
            try:
                action = RepairAction(action_name)
            except ValueError:
                continue

            if action in past_actions:
                continue

            # Check if action is viable
            decision = self._check_viable(action, node_id, worker_id, error_message)
            if decision is not None:
                self._attempts[node_id] = attempts + 1
                self._history.setdefault(node_id, []).append(action)
                return decision

        logger.info("[RepairLoop] No viable repair action for node %s", node_id)
        return None

    async def evaluate_async(
        self,
        node_id: str,
        worker_id: str,
        error_message: str = "",
        node_description: str = "",
        node_role: str = "",
        acceptance_criteria: Optional[List[str]] = None,
        upstream_summaries: Optional[Dict[str, str]] = None,
        graph_stats: Optional[Dict[str, int]] = None,
    ) -> Optional[RepairDecision]:
        """Async version that can consult DecisionAdvisor for split/replan.

        Same logic as evaluate(), but when split or replan is reached and
        an advisor is available, it calls the advisor asynchronously.
        """
        attempts = self._attempts.get(node_id, 0)
        if attempts >= self._cfg.repair_max_actions_per_task:
            return None

        if error_message:
            self._errors.setdefault(node_id, []).append(error_message)

        past_actions = self._history.get(node_id, [])

        for action_name in self._cfg.repair_action_order:
            try:
                action = RepairAction(action_name)
            except ValueError:
                continue

            if action in past_actions:
                continue

            # For split/replan, consult advisor if available
            if action == RepairAction.SPLIT and self._advisor:
                decision = await self._advise_split(
                    node_id, worker_id, error_message,
                    node_description, node_role,
                    acceptance_criteria or [],
                    upstream_summaries or {},
                )
                # Record in history regardless of outcome (don't re-ask)
                self._history.setdefault(node_id, []).append(action)
                if decision is not None:
                    self._attempts[node_id] = attempts + 1
                    return decision
                continue  # advisor said no, try next action

            if action == RepairAction.REPLAN and self._advisor:
                decision = await self._advise_replan(
                    node_id, graph_stats or {},
                )
                self._history.setdefault(node_id, []).append(action)
                if decision is not None:
                    self._attempts[node_id] = attempts + 1
                    return decision
                continue

            decision = self._check_viable(action, node_id, worker_id, error_message)
            if decision is not None:
                self._attempts[node_id] = attempts + 1
                self._history.setdefault(node_id, []).append(action)
                return decision

        return None

    def _check_viable(
        self,
        action: RepairAction,
        node_id: str,
        worker_id: str,
        error_message: str,
    ) -> Optional[RepairDecision]:
        """Check if a specific repair action is viable."""
        if action == RepairAction.RETRY_SAME:
            if self._health:
                wh = self._health.get(worker_id)
                if wh and wh.health_status == HealthStatus.BROKEN:
                    return None
            return RepairDecision(
                action=action, node_id=node_id, worker_id=worker_id,
                reason="retry on same worker",
            )

        elif action == RepairAction.REROUTE:
            return RepairDecision(
                action=action, node_id=node_id, worker_id="",
                reason="reroute to different worker",
            )

        elif action == RepairAction.SPLIT:
            # Without advisor: always viable, carry error context
            return RepairDecision(
                action=action, node_id=node_id,
                reason="split into smaller sub-tasks",
                metadata={"original_error": error_message},
            )

        elif action == RepairAction.REVIEW_FIRST:
            return RepairDecision(
                action=action, node_id=node_id,
                reason="send to reviewer before retry",
            )

        elif action == RepairAction.REPLAN:
            return RepairDecision(
                action=action, node_id=node_id,
                reason="re-decompose remaining graph",
                metadata={"original_error": error_message},
            )

        return None

    async def _advise_split(
        self,
        node_id: str,
        worker_id: str,
        error_message: str,
        description: str,
        role: str,
        criteria: List[str],
        upstream: Dict[str, str],
    ) -> Optional[RepairDecision]:
        """Consult advisor for split decision."""
        from app.avatar.runtime.multiagent.resilience.decision_advisor import AdvisorContext, AdvisoryAction

        ctx = AdvisorContext(
            node_id=node_id,
            node_description=description,
            node_role=role,
            failure_count=len(self._errors.get(node_id, [])),
            error_messages=self._errors.get(node_id, []),
            acceptance_criteria=criteria,
            upstream_summaries=upstream,
        )

        advisory = await self._advisor.advise_split(ctx)

        if advisory.action == AdvisoryAction.SPLIT_TASK and advisory.sub_tasks:
            return RepairDecision(
                action=RepairAction.SPLIT,
                node_id=node_id,
                reason=advisory.reason,
                metadata={
                    "sub_tasks": advisory.sub_tasks,
                    "confidence": advisory.confidence,
                    "advisor_source": "decision_advisor",
                },
            )

        logger.info(
            "[RepairLoop] Advisor declined split for %s: %s",
            node_id, advisory.reason,
        )
        return None

    async def _advise_replan(
        self,
        node_id: str,
        graph_stats: Dict[str, int],
    ) -> Optional[RepairDecision]:
        """Consult advisor for replan decision."""
        from app.avatar.runtime.multiagent.resilience.decision_advisor import AdvisorContext, AdvisoryAction

        ctx = AdvisorContext(
            node_id=node_id,
            pending_node_count=graph_stats.get("pending", 0),
            failed_node_count=graph_stats.get("failed", 0),
            completed_node_count=graph_stats.get("completed", 0),
            stalled=graph_stats.get("stalled", False),
            error_messages=self._errors.get(node_id, []),
        )

        advisory = await self._advisor.advise_replan(ctx)

        if advisory.action == AdvisoryAction.REPLAN_SUBGRAPH:
            return RepairDecision(
                action=RepairAction.REPLAN,
                node_id=node_id,
                reason=advisory.reason,
                metadata={
                    "confidence": advisory.confidence,
                    "proposed_changes": advisory.proposed_changes,
                    "advisor_source": "decision_advisor",
                },
            )

        logger.info(
            "[RepairLoop] Advisor declined replan for %s: %s",
            node_id, advisory.reason,
        )
        return None

    def get_history(self, node_id: str) -> List[RepairAction]:
        return list(self._history.get(node_id, []))

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_repairs": sum(self._attempts.values()),
            "nodes_repaired": len(self._attempts),
            "history": {
                nid: [a.value for a in actions]
                for nid, actions in self._history.items()
            },
        }
