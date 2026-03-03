# app/llm/providers/openai.py
"""
OpenAI-compatible API adapter (uses official openai SDK).
"""
from typing import List, Iterator, Optional

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from app.llm.base import BaseLLMClient
from app.llm.types import LLMMessage, LLMResponse, LLMRole


class OpenAIClient(BaseLLMClient):

    def __init__(self, config, llm_logger=None):
        super().__init__(config, llm_logger)
        if OpenAI is None:
            raise ImportError("Please install 'openai' package to use OpenAIClient.")
        self.client = OpenAI(
            api_key=self.config.api_key or "dummy",
            base_url=self.config.base_url,
            timeout=self.config.timeout,
        )

    def _chat_impl(self, messages: List[LLMMessage], tools: Optional[List] = None) -> LLMResponse:
        openai_messages = self._convert_messages(messages)
        _, llm_log_id = self._log_start(messages, "openai")

        try:
            api_params = {
                "model": self.config.model,
                "messages": openai_messages,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
                "top_p": self.config.top_p,
                "stream": False,
            }

            tools_payload = self._build_tools_payload(tools)
            if tools_payload:
                api_params["tools"] = tools_payload

            if self.config.json_schema:
                api_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "plan_schema",
                        "strict": True,
                        "schema": self.config.json_schema,
                    },
                }

            response = self.client.chat.completions.create(**api_params)
            choice = response.choices[0]
            content = choice.message.content or ""

            # Parse tool_calls from SDK objects
            raw_calls = getattr(choice.message, "tool_calls", None)
            tool_calls = self._parse_tool_calls_from_list(raw_calls) if raw_calls else None

            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }

            self._log_end(llm_log_id, success=True, response=content, usage=usage)

            return LLMResponse(
                content=content,
                role=LLMRole.ASSISTANT,
                usage=usage,
                model_name=response.model,
                finish_reason=choice.finish_reason,
                tool_calls=tool_calls,
            )

        except Exception as e:
            self._log_end(llm_log_id, success=False, error=str(e))
            raise

    def stream_chat(self, messages: List[LLMMessage]) -> Iterator[str]:
        openai_messages = self._convert_messages(messages)
        _, llm_log_id = self._log_start(messages, "openai", {"stream": True})
        full_content = ""

        try:
            stream = self.client.chat.completions.create(
                model=self.config.model,
                messages=openai_messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                top_p=self.config.top_p,
                stream=True,
            )
            for chunk in stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        full_content += delta.content
                        yield delta.content

            self._log_end(llm_log_id, success=True, response=full_content)
        except Exception as e:
            self._log_end(llm_log_id, success=False, error=str(e))
            raise
