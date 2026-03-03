# app/avatar/skills/common/tool_format.py
"""
技能定义转工具格式转换器
将 SkillSpec 转换为 LLM Tool Calling 格式
"""

from typing import List, Dict, Any
from app.avatar.skills.base import SkillSpec
from app.llm.types import ToolDefinition


class SkillToToolConverter:
    """将技能定义转换为 Tool Calling 格式"""
    
    @staticmethod
    def convert(skill_spec: SkillSpec) -> ToolDefinition:
        """
        将单个 SkillSpec 转换为 ToolDefinition
        
        Args:
            skill_spec: 技能规范
            
        Returns:
            ToolDefinition: OpenAI 格式的工具定义
        """
        # 从 Pydantic model 提取 JSON Schema
        parameters = skill_spec.input_model.model_json_schema()
        
        # 清理 schema 中不需要的字段
        parameters.pop("title", None)
        parameters.pop("description", None)
        
        # 构建描述（包含示例）
        description = skill_spec.description
        if skill_spec.examples:
            examples_text = "\n\nExamples:\n"
            for i, example in enumerate(skill_spec.examples[:2], 1):  # 限制2个示例
                examples_text += f"{i}. {example.get('description', '')}\n"
            description += examples_text
        
        return ToolDefinition(
            name=skill_spec.api_name,
            description=description,
            parameters=parameters
        )
    
    @staticmethod
    def convert_batch(
        skills: List[SkillSpec],
        filter_deprecated: bool = True
    ) -> List[ToolDefinition]:
        """
        批量转换技能定义
        
        Args:
            skills: 技能列表
            filter_deprecated: 是否过滤已废弃的技能
            
        Returns:
            List[ToolDefinition]: 工具定义列表
        """
        tools = []
        for skill in skills:
            if filter_deprecated and skill.deprecated:
                continue
            try:
                tools.append(SkillToToolConverter.convert(skill))
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"Failed to convert skill {skill.name}: {e}"
                )
        return tools
    
    @staticmethod
    def convert_by_names(skill_names: List[str]) -> List[ToolDefinition]:
        """
        根据技能名称列表转换
        
        Args:
            skill_names: 技能名称列表
            
        Returns:
            List[ToolDefinition]: 工具定义列表
        """
        from app.avatar.skills.registry import skill_registry
        
        tools = []
        for name in skill_names:
            skill_cls = skill_registry.get(name)
            if skill_cls and hasattr(skill_cls, 'spec'):
                try:
                    tools.append(SkillToToolConverter.convert(skill_cls.spec))
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(
                        f"Failed to convert skill {name}: {e}"
                    )
        return tools
