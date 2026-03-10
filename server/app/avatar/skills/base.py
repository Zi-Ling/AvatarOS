# app/avatar/skills/base.py

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Type, Generic, TypeVar, Set
from enum import Enum

from .context import SkillContext
from .schema import SkillInput, SkillOutput

InT = TypeVar("InT", bound=SkillInput)
OutT = TypeVar("OutT", bound=SkillOutput)


class SideEffect(str, Enum):
    """副作用类型 - 描述 skill 对外部世界的影响"""
    FS = "fs"
    NETWORK = "network"
    EXEC = "exec"
    HUMAN = "human"
    BROWSER = "browser"  # 浏览器自动化：需要联网沙箱（browser sandbox）


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
    """
    name: str
    description: str
    input_model: Type[SkillInput]
    output_model: Type[SkillOutput]
    side_effects: Set[SideEffect] = field(default_factory=set)
    risk_level: SkillRiskLevel = SkillRiskLevel.SAFE
    aliases: List[str] = field(default_factory=list)


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
