"""
ParameterExtractor — Lightweight structured parameter extraction layer.

Sits between Router and Planner. Extracts concrete parameter values from
natural language so the Planner doesn't have to do both "understanding"
and "step generation" in a single LLM call.

Design:
- Rule-based (regex + pattern matching), NO LLM calls
- Uses top_skills' param schemas to know WHAT to extract
- Extracted params are written into IntentSpec.params
- Planner prompt already renders params via "Required Params" section
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ParameterExtractor:
    """
    Extracts structured parameters from user's natural language input.
    
    Uses the top-scored skills' parameter schemas to determine what
    parameters to look for, then applies domain-specific regex patterns.
    """

    # ---- URL patterns ----
    _URL_RE = re.compile(
        r'https?://[^\s<>"\'，。、）\)]+',
        re.IGNORECASE,
    )

    # ---- File path patterns (Windows + Unix) ----
    _WIN_PATH_RE = re.compile(
        r'[A-Za-z]:\\(?:[^\s\\/:*?"<>|，。]+\\)*[^\s\\/:*?"<>|，。]+\.\w{1,10}'
    )
    _UNIX_PATH_RE = re.compile(
        r'(?:~/|/)[^\s，。、）\)]+\.\w{1,10}'
    )
    # Bare filename with extension (e.g. "report.xlsx", "data.csv")
    _FILENAME_RE = re.compile(
        r'\b[\w\-]+\.(?:xlsx?|csv|pdf|docx?|txt|json|html?|png|jpe?g|pptx?|zip|md)\b',
        re.IGNORECASE,
    )

    # ---- Selector patterns (CSS-like) ----
    _CSS_SELECTOR_RE = re.compile(
        r'(?:selector|选择器|元素)[：:\s]*["\']?([#\.\w][\w\-\s>#\.\[\]=\'"*:]+)["\']?',
        re.IGNORECASE,
    )

    # ---- Number patterns ----
    _NUMBER_RE = re.compile(r'\b\d+(?:\.\d+)?\b')

    # ---- Column / field name patterns (Chinese + English) ----
    _COLUMN_RE = re.compile(
        r'(?:列|字段|column|field)[：:\s]*["\']?([\w\u4e00-\u9fff]+)["\']?',
        re.IGNORECASE,
    )

    # ---- Sheet name patterns ----
    _SHEET_RE = re.compile(
        r'(?:sheet|工作表|表)[：:\s]*["\']?([\w\u4e00-\u9fff]+)["\']?',
        re.IGNORECASE,
    )

    # ---- Chart type patterns ----
    _CHART_TYPE_RE = re.compile(
        r'(?:图表类型|chart[\s_]?type|图|chart)[：:\s]*["\']?'
        r'(bar|line|pie|scatter|area|column|柱状|折线|饼|散点|面积)["\']?',
        re.IGNORECASE,
    )
    _CHART_TYPE_MAP = {
        "柱状": "bar", "柱形": "bar", "bar": "bar", "column": "bar",
        "折线": "line", "line": "line",
        "饼": "pie", "pie": "pie",
        "散点": "scatter", "scatter": "scatter",
        "面积": "area", "area": "area",
    }

    @staticmethod
    def extract(
        user_input: str,
        goal: str,
        top_skills: List[str],
        skill_schemas: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Extract structured parameters from user input.

        Args:
            user_input: Raw user message
            goal: Resolved goal (after pronoun resolution)
            top_skills: List of top skill names from Router (e.g. ["web.open", "excel.write"])
            skill_schemas: Skill param schemas {skill_name: {"params_schema": {...}, "required": [...]}}

        Returns:
            Dict of extracted parameters. Keys match skill param names where possible.
        """
        if not user_input and not goal:
            return {}

        text = f"{goal} {user_input}" if goal != user_input else user_input
        params: Dict[str, Any] = {}

        # Determine which param types to look for based on top skills
        needed = ParameterExtractor._analyze_needed_params(top_skills, skill_schemas)

        # Extract by category
        if "url" in needed:
            urls = ParameterExtractor._extract_urls(text)
            if urls:
                params["url"] = urls[0]
                if len(urls) > 1:
                    params["urls"] = urls

        if "path" in needed or "file_path" in needed or "output_path" in needed:
            paths = ParameterExtractor._extract_file_paths(text)
            if paths:
                # Assign to the most specific param name
                for key in ("file_path", "output_path", "path", "src", "dst"):
                    if key in needed:
                        params[key] = paths[0]
                        break
                else:
                    params["file_path"] = paths[0]
                if len(paths) > 1:
                    # Second path is likely destination
                    for key in ("dst", "output_path", "target_path"):
                        if key in needed and key not in params:
                            params[key] = paths[1]
                            break

        if "selector" in needed:
            sel = ParameterExtractor._extract_selector(text)
            if sel:
                params["selector"] = sel

        if "column" in needed or "column_name" in needed:
            cols = ParameterExtractor._extract_columns(text)
            if cols:
                key = "column_name" if "column_name" in needed else "column"
                params[key] = cols[0] if len(cols) == 1 else cols

        if "sheet_name" in needed or "sheet" in needed:
            sheet = ParameterExtractor._extract_sheet(text)
            if sheet:
                params["sheet_name"] = sheet

        if "chart_type" in needed:
            ct = ParameterExtractor._extract_chart_type(text)
            if ct:
                params["chart_type"] = ct

        if "text" in needed or "value" in needed or "content" in needed:
            # Don't extract free text — too ambiguous, let Planner handle it
            pass

        if params:
            logger.info(f"[ParamExtractor] Extracted {len(params)} params: {list(params.keys())}")
            logger.debug(f"[ParamExtractor] Values: {params}")

        return params

    # ---- Internal helpers ----

    @staticmethod
    def _analyze_needed_params(
        top_skills: List[str],
        skill_schemas: Dict[str, Dict[str, Any]],
    ) -> set:
        """Collect all parameter names from top skills' schemas."""
        needed = set()
        for skill_name in top_skills:
            schema = skill_schemas.get(skill_name, {})
            props = schema.get("params_schema", {})
            needed.update(props.keys())
        return needed

    @staticmethod
    def _extract_urls(text: str) -> List[str]:
        """Extract URLs from text."""
        matches = ParameterExtractor._URL_RE.findall(text)
        # Clean trailing punctuation
        cleaned = []
        for url in matches:
            url = url.rstrip('.,;:!?')
            # Validate it's a real URL
            try:
                parsed = urlparse(url)
                if parsed.scheme and parsed.netloc:
                    cleaned.append(url)
            except Exception:
                pass
        return cleaned

    @staticmethod
    def _extract_file_paths(text: str) -> List[str]:
        """Extract file paths from text."""
        paths = []

        # Windows paths first (more specific)
        for m in ParameterExtractor._WIN_PATH_RE.finditer(text):
            paths.append(m.group())

        # Unix paths
        for m in ParameterExtractor._UNIX_PATH_RE.finditer(text):
            paths.append(m.group())

        # Bare filenames (only if no full paths found)
        if not paths:
            for m in ParameterExtractor._FILENAME_RE.finditer(text):
                paths.append(m.group())

        return paths

    @staticmethod
    def _extract_selector(text: str) -> Optional[str]:
        """Extract CSS selector from text."""
        m = ParameterExtractor._CSS_SELECTOR_RE.search(text)
        if m:
            return m.group(1).strip()
        return None

    @staticmethod
    def _extract_columns(text: str) -> List[str]:
        """Extract column/field names from text."""
        results = []
        for m in ParameterExtractor._COLUMN_RE.finditer(text):
            results.append(m.group(1).strip())
        return results

    @staticmethod
    def _extract_sheet(text: str) -> Optional[str]:
        """Extract sheet name from text."""
        m = ParameterExtractor._SHEET_RE.search(text)
        if m:
            return m.group(1).strip()
        return None

    @staticmethod
    def _extract_chart_type(text: str) -> Optional[str]:
        """Extract and normalize chart type."""
        m = ParameterExtractor._CHART_TYPE_RE.search(text)
        if m:
            raw = m.group(1).strip().lower()
            return ParameterExtractor._CHART_TYPE_MAP.get(raw, raw)
        return None
