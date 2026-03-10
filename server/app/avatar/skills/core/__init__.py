# server/app/avatar/skills/core/__init__.py
"""
核心技能模块 - executor 型边界技能

1. python.run   - 计算沙箱
2. fs.*         - 文件系统边界（文本优先，20MB限制，路径白名单）
3. net.*        - 网络边界（安全双轨：net.get 文本直读 / net.download 落盘）
4. browser.run  - 浏览器执行器（Playwright，per-task context 隔离，artifact-first）
5. state.*      - 短期状态（task/session/user scope）
6. memory.*     - 长期记忆（向量库）
7. approval.*   - 人工审批（幂等协议）
"""

from .python import PythonRunSkill
from .fs import (
    FsReadSkill,
    FsWriteSkill,
    FsListSkill,
    FsDeleteSkill,
    FsMoveSkill,
    FsCopySkill,
)
from .net import NetGetSkill, NetPostSkill, NetDownloadSkill
from .browser import BrowserRunSkill
from .state import StateSetSkill, StateGetSkill, StateDeleteSkill
from .memory import MemoryStoreSkill, MemorySearchSkill, MemoryDeleteSkill
from .approval import ApprovalRequestSkill

__all__ = [
    # Python 沙箱
    "PythonRunSkill",
    # 文件系统
    "FsReadSkill",
    "FsWriteSkill",
    "FsListSkill",
    "FsDeleteSkill",
    "FsMoveSkill",
    "FsCopySkill",
    # 网络（安全双轨）
    "NetGetSkill",
    "NetPostSkill",
    "NetDownloadSkill",
    # 浏览器执行器
    "BrowserRunSkill",
    # 状态
    "StateSetSkill",
    "StateGetSkill",
    "StateDeleteSkill",
    # 记忆
    "MemoryStoreSkill",
    "MemorySearchSkill",
    "MemoryDeleteSkill",
    # 审批
    "ApprovalRequestSkill",
]
