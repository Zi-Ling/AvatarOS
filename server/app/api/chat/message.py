# app/api/chat/message.py
"""
聊天消息接口 — 仅包含 HTTP endpoint 定义
业务逻辑见 chat_service.py / task_executor.py
"""
import uuid
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.chat.models import ChatRequest, ChatResponse
from app.router.router import AvatarRouter
from app.core.dependencies import get_avatar_router, get_memory_manager, get_learning_manager
from app.avatar.memory.manager import MemoryManager
from app.avatar.learning.manager import LearningManager
from app.avatar.perception.vision.processor import ImageProcessor
from .session import save_message_to_session, get_session_messages
from .chat_service import (
    handle_message_with_route,
    stream_chat_response,
    update_session_last_output,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/")
async def send_message(
    request: ChatRequest,
    avatar_router: AvatarRouter = Depends(get_avatar_router),
    memory_manager: MemoryManager = Depends(get_memory_manager),
    learning_manager: LearningManager = Depends(get_learning_manager),
):
    """发送聊天消息（支持流式/非流式，支持图片 OCR）"""
    session_id = request.session_id or str(uuid.uuid4())
    
    # 处理图片附件（OCR）
    if request.images:
        request.message = _process_image_attachments(request)
    
    # 保存用户消息
    save_message_to_session(session_id, "user", request.message)
    _save_to_working_state(memory_manager, session_id, request.message)
    
    if request.stream:
        return StreamingResponse(
            stream_chat_response(
                avatar_router, request.message, session_id,
                request.enable_think, memory_manager, learning_manager,
            ),
            media_type="text/event-stream",
        )
    
    # 非流式
    reply = await handle_message_with_route(
        avatar_router, request.message, session_id,
        request.enable_think, memory_manager,
    )
    save_message_to_session(session_id, "assistant", reply)
    await update_session_last_output(memory_manager, session_id, reply)
    return ChatResponse(message=reply)


@router.post("/stop")
async def stop_session(request: ChatRequest):
    """停止指定 session 的流式输出和所有后台任务"""
    from app.api.chat.cancellation import get_cancellation_manager
    session_id = request.session_id
    if not session_id:
        return {"success": False, "message": "session_id required"}
    
    mgr = get_cancellation_manager()
    # 停止流式输出
    mgr.cancel_session(session_id)
    # 停止所有关联的后台任务
    cancelled_tasks = mgr.cancel_all_session_tasks(session_id)
    logger.info(f"[Stop] session={session_id}, cancelled_tasks={cancelled_tasks}")
    return {"success": True, "cancelled_tasks": cancelled_tasks}


def _process_image_attachments(request: ChatRequest) -> str:
    """处理图片附件，返回注入 OCR 结果后的消息"""
    image_context = ""
    processor = ImageProcessor()
    
    for idx, img in enumerate(request.images):
        try:
            result = processor.process_image(
                image_data=img.data, extract_text=True, max_size=(1920, 1080),
            )
            if result.get("text"):
                image_context += f"\n\n[图片 {idx+1} - {img.name}]\n识别的文字：\n{result['text']}\n"
            else:
                image_context += f"\n\n[图片 {idx+1} - {img.name}]\n（未识别到文字）\n"
        except Exception as e:
            logger.warning(f"Failed to process image {idx+1}: {e}")
            image_context += f"\n\n[图片 {idx+1} - {img.name}]\n（处理失败：{str(e)}）\n"
    
    return f"{request.message}\n{image_context}" if image_context else request.message


def _save_to_working_state(memory_manager: MemoryManager, session_id: str, message: str):
    """保存对话历史到 Working State（短期记忆）"""
    try:
        history = get_session_messages(session_id)
        memory_manager.set_working_state(
            key=f"conv:{session_id}:messages",
            data={
                "session_id": session_id,
                "messages": history,
                "last_user_message": message,
            },
        )
    except Exception as e:
        logger.error(f"Failed to save conversation to memory: {e}")
