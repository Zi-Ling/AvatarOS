"""
ArtifactRegistryRecord — SQLModel persistence for ArtifactRegistry.

Stores semantic metadata managed by ArtifactRegistry (P0 spec).
Separate from ArtifactRecord which tracks byte storage.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class ArtifactRegistryRecord(SQLModel, table=True):
    """
    Persistent record for ArtifactRegistry entries.

    Maps to the artifact_registry table defined in the design doc.
    """
    __tablename__ = "artifact_registry"

    id: str = Field(primary_key=True, index=True)       # UUID
    session_id: str = Field(index=True)
    type: str                                            # ArtifactType enum value
    path: str
    producer_step: str = Field(index=True)
    hash: str                                            # SHA-256
    size: int
    preview: Optional[str] = Field(default=None)        # ≤256 chars
    semantic_label: Optional[str] = Field(default=None, index=True)
    version: int = Field(default=1)
    metadata_json: Optional[str] = Field(default=None)  # JSON-encoded metadata dict
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_metadata_dict(self) -> dict:
        if self.metadata_json:
            try:
                return json.loads(self.metadata_json)
            except Exception:
                return {}
        return {}
