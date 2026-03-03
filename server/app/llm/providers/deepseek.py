# app/llm/providers/deepseek.py
"""
DeepSeek API adapter (OpenAI-compatible, uses httpx directly).
"""
import httpx
import json
import logging
from typing import List, Iterator, Optional

from app.llm.base import BaseLLMClient
from app.llm.types import LLMMessage, LLMResponse, LLMRole

logger = logging.getLogger(__name__)


class DeepSeekClient(BaseLLMClient):

    def _build_url(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/v1/chat/completions"

    def _build_headers(self) -> dict:
        headers = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _build_payload(self, messages: list, tools=None, stream=False) -> dict:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": stream,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "top_p": self.config.top_p,
        }
        tools_payload = self._build_tools_payload(tools)
        if tools_payload:
            payload["tools"] = tools_payload

        if self.config.json_schema:
            payload["response_format"] = {"type": "json_object"}
            # DeepSeek requires "json" keyword in prompt
            last = messages[-1] if messages else None
            if last and "json" not in last["content"].lower():
                last["content"] += "\n\nPlease respond in valid JSON format."

        return {k: v for k, v in payload.items() if v is not None}

    def _chat_impl(self, messages: List[LLMMessage], tools: Optional[List] = None) -> LLMResponse:
        api_messages = self._convert_messages(messages)
        _, llm_log_id = self._log_start(messages, "deepseek")

        try:
            payload = self._build_payload(api_messages, tools, stream=False)

            # Payload size check
            payload_json = json.dumps(payload)
            if len(payload_json) > 500_000:
                logger.warning(f"[DeepSeek] Large payload: {len(payload_json)} bytes")

            timeout = self.config.timeout or 120
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(self._build_url(), json=payload, headers=self._build_headers())
                resp.raise_for_status()
                data = resp.json()

            message = data["choices"][0]["message"]
            content = message.get("content") or ""
            tool_calls = self._parse_tool_calls_from_list(message.get("tool_calls"))

            usage = {}
            if "usage" in data:
                usage = {
                    "prompt_tokens": data["usage"].get("prompt_tokens", 0),
                    "completion_tokens": data["usage"].get("completion_tokens", 0),
                    "total_tokens": data["usage"].get("total_tokens", 0),
                }

            self._log_end(llm_log_id, success=True, response=content, usage=usage)

            return LLMResponse(
                content=content,
                role=LLMRole.ASSISTANT,
                usage=usage,
                model_name=data.get("model", self.config.model),
                finish_reason=data["choices"][0].get("finish_reason", "stop"),
                tool_calls=tool_calls,
            )

        except httpx.HTTPStatusError as e:
            error_body = ""
            try:
                error_body = e.response.text[:500]
            except Exception:
                pass
            logger.error(f"[DeepSeek] HTTP {e.response.status_code}: {error_body}")
            self._log_end(llm_log_id, success=False, error=f"HTTP {e.response.status_code}: {error_body[:200]}")
            raise

        except Exception as e:
            self._log_end(llm_log_id, success=False, error=str(e))
            raise

    def stream_chat(self, messages: List[LLMMessage]) -> Iterator[str]:
        api_messages = self._convert_messages(messages)
        _, llm_log_id = self._log_start(messages, "deepseek", {"stream": True})
        full_content = ""

        try:
            payload = self._build_payload(api_messages, stream=True)
            with httpx.Client(timeout=self.config.timeout or 120) as client:
                with client.stream("POST", self._build_url(), json=payload, headers=self._build_headers()) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        line = line.strip()
                        if line.startswith("data: "):
                            line = line[6:]
                        if line == "[DONE]":
                            break
                        try:
                            chunk = json.loads(line)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            if "content" in delta:
                                full_content += delta["content"]
                                yield delta["content"]
                        except json.JSONDecodeError:
                            continue

            self._log_end(llm_log_id, success=True, response=full_content)
        except Exception as e:
            self._log_end(llm_log_id, success=False, error=str(e))
            raise
