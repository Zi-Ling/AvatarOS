# app/avatar/runtime/workspace/session_workspace.py
"""
SessionWorkspace — 受控 IO 边界

用户 workspace 只含用户可见目录：
  {workspace}/
    input/    — 输入文件
    output/   — 业务输出

系统目录统一在 ~/.avatar/ 下，不随 workspace 变化：
  ~/.avatar/sessions/{session_id}/   — session sandbox（本文件管理）
  ~/.avatar/artifacts/               — artifact 存储
  ~/.avatar/logs/                    — 运行日志
  ~/.avatar/.tmp/                    — 临时文件

设计原则：
- SessionWorkspace 只管 session sandbox 目录边界
- ArtifactCollector 扫描 sandbox 根目录，排除系统目录
- SandboxExecutor 通过 get_mount_config() 获取挂载配置
"""

import logging
import shutil
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass

from app.core.config import AVATAR_SESSIONS_DIR

logger = logging.getLogger(__name__)

# 容器内固定挂载点
CONTAINER_WORKSPACE_PATH = "/workspace"

# ---------------------------------------------------------------------------
# 目录常量（单一定义，所有地方引用这里）
# ---------------------------------------------------------------------------

# 用户可见目录（跟随用户 workspace）
USER_DIRS: List[str] = ["input", "output"]

# Session sandbox 内的系统目录（不收集 artifact，不暴露给用户）
# 注意：这里是 session sandbox 内的子目录，不是 ~/.avatar/ 下的系统目录
SYSTEM_DIRS: List[str] = []   # session sandbox 根目录下无系统子目录，全部是用户文件

# ArtifactCollector 扫描时排除的根目录名集合
# inputs/ 是框架注入的上游数据目录，不是用户产出，不应收集
SCAN_EXCLUDE_DIRS: frozenset = frozenset({"inputs"})


@dataclass
class MountConfig:
    """SandboxExecutor 挂载配置"""
    host_path: str
    container_path: str
    mode: str = "rw"


class SessionWorkspace:
    """
    单个 session 的 sandbox workspace。

    通过 SessionWorkspaceManager.get_or_create() 获取，不要直接实例化。
    根目录在 ~/.avatar/sessions/{session_id}/
    """

    def __init__(self, session_id: str, root: Path):
        self.session_id = session_id
        self.root = root
        self._ensure_dirs()

    def _ensure_dirs(self):
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # SandboxExecutor 挂载配置
    # ------------------------------------------------------------------

    def get_mount_config(self) -> MountConfig:
        return MountConfig(
            host_path=str(self.root.resolve()),
            container_path=CONTAINER_WORKSPACE_PATH,
            mode="rw",
        )

    def get_docker_volumes(self) -> Dict[str, Dict[str, str]]:
        cfg = self.get_mount_config()
        return {cfg.host_path: {"bind": cfg.container_path, "mode": cfg.mode}}

    # ------------------------------------------------------------------
    # Workspace 快照（供 ArtifactCollector 使用）
    # ------------------------------------------------------------------

    def snapshot_workspace(self) -> Dict[str, float]:
        """
        返回 session sandbox 根目录下所有文件的 {相对路径: mtime} 快照。
        排除 SCAN_EXCLUDE_DIRS 中的根目录（当前为空，所有文件均收集）。
        ArtifactCollector 用前后快照 diff 找到新增/修改文件。
        """
        snapshot: Dict[str, float] = {}
        if not self.root.exists():
            return snapshot
        for p in self.root.rglob("*"):
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(self.root)
            except ValueError:
                continue
            # 排除根目录系统目录（仅排第一级）
            if SCAN_EXCLUDE_DIRS and rel.parts and rel.parts[0] in SCAN_EXCLUDE_DIRS:
                continue
            snapshot[str(rel)] = p.stat().st_mtime
        return snapshot

    def changed_workspace_files(
        self,
        before: Dict[str, float],
    ) -> Dict[str, List[Path]]:
        """
        对比 before 快照，返回新增和修改的文件。

        Returns:
            {"new": [...], "modified": [...]}
        """
        after = self.snapshot_workspace()
        new_keys      = set(after.keys()) - set(before.keys())
        modified_keys = {
            k for k in after.keys() & before.keys()
            if after[k] != before[k]
        }
        return {
            "new":      [self.root / k for k in sorted(new_keys)],
            "modified": [self.root / k for k in sorted(modified_keys)],
        }

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    def cleanup_all(self):
        """删除整个 session sandbox（session 结束后调用）"""
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
            logger.info(f"[SessionWorkspace] Cleaned up {self.session_id}")

    def __repr__(self):
        return f"<SessionWorkspace session_id={self.session_id} root={self.root}>"


class SessionWorkspaceManager:
    """
    管理所有 session 的 sandbox workspace。
    根目录固定在 ~/.avatar/sessions/，不随用户 workspace 变化。
    """

    def __init__(self, base_path: Optional[Path] = None):
        self.base_path = Path(base_path) if base_path else AVATAR_SESSIONS_DIR
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, SessionWorkspace] = {}
        logger.info(f"[SessionWorkspaceManager] base_path={self.base_path}")

    def get_or_create(self, session_id: str) -> SessionWorkspace:
        if session_id not in self._sessions:
            root = self.base_path / session_id
            ws = SessionWorkspace(session_id=session_id, root=root)
            self._sessions[session_id] = ws
            logger.info(f"[SessionWorkspaceManager] Created workspace for {session_id}: {root}")
        return self._sessions[session_id]

    def get(self, session_id: str) -> Optional[SessionWorkspace]:
        return self._sessions.get(session_id)

    def cleanup(self, session_id: str, delete_files: bool = False):
        ws = self._sessions.pop(session_id, None)
        if ws and delete_files:
            ws.cleanup_all()

    def cleanup_all(self, delete_files: bool = False):
        for session_id in list(self._sessions.keys()):
            self.cleanup(session_id, delete_files=delete_files)


# 全局单例
_manager: Optional[SessionWorkspaceManager] = None


def init_session_workspace_manager(base_path: Optional[Path] = None) -> SessionWorkspaceManager:
    global _manager
    _manager = SessionWorkspaceManager(base_path=base_path)
    return _manager


def get_session_workspace_manager() -> SessionWorkspaceManager:
    global _manager
    if _manager is None:
        _manager = SessionWorkspaceManager()
    return _manager
