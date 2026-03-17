"""
learning_store.py — 学习候选持久化存储

基于 SQLModel + SQLite。支持按 type、status、scope、confidence、tags 查询。
状态变更历史 append-only。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.avatar.evolution.config import EvolutionConfig
from app.avatar.evolution.models import (
    CandidateContent,
    CandidateRule,
    CandidateStatus,
    CandidateType,
    ConflictGroup,
    EvidenceLink,
    LearningCandidate,
    LearningCandidateDB,
    RollbackInfo,
    StatusChange,
    StatusChangeDB,
)

logger = logging.getLogger(__name__)


class LearningStore:
    """
    学习候选持久化存储。
    支持按 type、status、scope、confidence、tags 查询。
    状态变更历史 append-only。
    """

    def __init__(self, db_engine: Any, config: Optional[EvolutionConfig] = None) -> None:
        self._engine = db_engine
        self._config = config or EvolutionConfig()

    # ------------------------------------------------------------------
    # 从 CandidateRule 创建 LearningCandidate
    # ------------------------------------------------------------------

    def create_from_rule(
        self,
        rule: CandidateRule,
        source_reflection_id: str,
        evidence_links: Optional[List[EvidenceLink]] = None,
    ) -> LearningCandidate:
        """
        从 CandidateRule 创建 LearningCandidate。
        初始 status=draft，填充 rollback_info。
        """
        before_value = rule.content.get("before_value") if isinstance(rule.content, dict) else None
        after_value = rule.content.get("after_value") if isinstance(rule.content, dict) else str(rule.content)

        candidate = LearningCandidate(
            candidate_id=str(uuid.uuid4()),
            type=rule.type,
            scope=rule.scope,
            content=CandidateContent(before_value=before_value, after_value=after_value),
            evidence_links=evidence_links or [],
            confidence=rule.confidence,
            status=CandidateStatus.DRAFT,
            rollback_info=RollbackInfo(before_value=before_value),
            source_reflection_id=source_reflection_id,
            created_at=datetime.now(timezone.utc),
            status_history=[],
            tags=[],
        )
        return candidate

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def save_candidate(self, candidate: LearningCandidate) -> str:
        """持久化候选，返回 candidate_id。"""
        with Session(self._engine) as session:
            db_obj = LearningCandidateDB(
                candidate_id=candidate.candidate_id,
                type=candidate.type.value,
                scope=candidate.scope,
                content=json.dumps({"before_value": candidate.content.before_value, "after_value": candidate.content.after_value}, default=str),
                evidence_links=json.dumps([{"trace_id": el.trace_id, "step_id": el.step_id, "artifact_id": el.artifact_id, "verifier_result_id": el.verifier_result_id, "description": el.description} for el in candidate.evidence_links], default=str),
                confidence=candidate.confidence,
                status=candidate.status.value,
                rollback_info=json.dumps({"before_value": candidate.rollback_info.before_value, "rollback_steps": candidate.rollback_info.rollback_steps}, default=str),
                source_reflection_id=candidate.source_reflection_id,
                created_at=candidate.created_at,
                tags=json.dumps(candidate.tags),
            )
            session.add(db_obj)
            session.commit()
        return candidate.candidate_id

    def get_candidate(self, candidate_id: str) -> Optional[LearningCandidate]:
        """按 ID 获取候选。"""
        with Session(self._engine) as session:
            db_obj = session.get(LearningCandidateDB, candidate_id)
            if not db_obj:
                return None
            return self._to_domain(db_obj, session)

    def query_candidates(
        self,
        type: Optional[CandidateType] = None,
        status: Optional[CandidateStatus] = None,
        scope: Optional[str] = None,
        confidence_min: Optional[float] = None,
        confidence_max: Optional[float] = None,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
    ) -> List[LearningCandidate]:
        """灵活查询候选，支持按 tags 过滤。"""
        with Session(self._engine) as session:
            stmt = select(LearningCandidateDB)
            if type is not None:
                stmt = stmt.where(LearningCandidateDB.type == type.value)
            if status is not None:
                stmt = stmt.where(LearningCandidateDB.status == status.value)
            if scope is not None:
                stmt = stmt.where(LearningCandidateDB.scope == scope)
            if confidence_min is not None:
                stmt = stmt.where(LearningCandidateDB.confidence >= confidence_min)
            if confidence_max is not None:
                stmt = stmt.where(LearningCandidateDB.confidence <= confidence_max)
            if created_after is not None:
                stmt = stmt.where(LearningCandidateDB.created_at >= created_after)
            if created_before is not None:
                stmt = stmt.where(LearningCandidateDB.created_at <= created_before)
            stmt = stmt.limit(limit)
            rows = session.exec(stmt).all()

            candidates = [self._to_domain(r, session) for r in rows]

            # tags 过滤（JSON 字段，需在应用层过滤）
            if tags:
                candidates = [
                    c for c in candidates
                    if any(t in c.tags for t in tags)
                ]

            return candidates

    def update_status(
        self,
        candidate_id: str,
        new_status: CandidateStatus,
        reason: str = "",
    ) -> None:
        """更新候选状态，append-only 记录状态变更历史。"""
        with Session(self._engine) as session:
            db_obj = session.get(LearningCandidateDB, candidate_id)
            if not db_obj:
                raise ValueError(f"Candidate {candidate_id} not found")

            old_status = db_obj.status
            db_obj.status = new_status.value
            session.add(db_obj)

            # append-only 状态变更记录
            change = StatusChangeDB(
                candidate_id=candidate_id,
                from_status=old_status,
                to_status=new_status.value,
                reason=reason,
                timestamp=datetime.now(timezone.utc),
            )
            session.add(change)
            session.commit()

    def tag_candidate(self, candidate_id: str, tag: str) -> None:
        """为候选添加标签。"""
        with Session(self._engine) as session:
            db_obj = session.get(LearningCandidateDB, candidate_id)
            if not db_obj:
                raise ValueError(f"Candidate {candidate_id} not found")
            tags = json.loads(db_obj.tags) if db_obj.tags else []
            if tag not in tags:
                tags.append(tag)
                db_obj.tags = json.dumps(tags)
                session.add(db_obj)
                session.commit()

    def detect_conflicts(self, scope: str) -> List[ConflictGroup]:
        """检测同一 scope 下的冲突候选。"""
        with Session(self._engine) as session:
            stmt = (
                select(LearningCandidateDB)
                .where(LearningCandidateDB.scope == scope)
                .where(LearningCandidateDB.status.in_(["active", "shadow"]))
            )
            rows = session.exec(stmt).all()
            if len(rows) <= 1:
                return []
            return [ConflictGroup(
                conflict_group_id=str(uuid.uuid4()),
                scope=scope,
                candidate_ids=[r.candidate_id for r in rows],
            )]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _to_domain(self, db_obj: LearningCandidateDB, session: Session) -> LearningCandidate:
        """将 DB 对象转换为领域对象。"""
        content_data = json.loads(db_obj.content) if db_obj.content else {}
        evidence_data = json.loads(db_obj.evidence_links) if db_obj.evidence_links else []
        rollback_data = json.loads(db_obj.rollback_info) if db_obj.rollback_info else {}
        tags_data = json.loads(db_obj.tags) if db_obj.tags else []

        # 加载状态变更历史
        stmt = (
            select(StatusChangeDB)
            .where(StatusChangeDB.candidate_id == db_obj.candidate_id)
            .order_by(StatusChangeDB.timestamp)
        )
        changes = session.exec(stmt).all()

        return LearningCandidate(
            candidate_id=db_obj.candidate_id,
            type=CandidateType(db_obj.type),
            scope=db_obj.scope,
            content=CandidateContent(
                before_value=content_data.get("before_value"),
                after_value=content_data.get("after_value"),
            ),
            evidence_links=[
                EvidenceLink(
                    trace_id=el.get("trace_id", ""),
                    step_id=el.get("step_id"),
                    artifact_id=el.get("artifact_id"),
                    verifier_result_id=el.get("verifier_result_id"),
                    description=el.get("description", ""),
                ) for el in evidence_data
            ],
            confidence=db_obj.confidence,
            status=CandidateStatus(db_obj.status),
            rollback_info=RollbackInfo(
                before_value=rollback_data.get("before_value"),
                rollback_steps=rollback_data.get("rollback_steps", []),
            ),
            source_reflection_id=db_obj.source_reflection_id,
            created_at=db_obj.created_at,
            status_history=[
                StatusChange(
                    from_status=CandidateStatus(c.from_status),
                    to_status=CandidateStatus(c.to_status),
                    reason=c.reason,
                    timestamp=c.timestamp,
                ) for c in changes
            ],
            tags=tags_data,
        )
