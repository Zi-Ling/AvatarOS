# app/avatar/actions/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class ActionResult:
    """Standardized response for actions."""

    success: bool
    message: str = ""
    data: Optional[Dict[str, Any]] = None

    def __bool__(self) -> bool:
        return self.success

class ActionError(Exception):
    """
    Base exception for any low-level action failure.
    """
    pass


@dataclass
class ActionContext:
    """
    Context object passed to actions.

    Keeping the structure lightweight lets future runtime code pass richer
    handles (for example filesystem access) without breaking the interface.
    """

    base_path: Optional[Path] = None

    def resolve_path(self, relative: str) -> Path:
        path = Path(relative)
        if path.is_absolute() or self.base_path is None:
            return path
        return self.base_path / path



class FileSystemActionContext:
    """
    Context for file-related actions.
    Future use:
      - sandbox root
      - permission checking
      - per-task working directory
    """
    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or ""


class WebActionContext:
    """
    Context for web/HTTP actions.
    Future use:
      - default headers
      - cookie/session management
      - proxy settings
    """
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or ""


class ShellActionContext:
    """
    Context for shell/command actions.
    Future:
      - environment variables
      - working directory
    """
    def __init__(self, cwd: Optional[str] = None):
        self.cwd = cwd or ""


class Action(ABC):
    """Base class for future action implementations."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def run(self, ctx: ActionContext, **kwargs: Any) -> ActionResult:
        raise NotImplementedError
