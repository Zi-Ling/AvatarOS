# app/avatar/intent/compiler.py
from __future__ import annotations

import json
import uuid
import logging
import re
from typing import Any, Dict, List, Optional

from .models import IntentSpec, IntentDomain, SafetyLevel

logger = logging.getLogger(__name__)

SIMPLIFIED_INTENT_PROMPT = """You are an Intent Classifier.
Your ONLY job is to classify the domain, safety level, and extract typed slots from the user's request.

User Input: "{user_input}"

TASK: Classify Domain, Safety Level, and extract typed slots.

Domain:
- file: File/folder operations
- web: Web browsing/scraping
- code: Code execution/calculation/data processing
- other: Everything else (default)

Safety Level:
- read_only: Only reading/viewing data
- modify: Creating/editing files or data (default)
- destructive: Deleting or overwriting data

Typed Slots (extract only explicit file paths from the user input, otherwise omit):
- file_path: An explicit file path or filename mentioned (e.g. "test.txt", "/home/user/doc.md")
- target_path: The destination path for save/copy/move operations

IMPORTANT: Do NOT extract "content" — content always comes from conversation history, never from the current request.

Output JSON ONLY:
{{
  "domain": "file|web|code|other",
  "safety_level": "read_only|modify|destructive",
  "slots": {{
    "file_path": "...",
    "target_path": "..."
  }}
}}

Rules for slots:
- Only include a slot key if the value is clearly present in the user input as a literal path/filename
- Do NOT infer or hallucinate slot values
- Do NOT extract pronouns or references like "this file", "that poem", "它", "这首诗" as slot values
- Short continuation phrases like "还有txt", "再来个json", "also txt", "and csv too" are NOT file paths — they mean "repeat the previous task in a different format". Leave slots empty for these.
- Bare format names (txt, json, csv, md, xlsx, png) without a directory path are NOT file paths — they are format requests. Leave slots empty.

Examples:

User: "把它保存到 test.py"
Output: {{"domain": "file", "safety_level": "modify", "slots": {{"file_path": "test.py"}}}}

User: "把这首诗保存到本地文件中"
Output: {{"domain": "file", "safety_level": "modify", "slots": {{}}}}

User: "帮我写一篇作文 要求标题段落 500字左右"
Output: {{"domain": "other", "safety_level": "read_only", "slots": {{}}}}

User: "计算 123 * 456"
Output: {{"domain": "code", "safety_level": "read_only", "slots": {{}}}}

User: "把 hello world 写入 output.txt"
Output: {{"domain": "file", "safety_level": "modify", "slots": {{"file_path": "output.txt"}}}}

User: "还有txt"
Output: {{"domain": "file", "safety_level": "modify", "slots": {{}}}}

User: "再来个json版本"
Output: {{"domain": "file", "safety_level": "modify", "slots": {{}}}}

User: "also save as csv"
Output: {{"domain": "file", "safety_level": "modify", "slots": {{}}}}
"""


class IntentExtractor:
    """
    Extracts structured IntentSpec from natural language user request.
    Classifies domain + safety_level and extracts typed slots (content, file_path, target_path).
    """
    def __init__(self, llm_client: Any):
        self.llm = llm_client

    # ── Continuation detection (rule-based, pre-LLM) ──────────────────
    _CONTINUATION_PATTERNS = re.compile(
        r'^(?:还有|再来[个一]|also|再给我[一个]*|and\s+(?:also\s+)?(?:save|export|generate)?)\s*'
        r'(txt|json|csv|md|markdown|xlsx|xls|pdf|png|jpg|html|xml|yaml)\s*(?:版本|格式|文件)?$',
        re.IGNORECASE,
    )
    _FORMAT_ONLY = re.compile(
        r'^(txt|json|csv|md|markdown|xlsx|xls|pdf|png|jpg|html|xml|yaml)\s*$',
        re.IGNORECASE,
    )

    def _detect_continuation(self, user_request: str) -> Optional[IntentSpec]:
        """
        Rule-based detection for short continuation phrases like "还有txt",
        "再来个json版本", "also csv". Returns an IntentSpec with
        metadata.is_continuation=True and metadata.requested_format set,
        or None if not a continuation.
        """
        text = user_request.strip()
        if len(text) > 30:
            return None

        m = self._CONTINUATION_PATTERNS.match(text) or self._FORMAT_ONLY.match(text)
        if not m:
            return None

        fmt = m.group(1).lower()
        # Normalize aliases
        if fmt == "markdown":
            fmt = "md"
        if fmt == "text":
            fmt = "txt"

        logger.info(f"[IntentExtractor] Continuation detected: format={fmt}")
        return IntentSpec(
            id=str(uuid.uuid4()),
            goal=user_request,
            intent_type="task",
            domain=IntentDomain.FILE,
            safety_level=SafetyLevel.MODIFY,
            raw_user_input=user_request,
            params={},  # No file_path — it's a format request, not a path
            metadata={
                "source": "continuation_detector",
                "is_continuation": True,
                "requested_format": fmt,
            },
        )

    async def extract(self, user_request: str, history: List[Dict[str, str]] = None) -> IntentSpec:
        """
        意图提取：分类（domain + safety_level）+ typed slots 提取。
        goal 保持原始用户输入，代词消解由 ReferenceResolver + Planner 负责。
        """
        # Rule-based continuation detection (before LLM call)
        continuation = self._detect_continuation(user_request)
        if continuation is not None:
            return continuation

        prompt = SIMPLIFIED_INTENT_PROMPT.format(user_input=user_request)

        try:
            if hasattr(self.llm, "call"):
                raw_resp = self.llm.call(prompt)
            elif hasattr(self.llm, "generate"):
                raw_resp = self.llm.generate(prompt)
            elif callable(self.llm):
                raw_resp = self.llm(prompt)
            else:
                raise TypeError("LLM client is not callable")

            logger.debug(f"[IntentExtractor] LLM response: {raw_resp[:200]}")

            data = self._parse_json(raw_resp)

            domain = self._parse_domain(data.get("domain", "other"))
            safety = self._parse_safety(data.get("safety_level", "modify"))

            # 提取 typed slots（只提取路径类，content 来自历史不在当前输入里）
            raw_slots = data.get("slots") or {}
            params: Dict[str, Any] = {}
            for key in ("file_path", "target_path"):
                val = raw_slots.get(key)
                if val and isinstance(val, str) and val.strip():
                    params[key] = val.strip()

            if params:
                logger.info(f"[IntentExtractor] Typed slots extracted: {list(params.keys())}")

            logger.info(
                f"[IntentExtractor] Extracted: goal='{user_request[:50]}...', "
                f"domain={domain.value}, safety={safety.value}, slots={list(params.keys())}"
            )

            return IntentSpec(
                id=str(uuid.uuid4()),
                goal=user_request,
                intent_type="task",
                domain=domain,
                safety_level=safety,
                raw_user_input=user_request,
                params=params,
                metadata={"source": "intent_extractor"}
            )

        except Exception as e:
            logger.error(f"[IntentExtractor] Extraction failed: {e}")
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
        try:
            return IntentDomain[domain_str.upper()]
        except KeyError:
            logger.warning(f"Unknown domain: {domain_str}, using OTHER")
            return IntentDomain.OTHER

    def _parse_safety(self, safety_str: str) -> SafetyLevel:
        safety_map = {
            "read_only": "READ_ONLY",
            "modify": "MODIFY",
            "destructive": "DESTRUCTIVE",
        }
        try:
            return SafetyLevel[safety_map.get(safety_str.lower(), "MODIFY")]
        except KeyError:
            logger.warning(f"Unknown safety level: {safety_str}, using MODIFY")
            return SafetyLevel.MODIFY

    def _parse_json(self, text: str) -> Dict[str, Any]:
        text = text.strip()

        # Remove <think> blocks (reasoning models)
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

        if "```" in text:
            match = re.search(r'```(?:json)?(.*?)```', text, re.DOTALL)
            if match:
                text = match.group(1).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

        try:
            fixed = text.replace("'", '"')
            start = fixed.find("{")
            end = fixed.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(fixed[start:end])
        except Exception:
            pass

        raise ValueError(f"Could not parse JSON from LLM output: {text[:100]}...")
