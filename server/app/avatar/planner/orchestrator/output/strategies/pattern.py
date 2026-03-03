"""
模式匹配策略
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Dict

logger = logging.getLogger(__name__)


class PatternMatchStrategy:
    """
    基于模式的智能映射（通用规则）
    
    处理常见的字段命名模式，例如：
    - result_file/output_file → path
    - file_path/file_name → path
    - file_content/text_content → content
    """
    
    @staticmethod
    def extract(
        output_name: str,
        raw_output: Dict[str, Any]
    ) -> Optional[Any]:
        """
        模式匹配提取
        
        Args:
            output_name: 期望的输出字段名
            raw_output: 原始输出字典
        
        Returns:
            提取的值，如果失败返回 None
        """
        if not isinstance(raw_output, dict):
            return None
        
        expected_lower = output_name.lower()
        
        # 规则1：任何包含 "file", "path", "output" 的字段可能映射到 "path"
        if any(keyword in expected_lower for keyword in ["file", "path", "output"]):
            for actual_field in raw_output.keys():
                if actual_field.lower() == "path":
                    logger.info(
                        f"✅ Extracted '{output_name}' via pattern_match "
                        f"(rule: file/path/output → 'path')"
                    )
                    return raw_output[actual_field]
        
        # 规则2：任何包含 "content", "text", "data" 的字段可能映射到 "content"
        if any(keyword in expected_lower for keyword in ["content", "text", "data"]):
            for actual_field in raw_output.keys():
                if actual_field.lower() == "content":
                    logger.info(
                        f"✅ Extracted '{output_name}' via pattern_match "
                        f"(rule: content/text/data → 'content')"
                    )
                    return raw_output[actual_field]
        
        # 规则3：result_* 模式 → 尝试去掉 "result_" 前缀匹配
        if expected_lower.startswith("result_"):
            suffix = expected_lower[7:]  # 去掉 "result_" 前缀
            for actual_field in raw_output.keys():
                if actual_field.lower() == suffix:
                    logger.info(
                        f"✅ Extracted '{output_name}' via pattern_match "
                        f"(rule: result_* → '{actual_field}')"
                    )
                    return raw_output[actual_field]
        
        # 规则4：output_* 模式 → 尝试去掉 "output_" 前缀匹配
        if expected_lower.startswith("output_"):
            suffix = expected_lower[7:]  # 去掉 "output_" 前缀
            for actual_field in raw_output.keys():
                if actual_field.lower() == suffix:
                    logger.info(
                        f"✅ Extracted '{output_name}' via pattern_match "
                        f"(rule: output_* → '{actual_field}')"
                    )
                    return raw_output[actual_field]
        
        return None

