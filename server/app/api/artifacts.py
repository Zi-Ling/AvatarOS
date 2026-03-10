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
    }


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
