# app/avatar/perception/vision/processor.py
"""
图片处理器

功能：
1. 图片格式转换
2. 图片压缩（减少传输大小）
3. 图片预处理（去噪、二值化等）
4. 集成 OCR 识别
"""
from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from ..ocr.engine import OCREngine

logger = logging.getLogger(__name__)


class ImageProcessor:
    """
    图片处理器
    
    使用示例：
    ```python
    processor = ImageProcessor()
    
    # 处理图片并提取文字
    result = processor.process_image(
        image_data=base64_data,
        extract_text=True,
        max_size=(1920, 1080)
    )
    
    print(result["text"])  # OCR 识别的文字
    print(result["width"], result["height"])  # 图片尺寸
    ```
    """
    
    def __init__(self, ocr_engine: Optional[OCREngine] = None):
        """
        初始化图片处理器
        
        Args:
            ocr_engine: OCR 引擎（可选，默认创建新实例）
        """
        self._ocr = ocr_engine or OCREngine()
    
    def process_image(
        self, 
        image_data: bytes | str,
        *,
        extract_text: bool = True,
        max_size: Tuple[int, int] = (1920, 1080),
        quality: int = 85,
    ) -> Dict[str, any]:
        """
        处理图片
        
        Args:
            image_data: 图片数据（bytes 或 Base64 字符串）
            extract_text: 是否提取文字（需要 OCR 引擎）
            max_size: 最大尺寸（宽, 高），超过会自动压缩
            quality: JPEG 质量（1-100）
        
        Returns:
            {
                "width": 1920,
                "height": 1080,
                "format": "PNG",
                "size_bytes": 123456,
                "text": "识别的文字（如果 extract_text=True）",
                "text_regions": [...],  # OCR 详细结果
                "base64": "...",  # 处理后的图片（Base64）
            }
        
        Raises:
            RuntimeError: PIL 不可用
        """
        if not PIL_AVAILABLE:
            raise RuntimeError("PIL is not available. Install it with: pip install Pillow")
        
        # 解码图片
        if isinstance(image_data, str):
            # Base64 字符串
            image_bytes = base64.b64decode(image_data)
        else:
            image_bytes = image_data
        
        image = Image.open(BytesIO(image_bytes))
        original_size = (image.width, image.height)
        
        # 压缩图片（如果太大）
        if image.width > max_size[0] or image.height > max_size[1]:
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
            logger.debug(f"Resized image: {original_size} → {(image.width, image.height)}")
        
        # 转换为 RGB（如果是 RGBA）
        if image.mode == "RGBA":
            # 创建白色背景
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[3])  # 使用 alpha 通道作为 mask
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")
        
        # 保存为 Base64（PNG 格式，无损）
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        base64_data = base64.b64encode(buffer.getvalue()).decode()
        
        result = {
            "width": image.width,
            "height": image.height,
            "format": "PNG",
            "size_bytes": len(buffer.getvalue()),
            "base64": base64_data,
        }
        
        # OCR 识别
        if extract_text and self._ocr.is_available():
            try:
                text_regions = self._ocr.recognize_base64(base64_data)
                result["text_regions"] = text_regions
                result["text"] = "\n".join(r["text"] for r in text_regions)
                
                if text_regions:
                    logger.debug(f"OCR extracted {len(text_regions)} text regions")
                else:
                    logger.debug("OCR found no text in image")
            except Exception as e:
                logger.warning(f"OCR failed: {e}")
                result["text"] = ""
                result["text_regions"] = []
        elif extract_text and not self._ocr.is_available():
            logger.debug("OCR requested but engine not available")
            result["text"] = ""
            result["text_regions"] = []
        
        return result
    
    def compress_image(
        self,
        image_data: bytes | str,
        *,
        max_size: Tuple[int, int] = (1920, 1080),
        quality: int = 85,
        format: str = "JPEG",
    ) -> str:
        """
        压缩图片（返回 Base64）
        
        Args:
            image_data: 图片数据
            max_size: 最大尺寸
            quality: 质量（1-100）
            format: 输出格式（JPEG/PNG）
        
        Returns:
            Base64 编码的压缩图片
        """
        if not PIL_AVAILABLE:
            raise RuntimeError("PIL is not available")
        
        # 解码图片
        if isinstance(image_data, str):
            image_bytes = base64.b64decode(image_data)
        else:
            image_bytes = image_data
        
        image = Image.open(BytesIO(image_bytes))
        
        # 压缩
        if image.width > max_size[0] or image.height > max_size[1]:
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # 转换格式
        if format.upper() == "JPEG" and image.mode != "RGB":
            image = image.convert("RGB")
        
        # 保存
        buffer = BytesIO()
        image.save(buffer, format=format.upper(), quality=quality)
        return base64.b64encode(buffer.getvalue()).decode()
    
    def get_image_info(self, image_data: bytes | str) -> Dict[str, any]:
        """
        获取图片信息（不处理）
        
        Args:
            image_data: 图片数据
        
        Returns:
            {
                "width": 1920,
                "height": 1080,
                "format": "PNG",
                "mode": "RGB",
                "size_bytes": 123456
            }
        """
        if not PIL_AVAILABLE:
            raise RuntimeError("PIL is not available")
        
        # 解码图片
        if isinstance(image_data, str):
            image_bytes = base64.b64decode(image_data)
        else:
            image_bytes = image_data
        
        image = Image.open(BytesIO(image_bytes))
        
        return {
            "width": image.width,
            "height": image.height,
            "format": image.format or "Unknown",
            "mode": image.mode,
            "size_bytes": len(image_bytes),
        }

