# app/avatar/skills/schema.py

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel

class SkillInput(BaseModel):
    """
    Base class for all skill input schemas.
    Specific skills should inherit from this and define their fields.
    """
    pass

class SkillOutput(BaseModel):
    """
    Base class for all skill output schemas.
    """
    success: bool = True
    message: Optional[str] = None
    data: Optional[Any] = None
    # 语义失败时设为 False，告知 graph_executor 不要重试（重试同一操作不会有不同结果）
    retryable: Optional[bool] = None

    # 文件系统操作元数据（用于自动刷新）
    fs_operation: Optional[str] = None  # 'created', 'modified', 'deleted'
    fs_path: Optional[str] = None  # 相对路径
    fs_type: Optional[str] = None  # 'file', 'dir'

    # skill 内部 LLM 调用的 token usage（供 cost 统计收集）
    # 格式与 LLMResponse.usage 一致：{prompt_tokens, completion_tokens, total_tokens}
    llm_usage: Optional[dict] = None
    llm_model: Optional[str] = None  # 实际使用的 model name