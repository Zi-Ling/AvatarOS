# app/avatar/errors.py
"""
错误分类和友好提示系统

定义所有可能的错误类型，并为每种错误提供：
1. 用户友好的错误消息
2. 具体的建议
3. 是否可以重试
4. 错误级别（严重/警告/提示）
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass


class ErrorType(Enum):
    """错误类型枚举"""
    # 文件相关错误
    FILE_NOT_FOUND = "file_not_found"
    FILE_PERMISSION_DENIED = "file_permission_denied"
    FILE_ALREADY_EXISTS = "file_already_exists"
    
    # 语法错误
    SYNTAX_ERROR = "syntax_error"
    INDENTATION_ERROR = "indentation_error"
    
    # 运行时错误
    RUNTIME_ERROR = "runtime_error"
    IMPORT_ERROR = "import_error"
    TYPE_ERROR = "type_error"
    VALUE_ERROR = "value_error"
    
    # LLM 相关错误
    LLM_OUTPUT_FORMAT_ERROR = "llm_output_format_error"
    LLM_TIMEOUT = "llm_timeout"
    LLM_CONNECTION_ERROR = "llm_connection_error"
    TASK_DECOMPOSITION_FAILED = "task_decomposition_failed"
    
    # 网络错误
    NETWORK_ERROR = "network_error"
    TIMEOUT_ERROR = "timeout_error"
    
    # 技能相关错误
    SKILL_NOT_FOUND = "skill_not_found"
    SKILL_EXECUTION_ERROR = "skill_execution_error"
    
    # 其他
    UNKNOWN_ERROR = "unknown_error"


class ErrorSeverity(Enum):
    """错误严重程度"""
    CRITICAL = "critical"  # 🔴 严重错误（无法继续）
    ERROR = "error"        # 🟠 错误（可能可以修复）
    WARNING = "warning"    # 🟡 警告（不影响主流程）
    INFO = "info"          # 🔵 提示（仅供参考）


@dataclass
class ErrorInfo:
    """错误信息"""
    error_type: ErrorType
    severity: ErrorSeverity
    user_message: str
    suggestions: List[str]
    retry_possible: bool
    technical_details: Optional[str] = None


class ErrorClassifier:
    """
    错误分类器
    
    根据异常类型和错误消息，自动分类错误并生成友好提示
    """
    
    # 错误模式匹配规则
    ERROR_PATTERNS = {
        # 文件错误
        "No such file or directory": ErrorType.FILE_NOT_FOUND,
        "FileNotFoundError": ErrorType.FILE_NOT_FOUND,
        "Permission denied": ErrorType.FILE_PERMISSION_DENIED,
        "PermissionError": ErrorType.FILE_PERMISSION_DENIED,
        "File exists": ErrorType.FILE_ALREADY_EXISTS,
        "FileExistsError": ErrorType.FILE_ALREADY_EXISTS,
        
        # 语法错误
        "SyntaxError": ErrorType.SYNTAX_ERROR,
        "IndentationError": ErrorType.INDENTATION_ERROR,
        "TabError": ErrorType.INDENTATION_ERROR,
        
        # 运行时错误
        "ModuleNotFoundError": ErrorType.IMPORT_ERROR,
        "ImportError": ErrorType.IMPORT_ERROR,
        "TypeError": ErrorType.TYPE_ERROR,
        "ValueError": ErrorType.VALUE_ERROR,
        
        # LLM 错误
        "JSON": ErrorType.LLM_OUTPUT_FORMAT_ERROR,
        "parse": ErrorType.LLM_OUTPUT_FORMAT_ERROR,
        "timeout": ErrorType.TIMEOUT_ERROR,
        "timed out": ErrorType.TIMEOUT_ERROR,
        
        # 网络错误
        "Connection": ErrorType.NETWORK_ERROR,
        "Network": ErrorType.NETWORK_ERROR,
    }
    
    # 错误类型对应的友好提示
    ERROR_MESSAGES = {
        ErrorType.FILE_NOT_FOUND: {
            "message": "找不到指定的文件",
            "suggestions": [
                "请检查文件路径是否正确",
                "确认文件名的大小写是否匹配",
                "如果文件不存在，请先创建该文件"
            ],
            "severity": ErrorSeverity.ERROR,
            "retry_possible": True,
        },
        ErrorType.FILE_PERMISSION_DENIED: {
            "message": "没有权限访问该文件",
            "suggestions": [
                "请检查文件权限设置",
                "尝试以管理员身份运行",
                "确认文件没有被其他程序占用"
            ],
            "severity": ErrorSeverity.CRITICAL,
            "retry_possible": False,
        },
        ErrorType.FILE_ALREADY_EXISTS: {
            "message": "文件已存在",
            "suggestions": [
                "如果要覆盖，请先删除原文件",
                "或者使用不同的文件名"
            ],
            "severity": ErrorSeverity.WARNING,
            "retry_possible": True,
        },
        ErrorType.SYNTAX_ERROR: {
            "message": "代码语法错误",
            "suggestions": [
                "请检查代码的语法是否正确",
                "确认括号、引号是否匹配",
                "尝试重新表述你的需求"
            ],
            "severity": ErrorSeverity.ERROR,
            "retry_possible": True,
        },
        ErrorType.INDENTATION_ERROR: {
            "message": "代码缩进错误",
            "suggestions": [
                "Python 对缩进非常敏感",
                "请确保使用一致的缩进（空格或 Tab）",
                "尝试让 AI 重新生成代码"
            ],
            "severity": ErrorSeverity.ERROR,
            "retry_possible": True,
        },
        ErrorType.IMPORT_ERROR: {
            "message": "缺少必需的 Python 模块",
            "suggestions": [
                "请先安装缺少的模块",
                "或者使用其他方法实现相同功能"
            ],
            "severity": ErrorSeverity.ERROR,
            "retry_possible": False,
        },
        ErrorType.TYPE_ERROR: {
            "message": "数据类型不匹配",
            "suggestions": [
                "请检查输入数据的类型",
                "尝试重新表述你的需求"
            ],
            "severity": ErrorSeverity.ERROR,
            "retry_possible": True,
        },
        ErrorType.VALUE_ERROR: {
            "message": "数据值不正确",
            "suggestions": [
                "请检查输入数据的值",
                "确认数据格式是否符合要求"
            ],
            "severity": ErrorSeverity.ERROR,
            "retry_possible": True,
        },
        ErrorType.LLM_OUTPUT_FORMAT_ERROR: {
            "message": "AI 理解了你的需求，但生成的计划格式有误",
            "suggestions": [
                "请尝试重新表述你的需求",
                "或者将任务分解成更简单的步骤",
                "如果问题持续，请切换到更强大的 LLM 模型"
            ],
            "severity": ErrorSeverity.ERROR,
            "retry_possible": True,
        },
        ErrorType.LLM_TIMEOUT: {
            "message": "AI 响应超时",
            "suggestions": [
                "请检查网络连接",
                "尝试简化你的需求",
                "稍后再试"
            ],
            "severity": ErrorSeverity.ERROR,
            "retry_possible": True,
        },
        ErrorType.TASK_DECOMPOSITION_FAILED: {
            "message": "任务分解失败",
            "suggestions": [
                "您的任务描述较为复杂，建议分步骤分别提问",
                "例如：先让我'生成文件内容'，再让我'保存到文件'",
                "或者简化任务描述，去除不必要的细节",
                "如果急需处理，可以稍后重试"
            ],
            "severity": ErrorSeverity.ERROR,
            "retry_possible": True,
        },
        ErrorType.NETWORK_ERROR: {
            "message": "网络连接失败",
            "suggestions": [
                "请检查网络连接",
                "确认服务器是否正常运行",
                "稍后再试"
            ],
            "severity": ErrorSeverity.CRITICAL,
            "retry_possible": True,
        },
        ErrorType.SKILL_NOT_FOUND: {
            "message": "找不到执行该任务所需的技能",
            "suggestions": [
                "该功能可能尚未实现",
                "尝试用其他方式描述你的需求"
            ],
            "severity": ErrorSeverity.ERROR,
            "retry_possible": True,
        },
        ErrorType.UNKNOWN_ERROR: {
            "message": "发生了未知错误",
            "suggestions": [
                "请尝试重新执行",
                "如果问题持续，请联系技术支持"
            ],
            "severity": ErrorSeverity.ERROR,
            "retry_possible": True,
        },
    }
    
    @classmethod
    def classify(cls, error_message: str, exception_type: Optional[str] = None) -> ErrorInfo:
        """
        分类错误并生成友好提示
        
        Args:
            error_message: 错误消息
            exception_type: 异常类型（可选）
        
        Returns:
            ErrorInfo 对象
        """
        # 首先尝试根据异常类型匹配
        if exception_type:
            for pattern, error_type in cls.ERROR_PATTERNS.items():
                if pattern in exception_type:
                    return cls._build_error_info(error_type, error_message)
        
        # 然后尝试根据错误消息匹配
        for pattern, error_type in cls.ERROR_PATTERNS.items():
            if pattern.lower() in error_message.lower():
                return cls._build_error_info(error_type, error_message)
        
        # 如果都不匹配，返回未知错误
        return cls._build_error_info(ErrorType.UNKNOWN_ERROR, error_message)
    
    @classmethod
    def _build_error_info(cls, error_type: ErrorType, technical_details: str) -> ErrorInfo:
        """构建 ErrorInfo 对象"""
        template = cls.ERROR_MESSAGES.get(error_type, cls.ERROR_MESSAGES[ErrorType.UNKNOWN_ERROR])
        
        return ErrorInfo(
            error_type=error_type,
            severity=template["severity"],
            user_message=template["message"],
            suggestions=template["suggestions"],
            retry_possible=template["retry_possible"],
            technical_details=technical_details[:500],  # 限制长度
        )
    
    @classmethod
    def format_for_frontend(cls, error_info: ErrorInfo) -> Dict:
        """
        格式化为前端可用的 JSON
        
        Returns:
            {
                "error_type": "file_not_found",
                "severity": "error",
                "message": "找不到指定的文件",
                "suggestions": ["...", "..."],
                "retry_possible": true,
                "technical_details": "..."
            }
        """
        return {
            "error_type": error_info.error_type.value,
            "severity": error_info.severity.value,
            "message": error_info.user_message,
            "suggestions": error_info.suggestions,
            "retry_possible": error_info.retry_possible,
            "technical_details": error_info.technical_details,
        }

