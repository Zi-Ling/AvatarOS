"""
DAGPlanner - One-shot complete graph planning

This module implements DAG mode planning where the LLM generates
the entire execution graph in one invocation, optimizing for
parallel execution opportunities.

Requirements: 6.4, 20.1, 20.2, 20.3, 20.4
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional
import json
import re
import logging

from app.avatar.runtime.graph.planner.prompt_builder import PromptBuilder
from app.avatar.runtime.graph.models.graph_patch import (
    GraphPatch,
    PatchAction,
    PatchOperation,
)
from app.avatar.runtime.graph.models.step_node import StepNode, NodeStatus
from app.avatar.runtime.graph.models.data_edge import DataEdge

logger = logging.getLogger(__name__)


class DAGPlanner:
    """
    DAG mode planner for one-shot complete graph planning.
    
    DAGPlanner generates the entire execution graph in one LLM invocation:
    1. Analyzes the goal and available capabilities
    2. Plans all nodes and edges upfront
    3. Optimizes for parallel execution opportunities
    4. Ensures DAG constraints are satisfied
    
    Requirements:
    - 6.4: Generate complete graph in one invocation
    - 20.1: Plan all nodes upfront
    - 20.2: Plan all edges upfront
    - 20.3: Optimize for parallel execution
    - 20.4: Ensure DAG constraints
    """
    
    def __init__(
        self,
        llm_client: Any,
        prompt_builder: Optional[PromptBuilder] = None,
    ):
        """
        Initialize DAGPlanner.

        Args:
            llm_client: LLM client for generating plans
            prompt_builder: Optional PromptBuilder (creates default if not provided)
        """
        self.llm_client = llm_client
        self.prompt_builder = prompt_builder or PromptBuilder()
        logger.info("DAGPlanner initialized")
    
    async def plan_complete_graph(
        self,
        goal: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> GraphPatch:
        """
        Plan complete execution graph in one invocation.
        
        This method:
        1. Generates DAG prompt using PromptBuilder
        2. Calls LLM to generate complete plan
        3. Parses response into GraphPatch with all nodes and edges
        4. Validates DAG constraints
        
        Args:
            goal: High-level goal description
            context: Optional context (workspace state, previous results, etc.)
            
        Returns:
            GraphPatch with all ADD_NODE and ADD_EDGE actions
            
        Requirements: 6.4, 20.1, 20.2, 20.3, 20.4
        """
        # Generate prompt
        prompt = self.prompt_builder.build_dag_prompt(goal, context)
        
        # Call LLM (run sync call in thread pool to avoid blocking event loop)
        import asyncio
        loop = asyncio.get_event_loop()
        raw_response = await loop.run_in_executor(None, self._call_llm, prompt)
        
        # Parse response
        try:
            data = self._parse_json(raw_response)
        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            raise ValueError(f"LLM output malformed: {e}\nRaw: {raw_response}")
        
        # Convert to GraphPatch
        patch = self._response_to_patch(data)
        
        # Validate DAG constraints
        self._validate_dag_constraints(patch)
        
        return patch
    
    def _call_llm(self, prompt: str) -> str:
        """
        Call LLM with prompt.
        
        Args:
            prompt: Formatted prompt string
            
        Returns:
            Raw LLM response
        """
        return self.llm_client.call(prompt)
    def _parse_json(self, text: str) -> Dict[str, Any]:
        """
        Parse JSON from LLM response.
        
        Handles common LLM output formats:
        - Plain JSON
        - JSON wrapped in markdown code blocks
        - JSON with extra text before/after
        
        Args:
            text: Raw LLM response
            
        Returns:
            Parsed JSON dictionary
            
        Raises:
            ValueError: If JSON cannot be parsed
        """
        cleaned = text.strip()
        
        # Try to extract JSON from markdown code blocks
        if "```" in cleaned:
            match = re.search(r'```(?:json)?(.*?)```', cleaned, re.DOTALL)
            if match:
                cleaned = match.group(1).strip()
        
        # Try to find JSON object
        if not cleaned.startswith('{'):
            # Look for first { and last }
            start = cleaned.find('{')
            end = cleaned.rfind('}')
            if start != -1 and end != -1:
                cleaned = cleaned[start:end+1]
        
        return json.loads(cleaned)
    
    def _response_to_patch(self, data: Dict[str, Any]) -> GraphPatch:
        """
        Convert LLM response to GraphPatch.
        
        Expected response format:
        {
          "reasoning": "Overall strategy...",
          "actions": [
            {
              "operation": "ADD_NODE",
              "node": {
                "id": "node1",
                "capability_name": "capability.name",
                "params": {"param": "value"}
              }
            },
            {
              "operation": "ADD_EDGE",
              "edge": {
                "source_node": "node1",
                "source_field": "output",
                "target_node": "node2",
                "target_param": "input"
              }
            }
          ]
        }
        
        Args:
            data: Parsed JSON response
            
        Returns:
            GraphPatch with all actions
            
        Raises:
            ValueError: If response format is invalid
        """
        reasoning = data.get("reasoning", "")
        actions_data = data.get("actions", [])
        
        if not actions_data:
            raise ValueError("LLM response contains no actions")
        
        actions = []
        for action_data in actions_data:
            operation_str = action_data.get("operation")
            
            # Parse operation (handle both uppercase and lowercase)
            try:
                # Try direct parsing first
                operation = PatchOperation(operation_str)
            except ValueError:
                # Try converting to lowercase with underscores
                try:
                    operation_lower = operation_str.lower() if operation_str else ""
                    operation = PatchOperation(operation_lower)
                except ValueError:
                    logger.warning(f"Unknown operation: {operation_str}, skipping")
                    continue
            
            # Create action based on operation type
            if operation == PatchOperation.ADD_NODE:
                node_data = action_data.get("node")
                if not node_data:
                    logger.warning("ADD_NODE action missing node data, skipping")
                    continue
                
                node = StepNode(
                    id=node_data.get("id"),
                    capability_name=node_data.get("capability_name"),
                    params=node_data.get("params", {}),
                    status=NodeStatus.PENDING,
                    metadata=node_data.get("metadata", {}),
                )
                
                actions.append(PatchAction(
                    operation=operation,
                    node=node,
                ))
            
            elif operation == PatchOperation.ADD_EDGE:
                edge_data = action_data.get("edge")
                if not edge_data:
                    logger.warning("ADD_EDGE action missing edge data, skipping")
                    continue
                
                edge = DataEdge(
                    source_node=edge_data.get("source_node"),
                    source_field=edge_data.get("source_field", "output"),
                    target_node=edge_data.get("target_node"),
                    target_param=edge_data.get("target_param", "input"),
                    transformer_name=edge_data.get("transformer_name"),
                    optional=edge_data.get("optional", False),
                )
                
                actions.append(PatchAction(
                    operation=operation,
                    edge=edge,
                ))
            
            elif operation == PatchOperation.FINISH:
                actions.append(PatchAction(
                    operation=operation,
                ))
            
            else:
                logger.warning(f"Unsupported operation: {operation}, skipping")
        
        return GraphPatch(
            actions=actions,
            reasoning=reasoning,
        )
    
    def _validate_dag_constraints(self, patch: GraphPatch) -> None:
        """
        Validate that the patch satisfies DAG constraints.
        
        Checks:
        1. All ADD_EDGE operations reference valid node IDs
        2. No self-loops (node cannot depend on itself)
        3. No cycles (using DFS)
        
        Args:
            patch: GraphPatch to validate
            
        Raises:
            ValueError: If DAG constraints are violated
            
        Requirements: 20.4
        """
        # Collect all node IDs
        node_ids = set()
        for action in patch.actions:
            if action.operation == PatchOperation.ADD_NODE and action.node:
                node_ids.add(action.node.id)
        
        # Build adjacency list for cycle detection
        adjacency = {node_id: [] for node_id in node_ids}
        
        # Validate edges
        for action in patch.actions:
            if action.operation == PatchOperation.ADD_EDGE and action.edge:
                edge = action.edge
                
                # Check that source and target nodes exist
                if edge.source_node not in node_ids:
                    raise ValueError(
                        f"Edge references unknown source node: {edge.source_node}"
                    )
                if edge.target_node not in node_ids:
                    raise ValueError(
                        f"Edge references unknown target node: {edge.target_node}"
                    )
                
                # Check for self-loops
                if edge.source_node == edge.target_node:
                    raise ValueError(
                        f"Self-loop detected: {edge.source_node} → {edge.target_node}"
                    )
                
                # Add to adjacency list
                adjacency[edge.source_node].append(edge.target_node)
        
        # Check for cycles using DFS
        visited = set()
        rec_stack = set()
        
        def has_cycle(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            
            for neighbor in adjacency.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            
            rec_stack.remove(node)
            return False
        
        for node_id in node_ids:
            if node_id not in visited:
                if has_cycle(node_id):
                    raise ValueError(
                        f"Cycle detected in graph starting from node: {node_id}"
                    )
        
        logger.info(f"DAG validation passed: {len(node_ids)} nodes, {len([a for a in patch.actions if a.operation == PatchOperation.ADD_EDGE])} edges")
