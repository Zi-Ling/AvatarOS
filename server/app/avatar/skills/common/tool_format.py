# app/avatar/skills/common/tool_format.py
"""
将 SkillSpec 转换为 LLM Tool Calling 格式
"""

from typing import List, Dict, Any
from app.avatar.skills.base import SkillSpec
from app.llm.types import ToolDefinition


class SkillToToolConverter:
    """将技能定义转换为 Tool Calling 格式"""

    @staticmethod
    def convert(skill_spec: SkillSpec) -> ToolDefinition:
        parameters = skill_spec.input_model.model_json_schema()
        parameters.pop("title", None)
        parameters.pop("description", None)

        return ToolDefinition(
            name=skill_spec.name,
            description=skill_spec.description,
            parameters=parameters,
        )

    @staticmethod
    def convert_batch(skills: List[SkillSpec]) -> List[ToolDefinition]:
        tools = []
        for skill in skills:
            try:
                tools.append(SkillToToolConverter.convert(skill))
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to convert skill {skill.name}: {e}")
        return tools

    @staticmethod
    def convert_by_names(skill_names: List[str]) -> List[ToolDefinition]:
        from app.avatar.skills.registry import skill_registry
        tools = []
        for name in skill_names:
            skill_cls = skill_registry.get(name)
            if skill_cls:
                try:
                    tools.append(SkillToToolConverter.convert(skill_cls.spec))
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Failed to convert skill {name}: {e}")
        return tools
