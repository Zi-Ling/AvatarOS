"""
Plan Normalizer

Normalizes parsed plan steps:
- Generates unique step IDs
- Resolves dependencies
- Fixes parameter references
- Resolves skill name aliases
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List

from app.avatar.skills.registry import skill_registry


class PlanNormalizer:
    """
    计划规范化器
    
    处理 LLM 返回的原始计划，进行：
    1. ID 唯一化（添加 UUID 后缀）
    2. 依赖关系映射
    3. 参数引用修复
    4. 技能名称解析（别名 → API名称）
    """
    
    @staticmethod
    def normalize(raw_steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        规范化步骤列表
        
        Args:
            raw_steps: LLM 返回的原始步骤列表
            
        Returns:
            规范化后的步骤列表
        """
        if not raw_steps:
            return []
        
        # 1. 生成 ID 映射表
        id_map = PlanNormalizer._generate_id_map(raw_steps)
        
        # 2. 规范化每个步骤
        normalized_steps = []
        
        for i, step in enumerate(raw_steps):
            normalized_step = PlanNormalizer._normalize_step(step, id_map, i)
            
            if normalized_step:  # 跳过无效步骤
                normalized_steps.append(normalized_step)
        
        return normalized_steps
    
    @staticmethod
    def _generate_id_map(steps: List[Dict[str, Any]]) -> Dict[str, str]:
        """
        生成 ID 映射表: old_id -> new_unique_id
        
        Args:
            steps: 原始步骤列表
            
        Returns:
            ID 映射字典
        """
        id_map = {}
        
        for i, step in enumerate(steps):
            old_id = step.get("id") or f"step_{i}"
            
            # 添加 UUID 后缀确保全局唯一性
            # 例如: "save_to_word" -> "save_to_word_a1b2c3d4"
            new_id = f"{old_id}_{uuid.uuid4().hex[:8]}"
            
            id_map[old_id] = new_id
        
        return id_map
    
    @staticmethod
    def _normalize_step(
        step: Dict[str, Any],
        id_map: Dict[str, str],
        index: int
    ) -> Optional[Dict[str, Any]]:
        """
        规范化单个步骤
        
        Args:
            step: 原始步骤
            id_map: ID 映射表
            index: 步骤索引
            
        Returns:
            规范化后的步骤或 None（如果步骤无效）
        """
        # 1. 解析技能名称
        skill_name = step.get("skill") or step.get("skill_name")
        
        if not skill_name:
            logger.debug(f"PlanNormalizer: Skipping invalid step {index}: missing skill name. "
                  f"Raw step: {step}")
            return None
        
        # 2. 解析技能别名
        resolved_skill = skill_registry.get(skill_name)
        if resolved_skill:
            skill_name = resolved_skill.spec.api_name
        
        # 3. 获取新 ID
        old_id = step.get("id") or f"step_{index}"
        new_id = id_map.get(old_id, old_id)
        
        # 4. 修复依赖关系
        new_depends_on = PlanNormalizer._fix_dependencies(
            step.get("depends_on", []),
            id_map
        )
        
        # 5. 修复参数引用
        new_params = PlanNormalizer._fix_param_references(
            step.get("params", {}),
            id_map
        )
        
        # 6. 构建规范化的步骤
        normalized = {
            "id": new_id,
            "skill": skill_name,
            "params": new_params,
            "max_retry": step.get("max_retry", 0),
            "depends_on": new_depends_on,
            "description": step.get("description", "")
        }
        
        return normalized
    
    @staticmethod
    def _fix_dependencies(
        depends_on: Any,
        id_map: Dict[str, str]
    ) -> List[str]:
        """
        修复依赖关系
        
        Args:
            depends_on: 原始依赖（可能是字符串或列表）
            id_map: ID 映射表
            
        Returns:
            规范化的依赖列表
        """
        # 处理单个字符串的情况
        if isinstance(depends_on, str):
            depends_on = [depends_on]
        
        if not isinstance(depends_on, list):
            return []
        
        # 映射到新 ID
        return [id_map.get(dep_id, dep_id) for dep_id in depends_on]
    
    @staticmethod
    def _fix_param_references(
        params: Dict[str, Any],
        id_map: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        修复参数引用
        
        替换参数值中的 ID 引用（如 {{ old_id.output }}）
        
        Args:
            params: 原始参数字典
            id_map: ID 映射表
            
        Returns:
            修复后的参数字典
        """
        new_params = params.copy()
        
        for key, value in new_params.items():
            if isinstance(value, str) and "{{" in value:
                # 替换所有 ID 引用
                for old_id, new_id in id_map.items():
                    # 处理两种格式: {{ old_id. 和 {{old_id.
                    value = value.replace(f"{{{{ {old_id}.", f"{{{{ {new_id}.")
                    value = value.replace(f"{{{{{old_id}.", f"{{{{{new_id}.")
                
                new_params[key] = value
        
        return new_params
    
    @staticmethod
    def apply_to_cached_steps(
        cached_steps: List[Dict[str, Any]],
        new_params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        将新参数应用到缓存的步骤中
        
        用于计划缓存场景：重用缓存的步骤结构，但替换参数
        
        Args:
            cached_steps: 缓存的步骤列表
            new_params: 新的参数（来自 intent）
            
        Returns:
            应用参数后的步骤列表
        """
        # 1. 生成新的 ID 映射（确保每次使用缓存时 ID 都唯一）
        id_map = {}
        
        for step in cached_steps:
            old_id = step["id"]
            # 移除旧的 UUID 后缀（如果存在）
            base_id = old_id.rsplit("_", 1)[0] if "_" in old_id else old_id
            new_id = f"{base_id}_{uuid.uuid4().hex[:8]}"
            id_map[old_id] = new_id
        
        # 2. 应用映射和参数
        result = []
        
        for step in cached_steps:
            new_step = step.copy()
            
            # 更新 ID
            new_step["id"] = id_map[step["id"]]
            
            # 更新依赖
            if "depends_on" in new_step:
                new_step["depends_on"] = [
                    id_map.get(dep, dep) for dep in new_step["depends_on"]
                ]
            
            # 更新参数引用 + 合并新参数
            step_params = new_step.get("params", {}).copy()
            
            # 修复内部引用
            for k, v in step_params.items():
                if isinstance(v, str) and "{{" in v:
                    for old_id, new_id in id_map.items():
                        if f"{{{{ {old_id}." in v:
                            step_params[k] = v.replace(f"{{{{ {old_id}.", f"{{{{ {new_id}.")
                        elif f"{{{{{old_id}." in v:
                            step_params[k] = v.replace(f"{{{{{old_id}.", f"{{{{{new_id}.")
            
            # 合并新参数（覆盖）
            if new_params:
                step_params.update(new_params)
            
            new_step["params"] = step_params
            result.append(new_step)
        
        return result


from typing import Optional

