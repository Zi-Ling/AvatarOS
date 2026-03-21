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


# ---------------------------------------------------------------------------
# V2 Enums
# ---------------------------------------------------------------------------

class PolicyDecisionV2(str, Enum):
    """Explicit four-state policy decision — eliminates ALLOW/no_match ambiguity."""
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    NO_MATCH = "no_match"


class PolicyTypeV2(str, Enum):
    """V2 policy type categories."""
    APPROVAL = "approval"
    DATA_BOUNDARY = "data_boundary"
    RISK = "risk"
    ORGANIZATION = "organization"
    CUSTOM = "custom"


# ---------------------------------------------------------------------------
# V2 Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PolicyRuleV2(PolicyRule):
    """Extended policy rule with V2 fields.

    Inherits from PolicyRule for backward compatibility.
    Adds: policy_type, config_source, timeout, default_on_timeout,
          specificity, schema_version.
    """
    policy_type: PolicyTypeV2 = PolicyTypeV2.CUSTOM
    config_source: str = ""          # e.g. "config.yaml", "api", "inline"
    timeout: float = 300.0           # seconds for approval timeout
    default_on_timeout: str = "deny" # fail-closed default
    specificity: int = 0             # higher = more specific rule
    schema_version: str = "1.0.0"
    role_type: Optional[str] = None  # 适用的角色类型（multi-agent）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type.value if isinstance(self.rule_type, PolicyRuleType) else str(self.rule_type),
            "priority": self.priority,
            "skill_pattern": self.skill_pattern,
            "path_pattern": self.path_pattern,
            "decision": self.decision.value if isinstance(self.decision, (PolicyDecision, PolicyDecisionV2)) else str(self.decision),
            "reason": self.reason,
            "enabled": self.enabled,
            "policy_type": self.policy_type.value if isinstance(self.policy_type, PolicyTypeV2) else str(self.policy_type),
            "config_source": self.config_source,
            "timeout": self.timeout,
            "default_on_timeout": self.default_on_timeout,
            "specificity": self.specificity,
            "schema_version": self.schema_version,
            "role_type": self.role_type,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolicyRuleV2":
        rule_type_val = data.get("rule_type", PolicyRuleType.SKILL_REQUIRES_APPROVAL.value)
        try:
            rule_type = PolicyRuleType(rule_type_val)
        except (ValueError, KeyError):
            rule_type = PolicyRuleType.SKILL_REQUIRES_APPROVAL

        decision_val = data.get("decision", PolicyDecision.DENY.value)
        try:
            decision = PolicyDecision(decision_val)
        except (ValueError, KeyError):
            decision = PolicyDecision.DENY

        policy_type_val = data.get("policy_type", PolicyTypeV2.CUSTOM.value)
        try:
            policy_type = PolicyTypeV2(policy_type_val)
        except (ValueError, KeyError):
            policy_type = PolicyTypeV2.CUSTOM

        return cls(
            rule_id=data.get("rule_id", ""),
            rule_type=rule_type,
            priority=data.get("priority", 0),
            skill_pattern=data.get("skill_pattern"),
            path_pattern=data.get("path_pattern"),
            decision=decision,
            reason=data.get("reason", ""),
            enabled=data.get("enabled", True),
            policy_type=policy_type,
            config_source=data.get("config_source", ""),
            timeout=data.get("timeout", 300.0),
            default_on_timeout=data.get("default_on_timeout", "deny"),
            specificity=data.get("specificity", 0),
            schema_version=data.get("schema_version", "1.0.0"),
            role_type=data.get("role_type"),
        )


# ---------------------------------------------------------------------------
# PolicyEngineV2
# ---------------------------------------------------------------------------

class PolicyEngineV2(PolicyEngine):
    """Extended policy engine with explicit four-state decisions.

    Inherits from PolicyEngine for backward compatibility.
    Key improvements:
    - Explicit NO_MATCH state (vs implicit ALLOW in V1)
    - fail_closed mode: NO_MATCH → DENY
    - Multi-rule matching with deny > require_approval > allow priority
    - Config-based rule loading (YAML/JSON)
    - Audit trail integration
    - Pluggable policy evaluators for ApprovalPolicy, DataBoundaryPolicy, etc.
    """

    def __init__(
        self,
        rules: Optional[List[PolicyRule]] = None,
        fail_closed: bool = True,
    ) -> None:
        super().__init__(rules)
        self._fail_closed = fail_closed
        self._policy_evaluators: List[Any] = []  # pluggable evaluators
        self._config_source: str = ""
        self._audit_trail: Optional[Any] = None  # AuditTrail instance

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_audit_trail(self, audit_trail: Any) -> None:
        """Attach an AuditTrail instance for evaluate_with_audit()."""
        self._audit_trail = audit_trail

    def register_evaluator(self, evaluator: Any) -> None:
        """Register a pluggable policy evaluator (ApprovalPolicy, DataBoundaryPolicy, etc.)."""
        with self._lock:
            self._policy_evaluators.append(evaluator)

    # ------------------------------------------------------------------
    # V2 Public API
    # ------------------------------------------------------------------

    def evaluate_v2(
        self,
        skill_name: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[PolicyDecisionV2, Optional[PolicyRuleV2], str]:
        """Evaluate all rules with explicit four-state decision.

        Returns (decision, matched_rule, reason).
        Multi-rule matching: deny > require_approval > allow priority.
        NO_MATCH + fail_closed → DENY.
        """
        try:
            with self._lock:
                rules_snapshot = list(self._rules)
                evaluators_snapshot = list(self._policy_evaluators)

            ctx = context or {}
            target_path = (
                ctx.get("target_path")
                or params.get("path")
                or params.get("target_path")
            )

            # Collect all matching decisions from rules
            matches: list[tuple[PolicyDecisionV2, Optional[PolicyRuleV2], str]] = []

            # 1. Evaluate built-in rules
            for rule in rules_snapshot:
                if not rule.enabled:
                    continue
                # V2: role_type matching for multi-agent
                if isinstance(rule, PolicyRuleV2) and rule.role_type is not None:
                    agent_role = ctx.get("agent_role", "")
                    if agent_role and agent_role != rule.role_type:
                        continue  # 角色不匹配，跳过此规则
                value_kind = ctx.get("value_kind", "")
                if self._match_rule(rule, skill_name, target_path, value_kind, ctx):
                    v2_decision = self._map_v1_decision(rule.decision)
                    v2_rule = self._wrap_as_v2(rule) if not isinstance(rule, PolicyRuleV2) else rule
                    matches.append((v2_decision, v2_rule, rule.reason))

            # 2. Evaluate pluggable evaluators
            for evaluator in evaluators_snapshot:
                try:
                    ev_decision, ev_reason = evaluator.evaluate(
                        skill_name, params, ctx
                    )
                    if ev_decision != PolicyDecisionV2.NO_MATCH:
                        matches.append((ev_decision, None, ev_reason))
                except Exception as exc:
                    logger.warning(
                        "[PolicyEngineV2] evaluator %s error: %s",
                        type(evaluator).__name__, exc,
                    )

            # 3. Multi-rule resolution: deny > require_approval > allow
            if not matches:
                if self._fail_closed:
                    return (
                        PolicyDecisionV2.DENY,
                        None,
                        "no matching rule (fail-closed)",
                    )
                return PolicyDecisionV2.NO_MATCH, None, "no matching rule"

            return self._resolve_matches(matches)

        except Exception as exc:
            logger.error(
                "[PolicyEngineV2] evaluation error for skill=%s: %s",
                skill_name, exc, exc_info=True,
            )
            return PolicyDecisionV2.DENY, None, f"evaluation error: {exc}"

    def evaluate(
        self,
        skill_name: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[PolicyDecision, Optional[PolicyRule]]:
        """Backward-compatible evaluate — uses V1 first-match-wins semantics.

        Delegates to the parent PolicyEngine.evaluate() so that rule
        evaluation order (first match wins) is preserved, matching V1
        behavior exactly.
        """
        return super().evaluate(skill_name, params, context)

    def evaluate_with_audit(
        self,
        skill_name: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[PolicyDecisionV2, Optional[PolicyRuleV2], str]:
        """Evaluate and record result to AuditTrail. Target P50 < 10ms."""
        start_time = time.time()
        decision, rule, reason = self.evaluate_v2(skill_name, params, context)
        elapsed_ms = (time.time() - start_time) * 1000

        if self._audit_trail is not None:
            try:
                from app.avatar.runtime.action_plane.audit_trail import AuditTrailEntry
                entry = AuditTrailEntry(
                    action_id=context.get("action_id", "") if context else "",
                    executor_id="policy_engine_v2",
                    executor_type="policy",
                    action_description=f"policy_eval: {skill_name}",
                    input_params_summary=str(params)[:200],
                    output_result_summary=f"{decision.value}: {reason}",
                    started_at=start_time,
                    completed_at=time.time(),
                    status=decision.value,
                )
                self._audit_trail.append(entry)
            except Exception as exc:
                logger.warning("[PolicyEngineV2] audit recording error: %s", exc)

        if elapsed_ms > 50:
            logger.warning(
                "[PolicyEngineV2] slow evaluation: %.1fms for skill=%s",
                elapsed_ms, skill_name,
            )

        return decision, rule, reason

    def load_from_config(self, config: Dict[str, Any], source: str = "", role_registry: Any = None) -> None:
        """Load policy rules from a config dict (parsed from YAML/JSON).

        Supports hot-reload — replaces all rules atomically.
        Expected format:
            {"rules": [{"rule_id": ..., "rule_type": ..., ...}, ...]}
        If role_registry is provided, validates that role_type references exist.
        """
        raw_rules = config.get("rules", [])
        new_rules: List[PolicyRuleV2] = []
        for raw in raw_rules:
            try:
                rule = PolicyRuleV2.from_dict(raw)
                if source:
                    rule.config_source = source
                # Validate role_type reference if registry provided
                if rule.role_type and role_registry is not None:
                    if hasattr(role_registry, "get") and role_registry.get(rule.role_type) is None:
                        logger.warning(
                            "[PolicyEngineV2] rule %s references unknown role_type '%s'",
                            rule.rule_id, rule.role_type,
                        )
                new_rules.append(rule)
            except Exception as exc:
                logger.warning(
                    "[PolicyEngineV2] skipping invalid rule %s: %s",
                    raw.get("rule_id", "?"), exc,
                )
        self.reload_rules(new_rules)  # type: ignore[arg-type]
        self._config_source = source
        logger.info(
            "[PolicyEngineV2] loaded %d rules from config source='%s'",
            len(new_rules), source,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_v1_decision(d: PolicyDecision) -> PolicyDecisionV2:
        """Map V1 PolicyDecision to V2 PolicyDecisionV2."""
        mapping = {
            PolicyDecision.ALLOW: PolicyDecisionV2.ALLOW,
            PolicyDecision.DENY: PolicyDecisionV2.DENY,
            PolicyDecision.REQUIRE_APPROVAL: PolicyDecisionV2.REQUIRE_APPROVAL,
        }
        return mapping.get(d, PolicyDecisionV2.DENY)

    @staticmethod
    def _map_v2_to_v1(d: PolicyDecisionV2) -> PolicyDecision:
        """Map V2 decision back to V1 for backward compatibility.

        NO_MATCH maps to ALLOW to match V1 behavior (no rule match → allow).
        """
        mapping = {
            PolicyDecisionV2.ALLOW: PolicyDecision.ALLOW,
            PolicyDecisionV2.DENY: PolicyDecision.DENY,
            PolicyDecisionV2.REQUIRE_APPROVAL: PolicyDecision.REQUIRE_APPROVAL,
            PolicyDecisionV2.NO_MATCH: PolicyDecision.ALLOW,  # V1 compat: no match → allow
        }
        return mapping.get(d, PolicyDecision.DENY)

    @staticmethod
    def _wrap_as_v2(rule: PolicyRule) -> PolicyRuleV2:
        """Wrap a V1 PolicyRule as PolicyRuleV2."""
        return PolicyRuleV2(
            rule_id=rule.rule_id,
            rule_type=rule.rule_type,
            priority=rule.priority,
            skill_pattern=rule.skill_pattern,
            path_pattern=rule.path_pattern,
            decision=rule.decision,
            reason=rule.reason,
            enabled=rule.enabled,
        )

    @staticmethod
    def _resolve_matches(
        matches: list[tuple[PolicyDecisionV2, Optional[PolicyRuleV2], str]],
    ) -> tuple[PolicyDecisionV2, Optional[PolicyRuleV2], str]:
        """Resolve multiple matching rules: deny > require_approval > allow."""
        # Priority order: DENY > REQUIRE_APPROVAL > ALLOW
        priority_order = {
            PolicyDecisionV2.DENY: 0,
            PolicyDecisionV2.REQUIRE_APPROVAL: 1,
            PolicyDecisionV2.ALLOW: 2,
            PolicyDecisionV2.NO_MATCH: 3,
        }
        matches_sorted = sorted(
            matches, key=lambda m: priority_order.get(m[0], 99)
        )
        return matches_sorted[0]
