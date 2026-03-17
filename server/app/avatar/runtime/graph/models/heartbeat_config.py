# app/avatar/runtime/graph/models/heartbeat_config.py
"""
按 Capability 类型的心跳配置。

匹配优先级：精确匹配 → 前缀/通配符匹配 → default 兜底。
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# 默认心跳配置，可通过 runtime_config 覆盖
# ---------------------------------------------------------------------------
HEARTBEAT_CONFIG: dict[str, dict] = {
    "python.run":  {"interval_s": 30, "stale_threshold_s": 120},
    "browser.run": {"interval_s": 60, "stale_threshold_s": 300},
    "build.*":     {"interval_s": 60, "stale_threshold_s": 600},
    "net.*":       {"interval_s": 30, "stale_threshold_s": 180},
    "default":     {"interval_s": 30, "stale_threshold_s": 120},
}


def get_heartbeat_config(capability_name: str) -> dict:
    """
    查找 capability 对应的心跳配置。

    匹配优先级（规则明确不可歧义）：
    1. 精确匹配 — capability_name 完全等于某个 key
    2. 前缀/通配符匹配 — key 以 ``.*`` 结尾，capability_name 以 key 前缀开头
    3. default 兜底
    """
    # 1) 精确匹配
    if capability_name in HEARTBEAT_CONFIG and not capability_name.endswith(".*"):
        return HEARTBEAT_CONFIG[capability_name]

    # 2) 前缀/通配符匹配（选最长前缀）
    best_match: str | None = None
    best_prefix_len = 0
    for key in HEARTBEAT_CONFIG:
        if key == "default" or not key.endswith(".*"):
            continue
        prefix = key[:-2]  # 去掉 ".*"
        if capability_name.startswith(prefix) and len(prefix) > best_prefix_len:
            best_match = key
            best_prefix_len = len(prefix)

    if best_match is not None:
        return HEARTBEAT_CONFIG[best_match]

    # 3) default 兜底
    return HEARTBEAT_CONFIG["default"]
