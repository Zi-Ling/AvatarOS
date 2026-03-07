# app/api/chat/chat_service.py
"""
聊天业务逻辑：路由决策、RAG 检索、流式/非流式响应生成
"""
import asyncio
import logging
from typing import AsyncGenerator

from starlette.concurrency import iterate_in_threadpool

from app.api.chat.models import StreamChunk
from app.intent_router.router import AvatarRouter
from app.llm.types import LLMMessage, LLMRole
from app.avatar.memory.manager import MemoryManager
from app.avatar.learning.manager import LearningManager
from app.avatar.runtime.core import SessionContext
from .session import save_message_to_session, get_session_messages
from .task_executor import execute_task, generate_capability_explanation

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
    return [
        {"role": msg["role"], "content": msg["content"]}
        for msg in history[:-1]
    ]


def _convert_to_llm_messages(chat_messages: list[dict]) -> list[LLMMessage]:
    """将 dict 格式的消息转换为 LLMMessage 对象"""
    llm_msgs = []
    for msg in chat_messages:
        role_val = msg.get("role", "user")
        try:
            if hasattr(role_val, "value"):
                role_enum = role_val
            else:
                role_enum = LLMRole(role_val)
        except ValueError:
            role_enum = LLMRole.USER
        llm_msgs.append(LLMMessage(role=role_enum, content=msg.get("content", "")))
    return llm_msgs


def _build_think_prefix(enable_think: bool, decision) -> str:
    """构建思考过程前缀"""
    if enable_think and decision.think_process:
        return f"> **Thinking Process:**\n> {decision.think_process.replace(chr(10), chr(10) + '> ')}\n\n---\n\n"
    return ""


def _retrieve_rag_context(learning_manager, user_input: str) -> str:
    """从文档知识库检索 RAG 上下文"""
    if not learning_manager or not learning_manager.has_document_kb():
        return ""
    
    try:
        relevant_docs = learning_manager.document_kb.search(query=user_input, n_results=3)
        if not relevant_docs:
            return ""
        
        logger.debug(f"Retrieved {len(relevant_docs)} relevant document chunks for RAG")
        rag_context = "\n\n## 📚 相关文档内容（参考）：\n"
        for i, doc in enumerate(relevant_docs, 1):
            doc_name = doc["metadata"].get("doc_name", "Unknown")
            content = doc["content"]
            if len(content) > 500:
                content = content[:500] + "..."
            rag_context += f"\n### 文档 {i}: {doc_name}\n{content}\n"
        rag_context += "\n(提示：如果用户的问题与上述文档相关，请引用文档内容回答。如果无关，请忽略。)\n\n"
        return rag_context
    except Exception as e:
        logger.warning(f"Failed to retrieve RAG context: {e}")
        return ""


def _inject_rag_into_messages(llm_msgs: list[LLMMessage], rag_context: str):
    """将 RAG 上下文注入到最后一条用户消息"""
    if not rag_context or not llm_msgs:
        return
    for i in range(len(llm_msgs) - 1, -1, -1):
        if llm_msgs[i].role == LLMRole.USER:
            llm_msgs[i].content = rag_context + llm_msgs[i].content
            break


async def handle_message_with_route(
    avatar_router: AvatarRouter,
    user_message: str,
    session_id: str,
    enable_think: bool = False,
    memory_manager: MemoryManager = None,
) -> str:
    """非流式消息处理：路由决策 → 聊天/任务分支"""
    history_for_llm = _build_history_for_llm(session_id)
    
    decision = await avatar_router.route(
        user_message, history_for_llm, session_id, None,
    )
    
    prefix_content = _build_think_prefix(enable_think, decision)

    if decision.intent_kind == "chat":
        response_text = decision.llm_explanation
        if not response_text:
            chat_messages = history_for_llm + [{"role": "user", "content": user_message}]
            try:
                llm_msgs = _convert_to_llm_messages(chat_messages)
                llm_response = await asyncio.to_thread(avatar_router.llm.chat, llm_msgs)
                response_text = llm_response.content
            except Exception as e:
                response_text = f"抱歉，生成回复时出错: {str(e)}"
        return prefix_content + response_text
    
    elif decision.intent_kind == "task":
        confirm_msg = "⚙️ 正在规划任务..."
        
        asyncio.create_task(
            execute_task(
                avatar_router, decision, user_message,
                session_id, prefix_content, history_for_llm, memory_manager,
            )
        )
        return f"{prefix_content}{confirm_msg}"
    
    else:
        return f"{prefix_content}❓ 抱歉，我无法理解你的请求。"


async def stream_chat_response(
    avatar_router: AvatarRouter,
    user_input: str,
    session_id: str,
    enable_think: bool = False,
    memory_manager: MemoryManager = None,
    learning_manager: LearningManager = None,
) -> AsyncGenerator[str, None]:
    """流式响应生成器"""
    from app.api.chat.cancellation import get_cancellation_manager
    
    cancellation_mgr = get_cancellation_manager()
    cancel_event = cancellation_mgr.register_session(session_id)
    
    try:
        history_for_llm = _build_history_for_llm(session_id)
        decision = await avatar_router.route(user_input, history_for_llm, session_id, None)
        
        prefix_content = _build_think_prefix(enable_think, decision)
        if prefix_content:
            yield f"data: {StreamChunk(content=prefix_content, done=False, session_id=session_id).model_dump_json()}\n\n"
        
        full_response_content = prefix_content

        # [Scenario A] Fast Gate → Chat (True Streaming)
        if decision.intent_kind == "chat" and not decision.llm_explanation:
            chat_messages = history_for_llm + [{"role": "user", "content": user_input}]
            
            rag_context = _retrieve_rag_context(learning_manager, user_input)
            llm_msgs = _convert_to_llm_messages(chat_messages)
            _inject_rag_into_messages(llm_msgs, rag_context)
            
            try:
                async for chunk_text in iterate_in_threadpool(avatar_router.llm.stream_chat(llm_msgs)):
                    if cancel_event.is_set():
                        logger.info(f"[StreamChat] 检测到取消信号 (session: {session_id})")
                        cancelled_msg = "\n\n_[已停止]_"
                        full_response_content += cancelled_msg
                        yield f"data: {StreamChunk(content=cancelled_msg, done=False, session_id=session_id).model_dump_json()}\n\n"
                        break
                    if chunk_text:
                        full_response_content += chunk_text
                        yield f"data: {StreamChunk(content=chunk_text, done=False, session_id=session_id).model_dump_json()}\n\n"
            except Exception as e:
                error_msg = f"\n\n❌ 流式生成出错: {str(e)}"
                full_response_content += error_msg
                yield f"data: {StreamChunk(content=error_msg, done=False, session_id=session_id).model_dump_json()}\n\n"

        # [Scenario B] Task Execution → Async Command Pattern
        else:
            if decision.intent_kind == "chat":
                # Legacy slow chat path (fake stream)
                result_text = decision.llm_explanation
                full_response_content += result_text
                chunk_size = 5
                for i in range(0, len(result_text), chunk_size):
                    chunk_text = result_text[i:i + chunk_size]
                    yield f"data: {StreamChunk(content=chunk_text, done=False, session_id=session_id).model_dump_json()}\n\n"
                    await asyncio.sleep(0.02)
            else:
                # TASK MODE: Fire-and-Forget
                confirm_msg = "⚙️ 正在规划任务..."
                full_response_content += confirm_msg
                yield f"data: {StreamChunk(content=confirm_msg, done=False, session_id=session_id).model_dump_json()}\n\n"
                
                asyncio.create_task(
                    execute_task(
                        avatar_router, decision, user_input,
                        session_id, "", history_for_llm, memory_manager,
                    )
                )
        
        # 保存完整回复
        save_message_to_session(session_id, "assistant", full_response_content)
        await update_session_last_output(memory_manager, session_id, full_response_content)
        
        yield f"data: {StreamChunk(content='', done=True, session_id=session_id).model_dump_json()}\n\n"
        
    except Exception as e:
        yield f"data: {StreamChunk(content=f'\\n\\n❌ 错误: {str(e)}', done=True, session_id=session_id).model_dump_json()}\n\n"
    finally:
        cancellation_mgr.unregister_session(session_id)
