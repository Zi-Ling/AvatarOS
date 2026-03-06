"""
Tests for Model Adapter - Task/Step to ExecutionGraph/StepNode Conversion

Tests verify that conversions preserve all data and maintain backward compatibility.
"""
import pytest
from datetime import datetime
import time

from app.avatar.planner.models.task import Task, TaskStatus
from app.avatar.planner.models.step import Step, StepStatus, StepResult
from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph, GraphStatus
from app.avatar.runtime.graph.models.step_node import StepNode, NodeStatus, RetryPolicy
from app.avatar.runtime.graph.models.data_edge import DataEdge

from .model_adapter import (
    task_to_execution_graph,
    step_to_step_node,
    execution_graph_to_task,
    step_node_to_step,
)


class TestStepToStepNode:
    """Test Step to StepNode conversion"""
    
    def test_basic_conversion(self):
        """Test basic step conversion with minimal fields"""
        step = Step(
            id="step1",
            order=0,
            skill_name="read_file",
            params={"path": "/test/file.txt"}
        )
        
        node = step_to_step_node(step)
        
        assert node.id == "step1"
        assert node.capability_name == "read_file"
        assert node.params == {"path": "/test/file.txt"}
        assert node.status == NodeStatus.PENDING
        assert node.metadata["order"] == 0
        assert node.metadata["depends_on"] == []
    
    def test_conversion_with_result(self):
        """Test conversion with execution result"""
        step = Step(
            id="step2",
            order=1,
            skill_name="write_file",
            params={"path": "/test/output.txt", "content": "test"},
            status=StepStatus.SUCCESS,
            result=StepResult(
                success=True,
                output={"bytes_written": 4}
            )
        )
        
        node = step_to_step_node(step)
        
        assert node.status == NodeStatus.SUCCESS
        assert node.outputs["ok"] is True
        assert node.outputs["data"] == {"bytes_written": 4}
        assert node.error_message is None
    
    def test_conversion_with_failure(self):
        """Test conversion with failed result"""
        step = Step(
            id="step3",
            order=2,
            skill_name="execute_command",
            params={"command": "invalid"},
            status=StepStatus.FAILED,
            result=StepResult(
                success=False,
                error="Command not found"
            )
        )
        
        node = step_to_step_node(step)
        
        assert node.status == NodeStatus.FAILED
        assert node.outputs["ok"] is False
        assert node.outputs["meta"]["error"] == "Command not found"
        assert node.error_message == "Command not found"
    
    def test_conversion_with_retry(self):
        """Test conversion with retry configuration"""
        step = Step(
            id="step4",
            order=3,
            skill_name="http_request",
            params={"url": "https://example.com"},
            max_retry=5,
            retry=2
        )
        
        node = step_to_step_node(step)
        
        assert node.retry_policy.max_retries == 5
        assert node.retry_count == 2
    
    def test_conversion_with_dependencies(self):
        """Test conversion with step dependencies"""
        step = Step(
            id="step5",
            order=4,
            skill_name="process_data",
            params={"data": "input"},
            depends_on=["step1", "step2"]
        )
        
        node = step_to_step_node(step)
        
        assert node.metadata["depends_on"] == ["step1", "step2"]
    
    def test_conversion_with_description(self):
        """Test conversion with description"""
        step = Step(
            id="step6",
            order=5,
            skill_name="analyze",
            params={},
            description="Analyze the data"
        )
        
        node = step_to_step_node(step)
        
        assert node.metadata["description"] == "Analyze the data"


class TestStepNodeToStep:
    """Test StepNode to Step conversion (reverse)"""
    
    def test_basic_reverse_conversion(self):
        """Test basic node to step conversion"""
        node = StepNode(
            id="node1",
            capability_name="read_file",
            params={"path": "/test/file.txt"},
            metadata={
                "order": 0,
                "depends_on": [],
                "description": None
            }
        )
        
        step = step_node_to_step(node)
        
        assert step.id == "node1"
        assert step.skill_name == "read_file"
        assert step.params == {"path": "/test/file.txt"}
        assert step.status == StepStatus.PENDING
        assert step.order == 0
    
    def test_reverse_conversion_with_outputs(self):
        """Test reverse conversion with outputs"""
        node = StepNode(
            id="node2",
            capability_name="write_file",
            params={},
            status=NodeStatus.SUCCESS,
            outputs={
                "ok": True,
                "data": {"bytes_written": 100},
                "meta": {}
            },
            metadata={"order": 1, "depends_on": []}
        )
        
        step = step_node_to_step(node)
        
        assert step.status == StepStatus.SUCCESS
        assert step.result is not None
        assert step.result.success is True
        assert step.result.output == {"bytes_written": 100}
    
    def test_reverse_conversion_with_error(self):
        """Test reverse conversion with error"""
        node = StepNode(
            id="node3",
            capability_name="execute",
            params={},
            status=NodeStatus.FAILED,
            outputs={
                "ok": False,
                "data": None,
                "meta": {"error": "Execution failed"}
            },
            error_message="Execution failed",
            metadata={"order": 2, "depends_on": []}
        )
        
        step = step_node_to_step(node)
        
        assert step.status == StepStatus.FAILED
        assert step.result is not None
        assert step.result.success is False
        assert step.result.error == "Execution failed"


class TestTaskToExecutionGraph:
    """Test Task to ExecutionGraph conversion"""
    
    def test_simple_task_conversion(self):
        """Test conversion of simple task with no dependencies"""
        task = Task(
            id="task1",
            intent_id=None,
            goal="Read and process file",
            steps=[
                Step(id="s1", order=0, skill_name="read_file", params={"path": "input.txt"}),
                Step(id="s2", order=1, skill_name="process", params={"data": "test"})
            ],
            status=TaskStatus.PENDING
        )
        
        graph = task_to_execution_graph(task)
        
        assert graph.id == "task1"
        assert graph.goal == "Read and process file"
        assert graph.status == GraphStatus.PENDING
        assert len(graph.nodes) == 2
        assert "s1" in graph.nodes
        assert "s2" in graph.nodes
        assert graph.nodes["s1"].capability_name == "read_file"
        assert graph.nodes["s2"].capability_name == "process"
    
    def test_task_conversion_with_dependencies(self):
        """Test conversion with step dependencies creates edges"""
        task = Task(
            id="task2",
            intent_id=None,
            goal="Sequential processing",
            steps=[
                Step(id="s1", order=0, skill_name="read_file", params={"path": "input.txt"}),
                Step(id="s2", order=1, skill_name="process", params={}, depends_on=["s1"]),
                Step(id="s3", order=2, skill_name="write_file", params={}, depends_on=["s2"])
            ]
        )
        
        graph = task_to_execution_graph(task)
        
        assert len(graph.nodes) == 3
        assert len(graph.edges) == 2
        
        # Check edges were created
        edges_list = list(graph.edges.values())
        assert any(e.source_node == "s1" and e.target_node == "s2" for e in edges_list)
        assert any(e.source_node == "s2" and e.target_node == "s3" for e in edges_list)
    
    def test_task_conversion_with_multiple_dependencies(self):
        """Test conversion with multiple dependencies"""
        task = Task(
            id="task3",
            intent_id=None,
            goal="Parallel then merge",
            steps=[
                Step(id="s1", order=0, skill_name="fetch_data_a", params={}),
                Step(id="s2", order=1, skill_name="fetch_data_b", params={}),
                Step(id="s3", order=2, skill_name="merge", params={}, depends_on=["s1", "s2"])
            ]
        )
        
        graph = task_to_execution_graph(task)
        
        assert len(graph.nodes) == 3
        assert len(graph.edges) == 2
        
        # Check both edges point to s3
        s3_incoming = graph.get_incoming_edges("s3")
        assert len(s3_incoming) == 2
        source_nodes = {e.source_node for e in s3_incoming}
        assert source_nodes == {"s1", "s2"}
    
    def test_task_conversion_preserves_metadata(self):
        """Test that task metadata is preserved"""
        task = Task(
            id="task4",
            intent_id="intent123",
            goal="Test metadata",
            steps=[Step(id="s1", order=0, skill_name="test", params={})],
            metadata={"user_id": "user456", "priority": "high"}
        )
        
        graph = task_to_execution_graph(task)
        
        assert graph.metadata["intent_id"] == "intent123"
        assert graph.metadata["user_id"] == "user456"
        assert graph.metadata["priority"] == "high"
        assert graph.metadata["legacy_task"] is True
    
    def test_task_conversion_with_status(self):
        """Test status conversion"""
        task = Task(
            id="task5",
            intent_id=None,
            goal="Test status",
            steps=[Step(id="s1", order=0, skill_name="test", params={})],
            status=TaskStatus.RUNNING
        )
        
        graph = task_to_execution_graph(task)
        
        assert graph.status == GraphStatus.RUNNING
    
    def test_dag_validation(self):
        """Test that converted graph is a valid DAG"""
        task = Task(
            id="task6",
            intent_id=None,
            goal="DAG test",
            steps=[
                Step(id="s1", order=0, skill_name="start", params={}),
                Step(id="s2", order=1, skill_name="middle", params={}, depends_on=["s1"]),
                Step(id="s3", order=2, skill_name="end", params={}, depends_on=["s2"])
            ]
        )
        
        graph = task_to_execution_graph(task)
        
        assert graph.validate_dag() is True


class TestExecutionGraphToTask:
    """Test ExecutionGraph to Task conversion (reverse)"""
    
    def test_simple_graph_to_task(self):
        """Test basic graph to task conversion"""
        graph = ExecutionGraph(
            id="graph1",
            goal="Test goal",
            status=GraphStatus.PENDING,
            metadata={"intent_id": "intent1"}
        )
        
        node1 = StepNode(
            id="n1",
            capability_name="read_file",
            params={"path": "test.txt"},
            metadata={"order": 0, "depends_on": []}
        )
        graph.add_node(node1)
        
        task = execution_graph_to_task(graph)
        
        assert task.id == "graph1"
        assert task.goal == "Test goal"
        assert task.status == TaskStatus.PENDING
        assert task.intent_id == "intent1"
        assert len(task.steps) == 1
        assert task.steps[0].id == "n1"
        assert task.steps[0].skill_name == "read_file"
    
    def test_graph_to_task_preserves_order(self):
        """Test that steps are sorted by order"""
        graph = ExecutionGraph(id="graph2", goal="Test", metadata={})
        
        # Add nodes in random order
        node3 = StepNode(id="n3", capability_name="c", params={}, metadata={"order": 2, "depends_on": []})
        node1 = StepNode(id="n1", capability_name="a", params={}, metadata={"order": 0, "depends_on": []})
        node2 = StepNode(id="n2", capability_name="b", params={}, metadata={"order": 1, "depends_on": []})
        
        graph.add_node(node3)
        graph.add_node(node1)
        graph.add_node(node2)
        
        task = execution_graph_to_task(graph)
        
        assert len(task.steps) == 3
        assert task.steps[0].id == "n1"
        assert task.steps[1].id == "n2"
        assert task.steps[2].id == "n3"


class TestRoundTripConversion:
    """Test round-trip conversions preserve data"""
    
    def test_task_to_graph_to_task(self):
        """Test Task → Graph → Task preserves data"""
        original_task = Task(
            id="task_rt1",
            goal="Round trip test",
            steps=[
                Step(
                    id="s1",
                    order=0,
                    skill_name="read_file",
                    params={"path": "input.txt"},
                    status=StepStatus.SUCCESS,
                    result=StepResult(success=True, output={"content": "test data"})
                ),
                Step(
                    id="s2",
                    order=1,
                    skill_name="process",
                    params={"mode": "fast"},
                    depends_on=["s1"]
                )
            ],
            intent_id="intent_rt1",
            status=TaskStatus.RUNNING,
            metadata={"user": "test_user"}
        )
        
        # Convert to graph and back
        graph = task_to_execution_graph(original_task)
        converted_task = execution_graph_to_task(graph)
        
        # Verify preservation
        assert converted_task.id == original_task.id
        assert converted_task.goal == original_task.goal
        assert converted_task.status == original_task.status
        assert converted_task.intent_id == original_task.intent_id
        assert len(converted_task.steps) == len(original_task.steps)
        
        # Check first step
        assert converted_task.steps[0].id == "s1"
        assert converted_task.steps[0].skill_name == "read_file"
        assert converted_task.steps[0].params == {"path": "input.txt"}
        assert converted_task.steps[0].status == StepStatus.SUCCESS
        assert converted_task.steps[0].result.success is True
        
        # Check second step
        assert converted_task.steps[1].id == "s2"
        assert converted_task.steps[1].depends_on == ["s1"]
    
    def test_step_to_node_to_step(self):
        """Test Step → Node → Step preserves data"""
        original_step = Step(
            id="step_rt1",
            order=5,
            skill_name="analyze_data",
            params={"threshold": 0.95, "mode": "strict"},
            status=StepStatus.RUNNING,
            retry=1,
            max_retry=3,
            depends_on=["step_rt0"],
            description="Analyze with high threshold"
        )
        
        # Convert to node and back
        node = step_to_step_node(original_step)
        converted_step = step_node_to_step(node)
        
        # Verify preservation
        assert converted_step.id == original_step.id
        assert converted_step.order == original_step.order
        assert converted_step.skill_name == original_step.skill_name
        assert converted_step.params == original_step.params
        assert converted_step.status == original_step.status
        assert converted_step.retry == original_step.retry
        assert converted_step.max_retry == original_step.max_retry
        assert converted_step.depends_on == original_step.depends_on
        assert converted_step.description == original_step.description


class TestEdgeInference:
    """Test edge inference from dependencies"""
    
    def test_edge_field_names(self):
        """Test that edges use correct field names"""
        task = Task(
            id="task_edge1",
            intent_id=None,
            goal="Test edges",
            steps=[
                Step(id="s1", order=0, skill_name="produce", params={}),
                Step(id="s2", order=1, skill_name="consume", params={}, depends_on=["s1"])
            ]
        )
        
        graph = task_to_execution_graph(task)
        
        edges = list(graph.edges.values())
        assert len(edges) == 1
        
        edge = edges[0]
        assert edge.source_node == "s1"
        assert edge.source_field == "data"
        assert edge.target_node == "s2"
        assert edge.target_param == "input_from_s1"
        assert edge.optional is False
    
    def test_multiple_edges_unique_ids(self):
        """Test that multiple edges have unique IDs"""
        task = Task(
            id="task_edge2",
            intent_id=None,
            goal="Multiple edges",
            steps=[
                Step(id="s1", order=0, skill_name="a", params={}),
                Step(id="s2", order=1, skill_name="b", params={}),
                Step(id="s3", order=2, skill_name="c", params={}, depends_on=["s1", "s2"])
            ]
        )
        
        graph = task_to_execution_graph(task)
        
        edge_ids = list(graph.edges.keys())
        assert len(edge_ids) == 2
        assert len(set(edge_ids)) == 2  # All unique


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
