# server/app/avatar/skills/core/fs.py

from __future__ import annotations

import logging
import shutil
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, model_validator

from charset_normalizer import from_bytes

from ..base import BaseSkill, SkillSpec, SideEffect, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext
from app.avatar.runtime.graph.models.output_contract import SkillOutputContract, ValueKind, TransportMode

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


def _detect_and_decode(raw: bytes, hint_encoding: str = "utf-8") -> tuple[str, str]:
    """
    Robust text decoding with automatic encoding detection fallback.

    Strategy (same as major IDEs / cloud platforms):
      1. Try the user-specified encoding first (fast path).
      2. On failure, run charset_normalizer detection on the raw bytes.
      3. If detection succeeds, decode with the detected encoding.
      4. Last resort: decode with 'utf-8' errors='replace' so we never crash.

    Returns (decoded_text, actual_encoding_used).
    """
    # 1. Fast path: try hint encoding
    try:
        return raw.decode(hint_encoding), hint_encoding
    except (UnicodeDecodeError, LookupError):
        pass

    # 2. Detect with charset_normalizer
    detection = from_bytes(raw)
    best = detection.best()
    if best is not None:
        detected_enc = best.encoding
        try:
            return raw.decode(detected_enc), detected_enc
        except (UnicodeDecodeError, LookupError):
            pass

    # 3. Last resort: lossy UTF-8 decode (replace bad bytes with U+FFFD)
    logger.warning(
        "[fs] All encoding detection failed, falling back to utf-8 with replacement characters"
    )
    return raw.decode("utf-8", errors="replace"), "utf-8(lossy)"


# ── fs.read ───────────────────────────────────────────────────────────────────

class FsReadItem(BaseModel):
    path: str = Field(..., description="File path to read")
    encoding: str = Field("utf-8", description="Text encoding")
    mode: str = Field("text", description="'text' or 'binary'")

class FsReadInput(SkillInput):
    # 单文件模式
    path: Optional[str] = Field(None, description="File path to read (single-file mode)")
    encoding: str = Field("utf-8", description="Text encoding")
    mode: str = Field("text", description="'text' or 'binary'")
    # batch 模式：reads=[{"path": "a.txt"}, {"path": "b.txt", "encoding": "gbk"}]
    reads: Optional[List[FsReadItem]] = Field(None, description="Batch read: list of {path, encoding?, mode?}")

class FsReadOutput(SkillOutput):
    output: Optional[Any] = Field(None, description="File content (single) or dict {path: content} (batch)")
    path: str = ""
    value_kind: Optional[str] = "text"
    transport_mode: Optional[str] = "inline"
    content: Optional[str] = None
    size_bytes: Optional[int] = None
    # batch 模式结果
    contents: Optional[Dict[str, Any]] = Field(None, description="Batch result: {path: content} mapping")

@register_skill
class FsReadSkill(BaseSkill[FsReadInput, FsReadOutput]):
    spec = SkillSpec(
        name="fs.read",
        description=(
            f"Read file content (text mode, max {MAX_FILE_SIZE_MB}MB). 读取文件内容。\n"
            "Single-file mode: {\"path\": \"file.txt\"}\n"
            "Batch mode (read multiple files in ONE step): {\"reads\": [{\"path\": \"a.txt\"}, {\"path\": \"b.txt\"}]}\n"
            "Batch output: {\"contents\": {\"a.txt\": \"...\", \"b.txt\": \"...\"}}\n"
            "Use batch mode whenever reading more than one file."
        ),
        input_model=FsReadInput,
        output_model=FsReadOutput,
        side_effects={SideEffect.FS},
        risk_level=SkillRiskLevel.READ,
        aliases=["read_file", "file.read", "open_file", "fs.read_file"],
        tags=["read", "open", "load", "读取", "打开", "查看"],
        output_contract=SkillOutputContract(value_kind=ValueKind.TEXT, transport_mode=TransportMode.INLINE),
    )

    # Binary file extensions that should NOT be read in text mode
    _BINARY_EXTENSIONS = frozenset({
        ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt",
        ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico",
        ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
        ".exe", ".dll", ".so", ".dylib", ".bin", ".dat",
        ".sqlite", ".db", ".woff", ".woff2", ".ttf", ".otf",
    })

    async def _read_one(self, ctx: SkillContext, item: FsReadItem) -> tuple[bool, str, Any, int]:
        """读单个文件，返回 (success, message, content, size)"""
        target = ctx.resolve_path(item.path)
        if not target.exists():
            return False, f"File not found: {item.path}", None, 0
        if not target.is_file():
            return False, f"Not a file: {item.path}", None, 0

        # Guard: reject text-mode reads on known binary file types
        ext = target.suffix.lower()
        if item.mode == "text" and ext in self._BINARY_EXTENSIONS:
            hint = {
                ".xlsx": "Use python.run with `import pandas; df = pandas.read_excel('path')`",
                ".xls":  "Use python.run with `import pandas; df = pandas.read_excel('path')`",
                ".docx": "Use python.run with `import docx; doc = docx.Document('path')`",
                ".pdf":  "Use python.run with `import PyPDF2` to extract text",
                ".png":  "Use python.run with `from PIL import Image; img = Image.open('path')`",
                ".jpg":  "Use python.run with `from PIL import Image; img = Image.open('path')`",
                ".jpeg": "Use python.run with `from PIL import Image; img = Image.open('path')`",
            }.get(ext, "Use python.run with an appropriate library to process this binary file")
            return (
                False,
                f"Cannot read binary file '{item.path}' ({ext}) in text mode. {hint}",
                None,
                0,
            )

        size = target.stat().st_size
        if size > MAX_FILE_SIZE_BYTES:
            return False, f"File too large: {size / 1024 / 1024:.1f}MB", None, 0
        try:
            raw = target.read_bytes()
            if item.mode == "binary":
                content = raw.hex()
            else:
                # Second-layer guard: detect binary via magic bytes even if
                # extension was not in _BINARY_EXTENSIONS (e.g. unknown ext)
                if len(raw) >= 4:
                    _MAGIC = {
                        b'\x89PNG': "PNG image",
                        b'%PDF': "PDF document",
                        b'PK\x03\x04': "ZIP-based file (xlsx/docx/pptx/zip)",
                        b'\xff\xd8\xff': "JPEG image",
                        b'GIF8': "GIF image",
                        b'\x7fELF': "ELF binary",
                        b'MZ': "Windows executable",
                        b'Rar!': "RAR archive",
                    }
                    for sig, desc in _MAGIC.items():
                        if raw[:len(sig)] == sig:
                            return (
                                False,
                                f"Binary file detected ({desc}): '{item.path}'. "
                                f"Use python.run with an appropriate library to process this file.",
                                None,
                                0,
                            )
                content, actual_enc = _detect_and_decode(raw, item.encoding)
                if actual_enc != item.encoding:
                    logger.info(
                        "[fs.read] %s: requested=%s, detected=%s",
                        item.path, item.encoding, actual_enc,
                    )
            return True, f"Read {size} bytes", content, size
        except Exception as e:
            return False, str(e), None, 0

    async def run(self, ctx: SkillContext, params: FsReadInput) -> FsReadOutput:
        # ── batch 模式 ──────────────────────────────────────────────────────
        if params.reads:
            if ctx.dry_run:
                paths = [r.path for r in params.reads]
                return FsReadOutput(
                    success=True,
                    message=f"[dry_run] Would read {len(paths)} files",
                    path=", ".join(paths),
                    output={p: "[dry_run]" for p in paths},
                    contents={p: "[dry_run]" for p in paths},
                )
            contents: Dict[str, Any] = {}
            failed = []
            for item in params.reads:
                ok, msg, content, _ = await self._read_one(ctx, item)
                if ok:
                    contents[item.path] = content
                else:
                    failed.append(f"{item.path}: {msg}")
            if failed:
                # Partial success: if some files were read successfully, report
                # success=True so that CircuitBreaker / Planner don't treat this
                # as a total failure.  The error details are preserved in message
                # for Planner to see and potentially retry the missing files.
                has_any_success = bool(contents)
                return FsReadOutput(
                    success=has_any_success,
                    message=(
                        f"Read {len(contents)}/{len(contents)+len(failed)} files. "
                        f"Failed: {'; '.join(failed)}"
                    ),
                    path=", ".join(contents.keys()) if contents else "",
                    output=contents if contents else None,
                    contents=contents if contents else None,
                )
            return FsReadOutput(
                success=True,
                message=f"Read {len(contents)} files",
                path=", ".join(contents.keys()),
                output=contents,
                contents=contents,
            )

        # ── 单文件模式 ──────────────────────────────────────────────────────
        if not params.path:
            return FsReadOutput(
                success=False,
                message="Either 'path' (single) or 'reads' (batch) must be provided",
                path="",
            )

        item = FsReadItem(path=params.path, encoding=params.encoding, mode=params.mode)

        if ctx.dry_run:
            return FsReadOutput(success=True, message=f"[dry_run] Would read: {params.path}", path=params.path)

        ok, msg, content, size = await self._read_one(ctx, item)
        target_str = str(ctx.resolve_path(params.path))
        if ok:
            return FsReadOutput(
                success=True, message=msg, path=target_str,
                content=content, size_bytes=size, output=content,
            )
        retryable = "not found" not in msg.lower() and "not a file" not in msg.lower() and "too large" not in msg.lower() and "encoding" not in msg.lower()
        return FsReadOutput(success=False, retryable=retryable, message=msg, path=target_str)


# ── fs.write ──────────────────────────────────────────────────────────────────

class FsWriteItem(BaseModel):
    path: str = Field(..., description="File path to write")
    content: str = Field(..., description="Content to write")
    encoding: str = Field("utf-8", description="Text encoding")
    mode: str = Field("text", description="'text' or 'binary'")
    append: bool = Field(False, description="Append instead of overwrite")

    @model_validator(mode="before")
    @classmethod
    def _coerce_content_to_str(cls, values: Any) -> Any:
        """Auto-coerce dict/list content to JSON string.

        Planner often passes structured data (e.g. python.run output dict)
        directly to fs.write's content field. Instead of failing with a
        ValidationError, serialize it to a pretty-printed JSON string.
        """
        import json as _json
        if isinstance(values, dict):
            raw = values.get("content")
            if isinstance(raw, (dict, list)):
                values["content"] = _json.dumps(raw, ensure_ascii=False, indent=2)
        return values

class FsWriteInput(SkillInput):
    # 单文件模式
    path: Optional[str] = Field(None, description="File path to write (single-file mode)")
    content: Optional[str] = Field(None, description="Content to write (single-file mode)")
    encoding: str = Field("utf-8", description="Text encoding")
    mode: str = Field("text", description="'text' or 'binary'")
    append: bool = Field(False, description="Append instead of overwrite")
    # batch 模式：writes=[{"path":..., "content":..., "encoding":..., "mode":..., "append":...}, ...]
    writes: Optional[List[FsWriteItem]] = Field(None, description="Batch write: list of {path, content, encoding?, mode?, append?}")

    @model_validator(mode="before")
    @classmethod
    def _coerce_content_to_str(cls, values: Any) -> Any:
        """Auto-coerce dict/list content to JSON string (single-file mode)."""
        import json as _json
        if isinstance(values, dict):
            raw = values.get("content")
            if isinstance(raw, (dict, list)):
                values["content"] = _json.dumps(raw, ensure_ascii=False, indent=2)
        return values

class FsWriteOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Written file path (single) or comma-separated paths (batch)")
    path: str = Field("", description="Written file path")
    bytes_written: Optional[int] = None
    written_count: Optional[int] = None  # batch 模式写入文件数

@register_skill
class FsWriteSkill(BaseSkill[FsWriteInput, FsWriteOutput]):
    spec = SkillSpec(
        name="fs.write",
        description=(
            f"Write content to file(s) (max {MAX_FILE_SIZE_MB}MB each). 写入文件内容。\n"
            "Single-file mode: {\"path\": \"file.txt\", \"content\": \"hello\"}\n"
            "Batch mode (write multiple files in ONE step): {\"writes\": [{\"path\": \"a.txt\", \"content\": \"...\"}, {\"path\": \"b.txt\", \"content\": \"...\"}]}\n"
            "Use batch mode whenever writing more than one file — do NOT call fs.write N times in a loop."
        ),
        input_model=FsWriteInput,
        output_model=FsWriteOutput,
        side_effects={SideEffect.FS},
        risk_level=SkillRiskLevel.WRITE,
        aliases=["write_file", "file.write", "save_file", "fs.write_file"],
        tags=["save", "write", "file", "保存", "写入", "文件", "存储", "创建"],
        dedup_mode="skip",
        output_contract=SkillOutputContract(value_kind=ValueKind.PATH, transport_mode=TransportMode.REF),
    )

    async def _write_one(self, ctx: SkillContext, item: FsWriteItem) -> tuple[bool, str, int]:
        """写单个文件，返回 (success, message, bytes_written)"""
        target = ctx.resolve_path(item.path)
        try:
            if item.mode == "binary":
                hex_str = "".join(item.content.split())
                content_bytes = bytes.fromhex(hex_str)
            else:
                # 强制 UTF-8 写入，避免 Windows 默认编码 (GBK/CP936) 导致后续读取失败
                write_encoding = "utf-8"
                content_bytes = item.content.encode(write_encoding)

            if len(content_bytes) > MAX_FILE_SIZE_BYTES:
                return False, f"Content too large for {item.path}", 0

            target.parent.mkdir(parents=True, exist_ok=True)

            if item.append:
                if item.mode == "binary":
                    with open(target, "ab") as f:
                        f.write(content_bytes)
                else:
                    with open(target, "a", encoding="utf-8") as f:
                        f.write(item.content)
            else:
                if item.mode == "binary":
                    target.write_bytes(content_bytes)
                else:
                    target.write_text(item.content, encoding="utf-8")

            return True, str(target), len(content_bytes)
        except Exception as e:
            return False, str(e), 0

    async def run(self, ctx: SkillContext, params: FsWriteInput) -> FsWriteOutput:
        # ── batch 模式 ──────────────────────────────────────────────────────
        if params.writes:
            if ctx.dry_run:
                paths = [w.path for w in params.writes]
                return FsWriteOutput(
                    success=True,
                    message=f"[dry_run] Would write {len(paths)} files",
                    path=", ".join(paths),
                    output=", ".join(paths),
                    written_count=len(paths),
                )
            results = []
            total_bytes = 0
            failed = []
            for item in params.writes:
                ok, msg, nbytes = await self._write_one(ctx, item)
                if ok:
                    results.append(msg)  # msg = str(target) 绝对路径，与单文件模式一致
                    total_bytes += nbytes
                else:
                    failed.append(f"{item.path}: {msg}")

            if failed:
                return FsWriteOutput(
                    success=False,
                    message=f"Batch write partial failure: {'; '.join(failed)}",
                    path=", ".join(results),
                    output=", ".join(results) if results else None,
                    written_count=len(results),
                )
            paths_str = ", ".join(results)
            return FsWriteOutput(
                success=True,
                message=f"Written {len(results)} files ({total_bytes} bytes total)",
                path=paths_str,
                output=paths_str,
                written_count=len(results),
                bytes_written=total_bytes,
            )

        # ── 单文件模式 ──────────────────────────────────────────────────────
        if not params.path or params.content is None:
            return FsWriteOutput(
                success=False,
                message="Either 'path'+'content' (single) or 'writes' (batch) must be provided",
                path="",
            )

        item = FsWriteItem(
            path=params.path,
            content=params.content,
            encoding=params.encoding,
            mode=params.mode,
            append=params.append,
        )

        if ctx.dry_run:
            return FsWriteOutput(
                success=True,
                message=f"[dry_run] Would write: {params.path}",
                path=params.path,
                output=params.path,
            )

        ok, msg, nbytes = await self._write_one(ctx, item)
        if ok:
            return FsWriteOutput(
                success=True,
                message=f"Written {nbytes} bytes",
                path=msg,
                bytes_written=nbytes,
                output=msg,
            )
        return FsWriteOutput(success=False, message=msg, path=params.path or "")


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
        tags=["list", "ls", "dir", "列出", "目录", "浏览"],
        output_contract=SkillOutputContract(value_kind=ValueKind.JSON, transport_mode=TransportMode.INLINE),
    )

    async def run(self, ctx: SkillContext, params: FsListInput) -> FsListOutput:
        target = ctx.resolve_path(params.path)

        if ctx.dry_run:
            return FsListOutput(success=True, message=f"[dry_run] Would list: {target}", path=str(target), output=[])

        if not target.exists():
            return FsListOutput(success=False, retryable=False, message=f"Not found: {target}", path=str(target))
        if not target.is_dir():
            return FsListOutput(success=False, retryable=False, message=f"Not a directory: {target}", path=str(target))

        try:
            items, total_files, total_dirs = [], 0, 0
            iterator = target.rglob("*") if params.recursive else target.iterdir()
            # Use workspace-root-relative paths so planner can directly
            # construct /workspace/{item.path} without guessing.
            rel_base = ctx.base_path if ctx.base_path else target
            for p in iterator:
                try:
                    item_path = p.relative_to(rel_base).as_posix()
                except ValueError:
                    # Fallback: if path is outside workspace root, use target-relative
                    item_path = p.relative_to(target).as_posix()
                item = FsListItem(name=p.name, path=item_path, is_dir=p.is_dir())
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
        tags=["delete", "remove", "删除", "移除"],
        dedup_mode="skip",
        output_contract=SkillOutputContract(value_kind=ValueKind.PATH, transport_mode=TransportMode.REF),
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
        tags=["move", "rename", "移动", "重命名"],
        dedup_mode="skip",
        output_contract=SkillOutputContract(value_kind=ValueKind.PATH, transport_mode=TransportMode.REF),
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
        tags=["copy", "复制", "备份"],
        dedup_mode="skip",
        output_contract=SkillOutputContract(value_kind=ValueKind.PATH, transport_mode=TransportMode.REF),
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
