# app/db/artifact_record.py
"""
ArtifactRecord — 持久化 artifact 元数据表

ArtifactStore 是内存索引 + 文件存储，进程重启后丢失。
ArtifactRecord 是持久化层，记录每个 artifact 的元数据，
供 History 回放、Inspector、下载接口使用。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field
import uuid


class ArtifactRecord(SQLModel, table=True):
    """
    Artifact 持久化元数据记录。

    - artifact_id: 与 ArtifactStore 内存索引的 Artifact.id 一致
    - session_id:  绑定 ExecutionSession.id
    - step_id:     绑定 runtime node identity（StepTraceRecord.step_id）
    - storage_uri: ArtifactStore backend 返回的存储路径（local path 或 s3://...）
    """
    __tablename__ = "artifact_records"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )

    # ── 关联锚点 ──────────────────────────────────────────────────────
    artifact_id: str = Field(index=True)          # ArtifactStore 内的 artifact id
    session_id: str = Field(index=True)
    step_id: Optional[str] = Field(default=None, index=True)  # runtime node id

    # ── 文件元数据 ────────────────────────────────────────────────────
    filename: str
    storage_uri: str                               # 存储路径，下载时校验真实存在
    size: int = Field(default=0)
    checksum: Optional[str] = Field(default=None) # SHA-256
    mime_type: Optional[str] = Field(default=None)
    artifact_type: str = Field(default="file")    # file / image / dataset / model / archive

    # ── 时间戳 ────────────────────────────────────────────────────────
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── 血缘关系 ──────────────────────────────────────────────────────
    # 哪些 step 消费了这个 artifact（JSON array of step_id strings）
    # 由 NodeRunner 在参数解析时写入，支持 artifact dependency graph
    consumed_by_step_ids_json: Optional[str] = Field(default=None)
