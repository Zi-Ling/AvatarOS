"""RiskPolicy — risk-based policy evaluation.

Defines risk patterns, risk levels, and mitigation actions.
Integrates into PolicyEngineV2.evaluate_v2() flow as a pluggable evaluator.

Requirements: 10.2
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from typing import Any, Dict, List, Optional

from app.avatar.runtime.policy.policy_engine import PolicyDecisionV2

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MitigationAction(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"
    LOG_ONLY = "log_only"


@dataclass
class RiskPolicyRule:
    """Single risk policy rule.

    Attributes:
        rule_id: Unique identifier.
        risk_pattern: Glob pattern matching skill/action names.
        risk_level: Assessed risk level for matching operations.
        mitigation_action: Action to take when pattern matches.
        reason: Human-readable description.
        enabled: Whether this rule is active.
        schema_version: Data schema version.
    """
    rule_id: str = ""
    risk_pattern: str = "*"
    risk_level: RiskLevel = RiskLevel.LOW
    mitigation_action: MitigationAction = MitigationAction.LOG_ONLY
    reason: str = ""
    enabled: bool = True
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "risk_pattern": self.risk_pattern,
            "risk_level": self.risk_level.value,
            "mitigation_action": self.mitigation_action.value,
            "reason": self.reason,
            "enabled": self.enabled,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskPolicyRule":
        risk_level_val = data.get("risk_level", RiskLevel.LOW.value)
        try:
            risk_level = RiskLevel(risk_level_val)
        except (ValueError, KeyError):
            risk_level = RiskLevel.LOW

        mitigation_val = data.get("mitigation_action", MitigationAction.LOG_ONLY.value)
        try:
            mitigation = MitigationAction(mitigation_val)
        except (ValueError, KeyError):
            mitigation = MitigationAction.LOG_ONLY

        return cls(
            rule_id=data.get("rule_id", ""),
            risk_pattern=data.get("risk_pattern", "*"),
            risk_level=risk_level,
            mitigation_action=mitigation,
            reason=data.get("reason", ""),
            enabled=data.get("enabled", True),
            schema_version=data.get("schema_version", "1.0.0"),
        )


class RiskPolicy:
    """Evaluates risk-based policies for skill invocations.

    Integrates into PolicyEngineV2 as a pluggable evaluator.
    Maps MitigationAction to PolicyDecisionV2.
    """

    _MITIGATION_TO_DECISION = {
        MitigationAction.ALLOW: PolicyDecisionV2.ALLOW,
        MitigationAction.REQUIRE_APPROVAL: PolicyDecisionV2.REQUIRE_APPROVAL,
        MitigationAction.DENY: PolicyDecisionV2.DENY,
        MitigationAction.LOG_ONLY: PolicyDecisionV2.ALLOW,
    }

    def __init__(self, rules: Optional[List[RiskPolicyRule]] = None) -> None:
        self._rules: List[RiskPolicyRule] = rules or []

    def add_rule(self, rule: RiskPolicyRule) -> None:
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
        """Evaluate risk rules for a skill invocation.

        Returns (decision, reason).
        Highest risk level match wins. Maps mitigation_action to PolicyDecisionV2.
        """
        try:
            best_match: Optional[RiskPolicyRule] = None
            risk_order = {
                RiskLevel.LOW: 0,
                RiskLevel.MEDIUM: 1,
                RiskLevel.HIGH: 2,
                RiskLevel.CRITICAL: 3,
            }

            for rule in self._rules:
                if not rule.enabled:
                    continue
                if fnmatch(skill_name, rule.risk_pattern):
                    if best_match is None or risk_order.get(
                        rule.risk_level, 0
                    ) > risk_order.get(best_match.risk_level, 0):
                        best_match = rule

            if best_match is None:
                return PolicyDecisionV2.NO_MATCH, ""

            decision = self._MITIGATION_TO_DECISION.get(
                best_match.mitigation_action, PolicyDecisionV2.DENY
            )
            reason = (
                f"risk={best_match.risk_level.value} "
                f"mitigation={best_match.mitigation_action.value}: "
                f"{best_match.reason}"
            )
            logger.info(
                "[RiskPolicy] rule=%s matched skill=%s %s",
                best_match.rule_id, skill_name, reason,
            )
            return decision, reason

        except Exception as exc:
            logger.error("[RiskPolicy] evaluation error: %s", exc)
            return PolicyDecisionV2.DENY, f"risk policy error: {exc}"

    def load_rules(self, raw_rules: List[Dict[str, Any]]) -> None:
        """Load rules from a list of dicts (parsed from config)."""
        self._rules = [RiskPolicyRule.from_dict(r) for r in raw_rules]

    @property
    def rules(self) -> List[RiskPolicyRule]:
        return list(self._rules)
