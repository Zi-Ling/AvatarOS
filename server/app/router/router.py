# router/router.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
import uuid
import logging
import re
import asyncio
from datetime import datetime

from .interpreter import IntentInterpreter
from .types import ChatResult, IntentResult, ErrorResult, RouterResult, RouteDecision
from .prompt import ROUTER_PROMPT, HISTORY_TEMPLATE
from .logging import RouterLogger, create_default_router_logger
from .classifier import IntentClassifier

# Use string imports if needed to avoid circular deps, but here we import classes for type hinting
from app.avatar.runtime.main import AvatarMain
from app.avatar.intent.models import IntentSpec, IntentDomain, SafetyLevel
from app.avatar.planner.composite.analyzer.complexity import ComplexityAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class LLMClient:
    """
    一个抽象的 LLM 客户端（你可以换成你的 Qwen/Ollama 调用）
    """

    def call(self, prompt: str) -> str:
        """
        你需要在这里接入 LLM 客户端。
        示例（伪代码）：
        result = ollama.chat(model="qwen2.5:8b", messages=[{"role": "user", "content": prompt}])
        return result["message"]["content"]
        """
        raise NotImplementedError("请在此对接LLM客户端")


class AvatarRouter:
    """
    Router：大模型 + IntentInterpreter + AvatarRuntime 的桥梁。
    """

    def __init__(
        self,
        runtime: AvatarMain,
        llm: LLMClient,
        memory_manager: Optional[Any] = None,
        logger: Optional[RouterLogger] = None,
        intent_compiler: Optional[Any] = None,  # IntentCompiler
    ):
        self.runtime = runtime
        self.llm = llm
        self.interpreter = IntentInterpreter()
        self.memory_manager = memory_manager
        self.logger = logger or create_default_router_logger()
        self.classifier = IntentClassifier(llm)
        self.intent_compiler = intent_compiler  # 可选的 IntentCompiler
        
        # [P1] 初始化ComplexityAnalyzer（用于复杂度判断）
        self.complexity_analyzer = ComplexityAnalyzer()

    # ---- 新版核心 API（推荐） ----

    async def route(
        self,
        user_message: str,
        history: Optional[list[dict]] = None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> RouteDecision:
        """
        统一的路由入口（新版）

        参数：
            user_message: 用户输入
            history: 历史对话记录，格式 [{"role": "user", "content": "..."}, ...]
            conversation_id: 会话 ID（用于 working state）
            user_id: 用户 ID（用于读取用户偏好）

        返回：
            RouteDecision: 包含意图类型、是否可执行、LLM解释等信息
        """

        # 0. Fast Gate (Tier-0 Router)
        # If it doesn't look like a task, return CHAT immediately.
        if not self.classifier.is_task_intent(user_message):
            return RouteDecision(
                intent_kind="chat",
                can_execute=False,
                llm_explanation="", # Empty explanation signals "Chat Only"
            )

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
        
        # 读取用户偏好（如果有）
        user_prefs = None
        if self.memory_manager and user_id:
            user_prefs = self.memory_manager.get_user_preference(user_id)
        
        # === 新增：调用 IntentCompiler（智能决策） ===
        intent_spec = await self._extract_intent_if_needed(user_message, history)

        # 技能选择交给 Planner/LLM，router 层直接放行
        is_complex = self.complexity_analyzer.is_complex_task(user_message).is_complex

        # 构造 RouteDecision
        decision = RouteDecision(
            intent_kind="task",
            task_mode="one_shot",
            can_execute=True,
            intent_spec=intent_spec,
            goal=intent_spec.goal,
            llm_explanation="",
            relevance_score=1.0,
            top_skills=[],
            route_reason="llm_planner",
            is_complex=is_complex,
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
            target="avatar" if decision.can_execute else "chat_fallback",
            intent_spec=None,  # 不再记录详细 spec
            meta={
                "can_execute": decision.can_execute,
                "relevance_score": 1.0,
                "top_skills": [],
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
        
        # 短消息 + 历史对话
        is_short_with_history = len(user_message) < 10 and history and len(history) > 0
        
        # 判断是否需要调用 IntentCompiler
        needs_extraction = has_pronoun or is_short_with_history
        
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
    
    def _check_missing_skills(self, intent_spec) -> list[str]:
        """
        检查 IntentSpec 中的技能是否都存在
        
        返回：缺失的技能列表
        """
        missing = []
        
        for step in intent_spec.steps:
            # Use Resolver via Registry to check if skill exists (handles aliases/api_name)
            if not skill_registry.get(step.skill):
                missing.append(step.skill)
        
        return missing

    # ---- 旧版 API（向后兼容） ----

    async def handle_user_message(self, user_input: str) -> str:
        """
        最终提供给聊天前端的接口：
        用户输入 -> LLM -> Router -> AvatarRuntime
        （旧版 API，建议使用 route() 方法）
        """

        # 1. 准备 Prompt（简化版，不需要技能列表）
        prompt = ROUTER_PROMPT.format(
            history_context="（无历史对话）", 
            user_input=user_input,
        )

        # 2. 调用 LLM（由你对接 Ollama Qwen 实现）
        # TODO: Make LLM call async
        llm_output = self.llm.call(prompt)

        # 3. 解析 LLM 输出
        result = self.interpreter.parse(llm_output)

        # 4. 根据类型路由
        if isinstance(result, ChatResult):
            return result.text

        if isinstance(result, IntentResult):
            # Async call here
            task = await self.runtime.run_intent(result.intent)
            return f"任务执行完成: {task.status}. \nTask ID: {task.id}"

        if isinstance(result, ErrorResult):
            return f"[Router Error] {result.error}\nRaw: {result.raw_output}"

        return "未知错误"
