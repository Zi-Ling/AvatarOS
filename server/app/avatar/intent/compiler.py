# app/avatar/intent/compiler.py
from __future__ import annotations

import json
import uuid
import logging
import re
from typing import Any, Dict, List, Optional

from .models import IntentSpec, IntentDomain, SafetyLevel

logger = logging.getLogger(__name__)

SIMPLIFIED_INTENT_PROMPT = """You are an Intent Resolver.
Your ONLY job is to:
1. Resolve pronouns/references in the user's message
2. Classify domain and safety level
3. Preserve the complete user goal

Recent Chat History:
{history}

User Input: "{user_input}"

TASK 1: Resolve Pronouns
- If the user mentions "it", "that", "this", "上面", "刚才" etc., find what they refer to in the history
- Replace pronouns with actual content from history

TASK 2: Classify Domain (粗分类)
- file: File/folder operations
- web: Web browsing/scraping
- code: Code execution/calculation/data processing
- other: Everything else (default)

TASK 3: Classify Safety Level
- read_only: Only reading/viewing data
- modify: Creating/editing files or data (default)
- destructive: Deleting or overwriting data

Output JSON ONLY:
{{
  "goal": "Complete user goal with resolved references",
  "domain": "file|web|code|other",
  "safety_level": "read_only|modify|destructive"
}}

CRITICAL: Keep "goal" complete and natural. Do NOT simplify or abbreviate.

Examples:

History: assistant: "def hello(): print('hi')"
User: "把它保存到 test.py"
Output: {{"goal": "保存代码 def hello(): print('hi') 到文件 test.py", "domain": "file", "safety_level": "modify"}}

User: "帮我写一篇作文 要求标题段落 500字左右"
Output: {{"goal": "帮我写一篇作文 要求标题段落 500字左右", "domain": "other", "safety_level": "read_only"}}

User: "计算 123 * 456"
Output: {{"goal": "计算 123 * 456", "domain": "code", "safety_level": "read_only"}}
"""

class IntentExtractor:
    """
    Extracts structured IntentSpec from natural language user request.
    """
    def __init__(self, llm_client: Any):
        self.llm = llm_client

    async def extract(self, user_request: str, history: List[Dict[str, str]] = None) -> IntentSpec:
        """
        简化版意图提取：只负责代词消解和粗分类
        """
        # Format history (最多3条)
        history_str = ""
        if history:
            history_lines = []
            for msg in history[-3:]:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                role_name = "user" if role == "user" else "assistant"
                history_lines.append(f"{role_name}: {content}")
            history_str = "\n".join(history_lines)
        else:
            history_str = "(无历史对话)"
        
        # 构建简化 prompt
        prompt = SIMPLIFIED_INTENT_PROMPT.format(
            history=history_str,
            user_input=user_request
        )
        
        try:
            # Call LLM (同步)
            if hasattr(self.llm, "call"):
                raw_resp = self.llm.call(prompt)
            elif hasattr(self.llm, "generate"):
                raw_resp = self.llm.generate(prompt)
            elif callable(self.llm):
                raw_resp = self.llm(prompt)
            else:
                raise TypeError("LLM client is not callable")
            
            logger.debug(f"[IntentCompiler] LLM response: {raw_resp[:200]}")
            
            # 解析 JSON
            data = self._parse_json(raw_resp)
            
            # 只提取 goal、domain、safety_level
            domain_str = data.get("domain", "other").lower()
            domain = self._parse_domain(domain_str)
            
            safety_str = data.get("safety_level", "modify").lower()
            safety = self._parse_safety(safety_str)
            
            goal = data.get("goal", user_request)
            
            logger.info(f"[IntentCompiler] Extracted: goal='{goal[:50]}...', domain={domain.value}, safety={safety.value}")
            
            return IntentSpec(
                id=str(uuid.uuid4()),
                goal=goal,
                intent_type="task",  # 固定为 task（Router 已经判断过了）
                domain=domain,
                safety_level=safety,
                raw_user_input=user_request,
                metadata={"source": "intent_compiler_simplified"}
            )
        
        except Exception as e:
            logger.error(f"[IntentCompiler] Extraction failed: {e}")
            # 降级：返回原始 goal
            return IntentSpec(
                id=str(uuid.uuid4()),
                goal=user_request,
                intent_type="task",
                domain=IntentDomain.OTHER,
                safety_level=SafetyLevel.MODIFY,
                raw_user_input=user_request,
                metadata={"error": str(e), "source": "fallback"}
            )
    
    def _parse_domain(self, domain_str: str) -> IntentDomain:
        """解析 domain 字符串"""
        domain_str = domain_str.upper()
        try:
            return IntentDomain[domain_str]
        except KeyError:
            logger.warning(f"Unknown domain: {domain_str}, using OTHER")
            return IntentDomain.OTHER
    
    def _parse_safety(self, safety_str: str) -> SafetyLevel:
        """解析 safety_level 字符串"""
        # 转换为枚举名称格式
        safety_map = {
            "read_only": "READ_ONLY",
            "modify": "MODIFY",
            "destructive": "DESTRUCTIVE"
        }
        
        safety_enum_name = safety_map.get(safety_str.lower(), "MODIFY")
        
        try:
            return SafetyLevel[safety_enum_name]
        except KeyError:
            logger.warning(f"Unknown safety level: {safety_str}, using MODIFY")
            return SafetyLevel.MODIFY

    def _parse_json(self, text: str) -> Dict[str, Any]:
        text = text.strip()
        
        # Remove <think> blocks (for reasoning models)
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        
        # Handle markdown blocks
        if "```" in text:
            match = re.search(r'```(?:json)?(.*?)```', text, re.DOTALL)
            if match:
                text = match.group(1).strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
            
        # Aggressive search for { ... }
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = text[start:end]
                return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            pass
            
        # Last resort: Fix common JSON errors (e.g. single quotes)
        try:
            fixed_text = text.replace("'", '"') # Very risky but sometimes works
            start = fixed_text.find("{")
            end = fixed_text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(fixed_text[start:end])
        except:
            pass

        raise ValueError(f"Could not parse JSON from LLM output: {text[:100]}...")
