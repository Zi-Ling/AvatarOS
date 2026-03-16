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

        # --- Priority 2.5: extract actual file paths from fs.write/fs.copy/fs.move node outputs ---
        targets = self._from_fs_node_outputs(graph, workspace)
        if targets:
            logger.debug(f"[TargetResolver] {len(targets)} target(s) from fs node outputs")
            return targets

        # --- Priority 3: workspace snapshot diff (new files in output/) ---
        targets = self._from_workspace_snapshot(workspace, graph)
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

    # fs skill 名称集合，用于从节点输出中提取实际写入的文件路径
    _FS_WRITE_SKILLS = {"fs.write", "fs.copy", "fs.move"}

    def _from_fs_node_outputs(
        self,
        graph: "ExecutionGraph",
        workspace: "SessionWorkspace",
    ) -> List[VerificationTarget]:
        """
        从已成功的 fs.write/fs.copy/fs.move 节点的 outputs 中反向提取实际写入的文件路径。

        这解决了 TargetResolver 无法从 goal 文本推断运行时文件名的问题：
        Planner 在运行时决定文件名（如 random_sentence_ja.txt），TargetResolver
        在 FINISH 前无法猜到。但 fs.write 节点执行后，outputs 里有实际写入的路径。
        """
        targets: List[VerificationTarget] = []
        try:
            from app.avatar.runtime.graph.models.step_node import NodeStatus
            for node in graph.nodes.values():
                if node.status != NodeStatus.SUCCESS:
                    continue
                if node.capability_name not in self._FS_WRITE_SKILLS:
                    continue

                outputs = node.outputs or {}
                # fs.write output 有 path 字段（单文件）或逗号分隔的多文件路径
                raw_path = outputs.get("path") or outputs.get("output") or ""
                if not raw_path:
                    continue

                # 支持 batch 模式：path 可能是 "a.txt, b.txt, c.txt"
                paths = [p.strip() for p in str(raw_path).split(",") if p.strip()]
                for fp in paths:
                    targets.append(VerificationTarget(
                        kind="file",
                        path=fp,
                        mime_type=self._guess_mime(fp),
                        producer_step_id=node.id,
                    ))
        except Exception as e:
            logger.debug(f"[TargetResolver] fs node output extraction failed: {e}")
        return targets

    def _from_workspace_snapshot(
        self,
        workspace: "SessionWorkspace",
        graph: "ExecutionGraph",
    ) -> List[VerificationTarget]:
        """
        Fallback: return files in workspace that were produced by the CURRENT graph.

        Scopes to current task by collecting all file paths referenced in
        succeeded nodes' outputs/params, then intersecting with the workspace
        snapshot. This prevents old files from previous tasks leaking in.
        """
        targets: List[VerificationTarget] = []
        try:
            # Collect file paths that the current graph's nodes actually produced
            from app.avatar.runtime.graph.models.step_node import NodeStatus
            graph_produced_names: set[str] = set()
            for node in graph.nodes.values():
                if node.status != NodeStatus.SUCCESS:
                    continue
                # Scan node outputs for file path references
                for v in (node.outputs or {}).values():
                    if isinstance(v, str) and v.strip():
                        # Could be a path or comma-separated paths
                        for segment in v.split(","):
                            segment = segment.strip()
                            if segment and ("." in segment or "/" in segment or "\\" in segment):
                                graph_produced_names.add(Path(segment).name)
                # Scan node params for file path references
                for v in (node.params or {}).values():
                    if isinstance(v, str) and v.strip():
                        for segment in v.split(","):
                            segment = segment.strip()
                            if segment and ("." in segment or "/" in segment or "\\" in segment):
                                graph_produced_names.add(Path(segment).name)

            if not graph_produced_names:
                logger.debug("[TargetResolver] workspace snapshot: no file names from graph nodes")
                return targets

            snapshot = workspace.snapshot_workspace()
            for rel_path in snapshot:
                file_name = Path(rel_path).name
                if file_name in graph_produced_names:
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
            ".svg":  "image/svg+xml",
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
