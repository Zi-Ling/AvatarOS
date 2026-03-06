from __future__ import annotations

import json
import re
import os
import time
from typing import Any, Dict, Mapping, Optional, List
from difflib import SequenceMatcher

from ..base import TaskPlanner
from ..models import Task, Step
from ..registry import register_planner
from app.avatar.skills.registry import skill_registry

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
        
        prompt = f"""{INTERACTIVE_SYSTEM_PROMPT}

## Goal
{task.goal}

## Available Skills
{_format_skills(available_skills)}

## Current Workspace State
{workspace_state}

## Execution History (Truth)
{_format_history(task)}

{loop_warning}

## Your Next Move
Return ONLY the JSON object.
"""
        # Call LLM
        raw_response = self._call_llm(prompt)
        
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
                skill_name = resolved_cls.spec.api_name or resolved_cls.spec.name

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

register_planner("interactive_llm", InteractiveLLMPlanner)

