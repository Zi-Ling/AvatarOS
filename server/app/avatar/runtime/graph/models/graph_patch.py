"""
GraphPatch - LLM-Generated Graph Modifications

Represents a set of operations to modify an ExecutionGraph.
Used by GraphPlanner to communicate graph changes.
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional
from enum import Enum
from pydantic import BaseModel, Field


class PatchOperation(str, Enum):
    """Graph patch operation types"""
    ADD_NODE = "add_node"
    ADD_EDGE = "add_edge"
    REMOVE_NODE = "remove_node"
    REMOVE_EDGE = "remove_edge"
    FINISH = "finish"


class PatchAction(BaseModel):
    """
    Single operation in a GraphPatch.
    
    Each action specifies one modification to the graph.
    """
    operation: PatchOperation = Field(description="Type of operation")
    
    # For ADD_NODE
    node: Optional['StepNode'] = Field(default=None, description="Node to add (for ADD_NODE)")
    
    # For ADD_EDGE
    edge: Optional['DataEdge'] = Field(default=None, description="Edge to add (for ADD_EDGE)")
    
    # For REMOVE_NODE
    node_id: Optional[str] = Field(default=None, description="Node ID to remove (for REMOVE_NODE)")
    
    # For REMOVE_EDGE
    edge_id: Optional[str] = Field(default=None, description="Edge ID to remove (for REMOVE_EDGE)")
    
    def validate_action(self) -> None:
        """
        Validate that action has required fields for its operation type.
        
        Raises:
            ValueError: If action is invalid
        """
        if self.operation == PatchOperation.ADD_NODE:
            if self.node is None:
                raise ValueError("ADD_NODE requires 'node' field")
        
        elif self.operation == PatchOperation.ADD_EDGE:
            if self.edge is None:
                raise ValueError("ADD_EDGE requires 'edge' field")
        
        elif self.operation == PatchOperation.REMOVE_NODE:
            if self.node_id is None:
                raise ValueError("REMOVE_NODE requires 'node_id' field")
        
        elif self.operation == PatchOperation.REMOVE_EDGE:
            if self.edge_id is None:
                raise ValueError("REMOVE_EDGE requires 'edge_id' field")
        
        elif self.operation == PatchOperation.FINISH:
            # FINISH requires no additional fields
            pass


class GraphPatch(BaseModel):
    """
    LLM-generated graph modification operations.
    
    Applied atomically to the ExecutionGraph by GraphRuntime.
    
    Example:
        patch = GraphPatch(
            actions=[
                PatchAction(operation=PatchOperation.ADD_NODE, node=node1),
                PatchAction(operation=PatchOperation.ADD_EDGE, edge=edge1),
                PatchAction(operation=PatchOperation.FINISH)
            ],
            reasoning="Added file read node and connected to processing node"
        )
    """
    
    actions: List[PatchAction] = Field(description="List of operations to apply")
    reasoning: str = Field(description="LLM's reasoning for this patch")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    def validate(self) -> None:
        """
        Validate all actions in the patch.
        
        Raises:
            ValueError: If any action is invalid
        """
        for i, action in enumerate(self.actions):
            try:
                action.validate_action()
            except ValueError as e:
                raise ValueError(f"Action {i} is invalid: {e}")
    
    def has_finish(self) -> bool:
        """Check if patch contains a FINISH operation"""
        return any(action.operation == PatchOperation.FINISH for action in self.actions)
    
    def count_operations(self) -> Dict[str, int]:
        """Count operations by type"""
        counts = {op.value: 0 for op in PatchOperation}
        for action in self.actions:
            counts[action.operation.value] += 1
        return counts
    
    def get_added_nodes(self) -> List['StepNode']:
        """Get all nodes being added"""
        return [
            action.node
            for action in self.actions
            if action.operation == PatchOperation.ADD_NODE and action.node
        ]
    
    def get_added_edges(self) -> List['DataEdge']:
        """Get all edges being added"""
        return [
            action.edge
            for action in self.actions
            if action.operation == PatchOperation.ADD_EDGE and action.edge
        ]


# Forward references for type hints
from .step_node import StepNode
from .data_edge import DataEdge

# Update forward references
PatchAction.model_rebuild()
GraphPatch.model_rebuild()
