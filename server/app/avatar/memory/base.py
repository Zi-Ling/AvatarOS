# avatar/memory/base.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol


class MemoryKind(str, Enum):
    """
    三大类记忆类型：
    - WORKING_STATE : Working State，短期工作记忆
    - EPISODIC      : Episodic Memory，情节/事件记忆
    - KNOWLEDGE     : Knowledge Memory，长期知识记忆
    """
    WORKING_STATE = "working_state"
    EPISODIC = "episodic"
    KNOWLEDGE = "knowledge"


@dataclass
class MemoryRecord:
    """
    通用记忆记录：
    - kind: 属于哪一类记忆（state / episodic / knowledge）
    - key : 逻辑 key，例如 "task:123:context" / "user:abc:prefs"
    - data: 任意结构化内容（建议是 dict）
    - created_at: 创建时间（UTC）
    """
    kind: MemoryKind
    key: str
    data: Dict[str, Any]
    created_at: datetime


class MemoryStore(Protocol):
    """
    通用记忆存储接口：
    你可以实现多个不同的具体存储（内存 / JSON 文件 / DB 等）。
    """

    def save(self, record: MemoryRecord) -> None:
        """保存一条记忆记录（如果 key 相同，可以视为覆盖或追加，具体由实现决定）"""
        ...

    def get(self, kind: MemoryKind, key: str) -> Optional[MemoryRecord]:
        """按 kind + key 精确获取一条记忆记录"""
        ...

    def query(
        self,
        kind: MemoryKind,
        prefix: Optional[str] = None,
        limit: int = 50,
    ) -> List[MemoryRecord]:
        """
        按 kind + key 前缀查询多条记录：
        - prefix: 如果指定，则只返回 key 以该前缀开头的记录
        - limit : 返回条数上限
        """
        ...
