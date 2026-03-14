# server/app/avatar/skills/core/fs.py

from __future__ import annotations

import logging
import shutil
from typing import Optional, List, Dict, Any
from pydantic import Field, model_validator

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
    path: Optional[str] = Field(None, description="Path to delete (single)")
    recursive: bool = Field(False, description="Delete directory recursively")
    paths: Optional[List[str]] = Field(None, description="Batch delete list: [\"a.txt\", \"b.txt\", ...]")

    @model_validator(mode="after")
    def check_params(self) -> "FsDeleteInput":
        if not self.path and not self.paths:
            raise ValueError("Either path or paths must be provided")
        return self


class FsDeleteOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Deleted path (single)")
    path: Optional[str] = None
    results: Optional[List[Dict[str, Any]]] = Field(None, description="Batch delete results")
    failed_paths: Optional[List[str]] = Field(None, description="Paths that failed to delete")


@register_skill
class FsDeleteSkill(BaseSkill[FsDeleteInput, FsDeleteOutput]):
    spec = SkillSpec(
        name="fs.delete",
        description="Delete file or directory. Supports batch mode via `paths` list. 删除文件或目录，支持批量。",
        input_model=FsDeleteInput,
        output_model=FsDeleteOutput,
        side_effects={SideEffect.FS},
        risk_level=SkillRiskLevel.WRITE,
        aliases=["delete_file", "remove_file", "rm", "fs.delete_file", "fs.remove"],
    )

    async def run(self, ctx: SkillContext, params: FsDeleteInput) -> FsDeleteOutput:
        targets = params.paths if params.paths else [params.path]

        if ctx.dry_run:
            results = [{"path": p, "success": True, "message": "[dry_run]"} for p in targets]
            if len(targets) == 1:
                return FsDeleteOutput(success=True, message="[dry_run]", path=targets[0], output=targets[0], results=results)
            return FsDeleteOutput(success=True, message=f"[dry_run] Would delete {len(targets)} items", results=results)

        results: List[Dict[str, Any]] = []
        all_ok = True
        for p in targets:
            target = ctx.resolve_path(p)
            if not target.exists():
                results.append({"path": p, "success": False, "message": f"Not found: {target}"})
                all_ok = False
                continue
            try:
                if target.is_dir():
                    if params.recursive:
                        shutil.rmtree(target)
                    else:
                        # 检查目录是否为空，给出友好提示
                        if any(target.iterdir()):
                            results.append({"path": p, "success": False, "message": f"Directory not empty: {target.name} — use recursive=True to delete"})
                            all_ok = False
                            continue
                        target.rmdir()
                else:
                    target.unlink()
                results.append({"path": p, "success": True, "message": f"Deleted: {target.name}"})
            except Exception as e:
                results.append({"path": p, "success": False, "message": str(e)})
                all_ok = False

        if len(targets) == 1:
            r = results[0]
            return FsDeleteOutput(
                success=r["success"],
                message=r["message"],
                path=r["path"],
                output=r["path"] if r["success"] else None,
                results=results,
                failed_paths=[] if r["success"] else [r["path"]],
            )

        ok_count = sum(1 for r in results if r["success"])
        failed = [r["path"] for r in results if not r["success"]]
        return FsDeleteOutput(
            success=all_ok,
            message=f"Deleted {ok_count}/{len(targets)} items" + ("" if all_ok else " (some failed)"),
            results=results,
            failed_paths=failed if failed else None,
        )


# ── fs.move ───────────────────────────────────────────────────────────────────

class FsMoveInput(SkillInput):
    src: Optional[str] = Field(None, description="Source path (single move)")
    dst: Optional[str] = Field(None, description="Destination path (single move)")
    overwrite: bool = Field(False, description="Overwrite destination if it exists")
    moves: Optional[List[Dict[str, str]]] = Field(
        None,
        description='Batch move list: [{"src": "old.txt", "dst": "new.txt"}, ...]',
    )

    @model_validator(mode="after")
    def check_params(self) -> "FsMoveInput":
        has_single = self.src is not None and self.dst is not None
        has_batch = bool(self.moves)
        if not has_single and not has_batch:
            raise ValueError("Either (src, dst) or moves must be provided")
        return self


class FsMoveOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Destination path (single move)")
    src: Optional[str] = None
    dst: Optional[str] = None
    results: Optional[List[Dict[str, Any]]] = Field(None, description="Batch move results")
    failed_paths: Optional[List[str]] = Field(None, description="Source paths that failed to move")


@register_skill
class FsMoveSkill(BaseSkill[FsMoveInput, FsMoveOutput]):
    spec = SkillSpec(
        name="fs.move",
        description=(
            "Move or rename file/directory. Supports batch mode via `moves` list. "
            "移动或重命名，支持批量。"
        ),
        input_model=FsMoveInput,
        output_model=FsMoveOutput,
        side_effects={SideEffect.FS},
        risk_level=SkillRiskLevel.WRITE,
        aliases=["move_file", "rename_file", "mv", "fs.move_file", "fs.rename"],
    )

    async def run(self, ctx: SkillContext, params: FsMoveInput) -> FsMoveOutput:
        pairs: List[Dict[str, str]] = params.moves if params.moves else [{"src": params.src, "dst": params.dst}]

        if ctx.dry_run:
            results = [{"src": p["src"], "dst": p["dst"], "success": True, "message": "[dry_run]"} for p in pairs]
            if len(pairs) == 1:
                return FsMoveOutput(
                    success=True, message="[dry_run]",
                    src=pairs[0]["src"], dst=pairs[0]["dst"],
                    output=pairs[0]["dst"], results=results,
                )
            return FsMoveOutput(success=True, message=f"[dry_run] Would move {len(pairs)} items", results=results)

        results: List[Dict[str, Any]] = []
        all_ok = True
        for p in pairs:
            src = ctx.resolve_path(p["src"])
            dst = ctx.resolve_path(p["dst"])
            if not src.exists():
                results.append({"src": p["src"], "dst": p["dst"], "success": False, "message": f"Source not found: {src}"})
                all_ok = False
                continue
            if dst.exists():
                if not params.overwrite:
                    results.append({"src": p["src"], "dst": p["dst"], "success": False, "message": f"Destination exists: {dst.name} — use overwrite=True to replace"})
                    all_ok = False
                    continue
                # overwrite=True：先删除目标
                try:
                    shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
                except Exception as e:
                    results.append({"src": p["src"], "dst": p["dst"], "success": False, "message": f"Failed to remove existing destination: {e}"})
                    all_ok = False
                    continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                results.append({"src": p["src"], "dst": p["dst"], "success": True, "message": f"Moved {src.name} -> {dst.name}"})
            except Exception as e:
                results.append({"src": p["src"], "dst": p["dst"], "success": False, "message": str(e)})
                all_ok = False

        if len(pairs) == 1:
            r = results[0]
            return FsMoveOutput(
                success=r["success"],
                message=r["message"],
                src=r["src"],
                dst=r["dst"],
                output=r["dst"] if r["success"] else None,
                results=results,
                failed_paths=[] if r["success"] else [r["src"]],
            )

        ok_count = sum(1 for r in results if r["success"])
        failed = [r["src"] for r in results if not r["success"]]
        return FsMoveOutput(
            success=all_ok,
            message=f"Moved {ok_count}/{len(pairs)} items" + ("" if all_ok else " (some failed)"),
            results=results,
            failed_paths=failed if failed else None,
        )


# ── fs.copy ───────────────────────────────────────────────────────────────────

class FsCopyInput(SkillInput):
    src: Optional[str] = Field(None, description="Source path (single copy)")
    dst: Optional[str] = Field(None, description="Destination path (single copy)")
    overwrite: bool = Field(False, description="Overwrite if destination exists")
    copies: Optional[List[Dict[str, str]]] = Field(
        None,
        description='Batch copy list: [{"src": "a.txt", "dst": "b.txt"}, ...]',
    )

    @model_validator(mode="after")
    def check_params(self) -> "FsCopyInput":
        has_single = self.src is not None and self.dst is not None
        has_batch = bool(self.copies)
        if not has_single and not has_batch:
            raise ValueError("Either (src, dst) or copies must be provided")
        return self


class FsCopyOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Destination path (single copy)")
    src: Optional[str] = None
    dst: Optional[str] = None
    results: Optional[List[Dict[str, Any]]] = Field(None, description="Batch copy results")


@register_skill
class FsCopySkill(BaseSkill[FsCopyInput, FsCopyOutput]):
    spec = SkillSpec(
        name="fs.copy",
        description=(
            "Copy file or directory. Supports batch mode via `copies` list. "
            "复制文件或目录，支持批量。"
        ),
        input_model=FsCopyInput,
        output_model=FsCopyOutput,
        side_effects={SideEffect.FS},
        risk_level=SkillRiskLevel.WRITE,
        aliases=["copy_file", "cp", "fs.copy_file"],
    )

    async def run(self, ctx: SkillContext, params: FsCopyInput) -> FsCopyOutput:
        pairs: List[Dict[str, str]] = params.copies if params.copies else [{"src": params.src, "dst": params.dst}]

        if ctx.dry_run:
            results = [{"src": p["src"], "dst": p["dst"], "success": True, "message": "[dry_run]"} for p in pairs]
            if len(pairs) == 1:
                return FsCopyOutput(
                    success=True, message="[dry_run]",
                    src=pairs[0]["src"], dst=pairs[0]["dst"],
                    output=pairs[0]["dst"], results=results,
                )
            return FsCopyOutput(success=True, message=f"[dry_run] Would copy {len(pairs)} items", results=results)

        results: List[Dict[str, Any]] = []
        all_ok = True
        for p in pairs:
            src = ctx.resolve_path(p["src"])
            dst = ctx.resolve_path(p["dst"])
            if not src.exists():
                results.append({"src": p["src"], "dst": p["dst"], "success": False, "message": f"Source not found: {src}"})
                all_ok = False
                continue
            if dst.exists() and not params.overwrite:
                results.append({"src": p["src"], "dst": p["dst"], "success": False, "message": f"Destination exists: {dst}"})
                all_ok = False
                continue
            try:
                if dst.exists():
                    shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
                if src.is_dir():
                    shutil.copytree(src, dst)
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                results.append({"src": p["src"], "dst": p["dst"], "success": True, "message": f"Copied {src.name} -> {dst.name}"})
            except Exception as e:
                results.append({"src": p["src"], "dst": p["dst"], "success": False, "message": str(e)})
                all_ok = False

        if len(pairs) == 1:
            r = results[0]
            return FsCopyOutput(
                success=r["success"],
                message=r["message"],
                src=r["src"],
                dst=r["dst"],
                output=r["dst"] if r["success"] else None,
                results=results,
            )

        ok_count = sum(1 for r in results if r["success"])
        return FsCopyOutput(
            success=all_ok,
            message=f"Copied {ok_count}/{len(pairs)} items" + ("" if all_ok else " (some failed)"),
            results=results,
        )
