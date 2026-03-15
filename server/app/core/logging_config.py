# app/logging_config.py
"""
日志配置

功能：
1. 结构化日志（JSON 格式）
2. 日志分级（DEBUG, INFO, WARNING, ERROR, CRITICAL）
3. 日志轮转（按大小或时间）
4. 日志聚合（统一输出到文件/控制台）
5. 请求追踪（Request ID）
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import json
from pathlib import Path
from typing import Optional
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """
    JSON 格式化器
    
    输出格式：
    {
        "timestamp": "2025-12-01T18:00:00.000Z",
        "level": "INFO",
        "logger": "app.avatar.runtime.loop",
        "message": "Task completed",
        "request_id": "abc123",
        "extra": {...}
    }
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # 添加额外字段
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        
        if hasattr(record, "task_id"):
            log_data["task_id"] = record.task_id
        
        # 添加异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # 添加其他自定义字段
        extra = {}
        for key, value in record.__dict__.items():
            if key not in [
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "pathname", "process", "processName",
                "relativeCreated", "thread", "threadName", "exc_info",
                "exc_text", "stack_info", "request_id", "user_id", "task_id"
            ]:
                extra[key] = value
        
        if extra:
            log_data["extra"] = extra
        
        return json.dumps(log_data, ensure_ascii=False)


class ColoredFormatter(logging.Formatter):
    """
    彩色控制台格式化器
    """
    
    COLORS = {
        "DEBUG": "\033[36m",      # Cyan
        "INFO": "\033[32m",       # Green
        "WARNING": "\033[33m",    # Yellow
        "ERROR": "\033[31m",      # Red
        "CRITICAL": "\033[35m",   # Magenta
    }
    RESET = "\033[0m"
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging(
    log_dir: Optional[Path] = None,
    log_level: str = "INFO",
    enable_json: bool = False,
    enable_console: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
) -> None:
    """
    配置日志系统
    
    Args:
        log_dir: 日志目录（None 表示不输出到文件）
        log_level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
        enable_json: 是否启用 JSON 格式（文件日志）
        enable_console: 是否输出到控制台
        max_bytes: 单个日志文件最大大小
        backup_count: 日志文件备份数量
    """
    # 获取根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # 清除现有 handlers
    root_logger.handlers.clear()
    
    # 控制台 Handler
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        
        if enable_json:
            console_handler.setFormatter(JSONFormatter())
        else:
            console_formatter = ColoredFormatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            console_handler.setFormatter(console_formatter)
        
        root_logger.addHandler(console_handler)
    
    # 文件 Handler
    if log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # 主日志文件（所有级别）
        main_log_file = log_dir / "app.log"
        main_handler = logging.handlers.RotatingFileHandler(
            main_log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8"
        )
        main_handler.setLevel(logging.DEBUG)
        
        if enable_json:
            main_handler.setFormatter(JSONFormatter())
        else:
            main_formatter = logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            main_handler.setFormatter(main_formatter)
        
        root_logger.addHandler(main_handler)
        
        # 错误日志文件（ERROR 及以上）
        error_log_file = log_dir / "error.log"
        error_handler = logging.handlers.RotatingFileHandler(
            error_log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8"
        )
        error_handler.setLevel(logging.ERROR)
        
        if enable_json:
            error_handler.setFormatter(JSONFormatter())
        else:
            error_formatter = logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s\n%(pathname)s:%(lineno)d\n",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            error_handler.setFormatter(error_formatter)
        
        root_logger.addHandler(error_handler)
    
    # 设置第三方库日志级别（减少噪音）
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    
    logging.info(f"Logging configured: level={log_level}, json={enable_json}, console={enable_console}, log_dir={log_dir}")


class RequestIDFilter(logging.Filter):
    """
    请求 ID 过滤器
    
    从上下文中提取 request_id 并添加到日志记录
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        # 尝试从 contextvars 获取 request_id
        try:
            from contextvars import ContextVar
            request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
            request_id = request_id_var.get()
            if request_id:
                record.request_id = request_id
        except Exception:
            pass
        
        return True


def get_logger(name: str) -> logging.Logger:
    """
    获取 logger
    
    Args:
        name: logger 名称（通常是模块名）
    
    Returns:
        logger 实例
    """
    logger = logging.getLogger(name)
    logger.addFilter(RequestIDFilter())
    return logger

