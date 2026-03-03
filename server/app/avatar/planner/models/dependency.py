from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Dependency:
    """
    纯数据结构：表示 step 之间的依赖关系。
    现在你可能用不到，后面做更复杂分析时会用。
    """
    from_step_id: str
    to_step_id: str
    type: str = "requires"
