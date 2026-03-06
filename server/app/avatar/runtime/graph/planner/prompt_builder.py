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
            parts += ["\n## Context", json.dumps(context, indent=2)]
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
