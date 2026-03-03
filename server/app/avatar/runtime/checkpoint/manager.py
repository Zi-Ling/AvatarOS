"""
Checkpoint 管理器
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import TaskCheckpoint

logger = logging.getLogger(__name__)


class CheckpointManager:
    """
    Checkpoint 管理器
    
    职责：
    - 保存任务检查点
    - 恢复任务状态
    - 清理过期检查点
    """
    
    def __init__(self, storage_dir: Optional[Path] = None):
        """
        Args:
            storage_dir: 存储目录（默认 .checkpoints/）
        """
        self._storage_dir = storage_dir or Path(".checkpoints")
        self._storage_dir.mkdir(parents=True, exist_ok=True)
    
    def save_checkpoint(
        self,
        composite_task: Any,
        current_subtask_index: int,
        completed_subtask_ids: List[str],
        outputs_cache: Dict[str, Any]
    ) -> str:
        """
        保存检查点
        
        Args:
            composite_task: 复合任务对象
            current_subtask_index: 当前子任务索引
            completed_subtask_ids: 已完成ID列表
            outputs_cache: 输出缓存
        
        Returns:
            str: Checkpoint ID
        """
        checkpoint_id = str(uuid.uuid4())
        
        checkpoint = TaskCheckpoint(
            checkpoint_id=checkpoint_id,
            task_id=composite_task.id,
            composite_task_data=composite_task.to_dict(),
            current_subtask_index=current_subtask_index,
            completed_subtask_ids=completed_subtask_ids,
            outputs_cache=outputs_cache,
            plan_version=getattr(composite_task, 'plan_version', 1),
            timestamp=datetime.now(),
            metadata=composite_task.metadata
        )
        
        # 保存到文件
        checkpoint_file = self._storage_dir / f"{composite_task.id}.json"
        with open(checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(self._serialize_checkpoint(checkpoint), f, indent=2)
        
        logger.info(f"Saved checkpoint: {checkpoint_id} for task {composite_task.id}")
        return checkpoint_id
    
    def restore_checkpoint(self, task_id: str) -> Optional[TaskCheckpoint]:
        """
        恢复检查点
        
        Args:
            task_id: 任务ID
        
        Returns:
            Optional[TaskCheckpoint]: 检查点对象，不存在返回 None
        """
        checkpoint_file = self._storage_dir / f"{task_id}.json"
        
        if not checkpoint_file.exists():
            logger.warning(f"No checkpoint found for task: {task_id}")
            return None
        
        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            checkpoint = self._deserialize_checkpoint(data)
            logger.info(f"Restored checkpoint for task: {task_id}")
            return checkpoint
        
        except Exception as e:
            logger.error(f"Failed to restore checkpoint: {e}")
            return None
    
    def cleanup_checkpoint(self, task_id: str):
        """
        清理检查点
        
        Args:
            task_id: 任务ID
        """
        checkpoint_file = self._storage_dir / f"{task_id}.json"
        
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            logger.info(f"Cleaned up checkpoint for task: {task_id}")
    
    def _serialize_checkpoint(self, checkpoint: TaskCheckpoint) -> Dict:
        """序列化 Checkpoint"""
        return {
            "checkpoint_id": checkpoint.checkpoint_id,
            "task_id": checkpoint.task_id,
            "composite_task_data": checkpoint.composite_task_data,
            "current_subtask_index": checkpoint.current_subtask_index,
            "completed_subtask_ids": checkpoint.completed_subtask_ids,
            "outputs_cache": checkpoint.outputs_cache,
            "plan_version": checkpoint.plan_version,
            "timestamp": checkpoint.timestamp.isoformat(),
            "metadata": checkpoint.metadata
        }
    
    def _deserialize_checkpoint(self, data: Dict) -> TaskCheckpoint:
        """反序列化 Checkpoint"""
        return TaskCheckpoint(
            checkpoint_id=data["checkpoint_id"],
            task_id=data["task_id"],
            composite_task_data=data["composite_task_data"],
            current_subtask_index=data["current_subtask_index"],
            completed_subtask_ids=data["completed_subtask_ids"],
            outputs_cache=data["outputs_cache"],
            plan_version=data.get("plan_version", 1),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            metadata=data.get("metadata", {})
        )

