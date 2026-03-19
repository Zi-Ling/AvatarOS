"""
StepNode - Single Execution Unit in Graph

Represents a single execution unit that invokes one Capability with typed parameters.
"""
from __future__ import annotations

from typing import Dict, List, Any, Optional
from enum import Enum
from datetime import datetime, UTC
from pydantic import BaseModel, Field


class NodeType(str, Enum):
    """Structural role of a node in the execution graph."""
    STANDARD = "standard"
    FAN_OUT = "fan_out"
    FAN_IN = "fan_in"


class AggregationType(str, Enum):
    """Aggregation strategy for FanInNode results."""
    CONCAT = "concat"
    MERGE = "merge"
    # REDUCE_CUSTOM = "reduce_custom"  # V2_PLANNED


class BatchFailPolicy(str, Enum):
    """Failure handling policy for batch (fan-out) execution."""
    BEST_EFFORT = "best_effort"
    FAIL_FAST = "fail_fast"


class NodeStatus(str, Enum):
    """Node execution status"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class RetryPolicy(BaseModel):
    """
    Retry configuration for node execution.
    
    Implements exponential backoff:
    delay = initial_delay * (backoff_multiplier ^ retry_count)
    """
    max_retries: int = Field(default=3, ge=0, description="Maximum number of retry attempts")
    backoff_multiplier: float = Field(default=2.0, ge=1.0, description="Exponential backoff multiplier")
    initial_delay: float = Field(default=1.0, ge=0.1, description="Initial delay in seconds")


class StreamEvent(BaseModel):
    """
    Streaming output event.
    
    Used for real-time output collection during node execution.
    """
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_type: str = Field(description="Event type (stdout, stderr, progress, etc.)")
    data: Any = Field(description="Event data")


class StepNode(BaseModel):
    """
    Represents a single execution unit in the graph.
    
    Each node invokes one Capability with typed parameters.
    Outputs are stored after execution and can be referenced by downstream nodes via DataEdges.
    """
    
    id: str = Field(description="Unique node identifier")
    capability_name: str = Field(description="Name of the Capability to execute")
    params: Dict[str, Any] = Field(default_factory=dict, description="Static parameters")
    status: NodeStatus = Field(default=NodeStatus.PENDING)
    outputs: Dict[str, Any] = Field(default_factory=dict, description="Execution outputs")
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Execution metadata")
    
    # Deliverable coverage claim: which deliverable IDs this node intends to produce
    intended_deliverables: List[str] = Field(default_factory=list, description="Deliverable IDs this node claims to produce")
    
    # Node type for fan-out/fan-in support
    node_type: NodeType = Field(default=NodeType.STANDARD, description="Structural role")
    # Fan-out specific
    batch_fail_policy: BatchFailPolicy = Field(
        default=BatchFailPolicy.BEST_EFFORT,
        description="Failure policy for fan-out children",
    )
    fan_out_count: int = Field(default=0, description="Number of items to fan out")
    # Fan-in specific
    aggregation_type: AggregationType = Field(
        default=AggregationType.CONCAT,
        description="Aggregation strategy for fan-in",
    )
    
    # Execution tracking
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    
    # Streaming output support
    stream_events: List[StreamEvent] = Field(default_factory=list, description="Streaming output events")
    
    def is_terminal(self) -> bool:
        """Check if node is in a terminal state"""
        return self.status in (
            NodeStatus.SUCCESS,
            NodeStatus.FAILED,
            NodeStatus.SKIPPED,
            NodeStatus.CANCELLED
        )
    
    def can_retry(self) -> bool:
        """Check if node can be retried"""
        return (
            self.status == NodeStatus.FAILED and
            self.retry_count < self.retry_policy.max_retries
        )
    
    def get_retry_delay(self) -> float:
        """Calculate retry delay using exponential backoff"""
        return self.retry_policy.initial_delay * (
            self.retry_policy.backoff_multiplier ** self.retry_count
        )
    
    def mark_running(self) -> None:
        """Mark node as running"""
        self.status = NodeStatus.RUNNING
        self.start_time = datetime.now(UTC)
    
    def mark_success(self, outputs: Dict[str, Any]) -> None:
        """Mark node as successful"""
        self.status = NodeStatus.SUCCESS
        self.outputs = outputs
        self.end_time = datetime.now(UTC)
    
    def mark_failed(self, error_message: str) -> None:
        """Mark node as failed"""
        self.status = NodeStatus.FAILED
        self.error_message = error_message
        self.end_time = datetime.now(UTC)
    
    def mark_skipped(self, reason: str) -> None:
        """Mark node as skipped"""
        self.status = NodeStatus.SKIPPED
        self.metadata['skip_reason'] = reason
        self.end_time = datetime.now(UTC)
    
    def add_stream_event(self, event_type: str, data: Any) -> None:
        """Add a streaming output event"""
        event = StreamEvent(event_type=event_type, data=data)
        self.stream_events.append(event)
