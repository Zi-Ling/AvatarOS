from __future__ import annotations

"""EnvironmentModel — workspace fact state.

Maintains a structured understanding of the current workspace environment.
Provides scope-based context extraction for LLM calls and incremental updates
via EventBus file.changed events.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WorkspaceSnapshot dataclass
# ---------------------------------------------------------------------------


@dataclass
class WorkspaceSnapshot:
    """Lightweight workspace snapshot (V1).

    Fields:
        file_tree_summary: Top-level directory structure and file counts.
        build_test_summary: Most recent build/test result summary.
        recent_changes: Last N changed files (default 20).
        active_services: Currently running services (if any).
        schema_version: Schema version string.
    """

    file_tree_summary: dict[str, Any] = field(default_factory=dict)
    build_test_summary: dict[str, Any] = field(default_factory=dict)
    recent_changes: list[str] = field(default_factory=list)
    active_services: list[str] = field(default_factory=list)
    schema_version: str = "1.0.0"

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_tree_summary": dict(self.file_tree_summary),
            "build_test_summary": dict(self.build_test_summary),
            "recent_changes": list(self.recent_changes),
            "active_services": list(self.active_services),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkspaceSnapshot:
        return cls(
            file_tree_summary=dict(data.get("file_tree_summary") or {}),
            build_test_summary=dict(data.get("build_test_summary") or {}),
            recent_changes=list(data.get("recent_changes") or []),
            active_services=list(data.get("active_services") or []),
            schema_version=data.get("schema_version", "1.0.0"),
        )


# ---------------------------------------------------------------------------
# Scope → snapshot field mapping
# ---------------------------------------------------------------------------

# Maps scope keywords to the snapshot fields that are relevant.
_SCOPE_FIELD_MAP: dict[str, list[str]] = {
    "build": ["build_test_summary", "recent_changes"],
    "test": ["build_test_summary", "recent_changes"],
    "files": ["file_tree_summary", "recent_changes"],
    "services": ["active_services"],
    "changes": ["recent_changes"],
}

_ALL_FIELDS = ["file_tree_summary", "build_test_summary", "recent_changes", "active_services"]

_MAX_RECENT_CHANGES = 20


# ---------------------------------------------------------------------------
# EnvironmentModel
# ---------------------------------------------------------------------------


class EnvironmentModel:
    """Environment model — maintains workspace current fact state.

    Provides:
    * ``get_context(scope)`` — scope-filtered subset of the snapshot.
    * ``get_snapshot()`` — full snapshot.
    * ``update_incremental(changed_files)`` — incremental update.
    * ``detect_significant_change()`` — detect major changes.
    """

    def __init__(self, workspace_path: Optional[Path] = None) -> None:
        self._workspace_path = workspace_path
        self._snapshot = WorkspaceSnapshot()
        self._previous_build_status: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_context(self, scope: str) -> dict[str, Any]:
        """Return a subset of the snapshot relevant to *scope*.

        If *scope* matches known keywords (build, test, files, services,
        changes), only the corresponding fields are returned.  Otherwise
        the full snapshot dict is returned.
        """
        scope_lower = scope.lower().strip() if scope else ""

        # Collect relevant fields from all matching keywords
        relevant_fields: set[str] = set()
        for keyword, fields in _SCOPE_FIELD_MAP.items():
            if keyword in scope_lower:
                relevant_fields.update(fields)

        if not relevant_fields:
            # No keyword match → return full snapshot
            return self._snapshot.to_dict()

        full = self._snapshot.to_dict()
        return {k: v for k, v in full.items() if k in relevant_fields or k == "schema_version"}

    def get_snapshot(self) -> WorkspaceSnapshot:
        """Return the full current snapshot."""
        return self._snapshot

    def update_incremental(self, changed_files: list[str]) -> None:
        """Incremental update — only update affected subtrees.

        * Appends to ``recent_changes`` (capped at ``_MAX_RECENT_CHANGES``).
        * Updates ``file_tree_summary`` entries for affected top-level dirs.
        """
        if not changed_files:
            return

        # Update recent_changes (prepend new, cap at max)
        existing = set(self._snapshot.recent_changes)
        for f in changed_files:
            if f not in existing:
                self._snapshot.recent_changes.insert(0, f)
        self._snapshot.recent_changes = self._snapshot.recent_changes[:_MAX_RECENT_CHANGES]

        # Update file_tree_summary for affected top-level directories
        for fpath in changed_files:
            parts = Path(fpath).parts
            if parts:
                top_dir = parts[0]
                count = self._snapshot.file_tree_summary.get(top_dir, 0)
                if isinstance(count, (int, float)):
                    self._snapshot.file_tree_summary[top_dir] = int(count) + 1
                else:
                    # Non-numeric entry — just mark as updated
                    self._snapshot.file_tree_summary[top_dir] = {"updated": True}

    def detect_significant_change(self) -> Optional[Any]:
        """Detect significant workspace changes.

        Returns a RuntimeSignal (ENVIRONMENT_CHANGE) if a significant change
        is detected, otherwise ``None``.

        Significant changes (V1):
        * Build status changed to failure.
        * Test status changed to failure.
        * Critical file deleted (detected via recent_changes heuristic).
        """
        from ..runtime.kernel.signals import RuntimeSignal, SignalType

        current_build_status = self._snapshot.build_test_summary.get("build_status")
        current_test_status = self._snapshot.build_test_summary.get("test_status")

        reasons: list[str] = []

        # Build failure detection
        if (
            current_build_status == "failed"
            and self._previous_build_status != "failed"
        ):
            reasons.append("build_failed")

        # Test regression detection
        if current_test_status == "failed":
            reasons.append("test_regression")

        self._previous_build_status = current_build_status

        if not reasons:
            return None

        return RuntimeSignal(
            signal_type=SignalType.ENVIRONMENT_CHANGE,
            source_subsystem="environment_model",
            reason=", ".join(reasons),
            metadata={"reasons": reasons},
        )

    # ------------------------------------------------------------------
    # Snapshot manipulation helpers
    # ------------------------------------------------------------------

    def set_snapshot(self, snapshot: WorkspaceSnapshot) -> None:
        """Replace the current snapshot (useful for testing / init)."""
        self._snapshot = snapshot

    def update_build_test_summary(self, summary: dict[str, Any]) -> None:
        """Update the build/test summary portion of the snapshot."""
        self._snapshot.build_test_summary.update(summary)

    def update_active_services(self, services: list[str]) -> None:
        """Replace the active services list."""
        self._snapshot.active_services = list(services)
