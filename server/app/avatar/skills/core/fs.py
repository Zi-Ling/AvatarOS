# server/app/avatar/skills/core/fs.py

from __future__ import annotations

import logging
import shutil
from typing import Optional, List
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SideEffect, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


# ── fs.read ───────────────────────────────────────────────────────────────────

class FsReadInput(SkillInput):
    path: str = Field(..., description="File path to read")
    encoding: str = Field("utf-8", description="Text encoding")
    mode: str = Field("text", description="'text' or 'binary'")

class FsReadOutput(SkillOutput):
    output: Optional[str] = Field(None, description="File content")
    path: str
    content: Optional[str] = None
    size_bytes: Optional[int] = None

@register_skill
class FsReadSkill(BaseSkill[FsReadInput, FsReadOutput]):
    spec = SkillSpec(
        name="fs.read",
        description=f"Read file content (text mode, max {MAX_FILE_SIZE_MB}MB). 读取文件内容。",
        input_model=FsReadInput,
        output_model=FsReadOutput,
        side_effects={SideEffect.FS},
        risk_level=SkillRiskLevel.READ,
        aliases=["read_file", "file.read", "open_file", "fs.read_file"],
    )

    async def run(self, ctx: SkillContext, params: FsReadInput) -> FsReadOutput:
        target = ctx.resolve_path(params.path)

        if ctx.dry_run:
            return FsReadOutput(success=True, message=f"[dry_run] Would read: {target}", path=str(target))

        if not target.exists():
            return FsReadOutput(success=False, message=f"File not found: {target}", path=str(target))
        if not target.is_file():
            return FsReadOutput(success=False, message=f"Not a file: {target}", path=str(target))

        size = target.stat().st_size
        if size > MAX_FILE_SIZE_BYTES:
            return FsReadOutput(success=False, message=f"File too large: {size / 1024 / 1024:.1f}MB", path=str(target))

        try:
            if params.mode == "binary":
                content = target.read_bytes().hex()
            else:
                content = target.read_text(encoding=params.encoding)
            return FsReadOutput(success=True, message=f"Read {size} bytes", path=str(target),
                                content=content, size_bytes=size, output=content)
        except UnicodeDecodeError as e:
            return FsReadOutput(success=False, message=f"Encoding error: {e}", path=str(target))
        except Exception as e:
            return FsReadOutput(success=False, message=str(e), path=str(target))


# ── fs.write ──────────────────────────────────────────────────────────────────

class FsWriteInput(SkillInput):
    path: str = Field(..., description="File path to write")
    content: str = Field(..., description="Content to write")
    encoding: str = Field("utf-8", description="Text encoding")
    mode: str = Field("text", description="'text' or 'binary'")
    append: bool = Field(False, description="Append instead of overwrite")

class FsWriteOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Written file path")
    path: str
    bytes_written: Optional[int] = None

@register_skill
class FsWriteSkill(BaseSkill[FsWriteInput, FsWriteOutput]):
    spec = SkillSpec(
        name="fs.write",
        description=f"Write content to file (max {MAX_FILE_SIZE_MB}MB). 写入文件内容。",
        input_model=FsWriteInput,
        output_model=FsWriteOutput,
        side_effects={SideEffect.FS},
        risk_level=SkillRiskLevel.WRITE,
        aliases=["write_file", "file.write", "save_file", "fs.write_file"],
    )

    async def run(self, ctx: SkillContext, params: FsWriteInput) -> FsWriteOutput:
        target = ctx.resolve_path(params.path)

        if ctx.dry_run:
            return FsWriteOutput(success=True, message=f"[dry_run] Would write: {target}", path=str(target), output=str(target))

        try:
            if params.mode == "binary":
                content_bytes = bytes.fromhex(params.content)
            else:
                content_bytes = params.content.encode(params.encoding)

            if len(content_bytes) > MAX_FILE_SIZE_BYTES:
                return FsWriteOutput(success=False, message=f"Content too large", path=str(target))

            target.parent.mkdir(parents=True, exist_ok=True)

            if params.append:
                if params.mode == "binary":
                    with open(target, "ab") as f:
                        f.write(content_bytes)
                else:
                    with open(target, "a", encoding=params.encoding) as f:
                        f.write(params.content)
            else:
                if params.mode == "binary":
                    target.write_bytes(content_bytes)
                else:
                    target.write_text(params.content, encoding=params.encoding)

            return FsWriteOutput(success=True, message=f"Written {len(content_bytes)} bytes",
                                 path=str(target), bytes_written=len(content_bytes), output=str(target))
        except Exception as e:
            return FsWriteOutput(success=False, message=str(e), path=str(target))


# ── fs.list ───────────────────────────────────────────────────────────────────

class FsListItem(SkillInput):
    name: str
    path: str
    is_dir: bool
    size: Optional[int] = None

class FsListInput(SkillInput):
    path: str = Field(".", description="Directory path")
    recursive: bool = Field(False, description="List recursively")

class FsListOutput(SkillOutput):
    output: Optional[List[FsListItem]] = Field(None, description="List of items")
    path: str
    items: List[FsListItem] = []
    total_files: int = 0
    total_dirs: int = 0

@register_skill
class FsListSkill(BaseSkill[FsListInput, FsListOutput]):
    spec = SkillSpec(
        name="fs.list",
        description="List directory contents. 列出目录内容。",
        input_model=FsListInput,
        output_model=FsListOutput,
        side_effects={SideEffect.FS},
        risk_level=SkillRiskLevel.READ,
        aliases=["list_dir", "fs.list_dir", "ls", "dir"],
    )

    async def run(self, ctx: SkillContext, params: FsListInput) -> FsListOutput:
        target = ctx.resolve_path(params.path)

        if ctx.dry_run:
            return FsListOutput(success=True, message=f"[dry_run] Would list: {target}", path=str(target), output=[])

        if not target.exists():
            return FsListOutput(success=False, message=f"Not found: {target}", path=str(target))
        if not target.is_dir():
            return FsListOutput(success=False, message=f"Not a directory: {target}", path=str(target))

        try:
            items, total_files, total_dirs = [], 0, 0
            iterator = target.rglob("*") if params.recursive else target.iterdir()
            for p in iterator:
                item = FsListItem(name=p.name, path=str(p.relative_to(target)), is_dir=p.is_dir())
                if p.is_file():
                    try:
                        item.size = p.stat().st_size
                    except OSError:
                        pass
                    total_files += 1
                else:
                    total_dirs += 1
                items.append(item)
            return FsListOutput(success=True, message=f"Found {len(items)} items", path=str(target),
                                items=items, total_files=total_files, total_dirs=total_dirs, output=items)
        except Exception as e:
            return FsListOutput(success=False, message=str(e), path=str(target))


# ── fs.delete ─────────────────────────────────────────────────────────────────

class FsDeleteInput(SkillInput):
    path: str = Field(..., description="Path to delete")
    recursive: bool = Field(False, description="Delete directory recursively")

class FsDeleteOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Deleted path")
    path: str

@register_skill
class FsDeleteSkill(BaseSkill[FsDeleteInput, FsDeleteOutput]):
    spec = SkillSpec(
        name="fs.delete",
        description="Delete file or directory. 删除文件或目录。",
        input_model=FsDeleteInput,
        output_model=FsDeleteOutput,
        side_effects={SideEffect.FS},
        risk_level=SkillRiskLevel.WRITE,
        aliases=["delete_file", "remove_file", "rm", "fs.delete_file", "fs.remove"],
    )

    async def run(self, ctx: SkillContext, params: FsDeleteInput) -> FsDeleteOutput:
        target = ctx.resolve_path(params.path)

        if ctx.dry_run:
            return FsDeleteOutput(success=True, message=f"[dry_run] Would delete: {target}", path=str(target), output=str(target))

        if not target.exists():
            return FsDeleteOutput(success=False, message=f"Not found: {target}", path=str(target))

        try:
            if target.is_dir():
                if params.recursive:
                    shutil.rmtree(target)
                else:
                    target.rmdir()
            else:
                target.unlink()
            return FsDeleteOutput(success=True, message=f"Deleted: {target}", path=str(target), output=str(target))
        except Exception as e:
            return FsDeleteOutput(success=False, message=str(e), path=str(target))


# ── fs.move ───────────────────────────────────────────────────────────────────

class FsMoveInput(SkillInput):
    src: str = Field(..., description="Source path")
    dst: str = Field(..., description="Destination path")

class FsMoveOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Destination path")
    src: str
    dst: str

@register_skill
class FsMoveSkill(BaseSkill[FsMoveInput, FsMoveOutput]):
    spec = SkillSpec(
        name="fs.move",
        description="Move or rename file/directory. 移动或重命名。",
        input_model=FsMoveInput,
        output_model=FsMoveOutput,
        side_effects={SideEffect.FS},
        risk_level=SkillRiskLevel.WRITE,
        aliases=["move_file", "rename_file", "mv", "fs.move_file", "fs.rename"],
    )

    async def run(self, ctx: SkillContext, params: FsMoveInput) -> FsMoveOutput:
        src = ctx.resolve_path(params.src)
        dst = ctx.resolve_path(params.dst)

        if ctx.dry_run:
            return FsMoveOutput(success=True, message=f"[dry_run] Would move {src} -> {dst}", src=str(src), dst=str(dst), output=str(dst))

        if not src.exists():
            return FsMoveOutput(success=False, message=f"Source not found: {src}", src=str(src), dst=str(dst))
        if dst.exists():
            return FsMoveOutput(success=False, message=f"Destination exists: {dst}", src=str(src), dst=str(dst))

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return FsMoveOutput(success=True, message=f"Moved {src.name} -> {dst}", src=str(src), dst=str(dst), output=str(dst))
        except Exception as e:
            return FsMoveOutput(success=False, message=str(e), src=str(src), dst=str(dst))


# ── fs.copy ───────────────────────────────────────────────────────────────────

class FsCopyInput(SkillInput):
    src: str = Field(..., description="Source path")
    dst: str = Field(..., description="Destination path")
    overwrite: bool = Field(False, description="Overwrite if destination exists")

class FsCopyOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Destination path")
    src: str
    dst: str

@register_skill
class FsCopySkill(BaseSkill[FsCopyInput, FsCopyOutput]):
    spec = SkillSpec(
        name="fs.copy",
        description="Copy file or directory. 复制文件或目录。",
        input_model=FsCopyInput,
        output_model=FsCopyOutput,
        side_effects={SideEffect.FS},
        risk_level=SkillRiskLevel.WRITE,
        aliases=["copy_file", "cp", "fs.copy_file"],
    )

    async def run(self, ctx: SkillContext, params: FsCopyInput) -> FsCopyOutput:
        src = ctx.resolve_path(params.src)
        dst = ctx.resolve_path(params.dst)

        if ctx.dry_run:
            return FsCopyOutput(success=True, message=f"[dry_run] Would copy {src} -> {dst}", src=str(src), dst=str(dst), output=str(dst))

        if not src.exists():
            return FsCopyOutput(success=False, message=f"Source not found: {src}", src=str(src), dst=str(dst))
        if dst.exists() and not params.overwrite:
            return FsCopyOutput(success=False, message=f"Destination exists: {dst}", src=str(src), dst=str(dst))

        try:
            if dst.exists():
                shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            return FsCopyOutput(success=True, message=f"Copied {src.name} -> {dst}", src=str(src), dst=str(dst), output=str(dst))
        except Exception as e:
            return FsCopyOutput(success=False, message=str(e), src=str(src), dst=str(dst))
