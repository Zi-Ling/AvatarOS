"""Multi-agent runtime metrics collection.

Lightweight in-process metrics for:
- Subtask execution time (histogram)
- Retry count per node
- Gate wait duration
- Cost distribution per role
- Dispatch throughput

Uses a simple in-memory collector that can be scraped via API.
No external dependency (Prometheus/StatsD) required — just expose via /metrics endpoint.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetricsConfig:
    """Configuration for metrics collection."""
    enabled: bool = True
    # Max data points to retain per metric (ring buffer)
    max_data_points: int = 1000
    # Histogram bucket boundaries for execution time (seconds)
    execution_time_buckets: tuple = (0.5, 1, 2, 5, 10, 30, 60, 120, 300)


@dataclass
class MetricPoint:
    """Single metric data point."""
    name: str
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class MultiAgentMetrics:
    """In-process metrics collector for multi-agent runtime."""

    def __init__(self, config: Optional[MetricsConfig] = None) -> None:
        self._cfg = config or MetricsConfig()
        self._lock = threading.Lock()
        # Counters
        self._counters: Dict[str, float] = defaultdict(float)
        # Gauges (current values)
        self._gauges: Dict[str, float] = {}
        # Histograms (list of values for percentile computation)
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        # Recent data points (ring buffer)
        self._points: List[MetricPoint] = []

    def _record(self, point: MetricPoint) -> None:
        if not self._cfg.enabled:
            return
        with self._lock:
            self._points.append(point)
            if len(self._points) > self._cfg.max_data_points:
                self._points = self._points[-self._cfg.max_data_points:]

    # ── Subtask execution ───────────────────────────────────────────

    def record_subtask_execution(
        self,
        node_id: str,
        role: str,
        duration_seconds: float,
        success: bool,
    ) -> None:
        """Record a subtask execution completion."""
        with self._lock:
            self._counters[f"subtask_total:{role}"] += 1
            if success:
                self._counters[f"subtask_success:{role}"] += 1
            else:
                self._counters[f"subtask_failure:{role}"] += 1
            self._histograms[f"subtask_duration:{role}"].append(duration_seconds)

        self._record(MetricPoint(
            name="subtask_execution",
            value=duration_seconds,
            labels={"node_id": node_id, "role": role, "success": str(success)},
        ))

    # ── Retry tracking ──────────────────────────────────────────────

    def record_retry(self, node_id: str, retry_count: int, reason: str) -> None:
        """Record a subtask retry."""
        with self._lock:
            self._counters["retry_total"] += 1
            self._counters[f"retry:{reason}"] += 1

        self._record(MetricPoint(
            name="subtask_retry",
            value=float(retry_count),
            labels={"node_id": node_id, "reason": reason},
        ))

    # ── Gate metrics ────────────────────────────────────────────────

    def record_gate_wait(self, gate_id: str, wait_seconds: float, gate_type: str) -> None:
        """Record gate wait duration."""
        with self._lock:
            self._counters["gate_total"] += 1
            self._histograms["gate_wait_duration"].append(wait_seconds)

        self._record(MetricPoint(
            name="gate_wait",
            value=wait_seconds,
            labels={"gate_id": gate_id, "gate_type": gate_type},
        ))

    # ── Cost tracking ───────────────────────────────────────────────

    def record_cost(self, role: str, tokens: int, cost: float) -> None:
        """Record per-role cost."""
        with self._lock:
            self._counters[f"tokens:{role}"] += tokens
            self._counters[f"cost:{role}"] += cost

        self._record(MetricPoint(
            name="cost",
            value=cost,
            labels={"role": role, "tokens": str(tokens)},
        ))

    # ── Dispatch throughput ─────────────────────────────────────────

    def record_dispatch(self, concurrent_count: int) -> None:
        """Record a dispatch event with current concurrency level."""
        with self._lock:
            self._counters["dispatch_total"] += 1
            self._gauges["dispatch_concurrent"] = float(concurrent_count)

    # ── Read ────────────────────────────────────────────────────────

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all collected metrics."""
        with self._lock:
            summary: Dict[str, Any] = {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {},
            }
            for name, values in self._histograms.items():
                if not values:
                    continue
                sorted_vals = sorted(values)
                n = len(sorted_vals)
                summary["histograms"][name] = {
                    "count": n,
                    "min": sorted_vals[0],
                    "max": sorted_vals[-1],
                    "avg": sum(sorted_vals) / n,
                    "p50": sorted_vals[n // 2],
                    "p95": sorted_vals[int(n * 0.95)] if n >= 20 else sorted_vals[-1],
                    "p99": sorted_vals[int(n * 0.99)] if n >= 100 else sorted_vals[-1],
                }
            return summary

    def get_recent_points(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent metric data points."""
        with self._lock:
            return [
                {
                    "name": p.name,
                    "value": p.value,
                    "labels": p.labels,
                    "timestamp": p.timestamp,
                }
                for p in self._points[-limit:]
            ]


# Singleton instance
_metrics: Optional[MultiAgentMetrics] = None
_metrics_lock = threading.Lock()


def get_metrics(config: Optional[MetricsConfig] = None) -> MultiAgentMetrics:
    """Get or create the singleton metrics collector."""
    global _metrics
    if _metrics is None:
        with _metrics_lock:
            if _metrics is None:
                _metrics = MultiAgentMetrics(config)
    return _metrics
