"""
智能依赖推断器（DependencyInferrer）

职责：
- 使用语义分析推断子任务之间的依赖关系
- 自动补充缺失的 depends_on 和 inputs
- 提高对 LLM 生成质量的容错性

策略：
1. 语义相似度：计算 subtask goal 之间的相似度
2. 类型推断：根据 SubTaskType 推断典型的依赖模式
3. 顺序推断：后续任务优先依赖前面的任务
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
import re

from ..models.subtask import CompositeTask, SubTask, SubTaskStatus
from ..models.types import SubTaskType, get_standard_output_field

logger = logging.getLogger(__name__)


class DependencyInferrer:
    """
    智能依赖推断器
    
    使用语义分析和类型推断来自动补充子任务之间的依赖关系。
    """
    
    @staticmethod
    def _normalize_dep_id(dep: Any) -> str:
        """
        标准化依赖 ID
        
        LLM 经常在 depends_on 中写错格式，如：
        - "subtask_1.output.text" → "subtask_1"
        - "subtask_2.result" → "subtask_2"
        
        Args:
            dep: 原始依赖（可能是字符串或其他类型）
        
        Returns:
            str: 标准化后的依赖 ID（只保留第一个部分）
        """
        if not isinstance(dep, str):
            logger.warning(f"[Deps] Non-string dependency: {type(dep).__name__}, value={dep}")
            return ""
        
        # 分割并取第一个部分
        normalized = dep.split(".")[0].strip()
        
        # 如果有修改，记录日志
        if normalized != dep:
            logger.info(f"[Deps] Normalized '{dep}' → '{normalized}'")
        
        return normalized
    
    @staticmethod
    def normalize_dependencies(subtasks: List[SubTask]) -> None:
        """
        标准化所有子任务的依赖关系
        
        修正 LLM 生成的错误依赖格式，如：
        - depends_on: ["subtask_1.output.text"] → ["subtask_1"]
        - depends_on: ["subtask_2.result.data"] → ["subtask_2"]
        
        Args:
            subtasks: 子任务列表（原地修改）
        """
        # 收集所有有效的子任务 ID
        valid_ids = {st.id for st in subtasks}
        
        logger.info(f"[Deps] Normalizing dependencies for {len(subtasks)} subtasks")
        logger.debug(f"[Deps] Valid subtask IDs: {valid_ids}")
        
        normalized_count = 0
        invalid_count = 0
        
        for st in subtasks:
            if not st.depends_on:
                continue
            
            cleaned = []
            original_deps = st.depends_on.copy()
            
            for dep in st.depends_on:
                # 标准化依赖 ID
                dep_id = DependencyInferrer._normalize_dep_id(dep)
                
                # 检查是否在有效 ID 中
                if dep_id in valid_ids:
                    cleaned.append(dep_id)
                    if dep != dep_id:
                        normalized_count += 1
                else:
                    # 无效的依赖 ID
                    invalid_count += 1
                    logger.warning(
                        f"[Deps] Invalid dependency '{dep}' on {st.id}, "
                        f"normalized='{dep_id}', valid_ids={valid_ids}"
                    )
            
            # 更新依赖列表
            st.depends_on = cleaned
            
            # 如果有变化，记录日志
            if original_deps != cleaned:
                logger.info(
                    f"[Deps] ✅ Fixed {st.id} dependencies: "
                    f"{original_deps} → {cleaned}"
                )
        
        if normalized_count > 0:
            logger.info(f"[Deps] ✅ Normalized {normalized_count} dependencies")
        if invalid_count > 0:
            logger.warning(f"[Deps] ⚠️ Removed {invalid_count} invalid dependencies")
    
    # 依赖模式：{type_from: {type_to: (confidence, default_input_mapping)}}
    # 这是基于类型的强规则，保留以提供基础判断
    # 注意：只使用 SubTaskType 中实际存在的类型
    DEPENDENCY_PATTERNS = {
        # content_generation 的输出通常被 file_io 使用
        SubTaskType.CONTENT_GENERATION: {
            SubTaskType.FILE_IO: (0.8, {"content": "text"}),
        },
        # information_extraction 的输出被 file_io 使用
        SubTaskType.INFORMATION_EXTRACTION: {
            SubTaskType.FILE_IO: (0.7, {"data": "data"}),
            SubTaskType.CONTENT_GENERATION: (0.6, {"info": "data"}),
        },
        # file_io 的输出可以被后续任务使用
        SubTaskType.FILE_IO: {
            SubTaskType.CONTENT_GENERATION: (0.4, {"file_path": "file_path"}),
        },
    }
    
    def __init__(self, embedding_service: Optional[Any] = None):
        """
        初始化依赖推断器
        
        Args:
            embedding_service: 语义向量服务（可选）
        """
        self._embedding_service = embedding_service
    
    def infer_and_补充(self, composite: CompositeTask) -> CompositeTask:
        """
        推断并补充依赖关系
        
        Args:
            composite: 复合任务
        
        Returns:
            CompositeTask: 补充后的复合任务（原地修改）
        """
        logger.info(
            f"[DependencyInferrer] Starting inference for {len(composite.subtasks)} subtasks"
        )
        
        # 🔥 第一步：标准化所有依赖关系（修正 LLM 错误）
        self.normalize_dependencies(composite.subtasks)
        
        inferred_count = 0
        
        # 遍历每个子任务
        for i, subtask in enumerate(composite.subtasks):
            # 如果已经有 inputs，跳过
            if subtask.inputs:
                logger.debug(f"[DependencyInferrer] {subtask.id} already has inputs, skipping")
                continue
            
            # 推断依赖
            inferred_deps = self._infer_dependencies(subtask, composite.subtasks[:i])
            
            if inferred_deps:
                # 补充 depends_on
                for dep_id, confidence, input_mapping in inferred_deps:
                    if dep_id not in subtask.depends_on:
                        subtask.depends_on.append(dep_id)
                        logger.info(
                            f"[DependencyInferrer] ✅ Added dependency: "
                            f"{subtask.id} depends on {dep_id} (confidence={confidence:.2f})"
                        )
                
                # 补充 inputs（使用最高置信度的依赖）
                if not subtask.inputs:
                    best_dep = inferred_deps[0]  # 按置信度排序
                    dep_id, confidence, input_mapping = best_dep
                    
                    # 构建引用格式：${subtask_id.output.field}
                    subtask.inputs = {}
                    for input_key, output_field in input_mapping.items():
                        subtask.inputs[input_key] = f"${{{dep_id}.output.{output_field}}}"
                    
                    logger.info(
                        f"[DependencyInferrer] ✅ Added inputs for {subtask.id}: "
                        f"{list(subtask.inputs.keys())}"
                    )
                    inferred_count += 1
        
        logger.info(
            f"[DependencyInferrer] Inference complete: inferred {inferred_count} dependencies"
        )
        
        return composite
    
    def _infer_dependencies(
        self,
        subtask: SubTask,
        previous_subtasks: List[SubTask]
    ) -> List[Tuple[str, float, Dict[str, str]]]:
        """
        推断单个子任务的依赖
        
        Args:
            subtask: 当前子任务
            previous_subtasks: 前面的子任务列表
        
        Returns:
            List[Tuple[dep_id, confidence, input_mapping]]: 
            推断的依赖列表，按置信度降序排序
        """
        if not previous_subtasks:
            return []
        
        candidates = []
        
        # 策略 1: 类型模式推断
        for prev in previous_subtasks:
            pattern_confidence = self._check_type_pattern(prev.type, subtask.type)
            if pattern_confidence > 0:
                mapping = self._get_input_mapping(prev.type, subtask.type)
                candidates.append((prev.id, pattern_confidence, mapping))
        
        # 策略 2: 语义相似度推断（替代原关键词推断）
        for prev in previous_subtasks:
            semantic_confidence = self._check_semantic_similarity(prev.goal, subtask.goal)
            if semantic_confidence > 0:
                mapping = self._get_default_mapping(prev.type)
                # 如果类型模式已存在，提升置信度
                existing = next((c for c in candidates if c[0] == prev.id), None)
                if existing:
                    idx = candidates.index(existing)
                    candidates[idx] = (
                        prev.id,
                        min(1.0, existing[1] + semantic_confidence * 0.5),  # 提高语义权重
                        existing[2]
                    )
                else:
                    candidates.append((prev.id, semantic_confidence, mapping))
        
        # 策略 3: 顺序加权（相邻任务更可能有依赖）
        for idx, prev in enumerate(previous_subtasks):
            # 计算顺序加权：越近的任务权重越高
            order_distance = len(previous_subtasks) - idx
            order_bonus = 0.15 / order_distance  # 相邻: 0.15, 隔1个: 0.075, ...
            
            # 如果已有候选，增加顺序加权
            existing = next((c for c in candidates if c[0] == prev.id), None)
            if existing:
                idx_in_list = candidates.index(existing)
                candidates[idx_in_list] = (
                    prev.id,
                    min(1.0, existing[1] + order_bonus),
                    existing[2]
                )
        
        # 按置信度降序排序
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        # 只返回置信度 > 0.4 的依赖
        return [c for c in candidates if c[1] > 0.4]
    
    def _check_type_pattern(
        self,
        from_type: SubTaskType,
        to_type: SubTaskType
    ) -> float:
        """
        检查类型模式匹配
        
        Args:
            from_type: 源任务类型
            to_type: 目标任务类型
        
        Returns:
            float: 置信度 (0.0 - 1.0)
        """
        patterns = self.DEPENDENCY_PATTERNS.get(from_type, {})
        if to_type in patterns:
            return patterns[to_type][0]
        return 0.0
    
    def _check_semantic_similarity(self, from_goal: str, to_goal: str) -> float:
        """
        使用语义相似度判断依赖关系（替代关键词匹配）
        
        Args:
            from_goal: 源任务目标
            to_goal: 目标任务目标
        
        Returns:
            float: 置信度 (0.0 - 1.0)
        """
        try:
            from app.avatar.infra.semantic import similarity
            
            # 计算语义相似度
            score = similarity(from_goal, to_goal)
            
            # 阈值：0.35 以上表示可能有语义关联
            if score > 0.35:
                # 转换为置信度：相似度越高，置信度越高
                # score=0.4 → confidence=0.35
                # score=0.6 → confidence=0.55
                # score=0.8 → confidence=0.75
                confidence = score * 0.9
                
                logger.debug(
                    f"[Semantic] '{from_goal[:30]}...' → '{to_goal[:30]}...': "
                    f"similarity={score:.2f}, confidence={confidence:.2f}"
                )
                
                return confidence
            
            return 0.0
            
        except Exception as e:
            logger.debug(f"[DependencyInferrer] Semantic similarity failed: {e}")
            # 降级：不判断（返回 0）
            return 0.0
    
    
    def _get_input_mapping(
        self,
        from_type: SubTaskType,
        to_type: SubTaskType
    ) -> Dict[str, str]:
        """
        获取类型间的输入映射
        
        Args:
            from_type: 源任务类型
            to_type: 目标任务类型
        
        Returns:
            Dict[str, str]: {input_key: output_field}
        """
        patterns = self.DEPENDENCY_PATTERNS.get(from_type, {})
        if to_type in patterns:
            return patterns[to_type][1]
        
        # 降级：使用默认映射
        return self._get_default_mapping(from_type)
    
    def _get_default_mapping(self, from_type: SubTaskType) -> Dict[str, str]:
        """
        获取默认的输入映射
        
        Args:
            from_type: 源任务类型
        
        Returns:
            Dict[str, str]: {input_key: output_field}
        """
        # 获取标准输出字段
        standard_field = get_standard_output_field(from_type)
        
        # 根据类型推断合适的输入键名
        if from_type == SubTaskType.CONTENT_GENERATION:
            return {"content": standard_field}
        elif from_type == SubTaskType.INFORMATION_EXTRACTION:
            return {"data": standard_field}
        elif from_type == SubTaskType.FILE_IO:
            return {"file_path": standard_field}
        else:
            return {"input": standard_field}

