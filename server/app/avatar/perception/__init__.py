# app/avatar/perception/__init__.py
"""
感知层 (Perception Layer)

拟人化设计：
- 视觉感知：OCR 文字识别、图像理解
- 听觉感知：语音识别、TTS 语音合成
- 上下文感知：时间、地理位置、环境（未来）

架构：
👁️ Perception (感知) → 🧠 Cognition (认知) → 🤲 Action (行动)
"""
from __future__ import annotations

__all__ = ["OCREngine", "ImageProcessor"]

# 延迟导入，避免循环依赖
def get_ocr_engine():
    from .ocr.engine import OCREngine
    return OCREngine

def get_image_processor():
    from .vision.processor import ImageProcessor
    return ImageProcessor
