# avatar/memory/knowledge/store.py
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..base import MemoryKind, MemoryRecord, MemoryStore


class JsonFileKnowledgeMemoryStore(MemoryStore):
    """
    Knowledge Memory（长期知识记忆）的 JSON 文件实现：
    - 本质上是一个持久化的 key-value store
    - 覆盖式：同一个 key 再次 save 会覆盖之前的记录
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
        if record.kind != MemoryKind.KNOWLEDGE:
            raise ValueError(
                f"JsonFileKnowledgeMemoryStore 只能保存 kind=KNOWLEDGE 的记录，当前={record.kind}"
            )
        ck = self._ck(record.kind, record.key)
        self._cache[ck] = record
        self._flush()

    def get(self, kind: MemoryKind, key: str) -> Optional[MemoryRecord]:
        if kind != MemoryKind.KNOWLEDGE:
            return None
        ck = self._ck(kind, key)
        return self._cache.get(ck)

    def query(
        self,
        kind: MemoryKind,
        prefix: Optional[str] = None,
        limit: int = 50,
    ) -> List[MemoryRecord]:
        if kind != MemoryKind.KNOWLEDGE:
            return []
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


# 便捷函数：用户偏好 & 任务模板

def set_user_preference(
    store: MemoryStore, user_id: str, prefs: Dict[str, Any]
) -> None:
    """
    保存某个用户的偏好（文件目录、语言习惯、默认输出格式等）
    key 示例: "user:123:prefs"
    """
    rec = MemoryRecord(
        kind=MemoryKind.KNOWLEDGE,
        key=f"user:{user_id}:prefs",
        data=prefs,
        created_at=datetime.utcnow(),
    )
    store.save(rec)


def get_user_preference(
    store: MemoryStore, user_id: str
) -> Optional[Dict[str, Any]]:
    rec = store.get(MemoryKind.KNOWLEDGE, f"user:{user_id}:prefs")
    return rec.data if rec else None


def set_task_template(
    store: MemoryStore, template_name: str, template: Dict[str, Any]
) -> None:
    """
    保存一个任务模板，比如“日报任务”的默认结构
    key 示例: "task_template:daily_report"
    """
    rec = MemoryRecord(
        kind=MemoryKind.KNOWLEDGE,
        key=f"task_template:{template_name}",
        data=template,
        created_at=datetime.utcnow(),
    )
    store.save(rec)


def get_task_template(
    store: MemoryStore, template_name: str
) -> Optional[Dict[str, Any]]:
    rec = store.get(MemoryKind.KNOWLEDGE, f"task_template:{template_name}")
    return rec.data if rec else None
