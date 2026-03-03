from __future__ import annotations

import json
import re
from typing import Any, Dict, Mapping, Optional, List

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
                # Truncate long outputs for context window
                out_preview = str(step.result.output)
                if len(out_preview) > 500:
                    out_preview = out_preview[:500] + "...(truncated)"
                result_str = f"Output: {out_preview}"
            else:
                result_str = f"Error: {step.result.error}"
        
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
        # Simplified schema for prompts
        params = meta.get("params_schema", {}) if isinstance(meta, dict) else {}
        skills_desc.append(f"- {name}: {desc}\n  Params: {list(params.keys())}")
    return "\n".join(skills_desc)


class InteractiveLLMPlanner(TaskPlanner):
    """
    A Planner that outputs ONE step at a time, strictly based on history.
    """

    def __init__(self, llm_client: Any, **kwargs) -> None:
        self._llm = llm_client

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
        
        prompt = f"""{INTERACTIVE_SYSTEM_PROMPT}

## Goal
{task.goal}

## Available Skills
{_format_skills(available_skills)}

## Execution History (Truth)
{_format_history(task)}

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
            return None
        
        if data.get("type") == "execute":
            skill_name = data.get("skill")
            
            # Resolve skill name (Alias support)
            resolved_cls = skill_registry.get(skill_name)
            if resolved_cls:
                skill_name = resolved_cls.spec.api_name or resolved_cls.spec.name

            return Step(
                id=f"step_{len(task.steps) + 1}",
                order=len(task.steps), # Add order based on current step count
                skill_name=skill_name,
                params=data.get("params", {}),
                description=data.get("thought", "")
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

register_planner("interactive_llm", InteractiveLLMPlanner)

