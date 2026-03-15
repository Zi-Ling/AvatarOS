"""
PolicyEngine — operation approval and path protection.

Evaluates policy rules before each skill execution.
Supports: skill_requires_approval / path_write_forbidden /
          budget_exceeded_deny / high_side_effect_confirm
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PolicyDecision(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class PolicyRuleType(str, Enum):
    SKILL_REQUIRES_APPROVAL = "skill_requires_approval"
    PATH_WRITE_FORBIDDEN = "path_write_forbidden"
    BUDGET_EXCEEDED_DENY = "budget_exceeded_deny"
    HIGH_SIDE_EFFECT_CONFIRM = "high_side_effect_confirm"


class ApprovalState(str, Enum):
    PENDING = "pending"
    GRANTED = "granted"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PolicyRule:
    """A single policy rule with priority and match conditions."""
    rule_id: str
    rule_type: PolicyRuleType
    priority: int = 0                    # higher = evaluated first
    skill_pattern: Optional[str] = None  # glob pattern, e.g. "write_*"
    path_pattern: Optional[str] = None   # glob pattern, e.g. "/etc/*"
    decision: PolicyDecision = PolicyDecision.DENY
    reason: str = ""
    enabled: bool = True


@dataclass
class ApprovalRequest:
    """Pending approval request created when REQUIRE_APPROVAL is returned."""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    task_id: str = ""
    step_id: str = ""
    skill_name: str = ""
    rule_id: str = ""
    reason: str = ""
    state: ApprovalState = ApprovalState.PENDING
    created_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None
    resolved_by: Optional[str] = None   # user_id
    timeout_seconds: float = 300.0


# ---------------------------------------------------------------------------
# PolicyEngine
# ---------------------------------------------------------------------------

class PolicyEngine:
    """
    Evaluates policy rules for skill executions.

    Rules are sorted by priority (descending); first match wins.
    On evaluation error, defaults to DENY (fail-safe).
    """

    def __init__(self, rules: Optional[List[PolicyRule]] = None) -> None:
        self._lock = threading.RLock()
        self._rules: List[PolicyRule] = sorted(
            rules or [], key=lambda r: r.priority, reverse=True
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        skill_name: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[PolicyDecision, Optional[PolicyRule]]:
        """
        Evaluate all rules for a skill invocation.

        Returns (decision, matched_rule).
        Defaults to (ALLOW, None) if no rule matches.
        On exception, returns (DENY, None) — fail-safe.
        """
        try:
            with self._lock:
                rules_snapshot = list(self._rules)

            ctx = context or {}
            target_path = ctx.get("target_path") or params.get("path") or params.get("target_path")
            value_kind = ctx.get("value_kind", "")

            for rule in rules_snapshot:
                if not rule.enabled:
                    continue
                if self._match_rule(rule, skill_name, target_path, value_kind, ctx):
                    logger.info(
                        f"[PolicyEngine] rule={rule.rule_id} type={rule.rule_type} "
                        f"decision={rule.decision} skill={skill_name}"
                    )
                    return rule.decision, rule
            return PolicyDecision.ALLOW, None

        except Exception as exc:
            logger.error(f"[PolicyEngine] evaluation error for skill={skill_name}: {exc}", exc_info=True)
            return PolicyDecision.DENY, None

    def reload_rules(self, new_rules: List[PolicyRule]) -> None:
        """
        Hot-reload rules without restarting the service.
        Thread-safe.
        """
        with self._lock:
            self._rules = sorted(new_rules, key=lambda r: r.priority, reverse=True)
        logger.info(f"[PolicyEngine] reloaded {len(new_rules)} rules")

    def add_rule(self, rule: PolicyRule) -> None:
        with self._lock:
            self._rules.append(rule)
            self._rules.sort(key=lambda r: r.priority, reverse=True)

    def remove_rule(self, rule_id: str) -> bool:
        with self._lock:
            before = len(self._rules)
            self._rules = [r for r in self._rules if r.rule_id != rule_id]
            return len(self._rules) < before

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _match_rule(
        self,
        rule: PolicyRule,
        skill_name: str,
        target_path: Optional[str],
        value_kind: str,
        context: Dict[str, Any],
    ) -> bool:
        """Return True if the rule matches the current invocation context."""
        if rule.rule_type == PolicyRuleType.SKILL_REQUIRES_APPROVAL:
            if rule.skill_pattern:
                return fnmatch(skill_name, rule.skill_pattern)
            return True

        elif rule.rule_type == PolicyRuleType.PATH_WRITE_FORBIDDEN:
            # BINARY + path matches forbidden pattern → deny
            if target_path and rule.path_pattern:
                path_match = fnmatch(target_path, rule.path_pattern)
                try:
                    from app.avatar.runtime.graph.models.output_contract import ValueKind
                    if value_kind == ValueKind.BINARY or value_kind == ValueKind.BINARY.value:
                        return path_match
                except ImportError:
                    if value_kind == "binary":
                        return path_match
                return path_match

        elif rule.rule_type == PolicyRuleType.BUDGET_EXCEEDED_DENY:
            return bool(context.get("budget_exceeded", False))

        elif rule.rule_type == PolicyRuleType.HIGH_SIDE_EFFECT_CONFIRM:
            if rule.skill_pattern:
                return fnmatch(skill_name, rule.skill_pattern)

        return False
