"""
Scheduler - Ready Node Detection with O(V) Complexity

The Scheduler determines which nodes are ready for execution by checking
dependency satisfaction using the ExecutionGraph's adjacency indexes.

Key Features:
- O(V) time complexity for ready node detection (V = number of nodes)
- Priority-based ordering when multiple nodes are ready
- Max concurrent nodes limit enforcement
- Deadlock detection for circular dependencies
- Support for optional dependencies

Algorithm:
1. Iterate through all PENDING nodes (O(V))
2. For each node, check incoming edges using adjacency index (O(1) lookup)
3. Verify all required dependencies have SUCCESS status
4. Apply priority sorting and concurrency limits
5. Detect deadlocks when no nodes are ready but graph is not complete
"""
from typing import List, Dict, Any, Set, Optional
from ..models.execution_graph import ExecutionGraph
from ..models.step_node import StepNode, NodeStatus
from ..models.data_edge import DataEdge


class DeadlockError(Exception):
    """Raised when a circular dependency deadlock is detected"""
    pass


class Scheduler:
    """
    Determines which nodes are ready for execution.
    
    Uses adjacency indexes for O(V) complexity where V is the number of nodes.
    A node is ready when all its required incoming dependencies have SUCCESS status.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the Scheduler.
        
        Args:
            config: Configuration dictionary with optional keys:
                - max_concurrent_nodes: Maximum number of nodes to execute in parallel (default: 10)
        """
        config = config or {}
        self.max_concurrent_nodes = config.get('max_concurrent_nodes', 10)
    
    def get_ready_nodes(self, graph: ExecutionGraph) -> List[StepNode]:
        """
        Identify nodes ready for execution.
        
        A node is ready when:
        1. Its status is PENDING
        2. All required incoming dependencies are satisfied (source node has SUCCESS status)
        3. Optional dependencies don't block execution
        
        Time complexity: O(V) where V is number of nodes
        
        Args:
            graph: The execution graph to analyze
            
        Returns:
            List of ready nodes, sorted by priority and limited by max_concurrent_nodes
            
        Raises:
            DeadlockError: If a circular dependency deadlock is detected
        """
        ready = []
        
        # Iterate through all nodes - O(V)
        for node_id, node in graph.nodes.items():
            # Skip non-pending nodes
            if node.status != NodeStatus.PENDING:
                continue
            
            # Check all incoming edges using adjacency index - O(1) lookup + O(k) edge check
            # where k is the number of incoming edges (typically small)
            incoming_edges = graph.get_incoming_edges(node_id)
            
            if self._dependencies_satisfied(graph, incoming_edges):
                ready.append(node)
        
        # Check for deadlock: no ready nodes but pending nodes exist
        if not ready and self._has_pending_nodes(graph):
            # Check if this is a deadlock (circular dependencies) or just waiting for running nodes
            if not self._has_running_nodes(graph):
                self._detect_and_report_deadlock(graph)
        
        # Apply priority sorting if metadata present
        # Higher priority values execute first
        ready.sort(key=lambda n: n.metadata.get('priority', 0), reverse=True)
        
        # Respect concurrency limit
        return ready[:self.max_concurrent_nodes]
    
    def _dependencies_satisfied(
        self,
        graph: ExecutionGraph,
        incoming_edges: List[DataEdge]
    ) -> bool:
        """
        Check if all required dependencies are satisfied.
        
        A dependency is satisfied when:
        - The edge is optional (doesn't block execution), OR
        - The source node has SUCCESS status
        
        Args:
            graph: The execution graph
            incoming_edges: List of incoming edges to check
            
        Returns:
            True if all required dependencies are satisfied, False otherwise
        """
        for edge in incoming_edges:
            source_node = graph.nodes.get(edge.source_node)
            
            # Validate source node exists
            if not source_node:
                # Missing source node means dependency cannot be satisfied
                return False
            
            # Optional edges don't block execution
            if edge.optional:
                continue
            
            # Required edge must have successful source
            if source_node.status != NodeStatus.SUCCESS:
                return False
        
        return True
    
    def _has_pending_nodes(self, graph: ExecutionGraph) -> bool:
        """
        Check if there are any pending nodes in the graph.
        
        Args:
            graph: The execution graph
            
        Returns:
            True if any nodes have PENDING status
        """
        return any(node.status == NodeStatus.PENDING for node in graph.nodes.values())
    
    def _has_running_nodes(self, graph: ExecutionGraph) -> bool:
        """
        Check if there are any running nodes in the graph.
        
        Args:
            graph: The execution graph
            
        Returns:
            True if any nodes have RUNNING status
        """
        return any(node.status == NodeStatus.RUNNING for node in graph.nodes.values())
    
    def _detect_and_report_deadlock(self, graph: ExecutionGraph) -> None:
        """
        Detect circular dependencies and raise DeadlockError with details.
        
        Uses DFS to detect cycles in the dependency graph.
        
        Args:
            graph: The execution graph
            
        Raises:
            DeadlockError: If circular dependencies are detected
        """
        # Find all pending nodes
        pending_nodes = [
            node_id for node_id, node in graph.nodes.items()
            if node.status == NodeStatus.PENDING
        ]
        
        if not pending_nodes:
            return
        
        # Use DFS to detect cycles among pending nodes
        visited = set()
        rec_stack = set()
        cycle_path = []
        
        def has_cycle(node_id: str, path: List[str]) -> bool:
            """DFS to detect cycles"""
            visited.add(node_id)
            rec_stack.add(node_id)
            path.append(node_id)
            
            # Check outgoing edges
            for edge_id in graph.outgoing_edges_index.get(node_id, []):
                edge = graph.edges[edge_id]
                target = edge.target_node
                target_node = graph.nodes.get(target)
                
                # Only follow edges to pending nodes
                if not target_node or target_node.status != NodeStatus.PENDING:
                    continue
                
                if target not in visited:
                    if has_cycle(target, path):
                        return True
                elif target in rec_stack:
                    # Found a cycle
                    cycle_path.extend(path[path.index(target):])
                    return True
            
            path.pop()
            rec_stack.remove(node_id)
            return False
        
        # Check each pending node for cycles
        for node_id in pending_nodes:
            if node_id not in visited:
                if has_cycle(node_id, []):
                    # Format cycle information
                    cycle_str = " -> ".join(cycle_path)
                    raise DeadlockError(
                        f"Circular dependency detected: {cycle_str}. "
                        f"These nodes are waiting for each other to complete."
                    )
        
        # If no cycle found but still deadlocked, it's a different issue
        # (e.g., all dependencies failed)
        pending_details = []
        for node_id in pending_nodes:
            node = graph.nodes[node_id]
            incoming = graph.get_incoming_edges(node_id)
            failed_deps = []
            
            for edge in incoming:
                if not edge.optional:
                    source = graph.nodes.get(edge.source_node)
                    if source and source.status != NodeStatus.SUCCESS:
                        failed_deps.append(f"{edge.source_node} ({source.status.value})")
            
            if failed_deps:
                pending_details.append(
                    f"{node_id} waiting for: {', '.join(failed_deps)}"
                )
        
        if pending_details:
            raise DeadlockError(
                f"Deadlock detected: {len(pending_nodes)} pending nodes cannot proceed. "
                f"Details:\n" + "\n".join(pending_details)
            )
        
        # Generic deadlock error
        raise DeadlockError(
            f"Deadlock detected: {len(pending_nodes)} pending nodes with no ready nodes "
            f"and no running nodes."
        )
    
    def get_max_concurrent_nodes(self) -> int:
        """
        Get the maximum number of concurrent nodes allowed.
        
        Returns:
            Maximum concurrent nodes limit
        """
        return self.max_concurrent_nodes
    
    def set_max_concurrent_nodes(self, limit: int) -> None:
        """
        Set the maximum number of concurrent nodes allowed.
        
        Args:
            limit: New maximum concurrent nodes limit (must be > 0)
            
        Raises:
            ValueError: If limit is not positive
        """
        if limit <= 0:
            raise ValueError(f"max_concurrent_nodes must be positive, got {limit}")
        self.max_concurrent_nodes = limit
