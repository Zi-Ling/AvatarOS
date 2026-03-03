# app/avatar/runtime/recovery/repair/validator.py
"""
代码修复验证逻辑
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """验证结果"""
    success: bool
    error: Optional[str] = None
    level: Optional[str] = None  # "syntax", "static", "execution"


class RepairValidator:
    """代码修复验证器"""
    
    @staticmethod
    def validate_syntax(code: str) -> ValidationResult:
        """
        Level 1: 语法检查（compile）
        """
        try:
            compile(code, '<repair>', 'exec')
            logger.info("[Validator] ✅ Level 1: Syntax validation passed")
            return ValidationResult(success=True)
        except SyntaxError as e:
            return ValidationResult(
                success=False,
                error=f"Syntax error at line {e.lineno}: {e.msg}",
                level="syntax"
            )
    
    @staticmethod
    def validate_imports(code: str, original_error: str) -> ValidationResult:
        """
        Level 2: Import 静态检查
        
        只在原错误是 ImportError 或 ModuleNotFoundError 时检查
        """
        if "ModuleNotFoundError" not in original_error and "ImportError" not in original_error:
            # 不是 import 错误，跳过此检查
            return ValidationResult(success=True)
        
        missing_module = RepairValidator._extract_missing_module(original_error)
        
        if missing_module:
            # 检查修复后的代码是否添加了 import
            import_patterns = [
                f"import {missing_module}",
                f"from {missing_module}",
                f"from {missing_module.split('.')[0]}"  # 支持子模块
            ]
            
            has_import = any(pattern in code for pattern in import_patterns)
            
            if not has_import:
                return ValidationResult(
                    success=False,
                    error=f"Repair did not add missing import: {missing_module}",
                    level="static"
                )
            
            logger.info(f"[Validator] ✅ Level 2: Import check passed ({missing_module})")
        
        return ValidationResult(success=True)
    
    @staticmethod
    def validate(temp_code: str, original_error: str) -> ValidationResult:
        """
        综合验证（Level 1 + Level 2）
        """
        # Level 1: 语法检查
        syntax_result = RepairValidator.validate_syntax(temp_code)
        if not syntax_result.success:
            return syntax_result
        
        # Level 2: Import 检查
        import_result = RepairValidator.validate_imports(temp_code, original_error)
        if not import_result.success:
            return import_result
        
        # 所有检查通过
        return ValidationResult(success=True)
    
    @staticmethod
    def _extract_missing_module(error_msg: str) -> Optional[str]:
        """从错误消息中提取缺失的模块名"""
        # ModuleNotFoundError: No module named 'random'
        match = re.search(r"No module named ['\"]([^'\"]+)['\"]", error_msg)
        if match:
            return match.group(1)
        
        # ImportError: cannot import name 'xxx' from 'module'
        match = re.search(r"from ['\"]([^'\"]+)['\"]", error_msg)
        if match:
            return match.group(1)
        
        return None

