"""
Migration Utility: AgentLoop/Step list → ExecutionGraph

Converts legacy step lists (from AgentLoop/SimpleLLMPlanner output) into
ExecutionGraph format, inferring DataEdges from template references.

Requirements: 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 23.7
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Regex patterns for template references: {{step_id.field}}, ${step_id.field}, ref://step_id/field
_REF_PATTERNS = [
    re.compile(r"\{\{(\w+)\.(\w+)\}\}"),          # {{step_id.field}}
    re.compile(r"\$\{(\w+)\.(\w+)\}"),             # ${step_id.field}
    re.compile(r"ref://(\w+)/(\w+)"),              # ref://step_id/field
]


@dataclass
class MigrationEdge:
    source_node: str
    source_field: str
    target_node: str
    target_param: str


@dataclass
class MigrationReport:
    total_steps: int
    converted_nodes: int
    inferred_edges: int
    warnings: List[str] = field(default_factory=list)
    unresolved_refs: List[str] = field(default_factory=list)
    dry_run: bool = False


def _extract_refs(value: Any) -> List[Tuple[str, str]]:
    """Extract (step_id, field) tuples from a string value."""
    if not isinstance(value, str):
        return []
    refs = []
    for pattern in _REF_PATTERNS:
        for m in pattern.finditer(value):
            refs.append((m.group(1), m.group(2)))
    return refs


def _infer_edges(steps: List[Dict[str, Any]]) -> List[MigrationEdge]:
    """
    Infer DataEdges by scanning step params for template references.

    Requirements: 23.3, 23.4
    """
    node_ids = {s.get("id") or s.get("step_id") or s.get("name", f"step_{i}")
                for i, s in enumerate(steps)}
    edges: List[MigrationEdge] = []

    for step in steps:
        node_id = step.get("id") or step.get("step_id") or step.get("name", "")
        params = step.get("params") or step.get("parameters") or {}

        for param_name, param_value in params.items():
            for src_node, src_field in _extract_refs(param_value):
                if src_node in node_ids and src_node != node_id:
                    edges.append(MigrationEdge(
                        source_node=src_node,
                        source_field=src_field,
                        target_node=node_id,
                        target_param=param_name,
                    ))

    return edges


def convert_loop_to_graph(
    steps: List[Dict[str, Any]],
    goal: str = "",
    dry_run: bool = False,
) -> Tuple[Optional[Dict[str, Any]], MigrationReport]:
    """
    Convert a list of AgentLoop steps to ExecutionGraph format.

    Args:
        steps: List of step dicts with keys: id/step_id/name, capability/skill, params
        goal: Optional goal description for the graph
        dry_run: If True, validate only without building the graph object

    Returns:
        (graph_dict, report) - graph_dict is None in dry_run mode

    Requirements: 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 23.7
    """
    report = MigrationReport(
        total_steps=len(steps),
        converted_nodes=0,
        inferred_edges=0,
        dry_run=dry_run,
    )

    if not steps:
        report.warnings.append("Empty step list provided")
        return None, report

    # Build node list
    nodes: Dict[str, Dict[str, Any]] = {}
    seen_ids = set()

    for i, step in enumerate(steps):
        node_id = step.get("id") or step.get("step_id") or step.get("name") or f"step_{i}"
        capability = (
            step.get("capability")
            or step.get("skill")
            or step.get("action")
            or "unknown"
        )
        params = step.get("params") or step.get("parameters") or {}

        if node_id in seen_ids:
            new_id = f"{node_id}_{i}"
            report.warnings.append(
                f"Duplicate node ID '{node_id}' renamed to '{new_id}'"
            )
            node_id = new_id
        seen_ids.add(node_id)

        nodes[node_id] = {
            "id": node_id,
            "capability_name": capability,
            "params": params,
            "status": "pending",
            "outputs": {},
            "metadata": step.get("metadata") or {},
        }
        report.converted_nodes += 1

    # Infer edges from template references
    edges_raw = _infer_edges(steps)
    edges: List[Dict[str, Any]] = []

    for e in edges_raw:
        if e.source_node not in nodes:
            report.unresolved_refs.append(
                f"{e.target_node}.{e.target_param} → {e.source_node}.{e.source_field} (source not found)"
            )
            continue
        edge_id = f"{e.source_node}-{e.target_node}-{e.target_param}"
        edges.append({
            "id": edge_id,
            "source_node": e.source_node,
            "source_field": e.source_field,
            "target_node": e.target_node,
            "target_param": e.target_param,
            "transformer_name": None,
            "optional": False,
        })
        report.inferred_edges += 1

    # Validate DAG (simple cycle check via DFS)
    cycle_error = _check_cycles(list(nodes.keys()), edges)
    if cycle_error:
        report.warnings.append(f"Cycle detected: {cycle_error}")

    if report.unresolved_refs:
        report.warnings.append(
            f"{len(report.unresolved_refs)} unresolved reference(s) - edges skipped"
        )

    logger.info(
        f"[Migration] Converted {report.converted_nodes} nodes, "
        f"{report.inferred_edges} edges inferred, "
        f"{len(report.warnings)} warnings"
    )

    if dry_run:
        _log_dry_run_report(report, nodes, edges)
        return None, report

    graph_dict = {
        "goal": goal,
        "nodes": nodes,
        "edges": {e["id"]: e for e in edges},
        "status": "pending",
        "metadata": {"migrated_from": "agent_loop"},
    }
    return graph_dict, report


def _check_cycles(node_ids: List[str], edges: List[Dict[str, Any]]) -> Optional[str]:
    """Simple DFS cycle detection. Returns description of cycle or None."""
    adj: Dict[str, List[str]] = {n: [] for n in node_ids}
    for e in edges:
        if e["source_node"] in adj:
            adj[e["source_node"]].append(e["target_node"])

    visited: set = set()
    in_stack: set = set()

    def dfs(node: str) -> Optional[str]:
        visited.add(node)
        in_stack.add(node)
        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                result = dfs(neighbor)
                if result:
                    return result
            elif neighbor in in_stack:
                return f"{node} → {neighbor}"
        in_stack.discard(node)
        return None

    for n in node_ids:
        if n not in visited:
            result = dfs(n)
            if result:
                return result
    return None


def _log_dry_run_report(
    report: MigrationReport,
    nodes: Dict[str, Any],
    edges: List[Dict[str, Any]],
) -> None:
    """Log dry-run preview. Requirements: 23.5, 23.6"""
    logger.info("=== DRY RUN MIGRATION REPORT ===")
    logger.info(f"  Steps:    {report.total_steps}")
    logger.info(f"  Nodes:    {report.converted_nodes}")
    logger.info(f"  Edges:    {report.inferred_edges}")
    for node_id, node in nodes.items():
        logger.info(f"  NODE {node_id}: capability={node['capability_name']}")
    for edge in edges:
        logger.info(
            f"  EDGE {edge['source_node']}.{edge['source_field']} "
            f"→ {edge['target_node']}.{edge['target_param']}"
        )
    for w in report.warnings:
        logger.warning(f"  WARNING: {w}")
    for r in report.unresolved_refs:
        logger.warning(f"  UNRESOLVED: {r}")
    logger.info("=== END DRY RUN ===")
