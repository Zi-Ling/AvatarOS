"""
path_canonical.py — 统一路径规范化层

系统中存在多种路径表示：
  - container path:  /workspace/merged_sales.xlsx
  - session path:    C:\\Users\\ZiLing\\.avatar\\sessions\\abc\\output\\file.txt
  - host workspace:  D:\\Temp\\IA\\merged_sales.xlsx

所有消费路径的模块（Verifier、TargetResolver、ReferenceResolver、
build_task_result_summary、GoalCoverageTracker）都必须通过本模块
做规范化，而不是各自硬编码翻译逻辑。

设计原则：
  - 单一入口：canonicalize_path()
  - 幂等：已经是宿主路径的不会被二次翻译
  - 安全：缺少映射信息时原样返回，不抛异常
"""

from __future__ import annotations

import logging
import os
from pathlib import PurePosixPath
from typing import Optional

logger = logging.getLogger(__name__)

# Container mount points (must stay in sync with session_workspace.py)
CONTAINER_WORKSPACE = "/workspace"
CONTAINER_SESSION = "/session"


def canonicalize_path(
    path: str,
    host_workspace: Optional[str] = None,
    session_root: Optional[str] = None,
) -> str:
    """
    把任意路径表示规范化为宿主机可访问的绝对路径。

    翻译规则（按优先级）：
      1. /session/...  → {session_root}/...
      2. /workspace/... → {host_workspace}/...
      3. 已经是宿主机绝对路径 → 原样返回
      4. 相对路径 → 原样返回（调用方自行解析）

    Args:
        path: 待规范化的路径（可能是容器路径、宿主路径、相对路径）
        host_workspace: 用户工作目录的宿主机路径（如 D:\\Temp\\IA）
        session_root: session workspace 的宿主机路径

    Returns:
        规范化后的宿主机路径字符串
    """
    if not path:
        return path

    # Normalize forward slashes for comparison
    normalized = path.replace("\\", "/")

    # Rule 1: /session/... → session_root
    if session_root and normalized.startswith(CONTAINER_SESSION + "/"):
        rel = normalized[len(CONTAINER_SESSION) + 1:]
        result = os.path.join(session_root, rel)
        logger.debug(f"[PathCanonical] {path} → {result} (session mount)")
        return result
    if session_root and normalized == CONTAINER_SESSION:
        return session_root

    # Rule 2: /workspace/... → host_workspace
    if host_workspace and normalized.startswith(CONTAINER_WORKSPACE + "/"):
        rel = normalized[len(CONTAINER_WORKSPACE) + 1:]
        result = os.path.join(host_workspace, rel)
        logger.debug(f"[PathCanonical] {path} → {result} (workspace mount)")
        return result
    if host_workspace and normalized == CONTAINER_WORKSPACE:
        return host_workspace

    # Rule 3/4: already host path or relative — return as-is
    return path


def canonicalize_paths_in_dict(
    d: dict,
    path_keys: tuple = ("path", "file_path", "output_path"),
    host_workspace: Optional[str] = None,
    session_root: Optional[str] = None,
) -> dict:
    """
    对 dict 中指定的 key 做路径规范化（浅层，不递归）。
    返回新 dict，不修改原始对象。
    """
    result = dict(d)
    for key in path_keys:
        val = result.get(key)
        if isinstance(val, str) and val:
            result[key] = canonicalize_path(val, host_workspace, session_root)
    return result


def is_container_path(path: str) -> bool:
    """判断路径是否是容器内路径。"""
    if not path:
        return False
    normalized = path.replace("\\", "/")
    return (
        normalized.startswith(CONTAINER_WORKSPACE + "/")
        or normalized == CONTAINER_WORKSPACE
        or normalized.startswith(CONTAINER_SESSION + "/")
        or normalized == CONTAINER_SESSION
    )
