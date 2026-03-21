# router/router.py
from __future__ import annotations

from typing import Any, Optional
import uuid
import logging
import re
import asyncio
from datetime import datetime

from .types import RouteDecision
from .logging import RouterLogger, create_default_router_logger

from app.avatar.runtime.main import AvatarMain
from app.avatar.intent.models import IntentSpec, IntentDomain, SafetyLevel

logger = logging.getLogger(__name__)


class AvatarRouter:
    """
    Router：大模型 + IntentInterpreter + AvatarRuntime 的桥梁。
    """

    def __init__(
        self,
        runtime: AvatarMain,
        memory_manager: Optional[Any] = None,
        logger: Optional[RouterLogger] = None,
        intent_compiler: Optional[Any] = None,  # IntentCompiler
    ):
        self.runtime = runtime
        self.memory_manager = memory_manager
        self.logger = logger or create_default_router_logger()
        self.intent_compiler = intent_compiler  # 可选的 IntentCompiler

    # ---- 新版核心 API（推荐） ----

    async def route(
        self,
        user_message: str,
        history: Optional[list[dict]] = None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> RouteDecision:
        """
        统一的路由入口 — 所有消息直接进 Planner pipeline。

        LLM gate 已移除。Planner 通过 LLM 原生 tool calling 自行决定：
        - 调用 tool → 执行 skill（task 模式）
        - 直接回复文本 → FINISH（chat 模式）

        这消除了 gate 的分类错误问题，也省掉了 1-2s 的额外延迟。
        """

        # 生成请求 ID 并记录请求开始
        request_id = str(uuid.uuid4())
        self.logger.on_request_start(
            request_id=request_id,
            input_text=user_message,
            meta={
                "conversation_id": conversation_id,
                "user_id": user_id,
                "has_history": bool(history),
            },
        )
        
        # 记录当前会话状态到 Working State
        if self.memory_manager and conversation_id:
            self.memory_manager.set_working_state(
                key=f"conv:{conversation_id}:current",
                data={
                    "user_message": user_message,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
        
        # ── 所有消息统一走 Planner pipeline ─────────────────────────────
        # Planner 通过 tool calling 自行决定是回复还是执行 skill。
        # 不再需要 _lightweight_intent_gate。
        intent_spec = await self._extract_intent_if_needed(user_message, history)

        decision = RouteDecision(
            intent_kind="task",
            task_mode="one_shot",
            can_execute=True,
            intent_spec=intent_spec,
            goal=intent_spec.goal,
            llm_explanation="",
            relevance_score=1.0,
            top_skills=[],
            route_reason="unified_pipeline",
            is_complex=True,
            scored_skills=[],
        )
        
        # 记录路由决策到 Working State
        if self.memory_manager and conversation_id:
            self.memory_manager.set_working_state(
                key=f"conv:{conversation_id}:last_decision",
                data={
                    "intent_kind": decision.intent_kind,
                    "can_execute": decision.can_execute,
                    "goal": decision.goal,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
        
        # 记录路由决策到日志系统
        self.logger.on_route_decision(
            request_id=request_id,
            route_type=decision.intent_kind,
            target="avatar",
            intent_spec=None,
            meta={
                "can_execute": decision.can_execute,
                "relevance_score": 1.0,
                "top_skills": [],
                "pipeline": "unified_tool_calling",
            },
        )
        
        return decision

    async def _extract_intent_if_needed(
        self, 
        user_message: str, 
        history: Optional[list[dict]] = None
    ) -> IntentSpec:
        """
        智能决策：是否需要调用 IntentCompiler
        
        判断条件：
        1. 检测到代词引用（"它"、"这个"、"那个"等）
        2. 消息很短（< 10 字）且有历史对话
        
        如果不需要，直接构造简单的 IntentSpec
        """
        # 检测代词（扩展量词引用：这首/这篇/这段/这张/这份）
        pronoun_pattern = r'(它|这个|那个|这些|那些|这样|那样|上面|刚才|之前|这首|这篇|这段|这张|这份|那首|那篇|那段)'
        has_pronoun = bool(re.search(pronoun_pattern, user_message))
        
        # 判断是否需要调用 IntentCompiler
        needs_extraction = has_pronoun
        
        if needs_extraction and self.intent_compiler:
            logger.info(f"[Router] Calling IntentCompiler for: '{user_message}'")
            try:
                # 调用 IntentCompiler（带 30 秒超时）
                intent_spec = await asyncio.wait_for(
                    self.intent_compiler.extract(user_message, history),
                    timeout=30
                )
                # 无论走哪条路，都注入 chat_history 供 Planner 使用
                intent_spec.metadata["chat_history"] = history or []
                return intent_spec
            
            except asyncio.TimeoutError:
                logger.warning(f"[Router] IntentCompiler timeout, using fallback")
                return self._create_simple_intent(user_message, history)
            
            except Exception as e:
                logger.error(f"[Router] IntentCompiler failed: {e}")
                return self._create_simple_intent(user_message, history)
        else:
            # 不需要 IntentCompiler，直接构造
            logger.debug(f"[Router] Using fast path for: '{user_message}'")
            return self._create_simple_intent(user_message, history)
    
    def _create_simple_intent(self, user_message: str, history: Optional[list[dict]] = None) -> IntentSpec:
        """
        快速构造 IntentSpec（不调用 LLM），注入 chat_history 供 Planner 使用
        """
        return IntentSpec(
            id=str(uuid.uuid4()),
            goal=user_message,
            intent_type="task",
            domain=IntentDomain.OTHER,
            raw_user_input=user_message,
            safety_level=SafetyLevel.MODIFY,
            metadata={"source": "router_fast_path", "chat_history": history or []}
        )
