# app/services/knowledge/preprocessor.py
"""文档规范化预处理器 — 第一版：txt/md/json，PDF 后续完善"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


class PreprocessError(Exception):
    """预处理失败（不可恢复）"""


class DocumentPreprocessor:
    """文档规范化预处理"""

    def preprocess(self, content: str | bytes, file_format: str) -> str:
        """
        统一预处理入口。
        - str: txt / md / json
        - bytes: pdf
        """
        if file_format == "pdf":
            if isinstance(content, str):
                content = content.encode("utf-8")
            text = self._extract_pdf_text(content)
        elif file_format == "json":
            if isinstance(content, bytes):
                content = content.decode("utf-8")
            text = self._expand_json(content)
        else:
            if isinstance(content, bytes):
                content = content.decode("utf-8")
            text = content

        text = self._normalize_whitespace(text)
        if file_format == "md":
            text = self._strip_markdown_noise(text)
        return text

    def _normalize_whitespace(self, text: str) -> str:
        """换行符统一 + 连续空白折叠"""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # 连续空行折叠为单个空行
        text = re.sub(r"\n{3,}", "\n\n", text)
        # 行内连续空格折叠
        text = re.sub(r"[^\S\n]+", " ", text)
        return text.strip()

    def _strip_markdown_noise(self, text: str) -> str:
        """
        去除图片标记、HTML 标签；保留代码块、标题层级、链接文本。
        """
        # 保护代码块：先提取，处理完再放回
        code_blocks: list[str] = []

        def _save_code(m):
            code_blocks.append(m.group(0))
            return f"\x00CODE{len(code_blocks) - 1}\x00"

        text = re.sub(r"```[\s\S]*?```", _save_code, text)
        text = re.sub(r"`[^`]+`", _save_code, text)

        # 去除图片标记 ![alt](url)
        text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
        # 保留链接文本 [text](url) → text
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
        # 去除 HTML 标签
        text = re.sub(r"<[^>]+>", "", text)

        # 恢复代码块
        for i, block in enumerate(code_blocks):
            text = text.replace(f"\x00CODE{i}\x00", block)
        return text

    def _expand_json(self, text: str) -> str:
        """
        嵌套 JSON 用 a.b.c: value 路径风格展平为可读文本。
        如果不是合法 JSON，原样返回。
        """
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text
        lines: list[str] = []
        self._flatten(data, "", lines)
        return "\n".join(lines)

    def _flatten(self, obj, prefix: str, lines: list[str]):
        if isinstance(obj, dict):
            for k, v in obj.items():
                path = f"{prefix}.{k}" if prefix else k
                self._flatten(v, path, lines)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                path = f"{prefix}[{i}]"
                self._flatten(v, path, lines)
        else:
            lines.append(f"{prefix}: {obj}")

    def _extract_pdf_text(self, pdf_bytes: bytes) -> str:
        """PDF 文本抽取 — 第一版占位，后续完善。"""
        try:
            import fitz  # pymupdf
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pages = [page.get_text() for page in doc]
            doc.close()
            text = "\n".join(pages)
            if text.strip():
                return text
        except Exception as e:
            logger.warning(f"pymupdf failed: {e}")

        try:
            import pdfplumber
            import io
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages]
            text = "\n".join(pages)
            if text.strip():
                return text
        except Exception as e:
            logger.warning(f"pdfplumber failed: {e}")

        raise PreprocessError("PDF extraction failed with all available parsers")
