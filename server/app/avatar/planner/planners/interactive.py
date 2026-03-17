from __future__ import annotations

import asyncio
import json
import logging
import re
import os
import time
from typing import Any, Dict, Mapping, Optional, List
from difflib import SequenceMatcher

from ..base import TaskPlanner
from ..models import Task, Step
from ..registry import register_planner
from app.avatar.skills.registry import skill_registry
from app.avatar.runtime.context.reference_resolver import _is_binary_like_payload

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Prompts
# ------------------------------------------------------------------------------

INTERACTIVE_SYSTEM_PROMPT = r"""You are an AI task planner for a local autonomous agent.

Your Operation Mode: **Interactive Step-by-Step Execution**

Your Job:
1. Analyze the user's `Goal`.
2. Review the `Execution History` (steps already executed and their REAL results).
3. Determine the **SINGLE NEXT STEP** to move closer to the goal.
4. If the goal is fully achieved based on the execution results, output `FINISH`.

**CRITICAL RULES (Defensive Mode):**
- **DO NOT Hallucinate Results**: You CANNOT know the result of a step before it is executed. Never write "Output: ...".
- **Strict Sequential Logic**: Use the `Output` from previous steps in the history to fill parameters for the current step.
- **Error Handling**: If the history shows the last step FAILED, your next step MUST be a fix/retry or an alternative approach. Do not repeat the exact same failed action.
- **HTTP 4xx Strategy Switch (MANDATORY)**: If a `net.get` step failed with HTTP 403, 404, or any 4xx status, do NOT retry `net.get` with the same or similar URL. Instead, immediately switch to `browser.run` to fetch the page via a real browser — it handles anti-bot protection and dynamic content that `net.get` cannot access.
- **browser.run Empty Output (MANDATORY)**: If a `browser.run` step succeeded but its output is empty (no stdout, no artifacts), the script did NOT extract any data. Do NOT call `browser.run` again with the same or similar script. Instead: (1) try a different URL or search engine, OR (2) use `llm.fallback` to inform the user that the data could not be retrieved.
- **No "Success" Claims**: Do not say "I have finished" unless you see the evidence in the history.
- **No Redundant Steps (MANDATORY)**: If the execution history already contains a successful step whose output fully answers the goal, output `FINISH` immediately. Do NOT add another step to "verify", "double-check", or "reformat" the same result. Repeating a step that already succeeded is FORBIDDEN.
- **No Inline Markup/Code Content (MANDATORY)**: NEVER embed raw XML, SVG, HTML, or any multi-line markup content directly as a string literal inside `python.run` code. These contain special characters (`<`, `>`, `"`, `\`) that WILL cause SyntaxError. Instead, ALWAYS reference such content via the `step_N_output` variable (which is auto-injected by the framework from `/workspace/input/`). The same applies to Windows file paths — use `step_N_output` instead of hardcoding paths with backslashes.
- **Goal Decomposition Check (MANDATORY before FINISH)**: Before outputting `FINISH`, mentally enumerate EVERY sub-goal in the original Goal. If ANY sub-goal has no corresponding successful step in the history, you MUST execute that step next instead of finishing. Example: Goal="write a poem AND save to file" → you must see BOTH a poem-generation step AND a file-write step succeed before finishing. For simple single-goal tasks (e.g. "count lines", "list files", "read a file"), ONE successful step that produces the answer is sufficient — output `FINISH` immediately after.
- **Cross-Turn Data Rule (MANDATORY)**: If the user refers to content from a previous turn (e.g., "this poem", "that result", "the text above", "统计这首诗", "这个时间", "刚才的结果"), FIRST look in the `Conversation History` section — the Assistant messages contain the actual output values. Treat those values as in-memory data — embed them directly as string literals in `python.run` code or as parameter values. Do NOT call `llm.fallback` to ask the user what they mean. Do NOT search the file system for content that already exists in the conversation history.
- **Session Artifacts Rule (MANDATORY)**: If the user refers to a file or output from a previous task (e.g., "that file", "the result I saved", "上次生成的文件"), FIRST check the `Conversation History` section for assistant messages with `task result` label — they contain the exact file path and content value. Use those values directly — do NOT guess or search the workspace.
- **net.download → python.run File Access (MANDATORY)**: When a previous `net.download` step saved a file, the framework injects `step_N_output` as the container-mapped file path (e.g., `/workspace/file.json`). To read that file in `python.run`, you MUST use the `fs.read` skill with `{"path": step_N_output_value}` — do NOT use `open()` (blocked in sandbox) and do NOT hardcode Windows host paths like `D:\Temp\...`. The correct pattern is: use `fs.read` skill with the path from `step_N_output`.
- **fs.read binary mode → python.run Image Processing (MANDATORY)**: When `fs.read` is called with `mode="binary"`, the output is a **hex-encoded string** (e.g. `"89504e47..."`), NOT raw bytes. To use it in `python.run` with Pillow or any bytes-based API, you MUST convert it first: `img_bytes = bytes.fromhex(step_N_output)`, then `img = Image.open(io.BytesIO(img_bytes))`. NEVER pass the hex string directly to `BytesIO` — that causes `TypeError: a bytes-like object is required`. To save the processed image, call `_save_binary("output.png", buf.getvalue().hex())` inside `python.run` — this writes the file to `/workspace` and outputs `{"__file__": "/workspace/output.png"}` as structured output. Do NOT use `fs.write` with `mode="binary"` for image data — the hex string is megabytes long and cannot be passed as a JSON parameter literal.
- **Unknown Skill Prohibition (MANDATORY)**: You MUST ONLY use skills listed in the `Available Skills` section. NEVER invent or guess a skill name that is not listed (e.g., `user.ask`, `user.input`, `ask_user` are NOT valid skills). If you need to ask the user a question or lack required information, use the `llm.fallback` skill instead.
- **LLM-First for Text Tasks (MANDATORY)**: For tasks that are purely about text understanding or generation — including translation, summarization, rewriting, classification, extraction, Q&A — use `llm.fallback` directly. Do NOT use `python.run` with third-party translation/NLP libraries (e.g. `googletrans`, `translate`, `nltk`, `spacy`). The LLM can handle these tasks natively without any external dependencies. Only use `python.run` when the task requires computation, data processing, file manipulation, or library-specific functionality (e.g. image processing with Pillow, data analysis with pandas).
- **ModuleNotFoundError Recovery (MANDATORY)**: If a `python.run` step failed with `ModuleNotFoundError` or `ImportError`, do NOT retry with the same code. The sandbox has a FIXED set of pre-installed packages (listed below). Instead: (1) rewrite the code using only pre-installed packages, OR (2) if the task is text-based (translation, summarization, etc.), switch to `llm.fallback`, OR (3) use a different approach that avoids the missing package entirely.
- **llm.fallback Output Structure (MANDATORY)**: When `llm.fallback` is used for executable text tasks (translation, summarization, rewriting, etc.), it returns the result directly in its `result` field. The downstream step can reference this via `step_N_output` (which will be the result text string). This means you can chain `llm.fallback` → `fs.write` directly: use `llm.fallback` to produce the text, then `fs.write` with the result as `content`. Do NOT insert an unnecessary `python.run` step between them to "organize" or "format" the output — it is already a clean text string.
- **web.search → Answer Flow (MANDATORY)**: When the goal requires searching the internet for information (current events, facts, documentation, product info, etc.), use `web.search` skill — do NOT use `browser.run` to visit search engines (Google, Bing, Baidu) directly. After `web.search` returns results, your IMMEDIATE next step MUST be `llm.fallback` to synthesize a concise answer from the search snippets. Do NOT insert `net.get`, `python.run`, or any other skill between `web.search` and `llm.fallback`. If the synthesized answer is insufficient and you need more detail, THEN you may use `net.get` to fetch a full page, followed by ANOTHER `llm.fallback` to produce the final answer. The pattern is always: `web.search → llm.fallback` (mandatory), optionally `→ net.get → llm.fallback` (if more detail needed). **CRITICAL**: Once `llm.fallback` has successfully synthesized an answer from search results, output `FINISH` immediately — do NOT add extra steps (python.run, net.get, etc.) to "verify", "parse", or "reformat" the search results. The synthesized answer IS the final answer. Do NOT use `python.run` to process web.search output — the results contain Unicode text that will cause SyntaxError if inlined into Python code.
- **Search-First for Information Queries (MANDATORY)**: When the goal is to find, look up, or query information (e.g. product specs, prices, news, facts, documentation), your FIRST step MUST be `web.search` — do NOT start with `net.get` or `net.download` to fetch a guessed URL. Even if Context Bindings provide a file path or URL from a previous task, ignore them if they are unrelated to the current goal. The correct pattern is: `web.search` first to find relevant sources, then `llm.fallback` to synthesize the answer.

**PYTHON CODE RESTRICTIONS (RestrictedPython):**
When using `python.run` skill, the code runs in a RESTRICTED sandbox with these limitations:
- ❌ NO `open()`, `file()` - Use `fs.read` or `fs.write` skills instead
- ❌ NO `import os`, `import sys`, `import subprocess` - System access blocked
- ❌ NO `Exception`, `ValueError`, `TypeError` - Use try/except with generic error handling
- ❌ NO `eval()`, `exec()`, `compile()` - Dynamic code execution blocked
- ❌ NO `__import__`, `globals()`, `locals()` - Introspection blocked
- ✅ YES: `random`, `math`, `json`, `datetime`, `re` - Safe modules allowed
- ✅ YES: Basic Python (list, dict, str, int, float, bool, for, if, while)
- ✅ YES: `print()` for output (captured automatically)
- ✅ YES pre-installed packages: `numpy`, `pandas`, `openpyxl`, `xlsxwriter`, `xlrd`, `odfpy`, `pyarrow`, `pyxlsb`, `scipy`, `matplotlib`, `sympy`, `scikit-learn`, `tabulate`, `pillow`, `opencv-python-headless` (import as `cv2`), `qrcode`, `python-barcode`, `pytesseract`, `requests`, `httpx`, `beautifulsoup4`, `lxml`, `cssselect`, `pydantic`, `python-docx`, `python-pptx`, `mammoth`, `PyPDF2`, `reportlab`, `pdfplumber`, `pymupdf` (import as `fitz`), `readability-lxml`, `trafilatura`, `markdownify`, `py7zr`, `rarfile`, `filetype`, `chardet`, `pyyaml`, `toml`, `markdown`, `orjson`, `python-dateutil`, `rapidfuzz`, `unidecode`, `sqlalchemy`, `duckdb`, `jsonschema`, `tenacity`, `defusedxml`, `cairosvg`, `aiofiles`
- ✅ YES injected helpers: `_output(value)` for structured output, `_save_binary(path, hex_str)` to write binary files directly
- ❌ DO NOT use packages not listed above (e.g. `googletrans`, `translate`, `paramiko`, `nltk`, `spacy`, `fpdf`, `weasyprint`, `camelot`, `paddleocr`) — they are NOT installed in the sandbox. If you need translation or text processing, use `llm.fallback` instead.

**DATA PASSING TO python.run (CRITICAL):**
The framework automatically writes all completed steps' outputs as JSON files into `/workspace/inputs/` before your code runs, and injects `import json` + `json.load()` statements at the top of your code.
Variable naming convention: `{step_id}_output` (e.g. `step_1_output`, `step_2_output`).
- ✅ CORRECT: Use the injected variable directly — it is already a Python object (list/dict/str/int/etc.), NOT a string:
  ```json
  {"code": "count = len(step_1_output.replace('\\n','').replace(' ',''))\nprint(count)"}
  ```
- ✅ ALSO CORRECT: If you prefer, embed the value as a string literal from Execution History.
- ❌ WRONG: `eval(step_2_output)` — the variable is already a Python object, never use eval/json.loads on it.
- ❌ WRONG: `text = previous_step_output` — use the exact `{step_id}_output` name instead.
- **Rule**: For `python.run`, always reference upstream data via `{step_id}_output` variables. The step_id matches the `Step N` label in Execution History (e.g. Step 1 → `step_1_output`). The variable is ready to use as-is.

**STRUCTURED OUTPUT FROM python.run (CRITICAL):**
The framework injects a `_output(value)` function into every python.run execution. Use it to pass structured data (list, dict, int, etc.) to downstream steps. It works alongside regular `print()` — you can print logs freely without affecting the structured output.
- ✅ CORRECT: `_output([{"src": "a.txt", "dst": "1_a.txt"}])` → next step gets a list of dicts as `step_N_output`, ready to pass directly to `fs.move` as `moves`
- ✅ CORRECT: mix logs and structured output freely:
  ```python
  print(f"Found {len(files)} files")   # log, ignored by framework
  _output(rename_pairs)                 # structured output for downstream
  ```
- ❌ WRONG: `print(json.dumps(result))` — downstream gets a raw string, not a Python object
- ❌ WRONG: omitting `_output()` when downstream needs structured data — `step_N_output` will be the raw stdout string
- **Rule**: Always call `_output(value)` when a downstream step needs to use the result as a Python object. `_output()` is already available — do NOT import or define it.

**BATCH FILE OPERATIONS:**
`fs.write`, `fs.move`, `fs.copy`, and `fs.delete` all support batch mode. Use batch whenever operating on multiple files — do NOT loop with individual calls.

- `fs.write` batch: `{"writes": [{"path": "a.txt", "content": "..."}, {"path": "b.txt", "content": "..."}]}`
- `fs.move` batch: `{"moves": [{"src": "a.txt", "dst": "1_a.txt"}, ...]}`
- `fs.copy` batch: `{"copies": [{"src": "a.txt", "dst": "backup/a.txt"}, ...]}`
- `fs.delete` batch: `{"paths": ["a.txt", "b.txt", "c.txt"], "recursive": false}`

✅ CORRECT (batch write 20 files, 1 step):
  ```json
  {"skill": "fs.write", "params": {"writes": [{"path": "test/file1.txt", "content": "This is file 1."}, {"path": "test/file2.txt", "content": "This is file 2."}]}}
  ```
✅ CORRECT (batch read multiple files, 1 step):
  ```json
  {"skill": "fs.read", "params": {"reads": [{"path": "a.txt"}, {"path": "b.txt"}]}}
  ```
✅ CORRECT (batch move, 1 step):
  ```json
  {"skill": "fs.move", "params": {"moves": [{"src": "a.txt", "dst": "1_a.txt"}, {"src": "b.txt", "dst": "2_b.txt"}]}}
  ```
✅ CORRECT (batch delete, 1 step):
  ```json
  {"skill": "fs.delete", "params": {"paths": ["tmp1.txt", "tmp2.txt", "tmp3.txt"]}}
  ```
✅ CORRECT (batch copy all files from a dir, 1 step):
  ```json
  {"skill": "fs.copy", "params": {"copies": [{"src": "src/a.txt", "dst": "dst/a.txt"}, {"src": "src/b.txt", "dst": "dst/b.txt"}]}}
  ```
❌ WRONG: calling `fs.move`/`fs.copy`/`fs.delete` N times in N separate steps for N files.
- Batch lists can be built from a `python.run` step that computes the pairs, then passed as a literal in the next step's params.

**Common Mistakes to Avoid:**
1. ❌ `except Exception as e:` → ✅ `except:` (no exception types)
2. ❌ `raise ValueError("error")` → ✅ `print("Error: ...")` (no raise)
3. ❌ `with open("file.txt") as f:` → ✅ Use `fs.read` skill
4. ❌ `import ast; ast.literal_eval(...)` → ✅ Use `json.loads()` or manual parsing

**Output Format**:
You must output a JSON object. The `thought` field MUST be under 100 words — be concise, do NOT write long reasoning chains.

Case 1: To execute a step
```json
{
  "type": "execute",
  "thought": "Why I am choosing this step...",
  "skill": "skill_name",
  "params": {
    "param_key": "param_value"
  }
}
```

Case 2: To finish the task
```json
{
  "type": "finish",
  "thought": "Why I believe the task is done...",
  "final_message": "A summary for the user."
}
```
"""

def _sanitize_host_paths(text: str, workspace_root: Optional[str]) -> str:
    """
    把 history 里的宿主机绝对路径替换成容器内路径 /workspace/...
    防止 Planner 从 history 里抠出 Windows 路径硬编码进脚本。
    """
    if not workspace_root or not text:
        return text
    # 统一用正斜杠比较，兼容 Windows 反斜杠
    root_fwd = workspace_root.replace("\\", "/").rstrip("/")
    root_back = workspace_root.replace("/", "\\").rstrip("\\")

    import re as _re
    # 匹配宿主机路径（正斜杠或反斜杠变体），替换为 /workspace/<rel>
    def _replace(m: "_re.Match") -> str:
        full = m.group(0)
        # 统一转正斜杠
        normalized = full.replace("\\", "/")
        root_norm = root_fwd
        if normalized.startswith(root_norm):
            rel = normalized[len(root_norm):].lstrip("/")
            return f"/workspace/{rel}" if rel else "/workspace"
        return full

    # 转义 root 用于正则
    escaped_fwd = _re.escape(root_fwd)
    escaped_back = _re.escape(root_back)
    pattern = f"({escaped_fwd}|{escaped_back})[^\\s\"']*"
    return _re.sub(pattern, _replace, text)


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


def _format_history(task: Task, workspace_root: Optional[str] = None) -> str:
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

                out_preview = _sanitize_host_paths(out_preview, workspace_root)
                result_str = f"Output: {out_preview}"
            else:
                error_msg = str(step.result.error)
                if len(error_msg) > 600:
                    error_msg = error_msg[:200] + "\n... [中间省略] ...\n" + error_msg[-400:]
                result_str = f"Error: {error_msg}"
        
        lines.append(f"Step {i+1}: {step.skill_name}")
        params_str = json.dumps(step.params, ensure_ascii=False)
        params_str = _sanitize_host_paths(params_str, workspace_root)
        lines.append(f"  Params: {params_str}")
        lines.append(f"  Status: {status}")
        lines.append(f"  Result: {result_str}")
        lines.append("---")

    # ── Goal Coverage Summary（第二层：面向目标判定的结构化摘要）──────────────
    # 让 LLM 看到"目标是否已满足"的明确结论，而不是只看事件流
    summary = _build_goal_coverage_summary(task, workspace_root)
    if summary:
        lines.append("")
        lines.append(summary)

    return "\n".join(lines)


def _build_goal_coverage_summary(task: Task, workspace_root: Optional[str] = None) -> str:
    """
    在 execution history 末尾注入面向目标判定的结构化摘要。

    包含：
    - 最近成功步骤的输出摘要（Latest successful outputs）
    - Finish Confidence 检查（第三层：规则化判定）
    - 明确的 Recommended action
    """
    from difflib import SequenceMatcher

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
        out = _sanitize_host_paths(out, workspace_root)
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
        
        # 格式化参数（包含类型信息）
        if params_schema:
            param_lines = []
            for param_name, param_info in params_schema.items():
                param_type = param_info.get("type", "any")
                param_desc = param_info.get("description", "")
                param_lines.append(f"    - {param_name} ({param_type}): {param_desc}")
            params_str = "\n".join(param_lines)
        else:
            params_str = "    (no parameters)"
        
        skills_desc.append(f"- {name}: {desc}\n  Parameters:\n{params_str}")
    return "\n".join(skills_desc)


class InteractiveLLMPlanner(TaskPlanner):
    """
    A Planner that outputs ONE step at a time, strictly based on history.
    """

    # 优化 4: 文件扫描忽略列表
    IGNORE_DIRS = {
        '.git', '.svn', '.hg',
        'node_modules', '__pycache__', '.pytest_cache',
        '.venv', 'venv', 'env',
        '.next', '.nuxt', 'dist', 'build',
        '.idea', '.vscode'
    }

    def __init__(self, llm_client: Any, **kwargs) -> None:
        self._llm = llm_client
        # 优化 2: 思维死循环检测
        self._last_thought = None
        self._last_action = None
        self._repeat_count = 0
        # 优化 4: 文件系统缓存
        self._fs_cache = None
        self._fs_cache_timestamp = 0

    async def make_task(
        self,
        intent: Any,
        env_context: Dict[str, Any],
        ctx: Optional[Any] = None,
        *,
        memory: Optional[str] = None,
    ) -> Task:
        # Initial call - just return an empty task. 
        # The Loop will call `next_step` immediately.
        goal = getattr(intent, "goal", "")
        intent_id = getattr(intent, "id", None)
        import uuid
        return Task(
            id=str(uuid.uuid4()),
            goal=goal, 
            steps=[], 
            intent_id=intent_id
        )

    async def next_step(
        self,
        task: Task,
        env_context: Dict[str, Any],
    ) -> Optional[Step]:
        """
        Generates the next step to append to the task.
        Returns None if task is finished.
        """
        available_skills = env_context.get("available_skills", {})
        
        # 优化 4: 获取文件系统状态
        workspace_state = self._get_workspace_state(env_context)
        
        # 优化 2: 检测思维死循环（在 Prompt 中注入警告）
        loop_warning = ""
        if self._repeat_count >= 1:
            loop_warning = """
⚠️ WARNING: You seem to be repeating the same operation and it keeps failing or returning empty results.
Please try a DIFFERENT approach:
- If browser.run returned empty output, the script failed to extract data — try a different URL or search engine
- Check if parameters are correct
- List files to verify state
- Use a different skill
- If all approaches failed, use llm.fallback to inform the user
"""
        
        # P1: 简单任务快速完成提示
        simple_task_section = ""
        if env_context.get("simple_task_mode"):
            simple_task_section = """
## ⚡ Simple Task Mode (Framework Detected)
This is a SIMPLE single-goal task. Follow these rules:
1. Complete it in as FEW steps as possible (ideally 1-2 steps).
2. Do NOT over-plan or add unnecessary verification/formatting steps.
3. Output `FINISH` as soon as the single goal is achieved.
4. For pure text tasks (translation, summarization, Q&A), use `llm.fallback` and FINISH immediately after.
"""

        # Framework-level goal tracker hint (injected when FINISH was rejected)
        goal_tracker_section = ""
        goal_tracker_hint = env_context.get("goal_tracker_hint")
        if goal_tracker_hint:
            goal_tracker_section = f"\n## ⚠️ Incomplete Sub-Goals (Framework Enforcement)\n{goal_tracker_hint}\n"

        # DedupGuard replan hint (injected when all proposed nodes were duplicates)
        dedup_hint_section = ""
        dedup_hint = env_context.get("dedup_hint")
        if dedup_hint:
            dedup_hint_section = f"\n## ⚠️ Duplicate Node Warning (Framework Enforcement)\n{dedup_hint}\n"

        # 跨轮对话历史：统一消息模型，task_result 类型消息携带结构化 metadata
        conversation_history_section = ""
        chat_history = env_context.get("chat_history", [])
        if chat_history:
            # 只取最近 10 条，避免 prompt 过长
            recent = chat_history[-10:]
            lines = ["## Conversation History (for cross-turn reference resolution)"]
            lines.append(
                "> MANDATORY: If the user refers to 'it', 'that', 'the result', 'this time', "
                "'这个时间', '那首诗', '刚才的结果', or ANY similar cross-turn reference, "
                "you MUST resolve it by finding the actual value in the Assistant messages below. "
                "Treat Assistant message content as in-memory data — embed it directly as a "
                "string literal in your skill parameters. Do NOT use llm.fallback to ask the user."
            )
            for msg in recent:
                role = msg.get("role", "user").capitalize()
                content = msg.get("content", "")
                meta = msg.get("metadata", {})
                msg_type = meta.get("message_type", "chat") if meta else "chat"

                # 截断过长的消息（binary-like payload 只展示长度）
                if _is_binary_like_payload(content):
                    content = f"[binary payload, {len(content)} chars — do NOT inline]"
                elif len(content) > 1500:
                    content = content[:1200] + "...[truncated]"

                if role == "Assistant" and msg_type == "task_result":
                    output_path = meta.get("output_path", "")
                    output_value = meta.get("output_value", "")
                    goal = meta.get("goal", "")
                    status = meta.get("status", "")
                    lines.append(f"\n[Assistant — task result | goal: {goal} | status: {status}]")
                    if output_path:
                        lines.append(f"  File Path (use this exact path): {output_path}")
                    if output_value:
                        # binary-like output_value 也只展示长度
                        if _is_binary_like_payload(output_value):
                            ov_preview = f"[binary payload, {len(output_value)} chars — do NOT inline]"
                        elif len(output_value) > 400:
                            ov_preview = output_value[:400] + "...[truncated]"
                        else:
                            ov_preview = output_value
                        lines.append(f"  Content (embed directly, do NOT re-fetch): {ov_preview}")
                    lines.append(f"  Display: {content}")
                elif role == "Assistant":
                    lines.append(f"\n[Assistant — previous reply, use this value directly if user refers to it]:\n{content}")
                else:
                    lines.append(f"\n[{role}]: {content}")
            conversation_history_section = "\n".join(lines) + "\n"

        # Context Bindings：ReferenceResolver 预计算的结构化绑定，Planner 直接使用，无需推断
        context_bindings_section = ""
        resolved_inputs = env_context.get("resolved_inputs")
        if resolved_inputs and resolved_inputs.get("confidence", 0) >= 0.5:
            lines = ["## Context Bindings (from previous turn — use ONLY if relevant to current goal)"]
            lines.append(
                "> These bindings are auto-resolved from the previous task result. "
                "Use them ONLY if the current goal explicitly refers to a previous result "
                "(e.g. 'translate that file', 'open the result', '翻译这个文件'). "
                "If the current goal is a NEW independent query (e.g. searching for information, "
                "creating something new), IGNORE these bindings entirely."
            )

            # 优先展示 typed refs（精确匹配）
            content_ref = resolved_inputs.get("content_ref")
            path_ref = resolved_inputs.get("path_ref")

            if path_ref and path_ref.get("file_path"):
                lines.append(
                    f"- [path_ref | source={path_ref.get('source_type')} | "
                    f"confidence={path_ref.get('confidence', 0):.2f}] "
                    f"file_path → use as `path` / `file_path` param: {path_ref['file_path']}"
                )
            elif resolved_inputs.get("file_path"):
                lines.append(f"- file_path (use as `path` / `file_path` param): {resolved_inputs['file_path']}")

            if content_ref and content_ref.get("content"):
                content = content_ref["content"]
                # binary-like：不展示内容，只告知长度，防止 LLM 内联截断后的脏字符串
                if _is_binary_like_payload(content):
                    preview = f"[binary payload, {len(content)} chars — use step_N_output variable, do NOT inline]"
                elif len(content) > 800:
                    preview = content[:800] + "...[truncated]"
                else:
                    preview = content
                lines.append(
                    f"- [content_ref | source={content_ref.get('source_type')} | "
                    f"confidence={content_ref.get('confidence', 0):.2f}] "
                    f"content → use as `content` / `text` param:\n```\n{preview}\n```"
                )
            elif resolved_inputs.get("content"):
                content = resolved_inputs["content"]
                if _is_binary_like_payload(content):
                    preview = f"[binary payload, {len(content)} chars — use step_N_output variable, do NOT inline]"
                elif len(content) > 800:
                    preview = content[:800] + "...[truncated]"
                else:
                    preview = content
                lines.append(f"- content (use as `content` / `text` param):\n```\n{preview}\n```")

            context_bindings_section = "\n".join(lines) + "\n"
            typed_keys = [k for k in ("content_ref", "path_ref") if resolved_inputs.get(k)]
            logger.debug(
                f"[Planner] context_bindings injected: "
                f"source={resolved_inputs['source_type']}, "
                f"confidence={resolved_inputs['confidence']:.2f}, "
                f"typed_refs={typed_keys}"
            )

        # 系统环境信息 section
        system_env_section = ""
        system_info = env_context.get("system")
        if system_info:
            default_paths = env_context.get("default_paths", {})
            system_env_section = f"""## System Environment
- Platform: {system_info.get('platform', 'unknown')}
- Username: {system_info.get('username', 'unknown')}
- Home Directory: {system_info.get('home_dir', '')}
- Desktop: {system_info.get('desktop_dir', '')}
- Downloads: {system_info.get('downloads_dir', '')}
- Documents: {system_info.get('documents_dir', '')}
- Path Separator: `{system_info.get('path_separator', '/')}`
- Workspace: {default_paths.get('workspace', '')}

> CRITICAL: Always use the exact paths above when the user refers to system directories (e.g. "桌面"→Desktop, "下载"→Downloads). Never guess Linux paths on Windows or vice versa.

"""

        prompt = f"""{INTERACTIVE_SYSTEM_PROMPT}

## Goal
{task.goal}

{simple_task_section}{system_env_section}## Available Skills
{_format_skills(available_skills)}

## Current Workspace State
{workspace_state}

{context_bindings_section}{conversation_history_section}
## Execution History (Truth)
{_format_history(task, workspace_root=env_context.get("workspace_path"))}

{loop_warning}{goal_tracker_section}{dedup_hint_section}
## Your Next Move
Return ONLY the JSON object.
"""
        # Call LLM (run sync call in thread pool to avoid blocking event loop)
        loop = asyncio.get_event_loop()
        raw_response = await loop.run_in_executor(None, self._call_llm, prompt)
        
        # Parse
        try:
            data = self._parse_json(raw_response)
        except Exception as e:
            # Fallback: if parsing fails, we might want to retry or return a "thinking" error.
            # For now, simple error.
            raise ValueError(f"LLM output malformed: {e}\nRaw: {raw_response}")

        if data.get("type") == "finish":
            # 重置死循环检测
            self._reset_loop_detection()
            return None
        
        if data.get("type") == "execute":
            skill_name = data.get("skill")
            params = data.get("params", {})
            thought = data.get("thought", "")
            
            # 优化 2: 检测思维死循环
            self._check_loop(thought, skill_name, params)
            
            # Resolve skill name (Alias support)
            resolved_cls = skill_registry.get(skill_name)
            if resolved_cls:
                skill_name = resolved_cls.spec.name

            return Step(
                id=f"step_{len(task.steps) + 1}",
                order=len(task.steps), # Add order based on current step count
                skill_name=skill_name,
                params=params,
                description=thought
            )
            
        raise ValueError(f"Unknown action type: {data.get('type')}")

    def _call_llm(self, prompt: str) -> str:
        # 统一接口：所有 LLM 客户端必须实现 call() 方法
        content, usage = self._llm.call_with_usage(prompt)
        self._last_usage: dict = usage  # 缓存供 GraphPlanner 读取
        return content

    def _parse_json(self, text: str) -> Dict[str, Any]:
        # Reuse the robust parser from simple_llm or write a simple one
        cleaned = text.strip()
        if "```" in cleaned:
            match = re.search(r'```(?:json)?(.*?)```', cleaned, re.DOTALL)
            if match:
                cleaned = match.group(1).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # ── Truncation recovery ──────────────────────────────────────────────
        # LLM output may be cut off mid-string (e.g. thought field too long).
        # If we can extract skill + params, we can still execute the step.
        type_match = re.search(r'"type"\s*:\s*"(\w+)"', cleaned)
        skill_match = re.search(r'"skill"\s*:\s*"([^"]+)"', cleaned)
        params_match = re.search(r'"params"\s*:\s*(\{.*?\})', cleaned, re.DOTALL)

        if type_match and type_match.group(1) == "finish":
            return {"type": "finish", "thought": "[truncated]", "final_message": "Task completed."}

        if type_match and type_match.group(1) == "execute" and skill_match:
            # 用括号深度匹配提取 params 对象，比正则更健壮（支持嵌套 JSON）
            params: Dict[str, Any] = {}
            params_start = cleaned.find('"params"')
            if params_start != -1:
                brace_start = cleaned.find('{', params_start + len('"params"'))
                if brace_start != -1:
                    depth = 0
                    end = brace_start
                    for i, ch in enumerate(cleaned[brace_start:], brace_start):
                        if ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                end = i
                                break
                    try:
                        params = json.loads(cleaned[brace_start:end + 1])
                    except Exception:
                        # 括号匹配也失败（params 本身被截断），尝试 regex fallback
                        if params_match:
                            try:
                                params = json.loads(params_match.group(1))
                            except Exception:
                                pass
            logger.warning(
                f"[Planner] LLM output truncated, recovered skill={skill_match.group(1)} "
                f"params_keys={list(params.keys())}"
            )
            return {
                "type": "execute",
                "thought": "[truncated — thought field exceeded token limit]",
                "skill": skill_match.group(1),
                "params": params,
            }

        # 无法恢复，抛出原始错误
        raise ValueError(f"Cannot parse or recover LLM output")

    def _get_workspace_state(self, env_context: Dict[str, Any]) -> str:
        """
        优化 4: 获取工作区文件状态（带缓存和忽略列表）
        """
        now = time.time()
        # 缓存 5 秒
        if self._fs_cache is not None and (now - self._fs_cache_timestamp) < 5:
            return self._fs_cache
        
        workspace_path = env_context.get("workspace_path", ".")
        
        try:
            all_items = os.listdir(workspace_path)
            
            # 过滤掉忽略的目录
            files = []
            dirs = []
            for item in all_items:
                if item in self.IGNORE_DIRS or item.startswith('.'):
                    continue
                
                full_path = os.path.join(workspace_path, item)
                if os.path.isfile(full_path):
                    files.append(item)
                elif os.path.isdir(full_path):
                    dirs.append(item)
            
            # 限制数量（防止爆炸）
            if len(files) > 50:
                files = files[:50] + [f"... and {len(files) - 50} more files"]
            if len(dirs) > 20:
                dirs = dirs[:20] + [f"... and {len(dirs) - 20} more directories"]
            
            state = {
                "workspace_path": workspace_path,
                "files": files,
                "directories": dirs
            }
            
            result = json.dumps(state, indent=2, ensure_ascii=False)
            
            # 更新缓存
            self._fs_cache = result
            self._fs_cache_timestamp = now
            
            return result
            
        except Exception as e:
            return f"(Failed to scan workspace: {e})"
    
    def _check_loop(self, thought: str, skill_name: str, params: Dict[str, Any]) -> None:
        """
        优化 2: 检测思维死循环
        只在 thought + action 完全一致时才计数，避免误判同 skill 不同参数的合法调用。
        """
        if self._last_thought and self._last_action:
            thought_similarity = SequenceMatcher(None, thought, self._last_thought).ratio()
            action_match = (skill_name == self._last_action[0] and params == self._last_action[1])

            if thought_similarity > 0.95 and action_match:
                self._repeat_count += 1
            else:
                self._repeat_count = 0

        # 更新历史
        self._last_thought = thought
        self._last_action = (skill_name, params)
    
    def _reset_loop_detection(self) -> None:
        """重置死循环检测状态"""
        self._last_thought = None
        self._last_action = None
        self._repeat_count = 0

    # -----------------------------------------------------------------------
    # Graph Runtime compatibility (Requirements: 6.3, 19.1-19.5)
    # -----------------------------------------------------------------------

    async def next_step_from_graph(
        self,
        graph: Any,
        env_context: Dict[str, Any],
        capability_registry: Optional[Any] = None,
    ) -> Optional[Any]:
        """
        Graph Runtime compatible entry point.

        Accepts an ExecutionGraph and returns a GraphPatch instead of a Step.
        Internally converts ExecutionGraph → Task, calls next_step(), then
        converts Step → GraphPatch.

        This preserves all existing optimizations (loop detection, fs caching,
        output truncation) while adding Graph Runtime support.

        Args:
            graph: ExecutionGraph instance
            env_context: Environment context dict
            capability_registry: Optional CapabilityRegistry for capability lookup

        Returns:
            GraphPatch or None if finished

        Requirements: 6.3, 19.1, 19.2, 19.3, 19.4, 19.5
        """
        from app.avatar.runtime.graph.models.graph_patch import (
            GraphPatch, PatchAction, PatchOperation,
        )
        from app.avatar.runtime.graph.models.step_node import StepNode, NodeStatus

        # Build env_context with capabilities if registry provided
        if capability_registry is not None and "available_skills" not in env_context:
            env_context = dict(env_context)
            env_context["available_skills"] = capability_registry.describe_capabilities()

        # Convert ExecutionGraph → Task
        task = self._execution_graph_to_task(graph)

        # Call existing next_step (preserves all optimizations)
        step = await self.next_step(task, env_context)

        if step is None:
            return GraphPatch(
                actions=[PatchAction(operation=PatchOperation.FINISH)],
                reasoning="Task completed",
            )

        # Convert Step → GraphPatch (ADD_NODE)
        node = StepNode(
            id=step.id,
            capability_name=step.skill_name,
            params=step.params,
            status=NodeStatus.PENDING,
            metadata={"description": step.description or ""},
        )
        return GraphPatch(
            actions=[PatchAction(operation=PatchOperation.ADD_NODE, node=node)],
            reasoning=step.description or "",
        )

    def _execution_graph_to_task(self, graph: Any) -> Task:
        """
        Convert ExecutionGraph to Task for use with next_step().

        Requirements: 19.1
        """
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        steps = []
        for node in graph.nodes.values():
            step = Step(
                id=node.id,
                order=len(steps),
                skill_name=node.capability_name,
                params=node.params,
                description=node.metadata.get("description", "") if node.metadata else "",
            )

            # Map node status → step status
            try:
                from app.avatar.planner.models import StepStatus, StepResult
                if node.status == NodeStatus.SUCCESS:
                    step.status = StepStatus.SUCCESS
                    # 按优先级提取输出：structured output 优先于原始 stdout
                    outputs = node.outputs or {}
                    output_val = (
                        outputs.get("output")
                        or outputs.get("result")
                        or outputs.get("content")
                        or outputs.get("stdout")
                        or outputs
                    )
                    step.result = StepResult(
                        success=True,
                        output=output_val,
                    )
                elif node.status == NodeStatus.FAILED:
                    step.status = StepStatus.FAILED
                    step.result = StepResult(
                        success=False,
                        error=node.error_message or "Unknown error",
                    )
                elif node.status == NodeStatus.RUNNING:
                    step.status = StepStatus.RUNNING
            except Exception:
                pass  # Keep default PENDING status

            steps.append(step)

        return Task(
            id=str(graph.id),
            goal=graph.goal,
            steps=steps,
            intent_id=None,
        )


register_planner("interactive_llm", InteractiveLLMPlanner)

