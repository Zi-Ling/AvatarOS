"""
Model Adapter - Task/Step to ExecutionGraph/StepNode Conversion

Provides backward compatibility by converting legacy Task/Step models to new graph models.

Conversion Strategy:
- Task → ExecutionGraph: Convert task structure to graph with nodes and edges
- Step → StepNode: Map step fields to node fields with compatibility layer
- Preserve all existing fields while adding new GraphNode fields
- Infer data dependencies from step dependencies

Requirements: 23.1, 23.2
"""
from __future__ import annotations

from typing import Dict, List, Optional, Any
from datetime import datetime
import uuid

from app.avatar.planner.models.task import Task, TaskStatus
from app.avatar.planner.models.step import Step, StepStatus, StepResult
from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph, GraphStatus
from app.avatar.runtime.graph.models.step_node import StepNode, NodeStatus, RetryPolicy
from app.avatar.runtime.graph.models.data_edge import DataEdge


def _task_status_to_graph_status(task_status: TaskStatus) -> GraphStatus:
    """Convert TaskStatus to GraphStatus"""
    mapping = {
        TaskStatus.PENDING: GraphStatus.PENDING,
        TaskStatus.RUNNING: GraphStatus.RUNNING,
        TaskStatus.SUCCESS: GraphStatus.SUCCESS,
        TaskStatus.FAILED: GraphStatus.FAILED,
        TaskStatus.PARTIAL_SUCCESS: GraphStatus.SUCCESS,  # Map partial success to success
    }
    return mapping.get(task_status, GraphStatus.PENDING)


def _graph_status_to_task_status(graph_status: GraphStatus) -> TaskStatus:
    """Convert GraphStatus to TaskStatus"""
    mapping = {
        GraphStatus.PENDING: TaskStatus.PENDING,
        GraphStatus.RUNNING: TaskStatus.RUNNING,
        GraphStatus.SUCCESS: TaskStatus.SUCCESS,
        GraphStatus.FAILED: TaskStatus.FAILED,
        GraphStatus.PAUSED: TaskStatus.RUNNING,  # Map paused to running
        GraphStatus.CANCELLED: TaskStatus.FAILED,  # Map cancelled to failed
    }
    return mapping.get(graph_status, TaskStatus.PENDING)


def _step_status_to_node_status(step_status: StepStatus) -> NodeStatus:
    """Convert StepStatus to NodeStatus"""
    mapping = {
        StepStatus.PENDING: NodeStatus.PENDING,
        StepStatus.RUNNING: NodeStatus.RUNNING,
        StepStatus.SUCCESS: NodeStatus.SUCCESS,
        StepStatus.FAILED: NodeStatus.FAILED,
        StepStatus.SKIPPED: NodeStatus.SKIPPED,
    }
    return mapping.get(step_status, NodeStatus.PENDING)


def _node_status_to_step_status(node_status: NodeStatus) -> StepStatus:
    """Convert NodeStatus to StepStatus"""
    mapping = {
        NodeStatus.PENDING: StepStatus.PENDING,
        NodeStatus.RUNNING: StepStatus.RUNNING,
        NodeStatus.SUCCESS: StepStatus.SUCCESS,
        NodeStatus.FAILED: StepStatus.FAILED,
        NodeStatus.SKIPPED: StepStatus.SKIPPED,
        NodeStatus.PAUSED: StepStatus.PENDING,  # Map paused to pending
        NodeStatus.CANCELLED: StepStatus.SKIPPED,  # Map cancelled to skipped
    }
    return mapping.get(node_status, StepStatus.PENDING)


def step_to_step_node(step: Step) -> StepNode:
    """
    Convert Step to StepNode.
    
    Preserves existing fields while adding new GraphNode fields:
    - Maps step.skill_name to node.capability_name
    - Maps step.params to node.params
    - Maps step.status to node.status
    - Maps step.result to node.outputs
    - Creates RetryPolicy from step.max_retry
    - Preserves step.depends_on in metadata for edge creation
    
    Args:
        step: Legacy Step model
        
    Returns:
        StepNode with converted fields
    """
    # Convert status
    node_status = _step_status_to_node_status(step.status)
    
    # Create retry policy from max_retry
    retry_policy = RetryPolicy(
        max_retries=step.max_retry,
        backoff_multiplier=2.0,
        initial_delay=1.0
    )
    
    # Convert result to outputs
    outputs = {}
    error_message = None
    if step.result:
        if step.result.success:
            outputs = {
                "ok": True,
                "data": step.result.output,
                "meta": {}
            }
        else:
            outputs = {
                "ok": False,
                "data": None,
                "meta": {"error": step.result.error}
            }
            error_message = step.result.error
    
    # Create metadata with legacy fields
    metadata = {
        "order": step.order,
        "depends_on": step.depends_on.copy() if step.depends_on else [],
        "description": step.description,
        "legacy_step_id": step.id,
    }
    
    # Create StepNode
    node = StepNode(
        id=step.id,
        capability_name=step.skill_name,
        params=step.params.copy() if step.params else {},
        status=node_status,
        outputs=outputs,
        retry_policy=retry_policy,
        metadata=metadata,
        error_message=error_message,
        retry_count=step.retry
    )
    
    return node


def step_node_to_step(node: StepNode) -> Step:
    """
    Convert StepNode back to Step for backward compatibility.
    
    Args:
        node: StepNode model
        
    Returns:
        Step with converted fields
    """
    # Convert status
    step_status = _node_status_to_step_status(node.status)
    
    # Extract legacy fields from metadata
    order = node.metadata.get("order", 0)
    depends_on = node.metadata.get("depends_on", [])
    description = node.metadata.get("description")
    
    # Convert outputs to result
    result = None
    if node.outputs:
        ok = node.outputs.get("ok", False)
        data = node.outputs.get("data")
        meta = node.outputs.get("meta", {})
        error = meta.get("error") or node.error_message
        
        result = StepResult(
            success=ok,
            output=data,
            error=error
        )
    
    # Create Step
    step = Step(
        id=node.id,
        order=order,
        skill_name=node.capability_name,
        params=node.params.copy() if node.params else {},
        status=step_status,
        result=result,
        retry=node.retry_count,
        max_retry=node.retry_policy.max_retries,
        depends_on=depends_on,
        description=description
    )
    
    return step


def task_to_execution_graph(task: Task) -> ExecutionGraph:
    """
    Convert Task to ExecutionGraph.
    
    Conversion process:
    1. Create ExecutionGraph with task metadata
    2. Convert each Step to StepNode
    3. Create DataEdges based on step dependencies
    4. Build adjacency indexes
    
    Data dependency inference:
    - For each step with depends_on, create edges from dependency steps
    - Edge connects previous step's output to current step's input
    - Uses generic field names: "output" → "input"
    
    Args:
        task: Legacy Task model
        
    Returns:
        ExecutionGraph with nodes and edges
    """
    # Create ExecutionGraph
    graph = ExecutionGraph(
        id=task.id,
        goal=task.goal,
        status=_task_status_to_graph_status(task.status),
        metadata={
            "intent_id": task.intent_id,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "legacy_task": True,
            **task.metadata
        },
        created_at=datetime.fromtimestamp(task.created_at),
        updated_at=datetime.fromtimestamp(task.updated_at)
    )
    
    # Convert steps to nodes
    for step in task.steps:
        node = step_to_step_node(step)
        graph.add_node(node)
    
    # Create edges based on dependencies
    edge_counter = 0
    for step in task.steps:
        if step.depends_on:
            for dep_step_id in step.depends_on:
                # Create edge from dependency to current step
                edge_id = f"edge_{edge_counter}"
                edge_counter += 1
                
                edge = DataEdge(
                    id=edge_id,
                    source_node=dep_step_id,
                    source_field="data",  # Generic output field
                    target_node=step.id,
                    target_param=f"input_from_{dep_step_id}",  # Generic input param
                    transformer_name=None,
                    optional=False
                )
                
                graph.add_edge(edge)
    
    return graph


def execution_graph_to_task(graph: ExecutionGraph) -> Task:
    """
    Convert ExecutionGraph back to Task for backward compatibility.
    
    Args:
        graph: ExecutionGraph model
        
    Returns:
        Task with converted fields
    """
    # Convert nodes to steps
    steps = []
    for node_id, node in graph.nodes.items():
        step = step_node_to_step(node)
        steps.append(step)
    
    # Sort steps by order
    steps.sort(key=lambda s: s.order)
    
    # Extract metadata
    metadata = graph.metadata.copy()
    intent_id = metadata.pop("intent_id", None)
    legacy_created_at = metadata.pop("created_at", graph.created_at.timestamp())
    legacy_updated_at = metadata.pop("updated_at", graph.updated_at.timestamp())
    metadata.pop("legacy_task", None)
    
    # Create Task
    task = Task(
        id=graph.id,
        goal=graph.goal,
        steps=steps,
        intent_id=intent_id,
        status=_graph_status_to_task_status(graph.status),
        created_at=legacy_created_at,
        updated_at=legacy_updated_at,
        metadata=metadata
    )
    
    return task
