# app/db/file_artifact.py
"""
FileArtifact — 文件产物元信息表（存储在 avatar.db）
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel


class FileArtifact(SQLModel, table=True):
    __tablename__ = "file_artifacts"

    id: Optional[int] = Field(default=None, primary_key=True)
    artifact_id: str = Field(unique=True, index=True)
    file_path: str = Field(index=True)
    filename: str
    sha256: str = Field(index=True)
    size: int
    mime_type: str = Field(default="")
    source_url: str = Field(default="", index=True)
    task_id: str = Field(default="", index=True)
    node_id: str = Field(default="", index=True)
    skill_name: str = Field(default="")
    created_at: str = Field(default="")
    lifecycle: str = Field(default="intermediate")  # intermediate | final | temp
