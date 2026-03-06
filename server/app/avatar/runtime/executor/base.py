# app/avatar/runtime/executor/base.py

"""
执行器抽象基类

定义所有执行器的统一接口
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any
import logging

logger = logging.getLogger(__name__)


class ExecutionStrategy(Enum):
    """执行策略"""
    LOCAL = "local"              # 本地执行（无隔离）
    PROCESS = "process"          # 进程隔离
    DOCKER = "docker"            # Docker 容器
    WASM = "wasm"                # WASM 沙箱（未来）
    KATA = "kata"                # Kata Containers（未来）
    FIRECRACKER = "firecracker"  # Firecracker MicroVM（接口预留）


class SkillExecutor(ABC):
    """
    Skill 执行器抽象基类
    
    所有执行器必须实现以下接口：
    - execute(): 执行 Skill
    - supports(): 检查是否支持该 Skill
    - health_check(): 健康检查
    - cleanup(): 资源清理
    """
    
    def __init__(self):
        self.strategy = ExecutionStrategy.LOCAL
        self._healthy = True
    
    @abstractmethod
    async def execute(
        self,
        skill: Any,
        input_data: Any,
        context: Any
    ) -> Any:
        """
        执行 Skill
        
        Args:
            skill: Skill 实例
            input_data: 输入数据（已验证的 Pydantic 模型）
            context: SkillContext
        
        Returns:
            执行结果
        
        Raises:
            Exception: 执行失败时抛出异常
        """
        pass
    
    @abstractmethod
    def supports(self, skill: Any) -> bool:
        """
        检查是否支持该 Skill
        
        Args:
            skill: Skill 实例
        
        Returns:
            是否支持
        """
        pass
    
    def health_check(self) -> bool:
        """
        健康检查
        
        Returns:
            是否健康
        """
        return self._healthy
    
    def cleanup(self):
        """资源清理（可选实现）"""
        pass
    
    def __repr__(self):
        return f"<{self.__class__.__name__} strategy={self.strategy.value}>"
