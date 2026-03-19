"""
GoalCoverageTracker — maintains per-round coverage of sub-goals.

Coverage judgment priority:
  1. Typed artifact / output contract from succeeded graph nodes (highest confidence)
  2. Verifier result binding
  3. File existence heuristic (lowest confidence, advisory only)

ever_satisfied is monotonically non-decreasing.
currently_satisfied can revert (e.g. file overwritten to empty).
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, List, Optional

from app.avatar.runtime.verification.models import (
    GoalCoverageSummary,
    NormalizedGoal,
    SubGoalStatus,
    VerificationResult,
    VerificationStatus,
)

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.verification.goal_normalizer import GoalNormalizer
    from app.avatar.runtime.workspace.session_workspace import SessionWorkspace

logger = logging.getLogger(__name__)


class GoalCoverageTracker:
    """
    Tracks sub-goal coverage across ReAct rounds.

    Usage:
        tracker = GoalCoverageTracker(goal_normalizer)
        summary = tracker.initialize(normalized_goal)
        # ... after each round ...
        summary = tracker.update_after_round(summary, graph, workspace, verifier_results)
    """

    def __init__(self, goal_normalizer: "GoalNormalizer") -> None:
        self._normalizer = goal_normalizer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def initialize(self, normalized_goal: NormalizedGoal) -> GoalCoverageSummary:
        """Create an initial GoalCoverageSummary from a NormalizedGoal."""
        sub_goals = [
            SubGoalStatus(description=sg)
            for sg in (normalized_goal.sub_goals or [normalized_goal.original])
        ]
        total = len(sub_goals)
        deliverable_total = len(normalized_goal.deliverables) if normalized_goal.deliverables else 0
        return GoalCoverageSummary(
            goal=normalized_goal.original,
            sub_goals=sub_goals,
            satisfied_count=0,
            total_count=total,
            coverage_ratio=0.0,
            last_updated_at=time.time(),
            deliverable_satisfied_count=0,
            deliverable_total_count=deliverable_total,
        )

    def update_after_round(
        self,
        summary: GoalCoverageSummary,
        graph: "ExecutionGraph",
        workspace: "SessionWorkspace",
        verifier_results: Optional[List[VerificationResult]] = None,
        env_context: Optional[dict] = None,
    ) -> GoalCoverageSummary:
        """
        Update coverage summary after one ReAct round.

        Postconditions:
        - summary.satisfied_count == count(sg for sg in sub_goals if sg.currently_satisfied)
        - sg.ever_satisfied is monotonically non-decreasing
        - sg.currently_satisfied CAN decrease
        """
        succeeded_nodes = self._get_succeeded_nodes(graph)
        artifacts = self._get_workspace_artifacts(workspace)

        for sg in summary.sub_goals:
            new_satisfied = False
            new_evidence: Optional[str] = None

            # Priority 1: output contract from succeeded nodes
            for node in succeeded_nodes:
                contract = (node.metadata or {}).get("output_contract")
                # SkillOutputContract 是 dataclass，转成 dict 供匹配
                if contract is not None and not isinstance(contract, dict):
                    try:
                        from dataclasses import asdict
                        contract = asdict(contract)
                    except Exception:
                        contract = {}
                contract = contract or {}
                if self._contract_matches_subgoal(contract, sg.description):
                    new_satisfied = True
                    new_evidence = f"step:{node.id}"
                    break

            # Priority 1.5: fs.write/fs.copy/fs.move 成功即判定覆盖
            # 这些 skill 成功意味着文件已确定性写入，不需要文本匹配
            _FS_WRITE_SKILLS = {"fs.write", "fs.copy", "fs.move"}
            if not new_satisfied:
                for node in succeeded_nodes:
                    if node.capability_name in _FS_WRITE_SKILLS:
                        outputs = node.outputs or {}
                        if outputs.get("success") is not False:
                            new_satisfied = True
                            written_path = outputs.get("path") or outputs.get("output") or ""
                            new_evidence = f"fs_write:{node.id}:{written_path}"
                            break

            # Priority 1.6: python.run 产物识别
            # python.run 不走 _output() 协议时，ArtifactCollector 会把实际产物路径
            # 写入 __artifact_paths__，或 output_processor 会写 artifact_semantic。
            _CODE_SKILLS = {"python.run"}
            if not new_satisfied:
                for node in succeeded_nodes:
                    if node.capability_name not in _CODE_SKILLS:
                        continue
                    outputs = node.outputs or {}
                    metadata = node.metadata or {}
                    # Check __artifact_paths__ (set by ArtifactCollector)
                    art_paths = outputs.get("__artifact_paths__")
                    if isinstance(art_paths, list) and art_paths:
                        new_satisfied = True
                        new_evidence = f"code_artifact:{node.id}:{art_paths[0]}"
                        break
                    # Check artifact_semantic (set by output_processor)
                    art_sem = metadata.get("artifact_semantic")
                    if isinstance(art_sem, list) and art_sem:
                        new_satisfied = True
                        p = art_sem[0].get("path", "") if isinstance(art_sem[0], dict) else ""
                        new_evidence = f"code_semantic:{node.id}:{p}"
                        break
                    # Check explicit file_path in outputs
                    fp = outputs.get("file_path")
                    if fp and isinstance(fp, str) and fp.strip():
                        new_satisfied = True
                        new_evidence = f"code_file:{node.id}:{fp}"
                        break

            # Priority 1.7: llm.fallback / 纯文本产出型 skill 成功即覆盖
            # 对于翻译/问答/总结等任务，llm.fallback 成功且有非空输出即判定覆盖
            _TEXT_SKILLS = {"llm.fallback"}
            if not new_satisfied:
                for node in succeeded_nodes:
                    if node.capability_name not in _TEXT_SKILLS:
                        continue
                    outputs = node.outputs or {}
                    # llm.fallback 输出有 result/output/content 字段
                    text_out = (
                        outputs.get("result")
                        or outputs.get("output")
                        or outputs.get("content")
                        or ""
                    )
                    if isinstance(text_out, str) and len(text_out.strip()) > 10:
                        new_satisfied = True
                        new_evidence = f"text_output:{node.id}:{len(text_out)}chars"
                        break

            # Priority 1.8: python.run stdout-only 成功（无文件产物但有 stdout 输出）
            # 覆盖"列出文件名并打印"等 info-display 任务
            if not new_satisfied:
                for node in succeeded_nodes:
                    if node.capability_name not in _CODE_SKILLS:
                        continue
                    outputs = node.outputs or {}
                    stdout = outputs.get("stdout") or ""
                    output_val = outputs.get("output")
                    # 有 stdout 输出或有非空 output（list/str）即判定覆盖
                    if isinstance(stdout, str) and len(stdout.strip()) > 5:
                        new_satisfied = True
                        new_evidence = f"code_stdout:{node.id}:{len(stdout)}chars"
                        break
                    if output_val is not None and output_val != "" and output_val != []:
                        new_satisfied = True
                        new_evidence = f"code_output:{node.id}:{type(output_val).__name__}"
                        break

            # Priority 2: verifier result binding
            if not new_satisfied and verifier_results:
                for result in verifier_results:
                    if (
                        result.status == VerificationStatus.PASSED
                        and self._result_matches_subgoal(result, sg.description)
                    ):
                        new_satisfied = True
                        new_evidence = f"verifier:{result.verifier_name}"
                        sg.verifier_result = result
                        break

            # Priority 3: artifact existence heuristic
            if not new_satisfied:
                for artifact_path in artifacts:
                    if self._artifact_matches_subgoal(artifact_path, sg.description):
                        new_satisfied = True
                        new_evidence = artifact_path
                        break

            # Update state
            sg.currently_satisfied = new_satisfied
            if new_satisfied:
                sg.ever_satisfied = True  # monotonically non-decreasing
                sg.evidence = new_evidence

        # Recompute counts
        satisfied = sum(1 for sg in summary.sub_goals if sg.currently_satisfied)
        total = max(summary.total_count, 1)
        summary.satisfied_count = satisfied
        summary.coverage_ratio = satisfied / total
        summary.last_updated_at = time.time()

        # Update deliverable counts from env_context
        if env_context:
            del_states = env_context.get("deliverable_states", {})
            if del_states:
                summary.deliverable_satisfied_count = sum(
                    1 for ds in del_states.values()
                    if hasattr(ds, "status") and ds.status == "satisfied"
                )

        logger.debug(
            f"[GoalCoverageTracker] Coverage: {satisfied}/{summary.total_count} "
            f"({summary.coverage_ratio:.0%})"
        )
        if summary.deliverable_total_count > 0:
            logger.debug(
                f"[GoalCoverageTracker] Coverage: {summary.satisfied_count}/{summary.total_count} sub-goals, "
                f"{summary.deliverable_satisfied_count}/{summary.deliverable_total_count} deliverables"
            )
        return summary

    # ------------------------------------------------------------------
    # Matching helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _contract_matches_subgoal(contract: dict, description: str) -> bool:
        """
        Check if a node's output contract satisfies a sub-goal description.

        Phase 2: enhanced typed artifact extraction.
        Checks file_path, output_path, artifact_ref, artifact_id, mime_type,
        typed_artifacts list, and goal/description fields.
        """
        if not contract:
            return False
        desc_lower = description.lower()

        # Direct path/ref fields
        for key in ("file_path", "output_path", "artifact_ref", "artifact_id"):
            val = contract.get(key)
            if val:
                val_str = str(val).lower()
                # Match by filename or extension
                if val_str in desc_lower:
                    return True
                # Match by extension keyword (e.g. ".csv" in description)
                import re
                ext_match = re.search(r'\.\w{2,6}$', val_str)
                if ext_match and ext_match.group().lstrip(".") in desc_lower:
                    return True

        # Phase 2: typed_artifacts list (e.g. [{"type": "csv", "path": "output/data.csv"}])
        typed_artifacts = contract.get("typed_artifacts") or contract.get("artifacts") or []
        if isinstance(typed_artifacts, list):
            for art in typed_artifacts:
                if not isinstance(art, dict):
                    continue
                art_type = str(art.get("type") or "").lower()
                art_path = str(art.get("path") or art.get("file_path") or "").lower()
                art_mime = str(art.get("mime_type") or "").lower()
                if art_type and art_type in desc_lower:
                    return True
                if art_path and art_path in desc_lower:
                    return True
                if art_mime:
                    # e.g. "text/csv" → "csv" in description
                    mime_ext = art_mime.split("/")[-1]
                    if mime_ext and mime_ext in desc_lower:
                        return True

        # Goal/description field in contract
        goal_field = contract.get("goal") or contract.get("description") or ""
        if goal_field and any(
            word in goal_field.lower()
            for word in desc_lower.split()
            if len(word) > 3
        ):
            return True
        return False

    @staticmethod
    def _result_matches_subgoal(result: VerificationResult, description: str) -> bool:
        """Check if a VerificationResult covers a sub-goal."""
        desc_lower = description.lower()
        target_path = result.target.path or ""
        if target_path and target_path.lower() in desc_lower:
            return True
        # Heuristic: if verifier passed and description mentions file-like keywords
        if result.status == VerificationStatus.PASSED:
            import re
            file_mentions = re.findall(r'\b\w+\.\w{2,6}\b', desc_lower)
            if file_mentions and target_path:
                for mention in file_mentions:
                    if mention in target_path.lower():
                        return True
        return False

    @staticmethod
    def _artifact_matches_subgoal(artifact_path: str, description: str) -> bool:
        """Heuristic: check if an artifact path is mentioned in the sub-goal."""
        import re
        desc_lower = description.lower()
        path_lower = artifact_path.lower()
        # Extract filename
        filename = path_lower.split("/")[-1].split("\\")[-1]
        if filename and filename in desc_lower:
            return True
        # Extension match
        ext_match = re.search(r'\.\w{2,6}$', path_lower)
        if ext_match:
            ext = ext_match.group().lstrip(".")
            if ext in desc_lower:
                return True
        return False

    @staticmethod
    def _get_succeeded_nodes(graph: "ExecutionGraph") -> list:
        try:
            from app.avatar.runtime.graph.models.step_node import NodeStatus
            return [n for n in graph.nodes.values() if n.status == NodeStatus.SUCCESS]
        except Exception:
            return []

    @staticmethod
    def _get_workspace_artifacts(workspace: "SessionWorkspace") -> List[str]:
        try:
            snapshot = workspace.snapshot_workspace()
            return list(snapshot.keys())
        except Exception:
            return []
