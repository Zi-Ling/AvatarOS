from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from difflib import SequenceMatcher

from ..base import TaskPlanner
from ..models import Task, Step
from ..registry import register_planner
from app.avatar.skills.registry import skill_registry
from app.avatar.runtime.context.reference_resolver import _is_binary_like_payload
from app.llm.types import LLMMessage, LLMRole, LLMResponse, ToolDefinition

# Extracted modules
from .planner_prompt import INTERACTIVE_SYSTEM_PROMPT
from .history_formatter import (
    _format_history,
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
        # Direction correction: soft off-track detection
        self._off_track_count = 0
        # 通用执行器不算偏航
        self._generic_skills = frozenset({"python.run", "browser.run", "llm.fallback"})
        # 优化 4: 文件系统缓存
        self._fs_cache = None
        self._fs_cache_timestamp = 0
        # Direct reply message from FINISH (no skill execution needed)
        self._last_final_message: str = ""

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
        available_skills = env_context.get("available_skills", {})  # kept for env_context passthrough
        
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

        # Direction correction: soft off-track warning
        direction_warning = ""
        if self._off_track_count >= 2:
            _top_skills = env_context.get("router_scored_skills", [])
            _top_names = [s.get("name", s) if isinstance(s, dict) else str(s) for s in _top_skills[:3]]
            if _top_names:
                direction_warning = (
                    f"\n⚠️ DIRECTION CHECK: Your recent skill choices don't align with the "
                    f"user's intent. The most relevant skills for this goal are: "
                    f"{', '.join(_top_names)}. Please reconsider your approach and "
                    f"prioritize these skills unless you have a specific reason not to.\n"
                )
        
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

        # 跨轮对话历史：两层记忆 + 滑动窗口
        # Layer 1: 结构化事实摘要（覆盖全部历史）
        # Layer 2: 最近 5 条完整消息（保证近期上下文精确）
        conversation_history_section = ""
        conversation_summary_section = ""
        chat_history = env_context.get("chat_history", [])

        # Inject conversation summary if available (covers older messages)
        _conv_summary = env_context.get("conversation_summary")
        if _conv_summary:
            try:
                from app.avatar.memory.conversation_summary import format_summary_for_prompt
                conversation_summary_section = format_summary_for_prompt(_conv_summary)
            except Exception:
                pass

        if chat_history:
            # 保留最近 5 条完整消息（近期上下文精确）
            recent = chat_history[-5:]
            lines = ["## Conversation History (recent — for cross-turn reference resolution)"]
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

        # 注入当前日期，防止 LLM 训练数据截止导致年份错误
        from datetime import date as _date
        _today = _date.today()
        _current_date_section = (
            f"## Current Date\n"
            f"Today is {_today.isoformat()} ({_today.strftime('%A')}). "
            f"Year is {_today.year}. Use this date for any time-sensitive queries.\n\n"
        )

        # 检测用户语言，注入回复语言指令
        _user_lang = "Chinese" if any('\u4e00' <= c <= '\u9fff' for c in task.goal) else "English"
        _reply_language_section = (
            f"## Reply Language\n"
            f"The user's language is {_user_lang}. All user-facing text "
            f"(final_message, clarifications, error messages) MUST be in {_user_lang}.\n\n"
        )

        prompt = f"""{INTERACTIVE_SYSTEM_PROMPT}

## Goal
{task.goal}

{_current_date_section}{_reply_language_section}{simple_task_section}{system_env_section}## Available Skills
(Provided as callable tools — see tool definitions)

## Current Workspace State
{workspace_state}

{context_bindings_section}{conversation_summary_section}{conversation_history_section}
## Execution History (Truth)
{_format_history(task, workspace_root=env_context.get("workspace_path"), session_root=env_context.get("session_workspace_path"))}

{loop_warning}{direction_warning}{goal_tracker_section}{dedup_hint_section}{truncation_hint_section}{schema_hint_section}{recovery_section}{deliverable_section}
## Your Next Move
Call a tool to execute the next step, or reply with text if the goal is achieved or no tool is needed.
"""
        # Build tool definitions and reverse name mapping from skill registry
        tool_defs, name_reverse_map = self._build_tool_definitions()

        # Build messages for chat API (system + user)
        messages = [
            LLMMessage(role=LLMRole.SYSTEM, content=prompt),
            LLMMessage(role=LLMRole.USER, content=task.goal),
        ]

        # Call LLM with tools (run sync call in thread pool to avoid blocking event loop)
        loop = asyncio.get_event_loop()
        response: LLMResponse = await loop.run_in_executor(
            None, self._call_llm_with_tools, messages, tool_defs,
        )

        # Parse response: tool_calls → execute, text content → finish
        if response.tool_calls and len(response.tool_calls) > 0:
            tc = response.tool_calls[0]  # Take first tool call
            # Reverse map API name (e.g. "web-search") back to registry name ("web.search")
            skill_name = name_reverse_map.get(tc.name, tc.name)
            params = tc.arguments or {}
            thought = response.content or ""

            self._check_loop(thought, skill_name, params)
            self._check_direction(skill_name, env_context)

            resolved_cls = skill_registry.get(skill_name)
            if resolved_cls:
                skill_name = resolved_cls.spec.name

            return Step(
                id=f"step_{len(task.steps) + 1}",
                order=len(task.steps),
                skill_name=skill_name,
                params=params,
                description=thought,
            )

        # No tool calls → LLM chose to reply with text → FINISH
        # But first check if this was caused by output truncation
        if response.finish_reason == "length" or (
            response.usage
            and response.usage.get("completion_tokens", 0) > 4000
            and not response.content
        ):
            raise PlannerTruncationError(
                skill_name="unknown",
                message=(
                    "LLM output was truncated (finish_reason=length), "
                    "tool_calls could not be parsed. "
                    f"completion_tokens={response.usage.get('completion_tokens', '?')}"
                ),
            )

        self._reset_loop_detection()
        self._last_final_message = response.content or ""
        return None

    def _call_llm(self, prompt: str) -> str:
        content, usage = self._llm.call_with_usage(prompt)
        self._last_usage: dict = usage
        return content

    def _call_llm_with_tools(
        self, messages: List[LLMMessage], tools: List[ToolDefinition],
    ) -> LLMResponse:
        """Call LLM with tool definitions. Returns full LLMResponse."""
        response = self._llm.chat(messages, tools=tools)
        self._last_usage: dict = response.usage or {}
        return response

    @staticmethod
    def _build_tool_definitions() -> tuple[List[ToolDefinition], Dict[str, str]]:
        """Convert all registered skills to LLM ToolDefinition objects.

        Skill names use dots (e.g. ``web.search``) but many LLM APIs
        (DeepSeek, OpenAI) require tool names to match ``^[a-zA-Z0-9_-]+$``.
        We replace ``.`` → ``-`` when building tool definitions and return
        a reverse mapping dict (api_name → original_name) for lookup.

        Returns:
            (tool_definitions, reverse_map) where reverse_map maps
            e.g. ``"web-search"`` → ``"web.search"``.
        """
        schemas = skill_registry.to_tool_schemas()
        tools = []
        reverse_map: Dict[str, str] = {}
        for s in schemas:
            original_name = s["name"]
            api_name = original_name.replace(".", "-")
            reverse_map[api_name] = original_name
            tools.append(ToolDefinition(
                name=api_name,
                description=s["description"],
                parameters=s["parameters"],
            ))
        return tools, reverse_map

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

    def _check_direction(self, skill_name: str, env_context: Dict[str, Any]) -> None:
        """Soft off-track detection: count consecutive uses of skills not in Router top-3.

        Generic executors (python.run, browser.run, llm.fallback) are exempt —
        they're used for many intent types and don't indicate direction error.
        """
        if skill_name in self._generic_skills:
            return  # generic executors are always on-track
        top_skills = env_context.get("router_scored_skills", [])
        top_names = set()
        for s in top_skills[:3]:
            if isinstance(s, dict):
                top_names.add(s.get("name", ""))
            else:
                top_names.add(str(s))
        if not top_names:
            return  # no router info, can't judge
        if skill_name in top_names:
            self._off_track_count = 0
        else:
            self._off_track_count += 1
    
    def _reset_loop_detection(self) -> None:
        """重置死循环检测状态"""
        self._last_thought = None
        self._last_action = None
        self._repeat_count = 0
        self._off_track_count = 0

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
            _final_message = getattr(self, '_last_final_message', '') or ''
            return GraphPatch(
                actions=[PatchAction(operation=PatchOperation.FINISH)],
                reasoning="Task completed",
                metadata={"final_message": _final_message},
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
