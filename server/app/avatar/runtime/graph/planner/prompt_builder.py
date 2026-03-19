"""
PromptBuilder - Prompt Management for Graph Planner

Generates prompts for ReAct, DAG, and REPAIR planning modes.
Depends on skill_registry — no capability_registry.

Requirements: 6.1, 27.5, 27.6, 28.5
"""

from __future__ import annotations
from typing import Dict, List, Any, Optional, TYPE_CHECKING
import json
import logging

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult

logger = logging.getLogger(__name__)


class PromptBuilder:
    """
    Builds LLM prompts using skill_registry as the single source of truth.
    """

    def __init__(self, skill_registry=None):
        if skill_registry is None:
            from app.avatar.skills.registry import skill_registry as _sr
            skill_registry = _sr
        self.skill_registry = skill_registry
        logger.info("PromptBuilder initialized")

    def build_react_prompt(
        self,
        goal: str,
        graph: Optional['ExecutionGraph'] = None,
        previous_results: Optional[Dict[str, Any]] = None,
    ) -> str:
        parts = [self._system_instruction(), f"\n## Goal\n{goal}",
                 "\n## Available Skills", self._format_skills()]

        if graph and graph.nodes:
            parts += ["\n## Current Graph State", self._format_graph_state(graph)]
        if previous_results:
            parts += ["\n## Previous Results", json.dumps(previous_results, indent=2)]

        parts.append(self._react_instructions())
        return "\n".join(parts)

    def build_dag_prompt(self, goal: str, context: Optional[Dict[str, Any]] = None) -> str:
        parts = [self._system_instruction(), f"\n## Goal\n{goal}",
                 "\n## Available Skills", self._format_skills()]
        if context:
            # Filter out non-serializable objects (e.g. skill_registry, callbacks)
            _serializable = {}
            for k, v in context.items():
                try:
                    json.dumps(v)
                    _serializable[k] = v
                except (TypeError, ValueError):
                    pass
            if _serializable:
                parts += ["\n## Context", json.dumps(_serializable, indent=2)]
        parts.append(self._dag_instructions())
        return "\n".join(parts)

    def build_repair_prompt(
        self,
        goal: str,
        graph: 'ExecutionGraph',
        failure_context: 'ExecutionResult',
        failed_node_id: str,
        error_message: str,
    ) -> str:
        parts = [
            self._system_instruction(),
            f"\n## Original Goal\n{goal}",
            "\n## Failure Information",
            f"Failed Node: {failed_node_id}",
            f"Error: {error_message}",
            f"Completed: {failure_context.completed_nodes}, Failed: {failure_context.failed_nodes}",
            "\n## Current Graph State",
            self._format_graph_state(graph),
        ]

        failed_node = graph.nodes.get(failed_node_id)
        if failed_node:
            parts += [
                "\n## Failed Node Details",
                f"Skill: {failed_node.capability_name}",
                f"Parameters: {json.dumps(failed_node.params, indent=2)}",
            ]

        parts += ["\n## Available Skills", self._format_skills(), self._repair_instructions()]
        return "\n".join(parts)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _system_instruction(self) -> str:
        return """# Graph Execution Planner

You are an AI assistant that plans execution graphs for achieving goals.
You work with Skills (atomic operations) and create execution plans
by adding nodes and edges to a graph.

**Key Principles:**
1. Use the `output` field to reference node results: `{{node_id.output}}`
2. Create data dependencies using edges between nodes
3. Optimize for parallel execution when possible"""

    def _format_skills(self) -> str:
        """Format all skills for LLM consumption, grouped by side_effect."""
        from app.avatar.skills.base import SideEffect

        groups: Dict[str, List] = {}
        for cls in self.skill_registry.iter_skills():
            spec = cls.spec
            effects = [e.value for e in spec.side_effects] if spec.side_effects else ["safe"]
            group = effects[0]
            groups.setdefault(group, []).append(spec)

        parts = []
        for group in sorted(groups):
            parts.append(f"\n### {group.upper()}")
            for spec in groups[group]:
                parts.append(f"\n**{spec.name}**")
                parts.append(f"Description: {spec.description}")

                input_schema = spec.input_model.model_json_schema()
                required = input_schema.get("required", [])
                properties = input_schema.get("properties", {})
                if properties:
                    parts.append("Inputs:")
                    for pname, pschema in properties.items():
                        req = " (required)" if pname in required else ""
                        ptype = pschema.get("type", "any")
                        pdesc = pschema.get("description", "")
                        parts.append(f"  - {pname}: {ptype}{req} - {pdesc}")

                output_schema = spec.output_model.model_json_schema()
                out_props = output_schema.get("properties", {})
                if out_props:
                    parts.append("Outputs:")
                    if "output" in out_props:
                        s = out_props["output"]
                        parts.append(f"  - output: {s.get('type','any')} - {s.get('description','Main output')} **[Use {{{{node_id.output}}}}]**")
                    for pname, pschema in out_props.items():
                        if pname != "output":
                            parts.append(f"  - {pname}: {pschema.get('type','any')} - {pschema.get('description','')}")

                parts.append("")

        return "\n".join(parts)

    def _format_graph_state(self, graph: 'ExecutionGraph') -> str:
        parts = [f"Nodes: {len(graph.nodes)}, Edges: {len(graph.edges)}, Status: {graph.status}"]
        for nid, node in graph.nodes.items():
            parts.append(f"  - {nid}: {node.capability_name} ({node.status.value})")
            if node.outputs:
                parts.append(f"    Output: {json.dumps(node.outputs.get('output', 'N/A'))}")
        for eid, edge in graph.edges.items():
            parts.append(f"  - {edge.source_node}.{edge.source_field} → {edge.target_node}.{edge.target_param}")
        return "\n".join(parts)

    def _react_instructions(self) -> str:
        return """
## Instructions

Think step-by-step about what needs to be done next.

**Response format (JSON):**
```json
{
  "thought": "Your reasoning",
  "action": {
    "operation": "ADD_NODE",
    "node": {
      "id": "unique_id",
      "capability_name": "skill.name",
      "params": {"param": "value or {{prev_node.output}}"}
    }
  }
}
```

Or to finish:
```json
{"thought": "Goal achieved", "action": {"operation": "FINISH"}}
```"""

    def _dag_instructions(self) -> str:
        return """
## Instructions

Plan the COMPLETE execution graph upfront.

**Response format (JSON):**
```json
{
  "reasoning": "Overall strategy",
  "actions": [
    {"operation": "ADD_NODE", "node": {"id": "n1", "capability_name": "skill.name", "params": {}}},
    {"operation": "ADD_EDGE", "edge": {"source_node": "n1", "source_field": "output", "target_node": "n2", "target_param": "input"}}
  ]
}
```"""

    def _repair_instructions(self) -> str:
        return """
## Instructions

Analyze the failure and generate recovery nodes.

**Response format (JSON):**
```json
{
  "analysis": "Why it failed",
  "recovery_strategy": "How to fix it",
  "actions": [
    {"operation": "ADD_NODE", "node": {"id": "recovery", "capability_name": "skill.name", "params": {}}}
  ]
}
```"""


# ---------------------------------------------------------------------------
# P1: PlannerPromptBuilder — execution state view based prompt construction
# ---------------------------------------------------------------------------

from dataclasses import dataclass as _dataclass, field as _field
from typing import Any as _Any, Dict as _Dict, List as _List, Optional as _Optional


@_dataclass
class ExecutionStateView:
    """
    Unified input structure for PlannerPromptBuilder.
    Replaces direct chat history stacking.
    """
    goal: str
    available_skills: _List[_Dict[str, _Any]]       # skill spec list
    workspace_snapshot: _Dict[str, _Any]             # filename + size + artifact_id
    goal_coverage_hint: _Optional[str] = None        # GoalCoverageSummary.to_planner_hint()
    repair_feedback: _Optional[_Any] = None          # RepairFeedback (optional)
    artifact_summary: _Optional[str] = None          # ArtifactRegistry.get_artifact_summary()
    graph_state: _Optional[_Dict[str, _Any]] = None  # current graph state summary


class PlannerPromptBuilder:
    """
    P1: Builds structured prompts from ExecutionStateView.

    Paragraph priority (high → low):
    1. goal
    2. goal_coverage_hint
    3. repair_feedback
    4. available_skills
    5. artifact_summary
    6. workspace_snapshot
    7. graph_state

    Token overflow truncation order: artifact_summary → workspace_snapshot → graph_state
    repair_feedback and goal_coverage_hint are always preserved in full.
    """

    def __init__(
        self,
        skill_registry: _Optional[_Any] = None,
        artifact_registry: _Optional[_Any] = None,
        trace_store: _Optional[_Any] = None,
        max_prompt_tokens: int = 32000,
        artifact_summary_limit: int = 1000,
    ) -> None:
        self.skill_registry = skill_registry
        self.artifact_registry = artifact_registry
        self.trace_store = trace_store
        self.max_prompt_tokens = max_prompt_tokens
        self.artifact_summary_limit = artifact_summary_limit

    def build_from_state_view(self, state_view: ExecutionStateView) -> str:
        """
        Build prompt from ExecutionStateView with token-aware truncation.
        Writes 'planner_prompt_built' event to StepTraceStore on completion.
        """
        # Build all sections
        goal_section = self._build_goal_section(state_view.goal)
        coverage_section = (
            f"\n## Goal Coverage\n{state_view.goal_coverage_hint}"
            if state_view.goal_coverage_hint else ""
        )
        repair_section = (
            self._build_repair_section(state_view.repair_feedback)
            if state_view.repair_feedback else ""
        )

        # P3: DomainPack prompt_hint injection (before available_skills)
        domain_hint_section = ""
        if state_view.goal:
            try:
                from app.avatar.runtime.verification.goal_normalizer import GoalNormalizer
                from app.avatar.runtime.verification.domain_packs.builtin import BUILTIN_DOMAIN_PACKS
                normalized = GoalNormalizer().normalize(state_view.goal)
                if normalized.matched_domain_pack:
                    pack = BUILTIN_DOMAIN_PACKS.get(normalized.matched_domain_pack)
                    if pack and pack.prompt_hint:
                        domain_hint_section = f"\n## 场景提示\n{pack.prompt_hint}"
            except Exception:
                pass

        skills_section = self._build_skills_section(state_view.available_skills)

        # Low-priority sections (truncatable)
        artifact_section = (
            f"\n## Artifacts\n{state_view.artifact_summary}"
            if state_view.artifact_summary else ""
        )
        workspace_section = self._build_workspace_section(state_view.workspace_snapshot)
        graph_section = (
            f"\n## Graph State\n{json.dumps(state_view.graph_state, indent=2)}"
            if state_view.graph_state else ""
        )

        # Enforce artifact_summary_limit
        if state_view.artifact_summary and len(state_view.artifact_summary) > self.artifact_summary_limit:
            truncated = state_view.artifact_summary[:self.artifact_summary_limit] + "..."
            artifact_section = f"\n## Artifacts\n{truncated}"

        # Assemble with token budget
        fixed_parts = [goal_section, coverage_section, repair_section, domain_hint_section, skills_section]
        truncatable = [artifact_section, workspace_section, graph_section]

        prompt = "\n".join(p for p in fixed_parts if p)
        token_budget = self.max_prompt_tokens - self._estimate_tokens(prompt)

        for section in truncatable:
            if not section:
                continue
            section_tokens = self._estimate_tokens(section)
            if token_budget >= section_tokens:
                prompt += "\n" + section
                token_budget -= section_tokens
            elif token_budget > 100:
                # Partial include
                chars_allowed = token_budget * 3  # rough: 3 chars/token
                prompt += "\n" + section[:chars_allowed] + "\n...[truncated]"
                token_budget = 0
            # else: skip entirely

        token_estimate = self._estimate_tokens(prompt)
        self._write_trace_event(state_view, token_estimate)
        return prompt

    def _build_goal_section(self, goal: str) -> str:
        return f"# Graph Execution Planner\n\n## Goal\n{goal}"

    def _build_skills_section(self, skills: _List[_Dict[str, _Any]]) -> str:
        """
        Format skills with name / description / input_schema / output_contract.
        Does NOT include implementation details.
        """
        if not skills:
            # Fall back to skill_registry if available
            if self.skill_registry:
                return self._format_skills_from_registry()
            return "\n## Available Skills\n(none)"

        parts = ["\n## Available Skills"]
        for skill in skills:
            name = skill.get("name", "unknown")
            desc = skill.get("description", "")
            parts.append(f"\n**{name}**\n{desc}")
            if "input_schema" in skill:
                props = skill["input_schema"].get("properties", {})
                required = skill["input_schema"].get("required", [])
                if props:
                    parts.append("Inputs:")
                    for pname, pschema in props.items():
                        req = " (required)" if pname in required else ""
                        parts.append(f"  - {pname}: {pschema.get('type','any')}{req}")
            if "output_contract" in skill:
                oc = skill["output_contract"]
                parts.append(
                    f"Output: value_kind={oc.get('value_kind','?')} "
                    f"transport={oc.get('transport_mode','?')}"
                )
        return "\n".join(parts)

    def _format_skills_from_registry(self) -> str:
        """Fallback: format from skill_registry."""
        parts = ["\n## Available Skills"]
        try:
            for cls in self.skill_registry.iter_skills():
                spec = cls.spec
                parts.append(f"\n**{spec.name}**\n{spec.description}")
        except Exception:
            pass
        return "\n".join(parts)

    def _build_workspace_section(self, snapshot: _Dict[str, _Any]) -> str:
        """List filenames, sizes, and artifact_ids only — no file content."""
        if not snapshot:
            return ""
        parts = ["\n## Workspace"]
        files = snapshot.get("files") or snapshot
        if isinstance(files, dict):
            for fname, info in files.items():
                if isinstance(info, dict):
                    size = info.get("size", "?")
                    art_id = info.get("artifact_id", "")
                    art_str = f" [artifact:{art_id[:8]}...]" if art_id else ""
                    parts.append(f"  - {fname} ({size}B){art_str}")
                else:
                    parts.append(f"  - {fname}")
        return "\n".join(parts)

    def _build_repair_section(self, feedback: _Any) -> str:
        """Format repair feedback as '上一轮失败原因与修复建议' paragraph."""
        if hasattr(feedback, "to_planner_summary"):
            summary = feedback.to_planner_summary()
        else:
            summary = str(feedback)
        return f"\n## 上一轮失败原因与修复建议\n{summary}"

    def _estimate_tokens(self, text: str) -> int:
        """
        Rough token estimate.
        English: ~4 chars/token; mixed CJK: ~2 chars/token.
        """
        if not text:
            return 0
        cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_count = len(text) - cjk_count
        return (cjk_count // 2) + (other_count // 4) + 1

    def _write_trace_event(self, state_view: ExecutionStateView, token_estimate: int) -> None:
        if not self.trace_store:
            return
        try:
            self.trace_store.record_event(
                session_id="",  # caller should set session_id via subclass or wrapper
                event_type="planner_prompt_built",
                payload={
                    "prompt_token_estimate": token_estimate,
                    "has_repair_feedback": state_view.repair_feedback is not None,
                    "has_coverage_hint": state_view.goal_coverage_hint is not None,
                    "artifact_summary_len": len(state_view.artifact_summary or ""),
                },
            )
        except Exception:
            pass
