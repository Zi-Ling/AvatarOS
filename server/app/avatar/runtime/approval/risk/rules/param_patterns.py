"""
参数模式匹配器 - 检测危险参数
"""
from __future__ import annotations

import logging
import re
from typing import Dict, Any, List, Tuple
from ..levels import RiskLevel

logger = logging.getLogger(__name__)


class ParamPatternMatcher:
    """
    参数模式匹配器
    
    检测危险的参数模式，例如：
    - path 包含系统目录
    - command 包含危险命令
    - 递归删除标志
    """
    
    # 危险路径模式
    DANGEROUS_PATHS = [
        r"^C:\\Windows",
        r"^/etc/",
        r"^/usr/",
        r"^/bin/",
        r"^/sbin/",
        r"^C:\\Program Files",
    ]
    
    # 危险命令模式
    DANGEROUS_COMMANDS = [
        r"rm\s+-rf",
        r"del\s+/s",
        r"format\s+",
        r"fdisk",
        r"dd\s+if=",
        r"mkfs",
    ]
    
    # 递归操作标志
    RECURSIVE_FLAGS = [
        "-rf",
        "-r",
        "--recursive",
        "/s",
    ]
    
    @classmethod
    def analyze_params(cls, params: Dict[str, Any]) -> Tuple[RiskLevel, List[str]]:
        """
        分析参数的风险
        
        Args:
            params: 参数字典
        
        Returns:
            (risk_level, warnings): 风险等级和警告列表
        """
        max_risk = RiskLevel.LOW
        warnings = []
        
        # 检查每个参数
        for key, value in params.items():
            if not isinstance(value, str):
                continue
            
            key_lower = key.lower()
            value_lower = value.lower()
            
            # 检查路径
            if any(keyword in key_lower for keyword in ['path', 'dir', 'file', 'folder']):
                path_risk, path_warnings = cls._check_path(value)
                if path_risk > max_risk:
                    max_risk = path_risk
                warnings.extend(path_warnings)
            
            # 检查命令
            if any(keyword in key_lower for keyword in ['command', 'cmd', 'exec']):
                cmd_risk, cmd_warnings = cls._check_command(value)
                if cmd_risk > max_risk:
                    max_risk = cmd_risk
                warnings.extend(cmd_warnings)
            
            # 检查递归标志
            if cls._is_recursive(value):
                max_risk = max(max_risk, RiskLevel.HIGH)
                warnings.append(f"Recursive operation detected in {key}")
        
        return max_risk, warnings
    
    @classmethod
    def _check_path(cls, path: str) -> Tuple[RiskLevel, List[str]]:
        """
        检查路径是否危险
        
        Args:
            path: 路径字符串
        
        Returns:
            (risk_level, warnings)
        """
        warnings = []
        risk = RiskLevel.LOW
        
        # 检查系统目录
        for pattern in cls.DANGEROUS_PATHS:
            if re.match(pattern, path, re.IGNORECASE):
                risk = RiskLevel.HIGH
                warnings.append(f"System path detected: {path}")
                break
        
        # 检查根目录操作
        if path in ['/', 'C:\\', 'C:/']:
            risk = RiskLevel.CRITICAL
            warnings.append(f"Root directory operation: {path}")
        
        return risk, warnings
    
    @classmethod
    def _check_command(cls, command: str) -> Tuple[RiskLevel, List[str]]:
        """
        检查命令是否危险
        
        Args:
            command: 命令字符串
        
        Returns:
            (risk_level, warnings)
        """
        warnings = []
        risk = RiskLevel.LOW
        
        for pattern in cls.DANGEROUS_COMMANDS:
            if re.search(pattern, command, re.IGNORECASE):
                risk = RiskLevel.CRITICAL
                warnings.append(f"Dangerous command detected: {command}")
                break
        
        return risk, warnings
    
    @classmethod
    def _is_recursive(cls, value: str) -> bool:
        """
        检查是否包含递归标志
        
        Args:
            value: 参数值
        
        Returns:
            bool: True 表示包含递归标志
        """
        value_lower = value.lower()
        for flag in cls.RECURSIVE_FLAGS:
            if flag.lower() in value_lower:
                return True
        
        return False

