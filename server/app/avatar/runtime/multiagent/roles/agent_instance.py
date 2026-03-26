"""AgentInstance, AgentInstanceState, AgentInstanceStatus, RoleRunner, TaskPacket, SuccessCriterion.

Agent 实例运行时对象与生命周期管理。

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 4.1, 6.1, 22.1, 22.2
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class AgentInstanceStatus(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    IDLE = "idle"
    FAILED = "failed"
    TERMINATED = "terminated"


@dataclass
class ResourceConsumption:
    """累计资源消耗.

    更新责任：BudgetMonitor 是唯一写入方。
    AgentInstance 和 Supervisor 只读取，不直接修改。
    """
    total_tokens: int = 0
    total_api_calls: int = 0
    total_cost_usd: float = 0.0
    total_duration_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "total_api_calls": self.total_api_calls,
            "total_cost_usd": self.total_cost_usd,
            "total_duration_seconds": self.total_duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ResourceConsumption:
        return cls(
            total_tokens=data.get("total_tokens", 0),
            total_api_calls=data.get("total_api_calls", 0),
            total_cost_usd=data.get("total_cost_usd", 0.0),
            total_duration_seconds=data.get("total_duration_seconds", 0.0),
        )


@dataclass
class SuccessCriterion:
    """结构化成功标准."""
    criterion_id: str = ""
    description: str = ""
    check_type: str = ""  # "artifact_exists" | "schema_match" | "value_range" | "llm_judge"
    check_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskPacket:
    """统一任务输入包."""
    goal: str = ""
    input_bindings: Dict[str, Any] = field(default_factory=dict)
    allowed_tools: List[str] = field(default_factory=list)
    output_contract: Dict[str, Any] = field(default_factory=dict)
    success_criteria: List[SuccessCriterion] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentInstanceState:
    """Agent 实例状态，支持序列化/反序列化往返一致性."""
    instance_id: str = ""
    role_name: str = ""
    status: AgentInstanceStatus = AgentInstanceStatus.CREATED
    created_at: float = field(default_factory=time.time)
    owned_task_ids: List[str] = field(default_factory=list)
    resource_consumption: ResourceConsumption = field(default_factory=ResourceConsumption)
    last_active_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "role_name": self.role_name,
            "status": self.status.value,
            "created_at": self.created_at,
            "owned_task_ids": list(self.owned_task_ids),
            "resource_consumption": self.resource_consumption.to_dict(),
            "last_active_at": self.last_active_at,
            "metadata": dict(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentInstanceState:
        return cls(
            instance_id=data.get("instance_id", ""),
            role_name=data.get("role_name", ""),
            status=AgentInstanceStatus(data.get("status", "created")),
            created_at=data.get("created_at", time.time()),
            owned_task_ids=list(data.get("owned_task_ids") or []),
            resource_consumption=ResourceConsumption.from_dict(
                data.get("resource_consumption") or {}
            ),
            last_active_at=data.get("last_active_at", time.time()),
            metadata=dict(data.get("metadata") or {}),
            schema_version=data.get("schema_version", "1.0.0"),
        )


@runtime_checkable
class RoleRunner(Protocol):
    """角色执行器协议，每种角色实现此接口."""
    async def execute(
        self, task_packet: TaskPacket, context: Dict[str, Any]
    ) -> Dict[str, Any]: ...


class AgentInstance:
    """Agent 实例运行时对象.

    构造函数接收 RoleSpec、instance_id、RoleRunner。
    初始状态为 CREATED，owned_task_ids 为空，resource_consumption 全零。
    """

    def __init__(
        self,
        spec: Any,  # RoleSpec — avoid circular import
        instance_id: Optional[str] = None,
        runner: Optional[RoleRunner] = None,
    ) -> None:
        self._spec = spec
        self._runner = runner
        now = time.time()
        self._state = AgentInstanceState(
            instance_id=instance_id or str(uuid.uuid4()),
            role_name=getattr(spec, "role_name", ""),
            status=AgentInstanceStatus.CREATED,
            created_at=now,
            owned_task_ids=[],
            resource_consumption=ResourceConsumption(),
            last_active_at=now,
        )

    @property
    def state(self) -> AgentInstanceState:
        return self._state

    @property
    def instance_id(self) -> str:
        return self._state.instance_id

    @property
    def role_name(self) -> str:
        return self._state.role_name

    @property
    def spec(self) -> Any:
        return self._spec

    async def run(self, task_packet: TaskPacket) -> Dict[str, Any]:
        """统一执行入口，委托给绑定的 RoleRunner."""
        if self._runner is None:
            raise RuntimeError(f"AgentInstance {self.instance_id} has no RoleRunner bound")
        self._state.last_active_at = time.time()
        context: Dict[str, Any] = {
            "instance_id": self.instance_id,
            "role_name": self.role_name,
        }
        return await self._runner.execute(task_packet, context)

    def activate(self, task_id: str) -> None:
        """分配任务，转为 ACTIVE 状态."""
        self._state.status = AgentInstanceStatus.ACTIVE
        if task_id not in self._state.owned_task_ids:
            self._state.owned_task_ids.append(task_id)
        self._state.last_active_at = time.time()

    def complete_task(self, task_id: str) -> None:
        """完成任务."""
        if task_id in self._state.owned_task_ids:
            self._state.owned_task_ids.remove(task_id)
        if not self._state.owned_task_ids:
            self._state.status = AgentInstanceStatus.IDLE
        self._state.last_active_at = time.time()

    def mark_failed(self, reason: str) -> None:
        """标记为失败状态."""
        self._state.status = AgentInstanceStatus.FAILED
        self._state.metadata["failure_reason"] = reason
        self._state.last_active_at = time.time()

    def check_idle(self) -> bool:
        """检查是否空闲."""
        return (
            self._state.status == AgentInstanceStatus.IDLE
            and len(self._state.owned_task_ids) == 0
        )

    def terminate(self) -> AgentInstanceState:
        """终止实例，返回最终状态."""
        self._state.status = AgentInstanceStatus.TERMINATED
        self._state.last_active_at = time.time()
        return self._state
