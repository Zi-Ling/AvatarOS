"""
Graph Runtime Distributed Tracing

OpenTelemetry-based distributed tracing for graph execution.
Falls back to no-op spans when OpenTelemetry is not installed.

Requirements: 16.1-16.7
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict, Generator, Optional

logger = logging.getLogger(__name__)

# Try to import OpenTelemetry; fall back to no-op if not available
try:
    from opentelemetry import trace
    from opentelemetry.trace import Span, Status, StatusCode
    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False
    trace = None  # type: ignore


# ==========================================
# No-op span for when OTEL is unavailable
# ==========================================

class _NoOpSpan:
    """No-op span used when OpenTelemetry is not installed."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, *args, **kwargs) -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# ==========================================
# GraphTracer
# ==========================================

class GraphTracer:
    """
    Distributed tracing for graph execution using OpenTelemetry.

    Creates:
    - Root span "graph.execute" for each graph execution
    - Child spans "node.execute.{capability_name}" for each node

    Span attributes include: graph_id, node_id, capability_name, status, retry_count

    Requirements: 16.1-16.7
    """

    TRACER_NAME = "graph_runtime"

    def __init__(self):
        if _OTEL_AVAILABLE:
            self._tracer = trace.get_tracer(self.TRACER_NAME)
        else:
            self._tracer = None
            logger.debug(
                "[GraphTracer] OpenTelemetry not available, using no-op spans. "
                "Install with: pip install opentelemetry-api opentelemetry-sdk"
            )

    @contextmanager
    def graph_span(
        self,
        graph_id: str,
        goal: str,
        mode: str = "complete"
    ) -> Generator:
        """
        Create root span for graph execution.

        Span name: "graph.execute"
        Attributes: graph_id, goal, mode

        Requirements: 16.2, 16.4, 16.5
        """
        if self._tracer is None:
            yield _NoOpSpan()
            return

        with self._tracer.start_as_current_span("graph.execute") as span:
            span.set_attribute("graph.id", graph_id)
            span.set_attribute("graph.goal", goal[:200])
            span.set_attribute("graph.mode", mode)
            try:
                yield span
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(StatusCode.ERROR, str(exc))
                raise

    @contextmanager
    def node_span(
        self,
        graph_id: str,
        node_id: str,
        capability_name: str,
        retry_count: int = 0
    ) -> Generator:
        """
        Create child span for node execution.

        Span name: "node.execute.{capability_name}"
        Attributes: graph_id, node_id, capability_name, retry_count

        Requirements: 16.3, 16.4, 16.5, 16.6
        """
        if self._tracer is None:
            yield _NoOpSpan()
            return

        span_name = f"node.execute.{capability_name}"
        with self._tracer.start_as_current_span(span_name) as span:
            span.set_attribute("graph.id", graph_id)
            span.set_attribute("node.id", node_id)
            span.set_attribute("node.capability", capability_name)
            span.set_attribute("node.retry_count", retry_count)
            try:
                yield span
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(StatusCode.ERROR, str(exc))
                raise

    def record_node_success(self, span, execution_time: float, cost: float = 0.0) -> None:
        """Record successful node completion on span. Requirements: 16.5"""
        if _OTEL_AVAILABLE and not isinstance(span, _NoOpSpan):
            span.set_attribute("node.execution_time_s", round(execution_time, 3))
            span.set_attribute("node.cost_usd", round(cost, 6))
            span.set_attribute("node.status", "success")
            span.set_status(StatusCode.OK)

    def record_node_failure(self, span, error: str, retry_count: int) -> None:
        """Record node failure on span. Requirements: 16.6, 16.7"""
        if _OTEL_AVAILABLE and not isinstance(span, _NoOpSpan):
            span.set_attribute("node.status", "failed")
            span.set_attribute("node.retry_count", retry_count)
            span.set_attribute("node.error", error[:500])
            span.set_status(StatusCode.ERROR, error)

    @property
    def is_available(self) -> bool:
        """Check if OpenTelemetry is available."""
        return _OTEL_AVAILABLE


# Global tracer instance
graph_tracer = GraphTracer()


def get_graph_tracer() -> GraphTracer:
    """Get the global GraphTracer instance."""
    return graph_tracer
