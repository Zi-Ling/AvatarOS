# app/api/chat/chat_service.py
"""
聊天业务逻辑：路由决策、RAG 检索、流式/非流式响应生成
"""
import asyncio
import logging
from typing import AsyncGenerator

from app.api.chat.models import StreamChunk
from app.router.router import AvatarRouter
from app.avatar.memory.manager import MemoryManager
from app.avatar.learning.manager import LearningManager
from app.avatar.runtime.core import SessionContext
from .session import get_session_messages
from .executor import execute_task

logger = logging.getLogger(__name__)


async def update_session_last_output(memory_manager: MemoryManager, session_id: str, content: str):
    """保存最后输出到 SessionContext"""
    if not memory_manager:
        return
    try:
        session_data = memory_manager.get_session_context(session_id)
        if session_data:
            session_ctx = SessionContext.from_dict(session_data)
        else:
            session_ctx = SessionContext.create(session_id=session_id)
        session_ctx.set_variable("last_output", content)
        memory_manager.save_session_context(session_ctx)
    except Exception as e:
        logger.warning(f"Failed to update SessionContext: {e}")


def _build_history_for_llm(session_id: str) -> list[dict]:
    """从 session 获取历史对话，排除最后一条（刚保存的用户消息）"""
    history = get_session_messages(session_id)
    result = []
    for msg in history[:-1]:
        entry = {"role": msg["role"], "content": msg["content"]}
        if "metadata" in msg:
            entry["metadata"] = msg["metadata"]
        result.append(entry)
    return result


def _build_think_prefix(enable_think: bool, decision) -> str:
    """构建思考过程前缀"""
    if enable_think and decision.think_process:
        return f"> **Thinking Process:**\n> {decision.think_process.replace(chr(10), chr(10) + '> ')}\n\n---\n\n"
    return ""


async def handle_message_with_route(
    avatar_router: AvatarRouter,
    user_message: str,
    session_id: str,
    enable_think: bool = False,
    memory_manager: MemoryManager = None,
) -> str:
    """非流式消息处理 — 统一管道，所有消息走 Planner pipeline"""
    history_for_llm = _build_history_for_llm(session_id)
    
    decision = await avatar_router.route(
        user_message, history_for_llm, session_id, None,
    )
    
    prefix_content = _build_think_prefix(enable_think, decision)

    # All messages go to Planner pipeline (tool calling decides chat vs task)
    asyncio.create_task(
        execute_task(
            avatar_router, decision, user_message,
            session_id, prefix_content, history_for_llm, memory_manager,
        )
    )
    return f"{prefix_content}"


async def stream_chat_response(
    avatar_router: AvatarRouter,
    user_input: str,
    session_id: str,
    enable_think: bool = False,
    memory_manager: MemoryManager = None,
    learning_manager: LearningManager = None,
) -> AsyncGenerator[str, None]:
    """流式响应生成器 — 统一管道。

    所有消息走 Planner pipeline（tool calling 模式）。
    Planner 自行决定是直接回复（FINISH）还是调用 tool（执行 skill）。
    不再有 Scenario A/B 分支。
    """
    from app.api.chat.cancellation import get_cancellation_manager
    
    cancellation_mgr = get_cancellation_manager()
    cancel_event = cancellation_mgr.register_session(session_id)
    
    try:
        history_for_llm = _build_history_for_llm(session_id)
        decision = await avatar_router.route(user_input, history_for_llm, session_id, None)
        
        prefix_content = _build_think_prefix(enable_think, decision)
        if prefix_content:
            yield f"data: {StreamChunk(content=prefix_content, done=False, session_id=session_id).model_dump_json()}\n\n"

        # ── Unified Pipeline: all messages go to Planner ──────────────
        # Planner uses tool calling to decide: call tool → task, text reply → chat.
        # Frontend shows typing indicator while waiting for socket events:
        #   - plan.generated → upgrades to execution block UI (task mode)
        #   - chat.direct_reply → replaces with chat message (Planner FINISH)
        asyncio.create_task(
            execute_task(
                avatar_router, decision, user_input,
                session_id, "", history_for_llm, memory_manager,
            )
        )
        
        # SSE stream ends immediately — real content comes via Socket events.
        # Don't save anything to session here; execute_task handles it.
        yield f"data: {StreamChunk(content='', done=True, session_id=session_id).model_dump_json()}\n\n"
        
    except Exception as e:
        yield f"data: {StreamChunk(content=f'\\n\\n❌ 错误: {str(e)}', done=True, session_id=session_id).model_dump_json()}\n\n"
    finally:
        cancellation_mgr.unregister_session(session_id)
