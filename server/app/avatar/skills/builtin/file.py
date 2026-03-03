# app/avatar/skills/builtin/file.py

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional
import shutil
from pydantic import Field, model_validator
from ..common.path_normalizer import normalize_file_extension
from ..common.path_mixins import PathBindMixin, SourceTargetAliasMixin
from ..common.content_mixins import ContentRobustnessMixin

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext

logger = logging.getLogger(__name__)

# ============================================================================
# file.write_text
# ============================================================================

class WriteTextFileInput(PathBindMixin,ContentRobustnessMixin, SkillInput):
    relative_path: str = Field(..., description="Relative file path (relative to base_path).")
    content: str = Field(..., description="Text content to write into the file.")
    encoding: str = Field("utf-8", description="File encoding (default: utf-8)")

    @model_validator(mode="after")
    def normalize_ext(self):
        # 允许的文本文件后缀（可以根据需要扩展）
        ALLOWED_TEXT_EXTS = {
            ".txt", ".md", ".log", ".json", ".xml", ".yaml", ".yml", ".ini", ".conf", 
            ".py", ".js", ".ts", ".html", ".css", ".sh", ".bat", ".csv", ".tsv"
        }
        self.relative_path = normalize_file_extension(
            self.relative_path, 
            default_ext=".txt", 
            allowed_exts=ALLOWED_TEXT_EXTS,
            strict_allowed=False # 关键：宽松模式，只记录日志，不强制修改
        )
        return self

class WriteTextFileOutput(SkillOutput):
    path: Optional[str] = None
    bytes_written: Optional[int] = None

@register_skill
class FileWriteTextSkill(BaseSkill[WriteTextFileInput, WriteTextFileOutput]):
    spec = SkillSpec(
        name="file.write_text",
        api_name="file.write", # Primary API Name seen by LLM
        aliases=["file.write_text", "file.create", "file.save"], # Aliases for compatibility
        description="Write text content to a file (create or overwrite). 写入文本内容到文件。",
        category=SkillCategory.FILE,
        input_model=WriteTextFileInput,
        output_model=WriteTextFileOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.WRITE, SkillCapability.CREATE},
            risk_level="high",
            file_extensions=[".txt", ".md", ".log", ".json", ".xml", ".yaml", ".yml", ".ini", ".conf", ".py", ".js", ".ts", ".html", ".css", ".sh", ".bat"]
        ),
        
        # ✅ Artifact Management（混合方案：声明式）
        produces_artifact=True,
        artifact_type="file:text",
        artifact_path_field="path",  # 从 output.path 读取
        
        # V2: Semantic search fields
        synonyms=[
            "create file",
            "save text to file",
            "make a text file",
            "write content",
            "overwrite file",
            "创建文件",
            "保存文本",
            "写入内容"
        ],
        examples=[
            {"description": "Create a hello world file", "params": {"relative_path": "hello.txt", "content": "Hello World"}}
        ],
        permissions=[
            SkillPermission(name="file_write", description="Write access to local filesystem")
        ],
        tags=["file", "io", "text", "文件", "保存", "写入", "文本"]
    )

    async def run(self, ctx: SkillContext, params: WriteTextFileInput) -> WriteTextFileOutput:
        target_path = ctx.resolve_path(params.relative_path)
        logger.debug(f"FileSkill: Writing content to '{target_path.absolute()}' (dry_run={ctx.dry_run})")
        
        if ctx.dry_run:
            return WriteTextFileOutput(
                success=True,
                message=f"[dry_run] Would write file: {target_path}",
                path=str(target_path),
                bytes_written=len(params.content.encode(params.encoding))
            )

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(params.content, encoding=params.encoding)
            
            # Post-Execution Validator (Strict Mode)
            if not target_path.exists():
                return WriteTextFileOutput(success=False, message=f"Validator Error: File not found at {target_path} after write operation.")
            
            # Verify content size/integrity
            written_content = target_path.read_text(encoding=params.encoding)
            if written_content != params.content:
                 return WriteTextFileOutput(success=False, message=f"Validator Error: Content mismatch. Written {len(written_content)} chars, expected {len(params.content)}.")
            
            return WriteTextFileOutput(
                success=True,
                message=f"File written: {target_path}",
                path=str(target_path),
                bytes_written=len(params.content.encode(params.encoding)),
                # 文件系统操作元数据
                fs_operation='created',
                fs_path=params.relative_path,
                fs_type='file'
            )
        except Exception as e:
            return WriteTextFileOutput(success=False, message=str(e))


# ============================================================================
# file.read_text
# ============================================================================

class ReadTextFileInput(PathBindMixin, SkillInput):
    # relative_path 可以允许为空，因为有可能完全靠 file_path/abs_path 驱动
    relative_path: str | None = Field(
        None, description="Relative file path (relative to base_path)."
    )
    encoding: str = Field("utf-8", description="File encoding (default: utf-8)")
    
    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute file path. If provided, takes precedence."
    )

class ReadTextFileOutput(SkillOutput):
    content: Optional[str] = None
    path: Optional[str] = None

@register_skill
class FileReadTextSkill(BaseSkill[ReadTextFileInput, ReadTextFileOutput]):
    spec = SkillSpec(
        name="file.read_text",
        api_name="file.read",
        aliases=["file.read_text", "file.read", "fs.read"],
        description="Read text content from a file. 读取文件文本内容。",
        category=SkillCategory.FILE,
        input_model=ReadTextFileInput,
        output_model=ReadTextFileOutput,
        
        # Capability Routing Metadata
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.READ},
            risk_level="normal",
            file_extensions=[".txt", ".md", ".log", ".json", ".xml", ".yaml", ".yml", ".ini", ".conf", ".py", ".js", ".ts", ".html", ".css", ".sh", ".bat"]
        ),
        
        synonyms=[
            "open file",
            "read content",
            "load text file",
            "get file content",
            "打开文件",
            "读取内容",
            "查看文件"
        ],
        examples=[
            {"description": "Read readme.md", "params": {"relative_path": "README.md"}}
        ],
        permissions=[
            SkillPermission(name="file_read", description="Read access to local filesystem")
        ],
        tags=["file", "io", "text", "文件", "读取", "文本"]
    )

    async def run(self, ctx: SkillContext, params: ReadTextFileInput) -> ReadTextFileOutput:
        # 1. 优先使用 abs_path
        if params.abs_path:
             target_path = Path(params.abs_path)
        # 2. 否则使用 relative_path
        elif params.relative_path:
             target_path = ctx.resolve_path(params.relative_path)
        # 3. 如果都没有，报错
        else:
             return ReadTextFileOutput(success=False, message="No valid path provided (neither relative_path nor abs_path).")

        if ctx.dry_run:
            return ReadTextFileOutput(
                success=True,
                message=f"[dry_run] Would read file: {target_path}",
                path=str(target_path)
            )

        try:
            # Pre-execution validation
            if not target_path.exists():
                return ReadTextFileOutput(success=False, message=f"File not found: {target_path}")
            
            if not target_path.is_file():
                return ReadTextFileOutput(success=False, message=f"Path is not a file: {target_path}")
            
            # Execute
            content = target_path.read_text(encoding=params.encoding)
            
            # Post-execution verification
            if content is None:
                return ReadTextFileOutput(success=False, message=f"Verification Failed: Read operation returned None")
            
            # Verify file is still accessible
            if not target_path.exists():
                return ReadTextFileOutput(success=False, message=f"Verification Failed: File disappeared after read")
            
            return ReadTextFileOutput(
                success=True,
                message=f"File read: {target_path} ({len(content)} characters)",
                content=content,
                path=str(target_path)
            )
        except UnicodeDecodeError as e:
            return ReadTextFileOutput(success=False, message=f"Encoding error: {e}. Try a different encoding.")
        except PermissionError:
            return ReadTextFileOutput(success=False, message=f"Permission denied: Cannot read {target_path}")
        except Exception as e:
            return ReadTextFileOutput(success=False, message=f"Read failed: {str(e)}")


# ============================================================================
# file.append_text
# ============================================================================

class AppendTextFileInput(PathBindMixin, ContentRobustnessMixin, SkillInput):
    # relative_path 可以允许为空，因为有可能完全靠 file_path/abs_path 驱动
    relative_path: str | None = Field(
        None, description="Relative file path (relative to base_path)."
    )
    content: str = Field(..., description="Text content to append to the file.")
    encoding: str = Field("utf-8", description="File encoding (default: utf-8)")
    
    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute file path. If provided, takes precedence."
    )

    @model_validator(mode="after")
    def normalize_ext(self):
        # 允许的文本文件后缀（可以根据需要扩展）
        ALLOWED_TEXT_EXTS = {
            ".txt", ".md", ".log", ".json", ".xml", ".yaml", ".yml", ".ini", ".conf", 
            ".py", ".js", ".ts", ".html", ".css", ".sh", ".bat", ".csv", ".tsv"
        }
        if self.relative_path:
            self.relative_path = normalize_file_extension(
                self.relative_path, 
                default_ext=".txt", 
                allowed_exts=ALLOWED_TEXT_EXTS,
                strict_allowed=False # 关键：宽松模式，只记录日志，不强制修改
            )
        return self

class AppendTextFileOutput(SkillOutput):
    path: Optional[str] = None
    bytes_appended: Optional[int] = None
    total_size: Optional[int] = None

@register_skill
class FileAppendTextSkill(BaseSkill[AppendTextFileInput, AppendTextFileOutput]):
    spec = SkillSpec(
        name="file.append_text",
        api_name="file.append",
        aliases=["file.append", "file.add_content"],
        description="Append text content to a file. 在文件中追加文本内容。",
        category=SkillCategory.FILE,
        input_model=AppendTextFileInput,
        output_model=AppendTextFileOutput,
        
        # Capability Routing Metadata
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.WRITE, SkillCapability.MODIFY},
            risk_level="normal",
            file_extensions=[".txt", ".md", ".log", ".json", ".xml", ".yaml", ".yml", ".ini", ".conf", ".py", ".js", ".ts", ".html", ".css", ".sh", ".bat"]
        ),
        
        # ✅ Artifact Management
        produces_artifact=True,
        artifact_type="file:text",
        artifact_path_field="path",
        
        synonyms=[
            "append to file",
            "add text to file",
            "追加内容",
            "添加文本"
        ],
        examples=[
            {"description": "Append log entry", "params": {"relative_path": "app.log", "content": "\n[INFO] Started"}}
        ],
        permissions=[
            SkillPermission(name="file_write", description="Write access to local filesystem")
        ],
        tags=["file", "io", "text", "文件", "追加", "写入"]
    )

    async def run(self, ctx: SkillContext, params: AppendTextFileInput) -> AppendTextFileOutput:
        # 1. 优先使用 abs_path
        if params.abs_path:
             target_path = Path(params.abs_path)
        # 2. 否则使用 relative_path
        elif params.relative_path:
             target_path = ctx.resolve_path(params.relative_path)
        # 3. 如果都没有，报错
        else:
             return AppendTextFileOutput(success=False, message="No valid path provided (neither relative_path nor abs_path).")
        
        if ctx.dry_run:
            return AppendTextFileOutput(
                success=True,
                message=f"[dry_run] Would append to file: {target_path}",
                path=str(target_path),
                bytes_appended=len(params.content.encode(params.encoding))
            )

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Append mode
            with open(target_path, "a", encoding=params.encoding) as f:
                f.write(params.content)
            
            # Validation
            if not target_path.exists():
                 return AppendTextFileOutput(success=False, message=f"Validator Error: File not found at {target_path} after append operation.")
            
            total_size = target_path.stat().st_size
            
            return AppendTextFileOutput(
                success=True,
                message=f"File appended: {target_path}",
                path=str(target_path),
                bytes_appended=len(params.content.encode(params.encoding)),
                total_size=total_size,
                # FS Metadata
                fs_operation='modified',
                fs_path=params.relative_path or os.path.basename(params.abs_path),
                fs_type='file'
            )
        except Exception as e:
            return AppendTextFileOutput(success=False, message=str(e))


# ============================================================================
# file.move
# ============================================================================

class MoveFileInput(SourceTargetAliasMixin, SkillInput):
    src: str = Field(..., description="Source file path.")
    dst: str = Field(..., description="Destination file path.")

    # 可选：增加 abs_src / abs_dst
    abs_src: str | None = Field(
        None, description="Absolute source path. If provided, takes precedence."
    )
    abs_dst: str | None = Field(
        None, description="Absolute destination path. If provided, takes precedence."
    )

class MoveFileOutput(SkillOutput):
    src: Optional[str] = None
    dst: Optional[str] = None

@register_skill
class FileMoveSkill(BaseSkill[MoveFileInput, MoveFileOutput]):
    spec = SkillSpec(
        name="file.move",
        api_name="file.move",
        aliases=["file.mv", "file.rename", "fs.move"],
        description="Move or rename a file (NOT for directories). 移动或重命名文件（仅限文件）。",
        category=SkillCategory.FILE,
        input_model=MoveFileInput,
        output_model=MoveFileOutput,
        
        # Capability Routing Metadata
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            # Moving is writing (creating new path) and deleting (removing old path)
            capabilities={SkillCapability.WRITE, SkillCapability.MODIFY, SkillCapability.CREATE, SkillCapability.DELETE},
            risk_level="high"
        ),
        
        synonyms=[
            "rename file",
            "move file",
            "cut and paste file",
            "change file name",
            "重命名文件",
            "移动文件",
            "改名"
        ],
        examples=[
            {"description": "Rename a file", "params": {"src": "old.txt", "dst": "new.txt"}}
        ],
        permissions=[
            SkillPermission(name="file_write", description="Write access to local filesystem")
        ],
        tags=["file", "io", "文件", "移动", "重命名"]
    )

    async def run(self, ctx: SkillContext, params: MoveFileInput) -> MoveFileOutput:
        # Resolve source
        if params.abs_src:
            src_path = Path(params.abs_src)
        else:
            src_path = ctx.resolve_path(params.src)

        # Resolve destination
        if params.abs_dst:
            dst_path = Path(params.abs_dst)
        else:
            dst_path = ctx.resolve_path(params.dst)

        if ctx.dry_run:
            return MoveFileOutput(
                success=True,
                message=f"[dry_run] Would move {src_path} -> {dst_path}",
                src=str(src_path),
                dst=str(dst_path)
            )

        try:
            # Pre-execution validation
            if not src_path.exists():
                return MoveFileOutput(success=False, message=f"Source not found: {src_path}")
            
            if src_path.is_dir():
                return MoveFileOutput(success=False, message=f"Source is a directory: {src_path} (Use directory.move for directories)")

            if dst_path.exists():
                # For move, behavior on existing dest depends on OS/implementation. 
                # shutil.move might overwrite if dest is a file.
                # Let's fail safely or clarify intent. Standard `mv` overwrites.
                # Here we warn.
                pass 
            
            # Execute
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_path), str(dst_path))
            
            # Post-execution verification
            if src_path.exists():
                return MoveFileOutput(success=False, message=f"Verification Failed: Source file still exists at {src_path}")
            
            if not dst_path.exists():
                return MoveFileOutput(success=False, message=f"Verification Failed: Destination file not found at {dst_path}")
            
            return MoveFileOutput(
                success=True,
                message=f"Moved {src_path.name} -> {dst_path}",
                src=str(src_path),
                dst=str(dst_path)
            )
        except PermissionError:
            return MoveFileOutput(success=False, message=f"Permission denied: Cannot move {src_path}")
        except Exception as e:
            return MoveFileOutput(success=False, message=f"Move failed: {str(e)}")


# ============================================================================
# file.copy
# ============================================================================

class CopyFileInput(SourceTargetAliasMixin, SkillInput):
    src: str = Field(..., description="Source file path.")
    dst: str = Field(..., description="Destination file path (or directory).")
    overwrite: bool = Field(False, description="Overwrite if destination exists.")

    # 可选：增加 abs_src / abs_dst
    abs_src: str | None = Field(
        None, description="Absolute source path. If provided, takes precedence."
    )
    abs_dst: str | None = Field(
        None, description="Absolute destination path. If provided, takes precedence."
    )

class CopyFileOutput(SkillOutput):
    src: Optional[str] = None
    dst: Optional[str] = None

@register_skill
class FileCopySkill(BaseSkill[CopyFileInput, CopyFileOutput]):
    spec = SkillSpec(
        name="file.copy",
        api_name="file.copy",
        aliases=["file.cp", "fs.copy"],
        description="Copy a file (NOT for directories). 复制文件（仅限文件）。",
        category=SkillCategory.FILE,
        input_model=CopyFileInput,
        output_model=CopyFileOutput,
        
        # Capability Routing Metadata
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.WRITE, SkillCapability.CREATE},
            risk_level="normal"
        ),
        
        synonyms=[
            "copy file",
            "duplicate file",
            "clone file",
            "backup file",
            "复制文件",
            "备份文件"
        ],
        examples=[
            {"description": "Copy a file", "params": {"src": "data.txt", "dst": "data_backup.txt"}}
        ],
        permissions=[
            SkillPermission(name="file_read", description="Read access"),
            SkillPermission(name="file_write", description="Write access")
        ],
        tags=["file", "io", "copy", "backup", "文件", "复制", "备份"]
    )

    async def run(self, ctx: SkillContext, params: CopyFileInput) -> CopyFileOutput:
        # Resolve source
        if params.abs_src:
            src_path = Path(params.abs_src)
        else:
            src_path = ctx.resolve_path(params.src)

        # Resolve destination
        if params.abs_dst:
            dst_path = Path(params.abs_dst)
        else:
            dst_path = ctx.resolve_path(params.dst)

        if ctx.dry_run:
            return CopyFileOutput(
                success=True,
                message=f"[dry_run] Would copy {src_path} -> {dst_path}",
                src=str(src_path),
                dst=str(dst_path)
            )

        try:
            # Pre-execution validation
            if not src_path.exists():
                return CopyFileOutput(success=False, message=f"Source not found: {src_path}")
            
            if src_path.is_dir():
                return CopyFileOutput(success=False, message=f"Source is a directory: {src_path} (Use directory.copy for directories)")

            # Check destination
            if dst_path.exists():
                if dst_path.is_dir():
                    # Copying file into directory is allowed, append filename
                    # dst_path = dst_path / src_path.name
                    # shutil.copy2 handles this automatically
                    pass
                elif not params.overwrite:
                    return CopyFileOutput(success=False, message=f"Destination exists: {dst_path}. Use overwrite=True to replace.")

            # Ensure parent dir exists
            if not dst_path.exists() and not dst_path.parent.exists():
                dst_path.parent.mkdir(parents=True, exist_ok=True)

            # Execute
            # copy2 preserves metadata
            shutil.copy2(str(src_path), str(dst_path))
            
            # Post-execution verification
            # Note: if dst was a dir, the actual file is inside it. 
            # shutil.copy2 returns the path to the newly created file.
            # But here we don't capture the return of shutil.copy2 easily without running it.
            
            # Simplified verification
            if not dst_path.exists() and not (dst_path / src_path.name).exists():
                 return CopyFileOutput(success=False, message=f"Verification Failed: Destination not found")

            return CopyFileOutput(
                success=True,
                message=f"Copied {src_path.name} -> {dst_path}",
                src=str(src_path),
                dst=str(dst_path)
            )
        except PermissionError:
            return CopyFileOutput(success=False, message=f"Permission denied: Cannot copy {src_path}")
        except Exception as e:
            return CopyFileOutput(success=False, message=f"Copy failed: {str(e)}")


# ============================================================================
# file.remove
# ============================================================================

class RemoveFileInput(PathBindMixin, SkillInput):
    # relative_path 可以允许为空，因为有可能完全靠 file_path/abs_path 驱动
    relative_path: str | None = Field(
        None, description="Relative file path to remove."
    )
    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute file path. If provided, takes precedence."
    )

class RemoveFileOutput(SkillOutput):
    path: str

@register_skill
class FileRemoveSkill(BaseSkill[RemoveFileInput, RemoveFileOutput]):
    spec = SkillSpec(
        name="file.remove",
        api_name="file.remove",
        aliases=["file.delete", "file.rm", "fs.remove"],
        description="Remove/Delete a file. 删除文件。",
        category=SkillCategory.FILE,
        input_model=RemoveFileInput,
        output_model=RemoveFileOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.DELETE},
            risk_level="high"
        ),
        
        synonyms=[
            "delete file",
            "erase file",
            "remove file",
            "unlink file",
            "删除文件",
            "移除文件"
        ],
        examples=[
            {"description": "Delete temp file", "params": {"relative_path": "temp.log"}}
        ],
        permissions=[
            SkillPermission(name="file_write", description="Delete files")
        ],
        tags=["file", "delete", "remove", "删除"]
    )

    async def run(self, ctx: SkillContext, params: RemoveFileInput) -> RemoveFileOutput:
        # Resolve path
        if params.abs_path:
            target_path = Path(params.abs_path)
        elif params.relative_path:
            target_path = ctx.resolve_path(params.relative_path)
        else:
            return RemoveFileOutput(success=False, message="No valid path provided.")

        if ctx.dry_run:
            return RemoveFileOutput(
                success=True,
                message=f"[dry_run] Would remove file: {target_path}",
                path=str(target_path)
            )

        try:
            if not target_path.exists():
                return RemoveFileOutput(success=False, message=f"File not found: {target_path}", path=str(target_path))
            
            if target_path.is_dir():
                return RemoveFileOutput(success=False, message=f"Path is a directory: {target_path} (Use directory.remove)", path=str(target_path))
            
            target_path.unlink()
            
            if target_path.exists():
                return RemoveFileOutput(success=False, message=f"Verification Failed: File still exists", path=str(target_path))
                
            return RemoveFileOutput(success=True, message=f"Removed: {target_path}", path=str(target_path))
        except Exception as e:
            return RemoveFileOutput(success=False, message=str(e), path=str(target_path))
