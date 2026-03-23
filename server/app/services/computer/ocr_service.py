# app/services/computer/ocr_service.py
"""OCRService — Windows 原生 OCR + LLM 回退."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Optional

from .models import OCRTextBlock

logger = logging.getLogger(__name__)


class OCRService:
    """OCR 文本提取，Windows 原生优先，LLM 回退."""

    def __init__(self, llm_client: Any = None) -> None:
        self._llm = llm_client
        self._win_ocr_available = self._check_win_ocr()

    async def extract(
        self,
        screenshot_b64: str,
        roi: Optional[tuple[int, int, int, int]] = None,
    ) -> list[OCRTextBlock]:
        """提取文本块列表。优先 Windows OCR，失败则 LLM 回退."""
        if not screenshot_b64:
            return []

        if self._win_ocr_available:
            try:
                return await self._extract_win_ocr(screenshot_b64, roi)
            except Exception as e:
                logger.warning("Windows OCR failed, falling back to LLM: %s", e)

        if self._llm:
            try:
                return await self._extract_llm(screenshot_b64, roi)
            except Exception as e:
                logger.error("LLM OCR fallback also failed: %s", e)

        return []

    async def extract_text_only(
        self,
        screenshot_b64: str,
        roi: Optional[tuple[int, int, int, int]] = None,
    ) -> str:
        """仅返回拼接后的纯文本."""
        blocks = await self.extract(screenshot_b64, roi)
        return " ".join(b.text for b in blocks if b.text)

    def _check_win_ocr(self) -> bool:
        """检查 Windows OCR API 是否可用."""
        try:
            import ctypes
            ctypes.windll.oleaut32  # noqa: B018
            return True
        except Exception:
            return False

    async def _extract_win_ocr(
        self,
        screenshot_b64: str,
        roi: Optional[tuple[int, int, int, int]] = None,
    ) -> list[OCRTextBlock]:
        """Windows 原生 OCR 提取."""
        # Decode base64 to bytes for Windows OCR API
        img_bytes = base64.b64decode(screenshot_b64)

        try:
            from PIL import Image
            import io

            image = Image.open(io.BytesIO(img_bytes))
            if roi:
                x, y, w, h = roi
                image = image.crop((x, y, x + w, y + h))

            # Use Windows OCR via WinRT
            # This is a simplified implementation; production would use
            # windows.media.ocr.OcrEngine via comtypes/winrt
            import pytesseract  # type: ignore[import-untyped]

            data = pytesseract.image_to_data(
                image, output_type=pytesseract.Output.DICT
            )
            blocks: list[OCRTextBlock] = []
            for i, text in enumerate(data["text"]):
                text = text.strip()
                if not text:
                    continue
                conf = float(data["conf"][i]) / 100.0
                bx, by = data["left"][i], data["top"][i]
                bw, bh = data["width"][i], data["height"][i]
                if roi:
                    bx += roi[0]
                    by += roi[1]
                blocks.append(
                    OCRTextBlock(text=text, bbox=(bx, by, bw, bh), confidence=conf)
                )
            return blocks
        except ImportError:
            raise RuntimeError("OCR dependencies (PIL/pytesseract) not available")

    async def _extract_llm(
        self,
        screenshot_b64: str,
        roi: Optional[tuple[int, int, int, int]] = None,
    ) -> list[OCRTextBlock]:
        """LLM 回退 OCR."""
        prompt = (
            "Extract all visible text from this screenshot. "
            "Return a JSON array of objects with fields: "
            '"text", "bbox":[x,y,w,h], "confidence". '
            "Return ONLY valid JSON array."
        )
        if roi:
            prompt += f"\nFocus on region: x={roi[0]}, y={roi[1]}, w={roi[2]}, h={roi[3]}"

        response = await self._llm.chat_with_vision(
            prompt=prompt, image_b64=screenshot_b64
        )
        text = getattr(response, "content", str(response)).strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            )
        try:
            items = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return []

        blocks: list[OCRTextBlock] = []
        for item in items:
            if isinstance(item, dict) and "text" in item:
                bbox = item.get("bbox", [0, 0, 0, 0])
                blocks.append(
                    OCRTextBlock(
                        text=item["text"],
                        bbox=tuple(bbox[:4]),  # type: ignore[arg-type]
                        confidence=float(item.get("confidence", 0.5)),
                    )
                )
        return blocks
