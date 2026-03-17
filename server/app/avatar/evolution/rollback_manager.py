"""
rollback_manager.py — RollbackManager

Supports version-based rollback of promoted LearningCandidates.
Rollback does not delete history -- it creates a new version that reverts the effect.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from app.avatar.evolution.audit_logger import EvolutionAuditLogger
from app.avatar.evolution.learning_store import LearningStore
from app.avatar.evolution.models import (
    CandidateStatus,
    EvolutionVersion,
    LearningCandidate,
)
from app.avatar.evolution.promotion_manager import PromotionManager

logger = logging.getLogger(__name__)


class RollbackError(Exception):
    """Raised when rollback cannot proceed."""


class RollbackManager:
    """
    Manages rollback of promoted LearningCandidates.

    Supports:
    - Single candidate rollback
    - Version-based rollback (revert all changes in a version)
    - Rollback to a specific version number (revert everything after that version)

    Rollback never deletes history -- it creates new versions that undo effects.
    """

    def __init__(
        self,
        promotion_manager: PromotionManager,
        learning_store: Optional[LearningStore] = None,
        audit_logger: Optional[EvolutionAuditLogger] = None,
    ) -> None:
        self._promotion = promotion_manager
        self._learning_store = learning_store
        self._audit_logger = audit_logger

    def rollback_candidate(
        self,
        candidate_id: str,
        reason: str = "",
        operator: str = "",
    ) -> LearningCandidate:
        """
        Rollback a single candidate from the active set.
        Validates rollback_info completeness before proceeding.
        """
        active = self._promotion.active_set
        candidate = active.get(candidate_id)
        if not candidate:
            raise RollbackError(
                f"candidate {candidate_id} not in active set"
            )

        if not self._validate_rollback_info(candidate):
            raise RollbackError(
                f"candidate {candidate_id} has incomplete rollback_info"
            )

        rolled_back = self._promotion.remove_from_active(candidate_id, reason)
        if not rolled_back:
            raise RollbackError(
                f"failed to remove candidate {candidate_id} from active set"
            )

        if self._learning_store:
            self._learning_store.update_status(
                candidate_id,
                CandidateStatus.ROLLED_BACK,
                reason=reason or "rollback",
            )

        if self._audit_logger:
            self._audit_logger.log_status_change(
                candidate_id=candidate_id,
                from_status=CandidateStatus.ACTIVE.value,
                to_status=CandidateStatus.ROLLED_BACK.value,
                reason=f"rollback by {operator}: {reason}" if operator else reason,
            )

        logger.info(
            f"[RollbackManager] rolled back candidate {candidate_id}: {reason}"
        )
        return rolled_back

    def rollback_to_version(
        self,
        target_version_number: int,
        reason: str = "",
        operator: str = "",
    ) -> List[LearningCandidate]:
        """
        Rollback all changes after target_version_number.
        Reverts candidates promoted in versions > target_version_number.
        """
        versions = self._promotion._versions
        if not versions:
            raise RollbackError("no versions to rollback")

        if target_version_number < 0:
            raise RollbackError(
                f"invalid target version: {target_version_number}"
            )

        # Find versions to revert (in reverse order)
        versions_to_revert = [
            v for v in reversed(versions)
            if v.version_number > target_version_number
        ]

        if not versions_to_revert:
            logger.info(
                f"[RollbackManager] no versions after {target_version_number}"
            )
            return []

        rolled_back_candidates = []
        for version in versions_to_revert:
            for change in version.changes:
                if change.startswith("promoted:"):
                    cid = change.split(":", 1)[1]
                    try:
                        c = self.rollback_candidate(cid, reason=reason, operator=operator)
                        rolled_back_candidates.append(c)
                    except RollbackError as e:
                        logger.warning(
                            f"[RollbackManager] skip rollback {cid}: {e}"
                        )

        logger.info(
            f"[RollbackManager] rolled back to version {target_version_number}, "
            f"reverted {len(rolled_back_candidates)} candidates"
        )
        return rolled_back_candidates

    def _validate_rollback_info(self, candidate: LearningCandidate) -> bool:
        """
        Validate that rollback_info is complete enough to perform rollback.
        At minimum, before_value must be present (even if None means 'did not exist').
        """
        ri = candidate.rollback_info
        # rollback_info must exist and have been explicitly set
        # (before_value=None is valid -- means the item didn't exist before)
        return ri is not None
