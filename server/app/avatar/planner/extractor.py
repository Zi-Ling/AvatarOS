# app/avatar/planner/extractor.py
"""
智能 JSON 提取器 - 三层容错机制

第一层：智能提取 JSON + 修复管线
第二层：LLM 自修复（只修“格式层”，不修“内容层/语义层”）
第三层：友好降级
"""
from __future__ import annotations

import json
import re
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Callable, Union

logger = logging.getLogger(__name__)


# =========================
# Error types
# =========================
@dataclass(frozen=True)
class PlanParseError:
    """
    结构化错误（建议：上层捕获后把 error_code 透传给 healer）
    """
    error_code: str
    message: str


class JSONExtractionError(Exception):
    """JSON 提取失败（带 error_code）"""

    def __init__(
        self,
        message: str,
        raw_text: str,
        suggestions: Optional[List[str]] = None,
        error_code: str = "unknown",
    ):
        super().__init__(message)
        self.raw_text = raw_text
        self.suggestions = suggestions or []
        self.error_code = error_code


class RetryablePlanningError(Exception):
    """
    可重试的规划失败异常
    
    用于标记"规划器产生了无效计划，但可以通过 replanner 重试"的情况：
    - 空计划（steps 为空）
    - 必需参数缺失
    - Schema 校验失败
    
    与直接使用 fallback 不同，这个异常应该触发 replanner 流程
    """
    def __init__(self, reason: str, original_error: Optional[Exception] = None):
        self.reason = reason
        self.original_error = original_error
        super().__init__(reason)


# =========================
# Smart JSON Extractor
# =========================
class SmartJSONExtractor:
    """
    智能 JSON 提取器

    功能：
    1. 从混乱的 LLM 输出中提取 JSON
    2. 支持多种格式（markdown、think 标签、纯文本）
    3. 自动修复常见的 JSON 格式错误（修复管线）
    4. 提供结构化 error_code
    """

    # -------- Error code helpers --------
    @staticmethod
    def _classify_json_decode_error(e: json.JSONDecodeError, text: str) -> str:
        msg = (e.msg or "").lower()

        # 常见格式错误归类
        if "unterminated string" in msg:
            return "unterminated_string"
        if "expecting property name enclosed in double quotes" in msg:
            # 典型单引号/未加引号键
            if "'" in text:
                return "single_quotes"
            return "json_decode_error"
        if "expecting value" in msg:
            # 尾逗号也会触发 expecting value
            if re.search(r",\s*[\]}]", text):
                return "trailing_comma"
            return "json_decode_error"
        if "extra data" in msg:
            return "extra_text_outside_json"

        return "json_decode_error"

    @staticmethod
    def _classify_non_decode_failure(raw_text: str) -> str:
        t = (raw_text or "").strip()
        if not t:
            return "empty_response"
        # 没找到任何 JSON 形态
        if ("{" not in t) and ("[" not in t):
            return "missing_brackets"
        return "unknown"

    # -------- Fixers --------
    @staticmethod
    def _fix_depends_on_colon(text: str) -> str:
        """
        修复 "depends_on":[ 这种缺少冒号/格式不一致的错误（尽量保守）
        """
        # 这里保持保守：如果已经包含正确键则不处理
        if re.search(r'"depends_on"\s*:', text):
            return text

        # 尝试把 depends_on: [ 修成 "depends_on": [
        fixed = re.sub(r'\bdepends_on\s*:\s*\[', r'"depends_on": [', text)

        if fixed != text:
            logger.debug("[JSONFixer] Fixed depends_on key formatting")
        return fixed

    @staticmethod
    def _fix_stray_quotes_in_array(text: str) -> str:
        """
        修复数组中的杂散引号，如 ["  ] 或 [" ]
        """
        fixed = re.sub(r'\[\s*"\s*\]', "[]", text)
        if fixed != text:
            logger.debug("[JSONFixer] Fixed stray quotes in array")
        return fixed

    @staticmethod
    def _fix_missing_comma_between_objects(text: str) -> str:
        """
        修复对象之间缺少逗号的错误： }{ -> },{
        仅在明显像“数组对象连续”的情况下触发（保守）
        """
        pattern = r"\}\s*\n\s*\{"

        # 启发式：前后都有 "id" 或 "skill" 时，认为更可信
        for match in re.finditer(pattern, text):
            start = max(0, match.start() - 80)
            end = min(len(text), match.end() + 80)
            context = text[start:end]
            left = context[: len(context) // 2]
            right = context[len(context) // 2 :]

            if (('"id"' in left or '"skill"' in left) and ('"id"' in right or '"skill"' in right)):
                fixed = re.sub(pattern, "},\n{", text)
                if fixed != text:
                    logger.debug("[JSONFixer] Fixed missing comma between objects")
                return fixed

        return text

    @staticmethod
    def _fix_trailing_comma(text: str) -> str:
        """
        修复尾部逗号： [1,2,] / {"a":1,}
        """
        fixed = re.sub(r",(\s*[}\]])", r"\1", text)
        if fixed != text:
            logger.debug("[JSONFixer] Fixed trailing comma")
        return fixed

    @staticmethod
    def _try_parse_with_fixes(text: str, fixers: List[Callable[[str], str]]) -> Optional[Any]:
        """
        使用修复管线尝试解析 JSON
        """
        try:
            parsed = json.loads(text)
            logger.debug("[JSONFixer] Direct parse succeeded")
            return parsed
        except json.JSONDecodeError as e:
            logger.debug(f"[JSONFixer] Direct parse failed: {e}")

        current_text = text
        for fixer in fixers:
            try:
                fixed_text = fixer(current_text)
                if fixed_text == current_text:
                    continue

                logger.debug(f"[JSONFixer] Fixer {fixer.__name__} modified text")
                try:
                    parsed = json.loads(fixed_text)
                    logger.debug(f"[JSONFixer] ✅ Parse succeeded after {fixer.__name__}")
                    return parsed
                except json.JSONDecodeError as e:
                    logger.debug(f"[JSONFixer] Parse still failed after {fixer.__name__}: {e}")
                    current_text = fixed_text  # 保留修改，继续
            except Exception as e:
                logger.warning(f"[JSONFixer] Fixer {fixer.__name__} raised exception: {e}")
                continue

        return None

    # -------- Public API --------
    @staticmethod
    def extract(raw_text: str) -> Tuple[Any, bool]:
        """
        提取 JSON（第一层容错）

        Returns:
            (parsed_json, is_clean)

        Raises:
            JSONExtractionError
        """
        if not raw_text or not raw_text.strip():
            raise JSONExtractionError(
                "LLM 返回了空响应",
                raw_text,
                ["请重试", "检查 LLM 是否正常运行"],
                error_code="empty_response",
            )

        text = raw_text.strip()

        # 1) 移除 think 标签
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()

        # 2) 提取 markdown code block
        if "```" in text:
            matches = re.findall(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
            if matches:
                for match in matches:
                    candidate = match.strip()
                    try:
                        parsed = json.loads(candidate)
                        return parsed, False
                    except json.JSONDecodeError:
                        # 尝试修复管线
                        fixers = [
                            SmartJSONExtractor._fix_depends_on_colon,
                            SmartJSONExtractor._fix_stray_quotes_in_array,
                            SmartJSONExtractor._fix_trailing_comma,
                            SmartJSONExtractor._fix_missing_comma_between_objects,
                            lambda t: t.replace("'", '"'),
                        ]
                        parsed2 = SmartJSONExtractor._try_parse_with_fixes(candidate, fixers)
                        if parsed2 is not None:
                            return parsed2, False

        # 3) 直接解析
        try:
            parsed = json.loads(text)
            return parsed, True
        except json.JSONDecodeError as e:
            decode_code = SmartJSONExtractor._classify_json_decode_error(e, text)
            logger.debug(f"[JSONExtractor] Direct parse failed ({decode_code}): {e}")

        # 4) 提取 JSON 数组
        array_match = re.search(r"\[\s*\{.*?\}\s*\]", text, re.DOTALL)
        if array_match:
            candidate = array_match.group(0)
            try:
                parsed = json.loads(candidate)
                return parsed, False
            except json.JSONDecodeError:
                pass

        # 5) 提取 JSON 对象
        obj_match = re.search(r"\{.*\}", text, re.DOTALL)
        if obj_match:
            candidate = obj_match.group(0)
            try:
                parsed = json.loads(candidate)
                return parsed, False
            except json.JSONDecodeError:
                pass

        # 6) 修复管线
        logger.debug(f"[JSONExtractor] Attempting repair pipeline on text: {text[:200]}...")

        fixers = [
            SmartJSONExtractor._fix_depends_on_colon,
            SmartJSONExtractor._fix_stray_quotes_in_array,
            SmartJSONExtractor._fix_trailing_comma,
            SmartJSONExtractor._fix_missing_comma_between_objects,
            lambda t: t.replace("'", '"'),
        ]

        parsed = SmartJSONExtractor._try_parse_with_fixes(text, fixers)
        if parsed is not None:
            logger.debug("[JSONExtractor] ✅ Repair pipeline succeeded")
            return parsed, False

        # 全失败
        code = SmartJSONExtractor._classify_non_decode_failure(raw_text)
        logger.error("[JSONExtractor] All extraction and repair attempts failed")
        raise JSONExtractionError(
            "无法从 LLM 输出中提取有效的 JSON",
            raw_text[:500],
            [
                "LLM 可能输出了非 JSON 格式的文本",
                "请尝试重新表述你的需求",
                "或者切换到更强大的 LLM 模型",
            ],
            error_code=code,
        )

    @staticmethod
    def validate_plan_structure(data: Any) -> Tuple[bool, Optional[str]]:
        """
        验证计划结构（只做结构校验，不做 params schema 校验）

        Returns:
            (is_valid, error_message)
        """
        # 允许 {"steps":[...]} 或直接 [...]
        if isinstance(data, dict):
            if "steps" in data:
                return SmartJSONExtractor.validate_plan_structure(data["steps"])
            return False, "JSON 对象缺少 'steps' 字段"

        # 必须是列表
        if not isinstance(data, list):
            return False, "计划必须是一个 JSON 数组"

        # 不能为空
        if len(data) == 0:
            return False, "计划不能为空（至少需要一个步骤）"

        # 检查每步
        for i, step in enumerate(data):
            if not isinstance(step, dict):
                return False, f"步骤 {i+1} 必须是一个 JSON 对象"

            if "skill" not in step and "skill_name" not in step:
                return False, f"步骤 {i+1} 缺少 'skill' 字段"

            if "params" not in step:
                return False, f"步骤 {i+1} 缺少 'params' 字段"

        return True, None


# =========================
# LLM Self Healer (format-only)
# =========================
class LLMSelfHealer:
    """
    LLM 自修复器（第二层容错）

    只用于“JSON提取/格式层失败”：
      - 括号缺失、尾逗号、单引号、字符串未闭合、夹杂额外文本等

    禁止用于“内容层问题”：
      - 计划为空
      - skill 不存在
      - 参数 schema 缺字段/字段名不匹配
      - HTTP 400/429/500 等调用层错误
    """

    ALLOWED_ERROR_CODES = {
        "json_decode_error",
        "missing_brackets",
        "trailing_comma",
        "single_quotes",
        "unterminated_string",
        "extra_text_outside_json",
    }

    # 这些一旦出现，说明不是格式小毛病，禁止 heal（交给 replan）
    BLOCKED_HINTS = {
        "计划不能为空",
        "steps cannot be empty",
        "skill not found",
        "validation error",
        "field required",
        "invalid parameters",
        "httpstatuserror",
        "bad request",
        "rate limit",
        "timeout",
        "client error",
        "server error",
    }

    def __init__(self, llm_client):
        self._llm = llm_client

    def _can_heal(self, err: Union[JSONExtractionError, str]) -> bool:
        if isinstance(err, JSONExtractionError):
            code = (err.error_code or "").lower()
            msg = (str(err) or "").lower()
            raw = (err.raw_text or "").lower()
        else:
            code = ""
            msg = (err or "").lower()
            raw = ""

        # 阻断内容层/调用层错误
        combined = f"{msg}\n{raw}"
        if any(h in combined for h in self.BLOCKED_HINTS):
            return False

        # 有 error_code 时按白名单
        if code:
            return code in self.ALLOWED_ERROR_CODES

        # 没 error_code 的旧用法：保守，只对典型格式字样放行
        format_hints = ["json", "decode", "unterminated", "trailing", "quotes", "extra data", "bracket", "brace"]
        return any(h in combined for h in format_hints)

    def heal(
        self,
        original_prompt: str,
        failed_output: str,
        error_message: Union[JSONExtractionError, str],
        max_retries: int = 2,
    ) -> Optional[str]:
        """
        让 LLM 修复自己的输出（仅格式层）

        Returns:
            healed_output（字符串），失败返回 None
        """
        if not self._can_heal(error_message):
            return None

        # 更短、更硬的 healing prompt：只要 JSON 数组
        task = (original_prompt or "")[:800]
        prev = (failed_output or "")[:1200]
        err_str = str(error_message)
        err_str = (err_str or "")[:300]

        healing_prompt = f"""Fix ONLY the JSON formatting of your previous output.

ORIGINAL TASK:
{task}

PREVIOUS OUTPUT (INVALID):
{prev}

ERROR:
{err_str}

STRICT RULES:
- Output ONLY a valid JSON array: [{{...}}, {{...}}]
- Do NOT output markdown, explanations, or any text outside JSON
- Keep only these keys per step: id, skill, params, depends_on
- The array MUST be non-empty

CORRECT JSON ARRAY:"""

        logger.info(f"[LLMSelfHealer] Attempting to heal LLM output (max_retries={max_retries})...")

        for attempt in range(max_retries):
            try:
                healed_output = self._llm.call(healing_prompt)

                parsed, _ = SmartJSONExtractor.extract(healed_output)
                is_valid, validation_error = SmartJSONExtractor.validate_plan_structure(parsed)

                # 关键：结构不合法（尤其“计划为空”）——不要继续 heal，直接交给上层 replan
                if not is_valid:
                    logger.warning(f"[LLMSelfHealer] Healed output still invalid: {validation_error}")
                    return None

                logger.info(f"[LLMSelfHealer] ✅ Successfully healed on attempt {attempt + 1}")
                return healed_output

            except JSONExtractionError as e:
                # 如果还是格式层错误，允许下一次；如果是明显非格式层，直接放弃
                if not self._can_heal(e):
                    return None
                continue
            except Exception as e:
                logger.warning(f"[LLMSelfHealer] Healing attempt {attempt + 1} failed: {e}")
                continue

        logger.warning("[LLMSelfHealer] ❌ All healing attempts failed")
        return None


# =========================
# Friendly error formatter
# =========================
class FriendlyErrorFormatter:
    """
    友好错误格式化器（第三层容错）
    """

    @staticmethod
    def format(error: JSONExtractionError) -> Dict[str, Any]:
        return {
            "user_message": f"😔 AI 理解了你的需求，但在生成执行计划时遇到了问题：{error}",
            "suggestions": error.suggestions,
            "technical_details": f"error_code={error.error_code}; raw={error.raw_text[:200]}...",
            "retry_possible": True,
            "error_type": "LLM_OUTPUT_FORMAT_ERROR",
        }
