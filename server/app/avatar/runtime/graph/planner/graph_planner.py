"""
GraphPlanner - Adapter for InteractiveLLMPlanner with Graph Runtime

This module provides an adapter layer that wraps InteractiveLLMPlanner
to work with the Graph Runtime architecture while preserving existing
optimizations (loop detection, filesystem caching, output truncation).

Requirements: 6.1, 19.1, 19.2, 19.3, 19.4, 19.5
"""

from __future__ import annotations
from typing import Optional, Dict, Any, TYPE_CHECKING
import logging

from app.avatar.planner.planners.interactive import InteractiveLLMPlanner
from app.avatar.planner.models import Task, Step
from app.avatar.runtime.graph.planner.prompt_builder import PromptBuilder
from app.avatar.runtime.graph.models.graph_patch import (
    GraphPatch,
    PatchAction,
    PatchOperation,
)
from app.avatar.runtime.graph.models.step_node import StepNode, NodeStatus
import logging

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph

logger = logging.getLogger(__name__)


class GraphPlanner:
    """
    Adapter for InteractiveLLMPlanner to work with Graph Runtime.
    
    This class wraps InteractiveLLMPlanner and provides:
    1. ExecutionGraph input support (converts from Task model)
    2. GraphPatch output support (converts from Step model)
    3. Integration with PromptBuilder for prompt generation
    4. Preservation of existing optimizations:
       - Loop detection (similarity > 95% + same action → warning)
       - Filesystem caching (5 second expiry)
       - Output truncation (first 250 + last 300 chars)
    
    Requirements:
    - 6.1: Integrate PromptBuilder for prompt generation
    - 19.1: Support ExecutionGraph input
    - 19.2: Support GraphPatch output
    - 19.3: Preserve loop detection optimization
    - 19.4: Preserve filesystem caching optimization
    - 19.5: Preserve output truncation optimization
    """
    
    def __init__(
        self,
        llm_client: Any,
        capability_registry: Any = None,  # kept for backward compat, unused
        prompt_builder: Optional[PromptBuilder] = None,
    ):
        self.interactive_planner = InteractiveLLMPlanner(llm_client)
        self.prompt_builder = prompt_builder or PromptBuilder()
        logger.info("GraphPlanner initialized")
    
    async def plan_next_step(
        self,
        graph: 'ExecutionGraph',
        env_context: Dict[str, Any],
    ) -> Optional[GraphPatch]:
        """
        Plan the next step for ReAct mode (iterative planning).
        
        This method:
        1. Converts ExecutionGraph to Task model
        2. Calls InteractiveLLMPlanner.next_step()
        3. Converts Step to GraphPatch
        
        Args:
            graph: Current execution graph
            env_context: Environment context (workspace_path, available_skills, etc.)
            
        Returns:
            GraphPatch with ADD_NODE action, or None if finished
            
        Requirements: 6.1, 19.1, 19.2, 19.3, 19.4, 19.5
        """
        # Convert ExecutionGraph to Task model
        task = self._graph_to_task(graph)
        
        # Call InteractiveLLMPlanner (preserves all optimizations)
        step = await self.interactive_planner.next_step(task, env_context)
        
        # Convert Step to GraphPatch
        if step is None:
            # Task is finished
            return GraphPatch(
                actions=[
                    PatchAction(
                        operation=PatchOperation.FINISH,
                    )
                ],
                reasoning="Task completed successfully",
            )
        
        # Create ADD_NODE action
        patch = self._step_to_patch(step, graph)
        return patch
    
    def _graph_to_task(self, graph: 'ExecutionGraph') -> Task:
        """
        Convert ExecutionGraph to Task model.
        
        This enables InteractiveLLMPlanner to work with Graph Runtime.
        
        Args:
            graph: ExecutionGraph to convert
            
        Returns:
            Task model compatible with InteractiveLLMPlanner
        """
        # Convert StepNodes to Steps
        steps = []
        for node_id, node in graph.nodes.items():
            step = Step(
                id=node.id,
                order=len(steps),
                skill_name=node.capability_name,
                params=node.params,
                description=node.metadata.get("description", ""),
            )
            
            # Set step status and result based on node status
            if node.status == NodeStatus.SUCCESS:
                from app.avatar.planner.models import StepStatus, StepResult
                step.status = StepStatus.SUCCESS
                step.result = StepResult(
                    success=True,
                    output=node.outputs.get("output", node.outputs),
                )
            elif node.status == NodeStatus.FAILED:
                from app.avatar.planner.models import StepStatus, StepResult
                step.status = StepStatus.FAILED
                step.result = StepResult(
                    success=False,
                    error=node.error_message or "Unknown error",
                )
            elif node.status == NodeStatus.RUNNING:
                from app.avatar.planner.models import StepStatus
                step.status = StepStatus.RUNNING
            else:
                from app.avatar.planner.models import StepStatus
                step.status = StepStatus.PENDING
            
            steps.append(step)
        
        # Create Task
        task = Task(
            id=str(graph.id),
            goal=graph.goal,
            steps=steps,
            intent_id=None,  # No intent_id for graph-based tasks
        )
        
        return task
    
    def _step_to_patch(self, step: Step, graph: 'ExecutionGraph') -> GraphPatch:
        """
        Convert Step to GraphPatch.
        
        This creates an ADD_NODE action from the Step returned by
        InteractiveLLMPlanner.
        
        Args:
            step: Step from InteractiveLLMPlanner
            graph: Current execution graph
            
        Returns:
            GraphPatch with ADD_NODE action
        """
        # Create StepNode from Step
        node = StepNode(
            id=step.id,
            capability_name=step.skill_name,
            params=step.params,
            status=NodeStatus.PENDING,
            metadata={"description": step.description},
        )
        
        # Create ADD_NODE action
        action = PatchAction(
            operation=PatchOperation.ADD_NODE,
            node=node,
        )
        
        # Create GraphPatch
        patch = GraphPatch(
            actions=[action],
            reasoning=step.description,
        )
        
        return patch
    
    async def plan_complete_graph(
        self,
        goal: str,
        env_context: Dict[str, Any],
    ) -> GraphPatch:
        """
        Plan complete graph for DAG mode (one-shot planning).
        
        Delegates to DAGPlanner for complete graph generation.
        
        Args:
            goal: High-level goal description
            env_context: Environment context
            
        Returns:
            GraphPatch with all ADD_NODE and ADD_EDGE actions
            
        Requirements: 6.4, 20.1, 20.2, 20.3, 20.4
        """
        from app.avatar.runtime.graph.planner.dag_planner import DAGPlanner

        dag_planner = DAGPlanner(
            llm_client=self.interactive_planner._llm,
            prompt_builder=self.prompt_builder,
        )
        
        # Plan complete graph
        return await dag_planner.plan_complete_graph(goal, env_context)
    
    async def plan_repair(
        self,
        graph: 'ExecutionGraph',
        failed_node_id: str,
        error_message: str,
        env_context: Dict[str, Any],
    ) -> GraphPatch:
        """
        Plan repair for REPAIR mode (error recovery).
        
        This method:
        1. Generates REPAIR prompt using PromptBuilder
        2. Calls LLM to generate recovery plan
        3. Parses response into GraphPatch with recovery actions
        
        Integrates with:
        - CodeRepairManager: For python.run error fixes
        - Replanner: For task replanning logic
        
        Args:
            graph: Current execution graph
            failed_node_id: ID of the failed node
            error_message: Error message from the failure
            env_context: Environment context
            
        Returns:
            GraphPatch with recovery actions
            
        Requirements: 10.1, 10.2, 10.3, 10.4
        """
        from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult
        
        # Create failure context
        failed_node = graph.nodes.get(failed_node_id)
        if not failed_node:
            raise ValueError(f"Failed node not found: {failed_node_id}")
        
        # Count completed/failed/skipped nodes
        completed_nodes = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.SUCCESS)
        failed_nodes = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.FAILED)
        skipped_nodes = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.SKIPPED)
        
        failure_context = ExecutionResult(
            success=False,
            final_status="failed",
            completed_nodes=completed_nodes,
            failed_nodes=failed_nodes,
            skipped_nodes=skipped_nodes,
            execution_time=0.0,
            error_message=error_message,
        )
        
        # Generate repair prompt
        prompt = self.prompt_builder.build_repair_prompt(
            goal=graph.goal,
            graph=graph,
            failure_context=failure_context,
            failed_node_id=failed_node_id,
            error_message=error_message,
        )
        
        # Call LLM (run sync call in thread pool to avoid blocking event loop)
        import asyncio
        loop = asyncio.get_event_loop()
        raw_response = await loop.run_in_executor(None, self.interactive_planner._call_llm, prompt)
        
        # Parse response
        try:
            data = self.interactive_planner._parse_json(raw_response)
        except Exception as e:
            logger.error(f"Failed to parse repair response: {e}")
            raise ValueError(f"LLM repair output malformed: {e}\nRaw: {raw_response}")
        
        # Convert to GraphPatch
        actions = []
        for action_data in data.get("actions", []):
            operation_str = action_data.get("operation")
            
            # Normalize operation string to lowercase (handle both "ADD_NODE" and "add_node")
            if operation_str:
                operation_str = operation_str.lower()
            
            try:
                operation = PatchOperation(operation_str)
            except ValueError:
                logger.warning(f"Unknown operation in repair: {operation_str}, skipping")
                continue
            
            if operation == PatchOperation.ADD_NODE:
                node_data = action_data.get("node")
                if not node_data:
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
                    continue
                
                from app.avatar.runtime.graph.models.data_edge import DataEdge
                
                edge = DataEdge(
                    source_node=edge_data.get("source_node"),
                    source_field=edge_data.get("source_field", "output"),
                    target_node=edge_data.get("target_node"),
                    target_param=edge_data.get("target_param"),
                    transformer_name=edge_data.get("transformer_name"),
                    optional=edge_data.get("optional", False),
                )
                
                actions.append(PatchAction(
                    operation=operation,
                    edge=edge,
                ))
        
        return GraphPatch(
            actions=actions,
            reasoning=data.get("analysis", "") + " | " + data.get("recovery_strategy", ""),
        )
