# avatar/actions/file/local.py
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..base import ActionResult, FileSystemActionContext


def read_text_file(path: str, *, ctx: Optional[FileSystemActionContext] = None) -> ActionResult:
    try:
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        return ActionResult(success=True, output=text)
    except Exception as e:  # noqa: BLE001
        return ActionResult(success=False, error=str(e))


def write_text_file(path: str, content: str, *, ctx: Optional[FileSystemActionContext] = None) -> ActionResult:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return ActionResult(success=True, output=str(p))
    except Exception as e:  # noqa: BLE001
        return ActionResult(success=False, error=str(e))


def move_file(src: str, dst: str, *, ctx: Optional[FileSystemActionContext] = None) -> ActionResult:
    try:
        src_p = Path(src)
        dst_p = Path(dst)
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        src_p.rename(dst_p)
        return ActionResult(success=True, output=str(dst_p))
    except Exception as e:  # noqa: BLE001
        return ActionResult(success=False, error=str(e))
