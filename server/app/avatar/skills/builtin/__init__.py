# app/avatar/skills/builtin/__init__.py

"""
Builtin skills package.
Importing this package registers all builtin skills.

重构原则：技能是"可控边界"，不是"功能目录"
- 核心边界（core/）：python.run, fs.*, net.*, state.*, memory.*, approval.*
- 专用边界：computer（GUI 自动化）
- 降级机制：fallback
"""

# ============================================================================
# 核心技能（Core Skills - P0 + P1 + P2）
# ============================================================================
from ..core import python  # noqa: F401
from ..core import fs  # noqa: F401
from ..core import net  # noqa: F401
from ..core import state  # noqa: F401
from ..core import memory  # noqa: F401
from ..core import approval  # noqa: F401

# ============================================================================
# 专用边界（Specialized Boundaries）
# ============================================================================
from . import computer  # noqa: F401 (GUI Automation - 真正的边界)

# ============================================================================
# 降级机制（Fallback Mechanism）
# ============================================================================
from . import fallback  # noqa: F401

__all__ = [
    # Core Boundaries
    "python",
    "fs",
    "net",
    "state",
    "memory",
    "approval",
    # Specialized Boundaries
    "computer",
    # Fallback
    "fallback",
]
