# app/avatar/skills/builtin/pdf.py

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional

from pydantic import Field, model_validator
from PyPDF2 import PdfReader, PdfWriter

from ..common.path_normalizer import normalize_file_extension
from ..common.path_mixins import PathBindMixin

from ..base import (
    BaseSkill, SkillSpec, SkillCategory, SkillPermission,
    SkillMetadata, SkillDomain, SkillCapability
)
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext

logger = logging.getLogger(__name__)


# ============================================================================
# pdf.read_text
# ============================================================================

class PdfReadTextInput(PathBindMixin, SkillInput):
    # relative_path 可以允许为空，因为有可能完全靠 abs_path 驱动
    relative_path: str | None = Field(None, description="Relative PDF file path (relative to base_path).")
    max_pages: int = Field(50, description="Max pages to extract.")
    abs_path: str | None = Field(None, description="Absolute file path. If provided, takes precedence.")


class PdfReadTextOutput(SkillOutput):
    path: Optional[str] = None
    pages_extracted: int = 0
    text: str = ""


@register_skill
class PdfReadTextSkill(BaseSkill[PdfReadTextInput, PdfReadTextOutput]):
    spec = SkillSpec(
        name="pdf.read_text",
        api_name="pdf.read_text",
        aliases=["pdf.extract_text", "pdf.text", "read_pdf"],
        description="Extract text from a PDF file. 从PDF文件提取文本内容。",
        category=SkillCategory.OFFICE,
        input_model=PdfReadTextInput,
        output_model=PdfReadTextOutput,

        meta=SkillMetadata(
            domain=SkillDomain.OFFICE,
            capabilities={SkillCapability.READ},
            risk_level="normal",
            file_extensions=[".pdf"]
        ),

        synonyms=[
            "read pdf",
            "extract pdf text",
            "parse pdf",
            "读取PDF",
            "提取PDF文本",
            "解析PDF"
        ],
        examples=[
            {"description": "Extract text from PDF", "params": {"relative_path": "document.pdf"}}
        ],
        permissions=[SkillPermission(name="file_read", description="Read PDF files")],
        tags=["office", "pdf", "read", "PDF", "提取", "读取", "文本"]
    )

    async def run(self, ctx: SkillContext, params: PdfReadTextInput) -> PdfReadTextOutput:
        # 1. 优先使用 abs_path
        if params.abs_path:
            target_path = Path(params.abs_path)
        # 2. 否则使用 relative_path
        elif params.relative_path:
            target_path = ctx.resolve_path(params.relative_path)
        # 3. 如果都没有，报错
        else:
            return PdfReadTextOutput(success=False, message="No valid path provided (neither relative_path nor abs_path).")

        if ctx.dry_run:
            return PdfReadTextOutput(
                success=True,
                message=f"[dry_run] Would read PDF: {target_path}",
                path=str(target_path),
                pages_extracted=0,
                text=""
            )

        try:
            # Pre-execution validation
            if not target_path.exists():
                return PdfReadTextOutput(success=False, message=f"File not found: {target_path}", path=str(target_path), pages_extracted=0, text="")

            if not target_path.is_file():
                return PdfReadTextOutput(success=False, message=f"Path is not a file: {target_path}", path=str(target_path), pages_extracted=0, text="")

            reader = PdfReader(str(target_path))
            num_pages = min(len(reader.pages), params.max_pages)

            texts: List[str] = []
            for i in range(num_pages):
                texts.append(reader.pages[i].extract_text() or "")

            text = "\n\n".join(texts)

            # Post-execution verification
            if text is None:
                return PdfReadTextOutput(success=False, message="Verification Failed: extract_text returned None", path=str(target_path), pages_extracted=0, text="")

            return PdfReadTextOutput(
                success=True,
                message=f"Extracted {num_pages} pages",
                path=str(target_path),
                pages_extracted=num_pages,
                text=text
            )
        except Exception as e:
            return PdfReadTextOutput(success=False, message=str(e), path=str(target_path), pages_extracted=0, text="")


# ============================================================================
# pdf.write_text
# ============================================================================

class PdfWriteTextInput(PathBindMixin, SkillInput):
    relative_path: str = Field(..., description="Relative output PDF path (relative to base_path).")
    content: str = Field(..., description="Text content to write into the PDF.")

    # 可选：基础排版（不搞别名/兼容字段）
    title: Optional[str] = Field(None, description="Optional title (first line, larger font).")
    font_size: int = Field(12, description="Body font size.")
    title_font_size: int = Field(16, description="Title font size.")
    margin_left: int = Field(50, description="Left margin in points.")
    margin_top: int = Field(50, description="Top margin in points.")
    line_height: int = Field(18, description="Line height in points.")
    page_size: str = Field("A4", description="Page size: A4 or LETTER.")
    font_path: Optional[str] = Field(None, description="Optional local font file path (.ttf/.otf) for CJK/Unicode.")

    @model_validator(mode="after")
    def normalize_ext(self):
        self.relative_path = normalize_file_extension(
            self.relative_path,
            default_ext=".pdf",
            allowed_exts={".pdf"},
            strict_allowed=False
        )
        # 参数防御
        self.font_size = max(6, min(int(self.font_size), 48))
        self.title_font_size = max(self.font_size, min(int(self.title_font_size), 72))
        self.line_height = max(int(self.font_size) + 2, int(self.line_height))
        return self


class PdfWriteTextOutput(SkillOutput):
    path: Optional[str] = None
    pages_written: int = 0


@register_skill
class PdfWriteTextSkill(BaseSkill[PdfWriteTextInput, PdfWriteTextOutput]):
    spec = SkillSpec(
        name="pdf.write_text",
        api_name="pdf.write_text",
        aliases=["pdf.create", "pdf.write", "create_pdf"],
        description="Write plain text content to a PDF file (create or overwrite). 将文本写入并生成PDF文件。",
        category=SkillCategory.OFFICE,
        input_model=PdfWriteTextInput,
        output_model=PdfWriteTextOutput,

        meta=SkillMetadata(
            domain=SkillDomain.OFFICE,
            capabilities={SkillCapability.WRITE, SkillCapability.CREATE},
            risk_level="normal",
            file_extensions=[".pdf"]
        ),

        produces_artifact=True,
        artifact_type="document:pdf",
        artifact_path_field="path",

        synonyms=[
            "create pdf",
            "write pdf",
            "save as pdf",
            "pdf from text",
            "生成PDF",
            "写入PDF",
            "保存为PDF",
            "把文字保存到PDF"
        ],
        examples=[
            {"description": "Write a poem into a PDF", "params": {"relative_path": "poem.pdf", "content": "《秋江夜泊》..."}}
        ],
        permissions=[SkillPermission(name="file_write", description="Create PDF files")],
        tags=["office", "pdf", "write", "create", "PDF", "生成", "写入"]
    )

    async def run(self, ctx: SkillContext, params: PdfWriteTextInput) -> PdfWriteTextOutput:
        output_path = ctx.resolve_path(params.relative_path)
        logger.debug(f"PdfSkill: Writing PDF to '{output_path.absolute()}' (dry_run={ctx.dry_run})")

        if ctx.dry_run:
            return PdfWriteTextOutput(
                success=True,
                message=f"[dry_run] Would write PDF: {output_path}",
                path=str(output_path),
                pages_written=1
            )

        try:
            # Lazy import
            try:
                from reportlab.pdfgen import canvas
                from reportlab.lib.pagesizes import A4, LETTER
                from reportlab.pdfbase import pdfmetrics
                from reportlab.pdfbase.ttfonts import TTFont
                from reportlab.pdfbase.pdfmetrics import stringWidth
            except Exception as e:
                return PdfWriteTextOutput(
                    success=False,
                    message=f"Missing dependency: reportlab. Install with `pip install reportlab`. Detail: {e}",
                    path=str(output_path),
                    pages_written=0
                )

            ps = (A4 if str(params.page_size).upper() == "A4" else LETTER)
            page_w, page_h = ps

            output_path.parent.mkdir(parents=True, exist_ok=True)

            c = canvas.Canvas(str(output_path), pagesize=ps)

            # Font
            font_name = "Helvetica"
            if params.font_path:
                fp = Path(params.font_path)
                if fp.exists() and fp.is_file():
                    try:
                        font_name = f"UserFont_{fp.stem}"
                        pdfmetrics.registerFont(TTFont(font_name, str(fp)))
                    except Exception:
                        font_name = "Helvetica"

            x = params.margin_left
            y = page_h - params.margin_top
            pages = 1

            def new_page():
                nonlocal y, pages
                c.showPage()
                pages += 1
                y = page_h - params.margin_top

            def wrap_line(line: str, fsize: int) -> List[str]:
                max_w = page_w - 2 * x
                buf = ""
                out: List[str] = []
                for ch in list(line):
                    cand = buf + ch
                    if stringWidth(cand, font_name, fsize) <= max_w:
                        buf = cand
                    else:
                        if buf:
                            out.append(buf)
                        buf = ch
                if buf:
                    out.append(buf)
                return out

            # Title
            if params.title:
                c.setFont(font_name, params.title_font_size)
                for ln in wrap_line(params.title, params.title_font_size):
                    if y < params.margin_top + params.line_height:
                        new_page()
                        c.setFont(font_name, params.title_font_size)
                    c.drawString(x, y, ln)
                    y -= params.line_height
                y -= int(params.line_height * 0.5)

            # Body
            c.setFont(font_name, params.font_size)
            body = params.content or ""
            for raw in body.splitlines():
                if raw.strip() == "":
                    y -= params.line_height
                    continue
                for ln in wrap_line(raw, params.font_size):
                    if y < params.margin_top + params.line_height:
                        new_page()
                        c.setFont(font_name, params.font_size)
                    c.drawString(x, y, ln)
                    y -= params.line_height

            c.save()

            # Post-Execution Validator (Strict Mode like file.write_text)
            if not output_path.exists():
                return PdfWriteTextOutput(success=False, message=f"Validator Error: PDF not found at {output_path} after write operation.")

            if output_path.stat().st_size == 0:
                return PdfWriteTextOutput(success=False, message=f"Validator Error: PDF is empty at {output_path}.")

            return PdfWriteTextOutput(
                success=True,
                message=f"PDF written: {output_path}",
                path=str(output_path),
                pages_written=pages,
                fs_operation="created",
                fs_path=params.relative_path,
                fs_type="file"
            )
        except Exception as e:
            return PdfWriteTextOutput(success=False, message=str(e))


# ============================================================================
# pdf.merge
# ============================================================================

class PdfMergeInput(SkillInput):
    relative_paths_json: str = Field(..., description="JSON array of relative PDF paths.")
    output_relative_path: str = Field(..., description="Output PDF path (relative to base_path).")

    @model_validator(mode="after")
    def normalize_ext(self):
        self.output_relative_path = normalize_file_extension(
            self.output_relative_path,
            default_ext=".pdf",
            allowed_exts={".pdf"},
            strict_allowed=False
        )
        return self


class PdfMergeOutput(SkillOutput):
    output_path: str
    inputs: List[str]


@register_skill
class PdfMergeSkill(BaseSkill[PdfMergeInput, PdfMergeOutput]):
    spec = SkillSpec(
        name="pdf.merge",
        api_name="pdf.merge",
        aliases=["pdf.combine", "merge_pdfs"],
        description="Merge multiple PDF files. 合并多个PDF文件。",
        category=SkillCategory.OFFICE,
        input_model=PdfMergeInput,
        output_model=PdfMergeOutput,

        meta=SkillMetadata(
            domain=SkillDomain.OFFICE,
            capabilities={SkillCapability.WRITE, SkillCapability.CREATE, SkillCapability.MODIFY},
            risk_level="normal",
            file_extensions=[".pdf"]
        ),

        produces_artifact=True,
        artifact_type="document:pdf",
        artifact_path_field="output_path",
        artifact_metadata={"contains_multiple": True},

        synonyms=[
            "combine pdfs",
            "merge documents",
            "join pdf files",
            "合并PDF",
            "合并文档",
            "组合PDF"
        ],
        examples=[
            {"description": "Merge PDF files", "params": {"relative_paths_json": '["a.pdf","b.pdf"]', "output_relative_path": "merged.pdf"}}
        ],
        permissions=[SkillPermission(name="file_write", description="Create PDF files")],
        tags=["office", "pdf", "merge", "PDF", "合并"]
    )

    async def run(self, ctx: SkillContext, params: PdfMergeInput) -> PdfMergeOutput:
        try:
            rel_paths = json.loads(params.relative_paths_json)
            if not isinstance(rel_paths, list):
                raise ValueError("Must be JSON array")
        except Exception as e:
            return PdfMergeOutput(success=False, message=str(e), output_path="", inputs=[])

        output_path = ctx.resolve_path(params.output_relative_path)

        if ctx.dry_run:
            return PdfMergeOutput(
                success=True,
                message="[dry_run]",
                output_path=str(output_path),
                inputs=rel_paths
            )

        try:
            writer = PdfWriter()
            for rel in rel_paths:
                p = ctx.resolve_path(rel)
                if not p.exists():
                    return PdfMergeOutput(success=False, message=f"Not found: {p}", output_path="", inputs=rel_paths)
                reader = PdfReader(str(p))
                for page in reader.pages:
                    writer.add_page(page)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("wb") as f:
                writer.write(f)

            return PdfMergeOutput(
                success=True,
                message="Merged PDFs",
                output_path=str(output_path),
                inputs=rel_paths,
                fs_operation="created",
                fs_path=params.output_relative_path,
                fs_type="file"
            )
        except Exception as e:
            return PdfMergeOutput(success=False, message=str(e), output_path=str(output_path), inputs=rel_paths)
