"""OrganizationPolicy — organization-specific policy rules.

Supports work hour limits, specific operation bans, and other
organization-level constraints. Integrates into PolicyEngineV2
as a pluggable evaluator.

Requirements: 10.2
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from typing import Any, Dict, List, Optional

from app.avatar.runtime.policy.policy_engine import PolicyDecisionV2

logger = logging.getLogger(__name__)


class OrgRuleType(str, Enum):
    """Types of organization-specific rules."""
    WORK_HOUR_LIMIT = "work_hour_limit"
    OPERATION_BAN = "operation_ban"
    RATE_LIMIT = "rate_limit"
    CUSTOM = "custom"


@dataclass
class OrganizationPolicyRule:
    """Single organization policy rule.

    Attributes:
        rule_id: Unique identifier.
        rule_type: Type of organization rule.
        action_pattern: Glob pattern matching skill/action names.
        allowed_hours: Tuple of (start_hour, end_hour) in 24h format. None = no restriction.
        banned_operations: List of explicitly banned operation patterns.
        max_operations_per_hour: Rate limit (0 = no limit).
        decision: Decision when rule triggers.
        reason: Human-readable description.
        enabled: Whether this rule is active.
        schema_version: Data schema version.
    """
    rule_id: str = ""
    rule_type: OrgRuleType = OrgRuleType.CUSTOM
    action_pattern: str = "*"
    allowed_hours_start: int = 0    # 0-23
    allowed_hours_end: int = 24     # 0-24 (24 = midnight)
    banned_operations: List[str] = field(default_factory=list)
    max_operations_per_hour: int = 0
    decision: PolicyDecisionV2 = PolicyDecisionV2.DENY
    reason: str = ""
    enabled: bool = True
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type.value,
            "action_pattern": self.action_pattern,
            "allowed_hours_start": self.allowed_hours_start,
            "allowed_hours_end": self.allowed_hours_end,
            "banned_operations": list(self.banned_operations),
            "max_operations_per_hour": self.max_operations_per_hour,
            "decision": self.decision.value,
            "reason": self.reason,
            "enabled": self.enabled,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrganizationPolicyRule":
        rule_type_val = data.get("rule_type", OrgRuleType.CUSTOM.value)
        try:
            rule_type = OrgRuleType(rule_type_val)
        except (ValueError, KeyError):
            rule_type = OrgRuleType.CUSTOM

        decision_val = data.get("decision", PolicyDecisionV2.DENY.value)
        try:
            decision = PolicyDecisionV2(decision_val)
        except (ValueError, KeyError):
            decision = PolicyDecisionV2.DENY

        return cls(
            rule_id=data.get("rule_id", ""),
            rule_type=rule_type,
            action_pattern=data.get("action_pattern", "*"),
            allowed_hours_start=data.get("allowed_hours_start", 0),
            allowed_hours_end=data.get("allowed_hours_end", 24),
            banned_operations=list(data.get("banned_operations", [])),
            max_operations_per_hour=data.get("max_operations_per_hour", 0),
            decision=decision,
            reason=data.get("reason", ""),
            enabled=data.get("enabled", True),
            schema_version=data.get("schema_version", "1.0.0"),
        )


class OrganizationPolicy:
    """Evaluates organization-specific policy rules.

    Supports:
    - Work hour limits: deny operations outside allowed hours
    - Operation bans: explicitly ban certain operations
    - Rate limits: limit operations per hour (tracked externally)

    Integrates into PolicyEngineV2 as a pluggable evaluator.
    """

    def __init__(self, rules: Optional[List[OrganizationPolicyRule]] = None) -> None:
        self._rules: List[OrganizationPolicyRule] = rules or []

    def add_rule(self, rule: OrganizationPolicyRule) -> None:
        self._rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.rule_id != rule_id]
        return len(self._rules) < before

    def evaluate(
        self,
        skill_name: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[PolicyDecisionV2, str]:
        """Evaluate organization rules for a skill invocation.

        Returns (decision, reason).
        Checks work hour limits, operation bans, and rate limits.
        """
        ctx = context or {}
        try:
            for rule in self._rules:
                if not rule.enabled:
                    continue

                # Check operation bans
                if rule.rule_type == OrgRuleType.OPERATION_BAN:
                    for banned in rule.banned_operations:
                        if fnmatch(skill_name, banned):
                            return (
                                PolicyDecisionV2.DENY,
                                f"operation '{skill_name}' banned by org policy: {rule.reason}",
                            )

                # Check work hour limits
                if rule.rule_type == OrgRuleType.WORK_HOUR_LIMIT:
                    if fnmatch(skill_name, rule.action_pattern):
                        current_hour = ctx.get(
                            "current_hour",
                            time.localtime().tm_hour,
                        )
                        if not self._is_within_hours(
                            current_hour,
                            rule.allowed_hours_start,
                            rule.allowed_hours_end,
                        ):
                            return (
                                rule.decision,
                                f"operation outside allowed hours "
                                f"({rule.allowed_hours_start}-{rule.allowed_hours_end}): "
                                f"{rule.reason}",
                            )

                # Check rate limits
                if rule.rule_type == OrgRuleType.RATE_LIMIT:
                    if fnmatch(skill_name, rule.action_pattern):
                        ops_count = ctx.get("operations_this_hour", 0)
                        if (
                            rule.max_operations_per_hour > 0
                            and ops_count >= rule.max_operations_per_hour
                        ):
                            return (
                                rule.decision,
                                f"rate limit exceeded ({ops_count}/{rule.max_operations_per_hour}): "
                                f"{rule.reason}",
                            )

            return PolicyDecisionV2.NO_MATCH, ""

        except Exception as exc:
            logger.error("[OrganizationPolicy] evaluation error: %s", exc)
            return PolicyDecisionV2.DENY, f"org policy error: {exc}"

    @staticmethod
    def _is_within_hours(current_hour: int, start: int, end: int) -> bool:
        """Check if current_hour is within [start, end) range."""
        if start <= end:
            return start <= current_hour < end
        # Wrap-around (e.g., 22-6 means 22,23,0,1,2,3,4,5)
        return current_hour >= start or current_hour < end

    def load_rules(self, raw_rules: List[Dict[str, Any]]) -> None:
        """Load rules from a list of dicts (parsed from config)."""
        self._rules = [OrganizationPolicyRule.from_dict(r) for r in raw_rules]

    @property
    def rules(self) -> List[OrganizationPolicyRule]:
        return list(self._rules)
