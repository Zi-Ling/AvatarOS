# app/api/artifacts.py
"""
Artifact 查询 / 下载接口

所有下载接口在返回文件前校验 storage_uri 真实存在，不信任表记录。
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.db.database import engine
from app.db.artifact_record import ArtifactRecord

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _record_to_dict(r: ArtifactRecord) -> dict:
    import json as _json
    consumed = _json.loads(r.consumed_by_step_ids_json) if r.consumed_by_step_ids_json else []
    return {
        "id": r.id,
        "artifact_id": r.artifact_id,
        "session_id": r.session_id,
        "step_id": r.step_id,
        "filename": r.filename,
        "storage_uri": r.storage_uri,
        "size": r.size,
        "checksum": r.checksum,
        "mime_type": r.mime_type,
        "artifact_type": r.artifact_type,
        "consumed_by_step_ids": consumed,
        "created_at": r.created_at.isoformat(),
        "preview_url": r.preview_url or f"/artifacts/{r.artifact_id}/download",
        "preview_state": r.preview_state if r.preview_state != "none" else _infer_preview_state(r),
    }


def _infer_preview_state(r: ArtifactRecord) -> str:
    """根据 mime_type 推断 preview_state（兼容旧数据）。"""
    if r.mime_type and (
        r.mime_type.startswith("text/html")
        or r.mime_type.startswith("image/")
        or r.mime_type.startswith("text/")
    ):
        return "static"
    return "none"


@router.get("/session/{session_id}")
async def list_session_artifacts(session_id: str):
    """列出某个 ExecutionSession 的所有 artifact"""
    with Session(engine) as db:
        records = db.exec(
            select(ArtifactRecord)
            .where(ArtifactRecord.session_id == session_id)
            .order_by(ArtifactRecord.created_at)
        ).all()
    return [_record_to_dict(r) for r in records]


@router.get("/step/{step_id}")
async def list_step_artifacts(step_id: str):
    """列出某个 step（runtime node id）的所有 artifact"""
    with Session(engine) as db:
        records = db.exec(
            select(ArtifactRecord)
            .where(ArtifactRecord.step_id == step_id)
            .order_by(ArtifactRecord.created_at)
        ).all()
    return [_record_to_dict(r) for r in records]


@router.get("/{artifact_id}")
async def get_artifact(artifact_id: str):
    """获取单个 artifact 元数据"""
    with Session(engine) as db:
        record = db.exec(
            select(ArtifactRecord).where(ArtifactRecord.artifact_id == artifact_id)
        ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return _record_to_dict(record)


@router.get("/{artifact_id}/lineage")
async def get_artifact_lineage(artifact_id: str):
    """
    Artifact 血缘查询：谁产生了它，谁消费了它，同 step 还产生了哪些其他 artifact。
    用于 Artifact Explorer 的依赖图。
    """
    import json as _json

    with Session(engine) as db:
        record = db.exec(
            select(ArtifactRecord).where(ArtifactRecord.artifact_id == artifact_id)
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="Artifact not found")

        # 同 step 产生的其他 artifact（siblings）
        siblings = []
        if record.step_id:
            sibling_records = db.exec(
                select(ArtifactRecord)
                .where(ArtifactRecord.step_id == record.step_id)
                .where(ArtifactRecord.artifact_id != artifact_id)
            ).all()
            siblings = [
                {"artifact_id": r.artifact_id, "filename": r.filename, "artifact_type": r.artifact_type}
                for r in sibling_records
            ]

        # 消费方 step 产生的 artifact（downstream）
        consumed_by = _json.loads(record.consumed_by_step_ids_json) if record.consumed_by_step_ids_json else []
        downstream = []
        for consumer_step_id in consumed_by:
            consumer_artifacts = db.exec(
                select(ArtifactRecord)
                .where(ArtifactRecord.step_id == consumer_step_id)
                .where(ArtifactRecord.session_id == record.session_id)
            ).all()
            downstream.extend([
                {
                    "artifact_id": r.artifact_id,
                    "filename": r.filename,
                    "artifact_type": r.artifact_type,
                    "produced_by_step_id": consumer_step_id,
                }
                for r in consumer_artifacts
            ])

    return {
        "artifact_id": artifact_id,
        "filename": record.filename,
        "artifact_type": record.artifact_type,
        "produced_by": {
            "step_id": record.step_id,
            "session_id": record.session_id,
        },
        "consumed_by_step_ids": consumed_by,
        "siblings": siblings,        # 同 step 产生的其他 artifact
        "downstream": downstream,    # 消费方 step 产生的 artifact
    }


@router.get("/{artifact_id}/download")
async def download_artifact(artifact_id: str):
    """
    下载 artifact 文件。

    校验逻辑：
    1. 表记录必须存在
    2. storage_uri 对应的文件必须真实存在于磁盘（local backend）
    3. 仅支持 local filesystem URI（s3:// 等暂不支持直接下载）
    """
    with Session(engine) as db:
        record = db.exec(
            select(ArtifactRecord).where(ArtifactRecord.artifact_id == artifact_id)
        ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Artifact not found")

    uri = record.storage_uri
    if uri.startswith("s3://"):
        raise HTTPException(status_code=501, detail="S3 artifact download not yet supported via this endpoint")

    file_path = Path(uri)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=410,
            detail=f"Artifact file no longer exists at storage location: {uri}",
        )

    return FileResponse(
        path=str(file_path),
        filename=record.filename,
        media_type=record.mime_type or "application/octet-stream",
    )


# ── Version Lineage & Diff ────────────────────────────────────────────────────

@router.get("/versions/{task_session_id}/{artifact_path:path}")
async def get_version_lineage(task_session_id: str, artifact_path: str):
    """
    获取某个 artifact_path 在指定 task_session 下的所有版本（含 lineage 关系）。
    """
    from app.db.long_task_models import ArtifactVersionRecord

    with Session(engine) as db:
        versions = db.exec(
            select(ArtifactVersionRecord)
            .where(ArtifactVersionRecord.task_session_id == task_session_id)
            .where(ArtifactVersionRecord.artifact_path == artifact_path)
            .order_by(ArtifactVersionRecord.version.asc())
        ).all()

    if not versions:
        raise HTTPException(status_code=404, detail="No versions found")

    return {
        "task_session_id": task_session_id,
        "artifact_path": artifact_path,
        "total_versions": len(versions),
        "versions": [
            {
                "id": v.id,
                "version": v.version,
                "parent_version_id": v.parent_version_id,
                "version_source": v.version_source,
                "producer_step_id": v.producer_step_id,
                "content_hash": v.content_hash,
                "size": v.size,
                "stale_status": v.stale_status,
                "created_at": v.created_at.isoformat(),
            }
            for v in versions
        ],
    }


@router.get("/versions/diff/{version_a_id}/{version_b_id}")
async def diff_versions(version_a_id: str, version_b_id: str):
    """
    对比两个 ArtifactVersionRecord 的文本内容差异。
    仅支持文本类文件（通过关联的 ArtifactRecord 读取 storage_uri）。
    返回 unified diff 格式。
    """
    import difflib
    from app.db.long_task_models import ArtifactVersionRecord

    with Session(engine) as db:
        va = db.get(ArtifactVersionRecord, version_a_id)
        vb = db.get(ArtifactVersionRecord, version_b_id)

    if not va or not vb:
        raise HTTPException(status_code=404, detail="Version not found")

    # 通过 artifact_path 找到对应的 ArtifactRecord（取 storage_uri）
    def _read_content(version: ArtifactVersionRecord) -> list[str]:
        with Session(engine) as db:
            record = db.exec(
                select(ArtifactRecord)
                .where(ArtifactRecord.session_id.isnot(None))
                .where(ArtifactRecord.filename == Path(version.artifact_path).name)
                .where(ArtifactRecord.checksum == version.content_hash)
            ).first()
        if not record:
            # Fallback: 直接用 artifact_path
            p = Path(version.artifact_path)
            if p.exists() and p.is_file():
                return p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            raise HTTPException(status_code=410, detail=f"File not found for version {version.id}")
        p = Path(record.storage_uri)
        if not p.exists():
            raise HTTPException(status_code=410, detail=f"File no longer exists: {record.storage_uri}")
        return p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)

    lines_a = _read_content(va)
    lines_b = _read_content(vb)

    diff = list(difflib.unified_diff(
        lines_a, lines_b,
        fromfile=f"{va.artifact_path} v{va.version}",
        tofile=f"{vb.artifact_path} v{vb.version}",
    ))

    return {
        "version_a": {"id": va.id, "version": va.version, "path": va.artifact_path},
        "version_b": {"id": vb.id, "version": vb.version, "path": vb.artifact_path},
        "has_changes": len(diff) > 0,
        "diff_lines": len(diff),
        "unified_diff": "".join(diff),
    }
