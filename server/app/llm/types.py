from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class LLMRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class LLMMessage:
    role: LLMRole
    content: str
    name: Optional[str] = None  # For tool calls
    tool_call_id: Optional[str] = None  # For tool results


@dataclass
class ToolDefinition:
    """OpenAI 标准格式的工具定义"""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema


@dataclass
class ToolCall:
    """LLM 返回的工具调用"""
    id: str  # 调用ID
    name: str  # 工具名
    arguments: Dict[str, Any]  # 解析后的参数


@dataclass
class LLMConfig:
    provider: str  # "openai", "ollama", "anthropic"
    model: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    
    # Generation parameters
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    top_p: float = 1.0
    stream: bool = False
    
    # Structured Output (JSON Schema)
    json_schema: Optional[Dict[str, Any]] = None  # JSON Schema for constrained generation
    
    # Tool Calling
    tools: Optional[List[ToolDefinition]] = None  # 可用工具列表
    
    # Advanced
    timeout: int = 60
    extra_headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str
    role: LLMRole = LLMRole.ASSISTANT
    usage: Optional[Dict[str, int]] = None  # prompt_tokens, completion_tokens, etc.
    finish_reason: Optional[str] = None
    model_name: Optional[str] = None  # Actual model name used
    tool_calls: Optional[List[ToolCall]] = None  # 工具调用列表

