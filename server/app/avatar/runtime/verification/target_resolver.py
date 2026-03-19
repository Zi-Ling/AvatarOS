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

    # 非文件产出型 goal_type：不需要文件验证目标
    _NON_FILE_GOAL_TYPES = frozenset({"query", "data_analysis", "general"})

    def resolve_targets(
        self,
        normalized_goal: NormalizedGoal,
        graph: "ExecutionGraph",
        workspace: "SessionWorkspace",
    ) -> List[VerificationTarget]:
        targets: List[VerificationTarget] = []

        # 非文件产出型任务：不提取文件 target，让 CompletionGate 走 _no_verifier_verdict
        if normalized_goal.goal_type in self._NON_FILE_GOAL_TYPES and not normalized_goal.expected_artifacts:
            logger.debug(
                f"[TargetResolver] Non-file goal_type={normalized_goal.goal_type}, "
                f"no expected_artifacts — skipping file target resolution"
            )
            return targets

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

        # --- Priority 2.4: __artifact_paths__ from ArtifactCollector (ground truth) ---
        targets = self._from_artifact_paths(graph)
        if targets:
            logger.debug(f"[TargetResolver] {len(targets)} target(s) from artifact paths")
            return targets

        # --- Priority 2.5: extract actual file paths from fs.write/fs.copy/fs.move node outputs ---
        targets = self._from_fs_node_outputs(graph, workspace)
        if targets:
            logger.debug(f"[TargetResolver] {len(targets)} target(s) from fs node outputs")
            return targets

        # --- Priority 2.6: extract file paths from python.run __OUTPUT__ protocol ---
        targets = self._from_code_node_outputs(graph)
        if targets:
            logger.debug(f"[TargetResolver] {len(targets)} target(s) from code node outputs")
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
                # output_contract is stored in node.metadata, not as a direct attribute
                contract = (node.metadata or {}).get("output_contract") or {}
                # SkillOutputContract dataclass → convert to dict if needed
                if not isinstance(contract, dict):
                    contract = {k: getattr(contract, k, None) for k in ("file_path", "output_path", "artifact_ref", "artifact_id", "mime_type")} if hasattr(contract, "file_path") else {}
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

    def _from_artifact_paths(
        self,
        graph: "ExecutionGraph",
    ) -> List[VerificationTarget]:
        """
        从所有成功节点的 __artifact_paths__（由 ArtifactCollector 写入）提取文件产物。

        这是最可靠的来源：ArtifactCollector 在节点执行后扫描 workspace diff，
        把实际新增/修改的文件路径写入 node.outputs["__artifact_paths__"]。
        不依赖 _output() 协议或 stdout 解析。
        """
        targets: List[VerificationTarget] = []
        try:
            from app.avatar.runtime.graph.models.step_node import NodeStatus
            for node in graph.nodes.values():
                if node.status != NodeStatus.SUCCESS:
                    continue
                art_paths = (node.outputs or {}).get("__artifact_paths__")
                if not isinstance(art_paths, list):
                    continue
                for p in art_paths:
                    if isinstance(p, str) and p.strip():
                        targets.append(VerificationTarget(
                            kind="file",
                            path=p.strip(),
                            mime_type=self._guess_mime(p),
                            producer_step_id=node.id,
                        ))
        except Exception as e:
            logger.debug(f"[TargetResolver] artifact_paths extraction failed: {e}")
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

    _CODE_SKILLS = {"python.run"}

    def _from_code_node_outputs(
        self,
        graph: "ExecutionGraph",
    ) -> List[VerificationTarget]:
        """
        从已成功的 python.run 节点中提取文件产物。

        来源优先级：
        1. node.outputs["file_path"]（_save_binary 写的单文件）
        2. node.outputs["stdout"] 中的 __OUTPUT__:{"__file__": ...} 协议行
        3. node.outputs["output"] 如果是 list，遍历其中的文件路径字符串
        4. node.metadata["artifact_semantic"] 中已提取的路径
        """
        import json as _json

        targets: List[VerificationTarget] = []
        try:
            from app.avatar.runtime.graph.models.step_node import NodeStatus
            for node in graph.nodes.values():
                if node.status != NodeStatus.SUCCESS:
                    continue
                if node.capability_name not in self._CODE_SKILLS:
                    continue

                outputs = node.outputs or {}
                seen_paths: set = set()

                # Source 1: explicit file_path field
                fp = outputs.get("file_path")
                if fp and isinstance(fp, str) and fp.strip():
                    seen_paths.add(fp.strip())

                # Source 2: __OUTPUT__ protocol lines in stdout
                stdout = outputs.get("stdout") or ""
                if isinstance(stdout, str):
                    for line in stdout.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("__OUTPUT__:"):
                            payload = stripped[len("__OUTPUT__:"):]
                            try:
                                obj = _json.loads(payload)
                                if isinstance(obj, dict):
                                    path = obj.get("__file__") or obj.get("path")
                                    if path and isinstance(path, str):
                                        seen_paths.add(path.strip())
                            except (ValueError, TypeError):
                                pass

                # Source 3: output list containing file path strings
                out_val = outputs.get("output")
                if isinstance(out_val, list):
                    for item in out_val:
                        if isinstance(item, str) and "." in item:
                            seen_paths.add(item.strip())

                # Source 4: artifact_semantic metadata (set by _extract_artifact_semantic)
                art_semantic = (node.metadata or {}).get("artifact_semantic")
                if isinstance(art_semantic, list):
                    for entry in art_semantic:
                        if isinstance(entry, dict):
                            p = entry.get("path")
                            if p and isinstance(p, str):
                                seen_paths.add(p.strip())

                for path in seen_paths:
                    targets.append(VerificationTarget(
                        kind="file",
                        path=path,
                        mime_type=self._guess_mime(path),
                        producer_step_id=node.id,
                    ))
        except Exception as e:
            logger.debug(f"[TargetResolver] code node output extraction failed: {e}")
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
                contract = (node.metadata or {}).get("output_contract") or {}
                if not isinstance(contract, dict):
                    contract = {}
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
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls":  "application/vnd.ms-excel",
            ".parquet": "application/x-parquet",
        }
        dot = path.rfind(".")
        if dot == -1:
            return None
        return _mime_map.get(path[dot:].lower())
