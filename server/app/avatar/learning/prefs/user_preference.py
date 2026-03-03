# app/avatar/learning/prefs/user_preference.py
from __future__ import annotations

from typing import Dict, Optional

from ..base import LearningContext, LearningExample, LearningModule, LearningResult


class UserPreferenceLearner(LearningModule):
    """
    学习用户偏好（保存到内存 & Knowledge Memory）：

    约定：
    - 只关心 example.kind == "task_finished"
    - 如果 example.input_data["extra"]["learn_user_prefs"] 是 dict：
        {
          "default_report_dir": "...",
          "default_format": "markdown",
          ...
        }
      则把这些键值视为“用户偏好更新”。

    行为：
    - 在本进程内缓存每个 user_id 的偏好
    - 如果 ctx.memory 存在，则调用 ctx.memory.set_user_preference(user_id, merged_prefs)
    """

    name = "user_preference"
    description = "Learns and persists user preferences based on task results."

    def __init__(self) -> None:
        # user_id -> prefs dict
        self._prefs_cache: Dict[str, Dict[str, object]] = {}

    def _merge_prefs(
        self,
        old: Dict[str, object],
        new: Dict[str, object],
    ) -> Dict[str, object]:
        merged = dict(old)
        merged.update(new)
        return merged

    def get_prefs(self, user_id: str) -> Optional[Dict[str, object]]:
        """获取用户偏好（从内存缓存）"""
        return self._prefs_cache.get(user_id)
    
    def get_preference(self, user_id: str, key: str, default=None):
        """获取单个偏好项"""
        prefs = self.get_prefs(user_id)
        if prefs:
            return prefs.get(key, default)
        return default

    def _auto_detect_preferences(self, example: LearningExample, ctx: LearningContext) -> Dict[str, object]:
        """
        自动检测用户偏好（基于任务执行历史）
        
        检测规则：
        1. 文件格式偏好：用户更喜欢用 Excel 还是 CSV？
        2. 保存路径偏好：用户常用的文件夹？
        3. 语言偏好：中文还是英文？
        4. 工具偏好：喜欢用 python.run 还是直接用 excel.append？
        """
        detected_prefs = {}
        
        data = example.input_data if isinstance(example.input_data, dict) else {}
        extra = data.get("extra", {})
        steps = extra.get("steps", [])
        
        # 1. 检测文件格式偏好
        for step in steps:
            if isinstance(step, dict):
                skill = step.get("skill", "")
                if "excel" in skill:
                    detected_prefs["preferred_file_format"] = "excel"
                    break
                elif "csv" in skill:
                    detected_prefs["preferred_file_format"] = "csv"
                    break
                elif "word" in skill:
                    detected_prefs["preferred_doc_format"] = "word"
                    break
        
        # 2. 检测是否喜欢用 python.run（高级用户）
        python_usage_count = sum(1 for step in steps if isinstance(step, dict) and step.get("skill") == "python.run")
        if python_usage_count > 0:
            # 获取历史 python.run 使用次数
            user_id = example.metadata.get("user_id") or ctx.user_id or "default"
            old_prefs = self._prefs_cache.get(user_id, {})
            total_python_usage = old_prefs.get("python_usage_count", 0) + python_usage_count
            detected_prefs["python_usage_count"] = total_python_usage
            
            # 如果使用次数 > 5，标记为高级用户
            if total_python_usage >= 5:
                detected_prefs["user_level"] = "advanced"
        
        # 3. 检测语言偏好（基于用户输入）
        user_request = extra.get("user_request", "")
        if user_request:
            # 简单检测：是否包含中文字符
            has_chinese = any('\u4e00' <= char <= '\u9fff' for char in user_request)
            detected_prefs["preferred_language"] = "zh" if has_chinese else "en"
        
        return detected_prefs
    
    def learn(
        self,
        example: LearningExample,
        *,
        ctx: LearningContext,
    ) -> LearningResult:
        # 只关心任务完成事件
        if example.kind != "task_finished":
            return LearningResult(success=True, message="ignored_non_task_finished")

        user_id = example.metadata.get("user_id") or ctx.user_id or "default"  # 使用 "default" 作为后备

        data = example.input_data if isinstance(example.input_data, dict) else {}
        extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
        
        # 支持两种方式学习偏好：
        # 1. 显式指定（旧逻辑）
        explicit_prefs = extra.get("learn_user_prefs")
        
        # 2. 自动检测（新逻辑）
        auto_detected_prefs = self._auto_detect_preferences(example, ctx)
        
        # 合并两种来源的偏好
        prefs_update = {}
        if isinstance(explicit_prefs, dict):
            prefs_update.update(explicit_prefs)
        if auto_detected_prefs:
            prefs_update.update(auto_detected_prefs)
        
        if not prefs_update:
            # 没有需要学习的偏好
            return LearningResult(success=True, message="no_prefs_update")

        old_prefs = self._prefs_cache.get(user_id, {})
        new_prefs = self._merge_prefs(old_prefs, prefs_update)
        self._prefs_cache[user_id] = new_prefs

        # 如有 MemoryManager，则写入 Knowledge Memory
        # 完全重构：使用通用的 set_knowledge 接口
        if ctx.memory is not None:
            try:
                ctx.memory.set_knowledge(f"user_prefs:{user_id}", new_prefs)
            except Exception as e:  # noqa: BLE001
                # 不让异常冒泡，避免影响主流程
                return LearningResult(
                    success=False,
                    message=f"update_memory_failed: {e}",
                    data={"prefs": new_prefs},
                )

        return LearningResult(
            success=True,
            message="user_prefs_updated",
            data={"user_id": user_id, "prefs": new_prefs, "auto_detected": bool(auto_detected_prefs)},
        )
