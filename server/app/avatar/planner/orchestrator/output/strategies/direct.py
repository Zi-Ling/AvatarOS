"""
直接匹配策略
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Dict

logger = logging.getLogger(__name__)


class DirectMatchStrategy:
    """
    直接匹配策略
    
    策略：expected_output 直接存在于 raw_output
    """
    
    @staticmethod
    def extract(
        output_name: str,
        raw_output: Any
    ) -> Optional[Any]:
        """
        直接匹配提取
        
        Args:
            output_name: 期望的输出字段名
            raw_output: 原始输出
        
        Returns:
            提取的值，如果失败返回 None
        """
        # 非字典输出：直接返回
        if not isinstance(raw_output, dict):
            logger.debug(f"✅ Extracted '{output_name}' via direct_value (non-dict)")
            return raw_output
        
        # 直接匹配
        if output_name in raw_output:
            logger.info(f"✅ Extracted '{output_name}' via direct_match")
            return raw_output[output_name]
        
        return None

