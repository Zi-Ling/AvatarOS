"""AgentHealthMonitor — per-worker health tracking.

Maintains rolling metrics for each worker:
- consecutive_failures
- avg_completion_time (rolling window)
- contract_compliance_rate
- health_status: READY / BUSY / STUCK / DEGRADED / BROKEN

All thresholds from MultiAgentConfig (no hardcoding).
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

from app.avatar.runtime.multiagent.config import MultiAgentConfig

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    READY = "ready"
    BUSY = "busy"
    STUCK = "stuck"
    DEGRADED = "degraded"
    BROKEN = "broken"


@dataclass
class WorkerHealth:
    """Health metrics for a single worker."""
    worker_id: str = ""
    role_name: str = ""
    health_status: HealthStatus = HealthStatus.READY
    consecutive_failures: int = 0
    total_tasks: int = 0
    total_successes: int = 0
    total_failures: int = 0
    completion_times: Deque[float] = field(default_factory=deque)
    contract_checks: Deque[bool] = field(default_factory=deque)
    last_activity_at: float = field(default_factory=time.time)
    stuck_since: Optional[float] = None

    @property
    def avg_completion_time(self) -> float:
        if not self.completion_times:
            return 0.0
        return sum(self.completion_times) / len(self.completion_times)

    @property
    def contract_compliance_rate(self) -> float:
        if not self.contract_checks:
            return 1.0
        return sum(1 for c in self.contract_checks if c) / len(self.contract_checks)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "role_name": self.role_name,
            "health_status": self.health_status.value,
            "consecutive_failures": self.consecutive_failures,
            "total_tasks": self.total_tasks,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "avg_completion_time": self.avg_completion_time,
            "contract_compliance_rate": self.contract_compliance_rate,
        }


class AgentHealthMonitor:
    """Tracks health of all workers, updates status based on config thresholds."""

    def __init__(self, config: Optional[MultiAgentConfig] = None) -> None:
        self._cfg = config or MultiAgentConfig()
        self._workers: Dict[str, WorkerHealth] = {}
        self._window = self._cfg.health_avg_completion_time_window

    def register(self, worker_id: str, role_name: str) -> WorkerHealth:
        """Register a new worker for health tracking."""
        health = WorkerHealth(
            worker_id=worker_id,
            role_name=role_name,
            completion_times=deque(maxlen=self._window),
            contract_checks=deque(maxlen=self._window),
        )
        self._workers[worker_id] = health
        return health

    def get(self, worker_id: str) -> Optional[WorkerHealth]:
        return self._workers.get(worker_id)

    def get_all(self) -> Dict[str, WorkerHealth]:
        return dict(self._workers)

    def record_success(
        self,
        worker_id: str,
        completion_time: float = 0.0,
        contract_met: bool = True,
    ) -> HealthStatus:
        """Record a successful task completion and return updated status."""
        h = self._workers.get(worker_id)
        if h is None:
            return HealthStatus.READY

        h.total_tasks += 1
        h.total_successes += 1
        h.consecutive_failures = 0
        h.last_activity_at = time.time()
        h.stuck_since = None

        if completion_time > 0:
            h.completion_times.append(completion_time)
        h.contract_checks.append(contract_met)

        return self._evaluate(h)

    def record_failure(self, worker_id: str) -> HealthStatus:
        """Record a task failure and return updated status."""
        h = self._workers.get(worker_id)
        if h is None:
            return HealthStatus.BROKEN

        h.total_tasks += 1
        h.total_failures += 1
        h.consecutive_failures += 1
        h.last_activity_at = time.time()

        return self._evaluate(h)

    def mark_busy(self, worker_id: str) -> None:
        h = self._workers.get(worker_id)
        if h:
            h.health_status = HealthStatus.BUSY
            h.last_activity_at = time.time()

    def check_stuck(self) -> List[str]:
        """Return worker IDs that are stuck (no activity beyond threshold)."""
        now = time.time()
        stuck: List[str] = []
        for wid, h in self._workers.items():
            if h.health_status == HealthStatus.BUSY:
                idle = now - h.last_activity_at
                if idle > self._cfg.health_stuck_timeout_seconds:
                    h.health_status = HealthStatus.STUCK
                    if h.stuck_since is None:
                        h.stuck_since = now
                    stuck.append(wid)
        return stuck

    def _evaluate(self, h: WorkerHealth) -> HealthStatus:
        """Evaluate health status based on config thresholds."""
        if h.consecutive_failures >= self._cfg.health_consecutive_failure_threshold:
            h.health_status = HealthStatus.BROKEN
        elif h.contract_compliance_rate < self._cfg.health_compliance_rate_threshold:
            h.health_status = HealthStatus.DEGRADED
        else:
            h.health_status = HealthStatus.READY
        return h.health_status

    def remove(self, worker_id: str) -> None:
        self._workers.pop(worker_id, None)

    def get_summary(self) -> Dict[str, Any]:
        by_status: Dict[str, int] = {}
        for h in self._workers.values():
            by_status[h.health_status.value] = by_status.get(h.health_status.value, 0) + 1
        return {
            "total_workers": len(self._workers),
            "by_status": by_status,
            "workers": [h.to_dict() for h in self._workers.values()],
        }
