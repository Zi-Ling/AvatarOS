from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional
import time


class EventType(str, Enum):
    # System
    SYSTEM_START = "system.start"
    SYSTEM_ERROR = "system.error"
    
    # Plan
    PLAN_GENERATED = "plan.generated"
    PLAN_UPDATED = "plan.updated"
    PLAN_REPLANNING = "plan.replanning"
    
    # Task (Task Level Updates)
    TASK_UPDATED = "task.updated"
    TASK_COMPLETED = "task.completed"
    
    # === NEW: Execution Flow Events ===
    # 思考阶段
    TASK_THINKING = "task.thinking"
    TASK_DECOMPOSED = "task.decomposed"
    
    # 执行流
    SUBTASK_START = "subtask.start"
    SUBTASK_PROGRESS = "subtask.progress"
    SUBTASK_COMPLETE = "subtask.complete"
    SUBTASK_FAILED = "subtask.failed"
    
    # Step
    STEP_START = "step.start"
    STEP_END = "step.end"
    STEP_SKIPPED = "step.skipped"
    STEP_FAILED = "step.failed"
    
    # LLM
    LLM_START = "llm.start"
    LLM_TOKEN = "llm.token"
    LLM_END = "llm.end"
    
    # Skill
    SKILL_START = "skill.start"
    SKILL_PROGRESS = "skill.progress"
    SKILL_END = "skill.end"
    
    # Filesystem
    FILE_CREATED = "file.created"
    FILE_MODIFIED = "file.modified"
    FILE_DELETED = "file.deleted"
    DIR_CREATED = "dir.created"
    DIR_DELETED = "dir.deleted"


@dataclass
class Event:
    type: EventType
    source: str  # "planner", "runner", "llm", "skill"
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    # Optional correlation IDs
    run_id: Optional[str] = None
    step_id: Optional[str] = None
