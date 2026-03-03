# app/avatar/perception/ocr/__init__.py
"""
OCR (Optical Character Recognition) - 光学字符识别

支持：
1. PaddleOCR（推荐，精度高，支持中文）
2. Tesseract（通用，降级方案）
"""
from __future__ import annotations

__all__ = ["OCREngine"]

