"""ApprovalPolicy — defines which operations require human approval.

Each rule specifies an action_pattern, approval_level, timeout,
and default_on_timeout (fail-closed by default).

Requirements: 10.3
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Dict, List, Optional

from app.avatar.runtime.policy.policy_engine import (
    PolicyDecisionV2,
    PolicyTypeV2,
)

logger = logging.getLogger(__name__)


@dataclass
class ApprovalPolicyRule:
    """Single approval policy rule.

    Attributes:
        rule_id: Unique identifier for this rule.
        action_pattern: Glob pattern matching action/skill names (e.g. "write_*").
        approval_level: Required approval level ("user", "admin", "team_lead").
        timeout: Seconds to wait for approval before applying default_on_timeout.
        default_on_timeout: Action when approval times out — "deny" (default, fail-closed) or "allow".
        enabled: Whether this rule is active.
        reason: Human-readable description of why approval is needed.
        schema_version: Data schema version.
    """
    rule_id: str = ""
    action_pattern: str = "*"
    approval_level: str = "user"
    timeout: float = 300.0
    default_on_timeout: str = "deny"
    enabled: bool = True
    reason: str = ""
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "action_pattern": self.action_pattern,
            "approval_level": self.approval_level,
            "timeout": self.timeout,
            "default_on_timeout": self.default_on_timeout,
            "enabled": self.enabled,
            "reason": self.reason,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApprovalPolicyRule":
        return cls(
            rule_id=data.get("rule_id", ""),
            action_pattern=data.get("action_pattern", "*"),
            approval_level=data.get("approval_level", "user"),
            timeout=data.get("timeout", 300.0),
            default_on_timeout=data.get("default_on_timeout", "deny"),
            enabled=data.get("enabled", True),
            reason=data.get("reason", ""),
            schema_version=data.get("schema_version", "1.0.0"),
        )


class ApprovalPolicy:
    """Evaluates whether an operation requires human approval.

    Integrates into PolicyEngineV2 as a pluggable evaluator.
    """

    def __init__(self, rules: Optional[List[ApprovalPolicyRule]] = None) -> None:
        self._rules: List[ApprovalPolicyRule] = rules or []

    def add_rule(self, rule: ApprovalPolicyRule) -> None:
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
        """Evaluate approval rules for a skill invocation.

        Returns (decision, reason).
        If any enabled rule matches, returns REQUIRE_APPROVAL.
        If no rule matches, returns NO_MATCH.
        """
        try:
            for rule in self._rules:
                if not rule.enabled:
                    continue
                if fnmatch(skill_name, rule.action_pattern):
                    logger.info(
                        "[ApprovalPolicy] rule=%s matched skill=%s level=%s",
                        rule.rule_id, skill_name, rule.approval_level,
                    )
                    return (
                        PolicyDecisionV2.REQUIRE_APPROVAL,
                        f"approval required (level={rule.approval_level}): {rule.reason}",
                    )
            return PolicyDecisionV2.NO_MATCH, ""
        except Exception as exc:
            logger.error("[ApprovalPolicy] evaluation error: %s", exc)
            return PolicyDecisionV2.DENY, f"approval policy error: {exc}"

    def load_rules(self, raw_rules: List[Dict[str, Any]]) -> None:
        """Load rules from a list of dicts (parsed from config)."""
        self._rules = [ApprovalPolicyRule.from_dict(r) for r in raw_rules]

    @property
    def rules(self) -> List[ApprovalPolicyRule]:
        return list(self._rules)
