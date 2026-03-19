# server/app/avatar/runtime/graph/managers/recovery_policy_engine.py
"""
RecoveryPolicyEngine — recovery strategy engine.

Decision paths:
1. ErrorClassification-based (preferred): uses DEFAULT_RECOVERY_MAP + ERROR_CODE_OVERRIDES
2. Legacy string-matching fallback: uses _NON_RETRYABLE_ERRORS when ErrorClassifier is unavailable

Additional features:
- Context escalation: same RuntimeErrorClass 2 consecutive times → replan_subgraph
- Graceful fallback: ErrorClassifier failure → legacy string matching
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, Optional

from app.avatar.runtime.graph.types.error_classification import (
    ErrorClassification,
    ErrorCode,
    RecoveryResult,
    RuntimeErrorClass,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Recovery decision tables (Requirement 9)
# ---------------------------------------------------------------------------

DEFAULT_RECOVERY_MAP: Dict[RuntimeErrorClass, str] = {
    RuntimeErrorClass.TYPE_MISMATCH: "replan_current_step",
    RuntimeErrorClass.MISSING_FIELD: "replan_current_step",
    RuntimeErrorClass.MISSING_DEPENDENCY: "fail_fast",
    RuntimeErrorClass.INVALID_VALUE: "replan_current_step",
    RuntimeErrorClass.SYNTAX_ERROR: "replan_current_step",
    RuntimeErrorClass.EXTERNAL_IO_ERROR: "retry",
}

ERROR_CODE_OVERRIDES: Dict[ErrorCode, str] = {
    ErrorCode.PERMISSION_DENIED: "fail_fast",
    ErrorCode.DISK_FULL: "fail_fast",
}

# Context escalation threshold
_ESCALATION_THRESHOLD = 2


# ---------------------------------------------------------------------------
# Legacy fallback: non-retryable error keywords
# ---------------------------------------------------------------------------

_NON_RETRYABLE_ERRORS = {
    "permission denied",
    "access denied",
    "authentication failed",
    "authorization failed",
    "quota exceeded",
    "attributeerror",
    "typeerror",
    "keyerror",
    "valueerror",
    "nameerror",
    "indexerror",
    "zerodivisionerror",
    "unboundlocalerror",
    "jsondecodeeerror",
    "syntaxerror",
    "indentationerror",
    "modulenotfounderror",
    "importerror",
    "filenotfounderror",
}


class RecoveryPolicyEngine:
    """Recovery strategy engine with ErrorClassification-based decisions."""

    def __init__(self) -> None:
        # Track consecutive error classes per step for context escalation
        self._consecutive_errors: Dict[str, list] = defaultdict(list)

    # ------------------------------------------------------------------
    # Primary API: ErrorClassification-based decision
    # ------------------------------------------------------------------

    def decide_from_classification(
        self,
        classification: ErrorClassification,
        step_id: str = "",
    ) -> RecoveryResult:
        """Decide recovery strategy based on structured ErrorClassification.

        Decision order:
        1. Check ERROR_CODE_OVERRIDES whitelist
        2. Check context escalation (same class 2x consecutive → replan_subgraph)
        3. Fall back to DEFAULT_RECOVERY_MAP
        """
        error_class = classification.error_class
        error_code = classification.error_code

        # 1. ErrorCode override whitelist
        if error_code in ERROR_CODE_OVERRIDES:
            decision = ERROR_CODE_OVERRIDES[error_code]
            logger.info(
                "[RecoveryPolicy] Step %s: ErrorCode override %s → %s",
                step_id, error_code.value, decision,
            )
            return RecoveryResult(
                error_class=error_class,
                error_code=error_code,
                decision=decision,
                override_applied=True,
            )

        # 2. Context escalation: same RuntimeErrorClass 2 consecutive times
        if step_id:
            history = self._consecutive_errors[step_id]
            history.append(error_class)
            if len(history) >= _ESCALATION_THRESHOLD:
                recent = history[-_ESCALATION_THRESHOLD:]
                if all(ec == error_class for ec in recent):
                    logger.info(
                        "[RecoveryPolicy] Step %s: %d consecutive %s → replan_subgraph",
                        step_id, _ESCALATION_THRESHOLD, error_class.value,
                    )
                    return RecoveryResult(
                        error_class=error_class,
                        error_code=error_code,
                        decision="replan_subgraph",
                    )

        # 3. Default recovery map
        decision = DEFAULT_RECOVERY_MAP.get(error_class, "replan_current_step")
        logger.info(
            "[RecoveryPolicy] Step %s: %s.%s → %s (default)",
            step_id, error_class.value, error_code.value, decision,
        )
        return RecoveryResult(
            error_class=error_class,
            error_code=error_code,
            decision=decision,
        )

    def clear_history(self, step_id: str) -> None:
        """Clear consecutive error history for a step (e.g., after successful execution)."""
        self._consecutive_errors.pop(step_id, None)

    # ------------------------------------------------------------------
    # Legacy API: step_state-based decision (backward compatible)
    # ------------------------------------------------------------------

    def decide_step_recovery(self, step_state, max_retries: int = 3) -> str:
        """Legacy recovery decision based on step_state.

        Preserved for backward compatibility. New code should use
        decide_from_classification() instead.
        """
        status = step_state.status

        if status == "stale":
            if step_state.input_snapshot_json:
                logger.info(
                    "[RecoveryPolicy] Step %s is stale with input_snapshot → retry",
                    step_state.id,
                )
                return "retry"
            else:
                logger.info(
                    "[RecoveryPolicy] Step %s is stale without input_snapshot → rerun",
                    step_state.id,
                )
                return "rerun"

        if status == "failed":
            # Legacy string matching for non-retryable errors
            error_msg = (step_state.error_message or "").lower()
            for keyword in _NON_RETRYABLE_ERRORS:
                if keyword in error_msg:
                    logger.info(
                        "[RecoveryPolicy] Step %s failed with non-retryable error → escalate_to_replan",
                        step_state.id,
                    )
                    return "escalate_to_replan"

            if step_state.retry_count < max_retries:
                logger.info(
                    "[RecoveryPolicy] Step %s failed (retry_count=%d/%d) → retry",
                    step_state.id, step_state.retry_count, max_retries,
                )
                return "retry"
            else:
                logger.info(
                    "[RecoveryPolicy] Step %s failed (retry_count=%d >= %d) → escalate_to_replan",
                    step_state.id, step_state.retry_count, max_retries,
                )
                return "escalate_to_replan"

        if status == "blocked":
            logger.info("[RecoveryPolicy] Step %s is blocked → skip", step_state.id)
            return "skip"

        logger.debug(
            "[RecoveryPolicy] Step %s status=%s, no recovery needed → skip",
            step_state.id, status,
        )
        return "skip"

    def decide_checkpoint_rollback(
        self, task_session_id: str, checkpoint_manager
    ) -> Optional[str]:
        """Decide whether to rollback to a checkpoint."""
        checkpoint = checkpoint_manager.get_latest_valid_checkpoint(task_session_id)
        if checkpoint is None:
            logger.warning(
                "[RecoveryPolicy] No valid checkpoint found for %s",
                task_session_id,
            )
            return None

        logger.info(
            "[RecoveryPolicy] Recommending rollback to checkpoint %s "
            "(importance=%s, graph_version=%s)",
            checkpoint.id, checkpoint.importance, checkpoint.graph_version,
        )
        return checkpoint.id
