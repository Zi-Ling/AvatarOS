from abc import ABC, abstractmethod
from typing import Any, Union
from pathlib import Path
import json
import time

class LearningLogger(ABC):
    @abstractmethod
    def record(self, *, user_request: str, plan: Any, context: Any) -> None:
        ...

class FileLearningLogger(LearningLogger):
    def __init__(self, log_path: Union[str, Path] = "logs/learning.log") -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, *, user_request: str, plan: Any, context: Any) -> None:
        record_entry = {
            "timestamp": time.time(),
            "user_request": user_request,
            # Handle plan serialization if it's an object
            "plan_id": getattr(plan, "id", str(plan)),
            "context_task_id": getattr(context, "task_id", None),
        }
        
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record_entry, ensure_ascii=False) + "\n")
