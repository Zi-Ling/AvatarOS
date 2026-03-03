from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GraphEdge:
    """
    有向边：from_node -> to_node
    表示 to_node 依赖 from_node 的结果。
    """
    from_id: str
    to_id: str
    type: str = "dependency"  # 预留：之后可以有 "data-flow" 等类型
