# app/avatar/runtime/graph/models/state_machines.py
"""
TaskSession 和 StepNode 的合法状态转换表及副作用钩子机制。

转换副作用钩子模式：
    某些 transition 发生时自动触发 updated_at 更新、事件流发射、审计记录，
    避免业务代码到处手写字符串切换。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# TaskSession 合法状态转换表
# ---------------------------------------------------------------------------
VALID_TASK_SESSION_TRANSITIONS: dict[str, set[str]] = {
    "created":          {"planning"},
    "planning":         {"executing"},
    "executing":        {"paused", "interrupted", "waiting_input", "waiting_approval",
                         "completed", "failed", "cancelled"},
    "paused":           {"resuming"},
    "interrupted":      {"resuming"},
    "waiting_input":    {"executing"},
    "waiting_approval": {"executing"},
    "resuming":         {"executing", "failed"},
    # 终态无出边
    "completed":        set(),
    "failed":           set(),
    "cancelled":        set(),
}

# ---------------------------------------------------------------------------
# StepNode 合法状态转换表（11 态）
# ---------------------------------------------------------------------------
VALID_STEP_NODE_TRANSITIONS: dict[str, set[str]] = {
    "pending":          {"ready", "blocked", "cancelled"},
    "ready":            {"running", "cancelled"},
    "running":          {"success", "failed", "stale", "waiting", "cancelled"},
    "success":          {"stale"},
    "failed":           {"retry_scheduled"},
    "retry_scheduled":  {"running", "failed"},
    "stale":            {"ready", "pending"},
    "waiting":          {"running", "cancelled"},
    "blocked":          {"ready", "cancelled"},
    # 终态
    "skipped":          set(),
    "cancelled":        set(),
}


# ---------------------------------------------------------------------------
# 转换校验
# ---------------------------------------------------------------------------
class InvalidTransitionError(Exception):
    """非法状态转换异常。"""

    def __init__(self, entity_type: str, current: str, target: str):
        self.entity_type = entity_type
        self.current = current
        self.target = target
        super().__init__(f"{entity_type}: 非法转换 {current!r} → {target!r}")


def validate_transition(
    current: str,
    target: str,
    transitions_table: dict[str, set[str]],
) -> bool:
    """
    校验 (current → target) 是否在合法转换表中。

    Returns:
        True 如果合法，False 如果非法。
    """
    allowed = transitions_table.get(current)
    if allowed is None:
        return False
    return target in allowed


# ---------------------------------------------------------------------------
# 转换副作用钩子注册表
# ---------------------------------------------------------------------------
# 钩子签名: (entity_id: str, old_status: str, new_status: str) -> None
TransitionHookFn = Callable[[str, str, str], None]

# 全局钩子注册表：key = (entity_type, old_status, new_status) 或 (entity_type, "*", "*") 通配
_transition_hooks: dict[tuple[str, str, str], list[TransitionHookFn]] = {}


def register_transition_hook(
    entity_type: str,
    from_status: str = "*",
    to_status: str = "*",
    hook: Optional[TransitionHookFn] = None,
) -> Callable:
    """
    注册转换副作用钩子。

    支持精确匹配和通配符 ``*``：
    - ("task_session", "*", "*") — 所有 TaskSession 转换都触发
    - ("task_session", "executing", "paused") — 仅 executing→paused 触发
    - ("step_node", "*", "stale") — 任何状态转到 stale 时触发

    可作为装饰器使用::

        @register_transition_hook("task_session")
        def on_any_transition(entity_id, old, new):
            ...
    """
    def decorator(fn: TransitionHookFn) -> TransitionHookFn:
        key = (entity_type, from_status, to_status)
        _transition_hooks.setdefault(key, []).append(fn)
        return fn

    if hook is not None:
        decorator(hook)
        return hook
    return decorator


def fire_transition_hooks(
    entity_type: str,
    entity_id: str,
    old_status: str,
    new_status: str,
) -> None:
    """
    触发所有匹配的转换副作用钩子。

    匹配规则（按优先级全部触发，不短路）：
    1. 精确匹配 (entity_type, old_status, new_status)
    2. 半通配   (entity_type, old_status, "*")
    3. 半通配   (entity_type, "*", new_status)
    4. 全通配   (entity_type, "*", "*")
    """
    patterns = [
        (entity_type, old_status, new_status),
        (entity_type, old_status, "*"),
        (entity_type, "*", new_status),
        (entity_type, "*", "*"),
    ]
    seen: set[int] = set()
    for pattern in patterns:
        for fn in _transition_hooks.get(pattern, []):
            fn_id = id(fn)
            if fn_id not in seen:
                seen.add(fn_id)
                fn(entity_id, old_status, new_status)


def clear_transition_hooks() -> None:
    """清空所有已注册的钩子（主要用于测试）。"""
    _transition_hooks.clear()
