"""
ExecutionGraph - Typed Data Flow Graph Model

Represents a complete workflow as a directed acyclic graph (DAG).
Maintains adjacency indexes for O(V) dependency queries.
"""
from __future__ import annotations

from typing import Dict, List, Any, Optional
from enum import Enum
from datetime import datetime, UTC
from pydantic import BaseModel, Field
import uuid


def generate_uuid7() -> str:
    """Generate sortable, time-ordered UUID7"""
    # Python 3.13+ has uuid.uuid7(), for older versions use uuid4
    try:
        return str(uuid.uuid7())
    except AttributeError:
        # Fallback for Python < 3.13
        return str(uuid.uuid4())


class GraphStatus(str, Enum):
    """Graph execution status"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class ExecutionGraph(BaseModel):
    """
    Represents a complete workflow as a directed acyclic graph (DAG).
    
    Maintains adjacency indexes for O(V) dependency queries:
    - incoming_edges_index: Map of node_id -> list of incoming edge_ids
    - outgoing_edges_index: Map of node_id -> list of outgoing edge_ids
    
    This enables O(1) edge addition/removal and O(V) ready node detection.
    """
    
    id: str = Field(default_factory=generate_uuid7, description="Unique graph identifier (uuid7)")
    goal: str = Field(description="High-level user intent")
    nodes: Dict[str, 'StepNode'] = Field(default_factory=dict, description="Map of node_id to StepNode")
    edges: Dict[str, 'DataEdge'] = Field(default_factory=dict, description="Map of edge_id to DataEdge")
    status: GraphStatus = Field(default=GraphStatus.PENDING)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    
    # Adjacency indexes for O(V) scheduling (stored as regular fields for serialization)
    incoming_edges_index: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Map of node_id to list of incoming edge_ids"
    )
    outgoing_edges_index: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Map of node_id to list of outgoing edge_ids"
    )
    
    class Config:
        # Allow field aliases
        populate_by_name = True
    
    def add_node(self, node: 'StepNode') -> None:
        """
        Add a node to the graph and initialize adjacency indexes.
        
        Time complexity: O(1)
        """
        self.nodes[node.id] = node
        self.incoming_edges_index[node.id] = []
        self.outgoing_edges_index[node.id] = []
        self.updated_at = datetime.now(UTC)
    
    def add_edge(self, edge: 'DataEdge') -> None:
        """
        Add an edge and update adjacency indexes in O(1) time.
        
        Validates that both source and target nodes exist before adding the edge.
        
        Time complexity: O(1)
        
        Raises:
            ValueError: If source or target node doesn't exist
        """
        # Validate nodes exist
        if edge.source_node not in self.nodes:
            raise ValueError(f"Source node '{edge.source_node}' does not exist in graph")
        if edge.target_node not in self.nodes:
            raise ValueError(f"Target node '{edge.target_node}' does not exist in graph")
        
        self.edges[edge.id] = edge
        self.incoming_edges_index[edge.target_node].append(edge.id)
        self.outgoing_edges_index[edge.source_node].append(edge.id)
        self.updated_at = datetime.now(UTC)
    
    def remove_edge(self, edge_id: str) -> None:
        """
        Remove an edge and update adjacency indexes in O(1) time.
        
        Time complexity: O(1)
        """
        edge = self.edges.pop(edge_id)
        self.incoming_edges_index[edge.target_node].remove(edge_id)
        self.outgoing_edges_index[edge.source_node].remove(edge_id)
        self.updated_at = datetime.utcnow()
    
    def get_incoming_edges(self, node_id: str) -> List['DataEdge']:
        """
        Get all incoming edges for a node in O(1) time.
        
        Time complexity: O(1) for lookup + O(k) for edge retrieval where k is number of incoming edges
        """
        return [self.edges[eid] for eid in self.incoming_edges_index.get(node_id, [])]
    
    def get_outgoing_edges(self, node_id: str) -> List['DataEdge']:
        """
        Get all outgoing edges for a node in O(1) time.
        
        Time complexity: O(1) for lookup + O(k) for edge retrieval where k is number of outgoing edges
        """
        return [self.edges[eid] for eid in self.outgoing_edges_index.get(node_id, [])]
    
    def validate_dag(self) -> bool:
        """
        Validate that the graph is a DAG (no cycles) using DFS.
        
        Time complexity: O(V + E) where V is nodes and E is edges
        
        Returns:
            True if graph is a valid DAG, False if cycles detected
        """
        visited = set()
        rec_stack = set()
        
        def has_cycle(node_id: str) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)
            
            for edge_id in self.outgoing_edges_index.get(node_id, []):
                edge = self.edges[edge_id]
                target = edge.target_node
                
                if target not in visited:
                    if has_cycle(target):
                        return True
                elif target in rec_stack:
                    return True
            
            rec_stack.remove(node_id)
            return False
        
        for node_id in self.nodes:
            if node_id not in visited:
                if has_cycle(node_id):
                    return False
        return True
    
    def to_mermaid(self) -> str:
        """
        Generate Mermaid diagram representation.
        
        Returns:
            Mermaid graph definition string
        """
        from .step_node import NodeStatus
        
        lines = ["graph TD"]
        
        # Node definitions with status colors
        for node_id, node in self.nodes.items():
            color_map = {
                NodeStatus.PENDING: "gray",
                NodeStatus.RUNNING: "yellow",
                NodeStatus.SUCCESS: "green",
                NodeStatus.FAILED: "red",
                NodeStatus.SKIPPED: "blue",
                NodeStatus.PAUSED: "orange",
                NodeStatus.CANCELLED: "purple"
            }
            color = color_map.get(node.status, "gray")
            
            # Escape special characters in node labels
            label = f"{node_id}: {node.capability_name}".replace('"', '\\"')
            lines.append(f'    {node_id}["{label}"]')
            lines.append(f'    style {node_id} fill:{color}')
        
        # Edge definitions
        for edge in self.edges.values():
            label = f"{edge.source_field} → {edge.target_param}"
            if edge.transformer_name:
                label += f" ({edge.transformer_name})"
            label = label.replace('"', '\\"')
            lines.append(f'    {edge.source_node} -->|"{label}"| {edge.target_node}')
        
        # Legend
        lines.append("    subgraph Legend")
        lines.append("        L1[PENDING]")
        lines.append("        L2[RUNNING]")
        lines.append("        L3[SUCCESS]")
        lines.append("        L4[FAILED]")
        lines.append("        L5[SKIPPED]")
        lines.append("    end")
        lines.append("    style L1 fill:gray")
        lines.append("    style L2 fill:yellow")
        lines.append("    style L3 fill:green")
        lines.append("    style L4 fill:red")
        lines.append("    style L5 fill:blue")
        
        return "\n".join(lines)
    
    def to_json(self) -> str:
        """
        Serialize to JSON for persistence.
        
        Returns:
            JSON string representation
        """
        return self.model_dump_json(indent=2)


# Forward references for type hints
from .step_node import StepNode
from .data_edge import DataEdge

# Update forward references
ExecutionGraph.model_rebuild()
