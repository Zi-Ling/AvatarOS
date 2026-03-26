"""WorkerPoolManager — spawn / drain / replace / quarantine.

Manages the lifecycle of workers in the pool. Trigger conditions
from MultiAgentConfig.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from app.avatar.runtime.multiagent.config import MultiAgentConfig
from app.avatar.runtime.multiagent.resilience.health_monitor import AgentHealthMonitor, HealthStatus

logger = logging.getLogger(__name__)


class PoolAction(str, Enum):
    SPAWN = "spawn"
    DRAIN = "drain"
    REPLACE = "replace"
    QUARANTINE = "quarantine"


@dataclass
class PoolEvent:
    """Record of a pool management action."""
    action: PoolAction
    worker_id: str
    role_name: str = ""
    reason: str = ""
    timestamp: float = field(default_factory=time.time)


class WorkerPoolManager:
    """Manages worker pool lifecycle with health-aware decisions."""

    def __init__(
        self,
        config: Optional[MultiAgentConfig] = None,
        health_monitor: Optional[AgentHealthMonitor] = None,
    ) -> None:
        self._cfg = config or MultiAgentConfig()
        self._health = health_monitor
        # Active worker IDs by role
        self._active: Dict[str, Set[str]] = {}
        # Quarantined worker IDs
        self._quarantined: Set[str] = set()
        # Drained worker IDs (pending termination)
        self._draining: Set[str] = set()
        # Event log
        self._events: List[PoolEvent] = []

    @property
    def total_active(self) -> int:
        return sum(len(ids) for ids in self._active.values())

    def register(self, worker_id: str, role_name: str) -> None:
        """Register a worker in the pool."""
        self._active.setdefault(role_name, set()).add(worker_id)
        self._events.append(PoolEvent(
            action=PoolAction.SPAWN, worker_id=worker_id,
            role_name=role_name, reason="registered",
        ))

    def can_spawn(self, role_name: str) -> bool:
        """Check if a new worker can be spawned."""
        return self.total_active < self._cfg.pool_max_workers

    def should_quarantine(self, worker_id: str) -> bool:
        """Check if a worker should be quarantined based on health."""
        if self._health is None:
            return False
        wh = self._health.get(worker_id)
        if wh is None:
            return False
        return (
            wh.health_status == HealthStatus.BROKEN
            or wh.total_failures >= self._cfg.pool_quarantine_threshold
        )

    def quarantine(self, worker_id: str, reason: str = "") -> None:
        """Move a worker to quarantine."""
        self._quarantined.add(worker_id)
        # Remove from active
        for role_ids in self._active.values():
            role_ids.discard(worker_id)
        self._events.append(PoolEvent(
            action=PoolAction.QUARANTINE, worker_id=worker_id,
            reason=reason or "health threshold exceeded",
        ))
        logger.info("[WorkerPool] Quarantined %s: %s", worker_id, reason)

    def drain(self, worker_id: str, reason: str = "") -> None:
        """Mark a worker for draining (finish current task, then terminate)."""
        self._draining.add(worker_id)
        self._events.append(PoolEvent(
            action=PoolAction.DRAIN, worker_id=worker_id,
            reason=reason or "drain requested",
        ))

    def is_quarantined(self, worker_id: str) -> bool:
        return worker_id in self._quarantined

    def is_draining(self, worker_id: str) -> bool:
        return worker_id in self._draining

    def complete_drain(self, worker_id: str) -> None:
        """Finalize drain — remove from all tracking."""
        self._draining.discard(worker_id)
        self._quarantined.discard(worker_id)
        for role_ids in self._active.values():
            role_ids.discard(worker_id)

    def replace(self, old_worker_id: str, new_worker_id: str, role_name: str) -> None:
        """Replace a worker with a new one."""
        self.drain(old_worker_id, reason=f"replaced by {new_worker_id}")
        self.register(new_worker_id, role_name)
        self._events.append(PoolEvent(
            action=PoolAction.REPLACE, worker_id=new_worker_id,
            role_name=role_name,
            reason=f"replacing {old_worker_id}",
        ))

    def get_available(self, role_name: str) -> List[str]:
        """Get available (non-quarantined, non-draining) workers for a role."""
        role_ids = self._active.get(role_name, set())
        return [
            wid for wid in role_ids
            if wid not in self._quarantined and wid not in self._draining
        ]

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_active": self.total_active,
            "quarantined": len(self._quarantined),
            "draining": len(self._draining),
            "by_role": {
                role: len(ids) for role, ids in self._active.items()
            },
            "recent_events": [
                {
                    "action": e.action.value,
                    "worker_id": e.worker_id,
                    "reason": e.reason,
                }
                for e in self._events[-10:]  # last 10 events
            ],
        }
