"""NegotiationEngine — upgraded from ClarificationEngine.

Provides readiness assessment, ambiguity detection, scope drift detection,
and option generation for task negotiation.

Requirements: 6.1, 6.2, 6.3, 6.8
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..feature_flags import record_system_fallback

logger = logging.getLogger(__name__)

_MAX_OPTIONS = 3


@dataclass
class NegotiationOption:
    """A single approach option for task execution."""
    approach_description: str = ""
    estimated_effort: str = ""
    trade_offs: List[str] = field(default_factory=list)
    recommendation_score: float = 0.0


@dataclass
class NegotiationResult:
    """Result of NegotiationEngine assessment."""
    readiness_score: float = 0.0
    ambiguities: List[Dict[str, Any]] = field(default_factory=list)
    scope_drift: Optional[Dict[str, Any]] = None
    options: List[Dict[str, Any]] = field(default_factory=list)
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "readiness_score": self.readiness_score,
            "ambiguities": list(self.ambiguities),
            "scope_drift": self.scope_drift,
            "options": list(self.options),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NegotiationResult:
        return cls(
            readiness_score=data.get("readiness_score", 0.0),
            ambiguities=list(data.get("ambiguities") or []),
            scope_drift=data.get("scope_drift"),
            options=list(data.get("options") or []),
            schema_version=data.get("schema_version", "1.0.0"),
        )


class NegotiationEngine:
    """Upgraded from ClarificationEngine.

    Cognitive layer — judges readiness, detects ambiguity/drift, generates options.
    Does NOT send messages itself; uses RuntimeSignal.REQUEST_CLARIFICATION
    to delegate to CollaborationHub.

    Falls back to ClarificationEngine on exception.
    Requirements: 6.1, 6.2, 6.3, 6.8
    """

    def __init__(self, clarification_engine: Any = None) -> None:
        self._clarification_engine = clarification_engine

    # ------------------------------------------------------------------
    # Readiness assessment (preserves ClarificationEngine capability)
    # ------------------------------------------------------------------

    def assess_readiness(self, task_def: Any) -> Dict[str, Any]:
        """Assess execution readiness for a TaskDefinition.

        Returns dict with readiness_score (0.0-1.0), status, and details.
        Falls back to ClarificationEngine.assess() on error.
        """
        try:
            return self._assess_readiness_impl(task_def)
        except Exception as exc:
            logger.warning("[NegotiationEngine] assess_readiness error: %s", exc)
            return self._fallback_assess(task_def, exc)

    def _assess_readiness_impl(self, task_def: Any) -> Dict[str, Any]:
        objective = getattr(task_def, "objective", None)
        deliverables = getattr(task_def, "deliverables", []) or []
        acceptance_criteria = getattr(task_def, "acceptance_criteria", []) or []
        open_questions = getattr(task_def, "open_questions", []) or []
        assumptions = getattr(task_def, "assumptions", []) or []

        # Score components
        has_objective = bool(objective and getattr(objective, "text", ""))
        has_deliverables = len(deliverables) > 0
        has_criteria = len(acceptance_criteria) > 0
        no_blocking_questions = len(open_questions) == 0

        score = 0.0
        if has_objective:
            score += 0.3
        if has_deliverables:
            score += 0.25
        if has_criteria:
            score += 0.25
        if no_blocking_questions:
            score += 0.2

        # Penalize low-confidence assumptions
        low_conf = sum(
            1 for a in assumptions
            if getattr(a, "confidence_level", "medium") == "low"
        )
        if assumptions and low_conf / len(assumptions) > 0.5:
            score = max(0.0, score - 0.15)

        if score >= 0.8:
            status = "ready"
        elif score >= 0.5:
            status = "conditional"
        else:
            status = "blocked"

        return {
            "readiness_score": round(score, 2),
            "status": status,
            "has_objective": has_objective,
            "has_deliverables": has_deliverables,
            "has_criteria": has_criteria,
            "open_questions_count": len(open_questions),
        }

    # ------------------------------------------------------------------
    # Ambiguity detection
    # ------------------------------------------------------------------

    def detect_ambiguity(self, task_def: Any) -> List[Dict[str, Any]]:
        """Detect ambiguities in a TaskDefinition.

        Returns list of ambiguity dicts with field, description, severity.
        """
        try:
            return self._detect_ambiguity_impl(task_def)
        except Exception as exc:
            logger.warning("[NegotiationEngine] detect_ambiguity error: %s", exc)
            record_system_fallback("negotiation_engine", exc, "clarification_engine")
            return []

    def _detect_ambiguity_impl(self, task_def: Any) -> List[Dict[str, Any]]:
        ambiguities: List[Dict[str, Any]] = []

        # Check objective
        objective = getattr(task_def, "objective", None)
        if objective:
            source = getattr(objective, "source", None)
            if source and hasattr(source, "value") and source.value == "unknown":
                ambiguities.append({
                    "field": "objective",
                    "description": "Objective source is unknown",
                    "severity": "high",
                })

        # Check deliverables for unknown sources
        for i, d in enumerate(getattr(task_def, "deliverables", []) or []):
            source = getattr(d, "source", None)
            if source and hasattr(source, "value") and source.value == "unknown":
                ambiguities.append({
                    "field": f"deliverables[{i}]",
                    "description": f"Deliverable '{getattr(d, 'text', '')}' source is unknown",
                    "severity": "medium",
                })

        # Check open questions as ambiguity indicators
        for q in getattr(task_def, "open_questions", []) or []:
            ambiguities.append({
                "field": "open_questions",
                "description": q,
                "severity": "medium",
            })

        return ambiguities

    # ------------------------------------------------------------------
    # Scope drift detection
    # ------------------------------------------------------------------

    def detect_scope_drift(
        self,
        original_def: Any,
        current_def: Any,
    ) -> Optional[Dict[str, Any]]:
        """Compare initial vs current TaskDefinition for scope drift.

        Returns scope_drift_alert dict if drift detected, else None.
        Requirements: 6.3
        """
        try:
            return self._detect_scope_drift_impl(original_def, current_def)
        except Exception as exc:
            logger.warning("[NegotiationEngine] detect_scope_drift error: %s", exc)
            record_system_fallback("negotiation_engine", exc, "clarification_engine")
            return None

    def _detect_scope_drift_impl(
        self,
        original_def: Any,
        current_def: Any,
    ) -> Optional[Dict[str, Any]]:
        drifts: List[str] = []

        # Compare objectives
        orig_obj = getattr(original_def, "objective", None)
        curr_obj = getattr(current_def, "objective", None)
        orig_text = getattr(orig_obj, "text", "") if orig_obj else ""
        curr_text = getattr(curr_obj, "text", "") if curr_obj else ""
        if orig_text and curr_text and orig_text != curr_text:
            drifts.append("objective changed")

        # Compare deliverables count and content
        orig_deliverables = getattr(original_def, "deliverables", []) or []
        curr_deliverables = getattr(current_def, "deliverables", []) or []
        orig_del_texts = {getattr(d, "text", str(d)) for d in orig_deliverables}
        curr_del_texts = {getattr(d, "text", str(d)) for d in curr_deliverables}
        if orig_del_texts != curr_del_texts:
            drifts.append("deliverables changed")

        if not drifts:
            return None

        return {
            "original_scope": {
                "objective": orig_text,
                "deliverables_count": len(orig_deliverables),
            },
            "current_scope": {
                "objective": curr_text,
                "deliverables_count": len(curr_deliverables),
            },
            "drift_description": "; ".join(drifts),
        }

    # ------------------------------------------------------------------
    # Option generation
    # ------------------------------------------------------------------

    def generate_options(
        self,
        task_def: Any,
        max_options: int = _MAX_OPTIONS,
    ) -> List[Dict[str, Any]]:
        """Generate up to max_options (capped at 3) approach options.

        Each option contains approach_description, estimated_effort,
        trade_offs, and recommendation_score.
        Requirements: 6.2
        """
        try:
            return self._generate_options_impl(task_def, max_options)
        except Exception as exc:
            logger.warning("[NegotiationEngine] generate_options error: %s", exc)
            record_system_fallback("negotiation_engine", exc, "clarification_engine")
            return []

    def _generate_options_impl(
        self,
        task_def: Any,
        max_options: int,
    ) -> List[Dict[str, Any]]:
        # Cap at 3
        max_options = min(max_options, _MAX_OPTIONS)

        deliverables = getattr(task_def, "deliverables", []) or []
        constraints = getattr(task_def, "constraints", []) or []
        risks = getattr(task_def, "risks", []) or []

        options: List[Dict[str, Any]] = []

        # Option 1: Full implementation
        options.append({
            "approach_description": "Full implementation addressing all deliverables and constraints",
            "estimated_effort": "high",
            "trade_offs": ["Comprehensive but time-consuming"],
            "recommendation_score": 0.7,
        })

        # Option 2: Incremental (if multiple deliverables)
        if len(deliverables) > 1:
            options.append({
                "approach_description": "Incremental delivery — prioritize core deliverables first",
                "estimated_effort": "medium",
                "trade_offs": [
                    "Faster initial delivery",
                    "May need follow-up for remaining deliverables",
                ],
                "recommendation_score": 0.85,
            })

        # Option 3: Risk-mitigated (if risks exist)
        if risks:
            options.append({
                "approach_description": "Risk-mitigated approach — address high-risk items first",
                "estimated_effort": "medium",
                "trade_offs": [
                    "Reduces risk exposure early",
                    "May reorder deliverable priorities",
                ],
                "recommendation_score": 0.75,
            })

        return options[:max_options]

    # ------------------------------------------------------------------
    # Fallback to ClarificationEngine
    # ------------------------------------------------------------------

    def _fallback_assess(self, task_def: Any, error: Exception) -> Dict[str, Any]:
        """Fall back to ClarificationEngine for readiness assessment."""
        record_system_fallback("negotiation_engine", error, "clarification_engine")
        if self._clarification_engine is not None:
            try:
                result = self._clarification_engine.assess(task_def)
                status = getattr(result, "status", "ready")
                score = 1.0 if status == "ready" else 0.5 if status == "conditional" else 0.0
                return {
                    "readiness_score": score,
                    "status": status,
                    "fallback": True,
                }
            except Exception:
                pass
        return {"readiness_score": 0.0, "status": "blocked", "fallback": True}
