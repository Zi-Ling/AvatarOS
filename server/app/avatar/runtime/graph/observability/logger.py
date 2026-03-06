"""
Graph Runtime Structured Logging

JSON structured logging for graph execution events.

Requirements: 15.1-15.7
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, UTC
from typing import Any, Dict, Optional


# Event type constants (Requirements 15.3)
class GraphEvent:
    GRAPH_STARTED = "graph_started"
    GRAPH_COMPLETED = "graph_completed"
    GRAPH_FAILED = "graph_failed"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    NODE_RETRYING = "node_retrying"
    PLANNER_INVOKED = "planner_invoked"
    PATCH_APPLIED = "patch_applied"


class StructuredLogger:
    """
    JSON structured logger for graph runtime events.

    Emits log records with fields:
    - timestamp, level, event_type, graph_id, node_id, message, metadata

    Requirements: 15.1-15.7
    """

    def __init__(self, name: str = "graph_runtime"):
        self._logger = logging.getLogger(name)

    def _log(
        self,
        level: int,
        event_type: str,
        message: str,
        graph_id: Optional[str] = None,
        node_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit a structured JSON log record. Requirements: 15.1, 15.2"""
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": logging.getLevelName(level),
            "event_type": event_type,
            "message": message,
        }
        if graph_id:
            record["graph_id"] = graph_id
        if node_id:
            record["node_id"] = node_id
        if metadata:
            record["metadata"] = metadata

        self._logger.log(level, json.dumps(record, default=str))

    # ---- Graph lifecycle events ----

    def graph_started(self, graph_id: str, goal: str, mode: str = "complete") -> None:
        """Requirements: 15.3, 15.6"""
        self._log(
            logging.INFO,
            GraphEvent.GRAPH_STARTED,
            f"Graph execution started: {graph_id}",
            graph_id=graph_id,
            metadata={"goal": goal, "mode": mode},
        )

    def graph_completed(
        self,
        graph_id: str,
        status: str,
        execution_time: float,
        completed_nodes: int,
        failed_nodes: int,
        cost: float = 0.0,
    ) -> None:
        """Requirements: 15.3, 15.6"""
        self._log(
            logging.INFO,
            GraphEvent.GRAPH_COMPLETED,
            f"Graph execution completed: {graph_id} ({status})",
            graph_id=graph_id,
            metadata={
                "status": status,
                "execution_time_s": round(execution_time, 3),
                "completed_nodes": completed_nodes,
                "failed_nodes": failed_nodes,
                "cost_usd": round(cost, 6),
            },
        )

    def graph_failed(self, graph_id: str, error: str, execution_time: float) -> None:
        """Requirements: 15.3, 15.7"""
        self._log(
            logging.ERROR,
            GraphEvent.GRAPH_FAILED,
            f"Graph execution failed: {graph_id}",
            graph_id=graph_id,
            metadata={"error": error, "execution_time_s": round(execution_time, 3)},
        )

    # ---- Node lifecycle events ----

    def node_started(self, graph_id: str, node_id: str, capability_name: str) -> None:
        """Requirements: 15.4, 15.6"""
        self._log(
            logging.INFO,
            GraphEvent.NODE_STARTED,
            f"Node started: {node_id}",
            graph_id=graph_id,
            node_id=node_id,
            metadata={"capability": capability_name},
        )

    def node_completed(
        self,
        graph_id: str,
        node_id: str,
        capability_name: str,
        execution_time: float,
        retry_count: int = 0,
        cost: float = 0.0,
    ) -> None:
        """Requirements: 15.4, 15.6"""
        self._log(
            logging.INFO,
            GraphEvent.NODE_COMPLETED,
            f"Node completed: {node_id}",
            graph_id=graph_id,
            node_id=node_id,
            metadata={
                "capability": capability_name,
                "execution_time_s": round(execution_time, 3),
                "retry_count": retry_count,
                "cost_usd": round(cost, 6),
            },
        )

    def node_failed(
        self,
        graph_id: str,
        node_id: str,
        capability_name: str,
        error: str,
        retry_count: int = 0,
    ) -> None:
        """Requirements: 15.5, 15.7"""
        self._log(
            logging.ERROR,
            GraphEvent.NODE_FAILED,
            f"Node failed: {node_id}",
            graph_id=graph_id,
            node_id=node_id,
            metadata={
                "capability": capability_name,
                "error": error,
                "retry_count": retry_count,
            },
        )

    def node_retrying(
        self,
        graph_id: str,
        node_id: str,
        capability_name: str,
        attempt: int,
        delay: float,
        error: str,
    ) -> None:
        """Requirements: 15.5"""
        self._log(
            logging.WARNING,
            GraphEvent.NODE_RETRYING,
            f"Node retrying: {node_id} (attempt {attempt})",
            graph_id=graph_id,
            node_id=node_id,
            metadata={
                "capability": capability_name,
                "attempt": attempt,
                "delay_s": round(delay, 3),
                "error": error,
            },
        )

    # ---- Planner events ----

    def planner_invoked(
        self,
        graph_id: str,
        mode: str,
        invocation_count: int,
        latency_ms: float,
    ) -> None:
        """Requirements: 15.6"""
        self._log(
            logging.INFO,
            GraphEvent.PLANNER_INVOKED,
            f"Planner invoked for graph {graph_id}",
            graph_id=graph_id,
            metadata={
                "mode": mode,
                "invocation_count": invocation_count,
                "latency_ms": round(latency_ms, 1),
            },
        )

    def patch_applied(
        self,
        graph_id: str,
        add_nodes: int,
        add_edges: int,
        reasoning: str,
    ) -> None:
        """Requirements: 15.6"""
        self._log(
            logging.INFO,
            GraphEvent.PATCH_APPLIED,
            f"Patch applied to graph {graph_id}",
            graph_id=graph_id,
            metadata={
                "add_nodes": add_nodes,
                "add_edges": add_edges,
                "reasoning": reasoning[:200],  # Truncate long reasoning
            },
        )


# Global structured logger
graph_logger = StructuredLogger("graph_runtime")


def get_graph_logger() -> StructuredLogger:
    """Get the global StructuredLogger instance."""
    return graph_logger
