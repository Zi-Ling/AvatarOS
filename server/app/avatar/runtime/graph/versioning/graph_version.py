"""
Graph Versioning - Snapshot and History Management

Tracks versions of ExecutionGraph as patches are applied.
Supports version history retrieval, diff computation, and retention policies.

Requirements: 33.1-33.14
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.models.graph_patch import GraphPatch

logger = logging.getLogger(__name__)


@dataclass
class GraphVersion:
    """
    A snapshot of an ExecutionGraph at a point in time.

    Requirements: 33.1, 33.2, 33.3
    """
    version: int                          # Monotonically increasing version number
    graph_id: str                         # ID of the graph this version belongs to
    graph_snapshot: Dict[str, Any]        # Full serialized graph state
    patch_applied: Optional[Dict[str, Any]]  # The patch that created this version (None for v0)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"            # Who/what created this version

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "graph_id": self.graph_id,
            "graph_snapshot": self.graph_snapshot,
            "patch_applied": self.patch_applied,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
        }


@dataclass
class GraphDiff:
    """
    Diff between two graph versions.

    Requirements: 33.11, 33.12
    """
    from_version: int
    to_version: int
    added_nodes: List[str] = field(default_factory=list)
    removed_nodes: List[str] = field(default_factory=list)
    added_edges: List[str] = field(default_factory=list)
    removed_edges: List[str] = field(default_factory=list)
    status_changed: Dict[str, str] = field(default_factory=dict)  # node_id -> new_status


class GraphVersionManager:
    """
    Manages version history for ExecutionGraphs.

    Features:
    - Create new version on patch application
    - Retrieve full version history
    - Compute diffs between versions
    - Retention policy: keep first 10 and last 10 versions

    Requirements: 33.1-33.14
    """

    # Retention policy: keep first N and last N versions (Requirements 33.13, 33.14)
    RETENTION_FIRST = 10
    RETENTION_LAST = 10

    def __init__(self):
        # graph_id -> list of GraphVersion (sorted by version number)
        self._versions: Dict[str, List[GraphVersion]] = {}

    def create_version(
        self,
        graph: 'ExecutionGraph',
        patch: Optional['GraphPatch'] = None,
        created_by: str = "system"
    ) -> GraphVersion:
        """
        Create a new version snapshot for a graph.

        Args:
            graph: Current ExecutionGraph state to snapshot
            patch: The patch that was applied (None for initial version)
            created_by: Identifier of who created this version

        Returns:
            New GraphVersion

        Requirements: 33.1, 33.2, 33.7
        """
        history = self._versions.setdefault(graph.id, [])
        version_number = len(history)  # 0-indexed

        # Serialize graph snapshot
        graph_snapshot = json.loads(graph.to_json())

        # Serialize patch if provided
        patch_data = None
        if patch is not None:
            patch_data = patch.model_dump(mode="json")

        version = GraphVersion(
            version=version_number,
            graph_id=graph.id,
            graph_snapshot=graph_snapshot,
            patch_applied=patch_data,
            created_by=created_by,
        )

        history.append(version)

        # Apply retention policy
        self._apply_retention(graph.id)

        logger.info(
            f"[GraphVersionManager] Created version {version_number} for graph {graph.id} "
            f"(total versions: {len(self._versions[graph.id])})"
        )

        return version

    def get_history(self, graph_id: str) -> List[GraphVersion]:
        """
        Get complete version history for a graph.

        Returns versions sorted by version number (ascending).

        Requirements: 33.8
        """
        return list(self._versions.get(graph_id, []))

    def get_version(self, graph_id: str, version: int) -> Optional[GraphVersion]:
        """
        Get a specific version by number.

        Requirements: 33.3
        """
        for v in self._versions.get(graph_id, []):
            if v.version == version:
                return v
        return None

    def get_latest(self, graph_id: str) -> Optional[GraphVersion]:
        """Get the most recent version."""
        history = self._versions.get(graph_id, [])
        return history[-1] if history else None

    def compute_diff(
        self,
        graph_id: str,
        from_version: int,
        to_version: int
    ) -> Optional[GraphDiff]:
        """
        Compute diff between two versions.

        Shows added/removed nodes and edges between versions.

        Requirements: 33.11, 33.12
        """
        v_from = self.get_version(graph_id, from_version)
        v_to = self.get_version(graph_id, to_version)

        if v_from is None or v_to is None:
            logger.warning(
                f"[GraphVersionManager] Cannot compute diff: "
                f"version {from_version} or {to_version} not found for graph {graph_id}"
            )
            return None

        snap_from = v_from.graph_snapshot
        snap_to = v_to.graph_snapshot

        nodes_from = set(snap_from.get("nodes", {}).keys())
        nodes_to = set(snap_to.get("nodes", {}).keys())
        edges_from = set(snap_from.get("edges", {}).keys())
        edges_to = set(snap_to.get("edges", {}).keys())

        # Detect status changes
        status_changed = {}
        for node_id in nodes_from & nodes_to:
            old_status = snap_from["nodes"][node_id].get("status")
            new_status = snap_to["nodes"][node_id].get("status")
            if old_status != new_status:
                status_changed[node_id] = new_status

        return GraphDiff(
            from_version=from_version,
            to_version=to_version,
            added_nodes=sorted(nodes_to - nodes_from),
            removed_nodes=sorted(nodes_from - nodes_to),
            added_edges=sorted(edges_to - edges_from),
            removed_edges=sorted(edges_from - edges_to),
            status_changed=status_changed,
        )

    def _apply_retention(self, graph_id: str) -> None:
        """
        Apply retention policy: keep first N and last N versions.

        Requirements: 33.13, 33.14
        """
        history = self._versions.get(graph_id, [])
        total = len(history)
        keep_count = self.RETENTION_FIRST + self.RETENTION_LAST

        if total <= keep_count:
            return  # Nothing to prune

        # Keep first RETENTION_FIRST and last RETENTION_LAST
        keep_indices = set(range(self.RETENTION_FIRST)) | set(range(total - self.RETENTION_LAST, total))
        pruned = [v for i, v in enumerate(history) if i in keep_indices]

        removed = total - len(pruned)
        if removed > 0:
            logger.debug(
                f"[GraphVersionManager] Retention policy pruned {removed} versions for graph {graph_id}"
            )

        self._versions[graph_id] = pruned

    def version_count(self, graph_id: str) -> int:
        """Get number of stored versions for a graph."""
        return len(self._versions.get(graph_id, []))
