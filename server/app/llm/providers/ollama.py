# app/llm/providers/ollama.py
"""
Ollama API adapter (direct HTTP via httpx).
"""
import httpx
import json
from typing import List, Iterator, Optional

from app.llm.base import BaseLLMClient
from app.llm.types import LLMMessage, LLMResponse, LLMRole


class OllamaClient(BaseLLMClient):

    def _build_url(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/api/chat"

    def _build_payload(self, messages: list, tools=None, stream=False) -> dict:
        options = {
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
        }
        if self.config.max_tokens is not None:
            options["num_predict"] = self.config.max_tokens

        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": stream,
            "options": options,
        }

        tools_payload = self._build_tools_payload(tools)
        if tools_payload:
            payload["tools"] = tools_payload

        if self.config.json_schema:
            payload["format"] = "json"

        return payload

    def _chat_impl(self, messages: List[LLMMessage], tools: Optional[List] = None) -> LLMResponse:
        api_messages = self._convert_messages(messages)
        _, llm_log_id = self._log_start(messages, "ollama")

        try:
            payload = self._build_payload(api_messages, tools, stream=False)
            timeout = self.config.timeout or 120

            with httpx.Client(timeout=timeout) as client:
                resp = client.post(self._build_url(), json=payload)
                resp.raise_for_status()
                data = resp.json()

            message = data["message"]
            content = message.get("content", "")
            tool_calls = self._parse_tool_calls_from_list(message.get("tool_calls"))

            usage = {}
            if "prompt_eval_count" in data:
                usage["prompt_tokens"] = data["prompt_eval_count"]
            if "eval_count" in data:
                usage["completion_tokens"] = data["eval_count"]
                usage["total_tokens"] = usage.get("prompt_tokens", 0) + data["eval_count"]

            self._log_end(llm_log_id, success=True, response=content, usage=usage)

            return LLMResponse(
                content=content,
                role=LLMRole.ASSISTANT,
                usage=usage,
                model_name=data.get("model", self.config.model),
                finish_reason=data.get("done_reason", "stop"),
                tool_calls=tool_calls,
            )

        except Exception as e:
            self._log_end(llm_log_id, success=False, error=str(e))
            raise

    def stream_chat(self, messages: List[LLMMessage]) -> Iterator[str]:
        api_messages = self._convert_messages(messages)
        _, llm_log_id = self._log_start(messages, "ollama", {"stream": True})
        full_content = ""

        try:
            payload = self._build_payload(api_messages, stream=True)
            with httpx.Client(timeout=self.config.timeout or 120) as client:
                with client.stream("POST", self._build_url(), json=payload) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            if chunk.get("done", False):
                                continue
                            msg_content = chunk.get("message", {}).get("content")
                            if msg_content:
                                full_content += msg_content
                                yield msg_content
                        except json.JSONDecodeError:
                            continue

            self._log_end(llm_log_id, success=True, response=full_content)
        except Exception as e:
            self._log_end(llm_log_id, success=False, error=str(e))
            raise
