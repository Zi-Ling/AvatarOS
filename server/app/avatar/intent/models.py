# app/avatar/intent/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Literal
from enum import Enum

class IntentDomain(str, Enum):
    FILE = "file"
    WEB = "web"
    UI = "ui"
    SYSTEM = "system"
    OFFICE = "office"
    SCHEDULE = "schedule" # New domain for recurring tasks
    CODE = "code"         # New domain for programming/python tasks
    OTHER = "other"

class SafetyLevel(str, Enum):
    READ_ONLY = "read_only"       # e.g. read file, browse web
    MODIFY = "modify"             # e.g. write file, fill form
    DESTRUCTIVE = "destructive"   # e.g. delete file, format disk

@dataclass
class IntentSpec:
    """
    Intent v2: Structured representation of User's WHAT.
    Decoupled from HOW (Skills/Steps).
    """
    # 1. Core Identification
    id: str
    goal: str  # Human readable goal (e.g. "Create a file named test.txt")
    
    # 2. Classification
    intent_type: str  # e.g. "write_file", "browse_web", "summarize"
    domain: IntentDomain
    
    # 3. Extracted Parameters (Entities)
    params: Dict[str, Any] = field(default_factory=dict)
    
    # 4. Meta & Safety
    safety_level: SafetyLevel = SafetyLevel.READ_ONLY
    raw_user_input: str = ""
    
    # 5. Capability Routing (New in V2)
    action_type: Optional[str] = None  # e.g. "read", "write", "execute", "search"
    
    # 6. Context
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-safe dict.

        Private metadata keys (prefixed with ``_``) are stripped because they
        carry live runtime objects (e.g. ``_memory_manager``) that must never
        be persisted or serialized.
        """
        return {
            "id": self.id,
            "goal": self.goal,
            "intent_type": self.intent_type,
            "domain": self.domain.value,
            "params": self.params,
            "safety_level": self.safety_level.value,
            "raw_user_input": self.raw_user_input,
            "action_type": self.action_type,
            "metadata": {
                k: v for k, v in self.metadata.items()
                if not k.startswith("_")
            },
        }
