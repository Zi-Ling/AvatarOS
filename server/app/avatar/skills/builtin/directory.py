# app/avatar/skills/builtin/directory.py

from __future__ import annotations

import os
import shutil
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import Field, model_validator

logger = logging.getLogger(__name__)

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext
from ..common.path_mixins import SourceTargetAliasMixin


# ============================================================================
# directory.list (formerly dir.list)
# ============================================================================

class DirectoryListInput(SkillInput):
    path: str | None = Field(None, description="Directory path to list (default: current directory)")
    recursive: bool = Field(False, description="Whether to list contents recursively.")
    
    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute directory path. If provided, takes precedence."
    )

    @model_validator(mode="before")
    def bind_paths(cls, values):
        if not isinstance(values, dict):
            return values

        # ⭐⭐ 情况 1：Orchestrator 传了 file_path（最推荐的方式）
        file_path = values.get("file_path")
        if isinstance(file_path, str):
            if os.path.isabs(file_path):
                values.setdefault("abs_path", file_path)
                values.setdefault("path", os.path.basename(file_path))
            else:
                values.setdefault("path", file_path)
            logger.debug(f"DirectoryListSkill: bound from file_path={file_path}")
            return values

        return values

class DirectoryItem(SkillInput):
    name: str
    path: str
    is_dir: bool
    is_file: bool
    size: Optional[int] = None
    mtime: Optional[float] = None

class DirectoryListOutput(SkillOutput):
    path: str
    recursive: bool
    items: List[DirectoryItem] = []
    dirs_count: int = 0
    files_count: int = 0

@register_skill
class DirectoryListSkill(BaseSkill[DirectoryListInput, DirectoryListOutput]):
    spec = SkillSpec(
        name="directory.list",
        api_name="directory.list",
        aliases=["dir.list", "ls", "list_files", "dir"],
        description="List files and subdirectories under a given directory path. 列出目录下的文件和子目录。",
        category=SkillCategory.FILE,
        input_model=DirectoryListInput,
        output_model=DirectoryListOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.READ},
            risk_level="normal"
        ),
        
        synonyms=[
            "list directory",
            "list files",
            "show files",
            "列出目录",
            "列出文件",
            "显示文件列表"
        ],
        examples=[
            {"description": "List current directory", "params": {"path": "."}},
            {"description": "List directory recursively", "params": {"path": ".", "recursive": True}}
        ],
        permissions=[
            SkillPermission(name="file_read", description="Read directory contents")
        ],
        tags=["file", "directory", "ls", "目录", "文件", "列表"]
    )

    async def run(self, ctx: SkillContext, params: DirectoryListInput) -> DirectoryListOutput:
        # 1. 优先使用 abs_path
        if params.abs_path:
             target_path = Path(params.abs_path)
        # 2. 否则使用 path
        elif params.path:
             target_path = ctx.resolve_path(params.path)
        # 3. 默认当前目录
        else:
             target_path = ctx.resolve_path(".")
        
        if ctx.dry_run:
             return DirectoryListOutput(
                success=True,
                message=f"[dry_run] List directory: {target_path}",
                path=str(target_path),
                recursive=params.recursive
            )

        try:
            if not target_path.exists() or not target_path.is_dir():
                 return DirectoryListOutput(success=False, message=f"Directory not found: {target_path}", path=str(target_path), recursive=params.recursive)
            
            items = []
            dirs_count = 0
            files_count = 0
            
            iterator = target_path.rglob("*") if params.recursive else target_path.iterdir()
            
            for p in iterator:
                item = DirectoryItem(
                    name=p.name,
                    path=str(p),
                    is_dir=p.is_dir(),
                    is_file=p.is_file()
                )
                try:
                    stat = p.stat()
                    item.mtime = stat.st_mtime
                    if p.is_file():
                        item.size = stat.st_size
                except OSError:
                    pass

                if p.is_dir(): dirs_count += 1
                else: files_count += 1
                
                items.append(item)

            return DirectoryListOutput(
                success=True, 
                message=f"Found {len(items)} items", 
                path=str(target_path), 
                recursive=params.recursive,
                items=items,
                dirs_count=dirs_count,
                files_count=files_count
            )
        except Exception as e:
             return DirectoryListOutput(success=False, message=str(e), path=str(target_path), recursive=params.recursive)


# ============================================================================
# directory.create (formerly dir.create)
# ============================================================================

class DirectoryCreateInput(SkillInput):
    path: str | None = Field(None, description="Directory path to create.")
    exist_ok: bool = Field(True, description="Treat existing directory as success.")
    
    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute directory path. If provided, takes precedence."
    )

    @model_validator(mode="before")
    def bind_paths(cls, values):
        if not isinstance(values, dict):
            return values

        # ⭐⭐ 情况 1：Orchestrator 传了 file_path（最推荐的方式）
        file_path = values.get("file_path")
        if isinstance(file_path, str):
            if os.path.isabs(file_path):
                values.setdefault("abs_path", file_path)
                values.setdefault("path", os.path.basename(file_path))
            else:
                values.setdefault("path", file_path)
            logger.debug(f"DirectoryCreateSkill: bound from file_path={file_path}")
            return values

        return values

class DirectoryCreateOutput(SkillOutput):
    path: str

@register_skill
class DirectoryCreateSkill(BaseSkill[DirectoryCreateInput, DirectoryCreateOutput]):
    spec = SkillSpec(
        name="directory.create",
        api_name="directory.create",
        aliases=["dir.create", "mkdir", "folder.create"],
        description="Create a directory (recursive). 创建目录（递归创建）。",
        category=SkillCategory.FILE,
        input_model=DirectoryCreateInput,
        output_model=DirectoryCreateOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.CREATE},
            risk_level="normal"
        ),
        
        # ✅ Artifact Management（混合方案：声明式）
        produces_artifact=True,
        artifact_type="directory",
        artifact_path_field="path",
        
        synonyms=[
            "create directory",
            "make directory",
            "create folder",
            "创建目录",
            "创建文件夹",
            "新建目录"
        ],
        examples=[
            {"description": "Create a directory", "params": {"path": "new_folder"}},
            {"description": "Create nested directories", "params": {"path": "parent/child"}}
        ],
        permissions=[
            SkillPermission(name="file_write", description="Create directories")
        ],
        tags=["file", "directory", "mkdir", "目录", "创建", "文件夹"]
    )

    async def run(self, ctx: SkillContext, params: DirectoryCreateInput) -> DirectoryCreateOutput:
        # 1. 优先使用 abs_path
        if params.abs_path:
             target_path = Path(params.abs_path)
        # 2. 否则使用 path
        elif params.path:
             target_path = ctx.resolve_path(params.path)
        # 3. 如果都没有，报错
        else:
             return DirectoryCreateOutput(success=False, message="No valid path provided (neither path nor abs_path).", path="")

        if ctx.dry_run:
            return DirectoryCreateOutput(success=True, message=f"[dry_run] Create directory: {target_path}", path=str(target_path))

        try:
            target_path.mkdir(parents=True, exist_ok=params.exist_ok)
            return DirectoryCreateOutput(success=True, message=f"Created: {target_path}", path=str(target_path))
        except Exception as e:
            return DirectoryCreateOutput(success=False, message=str(e), path=str(target_path))


# ============================================================================
# directory.remove (formerly dir.remove)
# ============================================================================

class DirectoryRemoveInput(SkillInput):
    path: str | None = Field(None, description="Directory path to remove.")
    recursive: bool = Field(False, description="Recursive removal.")
    
    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute directory path. If provided, takes precedence."
    )

    @model_validator(mode="before")
    def bind_paths(cls, values):
        if not isinstance(values, dict):
            return values

        # ⭐⭐ 情况 1：Orchestrator 传了 file_path（最推荐的方式）
        file_path = values.get("file_path")
        if isinstance(file_path, str):
            if os.path.isabs(file_path):
                values.setdefault("abs_path", file_path)
                values.setdefault("path", os.path.basename(file_path))
            else:
                values.setdefault("path", file_path)
            logger.debug(f"DirectoryRemoveSkill: bound from file_path={file_path}")
            return values

        return values

class DirectoryRemoveOutput(SkillOutput):
    path: str

@register_skill
class DirectoryRemoveSkill(BaseSkill[DirectoryRemoveInput, DirectoryRemoveOutput]):
    spec = SkillSpec(
        name="directory.remove",
        api_name="directory.remove",
        aliases=["dir.remove", "rmdir", "folder.delete"],
        description="Remove a directory. 删除目录。",
        category=SkillCategory.FILE,
        input_model=DirectoryRemoveInput,
        output_model=DirectoryRemoveOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.DELETE},
            risk_level="high"
        ),
        
        synonyms=[
            "delete directory",
            "remove directory",
            "delete folder",
            "删除目录",
            "删除文件夹",
            "移除目录"
        ],
        examples=[
            {"description": "Remove empty directory", "params": {"path": "empty_folder", "recursive": False}},
            {"description": "Remove directory recursively", "params": {"path": "folder", "recursive": True}}
        ],
        permissions=[
            SkillPermission(name="file_write", description="Delete directories")
        ],
        tags=["file", "directory", "rmdir", "目录", "删除", "文件夹"]
    )

    async def run(self, ctx: SkillContext, params: DirectoryRemoveInput) -> DirectoryRemoveOutput:
        # 1. 优先使用 abs_path
        if params.abs_path:
             target_path = Path(params.abs_path)
        # 2. 否则使用 path
        elif params.path:
             target_path = ctx.resolve_path(params.path)
        # 3. 如果都没有，报错
        else:
             return DirectoryRemoveOutput(success=False, message="No valid path provided (neither path nor abs_path).", path="")
        
        if ctx.dry_run:
             return DirectoryRemoveOutput(success=True, message=f"[dry_run] Remove directory: {target_path}", path=str(target_path))

        try:
            if not target_path.exists():
                return DirectoryRemoveOutput(success=False, message=f"Not found: {target_path}", path=str(target_path))
            
            if not target_path.is_dir():
                return DirectoryRemoveOutput(success=False, message=f"Not a directory: {target_path} (Use file.remove for files)", path=str(target_path))
            
            if params.recursive:
                 shutil.rmtree(target_path)
            else:
                 target_path.rmdir()
            
            return DirectoryRemoveOutput(success=True, message=f"Removed: {target_path}", path=str(target_path))
        except Exception as e:
             return DirectoryRemoveOutput(success=False, message=str(e), path=str(target_path))


# ============================================================================
# directory.copy (formerly dir.copy)
# ============================================================================

class DirectoryCopyInput(SourceTargetAliasMixin, SkillInput):
    src: str | None = Field(None, description="Source directory path to copy.")
    dst: str | None = Field(None, description="Destination directory path.")
    overwrite: bool = Field(False, description="Overwrite if destination exists.")
    
    # 可选：增加 abs_src / abs_dst
    abs_src: str | None = Field(
        None, description="Absolute source path. If provided, takes precedence."
    )
    abs_dst: str | None = Field(
        None, description="Absolute destination path. If provided, takes precedence."
    )

    @model_validator(mode="before")
    def bind_paths(cls, values):
        if not isinstance(values, dict):
            return values

        # ⭐⭐ 情况 1：Orchestrator 传了 file_path（通常给 src）
        file_path = values.get("file_path")
        if isinstance(file_path, str):
            if os.path.isabs(file_path):
                values.setdefault("abs_src", file_path)
                values.setdefault("src", os.path.basename(file_path))
            else:
                values.setdefault("src", file_path)
            logger.debug(f"DirectoryCopySkill: bound from file_path={file_path} to src")
            return values

        return values

class DirectoryCopyOutput(SkillOutput):
    src: str
    dst: str
    files_copied: int = 0
    dirs_copied: int = 0

@register_skill
class DirectoryCopySkill(BaseSkill[DirectoryCopyInput, DirectoryCopyOutput]):
    spec = SkillSpec(
        name="directory.copy",
        api_name="directory.copy",
        aliases=["dir.copy", "cp", "folder.copy", "copy_dir"],
        description="Copy a directory recursively. ONLY for directories (use file.copy for files). 递归复制目录（仅限目录）。",
        category=SkillCategory.FILE,
        input_model=DirectoryCopyInput,
        output_model=DirectoryCopyOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.READ, SkillCapability.WRITE, SkillCapability.CREATE},
            risk_level="high"
        ),
        
        # ✅ Artifact Management（混合方案：声明式）
        produces_artifact=True,
        artifact_type="directory",
        artifact_path_field="dst",  # 目标目录
        artifact_metadata={"operation": "copy"},
        
        synonyms=[
            "copy directory",
            "duplicate folder",
            "clone directory",
            "复制目录",
            "复制文件夹",
            "克隆目录"
        ],
        examples=[
            {"description": "Copy a directory", "params": {"src": "source_folder", "dst": "backup_folder"}},
            {"description": "Copy with overwrite", "params": {"src": "src", "dst": "dst", "overwrite": True}}
        ],
        permissions=[
            SkillPermission(name="file_read", description="Read source directory"),
            SkillPermission(name="file_write", description="Write to destination")
        ],
        tags=["file", "directory", "copy", "backup", "目录", "复制", "备份"]
    )

    async def run(self, ctx: SkillContext, params: DirectoryCopyInput) -> DirectoryCopyOutput:
        # 1. Resolve src
        if params.abs_src:
             src_path = Path(params.abs_src)
        elif params.src:
             src_path = ctx.resolve_path(params.src)
        else:
             return DirectoryCopyOutput(success=False, message="No valid source path provided.", src="", dst="")

        # 2. Resolve dst
        if params.abs_dst:
             dst_path = Path(params.abs_dst)
        elif params.dst:
             dst_path = ctx.resolve_path(params.dst)
        else:
             return DirectoryCopyOutput(success=False, message="No valid destination path provided.", src="", dst="")
        
        if ctx.dry_run:
            return DirectoryCopyOutput(
                success=True,
                message=f"[dry_run] Copy directory: {src_path} -> {dst_path}",
                src=str(src_path),
                dst=str(dst_path)
            )

        try:
            # Pre-execution validation
            if not src_path.exists():
                return DirectoryCopyOutput(success=False, message=f"Source not found: {src_path}", src=str(src_path), dst=str(dst_path))
            
            if not src_path.is_dir():
                # [STRICT MODE] We removed the fallback logic. If it's a file, we fail.
                return DirectoryCopyOutput(success=False, message=f"Source is not a directory: {src_path} (Use file.copy for files)", src=str(src_path), dst=str(dst_path))
            
            if dst_path.exists():
                if not params.overwrite:
                    return DirectoryCopyOutput(success=False, message=f"Destination exists: {dst_path}. Use overwrite=True to replace.", src=str(src_path), dst=str(dst_path))
                # Remove existing destination
                shutil.rmtree(dst_path)
            
            # Execute copy
            shutil.copytree(src_path, dst_path)
            
            # Post-execution verification
            if not dst_path.exists():
                return DirectoryCopyOutput(success=False, message=f"Verification Failed: Destination not found after copy", src=str(src_path), dst=str(dst_path))
            
            # Count copied items
            files_copied = sum(1 for _ in dst_path.rglob("*") if _.is_file())
            dirs_copied = sum(1 for _ in dst_path.rglob("*") if _.is_dir())
            
            return DirectoryCopyOutput(
                success=True,
                message=f"Copied directory {src_path.name} -> {dst_path} ({files_copied} files, {dirs_copied} dirs)",
                src=str(src_path),
                dst=str(dst_path),
                files_copied=files_copied,
                dirs_copied=dirs_copied
            )
        except Exception as e:
            return DirectoryCopyOutput(success=False, message=str(e), src=str(src_path), dst=str(dst_path))


# ============================================================================
# directory.move (formerly dir.move)
# ============================================================================

class DirectoryMoveInput(SourceTargetAliasMixin, SkillInput):
    src: str | None = Field(None, description="Source directory path to move/rename.")
    dst: str | None = Field(None, description="Destination directory path.")
    
    # 可选：增加 abs_src / abs_dst
    abs_src: str | None = Field(
        None, description="Absolute source path. If provided, takes precedence."
    )
    abs_dst: str | None = Field(
        None, description="Absolute destination path. If provided, takes precedence."
    )

    @model_validator(mode="before")
    def bind_paths(cls, values):
        if not isinstance(values, dict):
            return values

        # ⭐⭐ 情况 1：Orchestrator 传了 file_path（通常给 src）
        file_path = values.get("file_path")
        if isinstance(file_path, str):
            if os.path.isabs(file_path):
                values.setdefault("abs_src", file_path)
                values.setdefault("src", os.path.basename(file_path))
            else:
                values.setdefault("src", file_path)
            logger.debug(f"DirectoryMoveSkill: bound from file_path={file_path} to src")
            return values

        return values

class DirectoryMoveOutput(SkillOutput):
    src: str
    dst: str

@register_skill
class DirectoryMoveSkill(BaseSkill[DirectoryMoveInput, DirectoryMoveOutput]):
    spec = SkillSpec(
        name="directory.move",
        api_name="directory.move",
        aliases=["dir.move", "mv", "folder.move", "dir.rename", "folder.rename"],
        description="Move or rename a directory. 移动或重命名目录。",
        category=SkillCategory.FILE,
        input_model=DirectoryMoveInput,
        output_model=DirectoryMoveOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.WRITE, SkillCapability.MODIFY, SkillCapability.DELETE},
            risk_level="high"
        ),
        
        # ✅ Artifact Management（混合方案：声明式）
        produces_artifact=True,
        artifact_type="directory",
        artifact_path_field="dst",  # 目标目录（移动后的位置）
        artifact_metadata={"operation": "move"},
        
        synonyms=[
            "move directory",
            "rename directory",
            "relocate folder",
            "移动目录",
            "重命名目录",
            "移动文件夹"
        ],
        examples=[
            {"description": "Rename a directory", "params": {"src": "old_name", "dst": "new_name"}},
            {"description": "Move to another location", "params": {"src": "folder", "dst": "archive/folder"}}
        ],
        permissions=[
            SkillPermission(name="file_write", description="Move/rename directories")
        ],
        tags=["file", "directory", "move", "rename", "目录", "移动", "重命名"]
    )

    async def run(self, ctx: SkillContext, params: DirectoryMoveInput) -> DirectoryMoveOutput:
        # 1. Resolve src
        if params.abs_src:
             src_path = Path(params.abs_src)
        elif params.src:
             src_path = ctx.resolve_path(params.src)
        else:
             return DirectoryMoveOutput(success=False, message="No valid source path provided.", src="", dst="")

        # 2. Resolve dst
        if params.abs_dst:
             dst_path = Path(params.abs_dst)
        elif params.dst:
             dst_path = ctx.resolve_path(params.dst)
        else:
             return DirectoryMoveOutput(success=False, message="No valid destination path provided.", src="", dst="")
        
        if ctx.dry_run:
            return DirectoryMoveOutput(
                success=True,
                message=f"[dry_run] Move directory: {src_path} -> {dst_path}",
                src=str(src_path),
                dst=str(dst_path)
            )

        try:
            # Pre-execution validation
            if not src_path.exists():
                return DirectoryMoveOutput(success=False, message=f"Source not found: {src_path}", src=str(src_path), dst=str(dst_path))
            
            if not src_path.is_dir():
                return DirectoryMoveOutput(success=False, message=f"Source is not a directory: {src_path}", src=str(src_path), dst=str(dst_path))
            
            if dst_path.exists():
                return DirectoryMoveOutput(success=False, message=f"Destination already exists: {dst_path}", src=str(src_path), dst=str(dst_path))
            
            # Execute move
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_path), str(dst_path))
            
            # Post-execution verification
            if src_path.exists():
                return DirectoryMoveOutput(success=False, message=f"Verification Failed: Source still exists at {src_path}", src=str(src_path), dst=str(dst_path))
            
            if not dst_path.exists():
                return DirectoryMoveOutput(success=False, message=f"Verification Failed: Destination not found at {dst_path}", src=str(src_path), dst=str(dst_path))
            
            return DirectoryMoveOutput(
                success=True,
                message=f"Moved {src_path.name} -> {dst_path}",
                src=str(src_path),
                dst=str(dst_path)
            )
        except Exception as e:
            return DirectoryMoveOutput(success=False, message=str(e), src=str(src_path), dst=str(dst_path))


# ============================================================================
# directory.info (formerly dir.info)
# ============================================================================

class DirectoryInfoInput(SkillInput):
    path: str | None = Field(None, description="Directory path to get info about.")
    include_size: bool = Field(True, description="Calculate total directory size (may be slow for large dirs).")
    
    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute directory path. If provided, takes precedence."
    )

    @model_validator(mode="before")
    def bind_paths(cls, values):
        if not isinstance(values, dict):
            return values

        # ⭐⭐ 情况 1：Orchestrator 传了 file_path（最推荐的方式）
        file_path = values.get("file_path")
        if isinstance(file_path, str):
            if os.path.isabs(file_path):
                values.setdefault("abs_path", file_path)
                values.setdefault("path", os.path.basename(file_path))
            else:
                values.setdefault("path", file_path)
            logger.debug(f"DirectoryInfoSkill: bound from file_path={file_path}")
            return values

        return values

class DirectoryInfoOutput(SkillOutput):
    path: str
    exists: bool = False
    total_files: int = 0
    total_dirs: int = 0
    total_size: Optional[int] = None  # in bytes
    total_size_mb: Optional[float] = None
    depth: int = 0  # max depth of directory tree

@register_skill
class DirectoryInfoSkill(BaseSkill[DirectoryInfoInput, DirectoryInfoOutput]):
    spec = SkillSpec(
        name="directory.info",
        api_name="directory.info",
        aliases=["dir.info", "dir.stat", "folder.info", "dir_info"],
        description="Get information about a directory (size, file count, etc). 获取目录信息（大小、文件数等）。",
        category=SkillCategory.FILE,
        input_model=DirectoryInfoInput,
        output_model=DirectoryInfoOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.READ},
            risk_level="normal"
        ),
        
        synonyms=[
            "directory information",
            "folder statistics",
            "check directory size",
            "目录信息",
            "文件夹统计",
            "查看目录大小"
        ],
        examples=[
            {"description": "Get directory info", "params": {"path": "my_folder"}},
            {"description": "Get info without size calculation", "params": {"path": "large_folder", "include_size": False}}
        ],
        permissions=[
            SkillPermission(name="file_read", description="Read directory information")
        ],
        tags=["file", "directory", "info", "stat", "目录", "信息", "统计"]
    )

    async def run(self, ctx: SkillContext, params: DirectoryInfoInput) -> DirectoryInfoOutput:
        # 1. 优先使用 abs_path
        if params.abs_path:
             target_path = Path(params.abs_path)
        # 2. 否则使用 path
        elif params.path:
             target_path = ctx.resolve_path(params.path)
        # 3. 如果都没有，报错
        else:
             return DirectoryInfoOutput(success=False, message="No valid path provided (neither path nor abs_path).", path="")
        
        if ctx.dry_run:
            return DirectoryInfoOutput(
                success=True,
                message=f"[dry_run] Get info for: {target_path}",
                path=str(target_path)
            )

        try:
            if not target_path.exists():
                return DirectoryInfoOutput(success=False, message=f"Directory not found: {target_path}", path=str(target_path), exists=False)
            
            if not target_path.is_dir():
                return DirectoryInfoOutput(success=False, message=f"Path is not a directory: {target_path}", path=str(target_path), exists=True)
            
            # Count files and directories
            total_files = 0
            total_dirs = 0
            total_size = 0
            max_depth = 0
            
            for p in target_path.rglob("*"):
                # Calculate depth
                try:
                    relative = p.relative_to(target_path)
                    depth = len(relative.parts)
                    max_depth = max(max_depth, depth)
                except ValueError:
                    pass
                
                if p.is_file():
                    total_files += 1
                    if params.include_size:
                        try:
                            total_size += p.stat().st_size
                        except OSError:
                            pass
                elif p.is_dir():
                    total_dirs += 1
            
            total_size_mb = round(total_size / (1024 * 1024), 2) if params.include_size else None
            
            message = f"Directory: {target_path.name} | Files: {total_files} | Subdirs: {total_dirs}"
            if params.include_size:
                message += f" | Size: {total_size_mb} MB"
            
            return DirectoryInfoOutput(
                success=True,
                message=message,
                path=str(target_path),
                exists=True,
                total_files=total_files,
                total_dirs=total_dirs,
                total_size=total_size if params.include_size else None,
                total_size_mb=total_size_mb,
                depth=max_depth
            )
        except Exception as e:
            return DirectoryInfoOutput(success=False, message=str(e), path=str(target_path))


# ============================================================================
# directory.clear (formerly dir.clear)
# ============================================================================

class DirectoryClearInput(SkillInput):
    path: str | None = Field(None, description="Directory path to clear (remove all contents).")
    keep_hidden: bool = Field(False, description="Keep hidden files/folders (starting with .).")
    
    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute directory path. If provided, takes precedence."
    )

    @model_validator(mode="before")
    def bind_paths(cls, values):
        if not isinstance(values, dict):
            return values

        # ⭐⭐ 情况 1：Orchestrator 传了 file_path（最推荐的方式）
        file_path = values.get("file_path")
        if isinstance(file_path, str):
            if os.path.isabs(file_path):
                values.setdefault("abs_path", file_path)
                values.setdefault("path", os.path.basename(file_path))
            else:
                values.setdefault("path", file_path)
            logger.debug(f"DirectoryClearSkill: bound from file_path={file_path}")
            return values

        return values

class DirectoryClearOutput(SkillOutput):
    path: str
    items_removed: int = 0

@register_skill
class DirectoryClearSkill(BaseSkill[DirectoryClearInput, DirectoryClearOutput]):
    spec = SkillSpec(
        name="directory.clear",
        api_name="directory.clear",
        aliases=["dir.clear", "dir.empty", "folder.clear", "clear_dir"],
        description="Clear all contents from a directory (keeps the directory itself). 清空目录内容（保留目录本身）。",
        category=SkillCategory.FILE,
        input_model=DirectoryClearInput,
        output_model=DirectoryClearOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.DELETE},
            risk_level="critical"  # Deleting contents is risky
        ),
        
        synonyms=[
            "empty directory",
            "clear folder",
            "remove directory contents",
            "清空目录",
            "清空文件夹",
            "删除目录内容"
        ],
        examples=[
            {"description": "Clear all contents", "params": {"path": "temp_folder"}},
            {"description": "Clear but keep hidden files", "params": {"path": "folder", "keep_hidden": True}}
        ],
        permissions=[
            SkillPermission(name="file_write", description="Delete directory contents")
        ],
        tags=["file", "directory", "clear", "empty", "目录", "清空", "删除"]
    )

    async def run(self, ctx: SkillContext, params: DirectoryClearInput) -> DirectoryClearOutput:
        # 1. 优先使用 abs_path
        if params.abs_path:
             target_path = Path(params.abs_path)
        # 2. 否则使用 path
        elif params.path:
             target_path = ctx.resolve_path(params.path)
        # 3. 如果都没有，报错
        else:
             return DirectoryClearOutput(success=False, message="No valid path provided (neither path nor abs_path).", path="")
        
        if ctx.dry_run:
            return DirectoryClearOutput(
                success=True,
                message=f"[dry_run] Clear directory: {target_path}",
                path=str(target_path)
            )

        try:
            if not target_path.exists():
                return DirectoryClearOutput(success=False, message=f"Directory not found: {target_path}", path=str(target_path))
            
            if not target_path.is_dir():
                return DirectoryClearOutput(success=False, message=f"Path is not a directory: {target_path}", path=str(target_path))
            
            items_removed = 0
            
            # Remove all items in directory
            for item in target_path.iterdir():
                # Skip hidden files if requested
                if params.keep_hidden and item.name.startswith('.'):
                    continue
                
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                    items_removed += 1
                except Exception as e:
                    # Continue even if one item fails
                    logger.warning(f"Failed to remove {item}: {e}")
            
            # Verify directory still exists but is empty (or only has hidden files)
            remaining = list(target_path.iterdir())
            if params.keep_hidden:
                remaining = [r for r in remaining if not r.name.startswith('.')]
            
            if remaining:
                return DirectoryClearOutput(
                    success=False,
                    message=f"Verification Failed: {len(remaining)} items still remain in {target_path}",
                    path=str(target_path),
                    items_removed=items_removed
                )
            
            return DirectoryClearOutput(
                success=True,
                message=f"Cleared {items_removed} items from {target_path.name}",
                path=str(target_path),
                items_removed=items_removed
            )
        except Exception as e:
            return DirectoryClearOutput(success=False, message=str(e), path=str(target_path))
