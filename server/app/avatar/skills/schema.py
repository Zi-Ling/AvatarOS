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
    
    # 文件系统操作元数据（用于自动刷新）
    fs_operation: Optional[str] = None  # 'created', 'modified', 'deleted'
    fs_path: Optional[str] = None  # 相对路径
    fs_type: Optional[str] = None  # 'file', 'dir'