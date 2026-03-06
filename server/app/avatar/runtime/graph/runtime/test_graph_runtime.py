"""
Tests for GraphRuntime

Tests cover:
- Main execution loop (get ready nodes → execute → update state)
- Parallel execution of ready nodes
- Failure propagation to downstream nodes
- Terminal state detection
- Stuck state detection (for ReAct mode)
- Event emission
- Final status computation
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

from app.avatar.runtime.graph.runtime.graph_runtime import GraphRuntime, ExecutionResult
from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph, GraphStatus
from app.avatar.runtime.graph.models.step_node import StepNode, NodeStatus, RetryPolicy
from app.avatar.runtime.graph.models.data_edge import DataEdge
from app.avatar.runtime.graph.scheduler.scheduler import Scheduler
from app.avatar.runtime.graph.executor.node_runner import NodeRunner, NodeResult
from app.avatar.runtime.graph.context.execution_context import ExecutionContext


@pytest.fixture
def mock_scheduler():
    """Create a mock Scheduler"""
    scheduler = Mock(spec=Scheduler)
    scheduler.max_concurrent_nodes = 10
    return scheduler


@pytest.fixture
def mock_node_runner():
    """Create a mock NodeRunner"""
    node_runner = Mock(spec=NodeRunner)
    node_runner.run_node = AsyncMock()
    node_runner.run_nodes_parallel = AsyncMock()
    return node_runner


@pytest.fixture
def mock_context():
    """Create a mock ExecutionContext"""
    context = Mock(spec=ExecutionContext)
    context.graph_id = "test-graph"
    context.set_node_output = Mock()
    context.get_node_output = Mock(return_value={})
    return context


@pytest.fixture
def mock_event_bus():
    """Create a mock EventBus"""
    event_bus = Mock()
    event_bus.publish = Mock()
    return event_bus


@pytest.fixture
def graph_runtime(mock_scheduler, mock_node_runner, mock_context, mock_event_bus):
    """Create a GraphRuntime instance with mocks"""
    return GraphRuntime(
        scheduler=mock_scheduler,
        node_runner=mock_node_runner,
        context=mock_context,
        event_bus=mock_event_bus,
        config={'max_execution_time': 60}
    )


@pytest.fixture
def simple_graph():
    """Create a simple linear graph: n1 → n2 → n3"""
    graph = ExecutionGraph(
        id="test-graph",
        goal="Test execution"
    )
    
    # Create nodes
    n1 = StepNode(id="n1", capability_name="cap1")
    n2 = StepNode(id="n2", capability_name="cap2")
    n3 = StepNode(id="n3", capability_name="cap3")
    
    graph.add_node(n1)
    graph.add_node(n2)
    graph.add_node(n3)
    
    # Create edges
    e1 = DataEdge(
        id="e1",
        source_node="n1",
        source_field="output",
        target_node="n2",
        target_param="input"
    )
    e2 = DataEdge(
        id="e2",
        source_node="n2",
        source_field="output",
        target_node="n3",
        target_param="input"
    )
    
    graph.add_edge(e1)
    graph.add_edge(e2)
    
    return graph


@pytest.fixture
def parallel_graph():
    """Create a graph with parallel execution: n1 → [n2, n3] → n4"""
    graph = ExecutionGraph(
        id="parallel-graph",
        goal="Test parallel execution"
    )
    
    # Create nodes
    n1 = StepNode(id="n1", capability_name="cap1")
    n2 = StepNode(id="n2", capability_name="cap2")
    n3 = StepNode(id="n3", capability_name="cap3")
    n4 = StepNode(id="n4", capability_name="cap4")
    
    graph.add_node(n1)
    graph.add_node(n2)
    graph.add_node(n3)
    graph.add_node(n4)
    
    # Create edges: n1 → n2, n1 → n3, n2 → n4, n3 → n4
    graph.add_edge(DataEdge(
        id="e1", source_node="n1", source_field="output",
        target_node="n2", target_param="input"
    ))
    graph.add_edge(DataEdge(
        id="e2", source_node="n1", source_field="output",
        target_node="n3", target_param="input"
    ))
    graph.add_edge(DataEdge(
        id="e3", source_node="n2", source_field="output",
        target_node="n4", target_param="input1"
    ))
    graph.add_edge(DataEdge(
        id="e4", source_node="n3", source_field="output",
        target_node="n4", target_param="input2"
    ))
    
    return graph


class TestGraphRuntimeExecution:
    """Test main execution loop"""
    
    @pytest.mark.asyncio
    async def test_execute_simple_linear_graph(
        self, graph_runtime, simple_graph, mock_scheduler, mock_node_runner
    ):
        """Test executing a simple linear graph"""
        # Setup: scheduler returns nodes in order
        call_count = [0]
        
        def get_ready_nodes_side_effect(graph):
            call_count[0] += 1
            if call_count[0] == 1:
                return [graph.nodes["n1"]]
            elif call_count[0] == 2:
                return [graph.nodes["n2"]]
            elif call_count[0] == 3:
                return [graph.nodes["n3"]]
            else:
                return []
        
        mock_scheduler.get_ready_nodes = Mock(side_effect=get_ready_nodes_side_effect)
        
        # Mock node runner to mark nodes as successful
        async def run_nodes_parallel_side_effect(graph, nodes, context, max_concurrent=None):
            results = []
            for node in nodes:
                node.mark_success({"output": f"result from {node.id}"})
                results.append(NodeResult(success=True, outputs=node.outputs))
            return results
        
        mock_node_runner.run_nodes_parallel = AsyncMock(side_effect=run_nodes_parallel_side_effect)
        
        # Execute
        result = await graph_runtime.execute_graph(simple_graph)
        
        # Verify
        assert result.success is True
        assert simple_graph.status == GraphStatus.SUCCESS
        assert simple_graph.nodes["n1"].status == NodeStatus.SUCCESS
        assert simple_graph.nodes["n2"].status == NodeStatus.SUCCESS
        assert simple_graph.nodes["n3"].status == NodeStatus.SUCCESS
        assert mock_node_runner.run_nodes_parallel.call_count == 3
    
    @pytest.mark.asyncio
    async def test_execute_parallel_nodes(
        self, graph_runtime, parallel_graph, mock_scheduler, mock_node_runner
    ):
        """Test parallel execution of independent nodes"""
        call_count = [0]
        
        def get_ready_nodes_side_effect(graph):
            call_count[0] += 1
            if call_count[0] == 1:
                return [graph.nodes["n1"]]
            elif call_count[0] == 2:
                # n2 and n3 are ready in parallel
                return [graph.nodes["n2"], graph.nodes["n3"]]
            elif call_count[0] == 3:
                return [graph.nodes["n4"]]
            else:
                return []
        
        mock_scheduler.get_ready_nodes = Mock(side_effect=get_ready_nodes_side_effect)
        
        # Track parallel execution
        execution_times = {}
        
        async def run_nodes_parallel_side_effect(graph, nodes, context, max_concurrent=None):
            results = []
            for node in nodes:
                start = asyncio.get_event_loop().time()
                await asyncio.sleep(0.01)  # Simulate work
                execution_times[node.id] = asyncio.get_event_loop().time() - start
                node.mark_success({"output": f"result from {node.id}"})
                results.append(NodeResult(success=True, outputs=node.outputs))
            return results
        
        mock_node_runner.run_nodes_parallel = AsyncMock(side_effect=run_nodes_parallel_side_effect)
        
        # Execute
        result = await graph_runtime.execute_graph(parallel_graph)
        
        # Verify
        assert result.success is True
        assert parallel_graph.status == GraphStatus.SUCCESS
        assert mock_node_runner.run_nodes_parallel.call_count == 3
        
        # Verify n2 and n3 were executed (they should be in execution_times)
        assert "n2" in execution_times
        assert "n3" in execution_times
    
    @pytest.mark.asyncio
    async def test_execute_ready_nodes_for_react_mode(
        self, graph_runtime, simple_graph, mock_scheduler, mock_node_runner
    ):
        """Test execute_ready_nodes for ReAct mode (execute one batch then return)"""
        # Setup: only n1 is ready
        mock_scheduler.get_ready_nodes = Mock(return_value=[simple_graph.nodes["n1"]])
        
        async def run_nodes_parallel_side_effect(graph, nodes, context, max_concurrent=None):
            results = []
            for node in nodes:
                node.mark_success({"output": f"result from {node.id}"})
                results.append(NodeResult(success=True, outputs=node.outputs))
            return results
        
        mock_node_runner.run_nodes_parallel = AsyncMock(side_effect=run_nodes_parallel_side_effect)
        
        # Execute
        result = await graph_runtime.execute_ready_nodes(simple_graph)
        
        # Verify
        assert result.success is True
        assert result.is_stuck is False
        assert simple_graph.nodes["n1"].status == NodeStatus.SUCCESS
        assert simple_graph.nodes["n2"].status == NodeStatus.PENDING
        assert simple_graph.nodes["n3"].status == NodeStatus.PENDING
        assert mock_node_runner.run_nodes_parallel.call_count == 1


class TestFailurePropagation:
    """Test failure propagation to downstream nodes"""
    
    @pytest.mark.asyncio
    async def test_propagate_failure_to_downstream_nodes(
        self, graph_runtime, simple_graph, mock_scheduler, mock_node_runner
    ):
        """Test that failure propagates to downstream nodes"""
        call_count = [0]
        
        def get_ready_nodes_side_effect(graph):
            call_count[0] += 1
            if call_count[0] == 1:
                return [graph.nodes["n1"]]
            else:
                # After n1 fails, no more nodes should be ready
                return []
        
        mock_scheduler.get_ready_nodes = Mock(side_effect=get_ready_nodes_side_effect)
        
        # Mock n1 to fail
        async def run_nodes_parallel_side_effect(graph, nodes, context, max_concurrent=None):
            results = []
            for node in nodes:
                if node.id == "n1":
                    node.mark_failed("Simulated failure")
                    results.append(NodeResult(success=False, error_message="Simulated failure"))
                else:
                    node.mark_success({"output": f"result from {node.id}"})
                    results.append(NodeResult(success=True, outputs=node.outputs))
            return results
        
        mock_node_runner.run_nodes_parallel = AsyncMock(side_effect=run_nodes_parallel_side_effect)
        
        # Execute
        result = await graph_runtime.execute_graph(simple_graph)
        
        # Verify
        assert result.success is False
        assert simple_graph.status == GraphStatus.FAILED
        assert simple_graph.nodes["n1"].status == NodeStatus.FAILED
        assert simple_graph.nodes["n2"].status == NodeStatus.SKIPPED
        assert simple_graph.nodes["n3"].status == NodeStatus.SKIPPED
        assert simple_graph.nodes["n2"].metadata.get('skip_reason') == 'Required dependency n1 failed'
    
    @pytest.mark.asyncio
    async def test_optional_edge_does_not_propagate_failure(
        self, graph_runtime, mock_scheduler, mock_node_runner, mock_context, mock_event_bus
    ):
        """Test that optional edges don't propagate failure"""
        # Create graph with optional edge
        graph = ExecutionGraph(id="optional-graph", goal="Test optional edges")
        
        n1 = StepNode(id="n1", capability_name="cap1")
        n2 = StepNode(id="n2", capability_name="cap2")
        
        graph.add_node(n1)
        graph.add_node(n2)
        
        # Add optional edge
        graph.add_edge(DataEdge(
            id="e1",
            source_node="n1",
            source_field="output",
            target_node="n2",
            target_param="input",
            optional=True  # Optional dependency
        ))
        
        call_count = [0]
        
        def get_ready_nodes_side_effect(g):
            call_count[0] += 1
            if call_count[0] == 1:
                return [g.nodes["n1"]]
            elif call_count[0] == 2:
                # n2 should still be ready even though n1 failed (optional edge)
                return [g.nodes["n2"]]
            else:
                return []
        
        mock_scheduler.get_ready_nodes = Mock(side_effect=get_ready_nodes_side_effect)
        
        # Mock n1 to fail, n2 to succeed
        async def run_nodes_parallel_side_effect(g, nodes, context, max_concurrent=None):
            results = []
            for node in nodes:
                if node.id == "n1":
                    node.mark_failed("Simulated failure")
                    results.append(NodeResult(success=False, error_message="Simulated failure"))
                else:
                    node.mark_success({"output": f"result from {node.id}"})
                    results.append(NodeResult(success=True, outputs=node.outputs))
            return results
        
        mock_node_runner.run_nodes_parallel = AsyncMock(side_effect=run_nodes_parallel_side_effect)
        
        # Execute
        result = await graph_runtime.execute_graph(graph)
        
        # Verify: n2 should NOT be skipped because edge is optional
        assert graph.nodes["n1"].status == NodeStatus.FAILED
        assert graph.nodes["n2"].status == NodeStatus.SUCCESS
        assert result.success is False  # Graph failed because n1 failed


class TestTerminalStateDetection:
    """Test terminal state and final status computation"""
    
    @pytest.mark.asyncio
    async def test_compute_final_status_all_success(
        self, graph_runtime, simple_graph, mock_scheduler, mock_node_runner
    ):
        """Test final status when all nodes succeed"""
        mock_scheduler.get_ready_nodes = Mock(return_value=[])
        
        # Mark all nodes as success
        for node in simple_graph.nodes.values():
            node.status = NodeStatus.SUCCESS
        
        # Execute (should immediately detect completion)
        result = await graph_runtime.execute_graph(simple_graph)
        
        # Verify
        assert result.success is True
        assert simple_graph.status == GraphStatus.SUCCESS
    
    @pytest.mark.asyncio
    async def test_compute_final_status_with_skipped(
        self, graph_runtime, simple_graph, mock_scheduler, mock_node_runner
    ):
        """Test final status when some nodes are skipped"""
        mock_scheduler.get_ready_nodes = Mock(return_value=[])
        
        # Mark nodes: n1 success, n2 skipped, n3 skipped
        simple_graph.nodes["n1"].status = NodeStatus.SUCCESS
        simple_graph.nodes["n2"].status = NodeStatus.SKIPPED
        simple_graph.nodes["n3"].status = NodeStatus.SKIPPED
        
        # Execute
        result = await graph_runtime.execute_graph(simple_graph)
        
        # Verify: graph should be partial_success (some nodes skipped)
        assert result.success is True
        assert simple_graph.status == GraphStatus.SUCCESS or simple_graph.status == "partial_success"
    
    @pytest.mark.asyncio
    async def test_compute_final_status_with_failure(
        self, graph_runtime, simple_graph, mock_scheduler, mock_node_runner
    ):
        """Test final status when any node fails"""
        mock_scheduler.get_ready_nodes = Mock(return_value=[])
        
        # Mark nodes: n1 success, n2 failed, n3 skipped
        simple_graph.nodes["n1"].status = NodeStatus.SUCCESS
        simple_graph.nodes["n2"].status = NodeStatus.FAILED
        simple_graph.nodes["n3"].status = NodeStatus.SKIPPED
        
        # Execute
        result = await graph_runtime.execute_graph(simple_graph)
        
        # Verify
        assert result.success is False
        assert simple_graph.status == GraphStatus.FAILED


class TestStuckStateDetection:
    """Test stuck state detection for ReAct mode"""
    
    @pytest.mark.asyncio
    async def test_detect_stuck_state(
        self, graph_runtime, simple_graph, mock_scheduler, mock_node_runner
    ):
        """Test detection of stuck state (no ready nodes but pending nodes exist)"""
        # Setup: no ready nodes but n2 and n3 are still pending
        mock_scheduler.get_ready_nodes = Mock(return_value=[])
        
        # Mark n1 as success, leave n2 and n3 as pending
        simple_graph.nodes["n1"].status = NodeStatus.SUCCESS
        # n2 and n3 remain PENDING
        
        # Execute
        result = await graph_runtime.execute_graph(simple_graph)
        
        # Verify
        assert result.is_stuck is True
        assert result.success is False
        assert simple_graph.nodes["n2"].status == NodeStatus.PENDING
        assert simple_graph.nodes["n3"].status == NodeStatus.PENDING


class TestEventEmission:
    """Test event emission for observability"""
    
    @pytest.mark.asyncio
    async def test_emit_graph_lifecycle_events(
        self, graph_runtime, simple_graph, mock_scheduler, mock_node_runner, mock_event_bus
    ):
        """Test that graph lifecycle events are emitted"""
        mock_scheduler.get_ready_nodes = Mock(return_value=[])
        
        # Mark all nodes as success
        for node in simple_graph.nodes.values():
            node.status = NodeStatus.SUCCESS
        
        # Execute
        await graph_runtime.execute_graph(simple_graph)
        
        # Verify events were emitted
        calls = mock_event_bus.publish.call_args_list
        event_types = [call[0][0].type for call in calls]
        
        assert 'graph_started' in event_types
        assert 'graph_completed' in event_types
    
    @pytest.mark.asyncio
    async def test_emit_node_events(
        self, graph_runtime, simple_graph, mock_scheduler, mock_node_runner, mock_event_bus
    ):
        """Test that node events are emitted"""
        # Setup: only n1 is ready
        mock_scheduler.get_ready_nodes = Mock(
            side_effect=[[simple_graph.nodes["n1"]], []]
        )
        
        async def run_nodes_parallel_side_effect(graph, nodes, context, max_concurrent=None):
            results = []
            for node in nodes:
                node.mark_success({"output": f"result from {node.id}"})
                results.append(NodeResult(success=True, outputs=node.outputs))
            return results
        
        mock_node_runner.run_nodes_parallel = AsyncMock(side_effect=run_nodes_parallel_side_effect)
        
        # Execute
        await graph_runtime.execute_graph(simple_graph)
        
        # Verify node events
        calls = mock_event_bus.publish.call_args_list
        event_types = [call[0][0].type for call in calls]
        
        assert 'node_started' in event_types
        assert 'node_completed' in event_types


class TestExecutionTimeout:
    """Test execution timeout handling"""
    
    @pytest.mark.asyncio
    async def test_execution_timeout(
        self, mock_scheduler, mock_node_runner, mock_context, mock_event_bus, simple_graph
    ):
        """Test that execution times out after max_execution_time"""
        # Create runtime with very short timeout
        runtime = GraphRuntime(
            scheduler=mock_scheduler,
            node_runner=mock_node_runner,
            context=mock_context,
            event_bus=mock_event_bus,
            config={'max_execution_time': 0.1}  # 100ms timeout
        )
        
        # Setup: scheduler always returns n1 (infinite loop)
        mock_scheduler.get_ready_nodes = Mock(return_value=[simple_graph.nodes["n1"]])
        
        # Mock node runner to take a long time
        async def run_nodes_parallel_side_effect(graph, nodes, context, max_concurrent=None):
            await asyncio.sleep(0.2)  # Longer than timeout
            results = []
            for node in nodes:
                node.mark_success({"output": "result"})
                results.append(NodeResult(success=True, outputs=node.outputs))
            return results
        
        mock_node_runner.run_nodes_parallel = AsyncMock(side_effect=run_nodes_parallel_side_effect)
        
        # Execute
        result = await runtime.execute_graph(simple_graph)
        
        # Verify timeout
        assert result.success is False
        assert simple_graph.status == GraphStatus.FAILED
        assert 'Execution time limit exceeded' in simple_graph.metadata.get('error', '')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
