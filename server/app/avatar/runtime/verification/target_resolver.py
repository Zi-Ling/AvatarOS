"""
TargetResolver — resolves VerificationTarget list from NormalizedGoal + execution facts.

Resolution priority:
  1. NormalizedGoal.expected_artifacts (typed artifact first)
  2. Graph last-succeeded node output contract (file_path / artifact_ref)
  3. SessionWorkspace.snapshot_workspace() diff (new files in output/)
  4. Empty list fallback
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from app.avatar.runtime.verification.models import NormalizedGoal, VerificationTarget

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.workspace.session_workspace import SessionWorkspace

logger = logging.getLogger(__name__)


class TargetResolver:

    def resolve_targets(
        self,
        normalized_goal: NormalizedGoal,
        graph: "ExecutionGraph",
        workspace: "SessionWorkspace",
    ) -> List[VerificationTarget]:
        targets: List[VerificationTarget] = []

        # --- Priority 1: expected_artifacts from NormalizedGoal ---
        for art in normalized_goal.expected_artifacts:
            if art.path_hint:
                # Resolve glob-like hints against workspace output_dir
                resolved = self._resolve_path_hint(art.path_hint, workspace)
                for p in resolved:
                    targets.append(VerificationTarget(
                        kind="file",
                        path=str(p),
                        mime_type=art.mime_type,
                        producer_step_id=self._find_producer(str(p), graph),
                    ))
            else:
                # No path hint — create a loose artifact_ref target
                targets.append(VerificationTarget(
                    kind="artifact_ref",
                    artifact_ref=art.label,
                    mime_type=art.mime_type,
                ))

        if targets:
            logger.debug(f"[TargetResolver] {len(targets)} target(s) from expected_artifacts")
            return targets

        # --- Priority 2: graph last-succeeded node output contract ---
        targets = self._from_graph_output_contract(graph, workspace)
        if targets:
            logger.debug(f"[TargetResolver] {len(targets)} target(s) from graph output contract")
            return targets

        # --- Priority 3: workspace snapshot diff (new files in output/) ---
        targets = self._from_workspace_snapshot(workspace)
        if targets:
            logger.debug(f"[TargetResolver] {len(targets)} target(s) from workspace snapshot")
            return targets

        logger.debug("[TargetResolver] No targets resolved — returning empty list")
        return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_path_hint(self, hint: str, workspace: "SessionWorkspace") -> List[Path]:
        """Resolve a path hint (may be absolute, relative, or glob) against output_dir."""
        p = Path(hint)
        if p.is_absolute():
            return [p] if p.exists() else [p]  # return even if not yet created

        # Try relative to output_dir
        output_dir = workspace.output_dir
        if "*" in hint or "?" in hint:
            # glob pattern
            return list(output_dir.glob(hint.lstrip("output/").lstrip("/")))
        candidate = output_dir / hint.lstrip("output/").lstrip("/")
        return [candidate]

    def _from_graph_output_contract(
        self,
        graph: "ExecutionGraph",
        workspace: "SessionWorkspace",
    ) -> List[VerificationTarget]:
        """Extract targets from the output contracts of recently succeeded nodes."""
        targets: List[VerificationTarget] = []
        try:
            from app.avatar.runtime.graph.models.step_node import NodeStatus
            succeeded = [
                n for n in graph.nodes.values()
                if n.status == NodeStatus.SUCCESS
            ]
            # Most recent first
            succeeded_sorted = sorted(
                succeeded,
                key=lambda n: getattr(n, "updated_at", None) or "",
                reverse=True,
            )
            for node in succeeded_sorted[:5]:  # inspect last 5 succeeded nodes
                contract = getattr(node, "output_contract", None) or {}
                file_path = contract.get("file_path") or contract.get("output_path")
                artifact_ref = contract.get("artifact_ref") or contract.get("artifact_id")
                mime_type = contract.get("mime_type")

                if file_path:
                    targets.append(VerificationTarget(
                        kind="file",
                        path=str(file_path),
                        mime_type=mime_type,
                        producer_step_id=node.id,
                    ))
                elif artifact_ref:
                    targets.append(VerificationTarget(
                        kind="artifact_ref",
                        artifact_ref=str(artifact_ref),
                        mime_type=mime_type,
                        producer_step_id=node.id,
                    ))
        except Exception as e:
            logger.debug(f"[TargetResolver] output_contract extraction failed: {e}")
        return targets

    def _from_workspace_snapshot(self, workspace: "SessionWorkspace") -> List[VerificationTarget]:
        """Return all files currently in output/ as file targets."""
        targets: List[VerificationTarget] = []
        try:
            snapshot = workspace.snapshot_workspace()
            for rel_path in snapshot:
                abs_path = workspace.root / rel_path
                targets.append(VerificationTarget(
                    kind="file",
                    path=str(abs_path),
                    mime_type=self._guess_mime(rel_path),
                ))
        except Exception as e:
            logger.debug(f"[TargetResolver] workspace snapshot failed: {e}")
        return targets

    @staticmethod
    def _find_producer(file_path: str, graph: "ExecutionGraph") -> Optional[str]:
        """Find the most recent succeeded node whose output_contract references this path."""
        try:
            from app.avatar.runtime.graph.models.step_node import NodeStatus
            for node in reversed(list(graph.nodes.values())):
                if node.status != NodeStatus.SUCCESS:
                    continue
                contract = getattr(node, "output_contract", None) or {}
                fp = contract.get("file_path") or contract.get("output_path")
                if fp and str(fp) == file_path:
                    return node.id
        except Exception:
            pass
        return None

    @staticmethod
    def _guess_mime(path: str) -> Optional[str]:
        _mime_map = {
            ".json": "application/json",
            ".csv":  "text/csv",
            ".png":  "image/png",
            ".jpg":  "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif":  "image/gif",
            ".txt":  "text/plain",
            ".md":   "text/markdown",
            ".html": "text/html",
            ".xml":  "application/xml",
            ".pdf":  "application/pdf",
            ".yaml": "application/yaml",
            ".yml":  "application/yaml",
        }
        dot = path.rfind(".")
        if dot == -1:
            return None
        return _mime_map.get(path[dot:].lower())
