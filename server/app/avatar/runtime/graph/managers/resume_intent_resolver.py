# server/app/avatar/runtime/graph/managers/resume_intent_resolver.py
"""
ResumeIntentResolver — 用户意图判别

基于简单关键词/启发式规则判断用户消息意图：
- resume: 继续旧任务
- change_request: 给旧任务提变更
- new_task: 新开独立任务
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 意图关键词
_RESUME_KEYWORDS = [
    "continue", "resume", "go on", "keep going", "proceed",
    "继续", "恢复", "接着",
]
_CHANGE_KEYWORDS = [
    "change", "modify", "update", "adjust", "instead", "but",
    "actually", "correction", "fix", "wrong",
    "改", "修改", "调整", "变更", "其实",
]
_NEW_TASK_KEYWORDS = [
    "new task", "start fresh", "different task", "another task",
    "新任务", "重新开始",
]


class ResumeIntentResolver:
    """恢复意图解析器。"""

    async def resolve(self, user_message: str, active_sessions: list) -> str:
        """
        判断用户消息意图。

        Returns:
            'resume' / 'change_request' / 'new_task'
        """
        msg_lower = user_message.lower().strip()

        # 没有活跃会话 → 一定是新任务
        if not active_sessions:
            logger.info("[ResumeIntentResolver] No active sessions → new_task")
            return "new_task"

        # 关键词匹配（按优先级）
        resume_score = sum(1 for kw in _RESUME_KEYWORDS if kw in msg_lower)
        change_score = sum(1 for kw in _CHANGE_KEYWORDS if kw in msg_lower)
        new_task_score = sum(1 for kw in _NEW_TASK_KEYWORDS if kw in msg_lower)

        # Determine intent based on highest score
        scores = {
            "resume": resume_score,
            "change_request": change_score,
            "new_task": new_task_score,
        }
        best_intent = max(scores, key=scores.get)  # type: ignore[arg-type]

        # If no keywords matched, default based on context
        if all(s == 0 for s in scores.values()):
            # Short message with active sessions → likely resume
            if len(msg_lower) < 20 and active_sessions:
                best_intent = "resume"
            else:
                # Longer message → likely change_request or new_task
                best_intent = "new_task"

        logger.info(
            f"[ResumeIntentResolver] Resolved intent: {best_intent} "
            f"(scores: resume={resume_score}, change={change_score}, "
            f"new_task={new_task_score})"
        )
        return best_intent
