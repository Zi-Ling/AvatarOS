"""Structured JSON logging for multi-agent runtime.

Provides:
- StructuredLogger: wraps stdlib logger with JSON-formatted extra fields
- trace_context: context var for propagating trace_id across async calls
- log_event(): convenience function for structured event logging

All multi-agent modules should use get_structured_logger() instead of
logging.getLogger() for consistent structured output.
"""
from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# Context variable for trace_id propagation across async boundaries
trace_context: ContextVar[Dict[str, str]] = ContextVar("trace_context", default={})


@dataclass(frozen=True)
class StructuredLogConfig:
    """Configuration for structured logging."""
    # Include these fields in every log entry
    default_fields: tuple = ("trace_id", "session_id", "task_id", "node_id")
    # Max chars for string values in extra fields
    max_value_chars: int = 500
    # Enable JSON formatting (False = human-readable for dev)
    json_format: bool = True


def set_trace_context(**kwargs: str) -> None:
    """Set trace context fields (trace_id, session_id, etc.) for the current async task."""
    ctx = trace_context.get().copy()
    ctx.update(kwargs)
    trace_context.set(ctx)


def get_trace_context() -> Dict[str, str]:
    """Get current trace context."""
    return trace_context.get()


class StructuredLogger:
    """Logger wrapper that emits structured JSON log entries.

    Usage:
        log = get_structured_logger("multiagent.supervisor")
        log.info("dispatch_started", node_id="t_0", role="researcher")
        log.error("dispatch_failed", node_id="t_0", error="timeout")
    """

    def __init__(
        self,
        name: str,
        config: Optional[StructuredLogConfig] = None,
    ) -> None:
        self._logger = logging.getLogger(name)
        self._cfg = config or StructuredLogConfig()
        self._component = name.split(".")[-1] if "." in name else name

    def _build_entry(
        self,
        event: str,
        level: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Build a structured log entry dict."""
        ctx = get_trace_context()
        entry: Dict[str, Any] = {
            "ts": time.time(),
            "level": level,
            "component": self._component,
            "event": event,
        }
        # Inject trace context fields
        for field_name in self._cfg.default_fields:
            val = kwargs.pop(field_name, None) or ctx.get(field_name, "")
            if val:
                entry[field_name] = val

        # Add remaining kwargs as extra fields
        for k, v in kwargs.items():
            sv = str(v)
            if len(sv) > self._cfg.max_value_chars:
                sv = sv[:self._cfg.max_value_chars] + "…"
            entry[k] = sv if not isinstance(v, (int, float, bool)) else v

        return entry

    def _emit(self, level_fn, event: str, **kwargs: Any) -> None:
        level_name = level_fn.__name__.upper()
        entry = self._build_entry(event, level_name, **kwargs)
        if self._cfg.json_format:
            level_fn("[%s] %s", self._component, json.dumps(entry, ensure_ascii=False))
        else:
            # Human-readable format for development
            extras = " ".join(f"{k}={v}" for k, v in entry.items() if k not in ("ts", "level", "component", "event"))
            level_fn("[%s] %s %s", self._component, event, extras)

    def info(self, event: str, **kwargs: Any) -> None:
        self._emit(self._logger.info, event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._emit(self._logger.warning, event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._emit(self._logger.error, event, **kwargs)

    def debug(self, event: str, **kwargs: Any) -> None:
        self._emit(self._logger.debug, event, **kwargs)


# Module-level cache for structured loggers
_loggers: Dict[str, StructuredLogger] = {}


def get_structured_logger(
    name: str,
    config: Optional[StructuredLogConfig] = None,
) -> StructuredLogger:
    """Get or create a StructuredLogger for the given module name."""
    if name not in _loggers:
        _loggers[name] = StructuredLogger(name, config)
    return _loggers[name]
