"""
Plan Optimizer - 计划优化器

在 Planner 输出后、Runner 执行前对计划进行优化。
主要优化：合并连续的相同技能调用为批量操作。
"""
from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional, Set
from dataclasses import replace

from app.avatar.planner.models import Task, Step, StepStatus

logger = logging.getLogger(__name__)


class PlanOptimizer:
    """
    计划优化器
    
    优化策略：
    1. 合并连续的相同技能调用（如 excel.write → excel.append × N）
    2. 消除冗余步骤
    3. 重排序以减少依赖等待
    """
    
    # 技能批量操作映射：单操作技能 → 批量操作技能
    BATCH_SKILL_MAP = {
        "excel.write": "excel.write_table",
        "excel.append": "excel.write_table",
        "file.write": "file.write",  # 可扩展：支持批量写
        # 可继续添加其他技能的批量映射
    }
    
    # 批量操作的参数合并规则
    MERGE_RULES = {
        "excel.write_table": {
            "target_param": "rows",  # 合并到哪个参数
            "extract_from": ["value", "row", "values", "data"],  # 从单操作中提取
            "keep_first": ["relative_path", "abs_path", "sheet_name", "start_cell"],  # 保留第一个的值
        },
        # 可扩展其他批量技能的规则
    }
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
    
    def optimize(self, task: Task) -> Task:
        """
        优化任务计划
        
        Args:
            task: 原始任务
            
        Returns:
            Task: 优化后的任务
        """
        if not self.enabled or not task.steps:
            return task
        
        logger.info(f"Optimizing task {task.id} with {len(task.steps)} steps")
        
        # 执行优化
        optimized_steps = self._merge_consecutive_operations(task.steps)
        
        if len(optimized_steps) < len(task.steps):
            logger.info(f"Optimized: {len(task.steps)} → {len(optimized_steps)} steps")
            return replace(task, steps=optimized_steps)
        
        return task
    
    def _merge_consecutive_operations(self, steps: List[Step]) -> List[Step]:
        """
        合并连续的相同技能操作
        
        策略：
        1. 扫描连续的相同技能步骤
        2. 检查是否可合并（同文件、无外部依赖）
        3. 合并为批量操作
        """
        if len(steps) <= 1:
            return steps
        
        optimized = []
        i = 0
        
        while i < len(steps):
            step = steps[i]
            
            # 检查是否可以开始合并
            batch_skill = self._get_batch_skill(self._get_skill_name(step))
            if not batch_skill:
                optimized.append(step)
                i += 1
                continue
            
            # 查找连续的可合并步骤
            merge_group = [step]
            j = i + 1
            
            while j < len(steps):
                next_step = steps[j]
                
                # 检查是否可合并
                if not self._can_merge(step, next_step, merge_group):
                    break
                
                merge_group.append(next_step)
                j += 1
            
            # 如果找到了多个可合并的步骤
            if len(merge_group) > 1:
                merged_step = self._merge_steps(merge_group, batch_skill)
                if merged_step:
                    optimized.append(merged_step)
                    i = j
                    continue
            
            # 无法合并，保持原样
            optimized.append(step)
            i += 1
        
        return optimized
    
    def _get_batch_skill(self, skill_name: str) -> Optional[str]:
        """
        获取技能对应的批量操作技能
        
        Args:
            skill_name: 原始技能名
            
        Returns:
            批量技能名，如果不支持则返回 None
        """
        return self.BATCH_SKILL_MAP.get(skill_name)
    
    def _get_skill_name(self, step: Step) -> str:
        """获取步骤的技能名称（兼容不同字段名）"""
        return getattr(step, 'skill_name', getattr(step, 'skill', ''))
    
    def _can_merge(self, first_step: Step, next_step: Step, merge_group: List[Step]) -> bool:
        """
        检查两个步骤是否可以合并
        
        条件：
        1. 技能相同或映射到相同的批量技能
        2. 操作同一文件（路径相同）
        3. 无外部依赖（仅依赖组内步骤）
        """
        # 1. 技能检查
        batch_skill_1 = self._get_batch_skill(self._get_skill_name(first_step))
        batch_skill_2 = self._get_batch_skill(self._get_skill_name(next_step))
        
        if batch_skill_1 != batch_skill_2:
            return False
        
        # 2. 文件路径检查
        path_1 = self._get_target_path(first_step.params)
        path_2 = self._get_target_path(next_step.params)
        
        if path_1 != path_2 or not path_1:
            return False
        
        # 3. 依赖检查
        group_ids = {s.id for s in merge_group}
        
        for dep in next_step.depends_on:
            # 如果依赖组外步骤，不能合并
            if dep not in group_ids:
                return False
        
        return True
    
    def _get_target_path(self, params: Dict[str, Any]) -> Optional[str]:
        """
        提取目标文件路径
        
        Args:
            params: 步骤参数
            
        Returns:
            文件路径，优先返回 abs_path，否则返回 relative_path
        """
        return params.get("abs_path") or params.get("relative_path")
    
    def _merge_steps(self, steps: List[Step], batch_skill: str) -> Optional[Step]:
        """
        合并多个步骤为一个批量操作步骤
        
        Args:
            steps: 要合并的步骤列表
            batch_skill: 批量技能名
            
        Returns:
            合并后的步骤，失败返回 None
        """
        if not steps or batch_skill not in self.MERGE_RULES:
            return None
        
        rule = self.MERGE_RULES[batch_skill]
        first_step = steps[0]
        
        # 构建合并后的参数
        merged_params = {}
        
        # 1. 保留第一个步骤的公共参数
        for key in rule["keep_first"]:
            if key in first_step.params:
                merged_params[key] = first_step.params[key]
        
        # 2. 合并数据
        target_param = rule["target_param"]
        extract_keys = rule["extract_from"]
        
        merged_data = []
        for step in steps:
            # 从各种可能的参数中提取数据
            for key in extract_keys:
                if key in step.params:
                    data = step.params[key]
                    
                    # 规范化为列表
                    if isinstance(data, list):
                        # 检查是否已经是二维数组
                        if data and isinstance(data[0], list):
                            merged_data.extend(data)
                        else:
                            merged_data.append(data)
                    else:
                        merged_data.append([data])
                    break
        
        if not merged_data:
            logger.warning(f"No data extracted from {len(steps)} steps")
            return None
        
        merged_params[target_param] = merged_data
        
        # 3. 构建合并后的步骤
        merged_step = Step(
            id=f"merged_{first_step.id}",
            order=first_step.order,
            skill_name=batch_skill,
            params=merged_params,
            depends_on=[],  # 合并后的步骤没有内部依赖
            status=StepStatus.PENDING
        )
        
        logger.info(
            f"Merged {len(steps)} steps ({self._get_skill_name(first_step)}) into {batch_skill}: "
            f"{len(merged_data)} rows"
        )
        
        return merged_step


# 全局单例
_default_optimizer: Optional[PlanOptimizer] = None


def get_plan_optimizer(enabled: bool = True) -> PlanOptimizer:
    """
    获取全局计划优化器实例
    
    Args:
        enabled: 是否启用优化
        
    Returns:
        PlanOptimizer 实例
    """
    global _default_optimizer
    if _default_optimizer is None:
        _default_optimizer = PlanOptimizer(enabled=enabled)
    return _default_optimizer


def optimize_task(task: Task, enabled: bool = True) -> Task:
    """
    优化任务计划（便捷函数）
    
    Args:
        task: 原始任务
        enabled: 是否启用优化
        
    Returns:
        优化后的任务
    """
    optimizer = get_plan_optimizer(enabled=enabled)
    return optimizer.optimize(task)
