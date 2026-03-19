"""DataBoundaryPolicy — defines data access boundaries for the Agent.

Controls which file paths the Agent can access, with denied_paths
taking priority over allowed_paths. Supports data classification
rules and PII handling strategies.

Requirements: 10.4
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Dict, List, Optional

from app.avatar.runtime.policy.policy_engine import PolicyDecisionV2

logger = logging.getLogger(__name__)


@dataclass
class DataBoundaryPolicy:
    """Data boundary policy configuration.

    Path matching logic: denied_paths takes priority over allowed_paths.
    If a path matches any denied_paths pattern → DENY.
    If allowed_paths is non-empty and path doesn't match any → DENY.
    If allowed_paths is empty, any non-denied path is allowed.

    Attributes:
        policy_id: Unique identifier.
        allowed_paths: Glob patterns for allowed file paths.
        denied_paths: Glob patterns for denied file paths (takes priority).
        data_classification_rules: Patterns for sensitive data detection.
        pii_handling: PII handling strategy — "mask", "redact", or "deny_access".
        enabled: Whether this policy is active.
        schema_version: Data schema version.
    """
    policy_id: str = ""
    allowed_paths: List[str] = field(default_factory=list)
    denied_paths: List[str] = field(default_factory=list)
    data_classification_rules: List[str] = field(default_factory=list)
    pii_handling: str = "deny_access"
    enabled: bool = True
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "allowed_paths": list(self.allowed_paths),
            "denied_paths": list(self.denied_paths),
            "data_classification_rules": list(self.data_classification_rules),
            "pii_handling": self.pii_handling,
            "enabled": self.enabled,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DataBoundaryPolicy":
        return cls(
            policy_id=data.get("policy_id", ""),
            allowed_paths=list(data.get("allowed_paths", [])),
            denied_paths=list(data.get("denied_paths", [])),
            data_classification_rules=list(data.get("data_classification_rules", [])),
            pii_handling=data.get("pii_handling", "deny_access"),
            enabled=data.get("enabled", True),
            schema_version=data.get("schema_version", "1.0.0"),
        )

    def check_path(self, path: str) -> tuple[PolicyDecisionV2, str]:
        """Check whether a file path is allowed by this policy.

        Returns (decision, reason).
        denied_paths takes priority over allowed_paths.
        """
        if not self.enabled:
            return PolicyDecisionV2.NO_MATCH, "policy disabled"

        # 1. Check denied_paths first (highest priority)
        for pattern in self.denied_paths:
            if fnmatch(path, pattern):
                return (
                    PolicyDecisionV2.DENY,
                    f"path '{path}' matches denied pattern '{pattern}'",
                )

        # 2. Check allowed_paths (if specified)
        if self.allowed_paths:
            for pattern in self.allowed_paths:
                if fnmatch(path, pattern):
                    return (
                        PolicyDecisionV2.ALLOW,
                        f"path '{path}' matches allowed pattern '{pattern}'",
                    )
            # Path not in allowed list → deny
            return (
                PolicyDecisionV2.DENY,
                f"path '{path}' not in allowed paths",
            )

        # 3. No allowed_paths specified and not denied → allow
        return PolicyDecisionV2.ALLOW, "path not restricted"


class DataBoundaryPolicyEvaluator:
    """Evaluator that integrates DataBoundaryPolicy into PolicyEngineV2.

    Registered as a pluggable evaluator via PolicyEngineV2.register_evaluator().
    """

    def __init__(self, policies: Optional[List[DataBoundaryPolicy]] = None) -> None:
        self._policies: List[DataBoundaryPolicy] = policies or []

    def add_policy(self, policy: DataBoundaryPolicy) -> None:
        self._policies.append(policy)

    def remove_policy(self, policy_id: str) -> bool:
        before = len(self._policies)
        self._policies = [p for p in self._policies if p.policy_id != policy_id]
        return len(self._policies) < before

    def evaluate(
        self,
        skill_name: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[PolicyDecisionV2, str]:
        """Evaluate data boundary policies for a skill invocation.

        Extracts target_path from params/context and checks all policies.
        denied_paths always takes priority.
        """
        ctx = context or {}
        target_path = (
            ctx.get("target_path")
            or params.get("path")
            or params.get("target_path")
        )

        if not target_path:
            return PolicyDecisionV2.NO_MATCH, "no target path"

        try:
            # Collect decisions from all policies — deny takes priority
            has_allow = False
            for policy in self._policies:
                if not policy.enabled:
                    continue
                decision, reason = policy.check_path(target_path)
                if decision == PolicyDecisionV2.DENY:
                    logger.info(
                        "[DataBoundaryPolicy] policy=%s denied path=%s: %s",
                        policy.policy_id, target_path, reason,
                    )
                    return decision, reason
                if decision == PolicyDecisionV2.ALLOW:
                    has_allow = True

            if has_allow:
                return PolicyDecisionV2.ALLOW, f"path '{target_path}' allowed"
            return PolicyDecisionV2.NO_MATCH, "no matching data boundary policy"

        except Exception as exc:
            logger.error("[DataBoundaryPolicy] evaluation error: %s", exc)
            return PolicyDecisionV2.DENY, f"data boundary error: {exc}"

    def load_policies(self, raw_policies: List[Dict[str, Any]]) -> None:
        """Load policies from a list of dicts (parsed from config)."""
        self._policies = [DataBoundaryPolicy.from_dict(p) for p in raw_policies]

    @property
    def policies(self) -> List[DataBoundaryPolicy]:
        return list(self._policies)
