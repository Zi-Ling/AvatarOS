"""
audit_logger.py — EvolutionAuditLogger 审计集成

与现有 AuditService 集成，记录所有演化事件的结构化审计日志。
包含变更权限分级标记（行为层/策略层/代码层）。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.avatar.evolution.models import (
    CandidateType,
    EvolutionVersion,
    LearningCandidate,
    ReflectionOutput,
)

logger = logging.getLogger(__name__)


@dataclass
class AuditReport:
    """结构化审计报告，不以纯文本形式输出。"""
    report_id: str
    candidate_id: str
    trace_refs: List[str] = field(default_factory=list)
    validation_summary: Dict[str, Any] = field(default_factory=dict)
    risk_assessment: str = ""
    decision: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# 变更权限分级
_RISK_LEVEL_MAP: Dict[str, str] = {
    CandidateType.SKILL_SCORE.value: "low",        # 行为层
    CandidateType.MEMORY_FACT.value: "low",         # 行为层
    CandidateType.PLANNER_RULE.value: "medium",     # 策略层
    CandidateType.POLICY_HINT.value: "medium",      # 策略层
    CandidateType.WORKFLOW_TEMPLATE.value: "medium", # 策略层
}


class EvolutionAuditLogger:
    """
    演化审计日志记录器。
    与现有 AuditService 集成，所有演化事件都记录结构化审计日志。
    """

    def __init__(self, audit_service: Any = None) -> None:
        self._audit_service = audit_service

    def _log(self, event_type: str, details: Dict[str, Any], resource: str = "") -> None:
        """通过 AuditService 记录审计日志。"""
        if self._audit_service:
            try:
                self._audit_service.log(
                    event_type=event_type,
                    actor="evolution_pipeline",
                    resource=resource,
                    operation=event_type,
                    outcome="success",
                    details=details,
                )
            except Exception as exc:
                logger.warning(f"[EvolutionAuditLogger] audit log failed: {exc}")
        logger.info(f"[EvolutionAuditLogger] {event_type}: {resource}")

    def log_cold_start(
        self,
        version: EvolutionVersion,
        loaded_baselines: List[str],
        missing_baselines: List[str],
    ) -> None:
        """记录冷启动事件到审计日志。v0 同样可审计。"""
        self._log(
            event_type="evolution_cold_start",
            resource=f"v{version.version_number}",
            details={
                "version_id": version.version_id,
                "version_number": version.version_number,
                "loaded_baselines": loaded_baselines,
                "missing_baselines": missing_baselines,
            },
        )

    def log_reflection(
        self,
        reflection_output: ReflectionOutput,
        trace_id: str,
    ) -> None:
        """记录反思事件到审计日志。"""
        self._log(
            event_type="evolution_reflection",
            resource=reflection_output.reflection_id,
            details={
                "reflection_id": reflection_output.reflection_id,
                "trace_id": trace_id,
                "pattern_type": reflection_output.pattern_type.value,
                "confidence": reflection_output.confidence,
                "candidate_count": len(reflection_output.candidate_rules),
            },
        )

    def log_candidate_created(
        self,
        candidate: LearningCandidate,
    ) -> None:
        """记录候选创建事件到审计日志。"""
        risk_level = _RISK_LEVEL_MAP.get(candidate.type.value, "medium")
        self._log(
            event_type="evolution_candidate_created",
            resource=candidate.candidate_id,
            details={
                "candidate_id": candidate.candidate_id,
                "type": candidate.type.value,
                "scope": candidate.scope,
                "confidence": candidate.confidence,
                "risk_level": risk_level,
                "source_reflection_id": candidate.source_reflection_id,
            },
        )

    def log_status_change(
        self,
        candidate_id: str,
        from_status: str,
        to_status: str,
        reason: str,
    ) -> None:
        """记录候选状态变更到审计日志。"""
        self._log(
            event_type="evolution_status_change",
            resource=candidate_id,
            details={
                "candidate_id": candidate_id,
                "from_status": from_status,
                "to_status": to_status,
                "reason": reason,
            },
        )

    def generate_audit_report(
        self,
        candidate: LearningCandidate,
    ) -> AuditReport:
        """
        生成结构化审计报告。
        包含 candidate_id、trace_refs、validation_summary、risk_assessment、decision。
        """
        trace_refs = [el.trace_id for el in candidate.evidence_links]
        risk_level = _RISK_LEVEL_MAP.get(candidate.type.value, "medium")

        report = AuditReport(
            report_id=str(uuid.uuid4()),
            candidate_id=candidate.candidate_id,
            trace_refs=trace_refs,
            validation_summary={
                "confidence": candidate.confidence,
                "status": candidate.status.value,
                "evidence_count": len(candidate.evidence_links),
            },
            risk_assessment=f"risk_level={risk_level}, type={candidate.type.value}",
            decision=f"current_status={candidate.status.value}",
            timestamp=datetime.now(timezone.utc),
        )

        self._log(
            event_type="evolution_audit_report_generated",
            resource=report.report_id,
            details={
                "report_id": report.report_id,
                "candidate_id": candidate.candidate_id,
                "risk_level": risk_level,
            },
        )
        return report
