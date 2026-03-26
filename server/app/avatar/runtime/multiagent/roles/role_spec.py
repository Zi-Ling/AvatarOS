"""RoleSpec, ContextScope, LifecyclePolicy, RoleSpecRegistry.

角色规格定义与注册表。每种角色通过 RoleSpec 声明其语义协议、
工具权限、上下文范围和生命周期策略。

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# RoleSpec 必填字段列表
_REQUIRED_FIELDS = [
    "role_name", "description", "allowed_tools", "context_scope",
    "lifecycle_policy", "is_singleton", "input_schema", "output_schema",
]


@dataclass
class ContextScope:
    """上下文范围定义."""
    access_level: str = "task_local"          # "global" | "task_local" | "read_only"
    allowed_artifact_types: List[str] = field(default_factory=list)
    max_context_tokens: int = 0


@dataclass
class LifecyclePolicy:
    """生命周期策略."""
    idle_timeout_seconds: float = 300.0
    max_task_duration_seconds: float = 600.0
    auto_terminate_on_idle: bool = True


@dataclass
class RoleSpec:
    """角色规格定义.

    实例并发上限由 SpawnPolicy 统一管理，RoleSpec 不重复定义。
    """
    role_name: str = ""
    description: str = ""
    allowed_tools: List[str] = field(default_factory=list)
    context_scope: ContextScope = field(default_factory=ContextScope)
    lifecycle_policy: LifecyclePolicy = field(default_factory=LifecyclePolicy)
    is_singleton: bool = False
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0.0"


class RoleSpecRegistry:
    """角色规格注册表.

    核心角色在初始化时预注册。支持临时角色受控注册。
    Requirements: 1.1, 1.2, 1.3, 1.5, 1.6
    """

    CORE_ROLES = ["supervisor", "planner", "researcher", "executor", "verifier", "recovery"]

    def __init__(self) -> None:
        self._specs: Dict[str, RoleSpec] = {}
        self._temporary: set[str] = set()
        self._register_core_roles()

    def _register_core_roles(self) -> None:
        """预注册 6 种核心角色."""
        defaults: Dict[str, Dict[str, Any]] = {
            "supervisor": {
                "description": "全局单例调度者，驱动主循环",
                "allowed_tools": ["*"],
                "context_scope": ContextScope(access_level="global"),
                "is_singleton": True,
            },
            "planner": {
                "description": "任务分解与子图规划",
                "allowed_tools": ["plan_*", "read_*"],
                "context_scope": ContextScope(access_level="global"),
                "is_singleton": True,
            },
            "researcher": {
                "description": "信息收集与事实研究，仅使用只读工具",
                "allowed_tools": ["read_*", "search_*", "browse_*"],
                "context_scope": ContextScope(access_level="read_only"),
                "is_singleton": False,
            },
            "executor": {
                "description": "执行具体任务，可使用读写工具",
                "allowed_tools": ["*"],
                "context_scope": ContextScope(access_level="task_local"),
                "is_singleton": False,
            },
            "verifier": {
                "description": "独立验证执行结果",
                "allowed_tools": ["read_*", "verify_*", "test_*"],
                "context_scope": ContextScope(access_level="read_only"),
                "is_singleton": False,
            },
            "recovery": {
                "description": "故障分析与恢复策略制定",
                "allowed_tools": ["read_*", "analyze_*"],
                "context_scope": ContextScope(access_level="task_local"),
                "is_singleton": False,
            },
        }
        for role_name in self.CORE_ROLES:
            cfg = defaults[role_name]
            spec = RoleSpec(
                role_name=role_name,
                description=cfg["description"],
                allowed_tools=cfg["allowed_tools"],
                context_scope=cfg.get("context_scope", ContextScope()),
                lifecycle_policy=LifecyclePolicy(),
                is_singleton=cfg.get("is_singleton", False),
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
            self._specs[role_name] = spec

    def validate_spec(self, spec: RoleSpec) -> List[str]:
        """校验 RoleSpec，返回缺失字段名称列表."""
        missing: List[str] = []
        for f in _REQUIRED_FIELDS:
            val = getattr(spec, f, None)
            if val is None:
                missing.append(f)
            elif isinstance(val, str) and not val:
                missing.append(f)
            elif isinstance(val, list) and f == "allowed_tools" and len(val) == 0:
                missing.append(f)
        return missing

    def register(self, spec: RoleSpec) -> None:
        """注册角色规格. 缺少必填字段时抛出 ValueError."""
        missing = self.validate_spec(spec)
        if missing:
            raise ValueError(
                f"RoleSpec '{spec.role_name}' missing required fields: {', '.join(missing)}"
            )
        self._specs[spec.role_name] = spec
        logger.info("[RoleSpecRegistry] registered role: %s", spec.role_name)

    def get(self, role_name: str) -> Optional[RoleSpec]:
        """按 role_name 查询角色规格."""
        return self._specs.get(role_name)

    def register_temporary(self, spec: RoleSpec, parent_allowed_tools: Optional[List[str]] = None) -> None:
        """受控注册临时角色.

        校验工具权限不超出声明范围（parent_allowed_tools）。
        """
        missing = self.validate_spec(spec)
        if missing:
            raise ValueError(
                f"Temporary RoleSpec '{spec.role_name}' missing required fields: {', '.join(missing)}"
            )
        if parent_allowed_tools is not None:
            for tool in spec.allowed_tools:
                if not any(fnmatch(tool, pat) for pat in parent_allowed_tools):
                    raise ValueError(
                        f"Temporary role '{spec.role_name}' tool '{tool}' "
                        f"exceeds parent allowed scope: {parent_allowed_tools}"
                    )
        self._specs[spec.role_name] = spec
        self._temporary.add(spec.role_name)
        logger.info("[RoleSpecRegistry] registered temporary role: %s", spec.role_name)

    def list_registered(self) -> List[str]:
        """列出所有已注册角色名称."""
        return list(self._specs.keys())

    def is_temporary(self, role_name: str) -> bool:
        """判断角色是否为临时角色."""
        return role_name in self._temporary
