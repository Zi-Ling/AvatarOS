# app/avatar/perception/speech/asr.py
"""
ASR (Automatic Speech Recognition) - 语音识别

使用 Whisper 模型（OpenAI）
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False


class ASREngine:
    """
    ASR 语音识别引擎（单例模式）
    
    特点：
    - 懒加载：首次调用时才加载模型
    - 单例：应用生命周期内只加载一次
    - 线程安全：使用锁保护模型加载和推理
    
    使用示例：
    ```python
    asr = ASREngine()
    asr.load_model("base", device="cpu")
    
    result = asr.transcribe("audio.mp3", language="zh")
    print(result["text"])
    ```
    """
    
    _instance: Optional[ASREngine] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        # 避免重复初始化
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self._model = None
        self._model_lock = threading.Lock()
        self._model_path: Optional[Path] = None
        self._device: Optional[str] = None
        self._compute_type: Optional[str] = None
    
    def load_model(
        self,
        model_path: str | Path,
        device: str = "auto",
        compute_type: str = "int8",
    ) -> None:
        """
        加载 Whisper 模型
        
        Args:
            model_path: 模型路径或模型名称
                - "tiny": 最快，精度较低
                - "base": 平衡（推荐）
                - "small": 较好精度
                - "medium": 高精度
                - "large": 最高精度，最慢
            device: 设备
                - "auto": 自动选择（有 CUDA 用 GPU，否则 CPU）
                - "cpu": 强制使用 CPU
                - "cuda": 强制使用 GPU
            compute_type: 计算类型
                - "int8": 8位整数（推荐，速度快）
                - "float16": 16位浮点（GPU 推荐）
                - "float32": 32位浮点（精度最高）
        
        Raises:
            RuntimeError: Whisper 不可用或加载失败
        """
        if not WHISPER_AVAILABLE:
            raise RuntimeError(
                "faster-whisper is not available. "
                "Install it with: pip install faster-whisper"
            )
        
        with self._model_lock:
            try:
                logger.info(f"Loading Whisper model: {model_path} (device={device}, compute_type={compute_type})")
                self._model = WhisperModel(
                    str(model_path),
                    device=device,
                    compute_type=compute_type,
                )
                self._model_path = Path(model_path) if isinstance(model_path, str) else model_path
                self._device = device
                self._compute_type = compute_type
                logger.info("✅ Whisper model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load Whisper model: {e}")
                raise RuntimeError(f"Failed to load Whisper model: {e}")
    
    def is_loaded(self) -> bool:
        """检查模型是否已加载"""
        return self._model is not None
    
    def transcribe(
        self,
        audio_path: str | Path,
        language: str = "zh",
        beam_size: int = 5,
        vad_filter: bool = True,
    ) -> Dict[str, Any]:
        """
        语音转文字
        
        Args:
            audio_path: 音频文件路径
            language: 语言代码
                - "zh": 中文
                - "en": 英文
                - "ja": 日文
                - "ko": 韩文
                - None: 自动检测
            beam_size: Beam search 大小（1-10，越大越准确但越慢）
            vad_filter: 是否启用 VAD（语音活动检测）过滤静音
        
        Returns:
            {
                "text": "识别的文字",
                "language": "zh",
                "language_probability": 0.95,
                "duration": 10.5,
                "segments": [...]  # 详细分段信息
            }
        
        Raises:
            RuntimeError: 模型未加载
        """
        if not self.is_loaded():
            raise RuntimeError("Model not loaded. Call load_model() first.")
        
        with self._model_lock:
            try:
                segments, info = self._model.transcribe(
                    str(audio_path),
                    language=language if language else None,
                    beam_size=beam_size,
                    vad_filter=vad_filter,
                )
                
                # 拼接所有片段
                segments_list = list(segments)
                full_text = " ".join(seg.text for seg in segments_list)
                
                return {
                    "text": full_text.strip(),
                    "language": info.language,
                    "language_probability": info.language_probability,
                    "duration": info.duration,
                    "segments": [
                        {
                            "start": seg.start,
                            "end": seg.end,
                            "text": seg.text,
                        }
                        for seg in segments_list
                    ],
                }
            except Exception as e:
                logger.error(f"Transcription failed: {e}")
                raise RuntimeError(f"Transcription failed: {e}")
    
    def get_info(self) -> Dict[str, Any]:
        """
        获取 ASR 引擎信息
        
        Returns:
            {
                "loaded": True,
                "model_path": "base",
                "device": "cpu",
                "compute_type": "int8"
            }
        """
        return {
            "loaded": self.is_loaded(),
            "model_path": str(self._model_path) if self._model_path else None,
            "device": self._device,
            "compute_type": self._compute_type,
        }
    
    def unload_model(self) -> None:
        """卸载模型（释放内存）"""
        with self._model_lock:
            if self._model is not None:
                del self._model
                self._model = None
                logger.info("Whisper model unloaded")

