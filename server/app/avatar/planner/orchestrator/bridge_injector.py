"""
BridgeInjector - 自动修正子任务间的类型不匹配

核心职责：
- 检测"下游需要文本，但上游只提供路径"的场景
- 自动插入 file.read 桥接子任务
- 修正依赖关系和输入引用

设计原则：
- 纯结构规则引擎，不依赖 LLM
- 不修改子任务的 goal 和 type
- 幂等性：重复调用不会插入重复桥接
"""
from __future__ import annotations

import logging
import re
from typing import List, Dict
from uuid import uuid4

from ..models.subtask import SubTask, CompositeTask
from ..models.types import SubTaskType
from .io_schema import (
    get_expected_input_role,
    is_text_role,
    get_standard_text_output_field,
)

logger = logging.getLogger(__name__)


class BridgeInjector:
    """
    桥接注入器（Bridge Injector）
    
    自动检测并修正子任务之间的类型不匹配问题。
    
    典型场景：
    - content_generation 子任务需要 text，但只拿到了 file_path
    - 自动插入 file.read 子任务，将 file_path 转换为 text
    """
    
    @classmethod
    def apply(cls, composite: CompositeTask) -> CompositeTask:
        """
        应用桥接修正
        
        Args:
            composite: 待修正的复合任务
        
        Returns:
            CompositeTask: 修正后的复合任务（可能新增了桥接子任务）
        """
        if not composite or not composite.subtasks:
            return composite
        
        # 1. 建立索引
        id_to_task: Dict[str, SubTask] = {
            t.id: t for t in composite.subtasks
        }
        
        # 2. 记录修正计数
        bridge_count = 0
        
        # 3. 遍历每个子任务，检查其输入是否与类型期望矛盾
        # 注意：需要使用副本遍历，因为会在遍历过程中添加新任务
        original_subtasks = list(composite.subtasks)
        
        for task in original_subtasks:
            inserted = cls._fix_inputs_for_task(
                task=task,
                id_to_task=id_to_task,
                composite=composite
            )
            bridge_count += inserted
        
        if bridge_count > 0:
            logger.info(f"[BridgeInjector] Inserted {bridge_count} bridge subtask(s)")
        
        return composite
    
    @classmethod
    def _fix_inputs_for_task(
        cls,
        task: SubTask,
        id_to_task: Dict[str, SubTask],
        composite: CompositeTask
    ) -> int:
        """
        修正单个任务的输入类型不匹配
        
        Args:
            task: 当前任务
            id_to_task: 任务索引（会被更新）
            composite: 复合任务（会被修改）
        
        Returns:
            int: 插入的桥接任务数量
        """
        # 只处理有明确类型限制的任务类型
        if task.type not in {
            SubTaskType.CONTENT_GENERATION,
            SubTaskType.INFORMATION_EXTRACTION
        }:
            return 0
        
        if not task.inputs:
            return 0
        
        inserted_count = 0
        
        # 遍历所有输入字段
        for input_key, input_val in list(task.inputs.items()):
            # 只处理引用形式的输入
            if not isinstance(input_val, str) or "${" not in input_val:
                continue
            
            # 检查期望角色
            expected_role = get_expected_input_role(task.type, input_key)
            
            # 如果期望是 TEXT，但引用的是 file_path → 需要桥接
            if is_text_role(expected_role) and ".file_path" in input_val:
                logger.debug(
                    f"[BridgeInjector] {task.id}: Detected TEXT input '{input_key}' "
                    f"consuming FILE_PATH from upstream"
                )
                
                inserted = cls._insert_file_read_bridge(
                    downstream_task=task,
                    input_key=input_key,
                    input_val=input_val,
                    id_to_task=id_to_task,
                    composite=composite
                )
                
                if inserted:
                    inserted_count += 1
        
        return inserted_count
    
    @classmethod
    def _insert_file_read_bridge(
        cls,
        downstream_task: SubTask,
        input_key: str,
        input_val: str,
        id_to_task: Dict[str, SubTask],
        composite: CompositeTask
    ) -> bool:
        """
        插入 file.read 桥接任务
        
        流程：
        1. 解析上游任务 ID（从引用字符串中提取）
        2. 创建桥接任务（file.read）
        3. 修改下游任务的输入引用（指向桥接任务的输出）
        4. 增加依赖关系
        5. 注册到复合任务和索引
        
        Args:
            downstream_task: 下游任务（需要文本）
            input_key: 输入字段名
            input_val: 输入值（包含引用）
            id_to_task: 任务索引
            composite: 复合任务
        
        Returns:
            bool: 是否成功插入
        """
        # 1. 解析上游任务 ID
        # 示例输入: "${subtask_2.output.file_path}"
        # 需要提取: "subtask_2"
        try:
            # 使用正则提取引用中的任务 ID
            match = re.search(r'\$\{([^.]+)\.output\.[^}]+\}', input_val)
            if not match:
                logger.warning(
                    f"[BridgeInjector] Cannot parse upstream ID from: {input_val}"
                )
                return False
            
            upstream_id = match.group(1)
            
            if upstream_id not in id_to_task:
                logger.warning(
                    f"[BridgeInjector] Upstream task '{upstream_id}' not found"
                )
                return False
        
        except Exception as e:
            logger.error(f"[BridgeInjector] Error parsing reference: {e}")
            return False
        
        # 2. 检查是否已经存在桥接任务（幂等性）
        bridge_id = f"{downstream_task.id}_bridge_read_{upstream_id}"
        if bridge_id in id_to_task:
            logger.debug(f"[BridgeInjector] Bridge task '{bridge_id}' already exists")
            # 确保下游任务的输入已经指向桥接任务
            downstream_task.inputs[input_key] = f"${{{bridge_id}.output.content}}"
            return False
        
        # 3. 创建桥接任务
        bridge_task = SubTask(
            id=bridge_id,
            goal=f"Read file for {downstream_task.id}",
            order=downstream_task.order - 0.5,  # 插在下游任务之前
            type=SubTaskType.FILE_IO,
            depends_on=[upstream_id],
            inputs={
                "file_path": input_val  # 沿用原来的引用
            },
            expected_outputs=[
                get_standard_text_output_field(),
                "text"
            ],
            metadata={
                "bridge": True,
                "bridge_type": "file_read",
                "for_subtask": downstream_task.id
            }
        )
        
        # 4. 修改下游任务的输入引用
        # 从引用上游的 file_path 改为引用桥接任务的 content
        downstream_task.inputs[input_key] = f"${{{bridge_id}.output.content}}"
        
        # 5. 增加依赖关系
        if bridge_id not in downstream_task.depends_on:
            downstream_task.depends_on.append(bridge_id)
        
        # 6. 注册到复合任务和索引
        composite.add_subtask(bridge_task)
        id_to_task[bridge_id] = bridge_task
        
        logger.info(
            f"[BridgeInjector] ✅ Inserted bridge task: {bridge_id} "
            f"(reads from {upstream_id} for {downstream_task.id})"
        )
        
        return True

