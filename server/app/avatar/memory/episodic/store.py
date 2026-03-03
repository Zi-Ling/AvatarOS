# avatar/memory/episodic/store.py
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..base import MemoryKind, MemoryRecord, MemoryStore


@dataclass
class Episode:
    """
    一条“情节事件”：
    - id        : 可选的事件 id（不强制要求，全局唯一则更好）
    - source    : 来源，例如 "task", "skill", "system"
    - type      : 事件类型，例如 "task_run", "skill_error"
    - payload   : 事件具体内容（字典）
    - created_at: 时间戳
    """
    id: Optional[str]
    source: str
    type: str
    payload: Dict[str, Any]
    created_at: datetime


class JsonlEpisodicMemoryStore(MemoryStore):
    """
    Episodic Memory 的 JSONL 版本：
    - 每条 MemoryRecord 作为一行 JSON 写入文件
    - 适合做“事件日志 + 以后可回放/分析”
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, record: MemoryRecord) -> None:
        if record.kind != MemoryKind.EPISODIC:
            raise ValueError(
                f"JsonlEpisodicMemoryStore 只能保存 kind=EPISODIC 的记录，当前={record.kind}"
            )

        line = json.dumps(
            {
                "kind": record.kind.value,
                "key": record.key,
                "data": record.data,
                "created_at": record.created_at.isoformat(),
            },
            ensure_ascii=False,
        )
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def get(self, kind: MemoryKind, key: str) -> Optional[MemoryRecord]:
        # 通常 episodic 不会按 key 精确查一条，这里做简单实现：从后往前扫一遍
        if kind != MemoryKind.EPISODIC:
            return None

        if not self._path.exists():
            return None

        with self._path.open("r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in reversed(lines):
            item = json.loads(line)
            if item["kind"] != MemoryKind.EPISODIC.value:
                continue
            if item["key"] != key:
                continue
            return MemoryRecord(
                kind=MemoryKind.EPISODIC,
                key=item["key"],
                data=item["data"],
                created_at=datetime.fromisoformat(item["created_at"]),
            )
        return None

    def query(
        self,
        kind: MemoryKind,
        prefix: Optional[str] = None,
        limit: int = 50,
    ) -> List[MemoryRecord]:
        if kind != MemoryKind.EPISODIC:
            return []

        if not self._path.exists():
            return []

        records: List[MemoryRecord] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                item = json.loads(line)
                if item["kind"] != MemoryKind.EPISODIC.value:
                    continue
                if prefix and not item["key"].startswith(prefix):
                    continue
                rec = MemoryRecord(
                    kind=MemoryKind.EPISODIC,
                    key=item["key"],
                    data=item["data"],
                    created_at=datetime.fromisoformat(item["created_at"]),
                )
                records.append(rec)
                if len(records) >= limit:
                    break
        return records


# 一些便捷函数：用于记录 Task/Skill 事件
def remember_task_run(
    store: MemoryStore,
    task_id: str,
    status: str,
    summary: str,
    extra: Dict[str, Any] | None = None,
) -> None:
    """
    记录一次 Task 运行事件
    key 示例: "task:123:run"
    """
    data = {
        "task_id": task_id,
        "status": status,  # success / failed / running ...
        "summary": summary,
        "extra": extra or {},
    }
    rec = MemoryRecord(
        kind=MemoryKind.EPISODIC,
        key=f"task:{task_id}:run:{datetime.utcnow().isoformat()}",
        data=data,
        created_at=datetime.utcnow(),
    )
    store.save(rec)


def remember_skill_event(
    store: MemoryStore,
    skill_name: str,
    event_type: str,
    status: str,
    detail: str,
    extra: Dict[str, Any] | None = None,
) -> None:
    """
    记录一次 Skill 相关事件（成功/失败/警告等）
    key 示例: "skill:write_text_file:event"
    """
    data = {
        "skill_name": skill_name,
        "event_type": event_type,  # usage / error / warning ...
        "status": status,
        "detail": detail,
        "extra": extra or {},
    }
    rec = MemoryRecord(
        kind=MemoryKind.EPISODIC,
        key=f"skill:{skill_name}:{event_type}:{datetime.utcnow().isoformat()}",
        data=data,
        created_at=datetime.utcnow(),
    )
    store.save(rec)
