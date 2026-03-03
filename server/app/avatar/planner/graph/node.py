from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GraphNode:
    """
    图中的一个节点，对应一个 Step（或 Task）。
    为了避免循环导入，这里不直接依赖 Step 类型，只保存 id / payload。
    """
    id: str
    type: str = "step"          # e.g. "step" / "task" / "group"
    payload: Dict[str, Any] = field(default_factory=dict)

    # 运行期字段（可选）
    status: str = "pending"     # pending / running / success / failed / skipped
    error: Optional[str] = None

    def __hash__(self) -> int:
        return hash(self.id)
