"""
DAG 构建器 - 为并行执行构建依赖图
"""
from __future__ import annotations

import logging
from typing import Dict, List, Set
from ...models.subtask import SubTask

logger = logging.getLogger(__name__)


class DAGBuilder:
    """
    DAG（有向无环图）构建器
    
    职责：
    - 分析子任务依赖关系
    - 构建 DAG
    - 识别并行层（可同时执行的任务）
    """
    
    @staticmethod
    def build_layers(subtasks: List[SubTask]) -> List[List[SubTask]]:
        """
        构建并行层
        
        将子任务按依赖关系分层：
        - Layer 0: 无依赖的任务
        - Layer 1: 只依赖 Layer 0 的任务
        - Layer 2: 只依赖 Layer 0-1 的任务
        - ...
        
        Args:
            subtasks: 子任务列表
        
        Returns:
            List[List[SubTask]]: 分层的子任务列表
        """
        layers: List[List[SubTask]] = []
        remaining = subtasks.copy()
        completed_ids: Set[str] = set()
        
        while remaining:
            # 找到当前可执行的任务（依赖都已完成）
            current_layer = []
            
            for st in remaining:
                if all(dep_id in completed_ids for dep_id in st.depends_on):
                    current_layer.append(st)
            
            if not current_layer:
                # 可能存在循环依赖
                logger.error("Cannot build layers: possible circular dependency")
                break
            
            # 添加到layers
            layers.append(current_layer)
            
            # 更新状态
            for st in current_layer:
                completed_ids.add(st.id)
                remaining.remove(st)
        
        logger.info(f"Built {len(layers)} parallel layers")
        for i, layer in enumerate(layers):
            logger.debug(f"  Layer {i}: {len(layer)} tasks")
        
        return layers
    
    @staticmethod
    def get_parallel_groups(subtasks: List[SubTask]) -> List[List[SubTask]]:
        """
        获取可并行执行的任务组
        
        这是 build_layers 的别名，语义更清晰
        """
        return DAGBuilder.build_layers(subtasks)

