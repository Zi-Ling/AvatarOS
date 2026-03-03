"""
依赖关系验证器
"""
from __future__ import annotations

import logging
from typing import List, Set

from ...models.subtask import SubTask

logger = logging.getLogger(__name__)


class DependencyValidator:
    """
    依赖关系验证器
    
    职责：
    - 检查依赖关系是否有效
    - 检测循环依赖
    - 验证依赖的子任务是否存在
    """
    
    @staticmethod
    def validate(subtasks: List[SubTask]) -> bool:
        """
        验证依赖关系
        
        Args:
            subtasks: 子任务列表
        
        Returns:
            bool: True 表示依赖关系有效
        """
        subtask_ids = {st.id for st in subtasks}
        
        # 检查1：依赖的子任务是否存在
        for st in subtasks:
            for dep_id in st.depends_on:
                if dep_id not in subtask_ids:
                    logger.error(
                        f"Invalid dependency: subtask '{st.id}' depends on non-existent '{dep_id}'"
                    )
                    return False
        
        # 检查2：是否有循环依赖
        if DependencyValidator._has_cycle(subtasks):
            logger.error("Circular dependency detected in subtasks")
            return False
        
        logger.info("Dependency validation passed")
        return True
    
    @staticmethod
    def _has_cycle(subtasks: List[SubTask]) -> bool:
        """
        检测循环依赖（使用 DFS）
        
        Args:
            subtasks: 子任务列表
        
        Returns:
            bool: True 表示存在循环依赖
        """
        # 构建依赖图
        dep_graph = {st.id: st.depends_on for st in subtasks}
        
        # DFS 检测环
        WHITE = 0  # 未访问
        GRAY = 1   # 访问中
        BLACK = 2  # 已完成
        
        color = {st.id: WHITE for st in subtasks}
        
        def visit(node_id: str) -> bool:
            """DFS 访问节点，返回 True 表示发现环"""
            if color[node_id] == GRAY:
                return True  # 发现环
            
            if color[node_id] == BLACK:
                return False  # 已经处理过
            
            color[node_id] = GRAY
            
            for dep_id in dep_graph.get(node_id, []):
                if dep_id in color and visit(dep_id):
                    return True
            
            color[node_id] = BLACK
            return False
        
        # 检查所有节点
        for st_id in color:
            if color[st_id] == WHITE:
                if visit(st_id):
                    return True
        
        return False

