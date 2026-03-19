"""
TaskDefinition data models.

Provides the unified SourcedTextItem base model with source tracking
(extracted / inferred / unknown) and specialized subtypes for
deliverables, assumptions, and risks.

TaskDefinitionEngine (parse/update logic) will be added in Task 8.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class FieldSource(str, Enum):
    """Origin of a parsed field value."""
    EXTRACTED = "extracted"   # directly extracted from user input
    INFERRED = "inferred"     # system-inferred
    UNKNOWN = "unknown"       # cannot determine, explicit placeholder


@dataclass
class SourcedTextItem:
    """Unified text entry with source tracking.

    All TaskDefinition entries (objective, constraints, acceptance_criteria, etc.)
    use this model to ensure consistent serialization, update logic, UI/trace
    display, and incremental update field_path handling.

    Specialized subtypes (Deliverable, Assumption, Risk) extend this base
    with domain-specific fields.
    """
    text: str = ""
    source: FieldSource = FieldSource.UNKNOWN
    source_text_excerpt: Optional[str] = None  # only set when source == EXTRACTED


@dataclass
class Deliverable(SourcedTextItem):
    """A concrete deliverable produced by the task."""
    name: str = ""
    type: str = ""  # "file" / "data" / "report" / "artifact"
    description: str = ""


@dataclass
class Assumption(SourcedTextItem):
    """An assumption made during task understanding."""
    description: str = ""
    confidence_level: str = "medium"  # "high" / "medium" / "low"


@dataclass
class Risk(SourcedTextItem):
    """A risk identified during task understanding."""
    description: str = ""
    severity: str = "medium"  # "high" / "medium" / "low"
    mitigation: str = ""


@dataclass
class TaskDefinition:
    """Structured task definition produced by TaskDefinitionEngine.

    Every field carries source provenance so downstream components
    (ClarificationEngine, ComplexityAnalyzer, PhasedPlanner) can
    make informed decisions based on confidence levels.
    """
    objective: SourcedTextItem = field(
        default_factory=lambda: SourcedTextItem(source=FieldSource.EXTRACTED),
    )
    deliverables: List[Deliverable] = field(default_factory=list)
    constraints: List[SourcedTextItem] = field(default_factory=list)
    assumptions: List[Assumption] = field(default_factory=list)
    risks: List[Risk] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    acceptance_criteria: List[SourcedTextItem] = field(default_factory=list)
    schema_version: str = "1.0.0"


import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class TaskDefinitionEngine:
    """Structured task definition parser.

    parse() uses an LLM extractor to produce a TaskDefinition from raw text.
    Unit tests should inject a stubbed extractor via the constructor.

    Usage::

        engine = TaskDefinitionEngine(extractor=my_llm_extractor)
        task_def = await engine.parse("生成5首唐诗")
    """

    def __init__(self, extractor: Optional[Callable] = None) -> None:
        """
        Args:
            extractor: async callable(user_request: str) -> dict
                       Returns a dict matching TaskDefinition fields.
                       If None, a default no-op extractor is used.
        """
        self._extractor = extractor

    async def parse(self, user_request: str) -> TaskDefinition:
        """Parse user request into a structured TaskDefinition.

        Phase 1: LLM structured extraction (via extractor)
        Phase 2: Post-processing validation
        """
        raw = {}
        if self._extractor is not None:
            try:
                raw = await self._extractor(user_request)
                if not isinstance(raw, dict):
                    raw = {}
            except Exception as e:
                logger.warning("TaskDefinitionEngine extractor failed: %s", e)
                raw = {}

        task_def = self._build_from_raw(raw, user_request)
        self._post_process(task_def)
        return task_def

    def update(
        self,
        task_def: TaskDefinition,
        field_path: str,
        new_value: Any,
        new_source: FieldSource,
        new_excerpt: Optional[str] = None,
    ) -> TaskDefinition:
        """Incremental update: update a single entry by field_path.

        Supports paths like "objective", "deliverables[0]", "constraints[1]".
        """
        parts = field_path.replace("]", "").split("[")
        attr_name = parts[0]

        if attr_name == "objective":
            task_def.objective = SourcedTextItem(
                text=str(new_value),
                source=new_source,
                source_text_excerpt=new_excerpt,
            )
            return task_def

        container = getattr(task_def, attr_name, None)
        if container is None or not isinstance(container, list):
            logger.warning("Unknown field_path: %s", field_path)
            return task_def

        if len(parts) > 1:
            try:
                idx = int(parts[1])
                if 0 <= idx < len(container):
                    item = container[idx]
                    item.text = str(new_value)
                    item.source = new_source
                    item.source_text_excerpt = new_excerpt
            except (ValueError, IndexError):
                logger.warning("Invalid index in field_path: %s", field_path)

        return task_def

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_from_raw(raw: dict, user_request: str) -> TaskDefinition:
        """Build TaskDefinition from extractor output dict."""
        objective_raw = raw.get("objective", {})
        if isinstance(objective_raw, str):
            objective_raw = {"text": objective_raw, "source": "extracted"}

        objective = SourcedTextItem(
            text=objective_raw.get("text", user_request),
            source=FieldSource(objective_raw.get("source", "extracted")),
            source_text_excerpt=objective_raw.get("source_text_excerpt"),
        )

        deliverables = []
        for d in raw.get("deliverables", []):
            if isinstance(d, str):
                d = {"text": d}
            deliverables.append(Deliverable(
                text=d.get("text", ""),
                source=FieldSource(d.get("source", "inferred")),
                source_text_excerpt=d.get("source_text_excerpt"),
                name=d.get("name", ""),
                type=d.get("type", ""),
                description=d.get("description", ""),
            ))

        constraints = []
        for c in raw.get("constraints", []):
            if isinstance(c, str):
                c = {"text": c}
            constraints.append(SourcedTextItem(
                text=c.get("text", ""),
                source=FieldSource(c.get("source", "inferred")),
                source_text_excerpt=c.get("source_text_excerpt"),
            ))

        assumptions = []
        for a in raw.get("assumptions", []):
            if isinstance(a, str):
                a = {"text": a}
            assumptions.append(Assumption(
                text=a.get("text", ""),
                source=FieldSource(a.get("source", "inferred")),
                source_text_excerpt=a.get("source_text_excerpt"),
                description=a.get("description", ""),
                confidence_level=a.get("confidence_level", "medium"),
            ))

        risks = []
        for r in raw.get("risks", []):
            if isinstance(r, str):
                r = {"text": r}
            risks.append(Risk(
                text=r.get("text", ""),
                source=FieldSource(r.get("source", "inferred")),
                source_text_excerpt=r.get("source_text_excerpt"),
                description=r.get("description", ""),
                severity=r.get("severity", "medium"),
                mitigation=r.get("mitigation", ""),
            ))

        return TaskDefinition(
            objective=objective,
            deliverables=deliverables,
            constraints=constraints,
            assumptions=assumptions,
            risks=risks,
            open_questions=raw.get("open_questions", []),
            acceptance_criteria=[
                SourcedTextItem(
                    text=ac.get("text", "") if isinstance(ac, dict) else str(ac),
                    source=FieldSource(ac.get("source", "inferred")) if isinstance(ac, dict) else FieldSource.INFERRED,
                    source_text_excerpt=ac.get("source_text_excerpt") if isinstance(ac, dict) else None,
                )
                for ac in raw.get("acceptance_criteria", [])
            ],
        )

    @staticmethod
    def _post_process(task_def: TaskDefinition) -> None:
        """Post-processing validation.

        - objective must be extracted, else warning
        - unknown items generate open_questions
        - low-confidence assumptions added to open_questions
        - high-severity risks flag ApprovalGate (via marker in open_questions)
        """
        # Objective validation
        if task_def.objective.source != FieldSource.EXTRACTED:
            logger.warning("TaskDefinition objective is not extracted (source=%s)", task_def.objective.source)

        # Unknown items → open_questions
        all_items = (
            task_def.constraints
            + [d for d in task_def.deliverables]
            + task_def.acceptance_criteria
        )
        for item in all_items:
            if item.source == FieldSource.UNKNOWN and item.text:
                q = f"[unknown] {item.text}"
                if q not in task_def.open_questions:
                    task_def.open_questions.append(q)

        # Low-confidence assumptions → open_questions
        for assumption in task_def.assumptions:
            if assumption.confidence_level == "low" and assumption.text:
                q = f"[low-confidence assumption] {assumption.text}"
                if q not in task_def.open_questions:
                    task_def.open_questions.append(q)

        # High-severity risks → flag for ApprovalGate
        for risk in task_def.risks:
            if risk.severity == "high" and risk.text:
                q = f"[high-risk: requires approval] {risk.text}"
                if q not in task_def.open_questions:
                    task_def.open_questions.append(q)
