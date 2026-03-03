"""
Schema 匹配策略
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Dict

logger = logging.getLogger(__name__)


class SchemaMatchStrategy:
    """
    基于 Schema 的匹配策略
    """
    
    @staticmethod
    def extract(
        output_name: str,
        raw_output: Dict[str, Any],
        output_schema: Optional[Dict] = None
    ) -> Optional[Any]:
        """
        Schema 匹配提取
        
        Args:
            output_name: 期望的输出字段名
            raw_output: 原始输出字典
            output_schema: 输出 Schema（可选）
        
        Returns:
            提取的值，如果失败返回 None
        """
        if not isinstance(raw_output, dict):
            return None
        
        if not output_schema or "properties" not in output_schema:
            return None
        
        schema_properties = output_schema["properties"]
        if output_name in schema_properties:
            # Schema 中有定义，尝试找相关字段
            for field_name in raw_output.keys():
                if field_name.lower() == output_name.lower():
                    logger.info(f"✅ Extracted '{output_name}' via schema_case_insensitive")
                    return raw_output[field_name]
        
        return None

