"""Artifact, ArtifactStore — 多 Agent 结构化事实载体.

注意：现有代码库中已有 ArtifactRegistry（server/app/avatar/runtime/artifact/registry.py），
本模块为多 Agent 场景的轻量级适配层，不重复实现文件级 artifact 管理。

Requirements: 17.1, 17.2, 17.3, 17.4, 17.5
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Artifact:
    """结构化事实载体."""
    artifact_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    artifact_type: str = ""
    creator_instance_id: str = ""
    creator_role: str = ""
    task_id: str = ""
    content: Dict[str, Any] = field(default_factory=dict)
    version: int = 1
    created_at: float = field(default_factory=time.time)
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "creator_instance_id": self.creator_instance_id,
            "creator_role": self.creator_role,
            "task_id": self.task_id,
            "content": dict(self.content),
            "version": self.version,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Artifact:
        return cls(
            artifact_id=data.get("artifact_id", str(uuid.uuid4())),
            artifact_type=data.get("artifact_type", ""),
            creator_instance_id=data.get("creator_instance_id", ""),
            creator_role=data.get("creator_role", ""),
            task_id=data.get("task_id", ""),
            content=dict(data.get("content") or {}),
            version=data.get("version", 1),
            created_at=data.get("created_at", time.time()),
            schema_version=data.get("schema_version", "1.0.0"),
        )


class ArtifactStore:
    """Artifact 共享存储. Phase 1 为基础存储，版本追踪保留接口."""

    def __init__(self) -> None:
        self._artifacts: Dict[str, Artifact] = {}
        self._versions: Dict[str, List[Artifact]] = {}  # artifact_id -> version history

    def register(self, artifact: Artifact) -> str:
        """注册 Artifact，返回 artifact_id."""
        self._artifacts[artifact.artifact_id] = artifact
        if artifact.artifact_id not in self._versions:
            self._versions[artifact.artifact_id] = []
        self._versions[artifact.artifact_id].append(artifact)
        return artifact.artifact_id

    def get(self, artifact_id: str) -> Optional[Artifact]:
        """按 artifact_id 获取."""
        return self._artifacts.get(artifact_id)

    def query(
        self,
        artifact_type: Optional[str] = None,
        creator_role: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> List[Artifact]:
        """按条件查询."""
        results: List[Artifact] = []
        for a in self._artifacts.values():
            if artifact_type is not None and a.artifact_type != artifact_type:
                continue
            if creator_role is not None and a.creator_role != creator_role:
                continue
            if task_id is not None and a.task_id != task_id:
                continue
            results.append(a)
        return results

    def update(self, artifact_id: str, content: Dict[str, Any]) -> Optional[Artifact]:
        """更新 Artifact 内容，版本号递增."""
        artifact = self._artifacts.get(artifact_id)
        if artifact is None:
            return None
        artifact.content = content
        artifact.version += 1
        # Phase 2: 完善版本追踪
        return artifact

    def get_versions(self, artifact_id: str) -> List[Artifact]:
        """获取版本历史. Phase 1 保留接口."""
        return self._versions.get(artifact_id, [])
