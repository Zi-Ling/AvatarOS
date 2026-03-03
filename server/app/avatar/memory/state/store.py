# avatar/memory/state/store.py
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..base import MemoryKind, MemoryRecord, MemoryStore


class InMemoryWorkingStateStore(MemoryStore):
    """
    Working State（工作记忆）的内存版实现：
    - 用于保存当前会话、当前任务的临时状态
    - 进程退出后数据消失
    """

    def __init__(self) -> None:
        # key: f"{kind.value}::{key}" -> MemoryRecord
        self._store: Dict[str, MemoryRecord] = {}

    @staticmethod
    def _ck(kind: MemoryKind, key: str) -> str:
        return f"{kind.value}::{key}"

    def save(self, record: MemoryRecord) -> None:
        ck = self._ck(record.kind, record.key)
        self._store[ck] = record

    def get(self, kind: MemoryKind, key: str) -> Optional[MemoryRecord]:
        ck = self._ck(kind, key)
        return self._store.get(ck)

    def query(
        self,
        kind: MemoryKind,
        prefix: Optional[str] = None,
        limit: int = 50,
    ) -> List[MemoryRecord]:
        results: List[MemoryRecord] = []
        for ck, rec in self._store.items():
            if rec.kind != kind:
                continue
            if prefix and not rec.key.startswith(prefix):
                continue
            results.append(rec)
            if len(results) >= limit:
                break
        return results


class JsonFileWorkingStateStore(MemoryStore):
    """
    Working State（工作记忆）的 JSON 文件实现：
    - 适合做一个非常轻量的“短期持久化”
    - 会把所有记录放到一个 JSON 文件里
    - 不适合超大量数据，但做 MVP 足够
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, MemoryRecord] = {}
        self._load()

    @staticmethod
    def _ck(kind: MemoryKind, key: str) -> str:
        return f"{kind.value}::{key}"

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as f:
            items = json.load(f)
        for item in items:
            rec = MemoryRecord(
                kind=MemoryKind(item["kind"]),
                key=item["key"],
                data=item["data"],
                created_at=datetime.fromisoformat(item["created_at"]),
            )
            self._cache[self._ck(rec.kind, rec.key)] = rec

    def _flush(self) -> None:
        items = []
        for rec in self._cache.values():
            items.append(
                {
                    "kind": rec.kind.value,
                    "key": rec.key,
                    "data": rec.data,
                    "created_at": rec.created_at.isoformat(),
                }
            )
        with self._path.open("w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)

    def save(self, record: MemoryRecord) -> None:
        ck = self._ck(record.kind, record.key)
        self._cache[ck] = record
        self._flush()

    def get(self, kind: MemoryKind, key: str) -> Optional[MemoryRecord]:
        ck = self._ck(kind, key)
        return self._cache.get(ck)

    def query(
        self,
        kind: MemoryKind,
        prefix: Optional[str] = None,
        limit: int = 50,
    ) -> List[MemoryRecord]:
        results: List[MemoryRecord] = []
        for rec in self._cache.values():
            if rec.kind != kind:
                continue
            if prefix and not rec.key.startswith(prefix):
                continue
            results.append(rec)
            if len(results) >= limit:
                break
        return results


# 一些便捷函数（可选）
def set_working_state(
    store: MemoryStore, key: str, data: Dict[str, Any]
) -> None:
    """
    写入一条 Working State：
    - key 例子: "conv:123:working" / "task:abc:context"
    """
    rec = MemoryRecord(
        kind=MemoryKind.WORKING_STATE,
        key=key,
        data=data,
        created_at=datetime.utcnow(),
    )
    store.save(rec)


def get_working_state(
    store: MemoryStore, key: str
) -> Optional[Dict[str, Any]]:
    rec = store.get(MemoryKind.WORKING_STATE, key)
    return rec.data if rec else None
