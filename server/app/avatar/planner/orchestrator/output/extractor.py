"""
输出提取器
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...models import Task, StepStatus
from .mappings import SKILL_FIELD_MAPPINGS
from .strategies.direct import DirectMatchStrategy
from .strategies.pattern import PatternMatchStrategy
from .strategies.semantic import SemanticMatchStrategy
from .strategies.schema import SchemaMatchStrategy

logger = logging.getLogger(__name__)


class OutputExtractor:
    """
    输出提取器
    
    职责：
    - 从已完成的 Task 中提取输出
    - 使用多策略提取（直接匹配、语义匹配、模式匹配、Schema匹配）
    - 字段映射（处理技能输出字段与期望字段不匹配的情况）
    """
    
    def __init__(self, embedding_service: Optional[Any] = None):
        """
        Args:
            embedding_service: 语义向量服务（可选）
        """
        self._embedding_service = embedding_service
        self._semantic_strategy = SemanticMatchStrategy(embedding_service) if embedding_service else None
    
    def extract_task_outputs(
        self,
        task: Task,
        expected_outputs: List[str],
        available_skills: Dict[str, Any] = None,
        subtask_type: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        从已完成的 Task 中提取输出
        
        策略优先级（从高到低）：
        0. 标准字段映射：基于 subtask_type 使用标准输出字段
        1. 直接匹配：expected_output 直接存在于 raw_output
        2. 技能特定映射：使用 SKILL_FIELD_MAPPINGS
        3. 模式匹配：通用的字段命名模式
        4. 语义匹配：使用 embedding 相似度
        5. Schema匹配：从技能的 output_schema 获取
        6. 降级策略：使用完整输出
        
        Args:
            task: 已完成的Task对象
            expected_outputs: 期望的输出字段列表
            available_skills: 可选的技能信息字典
            subtask_type: 子任务类型（用于确定标准输出字段）
        
        Returns:
            Dict[str, Any]: 提取的输出字典
        """
        outputs = {}
        success_steps = [s for s in task.steps if s.status == StepStatus.SUCCESS]
        
        if not success_steps:
            logger.warning(f"Task {task.id} has no successful steps, cannot extract outputs")
            return outputs
        
        # 获取最后一个成功步骤的输出（作为主要数据源）
        last_step = success_steps[-1]
        raw_output = last_step.result.output if (last_step.result and last_step.result.output is not None) else None
        
        if raw_output is None:
            logger.warning(f"Step {last_step.id} has no output, cannot extract")
            return outputs
        
        # 始终保存原始输出作为备份
        outputs["_raw_result"] = raw_output
        
        # 【方案2】如果有 subtask_type，强制提取标准输出字段
        if subtask_type:
            from ...models.types import get_policy
            
            policy = get_policy(subtask_type)
            standard_fields = policy.standard_output_fields
            
            if standard_fields:
                logger.debug(f"[方案2] Extracting standard fields for type {subtask_type.value}: {standard_fields}")
                
                # 强制尝试提取标准字段
                for std_field in standard_fields:
                    extracted_value = self._extract_single_output(
                        std_field,
                        raw_output,
                        output_schema=None,
                        skill_name=last_step.skill_name,
                        subtask_type=subtask_type
                    )
                    
                    if extracted_value is not None:
                        outputs[std_field] = extracted_value
                        logger.info(f"✅ [方案2] Extracted standard field '{std_field}' = {str(extracted_value)[:100]}")
                    else:
                        # 【增强】如果标准策略失败，尝试强制提取
                        fallback_value = self._force_extract_standard_field(
                            std_field, raw_output, subtask_type
                        )
                        if fallback_value is not None:
                            outputs[std_field] = fallback_value
                            logger.info(f"✅ [方案2-Fallback] Extracted '{std_field}' via force extraction")
        
        # 获取 Schema（可选）
        output_schema = self._get_output_schema(last_step.skill_name, available_skills)
        
        if not expected_outputs:
            # 没有指定输出：直接使用完整结果
            outputs["result"] = raw_output
            logger.debug(f"No expected_outputs specified, using full result")
        else:
            # 指定了输出：使用多策略提取
            for output_name in expected_outputs:
                # 跳过已经提取的标准字段
                if output_name in outputs:
                    continue
                
                extracted_value = self._extract_single_output(
                    output_name,
                    raw_output,
                    output_schema,
                    skill_name=last_step.skill_name,
                    subtask_type=subtask_type
                )
                
                if extracted_value is not None:
                    outputs[output_name] = extracted_value
                else:
                    # 提取失败：使用完整输出降级
                    outputs[output_name] = raw_output
                    available_fields = list(raw_output.keys()) if isinstance(raw_output, dict) else type(raw_output).__name__
                    logger.warning(
                        f"⚠️ Could not extract '{output_name}', using full result. "
                        f"Available fields: {available_fields}"
                    )
        
        return outputs
    
    def _extract_single_output(
        self,
        output_name: str,
        raw_output: Any,
        output_schema: Optional[Dict] = None,
        skill_name: Optional[str] = None,
        subtask_type: Optional[Any] = None
    ) -> Optional[Any]:
        """
        提取单个输出字段（使用多策略）
        
        Args:
            output_name: 期望的输出字段名
            raw_output: 原始输出
            output_schema: 输出Schema（可选）
            skill_name: 技能名称（可选）
            subtask_type: 子任务类型（可选，用于辅助推断）
        
        Returns:
            提取的值，如果失败返回 None
        """
        # 策略1：直接匹配
        result = DirectMatchStrategy.extract(output_name, raw_output)
        if result is not None:
            return result
        
        if not isinstance(raw_output, dict):
            return None
        
        # 策略2：技能特定字段映射
        if skill_name:
            result = self._skill_mapping_extract(output_name, raw_output, skill_name)
            if result is not None:
                return result
        
        # [新增] 策略2.5：基于内部知识库的别名/候选词匹配
        # 利用 _get_field_candidates 中的通用和特定类型别名（例如 file_path -> fs_path）
        candidates = self._get_field_candidates(output_name, subtask_type)
        # 移除 output_name 本身，因为策略1已经试过了，但也无妨
        for candidate in candidates:
            if candidate in raw_output:
                logger.info(f"✅ Extracted '{output_name}' via alias match '{candidate}'")
                return raw_output[candidate]
        
        # 策略3：基于模式的智能映射
        result = PatternMatchStrategy.extract(output_name, raw_output)
        if result is not None:
            return result
        
        # 策略4：语义相似度匹配（如果服务可用）
        if self._semantic_strategy and len(raw_output) > 1:
            result = self._semantic_strategy.extract(output_name, raw_output)
            if result is not None:
                return result
        
        # 策略5：Schema 辅助匹配
        result = SchemaMatchStrategy.extract(output_name, raw_output, output_schema)
        if result is not None:
            return result
        
        # 策略6：单字段字典降级
        if len(raw_output) == 1:
            value = list(raw_output.values())[0]
            logger.info(f"✅ Extracted '{output_name}' via single_field_fallback")
            return value
        
        # 所有策略失败
        return None
    
    def _skill_mapping_extract(
        self,
        output_name: str,
        raw_output: Dict[str, Any],
        skill_name: str
    ) -> Optional[Any]:
        """
        使用技能特定字段映射提取
        
        Args:
            output_name: 期望的字段名
            raw_output: 原始输出
            skill_name: 技能名称
        
        Returns:
            提取的值，如果失败返回 None
        """
        # 优先使用技能特定映射
        skill_mappings = SKILL_FIELD_MAPPINGS.get(skill_name, {})
        if output_name in skill_mappings:
            actual_field = skill_mappings[output_name]
            if actual_field in raw_output:
                logger.info(
                    f"✅ Extracted '{output_name}' via skill_mapping "
                    f"(skill={skill_name}, mapped to '{actual_field}')"
                )
                return raw_output[actual_field]
        
        # 回退到通用映射
        universal_mappings = SKILL_FIELD_MAPPINGS.get("_universal_", {})
        if output_name in universal_mappings:
            actual_field = universal_mappings[output_name]
            if actual_field in raw_output:
                logger.info(
                    f"✅ Extracted '{output_name}' via universal_mapping "
                    f"(mapped to '{actual_field}')"
                )
                return raw_output[actual_field]
        
        return None
    
    def _force_extract_standard_field(
        self,
        field_name: str,
        raw_output: Any,
        subtask_type: Any
    ) -> Optional[Any]:
        """
        【方案2增强】强制提取标准字段
        
        当常规策略失败时，使用更激进的提取方法。
        
        Args:
            field_name: 字段名
            raw_output: 原始输出
            subtask_type: 子任务类型
        
        Returns:
            提取的值，如果失败返回 None
        """
        from ...models.types import SubTaskType
        
        # 策略1：如果是字符串，直接返回（适用于 text/content 类型）
        if isinstance(raw_output, str):
            if field_name in ["text", "content", "result"]:
                logger.debug(f"[ForceExtract] Returning raw string for '{field_name}'")
                return raw_output
        
        # 策略2：如果是字典，尝试多个可能的键名
        if isinstance(raw_output, dict):
            # 根据 subtask_type 和 field_name 确定候选键名
            candidates = self._get_field_candidates(field_name, subtask_type)
            
            for candidate in candidates:
                if candidate in raw_output:
                    logger.debug(f"[ForceExtract] Found '{field_name}' via candidate '{candidate}'")
                    return raw_output[candidate]
            
            # 策略3：如果字典只有一个值，直接返回
            if len(raw_output) == 1:
                value = list(raw_output.values())[0]
                logger.debug(f"[ForceExtract] Returning single value for '{field_name}'")
                return value
            
            # 策略4：尝试返回最大的字符串值（可能是主要内容）
            if field_name in ["text", "content"]:
                str_values = [v for v in raw_output.values() if isinstance(v, str)]
                if str_values:
                    longest = max(str_values, key=len)
                    logger.debug(f"[ForceExtract] Returning longest string for '{field_name}'")
                    return longest
        
        # 策略5：如果是列表，返回第一个元素
        if isinstance(raw_output, list) and raw_output:
            logger.debug(f"[ForceExtract] Returning first element for '{field_name}'")
            return raw_output[0]
        
        return None
    
    def _get_field_candidates(
        self,
        field_name: str,
        subtask_type: Any
    ) -> List[str]:
        """
        获取字段名的候选键名列表
        
        Args:
            field_name: 目标字段名
            subtask_type: 子任务类型
        
        Returns:
            List[str]: 候选键名列表（按优先级排序）
        """
        from ...models.types import SubTaskType
        
        # 通用候选
        candidates = [field_name]
        
        # 根据字段名添加候选
        if field_name == "text":
            candidates.extend(["content", "output", "result", "generated_text", "response"])
        elif field_name == "content":
            candidates.extend(["text", "output", "result", "data"])
        elif field_name == "file_path":
            candidates.extend(["path", "filepath", "fs_path", "output_path"])
        elif field_name == "data":
            candidates.extend(["result", "output", "extracted_data", "info"])
        elif field_name == "result":
            candidates.extend(["output", "data", "response"])
        
        # 根据 subtask_type 添加类型特定的候选
        if subtask_type == SubTaskType.CONTENT_GENERATION:
            if field_name in ["text", "content"]:
                candidates.append("generated_content")
        elif subtask_type == SubTaskType.FILE_IO:
            if field_name == "file_path":
                candidates.extend(["created_file", "saved_path", "src", "dst"])
        
        return candidates
    
    def _get_output_schema(
        self,
        skill_name: Optional[str],
        available_skills: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict]:
        """
        获取技能的输出 Schema
        
        Args:
            skill_name: 技能名称
            available_skills: 可用技能字典
        
        Returns:
            输出Schema，如果不存在返回 None
        """
        if not skill_name:
            return None
        
        # 尝试从 skill_registry 获取
        try:
            from app.avatar.skills.registry import skill_registry
            skill_cls = skill_registry.get(skill_name)
            if skill_cls and hasattr(skill_cls, 'spec') and skill_cls.spec.output_model:
                output_schema = skill_cls.spec.output_model.model_json_schema()
                logger.debug(f"✅ Found output_schema for skill '{skill_name}'")
                return output_schema
        except Exception as e:
            logger.debug(f"Could not get schema for skill '{skill_name}': {e}")
        
        # 尝试从 available_skills 获取
        if available_skills and skill_name in available_skills:
            skill_info = available_skills[skill_name]
            if isinstance(skill_info, dict) and "output_schema" in skill_info:
                logger.debug(f"✅ Found output_schema from available_skills for '{skill_name}'")
                return skill_info["output_schema"]
        
        return None

