from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
import time
import uuid

@dataclass
class SessionContext:
    """
    Global Session Context shared between Chat and Task.
    Persisted via MemoryManager.working_state.
    Acts as a "Unified Context Bus".
    """
    session_id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    # Global variables (e.g. last_output, user_preferences, current_topic)
    variables: Dict[str, Any] = field(default_factory=dict)
    
    # Workspace artifacts (files, images, code snippets generated in this session)
    # Structure: {"id": str, "type": str, "content/uri": str, "meta": dict}
    artifacts: List[Dict[str, Any]] = field(default_factory=list)

    def set_variable(self, key: str, value: Any) -> None:
        self.variables[key] = value
        self.updated_at = time.time()

    def get_variable(self, key: str, default: Any = None) -> Any:
        return self.variables.get(key, default)

    def add_artifact(self, artifact: Dict[str, Any]) -> None:
        self.artifacts.append(artifact)
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionContext":
        # Robust handling if fields are missing in old data
        return cls(
            session_id=data["session_id"],
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            variables=data.get("variables", {}),
            artifacts=data.get("artifacts", []),
        )

    @classmethod
    def create(cls, session_id: Optional[str] = None) -> "SessionContext":
        return cls(session_id=session_id or str(uuid.uuid4()))

