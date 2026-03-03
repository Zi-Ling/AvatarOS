# app/avatar/perception/ocr/engine.py
"""
OCR 引擎封装

优先级：
1. PaddleOCR（推荐）- 精度高，支持中文/英文，支持旋转文字
2. Tesseract（降级）- 通用 OCR 引擎（未来实现）
"""
from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    from paddleocr import PaddleOCR
    PADDLEOCR_AVAILABLE = True
except ImportError:
    PADDLEOCR_AVAILABLE = False

import logging

logger = logging.getLogger(__name__)


class OCREngine:
    """
    OCR 识别引擎
    
    使用示例：
    ```python
    ocr = OCREngine(lang="ch", use_gpu=False)
    
    # 识别图片文件
    results = ocr.recognize("screenshot.png")
    
    # 识别 Base64 图片
    text = ocr.extract_text_base64(base64_data)
    ```
    """
    
    def __init__(self, use_gpu: bool = False, lang: str = "ch"):
        """
        初始化 OCR 引擎
        
        Args:
            use_gpu: 是否使用 GPU 加速（需要 CUDA 支持）
            lang: 语言代码
                - "ch": 中文 + 英文（推荐）
                - "en": 仅英文
                - "japan": 日文
                - "korean": 韩文
        """
        self._ocr = None
        self._engine_type = None
        self._lang = lang
        self._use_gpu = use_gpu
        
        # 尝试初始化 PaddleOCR
        if PADDLEOCR_AVAILABLE:
            try:
                self._ocr = PaddleOCR(
                    use_angle_cls=True,  # 支持旋转文字识别
                    lang=lang,
                    use_gpu=use_gpu,
                    show_log=False,
                )
                self._engine_type = "PaddleOCR"
                logger.info(f"OCR engine initialized: PaddleOCR (lang={lang}, gpu={use_gpu})")
            except Exception as e:
                logger.error(f"Failed to initialize PaddleOCR: {e}")
        
        # 降级到 Tesseract（未来实现）
        if self._ocr is None:
            logger.warning("No OCR engine available. Install PaddleOCR: pip install paddleocr")
            self._engine_type = None
    
    def is_available(self) -> bool:
        """检查 OCR 引擎是否可用"""
        return self._ocr is not None
    
    def recognize(self, image_path: str | Path) -> List[Dict[str, any]]:
        """
        识别图片中的文字
        
        Args:
            image_path: 图片路径
        
        Returns:
            识别结果列表：
            [
                {
                    "text": "识别的文字",
                    "confidence": 0.95,
                    "bbox": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
                },
                ...
            ]
        
        Raises:
            RuntimeError: OCR 引擎不可用
        """
        if not self.is_available():
            raise RuntimeError("OCR Engine is not available. Install PaddleOCR first.")
        
        if self._engine_type == "PaddleOCR":
            return self._recognize_paddleocr(image_path)
        
        raise RuntimeError("No OCR engine available")
    
    def _recognize_paddleocr(self, image_path: str | Path) -> List[Dict[str, any]]:
        """使用 PaddleOCR 识别"""
        result = self._ocr.ocr(str(image_path), cls=True)
        
        if not result or not result[0]:
            return []
        
        # 转换为统一格式
        recognized_texts = []
        for line in result[0]:
            bbox = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            text_info = line[1]  # (text, confidence)
            
            recognized_texts.append({
                "text": text_info[0],
                "confidence": float(text_info[1]),
                "bbox": bbox,
            })
        
        return recognized_texts
    
    def recognize_base64(self, base64_data: str) -> List[Dict[str, any]]:
        """
        识别 Base64 编码的图片
        
        Args:
            base64_data: Base64 编码的图片数据
        
        Returns:
            识别结果列表
        
        Raises:
            RuntimeError: PIL 不可用或 OCR 引擎不可用
        """
        if not PIL_AVAILABLE:
            raise RuntimeError("PIL is not available. Install it with: pip install Pillow")
        
        # 解码 Base64
        image_data = base64.b64decode(base64_data)
        image = Image.open(BytesIO(image_data))
        
        # 保存到临时文件
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            image.save(tmp.name)
            tmp_path = tmp.name
        
        try:
            return self.recognize(tmp_path)
        finally:
            # 清理临时文件
            Path(tmp_path).unlink(missing_ok=True)
    
    def extract_text(self, image_path: str | Path) -> str:
        """
        提取图片中的所有文字（拼接成字符串）
        
        Args:
            image_path: 图片路径
        
        Returns:
            拼接后的文字（按从上到下顺序）
        """
        results = self.recognize(image_path)
        
        if not results:
            return ""
        
        # 按 Y 坐标排序（从上到下）
        results.sort(key=lambda x: x["bbox"][0][1])
        
        # 拼接文字
        texts = [r["text"] for r in results]
        return "\n".join(texts)
    
    def extract_text_base64(self, base64_data: str) -> str:
        """
        从 Base64 图片提取文字
        
        Args:
            base64_data: Base64 编码的图片数据
        
        Returns:
            拼接后的文字
        """
        results = self.recognize_base64(base64_data)
        
        if not results:
            return ""
        
        results.sort(key=lambda x: x["bbox"][0][1])
        texts = [r["text"] for r in results]
        return "\n".join(texts)
    
    def get_info(self) -> Dict[str, any]:
        """
        获取 OCR 引擎信息
        
        Returns:
            {
                "engine": "PaddleOCR",
                "available": True,
                "lang": "ch",
                "use_gpu": False
            }
        """
        return {
            "engine": self._engine_type or "None",
            "available": self.is_available(),
            "lang": self._lang,
            "use_gpu": self._use_gpu,
        }

