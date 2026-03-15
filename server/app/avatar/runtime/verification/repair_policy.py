"""
RepairPolicy — formalized repair retry strategy with idempotency protection.

Separates pure repair actions (RepairStrategy) from terminal state decisions
(CompletionDecision), which are handled independently.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.verification.models import VerificationResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RepairStrategy(str, Enum):
    """Pure repair actions — does NOT include terminal state decisions."""
    RERUN_LAST_STEP = "rerun_last_step"
    PATCH_FILE = "patch_file"
    FULL_RETRY = "full_retry"


# ---------------------------------------------------------------------------
# Policy configuration
# ---------------------------------------------------------------------------

@dataclass
class RepairPolicy:
    """
    Repair retry policy configuration.
    Supports per-skill overrides for high side-effect skills.
    """
    max_attempts: int = 3
    strategy_sequence: List[RepairStrategy] = field(
        default_factory=lambda: [
            RepairStrategy.RERUN_LAST_STEP,
            RepairStrategy.PATCH_FILE,
            RepairStrategy.FULL_RETRY,
        ]
    )
    idempotency_key_scope: List[str] = field(
        default_factory=lambda: ["skill_name", "target_path", "task_id"]
    )
    partial_success_threshold: float = 0.5  # passed verifier ratio ≥ this → PARTIAL_SUCCESS

    def get_strategy_for_attempt(self, attempt_number: int) -> RepairStrategy:
        """
        Return the strategy for a given attempt number (1-indexed).
        Strictly follows strategy_sequence order — no skipping.
        """
        if not self.strategy_sequence:
            return RepairStrategy.FULL_RETRY
        idx = min(attempt_number - 1, len(self.strategy_sequence) - 1)
        return self.strategy_sequence[idx]


# ---------------------------------------------------------------------------
# Idempotency key
# ---------------------------------------------------------------------------

@dataclass
class IdempotencyKey:
    """
    Idempotency key for repair operations.
    Generated from: skill_name + normalized_params_hash + target_path + task_id + attempt_number
    """
    skill_name: str
    normalized_params_hash: str
    target_path: Optional[str]
    task_id: str
    attempt_number: int

    def compute(self) -> str:
        """Generate a short hash string for this key."""
        raw = (
            f"{self.skill_name}:{self.normalized_params_hash}:"
            f"{self.target_path or ''}:{self.task_id}:{self.attempt_number}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @classmethod
    def from_repair_context(
        cls,
        skill_name: str,
        params: Dict[str, Any],
        target_path: Optional[str],
        task_id: str,
        attempt_number: int,
    ) -> "IdempotencyKey":
        """Create an IdempotencyKey from repair context."""
        # Normalize params: sort keys, serialize deterministically
        try:
            normalized = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
            params_hash = hashlib.sha256(normalized.encode()).hexdigest()[:12]
        except Exception:
            params_hash = "unknown"
        return cls(
            skill_name=skill_name,
            normalized_params_hash=params_hash,
            target_path=target_path,
            task_id=task_id,
            attempt_number=attempt_number,
        )


# ---------------------------------------------------------------------------
# Attempt record
# ---------------------------------------------------------------------------

@dataclass
class RepairAttemptRecord:
    attempt_number: int
    strategy: RepairStrategy
    timestamp: float
    result_summary: str
    idempotency_key: str
    skipped_idempotent: bool = False  # True if skipped due to same key already executed


# ---------------------------------------------------------------------------
# CompletionDecision — terminal state arbitration (separate from RepairLoop)
# ---------------------------------------------------------------------------

class CompletionDecision:
    """
    Terminal state arbitration after repair exhaustion.

    Responsibility is SEPARATE from RepairLoop:
    - RepairLoop: pure repair actions
    - CompletionDecision: terminal state decisions
    """

    def decide(
        self,
        all_results: List["VerificationResult"],
        policy: RepairPolicy,
    ) -> str:
        """
        Decide terminal state based on verifier pass ratio.

        Returns:
        - "partial_success" if passed ratio >= partial_success_threshold
        - "failed" otherwise
        """
        from app.avatar.runtime.verification.models import VerificationStatus

        if not all_results:
            return "failed"

        passed = sum(1 for r in all_results if r.status == VerificationStatus.PASSED)
        total = len(all_results)
        ratio = passed / total

        logger.debug(
            f"[CompletionDecision] passed={passed}/{total} ratio={ratio:.2f} "
            f"threshold={policy.partial_success_threshold}"
        )

        if ratio >= policy.partial_success_threshold:
            return "partial_success"
        return "failed"


# ---------------------------------------------------------------------------
# Idempotency store (in-memory, per-session)
# ---------------------------------------------------------------------------

class IdempotencyStore:
    """
    Tracks executed repair operations by IdempotencyKey.
    Prevents duplicate side effects on retry.
    """

    def __init__(self) -> None:
        self._executed: Dict[str, RepairAttemptRecord] = {}

    def has_executed(self, key: IdempotencyKey) -> bool:
        return key.compute() in self._executed

    def record(self, key: IdempotencyKey, record: RepairAttemptRecord) -> None:
        self._executed[key.compute()] = record

    def get_result(self, key: IdempotencyKey) -> Optional[RepairAttemptRecord]:
        return self._executed.get(key.compute())
