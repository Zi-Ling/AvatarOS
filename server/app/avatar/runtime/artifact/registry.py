"""
ArtifactRegistry — first-class artifact lifecycle management.

Sits above ArtifactStore (byte storage) and manages semantic metadata,
versioning, and queryable artifact records.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ArtifactType(str, Enum):
    FILE = "file"
    IMAGE = "image"
    TABLE = "table"
    JSON_BLOB = "json_blob"
    BINARY = "binary"
    REPORT = "report"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ArtifactVersion:
    version_id: str
    path: str
    producer_step: str
    hash: str                       # SHA-256
    semantic_label: Optional[str]
    created_at: datetime


@dataclass
class Artifact:
    id: str                         # globally unique UUID within session
    type: ArtifactType
    path: str                       # filesystem path
    producer_step: str              # step_id that produced this artifact
    hash: str                       # SHA-256, computed at registration
    size: int                       # bytes
    created_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    preview: Optional[str] = None           # ≤256 chars
    semantic_label: Optional[str] = None    # e.g. "output_report"
    version: int = 1                        # increments when hash changes
    versions: List[ArtifactVersion] = field(default_factory=list)


class ArtifactNotFoundError(Exception):
    """Raised when artifact_id is not found. Never returns None silently."""
    pass


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ArtifactRegistry:
    """
    Manages artifact lifecycle: registration, versioning, querying.

    Thread-safety: not guaranteed for concurrent writes; callers should
    serialize registration if needed.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        # artifact_id → Artifact
        self._artifacts: Dict[str, Artifact] = {}
        # (path, producer_step, semantic_label) → artifact_id for dedup
        self._path_index: Dict[tuple, str] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        path: str,
        producer_step: str,
        artifact_type: ArtifactType,
        semantic_label: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Artifact:
        """
        Register an artifact.

        1. Compute SHA-256 hash of file content
        2. Generate preview (image: dimensions/format; text: first 256 chars)
        3. Version check: path + producer_step + semantic_label key
           - hash changed → new version, version += 1, preserve history
           - hash unchanged → return existing artifact (idempotent)
        4. Assign unique UUID
        """
        file_hash = self._compute_hash(path)
        file_size = self._get_file_size(path)
        preview = self._generate_preview(path, artifact_type)

        index_key = (path, producer_step, semantic_label)
        existing_id = self._path_index.get(index_key)

        if existing_id and existing_id in self._artifacts:
            existing = self._artifacts[existing_id]
            if existing.hash == file_hash:
                # Idempotent: same content, return existing
                return existing
            # Hash changed: create new version
            new_version = existing.version + 1
            version_record = ArtifactVersion(
                version_id=str(uuid.uuid4()),
                path=existing.path,
                producer_step=existing.producer_step,
                hash=existing.hash,
                semantic_label=existing.semantic_label,
                created_at=existing.created_at,
            )
            existing.versions.append(version_record)
            existing.hash = file_hash
            existing.size = file_size
            existing.preview = preview
            existing.version = new_version
            existing.created_at = datetime.now(timezone.utc)
            if metadata:
                existing.metadata.update(metadata)
            logger.debug(
                f"[ArtifactRegistry] Updated artifact {existing.id} to version {new_version}"
            )
            return existing

        # New artifact
        artifact_id = str(uuid.uuid4())
        artifact = Artifact(
            id=artifact_id,
            type=artifact_type,
            path=path,
            producer_step=producer_step,
            hash=file_hash,
            size=file_size,
            created_at=datetime.now(timezone.utc),
            metadata=metadata or {},
            preview=preview,
            semantic_label=semantic_label,
            version=1,
            versions=[],
        )
        self._artifacts[artifact_id] = artifact
        self._path_index[index_key] = artifact_id
        logger.debug(f"[ArtifactRegistry] Registered artifact {artifact_id} at {path}")
        return artifact

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get(self, artifact_id: str) -> Artifact:
        """
        Retrieve artifact by id.
        Raises ArtifactNotFoundError if not found — never returns None.
        """
        artifact = self._artifacts.get(artifact_id)
        if artifact is None:
            raise ArtifactNotFoundError(
                f"Artifact '{artifact_id}' not found in session '{self.session_id}'"
            )
        return artifact

    def list(
        self,
        producer_step: Optional[str] = None,
        artifact_type: Optional[ArtifactType] = None,
        created_after: Optional[datetime] = None,
        semantic_label: Optional[str] = None,
    ) -> List[Artifact]:
        """
        Query artifacts with AND-combined filters.
        All filter parameters are optional; omitting them returns all artifacts.
        """
        results = []
        for artifact in self._artifacts.values():
            if producer_step is not None and artifact.producer_step != producer_step:
                continue
            if artifact_type is not None and artifact.type != artifact_type:
                continue
            if created_after is not None and artifact.created_at <= created_after:
                continue
            if semantic_label is not None and artifact.semantic_label != semantic_label:
                continue
            results.append(artifact)
        return results

    def get_artifact_summary(self, max_chars: int = 1000) -> str:
        """
        Generate a compact summary for PlannerPromptBuilder.
        Only includes: id / type / preview / producer_step / semantic_label.
        Total length capped at max_chars.
        """
        if not self._artifacts:
            return "[artifacts] none"

        lines = ["[artifacts]"]
        for artifact in self._artifacts.values():
            preview_str = f" preview={artifact.preview!r}" if artifact.preview else ""
            label_str = f" label={artifact.semantic_label}" if artifact.semantic_label else ""
            line = (
                f"  id={artifact.id[:8]}... type={artifact.type.value} "
                f"step={artifact.producer_step}{label_str}{preview_str}"
            )
            lines.append(line)

        summary = "\n".join(lines)
        if len(summary) > max_chars:
            summary = summary[:max_chars - 3] + "..."
        return summary

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_hash(self, path: str) -> str:
        """Compute SHA-256 hash of file content."""
        sha256 = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    sha256.update(chunk)
        except OSError as e:
            raise FileNotFoundError(f"Cannot compute hash for '{path}': {e}") from e
        return sha256.hexdigest()

    def _get_file_size(self, path: str) -> int:
        """Get file size in bytes."""
        import os
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    def _generate_preview(self, path: str, artifact_type: ArtifactType) -> Optional[str]:
        """
        Generate a ≤256 char preview string.
        - image: "{width}x{height} {format}"
        - text/json/report: first 256 chars
        - binary/table: None
        """
        try:
            if artifact_type == ArtifactType.IMAGE:
                return self._image_preview(path)
            elif artifact_type in (ArtifactType.FILE, ArtifactType.JSON_BLOB, ArtifactType.REPORT):
                return self._text_preview(path)
            else:
                return None
        except Exception:
            return None

    @staticmethod
    def _image_preview(path: str) -> Optional[str]:
        """Return '{width}x{height} {format}' for image files."""
        try:
            from PIL import Image
            with Image.open(path) as img:
                w, h = img.size
                fmt = img.format or "unknown"
                return f"{w}x{h} {fmt}"
        except ImportError:
            # PIL not available, fall back to basic info
            import os
            size = os.path.getsize(path)
            ext = path.rsplit(".", 1)[-1].upper() if "." in path else "unknown"
            return f"{ext} {size}B"
        except Exception:
            return None

    @staticmethod
    def _text_preview(path: str) -> Optional[str]:
        """Return first 256 chars of text content."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(256)
            return content[:256]
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Persistent backend (SQLite via SQLModel)
# ---------------------------------------------------------------------------

class PersistentArtifactRegistry(ArtifactRegistry):
    """
    ArtifactRegistry with SQLite persistence backend.
    Loads existing artifacts from DB on init, persists new registrations.
    """

    def __init__(self, session_id: str, engine: Any = None) -> None:
        super().__init__(session_id)
        if engine is None:
            try:
                from app.db.database import engine as default_engine
                engine = default_engine
            except ImportError:
                engine = None
        self._engine = engine
        if self._engine:
            self._load_from_db()

    def _load_from_db(self) -> None:
        """Load existing artifacts for this session from the database."""
        try:
            from sqlmodel import Session, select
            from app.db.artifact_registry_record import ArtifactRegistryRecord

            with Session(self._engine) as session:
                records = session.exec(
                    select(ArtifactRegistryRecord).where(
                        ArtifactRegistryRecord.session_id == self.session_id
                    )
                ).all()

            for rec in records:
                from app.avatar.runtime.artifact.registry import ArtifactType
                try:
                    atype = ArtifactType(rec.type)
                except ValueError:
                    atype = ArtifactType.FILE

                artifact = Artifact(
                    id=rec.id,
                    type=atype,
                    path=rec.path,
                    producer_step=rec.producer_step,
                    hash=rec.hash,
                    size=rec.size,
                    created_at=rec.created_at,
                    metadata=rec.to_metadata_dict(),
                    preview=rec.preview,
                    semantic_label=rec.semantic_label,
                    version=rec.version,
                    versions=[],
                )
                self._artifacts[artifact.id] = artifact
                index_key = (rec.path, rec.producer_step, rec.semantic_label)
                self._path_index[index_key] = artifact.id

            logger.debug(
                f"[PersistentArtifactRegistry] Loaded {len(records)} artifacts "
                f"for session {self.session_id}"
            )
        except Exception as e:
            logger.warning(f"[PersistentArtifactRegistry] Failed to load from DB: {e}")

    def register(
        self,
        path: str,
        producer_step: str,
        artifact_type: ArtifactType,
        semantic_label: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Artifact:
        """Register artifact and persist to DB."""
        artifact = super().register(
            path=path,
            producer_step=producer_step,
            artifact_type=artifact_type,
            semantic_label=semantic_label,
            metadata=metadata,
        )
        if self._engine:
            self._persist(artifact)
        return artifact

    def _persist(self, artifact: Artifact) -> None:
        """Upsert artifact record to database."""
        try:
            import json as _json
            from sqlmodel import Session
            from app.db.artifact_registry_record import ArtifactRegistryRecord

            record = ArtifactRegistryRecord(
                id=artifact.id,
                session_id=self.session_id,
                type=artifact.type.value,
                path=artifact.path,
                producer_step=artifact.producer_step,
                hash=artifact.hash,
                size=artifact.size,
                preview=artifact.preview,
                semantic_label=artifact.semantic_label,
                version=artifact.version,
                metadata_json=_json.dumps(artifact.metadata) if artifact.metadata else None,
                created_at=artifact.created_at,
            )
            with Session(self._engine) as session:
                existing = session.get(ArtifactRegistryRecord, artifact.id)
                if existing:
                    existing.hash = record.hash
                    existing.size = record.size
                    existing.preview = record.preview
                    existing.version = record.version
                    existing.metadata_json = record.metadata_json
                    existing.created_at = record.created_at
                    session.add(existing)
                else:
                    session.add(record)
                session.commit()
        except Exception as e:
            logger.warning(f"[PersistentArtifactRegistry] Failed to persist artifact {artifact.id}: {e}")
