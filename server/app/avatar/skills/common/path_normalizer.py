"""
Planner utility functions
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Set, Optional

logger = logging.getLogger(__name__)


def normalize_file_extension(
    path_str: str,
    default_ext: str,
    allowed_exts: Optional[Set[str]] = None,
    strict_allowed: bool = True
) -> str:
    """
    通用文件后缀规范化工具
    
    Args:
        path_str: 原始文件路径
        default_ext: 默认后缀（如果原始路径没有后缀），例如 ".docx"
        allowed_exts: 允许的后缀集合，例如 {".docx", ".doc"}
        strict_allowed: 是否强制使用 allowed_exts。
                        True: 如果后缀不在 allowed_exts 中，强制改为 default_ext
                        False: 仅记录警告，允许非常规后缀
    
    Returns:
        str: 规范化后的文件路径
    """
    p = Path(path_str)
    
    # 1. 无后缀：自动补全
    if not p.suffix:
        p = p.with_suffix(default_ext)
        logger.debug(f"Auto-appended extension '{default_ext}' to '{path_str}' -> '{p.name}'")
        return str(p)
        
    # 2. 有后缀：检查是否合规
    if allowed_exts:
        current_ext = p.suffix.lower()
        if current_ext not in allowed_exts:
            if strict_allowed:
                # 强制修正
                old_name = p.name
                p = p.with_suffix(default_ext)
                logger.warning(
                    f"Normalized extension for '{old_name}': '{current_ext}' not in {allowed_exts}, "
                    f"forced to '{default_ext}' -> '{p.name}'"
                )
            else:
                # 宽松模式：仅警告
                logger.debug(
                    f"Non-standard extension detected: '{current_ext}' (expected one of {allowed_exts}). "
                    f"Proceeding as requested."
                )
    
    return str(p)
