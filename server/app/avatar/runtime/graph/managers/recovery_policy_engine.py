# server/app/avatar/runtime/graph/managers/recovery_policy_engine.py
"""
RecoveryPolicyEngine — 恢复策略引擎

决策树：
- stale（心跳超时）
  - 有 input_snapshot → retry
  - 无 input_snapshot → rerun (replan)
- failed
  - retry_count < max_retries → retry
  - retry_count >= max_retries → escalate_to_replan
  - 不可重试错误 → escalate_to_replan
- blocked
  - 依赖可恢复 → 等待（skip）
  - 依赖不可恢复 → escalate_to_replan
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 不可重试的错误关键词
_NON_RETRYABLE_ERRORS = {
    # Auth / permission errors
    "permission denied",
    "access denied",
    "authentication failed",
    "authorization failed",
    "quota exceeded",
    # Deterministic Python runtime errors — retrying won't fix logic bugs
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
    """恢复策略引擎。"""

    def decide_step_recovery(self, step_state, max_retries: int = 3) -> str:
        """
        根据步骤状态决定恢复策略。

        Returns:
            'retry' — 从 input_snapshot 重试
            'rerun' — 重新规划输入后重跑
            'skip' — 跳过该步骤
            'escalate_to_replan' — 升级为重规划
        """
        status = step_state.status

        if status == "stale":
            # Stale 步骤：有 input_snapshot 则 retry，否则 rerun
            if step_state.input_snapshot_json:
                logger.info(
                    f"[RecoveryPolicy] Step {step_state.id} is stale with "
                    f"input_snapshot → retry"
                )
                return "retry"
            else:
                logger.info(
                    f"[RecoveryPolicy] Step {step_state.id} is stale without "
                    f"input_snapshot → rerun"
                )
                return "rerun"

        if status == "failed":
            # 检查是否为不可重试错误
            error_msg = (step_state.error_message or "").lower()
            for keyword in _NON_RETRYABLE_ERRORS:
                if keyword in error_msg:
                    logger.info(
                        f"[RecoveryPolicy] Step {step_state.id} failed with "
                        f"non-retryable error → escalate_to_replan"
                    )
                    return "escalate_to_replan"

            # 检查重试次数
            if step_state.retry_count < max_retries:
                logger.info(
                    f"[RecoveryPolicy] Step {step_state.id} failed "
                    f"(retry_count={step_state.retry_count}/{max_retries}) → retry"
                )
                return "retry"
            else:
                logger.info(
                    f"[RecoveryPolicy] Step {step_state.id} failed "
                    f"(retry_count={step_state.retry_count} >= {max_retries}) "
                    f"→ escalate_to_replan"
                )
                return "escalate_to_replan"

        if status == "blocked":
            logger.info(
                f"[RecoveryPolicy] Step {step_state.id} is blocked → skip"
            )
            return "skip"

        # 其他状态不需要恢复
        logger.debug(
            f"[RecoveryPolicy] Step {step_state.id} status={status}, "
            f"no recovery needed → skip"
        )
        return "skip"

    def decide_checkpoint_rollback(
        self, task_session_id: str, checkpoint_manager
    ) -> Optional[str]:
        """
        决定是否需要回退到某个 checkpoint。

        Returns:
            checkpoint_id to rollback to, or None if no rollback needed.
        """
        checkpoint = checkpoint_manager.get_latest_valid_checkpoint(task_session_id)
        if checkpoint is None:
            logger.warning(
                f"[RecoveryPolicy] No valid checkpoint found for {task_session_id}"
            )
            return None

        logger.info(
            f"[RecoveryPolicy] Recommending rollback to checkpoint {checkpoint.id} "
            f"(importance={checkpoint.importance}, "
            f"graph_version={checkpoint.graph_version})"
        )
        return checkpoint.id
