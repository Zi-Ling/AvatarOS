# app/avatar/runtime/workspace/artifact_collector.py

"""
ArtifactCollector — 把 session sandbox 接进 Runtime 数据链

职责：
  step 执行结束后，扫描 session sandbox 根目录，
  把新增/修改文件提升为 Artifact record，挂回 step result / session。

设计原则：
  - ArtifactCollector  负责发现（扫描 sandbox，diff 找变化文件）
  - ArtifactStore      负责保存（写盘 + 内存索引）
  - 调用方（NodeRunner）负责挂接关系（把 artifact_ids 写进 node outputs）
"""

import hashlib
import logging
import mimetypes
import shutil
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.graph.storage.artifact_store import ArtifactStore, Artifact
    from app.avatar.runtime.workspace.session_workspace import SessionWorkspace

logger = logging.getLogger(__name__)


def _mime_to_artifact_type(mime: Optional[str], path: Path) -> str:
    """把 MIME type 映射到 ArtifactType 枚举值"""
    if mime is None:
        return "file"
    if mime.startswith("image/"):
        return "image"
    if mime in ("application/json", "text/csv", "application/x-parquet"):
        return "dataset"
    if mime.startswith("text/"):
        return "file"
    if path.suffix in (".pkl", ".pt", ".onnx", ".bin"):
        return "model"
    if path.suffix in (".zip", ".tar", ".gz", ".bz2"):
        return "archive"
    return "file"


class CollectedArtifact:
    """单个收集到的 artifact 信息（轻量 DTO）"""
    __slots__ = ("artifact_id", "filename", "local_path", "storage_uri",
                 "size", "checksum", "mime_type", "artifact_type")

    def __init__(
        self,
        artifact_id: str,
        filename: str,
        local_path: str,
        storage_uri: str,
        size: int,
        checksum: str,
        mime_type: Optional[str],
        artifact_type: str,
    ):
        self.artifact_id   = artifact_id
        self.filename      = filename
        self.local_path    = local_path
        self.storage_uri   = storage_uri
        self.size          = size
        self.checksum      = checksum
        self.mime_type     = mime_type
        self.artifact_type = artifact_type

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


class ArtifactCollector:
    """
    扫描 session sandbox，把新增/修改文件提升为 Artifact。

    用法（在 NodeRunner 执行完后调用）：
        before = workspace.snapshot_workspace()
        # ... 执行 step ...
        artifacts = await collector.collect(
            workspace=workspace,
            before_snapshot=before,
            node_id=node.id,
            session_id=context.session_id,
        )
        node.outputs["__artifacts__"] = [a.artifact_id for a in artifacts]
    """

    def __init__(self, artifact_store: "ArtifactStore"):
        self.artifact_store = artifact_store

    async def collect(
        self,
        workspace: "SessionWorkspace",
        before_snapshot: Dict[str, float],
        node_id: str,
        session_id: str,
        export_to: Optional[Path] = None,
    ) -> List[CollectedArtifact]:
        """
        扫描 session sandbox 根目录，把 before_snapshot 之后新增或修改的文件注册为 artifact。
        如果提供 export_to，同时把文件 copy 到用户 workspace，让用户能直接看到产出物。

        Returns:
            新注册的 CollectedArtifact 列表（可能为空）
        """
        changed = workspace.changed_workspace_files(before_snapshot)
        new_files = changed["new"] + changed["modified"]
        if not new_files:
            return []

        # Filter out framework debug artifacts (input/ directory contains
        # step_N_output.json, manifest.json etc. injected by CodeInjectorMixin)
        _DEBUG_DIRS = {"input", "logs", "tmp"}
        deliverable_files: List[Path] = []
        for fp in new_files:
            try:
                rel = fp.relative_to(workspace.root)
                if rel.parts and rel.parts[0] in _DEBUG_DIRS:
                    continue
            except ValueError:
                pass
            deliverable_files.append(fp)

        if not deliverable_files:
            return []

        from app.avatar.runtime.graph.storage.artifact_store import ArtifactType

        collected: List[CollectedArtifact] = []

        for file_path in deliverable_files:
            try:
                artifact = await self._promote_file(
                    file_path=file_path,
                    node_id=node_id,
                    session_id=session_id,
                    artifact_type_cls=ArtifactType,
                )
                collected.append(artifact)
                logger.info(
                    f"[ArtifactCollector] Promoted {file_path.name} "
                    f"→ artifact {artifact.artifact_id} (node={node_id})"
                )

                # 持久化到 ArtifactRecord 表
                try:
                    from app.db.artifact_record import ArtifactRecord
                    from app.db.database import engine
                    from sqlmodel import Session as DBSession
                    record = ArtifactRecord(
                        artifact_id=artifact.artifact_id,
                        session_id=session_id,
                        step_id=node_id,
                        filename=artifact.filename,
                        storage_uri=artifact.storage_uri,
                        size=artifact.size,
                        checksum=artifact.checksum,
                        mime_type=artifact.mime_type,
                        artifact_type=artifact.artifact_type,
                    )
                    with DBSession(engine) as db:
                        db.add(record)
                        db.commit()
                except Exception as db_err:
                    logger.warning(f"[ArtifactCollector] ArtifactRecord persist failed: {db_err}")

                # 导出到用户 workspace
                if export_to is not None:
                    try:
                        dest = export_to / file_path.name
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(file_path), str(dest))
                        logger.info(f"[ArtifactCollector] Exported {file_path.name} → {dest}")
                    except Exception as e:
                        logger.warning(f"[ArtifactCollector] Export failed for {file_path.name}: {e}")

            except Exception as e:
                logger.warning(
                    f"[ArtifactCollector] Failed to promote {file_path}: {e}"
                )

        return collected

    async def _promote_file(
        self,
        file_path: Path,
        node_id: str,
        session_id: str,
        artifact_type_cls,
    ) -> CollectedArtifact:
        """读取文件，计算元数据，写入 ArtifactStore"""
        data = file_path.read_bytes()
        size = len(data)
        checksum = hashlib.sha256(data).hexdigest()

        mime_type, _ = mimetypes.guess_type(str(file_path))
        art_type_str = _mime_to_artifact_type(mime_type, file_path)

        # 映射到 ArtifactType 枚举
        try:
            art_type = artifact_type_cls(art_type_str)
        except ValueError:
            art_type = artifact_type_cls("file")

        stored: "Artifact" = await self.artifact_store.store(
            data=data,
            artifact_type=art_type,
            created_by_node=node_id,
            metadata={
                "filename":   file_path.name,
                "session_id": session_id,
                "checksum":   checksum,
                "mime_type":  mime_type,
                "source":     "workspace_output",
            },
        )

        return CollectedArtifact(
            artifact_id   = stored.id,
            filename      = file_path.name,
            local_path    = str(file_path),
            storage_uri   = stored.uri,
            size          = size,
            checksum      = checksum,
            mime_type     = mime_type,
            artifact_type = art_type_str,
        )
