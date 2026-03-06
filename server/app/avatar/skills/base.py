# app/avatar/skills/base.py

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Type, Generic, TypeVar, Dict, Any, Set
from enum import Enum

from .context import SkillContext
from .schema import SkillInput, SkillOutput

# Define generic types for Input/Output to allow type hinting in subclasses
InT = TypeVar("InT", bound=SkillInput)
OutT = TypeVar("OutT", bound=SkillOutput)


class SkillCategory(str, Enum):
    FILE = "file"
    SYSTEM = "system"
    WEB = "web"
    OFFICE = "office"
    EXPERIMENTAL = "experimental"
    COMPUTER = "computer" # Added computer category
    OTHER = "other"


class SkillDomain(str, Enum):
    """Domain for capability routing (Gatekeeper V2)"""
    FILE = "file"
    WEB = "web"
    OFFICE = "office"
    COMPUTE = "compute"
    SYSTEM = "system"
    UI = "ui"
    OTHER = "other"


class SkillCapability(str, Enum):
    """Atomic capabilities for permission checking"""
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NAVIGATE = "navigate"
    CREATE = "create"
    DELETE = "delete"
    MODIFY = "modify"
    SEARCH = "search"


class SkillRiskLevel(str, Enum):
    """
    Skill 风险级别（用于执行器选择）
    
    - SAFE: 纯计算，无副作用（math, json）
    - READ: 只读操作（fs.read, web.fetch）
    - WRITE: 写操作（fs.write, db.insert）
    - EXECUTE: 代码执行（python.run, shell.exec）
    - SYSTEM: 系统级操作（process.kill, network.config）
    """
    SAFE = "safe"
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    SYSTEM = "system"


class ExecutionClass(str, Enum):
    """
    执行器类别（显式声明，用于路由）
    
    - AUTO: 自动推导（默认，基于 risk_level）
    - LOCAL: 本机直接执行（纯计算，无副作用）
    - PROCESS: 子进程隔离（文件/DB 操作）
    - WASM_PLUGIN: WASM 插件加速（预编译静态工具）
    - SANDBOX: 强隔离沙箱（动态代码，Kata/Docker）
    
    注意：
    - AUTO 是默认值，Factory 会根据 risk_level 自动推导
    - 动态代码（LLM 生成）必须使用 SANDBOX
    - WASM_PLUGIN 仅用于预编译的静态工具
    """
    AUTO = "auto"
    LOCAL = "local"
    PROCESS = "process"
    WASM_PLUGIN = "wasm_plugin"
    SANDBOX = "sandbox"


@dataclass
class SkillMetadata:
    """
    Structured metadata for capability routing.
    Replaces loose keywords and implicit logic.
    """
    domain: SkillDomain
    capabilities: Set[SkillCapability] = field(default_factory=set)
    risk_level: SkillRiskLevel = SkillRiskLevel.SAFE  # 默认为 SAFE
    exec_class: ExecutionClass = ExecutionClass.AUTO  # 默认为 AUTO（自动推导）
    is_generic: bool = False   # True for fallback skills like python.run
    
    # 智能路由权重配置（避免硬编码）
    priority: int = 50  # 优先级：0-100，默认50。专用技能建议70+，通用技能建议30-
    min_match_score: float = 0.3  # 最低匹配分数：0-1，低于此分数将被过滤。通用技能建议设置更高阈值（0.6+）
    
    # 文件扩展名约束
    file_extensions: List[str] = field(default_factory=list) # Supported file extensions (e.g., [".txt", ".md"])


@dataclass
class SkillPermission:
    """Declaration of a permission required by a skill."""
    name: str
    description: str


@dataclass
class SkillSpec:
    """
    Metadata describing a skill.
    Used by the Registry, Router, Planner, and UI to understand the skill.
    """
    name: str                         # Legacy global name (now acts as default api_name)
    description: str                  # Description for LLM/UI
    category: SkillCategory
    input_model: Type[SkillInput]     # Pydantic input model class
    output_model: Type[SkillOutput]   # Pydantic output model class
    
    # Capability Routing (V2) - The future standard
    meta: SkillMetadata = field(default_factory=lambda: SkillMetadata(SkillDomain.OTHER))
    
    # Advanced Routing Fields
    api_name: str = ""                # Stable external API name (defaults to name)
    internal_name: str = ""           # Internal unique ID (defaults to name)
    aliases: List[str] = field(default_factory=list) # Alias names for compatibility/fuzzy match
    version: str = "1.0.0"            # Semantic versioning
    
    # Semantic Search Fields (V2)
    synonyms: List[str] = field(default_factory=list) # Natural language synonyms for embedding match
    examples: List[Dict[str, Any]] = field(default_factory=list) # Usage examples {"params": {...}, "description": "..."}
    
    # ✅ Artifact Management (混合方案：声明式 + 命令式逃生舱)
    produces_artifact: bool = False  # 是否产生持久化产物
    artifact_type: str = ""  # 产物类型，如 "document:word", "file:text", "archive:zip"
    artifact_path_field: str = "path"  # 从输出的哪个字段读取产物路径（默认 "path"）
    artifact_metadata: Dict[str, Any] = field(default_factory=dict)  # 额外的产物元数据
    manual_artifact_registration: bool = False  # 是否使用手动注册（复杂场景的逃生舱）
    
    permissions: List[SkillPermission] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    deprecated: bool = False
    
    # Parameter Mapping - 智能容错机制（元数据驱动，非硬编码）
    # 格式：{"别名": "标准参数名"} 例如 {"command": "code", "script": "code"}
    param_aliases: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not self.api_name:
            self.api_name = self.name
        if not self.internal_name:
            self.internal_name = self.name


class BaseSkill(ABC, Generic[InT, OutT]):
    """
    Base class for all skills.
    
    Contract:
      - Must define a class attribute `spec` of type SkillSpec.
      - Must implement `run(context, params)`.
    """
    
    # Abstract property for spec? Or just a class attribute convention.
    # We'll use class attribute for simplicity.
    spec: SkillSpec

    @abstractmethod
    async def run(self, context: SkillContext, params: InT) -> OutT:
        """
        Execute the skill logic.
        
        Args:
            context: Runtime context (memory, logger, etc.)
            params: Validated input parameters (Pydantic model)
            
        Returns:
            SkillOutput (Pydantic model)
        """
        pass
