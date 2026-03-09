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

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Prompts
# ------------------------------------------------------------------------------

INTERACTIVE_SYSTEM_PROMPT = """You are an AI task planner for a local autonomous agent.

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
- **No "Success" Claims**: Do not say "I have finished" unless you see the evidence in the history.
- **Goal Decomposition Check (MANDATORY before FINISH)**: Before outputting `FINISH`, mentally enumerate EVERY sub-goal in the original Goal. If ANY sub-goal has no corresponding successful step in the history, you MUST execute that step next instead of finishing. Example: Goal="write a poem AND save to file" → you must see BOTH a poem-generation step AND a file-write step succeed before finishing.
- **Cross-Turn Data Rule (MANDATORY)**: If the user refers to content from a previous turn (e.g., "this poem", "that result", "the text above", "统计这首诗", "这个时间", "刚才的结果"), FIRST look in the `Conversation History` section — the Assistant messages contain the actual output values. Treat those values as in-memory data — embed them directly as string literals in `python.run` code or as parameter values. Do NOT call `llm.fallback` to ask the user what they mean. Do NOT search the file system for content that already exists in the conversation history.
- **Session Artifacts Rule (MANDATORY)**: If the user refers to a file or output from a previous task (e.g., "that file", "the result I saved", "上次生成的文件"), FIRST check the `Conversation History` section for assistant messages with `task result` label — they contain the exact file path and content value. Use those values directly — do NOT guess or search the workspace.
- **Unknown Skill Prohibition (MANDATORY)**: You MUST ONLY use skills listed in the `Available Skills` section. NEVER invent or guess a skill name that is not listed (e.g., `user.ask`, `user.input`, `ask_user` are NOT valid skills). If you need to ask the user a question or lack required information, use the `llm.fallback` skill instead.

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
- ✅ YES pre-installed packages: `numpy`, `pandas`, `openpyxl`, `scipy`, `matplotlib`, `pillow`, `requests`, `httpx`, `beautifulsoup4`, `lxml`, `pydantic`
- ❌ DO NOT use packages not listed above (e.g. `xlrd`, `xlwt`, `paramiko`) — they are NOT installed

**DATA PASSING TO python.run (CRITICAL):**
The framework automatically injects all completed steps' outputs as variables before your code runs.
Variable naming convention: `{step_id}_output` (e.g. `step_1_output`, `step_2_output`).
- ✅ CORRECT: Use the injected variable directly:
  ```json
  {"code": "count = len(step_1_output.replace('\\n','').replace(' ',''))\nprint(count)"}
  ```
- ✅ ALSO CORRECT: If you prefer, embed the value as a string literal from Execution History.
- ❌ WRONG: `text = previous_step_output` — use the exact `{step_id}_output` name instead.
- **Rule**: For `python.run`, always reference upstream data via `{step_id}_output` variables. The step_id matches the `Step N` label in Execution History (e.g. Step 1 → `step_1_output`).

**Common Mistakes to Avoid:**
1. ❌ `except Exception as e:` → ✅ `except:` (no exception types)
2. ❌ `raise ValueError("error")` → ✅ `print("Error: ...")` (no raise)
3. ❌ `with open("file.txt") as f:` → ✅ Use `fs.read` skill
4. ❌ `import ast; ast.literal_eval(...)` → ✅ Use `json.loads()` or manual parsing

**Output Format**:
You must output a JSON object.

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

def _format_history(task: Task) -> str:
    if not task.steps:
        return "(No steps executed yet)"
    
    lines = []
    for i, step in enumerate(task.steps):
        status = step.status.name if hasattr(step.status, "name") else str(step.status)
        result_str = ""
        if step.result:
            if step.result.success:
                # 优化 1: 首尾保留策略（针对长输出）
                out_preview = str(step.result.output)
                if len(out_preview) > 600:
                    # 保留前 250 字符 + 后 300 字符
                    out_preview = out_preview[:250] + "\n... [中间省略] ...\n" + out_preview[-300:]
                result_str = f"Output: {out_preview}"
            else:
                # 优化 1: 错误信息也使用首尾保留（针对 Traceback）
                error_msg = str(step.result.error)
                if len(error_msg) > 600:
                    error_msg = error_msg[:200] + "\n... [中间省略] ...\n" + error_msg[-400:]
                result_str = f"Error: {error_msg}"
        
        lines.append(f"Step {i+1}: {step.skill_name}")
        lines.append(f"  Params: {json.dumps(step.params, ensure_ascii=False)}")
        lines.append(f"  Status: {status}")
        lines.append(f"  Result: {result_str}")
        lines.append("---")
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
        if self._repeat_count >= 2:
            loop_warning = """
⚠️ WARNING: You seem to be repeating the same operation and it keeps failing.
Please try a DIFFERENT approach:
- Check if parameters are correct
- List files to verify state
- Use a different skill
- Break down the problem into smaller steps
"""
        
        # Framework-level goal tracker hint (injected when FINISH was rejected)
        goal_tracker_section = ""
        goal_tracker_hint = env_context.get("goal_tracker_hint")
        if goal_tracker_hint:
            goal_tracker_section = f"\n## ⚠️ Incomplete Sub-Goals (Framework Enforcement)\n{goal_tracker_hint}\n"

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

                # 截断过长的消息
                if len(content) > 1500:
                    content = content[:1200] + "...[truncated]"

                if role == "Assistant" and msg_type == "task_result":
                    # 结构化任务结果：直接暴露 metadata 中的关键字段，让 Planner 精确引用
                    output_path = meta.get("output_path", "")
                    output_value = meta.get("output_value", "")
                    goal = meta.get("goal", "")
                    status = meta.get("status", "")
                    lines.append(f"\n[Assistant — task result | goal: {goal} | status: {status}]")
                    if output_path:
                        lines.append(f"  File Path (use this exact path): {output_path}")
                    if output_value:
                        preview = output_value[:400] + "...[truncated]" if len(output_value) > 400 else output_value
                        lines.append(f"  Content (embed directly, do NOT re-fetch): {preview}")
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
            lines = ["## Context Bindings (Pre-resolved, use these values directly)"]
            lines.append(
                "> MANDATORY: The system has already resolved cross-turn references. "
                "Use the bound values below as direct parameter values. "
                "Do NOT call llm.fallback because you 'don't know what the user is referring to'."
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
                preview = content[:800] + "...[truncated]" if len(content) > 800 else content
                lines.append(
                    f"- [content_ref | source={content_ref.get('source_type')} | "
                    f"confidence={content_ref.get('confidence', 0):.2f}] "
                    f"content → use as `content` / `text` param:\n```\n{preview}\n```"
                )
            elif resolved_inputs.get("content"):
                content = resolved_inputs["content"]
                preview = content[:800] + "...[truncated]" if len(content) > 800 else content
                lines.append(f"- content (use as `content` / `text` param):\n```\n{preview}\n```")

            context_bindings_section = "\n".join(lines) + "\n"
            typed_keys = [k for k in ("content_ref", "path_ref") if resolved_inputs.get(k)]
            logger.debug(
                f"[Planner] context_bindings injected: "
                f"source={resolved_inputs['source_type']}, "
                f"confidence={resolved_inputs['confidence']:.2f}, "
                f"typed_refs={typed_keys}"
            )

        prompt = f"""{INTERACTIVE_SYSTEM_PROMPT}

## Goal
{task.goal}

## Available Skills
{_format_skills(available_skills)}

## Current Workspace State
{workspace_state}

{context_bindings_section}{conversation_history_section}
## Execution History (Truth)
{_format_history(task)}

{loop_warning}{goal_tracker_section}
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
        return self._llm.call(prompt)

    def _parse_json(self, text: str) -> Dict[str, Any]:
        # Reuse the robust parser from simple_llm or write a simple one
        cleaned = text.strip()
        if "```" in cleaned:
            match = re.search(r'```(?:json)?(.*?)```', cleaned, re.DOTALL)
            if match:
                cleaned = match.group(1).strip()
        return json.loads(cleaned)

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
        """
        # 计算相似度
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
                    # 按优先级提取输出：stdout > output > content > 整个 outputs dict
                    outputs = node.outputs or {}
                    output_val = (
                        outputs.get("stdout")
                        or outputs.get("output")
                        or outputs.get("content")
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

