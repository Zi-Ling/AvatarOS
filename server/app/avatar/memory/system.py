from __future__ import annotations

"""MemorySystem — tiered query router.

Provides layered access to WorkingMemory, ProjectMemory, and UserMemory.
Delegates persistence to the existing MemoryManager.
Implements memory decay: ProjectMemory 90 days, UserMemory 180 days → stale.
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .manager import MemoryManager
from .project_memory import ProjectMemory
from .user_memory import UserMemory
from .working_memory import WorkingMemory


# ---------------------------------------------------------------------------
# MemoryTier enum
# ---------------------------------------------------------------------------


class MemoryTier(str, Enum):
    WORKING = "working"
    PROJECT = "project"
    USER = "user"


# Decay thresholds in seconds
_DECAY_THRESHOLDS: dict[MemoryTier, float] = {
    MemoryTier.PROJECT: 90 * 86400,   # 90 days
    MemoryTier.USER: 180 * 86400,     # 180 days
}


# ---------------------------------------------------------------------------
# MemoryEntry dataclass
# ---------------------------------------------------------------------------


@dataclass
class MemoryEntry:
    """A single entry in the memory system."""

    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tier: MemoryTier = MemoryTier.WORKING
    key: str = ""
    content: dict[str, Any] = field(default_factory=dict)
    access_count: int = 0
    last_accessed_at: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    stale: bool = False
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "tier": self.tier.value,
            "key": self.key,
            "content": dict(self.content),
            "access_count": self.access_count,
            "last_accessed_at": self.last_accessed_at,
            "created_at": self.created_at,
            "stale": self.stale,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        return cls(
            entry_id=data.get("entry_id", str(uuid.uuid4())),
            tier=MemoryTier(data["tier"]) if "tier" in data else MemoryTier.WORKING,
            key=data.get("key", ""),
            content=dict(data.get("content") or {}),
            access_count=data.get("access_count", 0),
            last_accessed_at=data.get("last_accessed_at", time.time()),
            created_at=data.get("created_at", time.time()),
            stale=data.get("stale", False),
            schema_version=data.get("schema_version", "1.0.0"),
        )

    def touch(self) -> None:
        """Update access metadata."""
        self.access_count += 1
        self.last_accessed_at = time.time()


# ---------------------------------------------------------------------------
# MemorySystem
# ---------------------------------------------------------------------------


class MemorySystem:
    """Tiered query router. Not a uniform interface — each tier has its own
    retrieval semantics.

    * WorkingMemory: indexed by task_id
    * ProjectMemory: singleton, semantic search over patterns/lessons
    * UserMemory: singleton, key-based lookup
    """

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._mm = memory_manager
        self._working: dict[str, WorkingMemory] = {}
        self._project: Optional[ProjectMemory] = None
        self._user: Optional[UserMemory] = None
        # In-memory entry store for cross-tier query
        self._entries: dict[str, MemoryEntry] = {}

    # ------------------------------------------------------------------
    # Tier accessors
    # ------------------------------------------------------------------

    def get_working_memory(self, task_id: str) -> WorkingMemory:
        """Return (or create) the WorkingMemory for *task_id*."""
        if task_id not in self._working:
            # Try to load from MemoryManager working state
            data = self._mm.get_working_state(f"wm:{task_id}")
            if data:
                self._working[task_id] = WorkingMemory.from_dict(data)
            else:
                self._working[task_id] = WorkingMemory(task_id=task_id)
        return self._working[task_id]

    def get_project_memory(self) -> ProjectMemory:
        """Return the singleton ProjectMemory (lazy-loaded)."""
        if self._project is None:
            data = self._mm.get_knowledge("project:memory")
            if data:
                self._project = ProjectMemory.from_dict(data)
            else:
                self._project = ProjectMemory()
            self._project._memory_manager = self._mm
        return self._project

    def get_user_memory(self) -> UserMemory:
        """Return the singleton UserMemory (lazy-loaded)."""
        if self._user is None:
            data = self._mm.get_knowledge("user:memory")
            if data:
                self._user = UserMemory.from_dict(data)
            else:
                self._user = UserMemory()
        return self._user

    # ------------------------------------------------------------------
    # Cross-tier query
    # ------------------------------------------------------------------

    def store_entry(self, entry: MemoryEntry) -> None:
        """Store a MemoryEntry for later querying."""
        self._entries[entry.entry_id] = entry

    def query(
        self,
        tier: MemoryTier,
        query_str: str,
        context: Optional[dict[str, Any]] = None,
    ) -> list[MemoryEntry]:
        """Cross-tier query. Routes to the corresponding tier.

        Response time target: < 500ms (Requirement 12.3).
        Implementation uses in-memory filtering — O(n) scan is bounded
        by the entry store size.
        """
        results: list[MemoryEntry] = []
        for entry in self._entries.values():
            if entry.tier != tier:
                continue
            # Simple key-prefix / content substring match
            if query_str and query_str not in entry.key:
                # Also check content values
                content_str = str(entry.content)
                if query_str not in content_str:
                    continue
            entry.touch()
            results.append(entry)
        return results

    # ------------------------------------------------------------------
    # Memory decay
    # ------------------------------------------------------------------

    def apply_decay(self, now: Optional[float] = None) -> list[MemoryEntry]:
        """Mark entries as stale if they exceed the tier-specific threshold.

        Returns the list of entries that were newly marked stale.
        """
        now = now if now is not None else time.time()
        newly_stale: list[MemoryEntry] = []
        for entry in self._entries.values():
            if entry.stale:
                continue
            threshold = _DECAY_THRESHOLDS.get(entry.tier)
            if threshold is None:
                continue  # WORKING tier has no decay
            elapsed = now - entry.last_accessed_at
            if elapsed > threshold:
                entry.stale = True
                newly_stale.append(entry)
        return newly_stale
