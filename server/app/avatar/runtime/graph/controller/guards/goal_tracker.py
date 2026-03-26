"""
GoalTracker — Goal decomposition, coverage detection, and terminal evidence.

Extracted from GraphController. Provides:
- Goal decomposition into sub-goals (regex, no LLM)
- Sub-goal coverage checking against succeeded nodes
- Terminal evidence short-circuit (runtime hard rule, not Planner-dependent)
- Progress guard (detect "success but no progress" loops)

All skill metadata (tags, risk levels, side effects) is read from the
SkillRegistry at init time — no hardcoded skill names or tag dicts.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, FrozenSet, List, Optional, Set, Tuple, TYPE_CHECKING
import logging
import re

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph

logger = logging.getLogger(__name__)


# ── Configuration dataclass ─────────────────────────────────────────────

@dataclass(frozen=True)
class GoalTrackerConfig:
    """All tunable parameters for GoalTracker in one place.

    Centralises regex patterns, thresholds, stopwords, and magic numbers
    that were previously hardcoded inline.
    """

    # ── Progress guard ──────────────────────────────────────────────
    max_no_progress_rounds: int = 2

    # ── Keyword overlap threshold for terminal evidence ─────────────
    keyword_overlap_threshold: float = 0.5

    # ── Meaningful text threshold (chars) for _check_required_outputs
    meaningful_text_threshold: int = 50

    # ── Multi-step guard: minimum distinct skill types ──────────────
    multi_step_min_distinct_skills: int = 2

    # ── Stopwords (English + Chinese) ───────────────────────────────
    stopwords: FrozenSet[str] = frozenset({
        "the", "a", "an", "is", "are", "in", "on", "at", "to", "of",
        "and", "or", "for", "with", "by", "from", "that", "this",
        "请", "帮我", "我要", "一下", "所有", "的", "了", "在", "把",
        "并", "然后", "接着", "之后",
    })

    # ── Regex patterns (source strings — compiled at GoalTracker init)
    # Goal split: conjunctions that separate sub-goals
    goal_split_pattern: str = (
        r'(?:[\s，,、;；。]+|(?<=[\u4e00-\u9fff])|(?<=\w))'
        r'(?:并且|然后|接着|之后|完成后'
        r'|and\s+then|then\s+also|after\s+that|additionally)'
        r'(?:[\s，,、;；]+|(?=[\u4e00-\u9fff])|(?=\w))'
    )

    # Multi-step connectors (blocks single-skill short-circuit)
    multi_step_connectors_pattern: str = (
        r'(?:然后|接着|之后|再|并|转换|转为|转成|改为|变为|变成'
        r'|then|after that|and then|convert|transform)'
    )

    # Phased goal prefix detection
    phased_goal_prefix_pattern: str = r'\[Phase\s+\d+/\d+\]'

    # ── File deliverable verification ───────────────────────────────
    # When True, deliverable short-circuit checks that files actually
    # exist on disk, have the correct extension, and are non-empty.
    file_verification_enabled: bool = True
    # Minimum file size in bytes to consider a deliverable non-empty
    file_min_size_bytes: int = 10
    # Known artifact extensions (lowercase, no dot) — files with these
    # extensions are eligible for on-disk verification
    artifact_extensions: FrozenSet[str] = frozenset({
        "md", "txt", "docx", "pdf", "html", "csv", "json", "xml",
        "xlsx", "pptx", "py", "js", "ts", "java", "c", "cpp", "go",
        "rs", "rb", "png", "jpg", "jpeg", "gif", "svg", "mp3", "mp4",
        "zip", "tar", "gz",
    })
    # Search directories (relative to session workspace root) when
    # resolving produced file paths for on-disk verification
    file_search_dirs: Tuple[str, ...] = ("output", ".")


class GoalTracker:
    """
    Framework-level goal tracking with zero LLM calls.

    Responsibilities:
    1. Decompose goal into sub-goals.
    2. Check which sub-goals are covered by succeeded nodes.
    3. Terminal evidence short-circuit — hard rule before each Planner call.
    4. Progress guard — detect consecutive rounds with no new side effects.
    """

    def __init__(self, config: Optional[GoalTrackerConfig] = None) -> None:
        self._cfg = config or GoalTrackerConfig()

        # ── Compile regex patterns from config ─────────────────────────
        self._goal_split_re = re.compile(self._cfg.goal_split_pattern, re.IGNORECASE)
        self._multi_step_connectors_re = re.compile(
            self._cfg.multi_step_connectors_pattern, re.IGNORECASE,
        )
        self._phased_goal_re = re.compile(self._cfg.phased_goal_prefix_pattern)

        # ── Progress guard state ───────────────────────────────────────
        self._prev_succeeded_ids: Set[str] = set()
        self._no_progress_rounds: int = 0

        # ── Build skill metadata from registry ─────────────────────────
        self._skill_tags: Dict[str, List[str]] = {}
        self._compute_skills: Set[str] = set()
        self._io_tags: Set[str] = set()
        self._producer_skills: Set[str] = set()
        self._read_only_skills: Set[str] = set()
        self._load_from_registry()

    def _load_from_registry(self) -> None:
        """
        Build all skill classification sets from SkillRegistry.

        Classification rules (based on SkillSpec metadata, not names):
        - skill_tags:      spec.tags (for sub-goal coverage matching)
        - compute_skills:  risk_level == EXECUTE (code execution skills)
        - io_tags:         union of tags from all WRITE/READ skills (for
                           detecting IO intent in sub-goals)
        - producer_skills: risk_level in (WRITE, EXECUTE, SYSTEM)
                           Only skills whose risk_level explicitly indicates
                           mutation are producers.  READ skills with FS
                           side_effects (e.g. fs.read) must NOT be counted —
                           they observe state but never produce deliverables.
        - read_only_skills: risk_level in (READ, SAFE)
        """
        from app.avatar.skills.base import SkillRiskLevel
        from app.avatar.skills.registry import skill_registry

        for spec in skill_registry.list_specs():
            # Tags for sub-goal coverage
            self._skill_tags[spec.name] = spec.tags if spec.tags else [spec.name]

            # Compute skills: EXECUTE risk level
            if spec.risk_level == SkillRiskLevel.EXECUTE:
                self._compute_skills.add(spec.name)

            # Producer skills: can create/modify external state.
            if spec.risk_level in (SkillRiskLevel.WRITE, SkillRiskLevel.EXECUTE, SkillRiskLevel.SYSTEM):
                self._producer_skills.add(spec.name)

            # Read-only skills: READ or SAFE risk level
            if spec.risk_level in (SkillRiskLevel.READ, SkillRiskLevel.SAFE):
                self._read_only_skills.add(spec.name)

            # IO tags: collect tags from READ/WRITE skills for IO intent detection
            if spec.risk_level in (SkillRiskLevel.READ, SkillRiskLevel.WRITE):
                self._io_tags.update(spec.tags)

        logger.debug(
            "[GoalTracker] Loaded from registry: %d skills, "
            "%d compute, %d producer, %d read-only",
            len(self._skill_tags), len(self._compute_skills),
            len(self._producer_skills), len(self._read_only_skills),
        )

    # ── Phase-local goal extraction (Bug 3 fix) ────────────────────────

    def _extract_local_goal(self, raw_goal: str) -> str:
        """Extract the phase-local goal line from a potentially scoped intent.

        PhasedPlanner builds scoped_intent as:
            "[Phase X/Y] <objective>\\n\\nOriginal user goal: ...\\n..."

        The "Original user goal" section contains the PARENT goal which may
        have multi-step connectors (然后, 并, etc.) that do NOT apply to
        this sub-phase.  Matching connectors against the full scoped_intent
        causes the multi-step guard (Condition 4) to block short-circuit
        for single-skill sub-phases, leading to infinite web.search loops.

        Returns only the first line (phase objective) when a phased prefix
        is detected, otherwise returns the full goal unchanged.
        """
        if self._phased_goal_re.match(raw_goal):
            first_line = raw_goal.split('\n', 1)[0].strip()
            if first_line:
                return first_line
        return raw_goal

    # ── Goal decomposition ──────────────────────────────────────────────

    def decompose_goal(self, goal: str) -> List[str]:
        """Split goal into sub-goals. Single-clause goals return [goal]."""
        # For phased goals, only split the actual goal line
        split_text = self._extract_local_goal(goal)

        parts = self._goal_split_re.split(split_text)
        sub_goals = [p.strip() for p in parts if p and p.strip()]
        result = sub_goals if len(sub_goals) > 1 else [goal]

        return result

    # ── Sub-goal coverage ───────────────────────────────────────────────

    def get_uncovered_sub_goals(
        self,
        sub_goals: List[str],
        graph: 'ExecutionGraph',
    ) -> List[str]:
        """Return sub-goals not yet covered by any succeeded node."""
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        if len(sub_goals) <= 1:
            return []

        successful_nodes = [
            n for n in graph.nodes.values() if n.status == NodeStatus.SUCCESS
        ]
        if not successful_nodes:
            return list(sub_goals)

        uncovered = []
        for sg in sub_goals:
            if not any(self._node_covers(n, sg) for n in successful_nodes):
                uncovered.append(sg)
        return uncovered

    # ── Deliverable coverage (planning perspective) ─────────────────────

    def get_unsatisfied_deliverables(
        self,
        deliverables: List[Any],
        graph: 'ExecutionGraph',
    ) -> List[Any]:
        """
        Return deliverables not yet produced by any succeeded node (planning perspective).

        This is a lightweight check: a deliverable is considered "produced" if any
        succeeded *producer* node wrote a file whose extension matches the deliverable
        format.  Read-only skills (fs.read, fs.list, …) are excluded so that input
        file paths are never mistaken for produced deliverables.

        Final verification (verifier pass) is done by CompletionGate, not here.
        """
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        if not deliverables:
            return []

        successful_nodes = [
            n for n in graph.nodes.values()
            if n.status == NodeStatus.SUCCESS
            and n.capability_name in self._producer_skills
        ]
        if not successful_nodes:
            return list(deliverables)

        produced_exts: Set[str] = set()
        produced_paths: Set[str] = set()
        for node in successful_nodes:
            for v in (node.outputs or {}).values():
                if isinstance(v, str) and "." in v:
                    ext = v.rsplit(".", 1)[-1].lower()
                    produced_exts.add(ext)
                    produced_paths.add(v.lower())
                elif isinstance(v, dict):
                    path = v.get("path") or v.get("file_path") or ""
                    if path and "." in path:
                        ext = path.rsplit(".", 1)[-1].lower()
                        produced_exts.add(ext)
                        produced_paths.add(path.lower())
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict):
                            path = item.get("path") or item.get("file_path") or ""
                            if path and "." in path:
                                ext = path.rsplit(".", 1)[-1].lower()
                                produced_exts.add(ext)
                                produced_paths.add(path.lower())

            oc = (node.metadata or {}).get("output_contract")
            if oc:
                oc_list = oc if isinstance(oc, list) else [oc]
                for item in oc_list:
                    if isinstance(item, dict):
                        p = item.get("path", "")
                    else:
                        p = getattr(item, "path", "")
                    if p and "." in p:
                        produced_exts.add(p.rsplit(".", 1)[-1].lower())
                        produced_paths.add(p.lower())

        unsatisfied = []
        for d in deliverables:
            fmt = d.format.lower()
            if fmt not in produced_exts:
                unsatisfied.append(d)
        return unsatisfied

    def _node_covers(self, node: Any, sub_goal: str) -> bool:
        sg_lower = sub_goal.lower()
        skill = node.capability_name
        tags = self._skill_tags.get(skill, [skill])
        if any(t.lower() in sg_lower for t in tags):
            return True
        if skill in self._compute_skills:
            if not any(t.lower() in sg_lower for t in self._io_tags):
                return True
        # CJK keyword match in node outputs
        output_text = ""
        for v in (node.outputs or {}).values():
            if isinstance(v, str):
                output_text += v.lower()
            elif isinstance(v, dict):
                output_text += str(v).lower()
        cjk_words = re.findall(r'[\u4e00-\u9fff]{2,}', sg_lower)
        if cjk_words and any(w in output_text for w in cjk_words):
            return True
        return False

    # ── Terminal evidence short-circuit ─────────────────────────────────

    def check_terminal_evidence(
        self,
        graph: 'ExecutionGraph',
        sub_goals: List[str],
        env_context: Dict[str, Any],
    ) -> Optional[str]:
        """
        Runtime hard rule: if terminal evidence is present, return reason string
        (truthy → caller should break). Return None to continue.

        Conditions (ALL must hold):
        1. All sub-goals covered.
        2. keyword_overlap >= threshold between goal and last success output,
           OR "answer-produced pattern" matches (web.search ok + llm.fallback ok).
        3. No CONTINUE signals (unsatisfied deliverables, recent failure).
        4. For multi-step goals: at least N distinct skill types succeeded.

        Hard override: if ALL expected deliverable formats have been produced
        by succeeded nodes, short-circuit regardless of other conditions.

        Structured output override: when _required_outputs is present (from
        TaskExecutionPlan), use structured output checking instead of text-based
        sub-goal coverage.
        """
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        successful_nodes = [
            n for n in graph.nodes.values() if n.status == NodeStatus.SUCCESS
        ]
        if not successful_nodes:
            return None

        # ── Structured output check (TaskExecutionPlan path) ────────────
        _required_outputs = env_context.get("_required_outputs")
        if _required_outputs:
            unsatisfied = self._check_required_outputs(
                _required_outputs, successful_nodes, env_context,
            )
            if unsatisfied:
                logger.debug(
                    "[TerminalEvidence] _required_outputs unsatisfied: %s — continuing",
                    [o.get("output_id") for o in unsatisfied],
                )
                return None
            _failed_nodes = [
                n for n in graph.nodes.values() if n.status == NodeStatus.FAILED
            ]
            if _failed_nodes:
                logger.info(
                    "[TerminalEvidence] _required_outputs satisfied but %d "
                    "failed node(s) — not short-circuiting",
                    len(_failed_nodes),
                )
                return None
            return (
                f"all {len(_required_outputs)} required outputs produced "
                f"AND no failed nodes (structured plan verification)"
            )

        # ── Read-only early exit ────────────────────────────────────────
        # GUARD: Skip when running as a sub-phase (_phased_depth > 0).
        _ng = env_context.get("normalized_goal")
        _deliverables = getattr(_ng, "deliverables", None) if _ng else None
        _phased_depth = env_context.get("_phased_depth", 0)
        if not _deliverables and len(sub_goals) <= 1 and _phased_depth == 0:
            _succeeded_skills = {n.capability_name for n in successful_nodes}
            if _succeeded_skills and _succeeded_skills <= self._read_only_skills:
                # Any read-only skill that produced substantial text output
                # is sufficient evidence — no need to filter by tag type.
                # This covers search skills, answer skills, and any future
                # SAFE/READ skill that returns meaningful content.
                _has_substantial_output = False
                for n in successful_nodes:
                    _output = getattr(n, 'result', None) or getattr(n, 'outputs', None) or {}
                    _output_str = str(_output)
                    if len(_output_str) > self._cfg.meaningful_text_threshold:
                        _has_substantial_output = True
                        break
                if _has_substantial_output:
                    logger.info(
                        "[TerminalEvidence] Read-only early exit: "
                        "substantial output produced, no deliverables needed"
                    )
                    return (
                        "read-only early exit: substantial output available, "
                        "no blocking deliverables"
                    )

        # ── Hard override: deliverable-level short-circuit ──────────────
        _ng = env_context.get("normalized_goal")
        _deliverables = getattr(_ng, "deliverables", None) if _ng else None
        if _deliverables:
            unsatisfied = self.get_unsatisfied_deliverables(_deliverables, graph)
            if not unsatisfied:
                uncovered = self.get_uncovered_sub_goals(sub_goals, graph)
                if not uncovered:
                    # On-disk verification for file deliverables
                    _fmts = [d.format for d in _deliverables]
                    _session_ws = env_context.get("session_workspace_path")
                    _workspace = env_context.get("workspace_path")
                    if (
                        self._cfg.file_verification_enabled
                        and (_session_ws or _workspace)
                    ):
                        _produced = self._collect_produced_paths(successful_nodes)
                        _unverified: List[str] = []
                        for d in _deliverables:
                            fmt = d.format.lower()
                            _matched = [
                                p for p in _produced
                                if p.rsplit(".", 1)[-1].lower() == fmt
                            ]
                            _any_ok = False
                            for fp in _matched:
                                ok, reason = self._verify_file_on_disk(
                                    fp, fmt, _session_ws, _workspace,
                                )
                                if ok:
                                    _any_ok = True
                                    break
                                logger.debug(
                                    "[TerminalEvidence] Deliverable .%s verify failed: %s",
                                    fmt, reason,
                                )
                            if not _any_ok and fmt in self._cfg.artifact_extensions:
                                _unverified.append(fmt)
                        if _unverified:
                            logger.info(
                                "[TerminalEvidence] Deliverable formats %s claimed "
                                "but not verified on disk — continuing",
                                _unverified,
                            )
                            return None
                    logger.info(
                        f"[TerminalEvidence] Deliverable short-circuit: "
                        f"all formats produced ({_fmts})"
                    )
                    return f"all deliverables produced ({_fmts}), all sub-goals covered"

        # Condition 1
        uncovered = self.get_uncovered_sub_goals(sub_goals, graph)
        if uncovered:
            return None

        # Condition 3a: unsatisfied deliverables block exit
        if _deliverables:
            unsatisfied = self.get_unsatisfied_deliverables(_deliverables, graph)
            if unsatisfied:
                _fmts = [d.format for d in unsatisfied]
                logger.debug(
                    "[TerminalEvidence] Unsatisfied deliverables %s — continuing", _fmts
                )
                return None

        # ── Single-goal, no-deliverable short-circuit ───────────────────
        # Bug 3 fix: use _extract_local_goal to match connectors against
        # the phase-local objective only, NOT the full scoped_intent that
        # includes "Original user goal: ..." with parent connectors.
        local_goal = self._extract_local_goal(graph.goal)
        if (
            len(sub_goals) <= 1
            and not _deliverables
            and not self._multi_step_connectors_re.search(local_goal)
            and all(n.status == NodeStatus.SUCCESS for n in graph.nodes.values())
        ):
            _succeeded_skills = {n.capability_name for n in successful_nodes}
            if _succeeded_skills <= self._read_only_skills:
                logger.debug(
                    "[TerminalEvidence] Only read-only skills succeeded (%s) — "
                    "letting Planner decide", _succeeded_skills
                )
                return None

            # Key guard: if more than one node succeeded the task clearly
            # required multiple steps — do not short-circuit regardless of
            # what the goal text says. This handles cases like
            # "open notepad write date save" (no punctuation, no connectors)
            # where the user intended sequential actions.
            if len(successful_nodes) > 1:
                logger.debug(
                    "[TerminalEvidence] %d productive nodes succeeded — "
                    "treating as multi-step, not short-circuiting",
                    len(successful_nodes),
                )
                return None

            logger.info(
                "[TerminalEvidence] Single-goal no-deliverable short-circuit: "
                f"{len(successful_nodes)} node(s) all succeeded"
            )
            return (
                f"single sub-goal covered, no deliverables, "
                f"all {len(successful_nodes)} node(s) succeeded"
            )

        # Condition 4: multi-step goal guard
        # Bug 3 fix: match connectors against local_goal only
        if self._multi_step_connectors_re.search(local_goal):
            distinct_skills = {n.capability_name for n in successful_nodes}
            if len(distinct_skills) < self._cfg.multi_step_min_distinct_skills:
                logger.debug(
                    f"[TerminalEvidence] Multi-step goal but only {len(distinct_skills)} "
                    f"distinct skill(s) succeeded: {distinct_skills} — not short-circuiting"
                )
                return None

        # Condition 2a: keyword overlap
        last_success = successful_nodes[-1]
        keyword_overlap = self._keyword_overlap(graph.goal, last_success)

        # Condition 2b: answer-produced pattern
        answer_produced = self._answer_produced_pattern(successful_nodes)

        if keyword_overlap < self._cfg.keyword_overlap_threshold and not answer_produced:
            return None

        # Condition 3b: ANY failed node blocks short-circuit
        all_nodes = list(graph.nodes.values())
        failed_nodes = [n for n in all_nodes if n.status == NodeStatus.FAILED]
        if failed_nodes:
            logger.debug(
                "[TerminalEvidence] %d failed node(s) present — "
                "deferring to OutcomeReducer (not short-circuiting)",
                len(failed_nodes),
            )
            return None

        reason_parts = ["all sub-goals covered"]
        if answer_produced:
            reason_parts.append("answer-produced (web.search+llm.fallback)")
        else:
            reason_parts.append(f"keyword_overlap={keyword_overlap:.0%}")
        reason_parts.append("no CONTINUE signals")
        return ", ".join(reason_parts)

    def _keyword_overlap(self, goal: str, node: Any) -> float:
        """Compute keyword overlap ratio between goal and node output."""
        goal_lower = goal.lower()
        output_text = ""
        for v in (node.outputs or {}).values():
            if isinstance(v, str):
                output_text += v.lower()
            elif isinstance(v, dict):
                output_text += str(v).lower()
        goal_tokens = set(re.findall(r'[\w\u4e00-\u9fff]+', goal_lower)) - self._cfg.stopwords
        output_tokens = set(re.findall(r'[\w\u4e00-\u9fff]+', output_text))
        return len(goal_tokens & output_tokens) / max(len(goal_tokens), 1)

    def _answer_produced_pattern(self, successful_nodes: List[Any]) -> bool:
        """
        Answer-produced pattern: a "search" skill succeeded AND an "answer/reply"
        skill succeeded.  Detection is tag-based — no hardcoded skill names.
        """
        has_search = False
        has_answer = False
        from app.avatar.skills.registry import skill_registry
        for n in successful_nodes:
            tags = set(self._skill_tags.get(n.capability_name, []))
            if tags & skill_registry.SEARCH_TAGS:
                has_search = True
            if tags & skill_registry.ANSWER_TAGS:
                has_answer = True
            if has_search and has_answer:
                return True
        return False

    # ── Progress guard ──────────────────────────────────────────────────

    def check_progress(self, graph: 'ExecutionGraph') -> Optional[str]:
        """
        Detect "success but no progress" loops.

        After each execution round, compare the set of succeeded node IDs
        with the previous round. If no new successes for N consecutive rounds,
        return a reason string (truthy → caller should break).
        """
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        current_succeeded = {
            n.id for n in graph.nodes.values() if n.status == NodeStatus.SUCCESS
        }
        new_successes = current_succeeded - self._prev_succeeded_ids

        if not new_successes:
            self._no_progress_rounds += 1
            logger.info(
                f"[ProgressGuard] No new successes this round "
                f"({self._no_progress_rounds}/{self._cfg.max_no_progress_rounds})"
            )
            if self._no_progress_rounds >= self._cfg.max_no_progress_rounds:
                return (
                    f"{self._no_progress_rounds} consecutive rounds with no new "
                    f"successful nodes — forcing termination"
                )
        else:
            self._no_progress_rounds = 0

        self._prev_succeeded_ids = current_succeeded
        return None

    def reset(self) -> None:
        """Reset progress guard state for a new task."""
        self._prev_succeeded_ids = set()
        self._no_progress_rounds = 0

    # ── Structured output checking (TaskExecutionPlan) ──────────────

    @staticmethod
    def _collect_produced_paths(
        successful_nodes: List[Any],
    ) -> Set[str]:
        """Extract all file paths mentioned in succeeded node outputs.

        Returns a set of raw path strings (not lowered) so callers can
        resolve them against the filesystem.
        """
        paths: Set[str] = set()
        for node in successful_nodes:
            outputs = getattr(node, "outputs", None) or {}
            for v in outputs.values():
                if isinstance(v, str) and "." in v:
                    paths.add(v)
                elif isinstance(v, dict):
                    p = v.get("path") or v.get("file_path") or ""
                    if p and "." in p:
                        paths.add(p)
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, str) and "." in item:
                            paths.add(item)
                        elif isinstance(item, dict):
                            p = item.get("path") or item.get("file_path") or ""
                            if p and "." in p:
                                paths.add(p)
            # output_contract metadata
            oc = (getattr(node, "metadata", None) or {}).get("output_contract")
            if oc:
                for item in (oc if isinstance(oc, list) else [oc]):
                    p = item.get("path", "") if isinstance(item, dict) else getattr(item, "path", "")
                    if p and "." in p:
                        paths.add(p)
            # artifacts list (browser.run style)
            for art in outputs.get("artifacts", []):
                if isinstance(art, str) and "." in art:
                    paths.add(art)
        return paths

    def _resolve_file_path(
        self,
        raw_path: str,
        session_ws_path: Optional[str],
        workspace_path: Optional[str],
    ) -> Optional[Path]:
        """Try to resolve *raw_path* to an existing file on disk.

        Resolution order:
        1. Absolute path — use as-is.
        2. Relative to each configured search dir inside session workspace.
        3. Relative to session workspace root.
        4. Relative to user workspace root.
        """
        p = Path(raw_path)
        if p.is_absolute():
            return p if p.is_file() else None

        roots: List[Path] = []
        if session_ws_path:
            sw = Path(session_ws_path)
            for d in self._cfg.file_search_dirs:
                roots.append(sw / d)
            roots.append(sw)
        if workspace_path:
            roots.append(Path(workspace_path))

        # Strip common container prefixes that may leak into output paths
        stripped = raw_path
        for prefix in ("/workspace/output/", "/workspace/", "/session/output/", "/session/"):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):]
                break

        for root in roots:
            candidate = root / stripped
            if candidate.is_file():
                return candidate
            # Also try the original (un-stripped) relative path
            if stripped != raw_path:
                candidate2 = root / raw_path.lstrip("/")
                if candidate2.is_file():
                    return candidate2
        return None

    def _verify_file_on_disk(
        self,
        raw_path: str,
        expected_ext: Optional[str],
        session_ws_path: Optional[str],
        workspace_path: Optional[str],
    ) -> Tuple[bool, str]:
        """Verify a single file deliverable on disk.

        Checks:
        1. File exists
        2. Extension matches *expected_ext* (if provided)
        3. File size >= file_min_size_bytes

        Returns (ok, reason).
        """
        resolved = self._resolve_file_path(raw_path, session_ws_path, workspace_path)
        if resolved is None:
            return False, f"file not found: {raw_path}"

        if expected_ext:
            actual_ext = resolved.suffix.lstrip(".").lower()
            if actual_ext != expected_ext.lower():
                return False, (
                    f"extension mismatch: expected .{expected_ext}, "
                    f"got .{actual_ext} ({resolved.name})"
                )

        try:
            size = resolved.stat().st_size
        except OSError as exc:
            return False, f"cannot stat {resolved}: {exc}"

        if size < self._cfg.file_min_size_bytes:
            return False, (
                f"file too small: {resolved.name} is {size}B "
                f"(min {self._cfg.file_min_size_bytes}B)"
            )

        return True, f"verified: {resolved.name} ({size}B)"

    def _check_required_outputs(
        self,
        required_outputs: List[Dict[str, Any]],
        successful_nodes: List[Any],
        env_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Check which required outputs are NOT yet satisfied by succeeded nodes.

        Returns list of unsatisfied output specs. Empty list = all satisfied.

        When file_verification_enabled is True and session_workspace_path is
        available in *env_context*, file-type outputs are additionally checked
        for on-disk existence, correct extension, and minimum size.
        """
        produced_exts: Set[str] = set()
        produced_files: Set[str] = set()
        has_text_output = False

        for node in successful_nodes:
            outputs = getattr(node, "outputs", None) or {}
            for v in outputs.values():
                if isinstance(v, str):
                    if len(v) > self._cfg.meaningful_text_threshold:
                        has_text_output = True
                    if "." in v:
                        ext = v.rsplit(".", 1)[-1].lower()
                        produced_exts.add(ext)
                        produced_files.add(v)
                elif isinstance(v, dict):
                    path = v.get("path") or v.get("file_path") or ""
                    if path and "." in path:
                        produced_exts.add(path.rsplit(".", 1)[-1].lower())
                        produced_files.add(path)
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, str) and "." in item:
                            produced_exts.add(item.rsplit(".", 1)[-1].lower())
                            produced_files.add(item)
                        elif isinstance(item, dict):
                            p = item.get("path") or item.get("file_path") or ""
                            if p and "." in p:
                                produced_exts.add(p.rsplit(".", 1)[-1].lower())
                                produced_files.add(p)
            # Check artifacts (browser.run style)
            for art in outputs.get("artifacts", []):
                if isinstance(art, str) and "." in art:
                    produced_exts.add(art.rsplit(".", 1)[-1].lower())
                    produced_files.add(art)

        # ── Resolve env_context paths for on-disk verification ──────────
        _env = env_context or {}
        _session_ws = _env.get("session_workspace_path")
        _workspace = _env.get("workspace_path")
        _do_file_verify = (
            self._cfg.file_verification_enabled
            and (_session_ws or _workspace)
        )

        unsatisfied = []
        for o in required_outputs:
            o_type = o.get("type", "data")
            o_format = o.get("format")

            if o_type == "file" and o_format:
                if o_format.lower() not in produced_exts:
                    unsatisfied.append(o)
                    continue
                # Extension matched in node outputs — now verify on disk
                if _do_file_verify:
                    _matched_paths = [
                        f for f in produced_files
                        if f.rsplit(".", 1)[-1].lower() == o_format.lower()
                    ]
                    _any_verified = False
                    for fp in _matched_paths:
                        ok, reason = self._verify_file_on_disk(
                            fp, o_format, _session_ws, _workspace,
                        )
                        if ok:
                            _any_verified = True
                            logger.debug(
                                "[TerminalEvidence] File output verified: %s", reason,
                            )
                            break
                        logger.debug(
                            "[TerminalEvidence] File verification failed: %s", reason,
                        )
                    if not _any_verified:
                        logger.info(
                            "[TerminalEvidence] File output .%s claimed but "
                            "not verified on disk — marking unsatisfied",
                            o_format,
                        )
                        unsatisfied.append(o)
            elif o_type == "answer":
                if not has_text_output:
                    unsatisfied.append(o)
            elif o_type == "data":
                if o_format and o_format.lower() in produced_exts:
                    continue
                if has_text_output and not o_format:
                    continue
                if o_format and o_format.lower() not in produced_exts:
                    unsatisfied.append(o)
                elif not has_text_output:
                    unsatisfied.append(o)

        return unsatisfied
