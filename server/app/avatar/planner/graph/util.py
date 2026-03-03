from __future__ import annotations

from typing import Iterable, List

from .task_graph import TaskGraph
from .node import GraphNode
from .edge import GraphEdge


def build_graph_from_steps(
    steps: Iterable["StepLike"],  # 这里只做 duck typing，避免循环依赖
) -> TaskGraph:
    """
    根据一组 Step-like 对象构建 TaskGraph。
    要求每个 step 至少有:
        - id: str
        - depends_on: List[str]
    """
    graph = TaskGraph()

    # 先加入所有节点
    for step in steps:
        node = GraphNode(
            id=step.id,
            type="step",
            payload={"step": step},
        )
        graph.add_node(node)

    # 再加入依赖边
    for step in steps:
        for dep_id in getattr(step, "depends_on", []):
            if dep_id not in graph.nodes:
                # 对于非法依赖，先简单跳过；你可以改成 raise
                continue
            graph.add_dependency(from_id=dep_id, to_id=step.id)

    return graph


class StepLike:
    """仅用于类型提示，实际项目中可删除"""
    id: str
    depends_on: List[str]
