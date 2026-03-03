# server/app/router/interpreter.py
from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional

from .types import ChatResult, IntentResult, ErrorResult, RouterResult, RouteDecision
from app.avatar.intent import IntentSpec
from app.avatar.intent.models import IntentDomain, SafetyLevel

class IntentInterpreter:
    """
    负责把大模型输出的 JSON 文本解析成 RouterResult。
    支持两种情况：
    1. 纯 JSON 字符串
    2. 前后有思考/解释文本，最后一段是 JSON（例如带 <think>...</think>）
    """

    @staticmethod
    def _fix_invalid_escapes(json_str: str) -> str:
        def replace_slash(match):
            s = match.group(0)
            if s in ('\\"', '\\\\', '\\/', '\\b', '\\f', '\\n', '\\r', '\\t'):
                return s
            if s.startswith('\\u'): 
                return s
            return s.replace('\\', '\\\\')
        return re.sub(r'\\.', replace_slash, json_str)

    @staticmethod
    def _extract_json_block(text: str) -> str | None:
        stripped = text.strip()
        if "```json" in stripped:
            start = stripped.find("```json") + 7
            end = stripped.find("```", start)
            if end != -1:
                stripped = stripped[start:end].strip()
        elif "```" in stripped:
            start = stripped.find("```") + 3
            end = stripped.find("```", start)
            if end != -1:
                stripped = stripped[start:end].strip()
        
        brace_count = 0
        start_idx = -1
        json_candidate = None
        
        for i, char in enumerate(stripped):
            if char == "{":
                if brace_count == 0:
                    start_idx = i
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0 and start_idx != -1:
                    json_candidate = stripped[start_idx : i + 1]
        
        if json_candidate:
            return json_candidate
        
        start_idx = stripped.rfind("{")
        if start_idx == -1:
            return None
        candidate = stripped[start_idx:]
        if not candidate.endswith("}"):
            return None
        return candidate

    @staticmethod
    def _extract_think_block(text: str) -> str:
        match = re.search(r'<think>(.*?)</think>', text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    def parse_route_decision(self, text: str) -> RouteDecision:
        text = text.strip()
        think_process = self._extract_think_block(text)
        
        def safe_load(s: str) -> Dict:
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                fixed = self._fix_invalid_escapes(s)
                return json.loads(fixed)

        # Pre-clean: Extract JSON if text doesn't start with {
        cleaned_text = text
        if not text.startswith('{'):
            # Try to find the first { and last }
            start = text.find('{')
            if start != -1:
                end = text.rfind('}')
                if end != -1 and end > start:
                    cleaned_text = text[start:end+1]

        data = None
        try:
            data = safe_load(cleaned_text)
        except Exception:
            pass
            
        if data is None:
            json_block = self._extract_json_block(text)
            if json_block:
                try:
                    data = safe_load(json_block)
                except Exception as e:
                    return RouteDecision(
                        intent_kind="chat",
                        llm_explanation=f"❌ JSON 格式错误: {str(e)}\n\n提取的内容：{json_block[:200]}",
                        raw_llm_output=text,
                        think_process=think_process,
                    )
            else:
                return RouteDecision(
                    intent_kind="chat",
                    llm_explanation=f"❌ 解析错误：LLM 返回了无效的 JSON\n\n原始输出：{text[:200]}",
                    raw_llm_output=text,
                    think_process=think_process,
                )
        
        if not isinstance(data, dict):
            return RouteDecision(
                intent_kind="chat",
                llm_explanation="❌ 解析错误：LLM 输出格式不正确",
                raw_llm_output=text,
                think_process=think_process,
            )
        
        # Try to get intent_kind from multiple possible field names (LLM might use different names)
        intent_kind = data.get("intent_kind") or data.get("classification") or data.get("intent") or "chat"
        # Normalize to lowercase
        intent_kind = str(intent_kind).lower().strip()
        if intent_kind not in ["chat", "task"]:
            intent_kind = "chat"
        
        # Try to get task_mode from multiple possible field names
        task_mode = data.get("task_mode") or data.get("mode") or "none"
        task_mode = str(task_mode).lower().strip()
        # Map common variations
        if task_mode in ["one_shot", "oneshot", "single"]:
            task_mode = "one_shot"
        elif task_mode in ["recurring", "repeat", "scheduled"]:
            task_mode = "recurring"
        elif task_mode not in ["one_shot", "recurring"]:
            task_mode = "none"
        
        can_execute = bool(data.get("can_execute", False))
        llm_explanation = data.get("llm_explanation", "")
        missing_skills = data.get("missing_skills", [])
        goal = data.get("goal", "")
        
        return RouteDecision(
            intent_kind=intent_kind,
            task_mode=task_mode,
            can_execute=can_execute,
            goal=goal, # New V2 field
            intent_spec=None, # No longer parsing complex intent_spec in Router
            llm_explanation=llm_explanation,
            missing_skills=missing_skills if isinstance(missing_skills, list) else [],
            raw_llm_output=text,
            think_process=think_process,
        )

    # --------- 旧版解析入口（保留以防万一，但功能已废弃） ---------

    def parse(self, text: str) -> RouterResult:
        # Legacy method implementation removed to force V2 usage
        return self.parse_route_decision(text) # Fallback? No, types mismatch.
        # Just return Error if called unexpectedly
        return ErrorResult(error="Legacy parse() called. Please use parse_route_decision()", raw_output=text)

    # --------- 辅助方法 ---------

    def _build_intent_from_dict(self, data: Dict[str, Any]) -> IntentSpec:
        # Deprecated helper
        return IntentSpec(id="deprecated", goal="deprecated", intent_type="deprecated", domain=IntentDomain.OTHER)
