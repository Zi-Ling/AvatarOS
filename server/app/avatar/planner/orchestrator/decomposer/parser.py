"""
分解响应解析器
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from ...extractor import SmartJSONExtractor, JSONExtractionError

logger = logging.getLogger(__name__)


class DecomposeResponseParser:
    """
    解析 LLM 的分解响应
    
    职责：
    - 提取 JSON
    - 验证结构
    - 规范化数据
    """
    
    @staticmethod
    def parse(raw_response: str) -> List[Dict[str, Any]]:
        """
        解析 LLM 的分解响应
        
        Args:
            raw_response: LLM 原始响应
        
        Returns:
            List[Dict]: 子任务列表
        
        Raises:
            JSONExtractionError: 解析失败
        """
        # 使用现有的 SmartJSONExtractor
        parsed, is_clean = SmartJSONExtractor.extract(raw_response)
        
        if not isinstance(parsed, list):
            if isinstance(parsed, dict) and "subtasks" in parsed:
                parsed = parsed["subtasks"]
            else:
                raise JSONExtractionError("Expected a list of subtasks", raw_response[:500])
        
        # 验证并规范化每个子任务的结构
        for i, item in enumerate(parsed):
            if not isinstance(item, dict):
                raise JSONExtractionError(f"Subtask {i} is not a dict", str(item))
            
            # 【兼容性处理】允许 "description" 作为 "goal" 的替代
            if "goal" not in item:
                if "description" in item:
                    item["goal"] = item["description"]
                    logger.debug(f"Subtask {i}: mapped 'description' → 'goal'")
                else:
                    raise JSONExtractionError(
                        f"Subtask {i} missing 'goal' field (also no 'description' to fallback)",
                        str(item)
                    )
            
            # 【兼容性处理】规范化 id 为字符串
            if "id" in item and not isinstance(item["id"], str):
                original_id = item["id"]
                item["id"] = f"subtask_{original_id}"
                logger.debug(f"Subtask {i}: normalized id {original_id} → '{item['id']}'")
            
            # 【兼容性处理】处理 "output" 字段（LLM 可能返回的格式）
            if "output" in item and "expected_outputs" not in item:
                # 尝试从 output 结构推断 expected_outputs
                output_obj = item["output"]
                if isinstance(output_obj, dict):
                    if "type" in output_obj:
                        # {"type": "text"} → expected_outputs: ["text"]
                        item["expected_outputs"] = [output_obj["type"]]
                        logger.debug(f"Subtask {i}: inferred expected_outputs from output.type")
                    elif "path" in output_obj or "file_path" in output_obj:
                        item["expected_outputs"] = ["file_path"]
                    else:
                        # 使用 output 的 keys
                        item["expected_outputs"] = list(output_obj.keys())[:3]
                # 删除临时字段
                del item["output"]
            
            # 【兼容性处理】处理 "input" 字段（LLM 可能返回的格式）
            if "input" in item and "inputs" not in item:
                input_obj = item["input"]
                if isinstance(input_obj, dict) and "source" in input_obj:
                    # {"source": "subtask1.output"} → inputs: {"data": "${subtask_1.output.result}"}
                    source_ref = input_obj["source"]
                    # 简单转换：subtask1.output → ${subtask_1.output.result}
                    if "subtask" in source_ref.lower():
                        import re
                        match = re.search(r'subtask(\d+)', source_ref, re.IGNORECASE)
                        if match:
                            subtask_num = match.group(1)
                            item["inputs"] = {"data": f"${{subtask_{subtask_num}.output.text}}"}
                            logger.debug(f"Subtask {i}: converted input.source to inputs")
                else:
                    item["inputs"] = input_obj if isinstance(input_obj, dict) else {}
                del item["input"]
        
        return parsed

