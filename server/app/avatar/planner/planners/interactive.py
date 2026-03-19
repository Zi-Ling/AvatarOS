from __future__ import annotations

import asyncio
import json
import logging
import re
import os
import time
from typing import Any, Dict, Optional
from difflib import SequenceMatcher

from ..base import TaskPlanner
from ..models import Task, Step
from ..registry import register_planner
from app.avatar.skills.registry import skill_registry
from app.avatar.runtime.context.reference_resolver import _is_binary_like_payload

# Extracted modules
from .planner_prompt import INTERACTIVE_SYSTEM_PROMPT
from .history_formatter import (
    _sanitize_host_paths,
    _is_markup_content,
    _compress_structured_output,
    _format_history,
    _build_goal_coverage_summary,
    _format_skills,
)

logger = logging.getLogger(__name__)


class PlannerTruncationError(ValueError):
    """Raised when LLM output is truncated beyond recovery.

    Carries the recovered skill name so the controller can inject a
    targeted PlanningHint for the next planner invocation.
    """

    def __init__(self, skill_name: str, message: str):
        self.skill_name = skill_name
        super().__init__(message)


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
        
        # simple_task_section removed — planner self-regulates step count
        simple_task_section = ""

        # Framework-level goal tracker hint (injected when FINISH was rejected)
        goal_tracker_section = ""
        goal_tracker_hint = env_context.get("goal_tracker_hint")
        if goal_tracker_hint:
            goal_tracker_section = f"\n## ⚠️ Incomplete Sub-Goals (Framework Enforcement)\n{goal_tracker_hint}\n"

        # Deliverable list injection (when normalized_goal has deliverables)
        deliverable_section = ""
        _ng = env_context.get("normalized_goal")
        if _ng and getattr(_ng, "deliverables", None):
            _dels = _ng.deliverables
            _del_lines = [f"## Deliverables ({len(_dels)} required file outputs)"]
            _del_lines.append(
                "> You MUST produce ALL listed deliverables before FINISH. "
                "Each deliverable is a separate file in the requested format."
            )
            for _d in _dels:
                _hint = f" (path: {_d.path_hint})" if _d.path_hint else ""
                _del_lines.append(f"  - [{_d.id}] format=.{_d.format}{_hint}")
            deliverable_section = "\n".join(_del_lines) + "\n"

        # DedupGuard replan hint (injected when all proposed nodes were duplicates)
        dedup_hint_section = ""
        dedup_hint = env_context.get("dedup_hint")
        if dedup_hint:
            dedup_hint_section = f"\n## ⚠️ Duplicate Node Warning (Framework Enforcement)\n{dedup_hint}\n"

        # Truncation recovery hint (injected when previous planner output was truncated)
        truncation_hint_section = ""
        truncation_hint = env_context.get("truncation_hint")
        if truncation_hint:
            truncation_hint_section = f"\n## ⚠️ Output Truncation Warning (Framework Enforcement)\n{truncation_hint}\n"

        # Schema violation hint (injected when proposed action had missing required params)
        schema_hint_section = ""
        schema_hint = env_context.get("schema_violation_hint")
        if schema_hint:
            schema_hint_section = f"\n## ⚠️ Missing Required Parameters (Framework Enforcement)\n{schema_hint}\n"

        # Recovery constraints (injected by controller on truncation or schema failure)
        recovery_section = ""
        recovery_constraints = env_context.get("recovery_constraints")
        if recovery_constraints:
            lines = ["## 🔒 Recovery Mode — Output Constraints (Framework Enforced)"]
            lines.append("> Your previous output was rejected. Follow these STRICT constraints:")
            if recovery_constraints.get("force_single_action"):
                lines.append("- Output EXACTLY ONE action (one skill call). Do NOT chain multiple operations.")
            max_thought = recovery_constraints.get("max_thought_words")
            if max_thought:
                lines.append(f"- Keep `thought` under {max_thought} words.")
            max_code = recovery_constraints.get("max_code_lines")
            if max_code:
                lines.append(f"- If using python.run, keep code under {max_code} lines. Split into multiple steps if needed.")
            reason = recovery_constraints.get("reason", "")
            if reason == "truncation":
                lines.append("- Prefer simple skills (llm.fallback, fs.write) over complex python.run when possible.")
            elif reason == "schema_violation":
                lines.append("- Double-check ALL required parameters before submitting.")
            recovery_section = "\n".join(lines) + "\n"

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
                if path_ref.get("artifact_ref"):
                    lines.append(
                        f"  ⚠️ Content is large (artifact_ref={path_ref['artifact_ref']}). "
                        f"Use `fs.read` to load the file content — do NOT try to inline it."
                    )
            elif resolved_inputs.get("artifact_ref") and not resolved_inputs.get("file_path"):
                # artifact_ref without file_path — large content only accessible via artifact
                lines.append(
                    f"- [artifact_ref] Large content object (artifact_ref={resolved_inputs['artifact_ref']}). "
                    f"Use `fs.read` on the artifact path to access content."
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
            # Show container paths for workspace — python.run executes inside
            # Docker where user workspace is mounted at /workspace.
            # Host-specific paths (Desktop/Downloads/Documents) are kept as-is
            # because fs.write/fs.copy run on the host via ProcessExecutor.
            system_env_section = f"""## System Environment
- Platform: {system_info.get('platform', 'unknown')}
- Username: {system_info.get('username', 'unknown')}
- Home Directory: {system_info.get('home_dir', '')}
- Desktop: {system_info.get('desktop_dir', '')}
- Downloads: {system_info.get('downloads_dir', '')}
- Documents: {system_info.get('documents_dir', '')}
- Path Separator: `{system_info.get('path_separator', '/')}`
- Workspace: /workspace

> CRITICAL: Always use the exact paths above when the user refers to system directories (e.g. "桌面"→Desktop, "下载"→Downloads). Never guess Linux paths on Windows or vice versa.
> CRITICAL: In `python.run` code, the workspace is mounted at `/workspace`. Always use `/workspace/...` paths in python.run code, NEVER use Windows host paths like `D:\\...` or `C:\\...`.

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
{_format_history(task, workspace_root=env_context.get("workspace_path"), session_root=env_context.get("session_workspace_path"))}

{loop_warning}{goal_tracker_section}{dedup_hint_section}{truncation_hint_section}{schema_hint_section}{recovery_section}{deliverable_section}
## Your Next Move
Return ONLY the JSON object.
"""
        # Call LLM (run sync call in thread pool to avoid blocking event loop)
        loop = asyncio.get_event_loop()
        raw_response = await loop.run_in_executor(None, self._call_llm, prompt)
        
        # Parse
        try:
            data = self._parse_json(raw_response)
        except PlannerTruncationError:
            raise  # Let graph_controller handle truncation recovery
        except Exception as e:
            raise ValueError(f"LLM output malformed: {e}\nRaw: {raw_response}")

        if data.get("type") == "finish":
            self._reset_loop_detection()
            return None
        
        if data.get("type") == "execute":
            skill_name = data.get("skill")
            params = data.get("params", {})
            thought = data.get("thought", "")
            
            self._check_loop(thought, skill_name, params)
            
            resolved_cls = skill_registry.get(skill_name)
            if resolved_cls:
                skill_name = resolved_cls.spec.name

            return Step(
                id=f"step_{len(task.steps) + 1}",
                order=len(task.steps),
                skill_name=skill_name,
                params=params,
                description=thought
            )
            
        raise ValueError(f"Unknown action type: {data.get('type')}")

    def _call_llm(self, prompt: str) -> str:
        content, usage = self._llm.call_with_usage(prompt)
        self._last_usage: dict = usage
        return content

    def _parse_json(self, text: str) -> Dict[str, Any]:
        cleaned = text.strip()

        # ── Attempt 1: direct parse (covers well-formed JSON) ────────────
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # ── Attempt 2: fix raw newlines inside JSON string values ────────
        # LLMs often emit literal newlines inside JSON strings (e.g. code in
        # fs.write content) instead of \\n escape sequences.
        try:
            fixed = self._fix_json_string_newlines(cleaned)
            return json.loads(fixed)
        except (json.JSONDecodeError, Exception):
            pass

        # ── Attempt 3: strip markdown code fences then retry ─────────────
        # Only try this if direct parse failed — avoids destroying JSON that
        # contains ``` inside string values (e.g. markdown in fs.write).
        if "```" in cleaned:
            match = re.search(r'```(?:json)?\s*\n?(.*?)```', cleaned, re.DOTALL)
            if match:
                fenced = match.group(1).strip()
                try:
                    return json.loads(fenced)
                except json.JSONDecodeError:
                    pass
                try:
                    return json.loads(self._fix_json_string_newlines(fenced))
                except (json.JSONDecodeError, Exception):
                    pass

        # ── Truncation recovery ──────────────────────────────────────────────
        # Use newline-fixed text for all recovery attempts
        try:
            fixed_for_recovery = self._fix_json_string_newlines(cleaned)
        except Exception:
            fixed_for_recovery = cleaned

        type_match = re.search(r'"type"\s*:\s*"(\w+)"', cleaned)
        skill_match = re.search(r'"skill"\s*:\s*"([^"]+)"', cleaned)

        if type_match and type_match.group(1) == "finish":
            return {"type": "finish", "thought": "[truncated]", "final_message": "Task completed."}

        if type_match and type_match.group(1) == "execute" and skill_match:
            params: Dict[str, Any] = {}
            # Try extracting params from the newline-fixed text using
            # string-aware brace matching (skips braces inside JSON strings)
            params_start = fixed_for_recovery.find('"params"')
            if params_start != -1:
                brace_start = fixed_for_recovery.find('{', params_start + len('"params"'))
                if brace_start != -1:
                    end = self._find_matching_brace(fixed_for_recovery, brace_start)
                    if end > brace_start:
                        try:
                            params = json.loads(fixed_for_recovery[brace_start:end + 1])
                        except Exception:
                            pass
            # Fallback: try on original cleaned text with naive brace matching
            if not params:
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
                            pass
            logger.warning(
                f"[Planner] LLM output truncated, recovered skill={skill_match.group(1)} "
                f"params_keys={list(params.keys())}"
            )
            # 如果参数为空，说明截断太严重，无法恢复出有效 action
            if not params:
                raise PlannerTruncationError(
                    skill_name=skill_match.group(1),
                    message=(
                        f"LLM output truncated: recovered skill={skill_match.group(1)} "
                        f"but params is empty, cannot construct valid action"
                    ),
                )
            return {
                "type": "execute",
                "thought": "[truncated — thought field exceeded token limit]",
                "skill": skill_match.group(1),
                "params": params,
            }

        raise ValueError(f"Cannot parse or recover LLM output")

    @staticmethod
    def _find_matching_brace(text: str, start: int) -> int:
        """Find the matching closing brace for an opening brace at `start`.

        Unlike naive depth counting, this is JSON-string-aware: braces inside
        quoted strings are ignored. Returns the index of the matching `}`,
        or `start` if no match is found.
        """
        depth = 0
        in_string = False
        i = start
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == '\\' and in_string and i + 1 < n:
                i += 2  # skip escaped char
                continue
            if ch == '"':
                in_string = not in_string
            elif not in_string:
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        return i
            i += 1
        return start

    @staticmethod
    def _fix_json_string_newlines(text: str) -> str:
        """Escape literal newlines/tabs inside JSON string values.

        LLMs frequently emit real newlines inside JSON strings (especially in
        code content for fs.write). This walks the text character-by-character,
        tracking whether we're inside a JSON string, and replaces unescaped
        control characters with their escape sequences.
        """
        result = []
        in_string = False
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == '\\' and in_string and i + 1 < n:
                # Escaped character — pass through as-is
                result.append(ch)
                result.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = not in_string
                result.append(ch)
            elif in_string and ch == '\n':
                result.append('\\n')
            elif in_string and ch == '\r':
                result.append('\\r')
            elif in_string and ch == '\t':
                result.append('\\t')
            else:
                result.append(ch)
            i += 1
        return ''.join(result)

    def _get_workspace_state(self, env_context: Dict[str, Any]) -> str:
        """优化 4: 获取工作区文件状态（带缓存和忽略列表）"""
        now = time.time()
        if self._fs_cache is not None and (now - self._fs_cache_timestamp) < 5:
            return self._fs_cache
        
        workspace_path = env_context.get("workspace_path", ".")
        
        try:
            all_items = os.listdir(workspace_path)
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
            
            if len(files) > 50:
                files = files[:50] + [f"... and {len(files) - 50} more files"]
            if len(dirs) > 20:
                dirs = dirs[:20] + [f"... and {len(dirs) - 20} more directories"]
            
            # Always show container path to planner — python.run executes
            # inside a Docker container where workspace is mounted at /workspace.
            # Exposing host paths causes planner to hardcode them in code,
            # which then fails inside the container.
            state = {"workspace_path": "/workspace", "files": files, "directories": dirs}
            result = json.dumps(state, indent=2, ensure_ascii=False)
            self._fs_cache = result
            self._fs_cache_timestamp = now
            return result
        except Exception as e:
            return f"(Failed to scan workspace: {e})"
    
    def _check_loop(self, thought: str, skill_name: str, params: Dict[str, Any]) -> None:
        """优化 2: 检测思维死循环"""
        if self._last_thought and self._last_action:
            thought_similarity = SequenceMatcher(None, thought, self._last_thought).ratio()
            action_match = (skill_name == self._last_action[0] and params == self._last_action[1])
            if thought_similarity > 0.95 and action_match:
                self._repeat_count += 1
            else:
                self._repeat_count = 0
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
        """
        from app.avatar.runtime.graph.models.graph_patch import (
            GraphPatch, PatchAction, PatchOperation,
        )
        from app.avatar.runtime.graph.models.step_node import StepNode, NodeStatus

        if capability_registry is not None and "available_skills" not in env_context:
            env_context = dict(env_context)
            env_context["available_skills"] = capability_registry.describe_capabilities()

        task = self._execution_graph_to_task(graph)
        step = await self.next_step(task, env_context)

        if step is None:
            return GraphPatch(
                actions=[PatchAction(operation=PatchOperation.FINISH)],
                reasoning="Task completed",
            )

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
        """Convert ExecutionGraph to Task for use with next_step()."""
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

            try:
                from app.avatar.planner.models import StepStatus, StepResult
                if node.status == NodeStatus.SUCCESS:
                    step.status = StepStatus.SUCCESS
                    outputs = node.outputs or {}
                    output_val = (
                        outputs.get("output")
                        or outputs.get("result")
                        or outputs.get("content")
                        or outputs.get("stdout")
                        or outputs
                    )
                    step.result = StepResult(success=True, output=output_val)
                elif node.status == NodeStatus.FAILED:
                    step.status = StepStatus.FAILED
                    step.result = StepResult(
                        success=False,
                        error=node.error_message or "Unknown error",
                    )
                elif node.status == NodeStatus.RUNNING:
                    step.status = StepStatus.RUNNING
            except Exception:
                pass

            steps.append(step)

        return Task(
            id=str(graph.id),
            goal=graph.goal,
            steps=steps,
            intent_id=None,
        )


register_planner("interactive_llm", InteractiveLLMPlanner)
