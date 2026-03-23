# app/llm/base.py
from abc import ABC, abstractmethod
from typing import List, Optional, Iterator, Dict, Any, Tuple
import json
import uuid
import logging
import httpx

from app.llm.types import LLMMessage, LLMConfig, LLMResponse, LLMRole, ToolCall
from app.llm.logging import LLMLogger, NullLLMLogger
from app.avatar.runtime.recovery.retry import retry_with_backoff, RetryConfig

logger = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    """
    Base class for all LLM providers.
    Provides unified interface + shared helpers for logging, message conversion,
    tool_calls parsing, etc.
    """

    def __init__(self, config: LLMConfig, llm_logger: Optional[LLMLogger] = None):
        self.config = config
        self.logger = llm_logger or NullLLMLogger()

        self.retry_config = RetryConfig(
            max_attempts=3,
            base_delay=1.0,
            max_delay=10.0,
            exponential_base=2.0,
            retryable_exceptions=(ConnectionError, TimeoutError, OSError, httpx.TransportError),
        )

    # ── Shared helpers ──

    @staticmethod
    def _convert_messages(messages: List[LLMMessage]) -> List[Dict[str, Any]]:
        """Convert LLMMessage list to OpenAI-style dicts.
        
        支持 multimodal content：如果 msg.content 是合法 JSON 数组，
        则作为 content parts 传递（OpenAI vision 格式）。
        """
        result = []
        for msg in messages:
            content = msg.content
            # 检测 multimodal content（JSON 数组格式）
            if content.startswith("["):
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, list):
                        content = parsed  # 保持为 list，OpenAI API 接受
                except (json.JSONDecodeError, ValueError):
                    pass  # 保持原始字符串
            result.append({"role": msg.role.value, "content": content})
        return result

    @staticmethod
    def _build_tools_payload(tools: Optional[List]) -> Optional[List[Dict]]:
        """Convert ToolDefinition list to OpenAI-style tools payload."""
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    @staticmethod
    def _parse_tool_calls_from_list(raw_calls: list) -> Optional[List[ToolCall]]:
        """Parse tool_calls from OpenAI-style response (list of dicts or objects)."""
        if not raw_calls:
            return None
        result = []
        for tc in raw_calls:
            try:
                # Handle both dict (httpx) and object (openai SDK) formats
                if isinstance(tc, dict):
                    tc_id = tc.get("id", str(uuid.uuid4()))
                    func = tc.get("function", tc)
                    name = func["name"]
                    args = func.get("arguments", {})
                else:
                    tc_id = tc.id
                    name = tc.function.name
                    args = tc.function.arguments

                if isinstance(args, str):
                    args = json.loads(args)

                result.append(ToolCall(id=tc_id, name=name, arguments=args))
            except (json.JSONDecodeError, KeyError, AttributeError) as e:
                logger.error(f"Failed to parse tool call: {e}")
                continue
        return result or None

    def _log_start(self, messages: List[LLMMessage], provider: str, extra: dict = None) -> Tuple[str, str]:
        """Start LLM logging. Returns (call_id, llm_log_id)."""
        call_id = str(uuid.uuid4())
        prompt_preview = messages[-1].content[:100] if messages else ""
        params = {"base_url": self.config.base_url, "provider": provider}
        if extra:
            params.update(extra)
        llm_log_id = self.logger.on_llm_start(
            call_id=call_id,
            model=self.config.model,
            prompt=prompt_preview,
            params=params,
        )
        return call_id, llm_log_id

    def _log_end(self, llm_log_id: str, success: bool, response: str = None,
                 error: str = None, usage: dict = None):
        """End LLM logging."""
        self.logger.on_llm_end(
            llm_log_id=llm_log_id,
            success=success,
            response=response,
            error=error,
            usage=usage,
        )

    # ── Capability declaration ──

    @property
    def supports_vision(self) -> bool:
        """该 provider 是否支持多模态 vision（image_url）。子类可覆盖。"""
        return False

    # ── Abstract interface ──

    @abstractmethod
    def _chat_impl(self, messages: List[LLMMessage], tools: Optional[List] = None) -> LLMResponse:
        """Actual chat implementation (subclass must implement)."""
        raise NotImplementedError

    def chat(self, messages: List[LLMMessage], tools: Optional[List] = None) -> LLMResponse:
        """Synchronous chat completion with retry."""
        effective_tools = tools if tools is not None else getattr(self.config, "tools", None)

        @retry_with_backoff(
            config=self.retry_config,
            on_retry=lambda e, attempt, delay: logger.warning(
                f"[LLM] Retry attempt {attempt} after {type(e).__name__}: {e}"
            ),
        )
        def _chat_with_retry():
            return self._chat_impl(messages, tools=effective_tools)

        return _chat_with_retry()

    def stream_chat(self, messages: List[LLMMessage]) -> Iterator[str]:
        """Streaming chat. Default falls back to sync. Override for true streaming."""
        response = self.chat(messages)
        yield response.content

    async def chat_with_vision(self, prompt: str, image_b64: str) -> LLMResponse:
        """
        多模态视觉对话：发送文本 + 图片给 LLM。
        使用 OpenAI 兼容的 multimodal content 格式。
        如果 image_b64 为空，退化为纯文本调用。
        不支持 vision 的 provider 会抛出 NotImplementedError。
        """
        import asyncio

        if not self.supports_vision and image_b64:
            raise NotImplementedError(
                f"{self.__class__.__name__} 不支持 vision（多模态图片）。"
                f"请配置 VISION_LLM_* 环境变量指向支持 vision 的 provider（如 OpenAI）。"
            )

        if not image_b64:
            # 纯文本退化
            msg = LLMMessage(role=LLMRole.USER, content=prompt)
            return await asyncio.get_event_loop().run_in_executor(
                None, self.chat, [msg]
            )

        # 构建 multimodal 消息（OpenAI vision 格式）
        vision_message = LLMMessage(
            role=LLMRole.USER,
            content=json.dumps([
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                },
            ]),
        )
        return await asyncio.get_event_loop().run_in_executor(
            None, self.chat, [vision_message]
        )

    def call(self, prompt: str, json_schema: Optional[dict] = None) -> str:
        """Simplified interface: string in, string out."""
        from app.llm.types import LLMMessage, LLMRole

        original_schema = self.config.json_schema
        if json_schema is not None:
            self.config.json_schema = json_schema
        try:
            msg = LLMMessage(role=LLMRole.USER, content=prompt)
            response = self.chat([msg])
            return response.content
        finally:
            self.config.json_schema = original_schema

    def call_with_usage(self, prompt: str, json_schema: Optional[dict] = None) -> Tuple[str, Dict[str, Any]]:
        """Like call(), but also returns usage dict with token counts."""
        from app.llm.types import LLMMessage, LLMRole

        original_schema = self.config.json_schema
        if json_schema is not None:
            self.config.json_schema = json_schema
        try:
            msg = LLMMessage(role=LLMRole.USER, content=prompt)
            response = self.chat([msg])
            return response.content, (response.usage or {})
        finally:
            self.config.json_schema = original_schema
