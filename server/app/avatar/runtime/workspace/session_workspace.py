# app/avatar/runtime/workspace/session_workspace.py
"""
SessionWorkspace -- Controlled IO boundary

Five-directory structure (architecture doc section 8):
  ~/.avatar/sessions/{session_id}/
    input/      -- Runtime-injected input files (not collected as artifacts)
    output/     -- Container write target (ArtifactCollector scans only this dir)
    artifacts/  -- Promoted structured artifact cache
    logs/       -- stdout / stderr / event logs (not collected as artifacts)
    tmp/        -- Runtime temp files (not collected as artifacts)

Container mount point: /workspace
Container may only write to /workspace/output/*

Design principles:
- SessionWorkspace manages only the session sandbox directory boundary
- ArtifactCollector scans only output/, excludes input/artifacts/logs/tmp
- SandboxExecutor gets mount config via get_mount_config()
- stdout/stderr written to logs/ by Runtime, not mixed with artifacts
"""

import logging
import shutil
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass

from app.core.config import AVATAR_SESSIONS_DIR

logger = logging.getLogger(__name__)

# Container fixed mount point
CONTAINER_WORKSPACE_PATH = "/workspace"

# ---------------------------------------------------------------------------
# Directory constants
# ---------------------------------------------------------------------------

USER_DIRS: List[str] = ["input", "output"]
SYSTEM_DIRS: List[str] = ["artifacts", "logs", "tmp"]
SCAN_EXCLUDE_DIRS: frozenset = frozenset({"input", "artifacts", "logs", "tmp", "inputs"})


@dataclass
class MountConfig:
    """SandboxExecutor mount configuration"""
    host_path: str
    container_path: str
    mode: str = "rw"


class SessionWorkspace:
    """
    Sandbox workspace for a single session.

    Obtain via SessionWorkspaceManager.get_or_create(), do not instantiate directly.
    Root directory: ~/.avatar/sessions/{session_id}/
    """

    def __init__(self, session_id: str, root: Path):
        self.session_id = session_id
        self.root = root
        self._ensure_dirs()

    def _ensure_dirs(self):
        self.root.mkdir(parents=True, exist_ok=True)
        for d in USER_DIRS + SYSTEM_DIRS:
            (self.root / d).mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Subdirectory accessors
    # ------------------------------------------------------------------

    @property
    def input_dir(self) -> Path:
        """Runtime-injected input files directory"""
        return self.root / "input"

    @property
    def output_dir(self) -> Path:
        """Result directory (ArtifactCollector scans this directory)"""
        return self.root / "output"

    @property
    def artifacts_dir(self) -> Path:
        """Promoted structured artifact cache directory"""
        return self.root / "artifacts"

    @property
    def logs_dir(self) -> Path:
        """stdout / stderr / event log directory"""
        return self.root / "logs"

    @property
    def tmp_dir(self) -> Path:
        """Runtime temp files directory"""
        return self.root / "tmp"

    # ------------------------------------------------------------------
    # SandboxExecutor mount configuration
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
    # stdout / stderr writing (separated into logs/)
    # ------------------------------------------------------------------

    def write_stdout(self, node_id: str, content: bytes) -> Path:
        """Write stdout to logs/{node_id}_stdout.txt, return path"""
        path = self.logs_dir / f"{node_id}_stdout.txt"
        path.write_bytes(content)
        return path

    def write_stderr(self, node_id: str, content: bytes) -> Path:
        """Write stderr to logs/{node_id}_stderr.txt, return path"""
        path = self.logs_dir / f"{node_id}_stderr.txt"
        path.write_bytes(content)
        return path

    # ------------------------------------------------------------------
    # Workspace snapshot (for ArtifactCollector)
    # Scans only output/, other directories are not user output
    # ------------------------------------------------------------------

    def snapshot_workspace(self) -> Dict[str, float]:
        """
        Return {relative_path: mtime} snapshot of all files under workspace root.
        ArtifactCollector uses before/after snapshot diff to find new/modified files.
        Scans entire root but skips system dirs (logs/, tmp/, artifacts/).
        """
        snapshot: Dict[str, float] = {}
        skip_dirs = {"logs", "tmp", "artifacts"}
        if not self.root.exists():
            return snapshot
        for p in self.root.rglob("*"):
            if not p.is_file():
                continue
            # Skip system directories
            try:
                rel = p.relative_to(self.root)
            except ValueError:
                continue
            if rel.parts and rel.parts[0] in skip_dirs:
                continue
            snapshot[str(rel)] = p.stat().st_mtime
        return snapshot

    def changed_workspace_files(
        self,
        before: Dict[str, float],
    ) -> Dict[str, List[Path]]:
        """
        Compare against before snapshot, return new and modified files.
        Scans entire workspace root (excluding system dirs).

        Returns:
            {"new": [...], "modified": [...]}
        """
        after = self.snapshot_workspace()
        new_keys = set(after.keys()) - set(before.keys())
        modified_keys = {
            k for k in after.keys() & before.keys()
            if after[k] != before[k]
        }
        return {
            "new": [self.root / k for k in sorted(new_keys)],
            "modified": [self.root / k for k in sorted(modified_keys)],
        }

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_all(self):
        """Delete entire session sandbox (call when session ends)"""
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
            logger.info(f"[SessionWorkspace] Cleaned up {self.session_id}")

    def __repr__(self):
        return f"<SessionWorkspace session_id={self.session_id} root={self.root}>"


# ---------------------------------------------------------------------------
# Global singleton manager
# ---------------------------------------------------------------------------

_manager: Optional["SessionWorkspaceManager"] = None


class SessionWorkspaceManager:
    """
    Manages sandbox workspaces for all sessions.
    Root directory fixed at ~/.avatar/sessions/, independent of user workspace.
    """

    def __init__(self, base_path: Optional[Path] = None):
        self.base_path = Path(base_path) if base_path else AVATAR_SESSIONS_DIR
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, SessionWorkspace] = {}
        logger.info(f"[SessionWorkspaceManager] base_path={self.base_path}")

    def get_or_create(self, session_id: str) -> "SessionWorkspace":
        # 清理 Windows 不允许的路径字符（冒号、斜杠等）
        safe_id = session_id.replace(":", "-").replace("/", "-").replace("\\", "-")
        if safe_id not in self._sessions:
            root = self.base_path / safe_id
            ws = SessionWorkspace(session_id=safe_id, root=root)
            self._sessions[safe_id] = ws
            logger.info(f"[SessionWorkspaceManager] Created workspace for {safe_id}: {root}")
        return self._sessions[safe_id]

    def get(self, session_id: str) -> Optional["SessionWorkspace"]:
        safe_id = session_id.replace(":", "-").replace("/", "-").replace("\\", "-")
        return self._sessions.get(safe_id)

    def cleanup(self, session_id: str, delete_files: bool = False):
        ws = self._sessions.pop(session_id, None)
        if ws and delete_files:
            ws.cleanup_all()

    def cleanup_all(self, delete_files: bool = False):
        for session_id in list(self._sessions.keys()):
            self.cleanup(session_id, delete_files=delete_files)


def init_session_workspace_manager(base_path: Optional[Path] = None) -> SessionWorkspaceManager:
    global _manager
    _manager = SessionWorkspaceManager(base_path=base_path)
    return _manager


def get_session_workspace_manager() -> SessionWorkspaceManager:
    global _manager
    if _manager is None:
        _manager = SessionWorkspaceManager()
    return _manager
