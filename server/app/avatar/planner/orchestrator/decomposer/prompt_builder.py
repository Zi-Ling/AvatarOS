"""
分解 Prompt 构建器
"""
from __future__ import annotations

from typing import Any, Dict


class DecomposePromptBuilder:
    """
    构建任务分解的 Prompt (轻量化版本)
    
    职责：
    - 仅关注"做什么" (Goal)
    - 不关注"怎么做" (Skills)
    - 移除所有冗余 Context
    """
    
    @staticmethod
    def build(
        user_request: str,
        intent: Any,
        env_context: Dict[str, Any]
    ) -> str:
        """
        构建任务分解的 Prompt (极简版)
        """
        
        prompt = f"""You are a Strategic Task Decomposer. Break down the User Request into logical Subtasks.

USER REQUEST: "{user_request}"

SubTask Types:
- `general_execution`: Default. Mixed logic, multi-step, Python scripts.
- `content_generation`: Writing stories, poems, emails.
- `file_io`: Move/Copy/Delete files.
- `information_extraction`: Search/Extract data.
- `gui_operation`: App interaction.

Output JSON Array (No markdown):
[
  {{
    "id": "s1",
    "type": "general_execution", 
    "goal": "Description of what to achieve (e.g. 'Read files and calculate sum')",
    "depends_on": [] 
  }},
  {{
    "id": "s2", 
    "type": "general_execution",
    "goal": "Description of next step",
    "depends_on": ["s1"]
  }}
]

Rules:
1. Keep it High-Level. "Read file A, B, C and merge" -> ONE subtask (general_execution).
2. "Create file A, then file B" -> TWO subtasks (s1, s2).
3. Use `depends_on` for ordering.
4. Output JSON ONLY.
"""
        return prompt
    
    @staticmethod
    def build_simplified(
        user_request: str,
        intent: Any,
        env_context: Dict[str, Any]
    ) -> str:
        """
        Same as build() - we are already simplified enough.
        """
        return DecomposePromptBuilder.build(user_request, intent, env_context)
