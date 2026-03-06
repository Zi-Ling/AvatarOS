# server/app/avatar/skills/core/fs_skill.py

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional, List
from pydantic import Field, model_validator

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext

logger = logging.getLogger(__name__)

# 文件大小限制（20MB）
MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# ============================================================================
# fs.read - 读取文件（文本模式，默认 UTF-8）
# ============================================================================

class FsReadInput(SkillInput):
    path: str = Field(..., description="File path to read (relative or absolute)")
    encoding: str = Field("utf-8", description="Text encoding (default: utf-8)")
    mode: str = Field("text", description="Read mode: 'text' (default) or 'binary'")

class FsReadOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Primary output: file content")  # ← 新增标准字段
    path: str
    content: Optional[str] = None
    size_bytes: Optional[int] = None

@register_skill
class FsReadSkill(BaseSkill[FsReadInput, FsReadOutput]):
    spec = SkillSpec(
        name="fs.read",
        api_name="fs.read",
        aliases=["read_file", "file.read"],
        description=f"Read file content (text mode by default, max {MAX_FILE_SIZE_MB}MB). 读取文件内容（默认文本模式，最大{MAX_FILE_SIZE_MB}MB）。",
        category=SkillCategory.FILE,
        input_model=FsReadInput,
        output_model=FsReadOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.READ},
            risk_level=SkillRiskLevel.READ,
            priority=10,  # 核心技能
        ),
        
        synonyms=["read file", "open file", "load file", "读取文件", "打开文件"],
        
        examples=[
            {"description": "Read text file", "params": {"path": "README.md"}},
            {"description": "Read with encoding", "params": {"path": "data.txt", "encoding": "gbk"}},
        ],
        
        permissions=[SkillPermission(name="file_read", description="Read files")],
        tags=["file", "read", "文件", "读取"]
    )

    async def run(self, ctx: SkillContext, params: FsReadInput) -> FsReadOutput:
        target_path = ctx.resolve_path(params.path)
        
        if ctx.dry_run:
            return FsReadOutput(
                success=True,
                message=f"[dry_run] Would read: {target_path}",
                path=str(target_path),
                output=None
            )

        try:
            if not target_path.exists():
                return FsReadOutput(success=False, message=f"File not found: {target_path}", path=str(target_path), output=None)
            
            if not target_path.is_file():
                return FsReadOutput(success=False, message=f"Not a file: {target_path}", path=str(target_path), output=None)
            
            # 检查文件大小
            file_size = target_path.stat().st_size
            if file_size > MAX_FILE_SIZE_BYTES:
                return FsReadOutput(
                    success=False,
                    message=f"File too large: {file_size / 1024 / 1024:.2f}MB (max {MAX_FILE_SIZE_MB}MB)",
                    path=str(target_path),
                    output=None
                )
            
            # 读取内容
            if params.mode == "binary":
                content = target_path.read_bytes().hex()  # 二进制转十六进制字符串
            else:
                content = target_path.read_text(encoding=params.encoding)
            
            return FsReadOutput(
                success=True,
                message=f"Read {file_size} bytes",
                path=str(target_path),
                content=content,
                size_bytes=file_size,
                output=content
            )
        except UnicodeDecodeError as e:
            return FsReadOutput(success=False, message=f"Encoding error: {e}. Try mode='binary' or different encoding.", path=str(target_path), output=None)
        except Exception as e:
            return FsReadOutput(success=False, message=str(e), path=str(target_path), output=None)


# ============================================================================
# fs.write - 写入文件（文本模式，默认 UTF-8）
# ============================================================================

class FsWriteInput(SkillInput):
    path: str = Field(..., description="File path to write (relative or absolute)")
    content: str = Field(..., description="Content to write")
    encoding: str = Field("utf-8", description="Text encoding (default: utf-8)")
    mode: str = Field("text", description="Write mode: 'text' (default) or 'binary'")
    append: bool = Field(False, description="Append to file instead of overwrite")

class FsWriteOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Primary output: file path")
    path: str
    bytes_written: Optional[int] = None

@register_skill
class FsWriteSkill(BaseSkill[FsWriteInput, FsWriteOutput]):
    spec = SkillSpec(
        name="fs.write",
        api_name="fs.write",
        aliases=["write_file", "file.write", "save_file"],
        description=f"Write content to file (text mode by default, max {MAX_FILE_SIZE_MB}MB). 写入内容到文件（默认文本模式，最大{MAX_FILE_SIZE_MB}MB）。",
        category=SkillCategory.FILE,
        input_model=FsWriteInput,
        output_model=FsWriteOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.WRITE, SkillCapability.CREATE},
            risk_level=SkillRiskLevel.WRITE,
            priority=10,
        ),
        
        synonyms=["write file", "save file", "create file", "写入文件", "保存文件", "创建文件"],
        
        examples=[
            {"description": "Write text file", "params": {"path": "output.txt", "content": "Hello World"}},
            {"description": "Append to file", "params": {"path": "log.txt", "content": "New log entry\n", "append": True}},
        ],
        
        permissions=[SkillPermission(name="file_write", description="Write files")],
        tags=["file", "write", "save", "文件", "写入", "保存"]
    )

    async def run(self, ctx: SkillContext, params: FsWriteInput) -> FsWriteOutput:
        target_path = ctx.resolve_path(params.path)
        
        if ctx.dry_run:
            return FsWriteOutput(
                success=True,
                message=f"[dry_run] Would write to: {target_path}",
                path=str(target_path),
                output=str(target_path)
            )

        try:
            # 检查内容大小
            if params.mode == "binary":
                content_bytes = bytes.fromhex(params.content)
            else:
                content_bytes = params.content.encode(params.encoding)
            
            if len(content_bytes) > MAX_FILE_SIZE_BYTES:
                return FsWriteOutput(
                    success=False,
                    message=f"Content too large: {len(content_bytes) / 1024 / 1024:.2f}MB (max {MAX_FILE_SIZE_MB}MB)",
                    path=str(target_path),
                    output=None
                )
            
            # 创建父目录
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 写入内容
            if params.append:
                if params.mode == "binary":
                    with open(target_path, "ab") as f:
                        f.write(content_bytes)
                else:
                    with open(target_path, "a", encoding=params.encoding) as f:
                        f.write(params.content)
            else:
                if params.mode == "binary":
                    target_path.write_bytes(content_bytes)
                else:
                    target_path.write_text(params.content, encoding=params.encoding)
            
            # 验证
            if not target_path.exists():
                return FsWriteOutput(success=False, message="File not found after write", path=str(target_path), output=None)
            
            return FsWriteOutput(
                success=True,
                message=f"Written {len(content_bytes)} bytes",
                path=str(target_path),
                bytes_written=len(content_bytes),
                output=str(target_path)
            )
        except Exception as e:
            return FsWriteOutput(success=False, message=str(e), path=str(target_path), output=None)


# ============================================================================
# fs.list - 列出目录内容
# ============================================================================

class FsListInput(SkillInput):
    path: str = Field(".", description="Directory path to list (default: current directory)")
    recursive: bool = Field(False, description="List recursively")

class FsListItem(SkillInput):
    name: str
    path: str
    is_dir: bool
    size: Optional[int] = None

class FsListOutput(SkillOutput):
    output: Optional[List[FsListItem]] = Field(None, description="Primary output: list of items")
    path: str
    items: List[FsListItem] = []
    total_files: int = 0
    total_dirs: int = 0

@register_skill
class FsListSkill(BaseSkill[FsListInput, FsListOutput]):
    spec = SkillSpec(
        name="fs.list",
        api_name="fs.list",
        aliases=["list_dir", "ls", "dir"],
        description="List directory contents. 列出目录内容。",
        category=SkillCategory.FILE,
        input_model=FsListInput,
        output_model=FsListOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.READ},
            risk_level=SkillRiskLevel.READ,
            priority=10,
        ),
        
        synonyms=["list directory", "list files", "列出目录", "列出文件"],
        
        examples=[
            {"description": "List current directory", "params": {"path": "."}},
            {"description": "List recursively", "params": {"path": "src", "recursive": True}},
        ],
        
        permissions=[SkillPermission(name="file_read", description="Read directory")],
        tags=["file", "directory", "list", "文件", "目录", "列表"]
    )

    async def run(self, ctx: SkillContext, params: FsListInput) -> FsListOutput:
        target_path = ctx.resolve_path(params.path)
        
        if ctx.dry_run:
            return FsListOutput(
                success=True,
                message=f"[dry_run] Would list: {target_path}",
                path=str(target_path),
                output=[]
            )

        try:
            if not target_path.exists():
                return FsListOutput(success=False, message=f"Directory not found: {target_path}", path=str(target_path), output=None)
            
            if not target_path.is_dir():
                return FsListOutput(success=False, message=f"Not a directory: {target_path}", path=str(target_path), output=None)
            
            items = []
            total_files = 0
            total_dirs = 0
            
            iterator = target_path.rglob("*") if params.recursive else target_path.iterdir()
            
            for p in iterator:
                item = FsListItem(
                    name=p.name,
                    path=str(p.relative_to(target_path)),
                    is_dir=p.is_dir()
                )
                
                if p.is_file():
                    try:
                        item.size = p.stat().st_size
                    except OSError:
                        pass
                    total_files += 1
                else:
                    total_dirs += 1
                
                items.append(item)
            
            return FsListOutput(
                success=True,
                message=f"Found {len(items)} items",
                path=str(target_path),
                items=items,
                total_files=total_files,
                total_dirs=total_dirs,
                output=items
            )
        except Exception as e:
            return FsListOutput(success=False, message=str(e), path=str(target_path), output=None)


# ============================================================================
# fs.delete - 删除文件或目录
# ============================================================================

class FsDeleteInput(SkillInput):
    path: str = Field(..., description="File or directory path to delete")
    recursive: bool = Field(False, description="Delete directory recursively (required for non-empty dirs)")

class FsDeleteOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Primary output: deleted path")
    path: str

@register_skill
class FsDeleteSkill(BaseSkill[FsDeleteInput, FsDeleteOutput]):
    spec = SkillSpec(
        name="fs.delete",
        api_name="fs.delete",
        aliases=["delete_file", "remove_file", "rm"],
        description="Delete file or directory. 删除文件或目录。",
        category=SkillCategory.FILE,
        input_model=FsDeleteInput,
        output_model=FsDeleteOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.DELETE},
            risk_level=SkillRiskLevel.WRITE,
            priority=10,
        ),
        
        synonyms=["delete file", "remove file", "delete directory", "删除文件", "删除目录"],
        
        examples=[
            {"description": "Delete file", "params": {"path": "temp.txt"}},
            {"description": "Delete directory", "params": {"path": "temp_folder", "recursive": True}},
        ],
        
        permissions=[SkillPermission(name="file_write", description="Delete files")],
        tags=["file", "delete", "remove", "文件", "删除"]
    )

    async def run(self, ctx: SkillContext, params: FsDeleteInput) -> FsDeleteOutput:
        target_path = ctx.resolve_path(params.path)
        
        if ctx.dry_run:
            return FsDeleteOutput(
                success=True,
                message=f"[dry_run] Would delete: {target_path}",
                path=str(target_path),
                output=str(target_path)
            )

        try:
            if not target_path.exists():
                return FsDeleteOutput(success=False, message=f"Not found: {target_path}", path=str(target_path), output=None)
            
            if target_path.is_dir():
                if params.recursive:
                    shutil.rmtree(target_path)
                else:
                    target_path.rmdir()  # 只删除空目录
            else:
                target_path.unlink()
            
            # 验证
            if target_path.exists():
                return FsDeleteOutput(success=False, message="Path still exists after delete", path=str(target_path), output=None)
            
            return FsDeleteOutput(
                success=True,
                message=f"Deleted: {target_path}",
                path=str(target_path),
                output=str(target_path)
            )
        except Exception as e:
            return FsDeleteOutput(success=False, message=str(e), path=str(target_path), output=None)


# ============================================================================
# fs.move - 移动/重命名文件或目录
# ============================================================================

class FsMoveInput(SkillInput):
    src: str = Field(..., description="Source path")
    dst: str = Field(..., description="Destination path")

class FsMoveOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Primary output: destination path")
    src: str
    dst: str

@register_skill
class FsMoveSkill(BaseSkill[FsMoveInput, FsMoveOutput]):
    spec = SkillSpec(
        name="fs.move",
        api_name="fs.move",
        aliases=["move_file", "rename_file", "mv"],
        description="Move or rename file/directory. 移动或重命名文件/目录。",
        category=SkillCategory.FILE,
        input_model=FsMoveInput,
        output_model=FsMoveOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.WRITE, SkillCapability.MODIFY},
            risk_level=SkillRiskLevel.WRITE,
            priority=10,
        ),
        
        synonyms=["move file", "rename file", "移动文件", "重命名文件"],
        
        examples=[
            {"description": "Rename file", "params": {"src": "old.txt", "dst": "new.txt"}},
            {"description": "Move file", "params": {"src": "file.txt", "dst": "backup/file.txt"}},
        ],
        
        permissions=[SkillPermission(name="file_write", description="Move files")],
        tags=["file", "move", "rename", "文件", "移动", "重命名"]
    )

    async def run(self, ctx: SkillContext, params: FsMoveInput) -> FsMoveOutput:
        src_path = ctx.resolve_path(params.src)
        dst_path = ctx.resolve_path(params.dst)
        
        if ctx.dry_run:
            return FsMoveOutput(
                success=True,
                message=f"[dry_run] Would move {src_path} -> {dst_path}",
                src=str(src_path),
                dst=str(dst_path),
                output=str(dst_path)
            )

        try:
            if not src_path.exists():
                return FsMoveOutput(success=False, message=f"Source not found: {src_path}", src=str(src_path), dst=str(dst_path), output=None)
            
            if dst_path.exists():
                return FsMoveOutput(success=False, message=f"Destination already exists: {dst_path}", src=str(src_path), dst=str(dst_path), output=None)
            
            # 创建目标父目录
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 移动
            shutil.move(str(src_path), str(dst_path))
            
            # 验证
            if src_path.exists():
                return FsMoveOutput(success=False, message="Source still exists after move", src=str(src_path), dst=str(dst_path), output=None)
            
            if not dst_path.exists():
                return FsMoveOutput(success=False, message="Destination not found after move", src=str(src_path), dst=str(dst_path), output=None)
            
            return FsMoveOutput(
                success=True,
                message=f"Moved {src_path.name} -> {dst_path}",
                src=str(src_path),
                dst=str(dst_path),
                output=str(dst_path)
            )
        except Exception as e:
            return FsMoveOutput(success=False, message=str(e), src=str(src_path), dst=str(dst_path), output=None)


# ============================================================================
# fs.copy - 复制文件或目录
# ============================================================================

class FsCopyInput(SkillInput):
    src: str = Field(..., description="Source path")
    dst: str = Field(..., description="Destination path")
    overwrite: bool = Field(False, description="Overwrite if destination exists")

class FsCopyOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Primary output: destination path")
    src: str
    dst: str

@register_skill
class FsCopySkill(BaseSkill[FsCopyInput, FsCopyOutput]):
    spec = SkillSpec(
        name="fs.copy",
        api_name="fs.copy",
        aliases=["copy_file", "cp"],
        description="Copy file or directory. 复制文件或目录。",
        category=SkillCategory.FILE,
        input_model=FsCopyInput,
        output_model=FsCopyOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.WRITE, SkillCapability.CREATE},
            risk_level=SkillRiskLevel.WRITE,
            priority=10,
        ),
        
        synonyms=["copy file", "duplicate file", "复制文件", "备份文件"],
        
        examples=[
            {"description": "Copy file", "params": {"src": "data.txt", "dst": "data_backup.txt"}},
            {"description": "Copy directory", "params": {"src": "src_folder", "dst": "backup_folder"}},
        ],
        
        permissions=[SkillPermission(name="file_write", description="Copy files")],
        tags=["file", "copy", "backup", "文件", "复制", "备份"]
    )

    async def run(self, ctx: SkillContext, params: FsCopyInput) -> FsCopyOutput:
        src_path = ctx.resolve_path(params.src)
        dst_path = ctx.resolve_path(params.dst)
        
        if ctx.dry_run:
            return FsCopyOutput(
                success=True,
                message=f"[dry_run] Would copy {src_path} -> {dst_path}",
                src=str(src_path),
                dst=str(dst_path),
                output=str(dst_path)
            )

        try:
            if not src_path.exists():
                return FsCopyOutput(success=False, message=f"Source not found: {src_path}", src=str(src_path), dst=str(dst_path), output=None)
            
            if dst_path.exists() and not params.overwrite:
                return FsCopyOutput(success=False, message=f"Destination exists: {dst_path}. Use overwrite=True", src=str(src_path), dst=str(dst_path), output=None)
            
            # 删除已存在的目标
            if dst_path.exists():
                if dst_path.is_dir():
                    shutil.rmtree(dst_path)
                else:
                    dst_path.unlink()
            
            # 复制
            if src_path.is_dir():
                shutil.copytree(src_path, dst_path)
            else:
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, dst_path)
            
            # 验证
            if not dst_path.exists():
                return FsCopyOutput(success=False, message="Destination not found after copy", src=str(src_path), dst=str(dst_path), output=None)
            
            return FsCopyOutput(
                success=True,
                message=f"Copied {src_path.name} -> {dst_path}",
                src=str(src_path),
                dst=str(dst_path),
                output=str(dst_path)
            )
        except Exception as e:
            return FsCopyOutput(success=False, message=str(e), src=str(src_path), dst=str(dst_path), output=None)
