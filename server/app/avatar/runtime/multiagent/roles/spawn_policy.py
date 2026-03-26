"""SpawnPolicy — 实例创建策略.

Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class SpawnPolicy:
    """实例创建策略.

    per_role_limits 定义每种角色最大并发实例数。
    global_max_instances 定义全局最大实例总数。
    """
    per_role_limits: Dict[str, int] = field(default_factory=lambda: {
        "supervisor": 1,
        "planner": 1,
        "researcher": 3,
        "executor": 5,
        "verifier": 3,
        "recovery": 2,
    })
    global_max_instances: int = 15

    def can_spawn(
        self,
        role_name: str,
        active_instances: Dict[str, int],
        budget_available: bool = True,
    ) -> tuple[bool, str]:
        """检查是否允许创建新实例.

        Returns (allowed, reason).
        """
        if not budget_available:
            return False, "budget exhausted"

        role_limit = self.per_role_limits.get(role_name)
        if role_limit is not None:
            current = active_instances.get(role_name, 0)
            if current >= role_limit:
                return False, (
                    f"role '{role_name}' at limit: {current}/{role_limit}"
                )

        total = sum(active_instances.values())
        if total >= self.global_max_instances:
            return False, (
                f"global instance limit reached: {total}/{self.global_max_instances}"
            )

        return True, "ok"
