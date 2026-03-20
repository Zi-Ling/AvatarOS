"""
GoalTracker — Goal decomposition, coverage detection, and terminal evidence.

Extracted from GraphController. Provides:
- Goal decomposition into sub-goals (regex, no LLM)
- Sub-goal coverage checking against succeeded nodes
- Terminal evidence short-circuit (runtime hard rule, not Planner-dependent)
- Progress guard (detect "success but no progress" loops)
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, Set, TYPE_CHECKING
import logging
import re

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph

logger = logging.getLogger(__name__)


class GoalTracker:
    """
    Framework-level goal tracking with zero LLM calls.

    Responsibilities:
    1. Decompose goal into sub-goals.
    2. Check which sub-goals are covered by succeeded nodes.
    3. Terminal evidence short-circuit — hard rule before each Planner call.
    4. Progress guard — detect consecutive rounds with no new side effects.
    """

    # ── Goal split pattern ──────────────────────────────────────────────
    # Chinese text often uses punctuation (，、；) instead of spaces before
    # conjunctions.  The boundary must support: "，然后", "并保存，然后",
    # "A接着B" (zero-width CJK boundary), as well as whitespace-delimited English.
    _GOAL_SPLIT_PATTERN = re.compile(
        r'(?:[\s，,、;；。]+|(?<=[\u4e00-\u9fff])|(?<=\w))'  # leading: punct / after CJK / after word char
        r'(?:并且|然后|接着|之后|完成后'                       # Chinese conjunctions (NOT bare 并/再 — too ambiguous)
        r'|and\s+then|then\s+also|after\s+that|additionally)' # English conjunctions
        r'(?:[\s，,、;；]+|(?=[\u4e00-\u9fff])|(?=\w))',      # trailing: punct / before CJK / before word char
        re.IGNORECASE,
    )

    # ── Skill semantic tags ─────────────────────────────────────────────
    COMPUTE_SKILLS: Set[str] = {"python.run", "python.eval", "shell.run"}

    IO_KEYWORDS: Set[str] = {
        "保存", "写入", "写到", "存储", "save", "write", "保存到",
        "读取", "下载", "发送", "上传", "fetch", "download", "send", "upload",
    }

    SKILL_TAGS: Dict[str, List[str]] = {
        "fs.write":          ["save", "write", "file", "保存", "写入", "文件", "存储"],
        "fs.read":           ["read", "open", "load", "读取", "打开"],
        "fs.list":           ["list", "ls", "dir", "列出", "目录"],
        "fs.delete":         ["delete", "remove", "删除"],
        "fs.copy":           ["copy", "复制"],
        "fs.move":           ["move", "rename", "移动", "重命名"],
        "python.run":        ["run", "execute", "compute", "calculate", "generate",
                              "运行", "执行", "计算", "生成"],
        "net.get":           ["fetch", "get", "download", "request", "获取", "下载", "请求"],
        "net.post":          ["post", "send", "submit", "发送", "提交"],
        "browser.open":      ["open", "browse", "visit", "打开", "浏览", "访问"],
        "computer.app.launch": ["launch", "open", "start", "启动", "打开"],
        "memory.store":      ["remember", "store", "记住", "存储"],
        "memory.retrieve":   ["recall", "retrieve", "remember", "回忆", "检索"],
        "web.search":        ["search", "搜索", "查找", "查询", "检索", "find"],
    }

    _STOPWORDS: Set[str] = {
        "the", "a", "an", "is", "are", "in", "on", "at", "to", "of",
        "and", "or", "for", "with", "by", "from", "that", "this",
        "请", "帮我", "我要", "一下", "所有", "的", "了", "在", "把",
        "并", "然后", "接着", "之后",
    }

    # ── Progress guard state ────────────────────────────────────────────
    # Tracks the set of succeeded node IDs at the end of each round.
    # If the set doesn't grow for N consecutive rounds, we declare "no progress".
    _MAX_NO_PROGRESS_ROUNDS = 2

    def __init__(self) -> None:
        self._prev_succeeded_ids: Set[str] = set()
        self._no_progress_rounds: int = 0

    # ── Goal decomposition ──────────────────────────────────────────────

    # ── Complex goal heuristic signals ────────────────────────────────
    _HIGH_LEVEL_VERBS = re.compile(
        r'翻译|生成|合并|统计|绘图|导出|保存|转换|下载|上传|发送|分析|创建|编写',
    )
    _OUTPUT_TYPE_PATTERN = re.compile(
        r'\b(?:docx|pptx|xlsx|png|jpg|pdf|csv|json|txt|md|html|xml)\b',
        re.IGNORECASE,
    )

    # ── Chinese conversational prefix stripping ───────────────────────
    # User instructions often start with conversational filler that adds
    # noise to sub-goal coverage matching (e.g. "老板说要中文的简历 你把原先的").
    # We strip these prefixes AFTER splitting so each sub-goal is cleaner.
    _CJK_PREFIX_PATTERN = re.compile(
        r'^(?:老板说|老板要|他说|她说|你|帮我|请你?|我要|我想|把)'
        r'(?:要|说|把|将|先|再|去)?'
        r'(?:[\s，,、]*)'
        r'(?:原先的?|之前的?|现有的?|那个)?'
        r'[\s，,、]*',
    )

    def decompose_goal(self, goal: str) -> List[str]:
        """Split goal into sub-goals. Single-clause goals return [goal]."""
        parts = self._GOAL_SPLIT_PATTERN.split(goal)
        sub_goals = [p.strip() for p in parts if p and p.strip()]
        result = sub_goals if len(sub_goals) > 1 else [goal]

        # ── Strip conversational prefixes from each sub-goal (Fix 4) ────
        if len(result) > 1:
            cleaned = []
            for sg in result:
                stripped = self._CJK_PREFIX_PATTERN.sub('', sg).strip()
                # Only use stripped version if it still has meaningful content
                cleaned.append(stripped if len(stripped) >= 2 else sg)
            result = cleaned

        # ── Lightweight complex-goal detection (observe only) ───────────
        if len(result) == 1:
            verb_count = len(self._HIGH_LEVEL_VERBS.findall(goal))
            output_types = set(self._OUTPUT_TYPE_PATTERN.findall(goal.lower()))
            if verb_count >= 2 or len(output_types) >= 2:
                logger.info(
                    f"[GoalTracker] complex_goal_suspected=True "
                    f"(verbs={verb_count}, output_types={output_types}) "
                    f"but regex produced 1 segment — goal: {goal!r}"
                )

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
        succeeded node wrote a file whose extension matches the deliverable format.
        Final verification (verifier pass) is done by CompletionGate, not here.
        """
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        if not deliverables:
            return []

        successful_nodes = [
            n for n in graph.nodes.values() if n.status == NodeStatus.SUCCESS
        ]
        if not successful_nodes:
            return list(deliverables)

        # Collect all output paths from succeeded nodes
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

            # Also check output_contract in metadata
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
        tags = self.SKILL_TAGS.get(skill, [skill])
        if any(t.lower() in sg_lower for t in tags):
            return True
        if skill in self.COMPUTE_SKILLS:
            if not any(kw in sg_lower for kw in self.IO_KEYWORDS):
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

    # ── Multi-step intent keywords ─────────────────────────────────────
    # When the goal contains these, a single step's keyword overlap is
    # insufficient — we need evidence that ALL phases have executed.
    _MULTI_STEP_CONNECTORS = re.compile(
        r'(?:然后|接着|之后|再|并|转换|转为|转成|改为|变为|变成'
        r'|then|after that|and then|convert|transform)',
        re.IGNORECASE,
    )

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
        2. keyword_overlap >= 0.5 between goal and last success output,
           OR "answer-produced pattern" matches (web.search ok + llm.fallback ok).
        3. No CONTINUE signals (missing write, recent failure).
        4. For multi-step goals: at least 2 distinct skill types succeeded.

        Hard override: if ALL expected deliverable formats have been produced
        by succeeded nodes, short-circuit regardless of other conditions.
        This prevents the Planner from adding unnecessary verification steps
        after all files are already written.
        """
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        successful_nodes = [
            n for n in graph.nodes.values() if n.status == NodeStatus.SUCCESS
        ]
        if not successful_nodes:
            return None

        # ── Hard override: deliverable-level short-circuit ──────────────
        # If all expected deliverable formats are produced, the task is done
        # regardless of whether Planner has said FINISH. This is a hard
        # constraint that doesn't depend on prompt engineering.
        _ng = env_context.get("normalized_goal")
        _deliverables = getattr(_ng, "deliverables", None) if _ng else None
        if _deliverables:
            unsatisfied = self.get_unsatisfied_deliverables(_deliverables, graph)
            if not unsatisfied:
                # Also require sub-goal coverage to avoid premature exit
                uncovered = self.get_uncovered_sub_goals(sub_goals, graph)
                if not uncovered:
                    _fmts = [d.format for d in _deliverables]
                    logger.info(
                        f"[TerminalEvidence] Deliverable short-circuit: "
                        f"all formats produced ({_fmts})"
                    )
                    return f"all deliverables produced ({_fmts}), all sub-goals covered"

        # Condition 1
        uncovered = self.get_uncovered_sub_goals(sub_goals, graph)
        if uncovered:
            return None

        # ── Single-goal, no-deliverable short-circuit ───────────────────
        # For simple tasks (e.g. "计算素数", "生成随机数") where:
        #   - Only 1 sub-goal (already covered above)
        #   - No deliverables expected
        #   - No multi-step connectors in goal
        #   - All nodes succeeded (no failures to recover from)
        # → Short-circuit without keyword overlap check.
        # This saves a full planner call (~9k tokens) for trivial tasks
        # where keyword overlap between Chinese goal and code output is low.
        if (
            len(sub_goals) <= 1
            and not _deliverables
            and not self._MULTI_STEP_CONNECTORS.search(graph.goal)
            and all(n.status == NodeStatus.SUCCESS for n in graph.nodes.values())
        ):
            logger.info(
                "[TerminalEvidence] Single-goal no-deliverable short-circuit: "
                f"{len(successful_nodes)} node(s) all succeeded"
            )
            return (
                f"single sub-goal covered, no deliverables, "
                f"all {len(successful_nodes)} node(s) succeeded"
            )

        # Condition 4: multi-step goal guard
        # If the goal contains multi-step connectors, require at least 2
        # distinct skill types to have succeeded. This prevents short-circuit
        # after only the first phase (e.g. download) when a second phase
        # (e.g. convert to grayscale) hasn't executed yet.
        goal_lower = graph.goal.lower()
        if self._MULTI_STEP_CONNECTORS.search(graph.goal):
            distinct_skills = {n.capability_name for n in successful_nodes}
            if len(distinct_skills) < 2:
                logger.debug(
                    f"[TerminalEvidence] Multi-step goal but only {len(distinct_skills)} "
                    f"distinct skill(s) succeeded: {distinct_skills} — not short-circuiting"
                )
                return None

        # Condition 2a: keyword overlap
        last_success = successful_nodes[-1]
        keyword_overlap = self._keyword_overlap(graph.goal, last_success)

        # Condition 2b: answer-produced pattern
        # web.search succeeded + llm.fallback succeeded → info-seeking goal is answered
        answer_produced = self._answer_produced_pattern(successful_nodes)

        if keyword_overlap < 0.5 and not answer_produced:
            return None

        # Condition 3: no CONTINUE signals

        # 3a: write intent without write success
        _WRITE_INTENT_KW = {
            "写入", "写到", "写文件", "创建文件", "保存", "存储", "生成文件",
            "write", "create file", "save file", "output file",
        }
        _WRITE_SKILLS = {"fs.write", "fs.copy"}
        if any(kw in goal_lower for kw in _WRITE_INTENT_KW):
            if not any(
                n.capability_name in _WRITE_SKILLS and n.status == NodeStatus.SUCCESS
                for n in graph.nodes.values()
            ):
                return None

        # 3b: last node failed
        all_nodes = list(graph.nodes.values())
        if all_nodes and all_nodes[-1].status == NodeStatus.FAILED:
            return None

        reason_parts = [f"all sub-goals covered"]
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
        goal_tokens = set(re.findall(r'[\w\u4e00-\u9fff]+', goal_lower)) - self._STOPWORDS
        output_tokens = set(re.findall(r'[\w\u4e00-\u9fff]+', output_text))
        return len(goal_tokens & output_tokens) / max(len(goal_tokens), 1)

    @staticmethod
    def _answer_produced_pattern(successful_nodes: List[Any]) -> bool:
        """
        Answer-produced pattern: web.search succeeded AND llm.fallback succeeded.
        This covers info-seeking goals where keyword overlap between Chinese goal
        and English LLM output is low, but the task is semantically complete.
        """
        skills = {n.capability_name for n in successful_nodes}
        return "web.search" in skills and "llm.fallback" in skills

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
                f"({self._no_progress_rounds}/{self._MAX_NO_PROGRESS_ROUNDS})"
            )
            if self._no_progress_rounds >= self._MAX_NO_PROGRESS_ROUNDS:
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
