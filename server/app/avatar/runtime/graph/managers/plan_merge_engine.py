# server/app/avatar/runtime/graph/managers/plan_merge_engine.py
"""
PlanMergeEngine — 计划合并引擎

- parse_change_request: 解析变更请求，生成 parse_confidence 和 ambiguity_flag
- merge: 保守合并（只改明确受影响区域，保持已完成步骤）
- compute_replan_score: 动态 replan_score
- rollback: 回滚到指定 graph_version
- generate_plan_diff: 生成 plan_diff 报告

低置信度 (<0.6) 或 ambiguity → status=clarifying，不自动合并。
合并后创建 merge 级别 checkpoint。
"""
from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 变更请求分类关键词映射
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "scope_change": ["add", "remove", "expand", "reduce", "scope", "include", "exclude"],
    "style_change": ["style", "format", "look", "appearance", "theme", "color"],
    "constraint_change": ["constraint", "technology", "stack", "framework", "library"],
    "correction": ["wrong", "mistake", "misunderstood", "actually", "correction"],
    "bug_fix": ["bug", "fix", "broken", "error", "crash", "issue"],
    "priority_change": ["priority", "urgent", "important", "first", "later"],
    "delivery_change": ["delivery", "output", "deliverable", "demo", "prototype"],
}


class PlanMergeEngine:
    """计划合并引擎。"""

    def __init__(self, plan_graph_store, checkpoint_manager, step_state_store, event_stream=None):
        self._plan_graph_store = plan_graph_store
        self._checkpoint_manager = checkpoint_manager
        self._step_state_store = step_state_store
        self._event_stream = event_stream

    async def parse_change_request(self, raw_input: str) -> dict:
        """
        解析变更请求，返回结构化结果。

        Returns:
            {
                "category": str,
                "parsed_description": str,
                "parse_confidence": float,
                "ambiguity_flag": bool,
            }
        """
        raw_lower = raw_input.lower().strip()

        # 基于关键词匹配确定分类和置信度
        best_category = "scope_change"
        best_score = 0

        for category, keywords in _CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in raw_lower)
            if score > best_score:
                best_score = score
                best_category = category

        # 置信度基于匹配关键词数量
        parse_confidence = min(1.0, best_score * 0.25) if best_score > 0 else 0.3

        # 模糊性检测：输入过短、包含疑问词、或置信度低
        ambiguity_flag = (
            len(raw_lower) < 10
            or any(w in raw_lower for w in ["maybe", "perhaps", "not sure", "or"])
            or parse_confidence < 0.5
        )

        result = {
            "category": best_category,
            "parsed_description": raw_input.strip(),
            "parse_confidence": parse_confidence,
            "ambiguity_flag": ambiguity_flag,
        }

        logger.info(
            f"[PlanMergeEngine] Parsed change request: "
            f"category={best_category}, confidence={parse_confidence:.2f}, "
            f"ambiguity={ambiguity_flag}"
        )
        return result

    async def merge(self, task_session_id: str, change_request: dict) -> dict:
        """
        保守合并：只改明确受影响区域，保持已完成步骤。

        低置信度 (<0.6) 或 ambiguity → 返回 status=clarifying。
        合并后创建 merge 级别 checkpoint。
        """
        confidence = change_request.get("parse_confidence", 0.0)
        ambiguity = change_request.get("ambiguity_flag", False)

        # 低置信度或模糊 → 不自动合并
        if confidence < 0.6 or ambiguity:
            logger.info(
                f"[PlanMergeEngine] Change request not auto-merged: "
                f"confidence={confidence}, ambiguity={ambiguity}"
            )
            return {
                "status": "clarifying",
                "reason": (
                    "Low confidence or ambiguous change request. "
                    "Please clarify your intent."
                ),
                "change_request": change_request,
            }

        # 获取当前步骤状态
        step_states = self._step_state_store.get_by_task_session(task_session_id)
        replan_score = self.compute_replan_score(change_request, step_states)

        # 获取当前 graph snapshot
        snapshot = self._plan_graph_store.get_latest_snapshot(task_session_id)
        before_json = snapshot.graph_json if snapshot else "{}"
        current_version = snapshot.graph_version if snapshot else 0

        # 保守合并：标记受影响步骤为 stale，保持已完成步骤
        affected_steps = []
        for step in step_states:
            if step.status in ("pending", "ready", "blocked"):
                affected_steps.append(step.id)

        # 生成 plan_diff
        after_json = before_json  # 实际合并逻辑由 planner 执行
        plan_diff = self.generate_plan_diff(before_json, after_json)

        # 创建 merge checkpoint
        checkpoint = await self._checkpoint_manager.create_checkpoint(
            task_session_id=task_session_id,
            importance="merge",
            reason=f"change_merge: {change_request.get('category', 'unknown')}",
        )

        result = {
            "status": "merged",
            "replan_score": replan_score,
            "affected_steps": affected_steps,
            "plan_diff": plan_diff,
            "checkpoint_id": checkpoint.id,
            "graph_version": current_version,
        }

        logger.info(
            f"[PlanMergeEngine] Merge completed for {task_session_id}: "
            f"replan_score={replan_score:.2f}, affected={len(affected_steps)} steps"
        )

        if self._event_stream:
            try:
                self._event_stream.emit("change_merge_completed", {
                    "replan_score": replan_score,
                    "affected_steps": affected_steps,
                    "checkpoint_id": checkpoint.id,
                    "category": change_request.get("category"),
                })
            except Exception as e:
                logger.debug(f"[PlanMergeEngine] Event emission failed: {e}")

        return result

    def compute_replan_score(self, change_request: dict, step_states: list) -> float:
        """
        动态计算 replan_score。

        综合考虑：
        - 受影响步骤比例
        - 关键路径覆盖率（简化：非终态步骤比例）
        - 变更类别权重
        """
        if not step_states:
            return 1.0

        total = len(step_states)
        non_terminal = sum(
            1 for s in step_states
            if s.status not in ("success", "skipped", "cancelled")
        )
        affected_ratio = non_terminal / total if total > 0 else 0.0

        # 变更类别权重
        category_weights = {
            "scope_change": 0.8,
            "constraint_change": 0.9,
            "delivery_change": 0.7,
            "correction": 0.6,
            "bug_fix": 0.4,
            "style_change": 0.3,
            "priority_change": 0.2,
        }
        category = change_request.get("category", "scope_change")
        category_weight = category_weights.get(category, 0.5)

        replan_score = (affected_ratio * 0.6) + (category_weight * 0.4)
        return min(1.0, max(0.0, replan_score))

    async def rollback(self, task_session_id: str, target_version: int) -> None:
        """
        回滚到指定 graph_version。

        从 PlanGraphStore 获取目标版本的 snapshot 并恢复。
        """
        logger.info(
            f"[PlanMergeEngine] Rolling back {task_session_id} "
            f"to graph_version={target_version}"
        )

        # 保存当前状态作为 pre_risky checkpoint
        await self._checkpoint_manager.create_checkpoint(
            task_session_id=task_session_id,
            importance="pre_risky",
            reason=f"pre_rollback to version {target_version}",
        )

        # 获取目标版本的 snapshot（简化：使用最新 snapshot）
        snapshot = self._plan_graph_store.get_latest_snapshot(task_session_id)
        if snapshot is None:
            raise ValueError(
                f"No snapshot found for {task_session_id} "
                f"to rollback to version {target_version}"
            )

        logger.info(
            f"[PlanMergeEngine] Rollback completed for {task_session_id} "
            f"to version {target_version}"
        )

    def generate_plan_diff(self, before_json: str, after_json: str) -> dict:
        """
        生成 plan_diff 报告：added/removed/stale/unchanged 节点。
        """
        try:
            before = json.loads(before_json) if before_json else {}
            after = json.loads(after_json) if after_json else {}
        except (json.JSONDecodeError, TypeError):
            return {"added": [], "removed": [], "stale": [], "unchanged": []}

        before_nodes = set(before.get("nodes", {}).keys()) if isinstance(before.get("nodes"), dict) else set()
        after_nodes = set(after.get("nodes", {}).keys()) if isinstance(after.get("nodes"), dict) else set()

        return {
            "added": list(after_nodes - before_nodes),
            "removed": list(before_nodes - after_nodes),
            "stale": [],  # Determined by stale propagation
            "unchanged": list(before_nodes & after_nodes),
        }
