"""TaskOwnershipManager, OwnershipRecord, OwnershipConflictError.

带版本号的安全任务归属管理。

Requirements: 20.1, 20.2, 20.3, 20.4, 20.5
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


class OwnershipConflictError(Exception):
    """transfer() 时 generation 不匹配抛出."""

    def __init__(self, task_id: str, expected_generation: int, actual_generation: int) -> None:
        self.task_id = task_id
        self.expected_generation = expected_generation
        self.actual_generation = actual_generation
        super().__init__(
            f"Ownership conflict for task '{task_id}': "
            f"expected generation {expected_generation}, actual {actual_generation}"
        )


@dataclass
class OwnershipRecord:
    """任务归属记录."""
    task_id: str = ""
    instance_id: str = ""
    generation: int = 1
    assigned_at: float = field(default_factory=time.time)
    source_handoff_id: Optional[str] = None


class TaskOwnershipManager:
    """任务归属管理器，纯数据层，由 Supervisor 调用."""

    def __init__(self) -> None:
        self._records: Dict[str, OwnershipRecord] = {}

    def assign(
        self,
        task_id: str,
        instance_id: str,
        handoff_id: Optional[str] = None,
    ) -> OwnershipRecord:
        """分配任务，返回新的归属记录."""
        record = OwnershipRecord(
            task_id=task_id,
            instance_id=instance_id,
            generation=1,
            assigned_at=time.time(),
            source_handoff_id=handoff_id,
        )
        self._records[task_id] = record
        return record

    def transfer(
        self,
        task_id: str,
        new_instance_id: str,
        expected_generation: int,
        handoff_id: Optional[str] = None,
    ) -> OwnershipRecord:
        """原子性转移任务.

        当 expected_generation 与当前 generation 不匹配时，
        抛出 OwnershipConflictError。
        """
        record = self._records.get(task_id)
        if record is None:
            # 不存在则视为新分配
            return self.assign(task_id, new_instance_id, handoff_id)

        if record.generation != expected_generation:
            raise OwnershipConflictError(
                task_id=task_id,
                expected_generation=expected_generation,
                actual_generation=record.generation,
            )

        record.instance_id = new_instance_id
        record.generation += 1
        record.assigned_at = time.time()
        record.source_handoff_id = handoff_id
        return record

    def get_owner(self, task_id: str) -> Optional[OwnershipRecord]:
        """查询任务当前归属."""
        return self._records.get(task_id)

    def get_owned_tasks(self, instance_id: str) -> List[OwnershipRecord]:
        """查询实例拥有的所有任务."""
        return [r for r in self._records.values() if r.instance_id == instance_id]

    def reclaim(self, instance_id: str) -> List[str]:
        """回收被销毁实例的所有任务，返回回收的 task_id 列表."""
        reclaimed: List[str] = []
        for task_id, record in list(self._records.items()):
            if record.instance_id == instance_id:
                record.instance_id = ""
                record.generation += 1
                reclaimed.append(task_id)
        return reclaimed
