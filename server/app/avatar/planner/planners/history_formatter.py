"""
History formatting and skill description utilities for the InteractiveLLMPlanner.

Extracted from interactive.py to keep the planner module focused on logic.
Contains: _sanitize_host_paths, _is_markup_content, _compress_structured_output,
           _format_history, _build_goal_coverage_summary, _format_skills
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Mapping, Optional

from app.avatar.runtime.context.reference_resolver import _is_binary_like_payload

# Re-export Task/Step types for callers
from ..models import Task, Step


def _sanitize_host_paths(text: str, workspace_root: Optional[str],
                         session_root: Optional[str] = None) -> str:
    """
    把 history 里的宿主机绝对路径替换成容器内路径。
    防止 Planner 从 history 里抠出 Windows 路径硬编码进脚本。

    Dual-mount aware:
      - session_root → /session/...  (must match first — longer prefix)
      - workspace_root → /workspace/...
    """
    if not text:
        return text

    import re as _re

    # Build (root_fwd, root_back, mount) mappings — session first
    _mappings: list = []
    if session_root:
        _s_fwd = session_root.replace("\\", "/").rstrip("/")
        _s_back = session_root.replace("/", "\\").rstrip("\\")
        _mappings.append((_s_fwd, _s_back, "/session"))
    if workspace_root:
        _w_fwd = workspace_root.replace("\\", "/").rstrip("/")
        _w_back = workspace_root.replace("/", "\\").rstrip("\\")
        _mappings.append((_w_fwd, _w_back, "/workspace"))

    if not _mappings:
        return text

    result = text
    for fwd, back, mount in _mappings:
        escaped_fwd = _re.escape(fwd)
        escaped_back = _re.escape(back)
        pattern = f"({escaped_fwd}|{escaped_back})[^\\s\"']*"

        def _make_replacer(_root_fwd: str, _mount: str):
            def _replace(m: "_re.Match") -> str:
                full = m.group(0)
                normalized = full.replace("\\", "/")
                if normalized.startswith(_root_fwd):
                    rel = normalized[len(_root_fwd):].lstrip("/")
                    return f"{_mount}/{rel}" if rel else _mount
                return full
            return _replace

        result = _re.sub(pattern, _make_replacer(fwd, mount), result)

    return result


def _is_markup_content(text: str) -> bool:
    """
    Detect XML/SVG/HTML markup content that should NOT be inlined into Python code.
    These contain <, >, ", \\ etc. that cause SyntaxError when embedded as string literals.
    """
    stripped = text.strip()
    if len(stripped) < 100:
        return False
    # Starts with XML declaration or root tag
    if stripped.startswith('<?xml') or stripped.startswith('<!DOCTYPE'):
        return True
    # Starts with common markup root tags
    if re.match(r'^<(svg|html|div|table|root|document|data)\b', stripped, re.IGNORECASE):
        return True
    # High density of angle brackets indicates markup
    bracket_count = stripped.count('<') + stripped.count('>')
    if bracket_count > 10 and bracket_count / len(stripped) > 0.02:
        return True
    return False


def _compress_structured_output(output: Any, step_index: int) -> Optional[str]:
    """
    Semantic-aware output compression for structured data.

    Detects outputs that serve as "working sets" for subsequent planning steps
    (file lists, batch results, search hits, artifact inventories, etc.) and
    compresses them into a compact, path-preserving format instead of applying
    the generic head+tail text truncation that destroys referenceability.

    Supported shapes:
      - list[dict]  (direct structured list, e.g. fs.list output)
      - dict with a high-value list field (files/results/items/matches/artifacts/contents)

    Returns a compressed string, or None if the output is not structured.
    """
    # ── Extract the list to compress ──────────────────────────────────────
    items: Optional[List] = None

    if isinstance(output, list) and output and isinstance(output[0], dict):
        items = output
    elif isinstance(output, dict):
        # Look for a high-value list field inside the dict
        _LIST_KEYS = ("files", "results", "items", "matches", "artifacts",
                      "contents", "entries", "records", "paths")
        for key in _LIST_KEYS:
            val = output.get(key)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                items = val
                break

    if not items:
        return None

    # ── Pick the most informative fields per item ─────────────────────────
    # Priority order: identity fields first, then status/type, then size
    _IDENTITY_KEYS = ("path", "name", "src", "dst", "id", "file_path", "url")
    _META_KEYS = ("type", "is_dir", "status", "error", "success", "size")

    # Determine which keys actually exist across items (sample first 5)
    sample = items[:5]
    available_identity = [k for k in _IDENTITY_KEYS if any(k in item for item in sample)]
    available_meta = [k for k in _META_KEYS if any(k in item for item in sample)]

    # If no identity keys found, fall back to None (use generic truncation)
    if not available_identity:
        return None

    keys_to_show = available_identity + available_meta[:3]  # cap meta fields

    # ── Compress each item into a single line ─────────────────────────────
    MAX_ITEMS = 80  # show up to 80 items before truncating
    compressed_lines = []
    for item in items[:MAX_ITEMS]:
        parts = []
        for k in keys_to_show:
            v = item.get(k)
            if v is not None:
                parts.append(f"{k}={v}")
        compressed_lines.append("  " + ", ".join(parts))

    total = len(items)
    header = f"[{total} items, showing key fields]"
    if total > MAX_ITEMS:
        compressed_lines.append(f"  ... [{total - MAX_ITEMS} more items omitted]")

    result = header + "\n" + "\n".join(compressed_lines)

    # Final safety: if compressed form is still huge (>3000 chars), do head+tail
    if len(result) > 3000:
        result = result[:2000] + f"\n  ... [truncated, {total} items total]\n" + result[-800:]

    return result


def _format_history(task: Task, workspace_root: Optional[str] = None,
                    session_root: Optional[str] = None) -> str:
    if not task.steps:
        return "(No steps executed yet)"
    
    lines = []
    for i, step in enumerate(task.steps):
        status = step.status.name if hasattr(step.status, "name") else str(step.status)
        result_str = ""
        if step.result:
            if step.result.success:
                raw_output = step.result.output
                out_preview = str(raw_output)

                # binary-like payload: show length only
                if _is_binary_like_payload(out_preview):
                    out_preview = f"[binary payload, {len(out_preview)} chars — use step_{i+1}_output variable, do NOT inline this value]"
                elif _is_markup_content(out_preview):
                    tag_hint = out_preview[:80].replace('\n', ' ')
                    out_preview = f"[markup content, {len(out_preview)} chars, starts with: {tag_hint}... — use step_{i+1}_output variable, do NOT inline]"
                else:
                    # Semantic-aware compression for structured outputs
                    # (file lists, batch results, search hits, etc.)
                    compressed = _compress_structured_output(raw_output, i)
                    if compressed is not None:
                        out_preview = compressed
                    elif len(out_preview) > 600:
                        # Generic long text: head+tail truncation
                        out_preview = out_preview[:250] + "\n... [中间省略] ...\n" + out_preview[-300:]

                out_preview = _sanitize_host_paths(out_preview, workspace_root, session_root)
                result_str = f"Output: {out_preview}"
            else:
                error_msg = str(step.result.error)
                if len(error_msg) > 600:
                    error_msg = error_msg[:200] + "\n... [中间省略] ...\n" + error_msg[-400:]
                result_str = f"Error: {error_msg}"

                # File Type Routing violation detection:
                # If a step failed and it used fs.read on a binary file type,
                # remind the planner of the correct routing rule.
                _BINARY_EXTS = (".xlsx", ".xls", ".docx", ".pdf", ".png", ".jpg",
                                ".gif", ".bmp", ".zip", ".7z", ".rar", ".pptx")
                if step.skill_name == "fs.read":
                    _path_param = (step.params or {}).get("path", "")
                    if any(_path_param.lower().endswith(ext) for ext in _BINARY_EXTS):
                        _ext = next(ext for ext in _BINARY_EXTS if _path_param.lower().endswith(ext))
                        result_str += (
                            f"\n  ⚠️ ROUTING VIOLATION: fs.read cannot read {_ext} files. "
                            f"Use python.run with the appropriate library instead "
                            f"(see File Type Routing rules above)."
                        )
        
        lines.append(f"Step {i+1}: {step.skill_name}")
        params_str = json.dumps(step.params, ensure_ascii=False)
        params_str = _sanitize_host_paths(params_str, workspace_root, session_root)
        lines.append(f"  Params: {params_str}")
        lines.append(f"  Status: {status}")
        lines.append(f"  Result: {result_str}")
        lines.append("---")

    # ── Goal Coverage Summary（第二层：面向目标判定的结构化摘要）──────────────
    # 让 LLM 看到"目标是否已满足"的明确结论，而不是只看事件流
    summary = _build_goal_coverage_summary(task, workspace_root, session_root)
    if summary:
        lines.append("")
        lines.append(summary)

    return "\n".join(lines)


def _build_goal_coverage_summary(task: Task, workspace_root: Optional[str] = None,
                                  session_root: Optional[str] = None) -> str:
    """
    在 execution history 末尾注入面向目标判定的结构化摘要。

    包含：
    - 最近成功步骤的输出摘要（Latest successful outputs）
    - Finish Confidence 检查（第三层：规则化判定）
    - 明确的 Recommended action
    """
    if not task.steps:
        return ""

    # 收集成功步骤
    successful_steps = [
        (i + 1, s) for i, s in enumerate(task.steps)
        if s.result and s.result.success
    ]
    failed_steps = [
        (i + 1, s) for i, s in enumerate(task.steps)
        if s.result and not s.result.success
    ]

    if not successful_steps:
        return ""

    lines = ["## Goal Coverage Summary"]
    lines.append(f"Goal: {task.goal}")
    lines.append("")

    # ── Latest successful outputs ──────────────────────────────────────────
    lines.append("Latest successful outputs:")
    # 只展示最近 3 个成功步骤的输出摘要
    for step_num, step in successful_steps[-3:]:
        raw_out = step.result.output
        out = str(raw_out) if raw_out else "(no output)"
        out = _sanitize_host_paths(out, workspace_root, session_root)
        # binary-like payload：只展示长度
        if _is_binary_like_payload(out):
            out = f"[binary payload, {len(out)} chars]"
        elif _is_markup_content(out):
            out = f"[markup content, {len(out)} chars — use step_{step_num}_output variable]"
        else:
            # Try structured compression first
            compressed = _compress_structured_output(raw_out, step_num - 1)
            if compressed is not None:
                # In summary, show a shorter version (first 15 items max)
                comp_lines = compressed.split("\n")
                if len(comp_lines) > 17:  # header + 15 items + omitted
                    out = "\n".join(comp_lines[:16]) + f"\n  ... [see step_{step_num} output for full list]"
                else:
                    out = compressed
            elif len(out) > 300:
                out = out[:250] + "...[truncated]"
        lines.append(f"  step_{step_num} ({step.skill_name}): {out}")
    lines.append("")

    # ── Finish Confidence 检查（第三层：规则化判定）────────────────────────
    # 规则 1：最近一步成功输出是否直接回答了 goal（关键词重叠）
    last_success_num, last_success_step = successful_steps[-1]
    last_output = str(last_success_step.result.output) if last_success_step.result.output else ""
    last_output_lower = last_output.lower()
    goal_lower = task.goal.lower()

    # 提取 goal 中的关键词（去掉停用词）
    _STOPWORDS = {"the", "a", "an", "is", "are", "in", "on", "at", "to", "of",
                  "and", "or", "for", "with", "by", "from", "that", "this",
                  "请", "帮我", "我要", "一下", "所有", "的", "了", "在", "把",
                  "并", "然后", "接着", "之后"}
    goal_tokens = set(re.findall(r'[\w\u4e00-\u9fff]+', goal_lower)) - _STOPWORDS
    output_tokens = set(re.findall(r'[\w\u4e00-\u9fff]+', last_output_lower))
    keyword_overlap = len(goal_tokens & output_tokens) / max(len(goal_tokens), 1)

    # 规则 2：最近两步是否是相同 skill + 相似参数（重复迹象）
    # 从 skill registry 动态获取参数名，不依赖硬编码映射
    recent_duplicate = False
    if len(successful_steps) >= 2:
        prev_num, prev_step = successful_steps[-2]
        if prev_step.skill_name == last_success_step.skill_name:
            skill = last_success_step.skill_name

            # 动态获取 skill 参数名
            _key_params = None
            try:
                from app.avatar.skills.registry import skill_registry as _sr
                _cls = _sr.get(skill)
                if _cls:
                    _im = getattr(_cls.spec, "input_model", None)
                    if _im:
                        _schema = _im.model_json_schema()
                        _props = _schema.get("properties", {})
                        _req = set(_schema.get("required", []))
                        _key_params = sorted(_props.keys(), key=lambda k: (k not in _req, k))
            except Exception:
                pass
            if _key_params is None:
                _key_params = list((last_success_step.params or {}).keys())[:2]

            def _fp(params):
                parts = [skill]
                for k in _key_params:
                    v = (params or {}).get(k)
                    if v is not None:
                        s = re.sub(r'\s+', ' ', str(v).strip())[:200]
                        parts.append(f"{k}={s}")
                return "|".join(parts)

            prev_fp = _fp(prev_step.params)
            last_fp = _fp(last_success_step.params)
            param_sim = SequenceMatcher(None, prev_fp, last_fp).ratio()
            if param_sim >= 0.92:
                recent_duplicate = True

    # 规则 3：是否有明确未完成的失败步骤（最近一步失败）
    has_recent_failure = bool(failed_steps) and failed_steps[-1][0] > (successful_steps[-1][0] if successful_steps else 0)

    # ── 规则 4：写文件意图但缺少 fs.write 成功步骤 ───────────────────────
    # goal 含写/创建文件关键词时，必须有 fs.write/fs.copy 成功才能 FINISH
    # 防止 python.run 只输出文件路径列表就被误判为"已完成写文件"
    _WRITE_INTENT_KEYWORDS = {
        "写入", "写到", "写文件", "创建文件", "保存", "存储", "生成文件",
        "write", "create file", "save file", "output file",
    }
    _WRITE_SKILLS = {"fs.write", "fs.copy"}
    goal_has_write_intent = any(kw in goal_lower for kw in _WRITE_INTENT_KEYWORDS)
    has_write_success = any(
        s.skill_name in _WRITE_SKILLS and s.result and s.result.success
        for _, s in successful_steps
    )
    missing_write = goal_has_write_intent and not has_write_success

    # ── 综合判定 ──────────────────────────────────────────────────────────
    finish_signals = []
    continue_signals = []

    if keyword_overlap >= 0.4 and not missing_write:
        finish_signals.append(f"last output has {keyword_overlap:.0%} keyword overlap with goal")
    if recent_duplicate:
        finish_signals.append("last two successful steps are near-identical (possible redundant loop)")
    if has_recent_failure:
        continue_signals.append("last step failed — may need retry or alternative approach")
    if missing_write:
        continue_signals.append("goal requires writing files but no fs.write/fs.copy has succeeded yet")

    lines.append("Finish Confidence Check:")
    if finish_signals:
        lines.append(f"  ✓ FINISH signals: {'; '.join(finish_signals)}")
    if continue_signals:
        lines.append(f"  ✗ CONTINUE signals: {'; '.join(continue_signals)}")

    # ── Recommended action ────────────────────────────────────────────────
    lines.append("")
    if has_recent_failure:
        lines.append(
            "Recommended action: CONTINUE — last step failed, fix or try alternative."
        )
    elif finish_signals and not continue_signals:
        lines.append(
            "Recommended action: FINISH — goal appears satisfied. "
            "Do NOT add verification/reformatting steps unless the goal explicitly requires them."
        )
    else:
        lines.append(
            "Recommended action: EVALUATE — check if all sub-goals are covered before deciding."
        )

    return "\n".join(lines)


def _format_skills(available_skills: Mapping[str, Any]) -> str:
    skills_desc = []
    for name, meta in available_skills.items():
        desc = meta.get("description", "") if isinstance(meta, dict) else ""
        # 获取完整的参数 schema
        params_schema = meta.get("params_schema", {}) if isinstance(meta, dict) else {}
        output_schema = meta.get("output_schema", {}) if isinstance(meta, dict) else {}
        
        # 格式化输入参数（包含类型信息）
        if params_schema:
            param_lines = []
            for param_name, param_info in params_schema.items():
                param_type = param_info.get("type", "any")
                param_desc = param_info.get("description", "")
                param_lines.append(f"    - {param_name} ({param_type}): {param_desc}")
            params_str = "\n".join(param_lines)
        else:
            params_str = "    (no parameters)"

        # 格式化输出字段（让 Planner 知道返回值结构）
        output_str = ""
        if output_schema:
            out_lines = []
            for field_name, field_info in output_schema.items():
                field_type = field_info.get("type", "any")
                field_desc = field_info.get("description", "")
                out_lines.append(f"    - {field_name} ({field_type}): {field_desc}")
            output_str = "\n  Output fields:\n" + "\n".join(out_lines)

        skills_desc.append(f"- {name}: {desc}\n  Parameters:\n{params_str}{output_str}")
    return "\n".join(skills_desc)
