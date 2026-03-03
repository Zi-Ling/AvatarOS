# app/llm/base.py
from abc import ABC, abstractmethod
from typing import List, Optional, Iterator, Dict, Any, Tuple
import json
import uuid
import logging

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
            retryable_exceptions=(ConnectionError, TimeoutError, OSError),
        )

    # ── Shared helpers ──

    @staticmethod
    def _convert_messages(messages: List[LLMMessage]) -> List[Dict[str, str]]:
        """Convert LLMMessage list to OpenAI-style dicts."""
        return [{"role": msg.role.value, "content": msg.content} for msg in messages]

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
