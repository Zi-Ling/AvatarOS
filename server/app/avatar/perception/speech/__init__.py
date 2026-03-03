# app/avatar/perception/speech/__init__.py
"""
语音处理 (Speech Processing)

功能：
1. ASR（Automatic Speech Recognition）- 语音转文字
2. TTS（Text-to-Speech）- 文字转语音
3. 语音情感识别（未来）

推荐引擎：
- ASR: OpenAI Whisper（开源，精度高）
- TTS: Azure TTS / Google TTS / 本地 TTS
"""
from __future__ import annotations

__all__ = ["ASREngine"]

from .asr import ASREngine

