# app/api/chat/speech.py
"""
语音识别 API 路由
"""
from fastapi import APIRouter, File, UploadFile, HTTPException, Form
from pathlib import Path
import uuid
import logging

from app.api.chat.models import TranscribeResponse, SpeechModelInfoResponse
from app.avatar.perception.speech.asr import ASREngine
from app.core.config import config

logger = logging.getLogger(__name__)

router = APIRouter()

# 全局 ASR 引擎实例（单例）
asr_engine = ASREngine()


@router.post("/speech", response_model=TranscribeResponse)
async def speech_audio(
    audio: UploadFile = File(..., description="音频文件"),
    language: str = Form(default="zh", description="语言代码 (zh/en/ja等)"),
):
    """
    语音转文字接口
    
    支持格式：webm, mp4, wav, mp3, ogg 等
    """
    # 确保模型已加载
    if not asr_engine.is_loaded():
        try:
            logger.info("首次使用，正在加载 Whisper 模型...")
            asr_engine.load_model(
                model_path=config.whisper_model_path,
                device=config.whisper_device,
                compute_type=config.whisper_compute_type,
            )
            logger.info("模型加载完成")
        except Exception as e:
            logger.error(f"模型加载失败: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"语音模型加载失败: {str(e)}"
            )
    
    # 保存上传的音频文件
    temp_file_id = str(uuid.uuid4())
    # 保留原始扩展名
    file_ext = Path(audio.filename).suffix if audio.filename else ".webm"
    temp_audio_path = config.temp_audio_dir / f"{temp_file_id}{file_ext}"
    
    try:
        # 保存文件
        content = await audio.read()
        temp_audio_path.write_bytes(content)
        logger.info(f"保存临时音频: {temp_audio_path.name}, 大小: {len(content)} bytes")
        
        # 执行识别
        result = asr_engine.transcribe(
            audio_path=temp_audio_path,
            language=language,
            beam_size=config.whisper_beam_size,
            vad_filter=config.whisper_vad_filter,
        )
        
        logger.info(f"识别成功: {result['text'][:50]}...")
        
        return TranscribeResponse(
            text=result["text"],
            language=result["language"],
            language_probability=result["language_probability"],
            duration=result["duration"],
        )
        
    except Exception as e:
        logger.error(f"语音识别失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"语音识别失败: {str(e)}"
        )
    finally:
        # 清理临时文件
        if temp_audio_path.exists():
            temp_audio_path.unlink()
            logger.debug(f"删除临时文件: {temp_audio_path.name}")


@router.get("/status", response_model=SpeechModelInfoResponse)
async def get_model_status():
    """
    获取语音模型状态
    """
    info = asr_engine.get_info()
    return SpeechModelInfoResponse(**info)


@router.post("/load-model")
async def load_model():
    """
    预加载模型（可选）
    
    用于首次使用前提前加载模型，避免首次识别时等待
    """
    if asr_engine.is_loaded():
        return {"message": "模型已加载", "status": "loaded"}
    
    try:
        logger.info("开始预加载 Whisper 模型...")
        asr_engine.load_model(
            model_path=config.whisper_model_path,
            device=config.whisper_device,
            compute_type=config.whisper_compute_type,
        )
        logger.info("模型预加载完成")
        return {"message": "模型加载成功", "status": "loaded"}
    except Exception as e:
        logger.error(f"模型加载失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"模型加载失败: {str(e)}"
        )


@router.delete("/unload-model")
async def unload_model():
    """
    卸载模型（释放内存）
    
    注意：卸载后下次使用需要重新加载
    """
    if not asr_engine.is_loaded():
        return {"message": "模型未加载", "status": "unloaded"}
    
    try:
        asr_engine.unload_model()
        return {"message": "模型已卸载", "status": "unloaded"}
    except Exception as e:
        logger.error(f"模型卸载失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"模型卸载失败: {str(e)}"
        )

