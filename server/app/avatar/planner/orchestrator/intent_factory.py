"""
Intent 工厂（IntentFactory）

职责：
- 唯一的 Intent 创建点
- 一次性设置完整的 metadata（包括 subtask_type, resolved_inputs）
- 后续代码不再修改 metadata

关键：metadata 在这里设置后，永不覆盖。
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict

from ..models.subtask import CompositeTask, SubTask


class IntentFactory:
    """
    Intent 工厂
    
    这是唯一创建子任务 Intent 的地方。
    metadata 在这里一次性设置完整，确保类型信息不会丢失。
    """
    
    def create(
        self,
        subtask: SubTask,
        composite: CompositeTask,
        original_intent: Any,
        resolved_inputs: Dict[str, Any]
    ) -> Any:
        """
        创建子任务的 Intent
        
        关键：metadata 包含所有必要信息，后续不再修改。
        
        Args:
            subtask: 子任务对象
            composite: 复合任务对象
            original_intent: 原始 Intent
            resolved_inputs: 已解析的输入（无占位符）
        
        Returns:
            IntentSpec: 构造好的 Intent
        """
        from ...intent.models import IntentSpec, IntentDomain
        from ..models.subtask import SubTaskType
        
        # 构建 resolved_inputs 的摘要（用于 Prompt 展示）
        resolved_summary = self._build_resolved_summary(resolved_inputs)
        
        # 🎯 修复：根据 SubTaskType 映射到正确的 IntentDomain
        domain = self._map_subtask_type_to_domain(subtask.type)
        
        # 一次性构造完整的 metadata
        metadata = {
            # === 子任务标识 ===
            "subtask_id": subtask.id,
            "is_subtask": True,
            
            # === 父任务信息 ===
            "parent_task_id": composite.id,
            "parent_goal": composite.goal,
            
            # === 【关键】子任务类型（用于技能过滤） ===
            "subtask_type": subtask.type,
            "allow_dangerous_skills": subtask.allow_dangerous_skills,
            
            # === 【关键】已解析的输入（Planner 可直接使用） ===
            "resolved_inputs": resolved_inputs,
            "resolved_values_summary": resolved_summary,
            
            # === 会话信息（继承自原始 Intent） ===
            "session_id": (
                getattr(original_intent, "metadata", {}).get("session_id")
                if hasattr(original_intent, "metadata")
                else None
            ),
            
            # === 继承原始 Intent 的其他 metadata ===
            **(getattr(original_intent, "metadata", {}) or {})
        }
        
        # 创建 Intent
        intent = IntentSpec(
            id=str(uuid.uuid4()),
            goal=subtask.goal,
            intent_type=getattr(original_intent, "intent_type", "subtask"),
            domain=domain,  # 🎯 使用映射后的 domain，而不是继承
            params=resolved_inputs,  # 已解析的输入作为 params
            metadata=metadata,
            raw_user_input=subtask.goal
        )
        
        return intent
    
    def _map_subtask_type_to_domain(self, subtask_type: Any) -> Any:
        """
        将 SubTaskType 映射到 IntentDomain（新架构 - 简化版）
        
        新架构策略：
        - FILE_IO → FILE
        - 其他所有类型 → OTHER
        - 不创建专用 domain，使用通用分类
        
        Args:
            subtask_type: SubTaskType 枚举值
        
        Returns:
            IntentDomain: 映射后的 domain
        """
        from ...intent.models import IntentDomain
        from ..models.types import SubTaskType
        
        # SubTaskType → IntentDomain 映射表（新架构：只映射实际存在的类型）
        TYPE_TO_DOMAIN = {
            SubTaskType.FILE_IO: IntentDomain.FILE,
            SubTaskType.CONTENT_GENERATION: IntentDomain.OTHER,
            SubTaskType.INFORMATION_EXTRACTION: IntentDomain.OTHER,
            SubTaskType.GUI_OPERATION: IntentDomain.UI,
            SubTaskType.CONTROL_FLOW: IntentDomain.OTHER,
            SubTaskType.GENERAL_EXECUTION: IntentDomain.OTHER,
        }
        
        # 如果 subtask_type 是枚举，直接查表
        if hasattr(subtask_type, 'value'):
            return TYPE_TO_DOMAIN.get(subtask_type, IntentDomain.OTHER)
        
        # 如果是字符串，尝试转换
        if isinstance(subtask_type, str):
            try:
                enum_type = SubTaskType(subtask_type)
                return TYPE_TO_DOMAIN.get(enum_type, IntentDomain.OTHER)
            except (ValueError, KeyError):
                pass
        
        # 默认返回 OTHER
        return IntentDomain.OTHER
    
    def _build_resolved_summary(self, resolved_inputs: Dict[str, Any]) -> Dict[str, str]:
        """
        构建已解析输入的摘要（用于 Prompt 展示）
        
        截断长文本，避免 Prompt 过长。
        
        Args:
            resolved_inputs: 已解析的输入字典
        
        Returns:
            Dict[str, str]: 摘要字典
        """
        summary = {}
        
        for key, value in resolved_inputs.items():
            if isinstance(value, str):
                # 字符串：截断到 100 字符
                summary[key] = value[:100] + "..." if len(value) > 100 else value
            elif isinstance(value, dict):
                # 字典：序列化后截断
                json_str = json.dumps(value, ensure_ascii=False)
                summary[key] = json_str[:100] + "..." if len(json_str) > 100 else json_str
            else:
                # 其他类型：转字符串后截断
                str_val = str(value)
                summary[key] = str_val[:100] + "..." if len(str_val) > 100 else str_val
        
        return summary

