from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Iterable, Set

from .node import GraphNode
from .edge import GraphEdge


@dataclass
class TaskGraph:
    """
    简单的有向无环图（DAG）实现，用于描述 Planner 生成的任务结构。
    """

    nodes: Dict[str, GraphNode] = field(default_factory=dict)
    outgoing: Dict[str, List[GraphEdge]] = field(default_factory=dict)
    incoming: Dict[str, List[GraphEdge]] = field(default_factory=dict)

    # ---------- 节点操作 ----------

    def add_node(self, node: GraphNode) -> None:
        if node.id in self.nodes:
            raise ValueError(f"Node {node.id} already exists")
        self.nodes[node.id] = node
        self.outgoing.setdefault(node.id, [])
        self.incoming.setdefault(node.id, [])

    def get_node(self, node_id: str) -> GraphNode:
        return self.nodes[node_id]

    # ---------- 边操作 ----------

    def add_edge(self, edge: GraphEdge) -> None:
        if edge.from_id not in self.nodes or edge.to_id not in self.nodes:
            raise ValueError("Both nodes must be added before creating an edge")

        # 简单防止重复边
        if edge not in self.outgoing[edge.from_id]:
            self.outgoing[edge.from_id].append(edge)
            self.incoming[edge.to_id].append(edge)

    def add_dependency(self, from_id: str, to_id: str) -> None:
        self.add_edge(GraphEdge(from_id=from_id, to_id=to_id))

    # ---------- 查询 ----------

    def parents_of(self, node_id: str) -> List[GraphNode]:
        return [self.nodes[e.from_id] for e in self.incoming.get(node_id, [])]

    def children_of(self, node_id: str) -> List[GraphNode]:
        return [self.nodes[e.to_id] for e in self.outgoing.get(node_id, [])]

    def roots(self) -> Iterable[GraphNode]:
        """没有任何依赖的节点。"""
        for node_id, edges in self.incoming.items():
            if not edges:
                yield self.nodes[node_id]

    def leaves(self) -> Iterable[GraphNode]:
        """没有被其他节点依赖的节点。"""
        for node_id, edges in self.outgoing.items():
            if not edges:
                yield self.nodes[node_id]

    # ---------- 拓扑排序 ----------

    def topological_sort(self) -> List[GraphNode]:
        """
        Kahn 算法简单实现。
        若图中有环，会抛出 ValueError。
        """
        in_degree: Dict[str, int] = {
            node_id: len(self.incoming[node_id]) for node_id in self.nodes
        }
        ready: List[str] = [nid for nid, deg in in_degree.items() if deg == 0]

        ordered: List[str] = []

        while ready:
            nid = ready.pop(0)
            ordered.append(nid)

            for edge in self.outgoing.get(nid, []):
                to_id = edge.to_id
                in_degree[to_id] -= 1
                if in_degree[to_id] == 0:
                    ready.append(to_id)

        if len(ordered) != len(self.nodes):
            raise ValueError("TaskGraph contains a cycle")

        return [self.nodes[nid] for nid in ordered]

    # ---------- 工具 ----------

    def subgraph_from(self, root_ids: Iterable[str]) -> "TaskGraph":
        """
        生成一个只包含 root_ids 及其后代的子图。
        """
        visited: Set[str] = set()
        stack = list(root_ids)

        while stack:
            nid = stack.pop()
            if nid in visited:
                continue
            visited.add(nid)
            for child in self.children_of(nid):
                stack.append(child.id)

        sub = TaskGraph()
        for nid in visited:
            sub.add_node(self.nodes[nid])
        for nid in visited:
            for e in self.outgoing.get(nid, []):
                if e.to_id in visited:
                    sub.add_edge(e)
        return sub
