"""
Graph Adapters - Backward Compatibility Layer

Provides conversion functions between legacy Task/Step models and new GraphNode models.
"""
from .model_adapter import (
    task_to_execution_graph,
    step_to_step_node,
    execution_graph_to_task,
    step_node_to_step,
)

__all__ = [
    'task_to_execution_graph',
    'step_to_step_node',
    'execution_graph_to_task',
    'step_node_to_step',
]
