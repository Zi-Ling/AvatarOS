"""
Graph Runtime Observability Metrics

Prometheus-compatible metrics for graph execution monitoring.

Requirements: 14.1-14.10
"""
from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from typing import Dict, Optional


class GraphMetrics:
    """
    Collects and exports Prometheus metrics for graph execution.

    Metrics:
    - graph_execution_duration_seconds
    - node_execution_duration_seconds
    - parallel_nodes_current
    - graph_status_total
    - scheduler_latency_ms
    - planner_latency_ms
    - edge_resolution_latency_ms

    Requirements: 14.1-14.10
    """

    def __init__(self):
        self._lock = Lock()

        # Graph execution durations: {status: [duration, ...]}
        self._graph_durations: Dict[str, list] = defaultdict(list)

        # Node execution durations: {capability_name: [duration, ...]}
        self._node_durations: Dict[str, list] = defaultdict(list)

        # Graph status counters: {status: count}
        self._graph_status_counts: Dict[str, int] = defaultdict(int)

        # Node status counters: {capability_name: {status: count}}
        self._node_status_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        # Current parallel nodes gauge
        self._parallel_nodes_current: int = 0

        # Scheduler latency samples (ms)
        self._scheduler_latencies: list = []

        # Planner latency samples (ms)
        self._planner_latencies: list = []

        # Edge resolution latency samples (ms)
        self._edge_resolution_latencies: list = []

        # Cost tracking
        self._graph_costs: Dict[str, float] = {}  # graph_id -> total_cost

    # ---- Graph-level recording ----

    def record_graph_start(self, graph_id: str) -> float:
        """Record graph execution start. Returns start timestamp."""
        return time.monotonic()

    def record_graph_end(self, graph_id: str, start_time: float, status: str, cost: float = 0.0) -> None:
        """Record graph execution completion. Requirements: 14.1, 14.4"""
        duration = time.monotonic() - start_time
        with self._lock:
            self._graph_durations[status].append(duration)
            self._graph_status_counts[status] += 1
            self._graph_costs[graph_id] = cost

    # ---- Node-level recording ----

    def record_node_start(self, node_id: str, capability_name: str) -> float:
        """Record node execution start. Returns start timestamp."""
        with self._lock:
            self._parallel_nodes_current += 1
        return time.monotonic()

    def record_node_end(
        self,
        node_id: str,
        capability_name: str,
        start_time: float,
        status: str
    ) -> None:
        """Record node execution completion. Requirements: 14.2, 14.3"""
        duration = time.monotonic() - start_time
        with self._lock:
            self._parallel_nodes_current = max(0, self._parallel_nodes_current - 1)
            self._node_durations[capability_name].append(duration)
            self._node_status_counts[capability_name][status] += 1

    # ---- Scheduler / Planner / Edge recording ----

    def record_scheduler_latency(self, latency_ms: float) -> None:
        """Record scheduler get_ready_nodes latency. Requirements: 14.5"""
        with self._lock:
            self._scheduler_latencies.append(latency_ms)

    def record_planner_latency(self, latency_ms: float) -> None:
        """Record planner invocation latency. Requirements: 14.6"""
        with self._lock:
            self._planner_latencies.append(latency_ms)

    def record_edge_resolution_latency(self, latency_ms: float) -> None:
        """Record edge parameter resolution latency. Requirements: 14.7"""
        with self._lock:
            self._edge_resolution_latencies.append(latency_ms)

    # ---- Prometheus export ----

    def get_prometheus_metrics(self) -> str:
        """Export metrics in Prometheus text format. Requirements: 14.1-14.10"""
        with self._lock:
            lines = []

            # 1. Graph execution duration
            lines.append("# HELP graph_execution_duration_seconds Graph execution duration")
            lines.append("# TYPE graph_execution_duration_seconds histogram")
            for status, durations in self._graph_durations.items():
                if durations:
                    avg = sum(durations) / len(durations)
                    lines.append(
                        f'graph_execution_duration_seconds{{status="{status}"}} {avg:.6f}'
                    )

            # 2. Node execution duration
            lines.append("# HELP node_execution_duration_seconds Node execution duration")
            lines.append("# TYPE node_execution_duration_seconds histogram")
            for cap, durations in self._node_durations.items():
                if durations:
                    avg = sum(durations) / len(durations)
                    lines.append(
                        f'node_execution_duration_seconds{{capability="{cap}"}} {avg:.6f}'
                    )

            # 3. Parallel nodes current
            lines.append("# HELP parallel_nodes_current Current number of parallel executing nodes")
            lines.append("# TYPE parallel_nodes_current gauge")
            lines.append(f"parallel_nodes_current {self._parallel_nodes_current}")

            # 4. Graph status total
            lines.append("# HELP graph_status_total Total graphs by final status")
            lines.append("# TYPE graph_status_total counter")
            for status, count in self._graph_status_counts.items():
                lines.append(f'graph_status_total{{status="{status}"}} {count}')

            # 5. Scheduler latency
            lines.append("# HELP scheduler_latency_ms Scheduler get_ready_nodes latency (ms)")
            lines.append("# TYPE scheduler_latency_ms gauge")
            if self._scheduler_latencies:
                avg = sum(self._scheduler_latencies) / len(self._scheduler_latencies)
                lines.append(f"scheduler_latency_ms {avg:.3f}")

            # 6. Planner latency
            lines.append("# HELP planner_latency_ms Planner invocation latency (ms)")
            lines.append("# TYPE planner_latency_ms gauge")
            if self._planner_latencies:
                avg = sum(self._planner_latencies) / len(self._planner_latencies)
                lines.append(f"planner_latency_ms {avg:.3f}")

            # 7. Edge resolution latency
            lines.append("# HELP edge_resolution_latency_ms Edge parameter resolution latency (ms)")
            lines.append("# TYPE edge_resolution_latency_ms gauge")
            if self._edge_resolution_latencies:
                avg = sum(self._edge_resolution_latencies) / len(self._edge_resolution_latencies)
                lines.append(f"edge_resolution_latency_ms {avg:.3f}")

            # 8. Cost metrics
            lines.append("# HELP capability_execution_cost_total Total execution cost by graph")
            lines.append("# TYPE capability_execution_cost_total gauge")
            for graph_id, cost in self._graph_costs.items():
                lines.append(f'graph_execution_cost_total{{graph_id="{graph_id}"}} {cost:.6f}')

            return "\n".join(lines) + "\n"

    def get_summary(self) -> Dict:
        """Get metrics summary dict."""
        with self._lock:
            total_graphs = sum(self._graph_status_counts.values())
            total_nodes = sum(
                sum(s.values()) for s in self._node_status_counts.values()
            )
            return {
                "total_graphs": total_graphs,
                "graph_status": dict(self._graph_status_counts),
                "total_nodes": total_nodes,
                "parallel_nodes_current": self._parallel_nodes_current,
                "avg_scheduler_latency_ms": (
                    sum(self._scheduler_latencies) / len(self._scheduler_latencies)
                    if self._scheduler_latencies else 0
                ),
                "avg_planner_latency_ms": (
                    sum(self._planner_latencies) / len(self._planner_latencies)
                    if self._planner_latencies else 0
                ),
            }

    def get_executor_metrics(self) -> str:
        """
        Get Prometheus metrics from ExecutorFactory (executor_executions_total, error_rate, etc.)
        Integrates existing executor metrics into Graph Runtime observability.

        Requirements: 17.9, 17.11
        """
        try:
            from app.avatar.runtime.executor.metrics import get_metrics
            return get_metrics().get_prometheus_metrics()
        except ImportError:
            return "# ExecutorFactory metrics not available\n"

    def get_combined_prometheus_metrics(self) -> str:
        """
        Export combined metrics: Graph Runtime + ExecutorFactory.

        Requirements: 14.1-14.10, 17.9, 17.11
        """
        graph_part = self.get_prometheus_metrics()
        executor_part = self.get_executor_metrics()
        return graph_part + executor_part

    def get_executor_summary(self) -> Dict:
        """Get executor metrics summary dict. Requirements: 17.9"""
        try:
            from app.avatar.runtime.executor.metrics import get_metrics
            return get_metrics().get_summary()
        except ImportError:
            return {}

    def reset(self) -> None:
        """Reset all metrics (for testing)."""
        with self._lock:
            self._graph_durations.clear()
            self._node_durations.clear()
            self._graph_status_counts.clear()
            self._node_status_counts.clear()
            self._parallel_nodes_current = 0
            self._scheduler_latencies.clear()
            self._planner_latencies.clear()
            self._edge_resolution_latencies.clear()
            self._graph_costs.clear()


# Global metrics instance
graph_metrics = GraphMetrics()


def get_graph_metrics() -> GraphMetrics:
    """Get the global GraphMetrics instance."""
    return graph_metrics
