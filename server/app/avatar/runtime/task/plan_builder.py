"""
TaskExecutionPlanBuilder — LLM-based construction of TaskExecutionPlan.

Takes TaskDefinition + ComplexityResult as input, produces a structured
TaskExecutionPlan with SubGoalUnits, RequiredOutputs, SkillHints, and
dependency edges.

Design: single LLM call with structured JSON output. Falls back to
a deterministic builder (from ComplexityResult.phase_hints) if LLM fails.

MVP scope: LLM builder + deterministic fallback. No caching, no
incremental re-planning.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from .execution_plan import (
    OutputStatus,
    PlanStatus,
    RequiredOutput,
    SkillHint,
    SubGoalUnit,
    TaskExecutionPlan,
    UnitStatus,
)

logger = logging.getLogger(__name__)


# ── Default LLM prompt (defined before PlanBuilderConfig so it can
#    be used as a field default) ─────────────────────────────────────

_DEFAULT_BUILD_PROMPT: str = """You are a task execution planner. Given a user's goal, decompose it into
ordered sub-goals with explicit outputs and dependencies.

## Input
User goal: {goal}
Task kind: {task_kind}
Complexity hints: {phase_hints}
Deliverables: {deliverables}

## Task Kind Constraint
The task has been classified as "{task_kind}". You MUST stay within this category:
- desktop_control: operate existing desktop apps/windows/mouse/keyboard. Do NOT write code to build new software.
- app_usage: use existing applications to accomplish the task. Do NOT develop new applications.
- software_build: write/develop/build software code.
- information_query: search/query/explain information. Do NOT execute actions.
- file_operation: read/write/convert/organize files.
- data_analysis: analyze/visualize/compute data.
- continuous_loop: scheduled/repeating/long-running control tasks.
- general: no specific constraint.

If the task kind is "desktop_control" or "app_usage", you are FORBIDDEN from generating
sub-goals that involve writing application code, building software, or developing programs.

If the task kind is "continuous_loop", you MUST follow these rules:
- Do NOT create a separate sub-goal for "setting up a timer/loop/schedule". The runtime handles repetition automatically.
- Do NOT use python.run to implement timers, loops, or sleep-based scheduling. Sandbox containers have strict timeouts.
- Plan ONLY the concrete actions to be performed (e.g. "open app", "scroll up"). Each action is a single sub-goal.
- The runtime scheduling system will call these actions repeatedly at the user-specified interval.

## Output format
Return a JSON array of sub-goal objects. Each object:
{{
  "unit_id": "sg_0",
  "objective": "concise sub-goal description",
  "unit_type": "desktop_control|code_generation|data_retrieval|file_production|analysis|configuration|verification|general",
  "required_outputs": [
    {{
      "output_id": "unique_id",
      "output_type": "file|data|answer",
      "description": "what this output is",
      "format_hint": "png|txt|json|null",
      "required": true
    }}
  ],
  "depends_on": ["sg_0"],
  "input_refs": {{"ref_name": "sg_0.output_id"}},
  "allowed_skills": ["web.search"],
  "forbidden_skills": ["browser.run"]
}}

## Rules
- unit_id must be "sg_0", "sg_1", etc. in order
- depends_on can only reference earlier unit_ids (no cycles)
- depends_on MUST reflect real data flow: if sg_1 needs sg_0's output, list "sg_0"
- input_refs MUST map to actual output_ids from upstream units (format: "sg_X.output_id")
- output_type "file" must have format_hint
- output_type "answer" means text response, no file needed
- unit_type must match the actual work: desktop_control for app ops, code_generation for coding, etc.
- allowed_skills: whitelist (empty = all allowed). forbidden_skills: blacklist.
- Keep sub-goals concrete and actionable, NOT abstract methodology
- Each sub-goal should map to 1-3 skill executions
- Return ONLY the JSON array, no other text

## Examples

Goal: "搜索今天天气并把结果保存到 weather.txt"
[
  {{"unit_id": "sg_0", "objective": "搜索今天天气信息", "unit_type": "data_retrieval", "required_outputs": [{{"output_id": "weather_data", "output_type": "data", "description": "天气搜索结果文本", "format_hint": null, "required": true}}], "depends_on": [], "input_refs": {{}}, "allowed_skills": ["web.search"], "forbidden_skills": ["browser.run"]}},
  {{"unit_id": "sg_1", "objective": "将天气信息保存到 weather.txt", "unit_type": "file_production", "required_outputs": [{{"output_id": "weather_file", "output_type": "file", "description": "天气结果文本文件", "format_hint": "txt", "required": true}}], "depends_on": ["sg_0"], "input_refs": {{"weather_data": "sg_0.weather_data"}}, "allowed_skills": ["fs.write"], "forbidden_skills": []}}
]
"""


# ── Configurable builder parameters ────────────────────────────────

@dataclass
class PlanBuilderConfig:
    """All tunable parameters for TaskExecutionPlanBuilder in one place.

    Centralises patterns, MIME mappings, skill hint rules, and prompt
    templates that were previously scattered as module-level constants.
    """

    # ── Search / screenshot detection patterns ──────────────────────
    search_engine_pattern: str = (
        r'(?:百度|google|bing|搜狗|duckduckgo|yahoo|yandex)'
    )
    search_intent_pattern: str = (
        r'(?:搜索|查找|查询|检索|search|look\s*up|find|query)'
    )
    screenshot_intent_pattern: str = (
        r'(?:截图|截屏|screenshot|capture|保存.*(?:页面|网页|screen))'
    )

    # ── File format → MIME type mapping ─────────────────────────────
    mime_mapping: Dict[str, str] = field(default_factory=lambda: {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "txt": "text/plain",
        "md": "text/markdown",
        "json": "application/json",
        "csv": "text/csv",
        "pdf": "application/pdf",
        "html": "text/html",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    })

    # ── SkillHint auto-injection rules ──────────────────────────────
    # search_preferred / search_prohibited: when search intent detected
    # without screenshot, inject these as SkillHint.
    search_preferred_skills: List[str] = field(
        default_factory=lambda: ["web.search", "llm.fallback"],
    )
    search_prohibited_skills: List[str] = field(
        default_factory=lambda: ["browser.run"],
    )
    search_hint_reason: str = "搜索任务应走 web.search，不要用浏览器自动化访问搜索引擎"

    screenshot_preferred_skills: List[str] = field(
        default_factory=lambda: ["browser.run"],
    )
    screenshot_hint_reason: str = "截图任务需要浏览器渲染"

    # ── Deterministic builder patterns ──────────────────────────────
    file_write_pattern: str = (
        r'(?:写入|保存|导出|生成|创建|write|save|export|create)'
    )
    analysis_pattern: str = (
        r'(?:分析|统计|计算|analyze|compute|calculate)'
    )
    verification_pattern: str = (
        r'(?:验证|测试|检查|verify|test|check)'
    )
    file_extension_pattern: str = (
        r'\.(?:txt|md|json|csv|xlsx|docx|pdf)'
    )

    # ── LLM prompt template ─────────────────────────────────────────
    # Use {goal}, {task_kind}, {phase_hints}, {deliverables} as placeholders.
    build_prompt: str = _DEFAULT_BUILD_PROMPT


class TaskExecutionPlanBuilder:
    """Build TaskExecutionPlan from TaskDefinition + ComplexityResult.

    Primary path: LLM structured generation.
    Fallback: deterministic builder from ComplexityResult.phase_hints.
    """

    def __init__(
        self,
        llm_client: Optional[Any] = None,
        config: Optional[PlanBuilderConfig] = None,
    ) -> None:
        self._llm = llm_client
        self.config = config or PlanBuilderConfig()
        # Pre-compile patterns from config
        self._search_engine_re = re.compile(self.config.search_engine_pattern, re.IGNORECASE)
        self._search_intent_re = re.compile(self.config.search_intent_pattern, re.IGNORECASE)
        self._screenshot_intent_re = re.compile(self.config.screenshot_intent_pattern, re.IGNORECASE)
        self._file_write_re = re.compile(self.config.file_write_pattern, re.IGNORECASE)
        self._analysis_re = re.compile(self.config.analysis_pattern, re.IGNORECASE)
        self._verification_re = re.compile(self.config.verification_pattern, re.IGNORECASE)
        self._file_ext_re = re.compile(self.config.file_extension_pattern, re.IGNORECASE)

    async def build(
        self,
        intent: str,
        task_def: Optional[Any] = None,
        complexity: Optional[Any] = None,
    ) -> TaskExecutionPlan:
        """Build a TaskExecutionPlan.

        Tries LLM first, falls back to deterministic builder.
        """
        plan = None

        if self._llm is not None:
            try:
                plan = await self._build_via_llm(intent, task_def, complexity)
            except Exception as e:
                logger.warning("[PlanBuilder] LLM build failed: %s, falling back to deterministic", e)

        if plan is None:
            plan = self._build_deterministic(intent, task_def, complexity)

        # Post-process: auto-generate SkillHints
        self._inject_skill_hints(plan)

        return plan

    # ── LLM builder ─────────────────────────────────────────────────

    async def _build_via_llm(
        self,
        intent: str,
        task_def: Optional[Any],
        complexity: Optional[Any],
    ) -> Optional[TaskExecutionPlan]:
        """Build plan via single LLM call."""
        phase_hints = getattr(complexity, "phase_hints", []) if complexity else []
        deliverables = []
        if task_def:
            for d in getattr(task_def, "deliverables", []):
                name = getattr(d, "name", "") or getattr(d, "text", "")
                dtype = getattr(d, "type", "")
                deliverables.append(f"{name} ({dtype})" if dtype else name)

        prompt = self.config.build_prompt.format(
            goal=intent[:500],
            task_kind=getattr(task_def, "task_kind", "general") or "general" if task_def else "general",
            phase_hints=", ".join(phase_hints[:5]) if phase_hints else "(none)",
            deliverables=", ".join(deliverables[:5]) if deliverables else "(none)",
        )

        raw = self._llm.call(prompt).strip()

        # Extract JSON array from response
        json_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not json_match:
            logger.warning("[PlanBuilder] LLM response has no JSON array")
            return None

        try:
            units_data = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            logger.warning("[PlanBuilder] JSON parse failed: %s", e)
            return None

        if not isinstance(units_data, list) or not units_data:
            return None

        return self._parse_units(units_data, intent)

    def _parse_units(self, units_data: list, intent: str) -> TaskExecutionPlan:
        """Parse LLM JSON output into TaskExecutionPlan."""
        from .execution_plan import UnitType, DegradationPolicy
        units: List[SubGoalUnit] = []

        # Valid unit_type values
        _UNIT_TYPE_MAP = {v.value: v for v in UnitType}

        for item in units_data:
            if not isinstance(item, dict):
                continue

            unit_id = item.get("unit_id", f"sg_{len(units)}")
            objective = item.get("objective", "")

            # Parse unit_type
            raw_type = item.get("unit_type", "general")
            unit_type = _UNIT_TYPE_MAP.get(raw_type, UnitType.GENERAL)

            outputs = []
            for o in item.get("required_outputs", []):
                if not isinstance(o, dict):
                    continue
                outputs.append(RequiredOutput(
                    output_id=o.get("output_id", f"out_{len(outputs)}"),
                    output_type=o.get("output_type", "data"),
                    description=o.get("description", ""),
                    format_hint=o.get("format_hint"),
                    mime_type_hint=self._format_to_mime(o.get("format_hint")),
                    required=o.get("required", True),
                ))

            depends_on = item.get("depends_on", [])
            if not isinstance(depends_on, list):
                depends_on = []
            # Validate: only reference earlier units
            valid_ids = {u.unit_id for u in units}
            depends_on = [d for d in depends_on if d in valid_ids]

            input_refs = item.get("input_refs", {})
            if not isinstance(input_refs, dict):
                input_refs = {}

            # Parse skill constraints
            allowed_skills = item.get("allowed_skills", [])
            if not isinstance(allowed_skills, list):
                allowed_skills = []
            forbidden_skills = item.get("forbidden_skills", [])
            if not isinstance(forbidden_skills, list):
                forbidden_skills = []

            units.append(SubGoalUnit(
                unit_id=unit_id,
                objective=objective,
                unit_type=unit_type,
                required_outputs=outputs,
                depends_on=depends_on,
                input_refs=input_refs,
                allowed_skills=[s for s in allowed_skills if isinstance(s, str)],
                forbidden_skills=[s for s in forbidden_skills if isinstance(s, str)],
            ))

        return TaskExecutionPlan(
            original_goal=intent,
            units=units,
        )

    # ── Deterministic fallback ──────────────────────────────────────

    def _build_deterministic(
        self,
        intent: str,
        task_def: Optional[Any],
        complexity: Optional[Any],
    ) -> TaskExecutionPlan:
        """Build plan from ComplexityResult.phase_hints without LLM.

        Each phase_hint becomes a SubGoalUnit with a generic RequiredOutput.
        Generates proper depends_on chains and input_refs between units.
        """
        from .execution_plan import UnitType
        phase_hints = getattr(complexity, "phase_hints", []) if complexity else []

        if not phase_hints:
            # Single unit with the full intent
            return TaskExecutionPlan(
                original_goal=intent,
                units=[SubGoalUnit(
                    unit_id="sg_0",
                    objective=intent,
                    required_outputs=[RequiredOutput(
                        output_id="result",
                        output_type="answer",
                        description="任务结果",
                    )],
                )],
            )

        units: List[SubGoalUnit] = []
        prev_id: Optional[str] = None

        for i, hint in enumerate(phase_hints):
            unit_id = f"sg_{i}"
            # Infer output type from hint text
            output_type = "data"
            format_hint = None
            if self._screenshot_intent_re.search(hint):
                output_type = "file"
                format_hint = "png"
            elif self._file_ext_re.search(hint):
                match = re.search(r'\.(\w+)', hint)
                if match:
                    output_type = "file"
                    format_hint = match.group(1).lower()

            # Infer unit_type from hint text
            unit_type = UnitType.GENERAL
            if self._search_intent_re.search(hint):
                unit_type = UnitType.DATA_RETRIEVAL
            elif self._screenshot_intent_re.search(hint):
                unit_type = UnitType.DATA_RETRIEVAL
            elif self._file_write_re.search(hint):
                unit_type = UnitType.FILE_PRODUCTION
            elif self._analysis_re.search(hint):
                unit_type = UnitType.ANALYSIS
            elif self._verification_re.search(hint):
                unit_type = UnitType.VERIFICATION

            # Build input_refs from previous unit's output
            input_refs: Dict[str, str] = {}
            if prev_id is not None:
                prev_idx = i - 1
                input_refs[f"prev_output"] = f"sg_{prev_idx}.output_{prev_idx}"

            output_id = f"output_{i}"
            units.append(SubGoalUnit(
                unit_id=unit_id,
                objective=hint,
                unit_type=unit_type,
                required_outputs=[RequiredOutput(
                    output_id=output_id,
                    output_type=output_type,
                    description=hint,
                    format_hint=format_hint,
                    mime_type_hint=self._format_to_mime(format_hint),
                )],
                depends_on=[prev_id] if prev_id else [],
                input_refs=input_refs,
            ))
            prev_id = unit_id

        return TaskExecutionPlan(
            original_goal=intent,
            units=units,
        )

    # ── SkillHint auto-injection ────────────────────────────────────

    def _inject_skill_hints(self, plan: TaskExecutionPlan) -> None:
        """Auto-generate SkillHints based on sub-goal content analysis.

        Rules (configurable via PlanBuilderConfig):
        - Search engine + search intent → prefer web.search, prohibit browser.run
          (unless screenshot is explicitly required)
        - Screenshot intent → prefer browser.run
        """
        for unit in plan.units:
            if unit.skill_hint is not None:
                continue  # LLM already provided one

            obj = unit.objective
            has_search = bool(self._search_intent_re.search(obj))
            has_search_engine = bool(self._search_engine_re.search(obj))
            has_screenshot = bool(self._screenshot_intent_re.search(obj))

            # Search task without screenshot → web.search, prohibit browser.run
            if (has_search or has_search_engine) and not has_screenshot:
                unit.skill_hint = SkillHint(
                    preferred_skills=list(self.config.search_preferred_skills),
                    prohibited_skills=list(self.config.search_prohibited_skills),
                    reason=self.config.search_hint_reason,
                )
            elif has_screenshot:
                unit.skill_hint = SkillHint(
                    preferred_skills=list(self.config.screenshot_preferred_skills),
                    reason=self.config.screenshot_hint_reason,
                )

    # ── Helpers ─────────────────────────────────────────────────────

    def _format_to_mime(self, fmt: Optional[str]) -> Optional[str]:
        """Convert format hint to MIME type using config mapping."""
        if not fmt:
            return None
        return self.config.mime_mapping.get(fmt.lower())
