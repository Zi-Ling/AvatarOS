# app/avatar/skills/base.py

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Type, Generic, TypeVar, Set, Optional, TYPE_CHECKING
from enum import Enum

from .context import SkillContext
from .schema import SkillInput, SkillOutput

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.output_contract import SkillOutputContract

InT = TypeVar("InT", bound=SkillInput)
OutT = TypeVar("OutT", bound=SkillOutput)


class SideEffect(str, Enum):
    """副作用类型 - 描述 skill 对外部世界的影响"""
    FS = "fs"
    NETWORK = "network"
    EXEC = "exec"
    HUMAN = "human"
    BROWSER = "browser"  # 浏览器自动化：需要联网沙箱（browser sandbox）
    GUI_CONTROL = "gui_control"  # 桌面 GUI 操控：直接作用于宿主系统，无沙箱隔离
    DATA_READ = "data_read"  # 结构化数据层：读操作
    DATA_WRITE = "data_write"  # 结构化数据层：写操作


class SkillRiskLevel(str, Enum):
    """
    风险级别 - 用于执行器路由和安全策略

    - SAFE: 纯计算，无副作用
    - READ: 只读操作
    - WRITE: 写操作
    - EXECUTE: 代码执行
    - SYSTEM: 系统级操作
    """
    SAFE = "safe"
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    SYSTEM = "system"


@dataclass
class SkillSpec:
    """
    Skill 元数据 - 唯一 source of truth

    字段职责：
    - name: 唯一标识 + LLM tool name
    - description: LLM 理解用
    - input_model / output_model: 类型约束
    - side_effects: 副作用声明（用于 executor 路由 + 审计）
    - risk_level: 安全等级（用于策略引擎）
    - aliases: 召回优化（fuzzy match + 向量搜索）
    - code_params: 包含可执行代码的参数名集合。这些参数中的
      step_N_output 引用由运行时变量注入处理，不创建 DataEdge。
    - tags: 语义标签（中英文），用于 GoalTracker 的 sub-goal 覆盖匹配。
      每个 skill 声明自己的 tags，GoalTracker 从 registry 读取。
    """
    name: str
    description: str
    input_model: Type[SkillInput]
    output_model: Type[SkillOutput]
    side_effects: Set[SideEffect] = field(default_factory=set)
    risk_level: SkillRiskLevel = SkillRiskLevel.SAFE
    aliases: List[str] = field(default_factory=list)
    code_params: Set[str] = field(default_factory=set)
    tags: List[str] = field(default_factory=list)
    dedup_mode: str = "fuzzy"  # "skip" | "exact" | "fuzzy"
    output_contract: Optional['SkillOutputContract'] = None  # 声明式输出契约，避免运行时推断
    requires_host_desktop: bool = False  # 显式声明：必须在宿主机桌面环境执行（GUI 操控类技能）


class BaseSkill(ABC, Generic[InT, OutT]):
    """
    所有 skill 的基类。

    约定：
    - 子类必须定义类属性 `spec: SkillSpec`
    - 子类必须实现 `run(context, params)`
    """
    spec: SkillSpec

    @abstractmethod
    async def run(self, context: SkillContext, params: InT) -> OutT:
        pass
