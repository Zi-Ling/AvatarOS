"""LocalReplanner — interface and LLM-based implementation for local re-planning.

When a worker's feedback suggests that downstream tasks need re-decomposition,
the LocalReplanner generates replacement SubtaskNodes for the affected subgraph.

Two implementations:
- LocalReplanner (Protocol): interface for dependency injection
- LLMLocalReplanner: calls LLM to re-decompose the affected path

All tunable parameters come from MultiAgentConfig.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from app.avatar.runtime.multiagent.config import MultiAgentConfig
from app.avatar.runtime.multiagent.core.subtask_graph import SubtaskGraph, SubtaskNode

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocalReplanConfig:
    """Tunable parameters for local re-planning."""
    # Max new nodes a single replan can produce
    max_new_nodes: int = 5
    # LLM temperature for replan calls
    replan_temperature: float = 0.3
    # Max chars of context to send to LLM
    replan_context_max_chars: int = 2000
    # System prompt for local replan LLM calls
    replan_system_prompt: str = (
        "You are a task re-planner for a multi-agent system. "
        "A subtask has completed but its worker reported quality issues. "
        "Given the feedback and current graph state, re-decompose the "
        "downstream work into corrected sub-tasks.\n\n"
        "Output a JSON array of replacement tasks. Each element:\n"
        '{{"task_id": "replan_0", "goal": "...", '
        '"suggested_role": "researcher|executor|writer", '
        '"expected_output": {{"type": "artifact|data|text", "format": "..."}}, '
        '"acceptance_criteria": ["..."]}}\n\n'
        "Rules:\n"
        "- task_id must be replan_0, replan_1, etc.\n"
        "- Address the feedback's concerns in the new decomposition\n"
        "- Keep it minimal (1-3 tasks typical)\n"
        "- Return ONLY the JSON array"
    )


@runtime_checkable
class LocalReplannerProtocol(Protocol):
    """Protocol for local re-planners (dependency injection point)."""

    async def replan(
        self,
        trigger_node_id: str,
        feedback: Dict[str, Any],
        current_graph: SubtaskGraph,
        replaceable_node_ids: List[str],
        completed_results: Dict[str, Dict[str, Any]],
    ) -> Optional[List[SubtaskNode]]:
        """Generate replacement nodes for the affected subgraph.

        Returns None or empty list to signal "no replan needed" (fallback to reset).
        """
        ...


class LLMLocalReplanner:
    """LLM-based local re-planner.

    Calls the LLM with:
    - The trigger node's result and feedback
    - Descriptions of the nodes being replaced
    - Completed upstream context

    Returns a list of new SubtaskNodes to replace the old ones.
    """

    def __init__(
        self,
        llm: Any,  # LLM client with .chat() method
        config: Optional[LocalReplanConfig] = None,
        ma_config: Optional[MultiAgentConfig] = None,
    ) -> None:
        self._llm = llm
        self._cfg = config or LocalReplanConfig()
        self._ma_cfg = ma_config or MultiAgentConfig()

    async def replan(
        self,
        trigger_node_id: str,
        feedback: Dict[str, Any],
        current_graph: SubtaskGraph,
        replaceable_node_ids: List[str],
        completed_results: Dict[str, Dict[str, Any]],
    ) -> Optional[List[SubtaskNode]]:
        # Build context for LLM
        trigger_result = completed_results.get(trigger_node_id, {})
        trigger_node = current_graph.nodes.get(trigger_node_id)

        replaced_descriptions = []
        for nid in replaceable_node_ids:
            node = current_graph.nodes.get(nid)
            if node:
                replaced_descriptions.append(
                    f"- {nid}: {node.description} (role={node.responsible_role})"
                )

        user_msg = (
            f"Trigger node: {trigger_node_id}\n"
            f"Trigger description: {trigger_node.description if trigger_node else 'N/A'}\n"
            f"Trigger result summary: {trigger_result.get('summary', 'N/A')[:self._cfg.replan_context_max_chars]}\n\n"
            f"Worker feedback:\n"
            f"  suggestion: {feedback.get('suggestion', 'N/A')}\n"
            f"  action: {feedback.get('action', 'N/A')}\n"
            f"  confidence: {feedback.get('confidence', 0)}\n"
            f"  context: {json.dumps(feedback.get('context', {}), ensure_ascii=False)[:500]}\n\n"
            f"Nodes to replace:\n"
            f"{chr(10).join(replaced_descriptions)}\n\n"
            f"Original goal: {current_graph.metadata.get('goal', 'N/A')[:self._cfg.replan_context_max_chars]}\n"
        )

        try:
            import asyncio
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._llm.chat(
                    messages=[
                        {"role": "system", "content": self._cfg.replan_system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=self._cfg.replan_temperature,
                ),
            )

            raw = response if isinstance(response, str) else getattr(response, "content", str(response))

            # Parse JSON array
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            tasks = json.loads(raw)
            if not isinstance(tasks, list):
                logger.warning("[LLMLocalReplanner] Expected JSON array, got %s", type(tasks))
                return None

            # Convert to SubtaskNodes
            new_nodes: List[SubtaskNode] = []
            for i, t in enumerate(tasks[:self._cfg.max_new_nodes]):
                node_id = t.get("task_id", f"replan_{i}")
                # Ensure unique IDs
                if node_id in current_graph.nodes:
                    node_id = f"{node_id}_{uuid.uuid4().hex[:6]}"

                new_nodes.append(SubtaskNode(
                    node_id=node_id,
                    description=t.get("goal", ""),
                    responsible_role=t.get("suggested_role", self._ma_cfg.default_role),
                    output_contract=t.get("expected_output", {}),
                    success_criteria=t.get("acceptance_criteria", []),
                    status="pending",
                ))

            if new_nodes:
                logger.info(
                    "[LLMLocalReplanner] Generated %d replacement nodes for %s",
                    len(new_nodes), trigger_node_id,
                )
            return new_nodes if new_nodes else None

        except Exception as exc:
            logger.warning("[LLMLocalReplanner] LLM replan failed: %s", exc)
            return None
