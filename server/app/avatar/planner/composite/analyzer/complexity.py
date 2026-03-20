"""
ComplexityAnalyzer — LLM-based task complexity classification.

Design philosophy: NO hardcoded verb/connector/keyword/pattern enumeration.
Natural language is open-ended — regex heuristics always have false positives
and false negatives. The LLM IS the best complexity classifier.

Classification outputs:
- simple: single-goal task, planner handles in 1-3 steps
- template_batch: N homogeneous independent items (e.g. "write 5 poems")
- complex: multi-phase task requiring decomposition

Deterministic signals (no LLM needed):
- TaskDefinition with ≥3 homogeneous deliverables → template_batch
- TaskDefinition with ≥3 heterogeneous deliverables → complex

Everything else → LLM classify (or default simple if no LLM).

Entry points:
- classify_from_task_definition(task_def) — primary path (structured input)
- classify_from_text(intent) — fallback path (raw text)
- should_decompose(user_request) — legacy backward-compatible API
- is_complex_task(text) — legacy backward-compatible API
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class BatchParams:
    """Parameters for template_batch execution."""
    count: int
    template: str
    variables: List[str] = field(default_factory=list)
    source_type: str = ""  # "literal_count" / "collection_input" / "upstream_list"


@dataclass
class ComplexityResult:
    """Result of complexity classification."""
    task_type: str = "simple"  # "simple" / "template_batch" / "complex"
    detection_channel: str = "none"  # "language" / "data" / "both" / "llm" / "none"
    has_cross_item_dependency: bool = False
    batch_params: Optional[BatchParams] = None
    requires_decomposition: bool = False
    schema_version: str = "1.0.0"

    # Phased planning signals (populated by LLM for complex tasks)
    estimated_phases: int = 1
    phase_hints: List[str] = field(default_factory=list)

    # Legacy compat fields
    is_complex: bool = False
    connector_score: float = 0.0
    verb_count: int = 0
    segment_count: int = 0
    reason: str = ""


# ---------------------------------------------------------------------------
# ComplexityAnalyzer
# ---------------------------------------------------------------------------

class ComplexityAnalyzer:
    """Task complexity analyzer — LLM-first, no hardcoded heuristics.

    Deterministic signals (no LLM needed):
    - TaskDefinition with ≥3 homogeneous deliverables → template_batch
    - TaskDefinition with ≥3 heterogeneous deliverables → complex

    Everything else → single LLM call (~200 tokens).
    Without LLM → default simple (planner self-regulates via ReAct loop).
    """

    def __init__(self, embedding_service: Optional[Any] = None, llm_client: Optional[Any] = None):
        self._embedding_service = embedding_service
        self._llm_client = llm_client

    # ------------------------------------------------------------------
    # Primary entry: structured TaskDefinition
    # ------------------------------------------------------------------

    def classify_from_task_definition(self, task_def: Any) -> ComplexityResult:
        """Classify from structured TaskDefinition.

        Uses deliverables count/structure first, then falls back to LLM.
        """
        objective_text = ""
        if hasattr(task_def, "objective"):
            obj = task_def.objective
            objective_text = getattr(obj, "text", str(obj)) if obj else ""

        deliverables = getattr(task_def, "deliverables", []) or []
        num_deliverables = len(deliverables)

        # Deterministic: multiple deliverables → batch or complex
        if num_deliverables >= 3:
            names = [
                getattr(d, "name", "") or getattr(d, "text", "") or str(d)
                for d in deliverables
            ]
            if self._deliverables_are_homogeneous(names):
                return ComplexityResult(
                    task_type="template_batch",
                    detection_channel="data",
                    batch_params=BatchParams(
                        count=num_deliverables,
                        template=objective_text,
                        source_type="structured_deliverables",
                    ),
                    requires_decomposition=False,
                    is_complex=True,
                    reason=f"template_batch from {num_deliverables} homogeneous deliverables",
                )
            return ComplexityResult(
                task_type="complex",
                detection_channel="data",
                requires_decomposition=True,
                is_complex=True,
                estimated_phases=num_deliverables,
                phase_hints=names,
                reason=f"complex: {num_deliverables} heterogeneous deliverables",
            )

        # Fall back to LLM-based classification
        return self._classify_via_llm(objective_text)

    @staticmethod
    def _deliverables_are_homogeneous(names: List[str]) -> bool:
        """Check if deliverable names suggest homogeneous items."""
        if not names or len(names) < 2:
            return False
        if all(len(n) <= 3 for n in names):
            return True
        prefix = os.path.commonprefix(names)
        if len(prefix) >= 2:
            return True
        return False

    # ------------------------------------------------------------------
    # Fallback entry: raw text
    # ------------------------------------------------------------------

    def classify_from_text(self, intent: str) -> ComplexityResult:
        """Classify from raw text — delegates entirely to LLM."""
        return self._classify_via_llm(intent)

    # ------------------------------------------------------------------
    # Core: LLM-based classification
    # ------------------------------------------------------------------

    # Phase hint blocklist: overly abstract / methodology-oriented hints
    _ABSTRACT_HINT_BLOCKLIST = frozenset({
        "需求分析", "系统设计", "详细设计", "测试", "部署", "维护",
        "planning", "design", "testing", "deployment", "maintenance",
        "analysis", "review", "setup", "init", "cleanup", "finish",
    })

    def _classify_via_llm(self, text: str) -> ComplexityResult:
        """Single LLM call for all classification.

        The LLM decides: simple / template_batch / complex.
        For template_batch, it also extracts count.
        Without LLM → default simple.
        """
        if not text:
            return ComplexityResult(task_type="simple", reason="empty input")

        if self._llm_client is None:
            return ComplexityResult(
                task_type="simple",
                reason="no LLM available, default simple (planner self-regulates)",
            )

        # Smart truncation: front goal (700 chars) + tail constraints/deliverables (300 chars)
        if len(text) > 1000:
            truncated = text[:700] + "\n...\n" + text[-300:]
        else:
            truncated = text

        prompt = (
            "Classify this task as exactly one of: simple, template_batch, complex\n\n"
            "Definitions:\n"
            "- simple: a single goal achievable in 1-3 steps (e.g. 'open a file', 'translate this text', 'write a poem')\n"
            "- template_batch: N independent homogeneous items from one template "
            "(e.g. 'write 5 poems', 'generate 10 test cases', 'create reports for each department'). "
            "Each item is independent and uses the same pattern.\n"
            "- complex: multi-phase task needing planning and decomposition "
            "(e.g. 'build an e-commerce system', 'read file then analyze then generate report')\n\n"
            "## Few-shot examples\n\n"
            "Task: 帮我写一首关于春天的诗\n"
            "type: simple\ncount: 0\nphases: 1\nphase_hints:\n\n"
            "Task: 为公司5个部门各生成一份月度报告\n"
            "type: template_batch\ncount: 5\nphases: 1\nphase_hints:\n\n"
            "Task: 搭建一个带用户认证的博客系统，包含文章管理和评论功能\n"
            "type: complex\ncount: 0\nphases: 3\n"
            "phase_hints: 搭建用户认证与数据库模型, 实现文章CRUD与API接口, 实现评论功能与前端页面\n\n"
            "## Constraints\n"
            "- phase_hints MUST be concrete deliverable-oriented descriptions, NOT abstract methodology "
            "(bad: '需求分析, 系统设计, 测试'; good: '搭建数据库模型, 实现API接口, 构建前端页面')\n"
            "- phases must be between 1 and 10\n"
            "- type must be exactly one of: simple, template_batch, complex\n\n"
            f"Task: {truncated}\n\n"
            "Reply in this exact format (nothing else):\n"
            "type: <simple|template_batch|complex>\n"
            "count: <number if template_batch, 0 otherwise>\n"
            "phases: <number of phases if complex, 1 otherwise>\n"
            "phase_hints: <comma-separated short phase descriptions if complex, empty otherwise>"
        )
        try:
            raw = self._llm_client.call(prompt).strip().lower()
            return self._parse_llm_response(raw, text)
        except Exception as e:
            logger.debug("[ComplexityAnalyzer] LLM classification failed: %s", e)
            return ComplexityResult(
                task_type="simple",
                reason=f"LLM call failed ({e}), default simple",
            )

    @staticmethod
    def _parse_llm_response(raw: str, original_text: str) -> ComplexityResult:
        """Parse LLM classification response with post-processing validation."""
        import re

        _VALID_TYPES = {"simple", "template_batch", "complex"}

        # Extract type — strict matching on "type:" line first
        task_type = "simple"
        type_match = re.search(r'type:\s*(simple|template_batch|complex)', raw)
        if type_match:
            task_type = type_match.group(1)
        elif "template_batch" in raw:
            task_type = "template_batch"
        elif "complex" in raw:
            task_type = "complex"
        elif "simple" in raw:
            task_type = "simple"
        else:
            logger.debug("[ComplexityAnalyzer] LLM returned unexpected: %s", raw)
            return ComplexityResult(
                task_type="simple",
                reason="LLM returned unrecognized output, default simple",
            )

        # Validate task_type
        if task_type not in _VALID_TYPES:
            task_type = "simple"

        if task_type == "template_batch":
            count = 0
            count_match = re.search(r'count:\s*(\d+)', raw)
            if count_match:
                count = int(count_match.group(1))
            return ComplexityResult(
                task_type="template_batch",
                detection_channel="llm",
                batch_params=BatchParams(
                    count=count,
                    template=original_text,
                    source_type="llm_classified",
                ),
                requires_decomposition=False,
                is_complex=True,
                reason=f"LLM classified as template_batch (count={count})",
            )

        if task_type == "complex":
            # Extract and validate phase count (clamp to 1-10)
            estimated_phases = 1
            phase_hints: List[str] = []
            phases_match = re.search(r'phases:\s*(\d+)', raw)
            if phases_match:
                estimated_phases = max(1, min(10, int(phases_match.group(1))))
            hints_match = re.search(r'phase_hints:\s*(.+)', raw)
            if hints_match:
                hints_raw = hints_match.group(1).strip()
                if hints_raw and hints_raw.lower() not in ("empty", "none", "n/a", ""):
                    phase_hints = [h.strip() for h in hints_raw.split(",") if h.strip()]

            # Post-processing: validate phase_hints quality
            phase_hints = ComplexityAnalyzer._validate_phase_hints(phase_hints)

            # If all hints were rejected, downgrade to simple
            if estimated_phases >= 3 and not phase_hints:
                logger.debug(
                    "[ComplexityAnalyzer] All phase_hints rejected as abstract, "
                    "downgrading complex → simple"
                )
                return ComplexityResult(
                    task_type="simple",
                    detection_channel="llm",
                    reason="LLM classified as complex but phase_hints too abstract, downgraded to simple",
                )

            return ComplexityResult(
                task_type="complex",
                detection_channel="llm",
                requires_decomposition=True,
                is_complex=True,
                estimated_phases=estimated_phases,
                phase_hints=phase_hints,
                reason=f"LLM classified as complex (phases={estimated_phases})",
            )

        return ComplexityResult(
            task_type="simple",
            detection_channel="llm",
            reason="LLM classified as simple",
        )

    @classmethod
    def _validate_phase_hints(cls, hints: List[str]) -> List[str]:
        """Filter out overly abstract / methodology-oriented phase hints.

        Returns only concrete, deliverable-oriented hints.
        Hints shorter than 4 chars or matching the blocklist are rejected.
        """
        valid = []
        for h in hints:
            if len(h) < 4:
                continue
            if h.lower() in cls._ABSTRACT_HINT_BLOCKLIST:
                continue
            valid.append(h)
        return valid

    # ------------------------------------------------------------------
    # Legacy backward-compatible API
    # ------------------------------------------------------------------

    def is_complex_task(self, text: str) -> ComplexityResult:
        """Legacy API: returns ComplexityResult with is_complex flag."""
        return self.classify_from_text(text)

    def should_decompose(self, user_request: str, intent: Any = None) -> bool:
        """Legacy API: returns True if task needs decomposition."""
        result = self.classify_from_text(user_request)
        if result.requires_decomposition:
            return True
        if result.task_type != "simple":
            return False  # template_batch — no decomposition

        # Intent metadata
        if intent and hasattr(intent, "metadata"):
            if intent.metadata.get("complexity") == "high":
                return True

        return False
