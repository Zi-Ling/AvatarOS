"""
promotion_manager.py — PromotionManager

Manages candidate lifecycle: draft → validating → shadow → active.
Maintains ActiveSet with explicit versioning (EvolutionVersion).
Supports DB persistence for ActiveSet and versions (restart-safe).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.avatar.evolution.config import EvolutionConfig
from app.avatar.evolution.models import (
    CandidateStatus,
    EvolutionVersion,
    EvolutionVersionDB,
    LearningCandidate,
    PromotionTier,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class PromotionManager:
    """
    Manages the promotion lifecycle of LearningCandidates.

    Promotion flow:
      draft → validating → shadow → active  (or rejected at any gate)

    Tier-based promotion:
      - low_risk_auto: auto-promote after validation passes
      - medium_risk_validated: auto-promote after validation + shadow period
      - high_risk_human: requires human approval, stays shadow until approved

    Maintains an ActiveSet with explicit EvolutionVersion tracking.
    """

    def __init__(
        self,
        config: Optional[EvolutionConfig] = None,
        db_engine: Optional[Any] = None,
        learning_store: Optional[Any] = None,
    ) -> None:
        self._config = config or EvolutionConfig()
        self._active_set: Dict[str, LearningCandidate] = {}
        self._shadow_set: Dict[str, LearningCandidate] = {}
        self._versions: List[EvolutionVersion] = []
        self._current_version_number: int = 0
        self._pending_approvals: Dict[str, LearningCandidate] = {}
        self._db_engine = db_engine
        self._learning_store = learning_store

        # Restore from DB if available
        if self._db_engine:
            self._restore_from_db()

    @property
    def active_set(self) -> Dict[str, LearningCandidate]:
        return dict(self._active_set)

    @property
    def current_version(self) -> Optional[EvolutionVersion]:
        return self._versions[-1] if self._versions else None

    @property
    def pending_approvals(self) -> Dict[str, LearningCandidate]:
        return dict(self._pending_approvals)

    def promote(
        self,
        candidate: LearningCandidate,
        validation_result: ValidationResult,
        tier: PromotionTier,
    ) -> LearningCandidate:
        """
        Attempt to promote a candidate based on validation result and tier.

        Returns the candidate with updated status.
        """
        if not validation_result.passed:
            candidate.status = CandidateStatus.REJECTED
            logger.info(
                f"[PromotionManager] candidate {candidate.candidate_id} "
                f"rejected: {validation_result.reason}"
            )
            return candidate

        if tier == PromotionTier.LOW_RISK_AUTO:
            return self._promote_to_active(candidate, "low_risk_auto: validation passed")

        if tier == PromotionTier.MEDIUM_RISK_VALIDATED:
            # Medium risk: go to shadow first, then auto-promote
            candidate.status = CandidateStatus.SHADOW
            self._shadow_set[candidate.candidate_id] = candidate
            logger.info(
                f"[PromotionManager] candidate {candidate.candidate_id} "
                f"entered shadow (medium_risk_validated)"
            )
            return candidate

        if tier == PromotionTier.HIGH_RISK_HUMAN:
            candidate.status = CandidateStatus.SHADOW
            self._shadow_set[candidate.candidate_id] = candidate
            self._pending_approvals[candidate.candidate_id] = candidate
            logger.info(
                f"[PromotionManager] candidate {candidate.candidate_id} "
                f"awaiting human approval (high_risk_human)"
            )
            return candidate

        return candidate

    def approve(self, candidate_id: str, approver: str = "") -> Optional[LearningCandidate]:
        """
        Human approval for high_risk_human candidates.
        Moves from shadow → active.
        """
        candidate = self._pending_approvals.pop(candidate_id, None)
        if not candidate:
            logger.warning(
                f"[PromotionManager] candidate {candidate_id} not in pending approvals"
            )
            return None

        reason = f"human approved by {approver}" if approver else "human approved"
        return self._promote_to_active(candidate, reason)

    def reject_approval(
        self, candidate_id: str, reason: str = ""
    ) -> Optional[LearningCandidate]:
        """Reject a pending approval."""
        candidate = self._pending_approvals.pop(candidate_id, None)
        if not candidate:
            return None
        candidate.status = CandidateStatus.REJECTED
        logger.info(
            f"[PromotionManager] candidate {candidate_id} approval rejected: {reason}"
        )
        return candidate

    def promote_shadow_to_active(
        self, candidate: LearningCandidate, reason: str = ""
    ) -> LearningCandidate:
        """
        Promote a shadow candidate to active (for medium_risk after shadow period).
        """
        if candidate.status != CandidateStatus.SHADOW:
            logger.warning(
                f"[PromotionManager] cannot promote non-shadow candidate "
                f"{candidate.candidate_id} (status={candidate.status})"
            )
            return candidate
        return self._promote_to_active(
            candidate, reason or "shadow period complete"
        )

    def get_active_candidates(
        self, scope: Optional[str] = None
    ) -> List[LearningCandidate]:
        """Get all active candidates, optionally filtered by scope."""
        candidates = list(self._active_set.values())
        if scope:
            candidates = [c for c in candidates if c.scope == scope]
        return candidates

    def check_shadow_expirations(self) -> List[LearningCandidate]:
        """
        Opportunistic check: scan shadow set for candidates whose shadow
        period has expired. Expired medium-risk candidates are auto-promoted
        to active. High-risk (pending approval) candidates are skipped.

        Returns list of newly promoted candidates.
        """
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        period = timedelta(hours=self._config.shadow_period_hours)
        promoted: List[LearningCandidate] = []
        expired_ids: List[str] = []

        for cid, candidate in list(self._shadow_set.items()):
            # Skip candidates awaiting human approval
            if cid in self._pending_approvals:
                continue
            if candidate.status != CandidateStatus.SHADOW:
                expired_ids.append(cid)
                continue
            created = candidate.created_at if hasattr(candidate, "created_at") and candidate.created_at else None
            if created is None:
                continue
            if now >= created + period:
                result = self.promote_shadow_to_active(
                    candidate, reason="shadow period expired"
                )
                if result.status == CandidateStatus.ACTIVE:
                    promoted.append(result)
                    expired_ids.append(cid)

        for cid in expired_ids:
            self._shadow_set.pop(cid, None)

        if promoted:
            logger.info(
                f"[PromotionManager] shadow expiration check: "
                f"promoted {len(promoted)} candidate(s)"
            )
        return promoted

    def resolve_conflicts(self, scope: str) -> Optional[LearningCandidate]:
        """
        Deterministic conflict resolution for same-scope candidates.

        Priority sequence (highest wins):
          1. human_approved > auto_promoted
          2. active > shadow
          3. higher confidence > lower confidence
          4. newer validated_at > older validated_at
          5. higher evidence count
          6. fixed candidate_id sort (tiebreaker)

        Returns the winning candidate, or None if no active/shadow in scope.
        Losers are superseded (set to REJECTED and removed from active/shadow).
        """
        # Gather all active + shadow candidates in this scope
        contenders: List[LearningCandidate] = []
        for c in self._active_set.values():
            if c.scope == scope:
                contenders.append(c)
        for c in self._shadow_set.values():
            if c.scope == scope and c.candidate_id not in self._active_set:
                contenders.append(c)

        if len(contenders) <= 1:
            return contenders[0] if contenders else None

        def _sort_key(c: LearningCandidate):
            # human_approved: check if status_history contains human approval
            is_human = 0
            if hasattr(c, "status_history") and c.status_history:
                for sh in c.status_history:
                    reason = getattr(sh, "reason", "") or ""
                    if "human approved" in reason.lower():
                        is_human = 1
                        break

            is_active = 1 if c.status == CandidateStatus.ACTIVE else 0
            confidence = c.confidence or 0.0
            # validated_at: use the latest status change timestamp, or created_at
            validated_at = datetime.min.replace(tzinfo=timezone.utc)
            if hasattr(c, "status_history") and c.status_history:
                last = c.status_history[-1]
                if hasattr(last, "timestamp") and last.timestamp:
                    validated_at = last.timestamp
            elif hasattr(c, "created_at") and c.created_at:
                validated_at = c.created_at

            evidence_count = len(c.evidence_links) if c.evidence_links else 0

            return (is_human, is_active, confidence, validated_at, evidence_count, c.candidate_id)

        contenders.sort(key=_sort_key, reverse=True)
        winner = contenders[0]

        # Supersede losers
        for loser in contenders[1:]:
            loser.status = CandidateStatus.REJECTED
            self._active_set.pop(loser.candidate_id, None)
            self._shadow_set.pop(loser.candidate_id, None)
            logger.info(
                f"[PromotionManager] conflict resolution: "
                f"superseded {loser.candidate_id} in scope '{scope}' "
                f"(winner={winner.candidate_id})"
            )

        return winner

    def remove_from_active(
        self, candidate_id: str, reason: str = ""
    ) -> Optional[LearningCandidate]:
        """Remove a candidate from the active set (for rollback)."""
        candidate = self._active_set.pop(candidate_id, None)
        if candidate:
            candidate.status = CandidateStatus.ROLLED_BACK
            self._record_version(
                changes=[f"removed:{candidate_id}"],
                rollback_info={
                    "candidate_id": candidate_id,
                    "reason": reason,
                    "before_value": candidate.rollback_info.before_value,
                },
            )
        return candidate

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _promote_to_active(
        self, candidate: LearningCandidate, reason: str
    ) -> LearningCandidate:
        """Move candidate to active status and update ActiveSet version."""
        candidate.status = CandidateStatus.ACTIVE
        self._active_set[candidate.candidate_id] = candidate
        # Remove from shadow set if present
        self._shadow_set.pop(candidate.candidate_id, None)
        self._record_version(
            changes=[f"promoted:{candidate.candidate_id}"],
            rollback_info={
                "candidate_id": candidate.candidate_id,
                "before_value": candidate.rollback_info.before_value,
            },
        )
        # Resolve conflicts: ensure single active per scope
        if candidate.scope:
            self.resolve_conflicts(candidate.scope)
        # Sync status to DB
        if self._learning_store:
            try:
                self._learning_store.update_status(
                    candidate.candidate_id, CandidateStatus.ACTIVE, reason=reason,
                )
            except Exception as exc:
                logger.warning(f"[PromotionManager] DB status sync failed: {exc}")
        logger.info(
            f"[PromotionManager] candidate {candidate.candidate_id} "
            f"promoted to active: {reason}"
        )
        return candidate

    def _record_version(
        self,
        changes: List[str],
        rollback_info: Optional[Dict[str, Any]] = None,
    ) -> EvolutionVersion:
        """Create a new EvolutionVersion for the ActiveSet and persist to DB."""
        self._current_version_number += 1
        version = EvolutionVersion(
            version_id=str(uuid.uuid4()),
            version_number=self._current_version_number,
            timestamp=datetime.now(timezone.utc),
            changes=changes,
            rollback_info=rollback_info,
        )
        self._versions.append(version)

        # Persist to DB
        if self._db_engine:
            try:
                self._persist_version(version)
            except Exception as exc:
                logger.warning(f"[PromotionManager] version persist failed: {exc}")

        return version

    def _persist_version(self, version: EvolutionVersion) -> None:
        """Write an EvolutionVersion to the database."""
        from sqlmodel import Session
        with Session(self._db_engine) as session:
            db_obj = EvolutionVersionDB(
                version_id=version.version_id,
                version_number=version.version_number,
                timestamp=version.timestamp,
                changes=json.dumps(version.changes),
                rollback_info=json.dumps(version.rollback_info, default=str) if version.rollback_info else None,
            )
            session.add(db_obj)
            session.commit()

    def _restore_from_db(self) -> None:
        """Restore ActiveSet and versions from DB on startup."""
        from sqlmodel import Session, select
        try:
            with Session(self._db_engine) as session:
                # Restore versions
                stmt = select(EvolutionVersionDB).order_by(EvolutionVersionDB.version_number)
                rows = session.exec(stmt).all()
                for row in rows:
                    v = EvolutionVersion(
                        version_id=row.version_id,
                        version_number=row.version_number,
                        timestamp=row.timestamp,
                        changes=json.loads(row.changes) if row.changes else [],
                        rollback_info=json.loads(row.rollback_info) if row.rollback_info else None,
                    )
                    self._versions.append(v)
                if self._versions:
                    self._current_version_number = self._versions[-1].version_number

                # Restore active_set from LearningStore
                if self._learning_store:
                    from app.avatar.evolution.models import CandidateStatus as CS
                    active_candidates = self._learning_store.query_candidates(
                        status=CS.ACTIVE, limit=1000,
                    )
                    for c in active_candidates:
                        self._active_set[c.candidate_id] = c

                    # Restore pending approvals (shadow candidates)
                    shadow_candidates = self._learning_store.query_candidates(
                        status=CS.SHADOW, limit=1000,
                    )
                    for c in shadow_candidates:
                        # Only high-risk types go to pending_approvals
                        from app.avatar.evolution.models import CandidateType
                        high_risk = {CandidateType.POLICY_HINT, CandidateType.WORKFLOW_TEMPLATE}
                        if c.type in high_risk:
                            self._pending_approvals[c.candidate_id] = c

            logger.info(
                f"[PromotionManager] restored {len(self._active_set)} active, "
                f"{len(self._pending_approvals)} pending, "
                f"{len(self._versions)} versions from DB"
            )
        except Exception as exc:
            logger.warning(f"[PromotionManager] DB restore failed: {exc}")
