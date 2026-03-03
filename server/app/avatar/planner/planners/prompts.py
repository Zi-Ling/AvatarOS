# avatar/planner/planners/prompts.py
from __future__ import annotations

import json
import sys
from typing import Any, Dict, Mapping, List, Optional

try:
    import dspy
    DSPY_AVAILABLE = True
except ImportError:
    DSPY_AVAILABLE = False


# ============================================================================
# SYSTEM PROMPT（精简 30% 版本，结构清晰、无废话）
# ============================================================================

SYSTEM_PROMPT = """
    You are the Task Planner of a local autonomous agent.
    Your responsibility: generate a valid JSON plan using ONLY the skills provided.

    OUTPUT FORMAT
    ----------------
    Output MUST be valid JSON:
    {"steps": [...]}

    - NO markdown, NO explanations, NO comments.
    - Return ONLY the JSON object.

    STEP FORMAT
    ----------------
    Each step:
    {"id": "s1", "skill": "x.y", "params": {...}, "depends_on": []}

    RULES
    ----------------
    1. One step = one skill call.
    2. Use literal values only (no variables).
    3. Split multi-action requests into multiple steps.
    4. Use exact filenames from the task; if none provided, generate meaningful ones.
    5. depends_on must reflect real data flow.
    6. NEVER invent skills — use ONLY those in AVAILABLE SKILLS.

    PARAMETER RULES (CRITICAL)
    ----------------
    - Use EXACTLY the parameter names defined in AVAILABLE SKILLS.
    - NEVER invent keys (e.g., no "file_path", "path" if spec says "relative_path").
    - MUST include ALL required parameters listed for the skill.
    - If required parameters are missing from the user input, you MUST infer them from:
        (1) the task goal,
        (2) filenames mentioned in the request,
        (3) recent artifacts.
    - If still uncertain, make the best concrete guess.
    - NEVER omit a required parameter.
    - NEVER output empty "params": {}.
    - NEVER output {"steps": []}.

    STEP REFERENCE SYNTAX (for multi-step tasks)
    ----------------
    When a later step needs the output of an earlier step, use:
      {{step_id.field}}
    Examples:
      - Step s1 runs llm.generate_text → output field is "text"
        → Reference in s2: "content": "{{s1.text}}"
      - Step s1 runs file.read → output field is "content"
        → Reference in s2: "text": "{{s1.content}}"
      - Step s1 runs python.run → output field is "output"
        → Reference in s2: "data": "{{s1.output}}"
    RULES:
      - The step_id must match the "id" of the earlier step exactly.
      - The field must be an output field of that skill (check skill description).
      - depends_on MUST include the referenced step_id.
      - NEVER write placeholder text like "The content from step X goes here".
      - NEVER leave content empty when a prior step produced it.

    For writing a text file, use: {"skill":"file.write","params":{"relative_path":"<name>","content":"<text>"}}
    For reading a text file, use: {"skill":"file.read","params":{"relative_path":"<name>"}} (prefer relative_path when filename is given)
 
    python.run RULES
    ----------------
    - Use ONLY when no built-in skill suffices.
    - MUST use {"code": "..."} (never "cmd").
    - Use print() for output.
    - USE python.run for batch/loop operations (e.g., rename all files, process multiple items).
      Do NOT try to reference array elements like {{step.items[0]}} across multiple steps.
      Instead, write a single python.run step that loops over the list.

    CONTENT HANDLING
    ----------------
    - Short text: pass directly in params.
    - Long/structured content: write to file first.
    - Reference existing files by exact path from artifacts.

    SUBTASK RULES (applied only when indicated)
    ----------------
    - Respect max_steps and allowed skills.
    - python.run forbidden unless explicitly permitted.
    - Use resolved_inputs exactly as provided.

    Return ONLY valid JSON: {"steps": [...]}
    Return json.
"""


# ============================================================================
# DSPY (Optional future integration)
# ============================================================================
if DSPY_AVAILABLE:

    class TaskPlannerSignature(dspy.Signature):
        user_goal = dspy.InputField()
        original_request = dspy.InputField()
        available_skills = dspy.InputField()
        screen_state = dspy.InputField()
        context_info = dspy.InputField()
        plan_json = dspy.OutputField()

    class ReplanSignature(dspy.Signature):
        original_goal = dspy.InputField()
        error_message = dspy.InputField()
        failed_step_id = dspy.InputField()
        current_plan_status = dspy.InputField()
        available_skills = dspy.InputField()
        remaining_plan_json = dspy.OutputField()


# ============================================================================
# Basic step schema example — kept minimal for LLM understanding
# ============================================================================
EXAMPLE_STEP_SCHEMA = {
    "id": "s1",
    "skill": "file.write",
    "params": {"relative_path": "x.txt", "content": "hello"},
    "depends_on": []
}


# ============================================================================
# Helper Functions
# ============================================================================
def _safe_get_attr(obj: Any, name: str, default: Any = None) -> Any:
    if hasattr(obj, name):
        return getattr(obj, name)
    if isinstance(obj, Mapping) and name in obj:
        return obj[name]
    return default


def _clean_json_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema
    KEEP = {"type", "description", "properties", "required", "items"}
    out = {}
    for k, v in schema.items():
        if k in KEEP:
            if k in ("properties", "items") and isinstance(v, dict):
                out[k] = _clean_json_schema(v)
            else:
                out[k] = v
    return out


def _format_available_skills(available_skills: Mapping[str, Any]) -> str:
    """
    Skills list — heavily compressed.
    Only required parameters are shown.
    """
    skills_desc = []

    for name, meta in available_skills.items():
        if not isinstance(meta, Mapping):
            skills_desc.append({"name": name, "parameters": {}})
            continue

        desc = meta.get("description", "")

        full_schema = meta.get("full_schema", {})
        properties = full_schema.get("properties", {})
        required = set(full_schema.get("required", []))

        required_params = {}
        optional_count = 0

        for p, info in properties.items():
            if p.startswith("_"):
                continue
            if p in required:
                t = info.get("type", "any")
                d = info.get("description", "")
                if len(d) > 60:
                    d = d[:60] + "..."
                if d:
                    summary = f"{p}: {t} - {d}"
                else:
                    summary = f"{p}: {t}"

                required_params[p] = summary
            else:
                optional_count += 1

        if optional_count > 0:
            required_params["..."] = f"({optional_count} optional)"

        skills_desc.append({
            "name": name,
            "description": desc,
            "parameters": required_params,
        })

    return json.dumps(skills_desc, ensure_ascii=False, indent=2)


def _format_screen_model(model: Any) -> str:
    if not model:
        return "No screen data."

    elements = []
    if hasattr(model, "elements"):
        elements = model.elements
    elif isinstance(model, dict):
        elements = model.get("elements", [])

    out = []
    count = 0
    MAX = 80

    for el in elements:
        d = el if isinstance(el, dict) else el.__dict__
        if not d.get("is_visible", True):
            continue

        eid = d.get("id", "?")
        role = d.get("role", "element")
        name = d.get("name", "")
        center = d.get("center", (0, 0))

        out.append(f"- [{eid}] {role} '{name}' at {center}")

        count += 1
        if count >= MAX:
            out.append("(truncated)")
            break

    return "\n".join(out) if out else "Screen visible, no actionable elements."


# ============================================================================
# Build Planner Prompt
# ============================================================================
def build_planner_prompt(
    intent: Any,
    available_skills: Mapping[str, Any],
    conversation_context: Optional[Dict[str, Any]] = None,
    user_preferences: Optional[Dict[str, Any]] = None,
    similar_cases: Optional[List[Dict[str, Any]]] = None,
    recent_artifacts: Optional[List[Dict[str, Any]]] = None,
) -> str:

    goal = _safe_get_attr(intent, "goal", "")
    intent_type = _safe_get_attr(intent, "intent_type", "")
    intent_id = _safe_get_attr(intent, "id", "")
    raw_input = _safe_get_attr(intent, "raw_user_input", "")
    params = _safe_get_attr(intent, "params", {})
    constraints = _safe_get_attr(intent, "constraints", {})
    context = _safe_get_attr(intent, "context", {}) or {}

    # Screen
    screen_desc = _format_screen_model(context.get("screen_model"))

    # Clean context (remove huge fields)
    context_dump = context.copy()
    context_dump.pop("available_skills", None)
    context_dump.pop("screen_model", None)

    # ---- conversation（只保留最近 4 条）
    conv_text = ""
    if conversation_context and conversation_context.get("messages"):
        msgs = conversation_context["messages"][-4:]
        conv_text = "\n# Recent Context\n" + "\n".join(
            f"{m.get('role')}: {m.get('content','')[:80]}"
            for m in msgs
        )

    # ---- artifacts（只取 3 个）+ 上一个任务结果
    arti_text = ""
    if recent_artifacts:
        arti_text = "\n# Recent Files & Context\n"
        for a in recent_artifacts[:5]:
            art_type = a.get("type", "")
            
            # 上一个任务的结构化结果（最有价值的上下文）
            if art_type == "previous_task_result":
                desc = a.get("description", "")
                output_path = a.get("output_path", "")
                if output_path:
                    arti_text += f"- [上一个任务产出] {desc} → {output_path}\n"
                elif desc:
                    arti_text += f"- [上一个任务] {desc}\n"
            else:
                # 标准 artifact（文件产出物）
                uri = a.get("uri", a.get("path", ""))
                fname = a.get("meta", {}).get("filename", uri.split("/")[-1] if uri else "")
                if uri:
                    arti_text += f"- {fname} → {uri}\n"

    # ---- user preferences（几行）
    pref_text = ""
    if user_preferences:
        pref_text = "\n# User Preferences\n"
        for k, v in user_preferences.items():
            pref_text += f"- {k}: {v}\n"

    # ---- similar cases（最多 3 个）
    sim_text = ""
    if similar_cases:
        shown = 0
        sim_text = "\n# Similar Tasks\n"
        for c in similar_cases:
            if c.get("distance", 1) > 0.5:
                continue
            doc = c.get("document", "").split("\n")[0][:80]
            sim_text += f"- {doc}\n"
            shown += 1
            if shown >= 3:
                break

    # ---- Subtask metadata
    md = _safe_get_attr(intent, "metadata", {}) or {}
    resolved_inputs = md.get("resolved_inputs", {})
    is_subtask = md.get("is_subtask", False)
    subtask_type = md.get("subtask_type", "")
    parent_goal = md.get("parent_goal", "")

    subtask_block = ""
    forbidden_block = ""

    # If subtask: forbid python.run unless whitelisted
    PYTHON_RUN_ALLOWED = {"general_execution", "content_generation"}

    if is_subtask:
        stype = subtask_type.value if hasattr(subtask_type, "value") else str(subtask_type)

        if stype not in PYTHON_RUN_ALLOWED:
            forbidden_block = "\nFORBIDDEN SKILLS: python.run\n"

        subtask_block = f"""
# SUBTASK
Parent: {parent_goal}
Goal: {goal}
Type: {stype}
{forbidden_block}
"""

    resolved_block = ""
    if resolved_inputs:
        resolved_block = "\n# Resolved Inputs\n" + json.dumps(resolved_inputs, ensure_ascii=False, indent=2)

    # Skills JSON
    skills_json = _format_available_skills(available_skills)

    # Compose final prompt
    prompt = f"""
{SYSTEM_PROMPT}

{subtask_block}

# Goal
{goal}

# Original Request
"{raw_input}"

{conv_text}
{arti_text}
{pref_text}
{sim_text}
{resolved_block}

# Intent Info
- id: {intent_id}
- type: {intent_type}
- Required Params: {json.dumps(params, ensure_ascii=False)}"""

    # 如果有提取的参数，添加明确提示让 Planner 直接使用
    extracted = md.get("extracted_params", {})
    if extracted:
        prompt += f"""

# Pre-extracted Parameters (USE THESE DIRECTLY in step params)
{json.dumps(extracted, ensure_ascii=False, indent=2)}
NOTE: These values were extracted from the user's request. Use them as-is in your step params."""

    prompt += f"""

# Constraints
{json.dumps(constraints, ensure_ascii=False, indent=2)}

# Context
{json.dumps(context_dump, ensure_ascii=False, indent=2)}

# Screen
{screen_desc}

# AVAILABLE SKILLS
{skills_json}
--- END SKILLS ---

Return ONLY valid JSON: an object with field "steps" (array of steps).
"""

    return prompt.strip()


# ============================================================================
# Replan Prompt
# ============================================================================
def build_replan_prompt(task: Any, failed_step: Any, error_msg: str, available_skills: Mapping[str, Any]) -> str:
    """
    构建 Replan Prompt（带内容截断，防止400错误）
    """
    skills_json = _format_available_skills(available_skills)

    steps_summary = []
    # 收集成功步骤的输出信息，供 LLM 引用
    successful_outputs = []

    for s in task.steps:
        status = getattr(s, "status", "")
        if hasattr(status, "name"):
            status = status.name
        steps_summary.append({
            "id": getattr(s, "id", ""),
            "skill": getattr(s, "skill_name", ""),
            "status": status,
            "params": getattr(s, "params", {})
        })

        # 收集成功步骤的输出字段，告诉 LLM 可以引用哪些变量
        if status == "SUCCESS":
            result = getattr(s, "result", None)
            if result:
                output = getattr(result, "output", None)
                if isinstance(output, dict):
                    output_fields = [k for k in output.keys() if not k.startswith("_") and output[k] is not None]
                    if output_fields:
                        successful_outputs.append({
                            "step_id": getattr(s, "id", ""),
                            "skill": getattr(s, "skill_name", ""),
                            "available_fields": output_fields,
                            "reference_syntax": {f: f"{{{{{getattr(s, 'id', '')}.{f}}}}}" for f in output_fields}
                        })

    failed_step_id = getattr(failed_step, "id", "unknown")
    
    # 错误消息截断
    MAX_ERROR_LENGTH = 500
    if len(error_msg) > MAX_ERROR_LENGTH:
        error_msg = error_msg[:MAX_ERROR_LENGTH] + "... (truncated)"
    
    # 计划摘要截断
    MAX_STEPS_IN_SUMMARY = 10
    if len(steps_summary) > MAX_STEPS_IN_SUMMARY:
        success_steps = [s for s in steps_summary if s.get("status") == "SUCCESS"]
        failed_steps = [s for s in steps_summary if s.get("status") == "FAILED"]
        other_steps = [s for s in steps_summary if s not in success_steps and s not in failed_steps]
        kept_steps = success_steps[:5] + failed_steps + other_steps[:2]
        steps_summary = kept_steps[:MAX_STEPS_IN_SUMMARY]

    # 构建成功步骤输出引用说明
    outputs_block = ""
    if successful_outputs:
        outputs_block = f"""
AVAILABLE OUTPUTS FROM SUCCESSFUL STEPS
----------------------------------------
Use {{{{step_id.field}}}} syntax to reference these in your new steps.
{json.dumps(successful_outputs, ensure_ascii=False, indent=2)}

EXAMPLE: If step s1 succeeded with field "text", use: "content": "{{{{s1.text}}}}"
NEVER write placeholder text. ALWAYS use the reference syntax above.
"""

    return f"""
You are the Error Recovery Planner.

Your job: fix the failed plan and output ONLY the remaining correct steps.

FORMAT:
{{"steps":[ ... ]}}

BATCH OPERATION RULE (CRITICAL)
---------------------------------
If the task involves processing MULTIPLE items (e.g., rename all files, process a list),
do NOT generate one step per item. Instead, use a SINGLE python.run step that loops over the list.
Example for renaming all .txt files:
{{"id":"s2","skill":"python.run","params":{{"code":"import os\\nfor f in os.listdir('.'):\\n    if f.endswith('.txt') and not f.startswith('1_'):\\n        os.rename(f, '1_' + f)\\nprint('done')"}},"depends_on":[]}}

FAILED STEP
-----------
ID: {failed_step_id}
Error: {error_msg}

CURRENT PLAN
------------
{json.dumps(steps_summary, ensure_ascii=False, indent=2)}
{outputs_block}
AVAILABLE SKILLS
----------------
{skills_json}

Return only the corrected {{"steps":[...]}}.
""".strip()
