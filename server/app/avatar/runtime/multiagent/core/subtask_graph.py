"""SubtaskGraph, SubtaskNode, SubtaskEdge — 子任务图.

Planner 输出的结构化任务分解结果。依赖关系由 SubtaskEdge 权威表达，
节点自身不维护 dependencies 字段。

Requirements: 4.1, 4.2, 4.3, 4.6, 4.7, 24.2
"""
from __future__ import annotations

import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.multiagent.roles.role_spec import RoleSpecRegistry
    from app.avatar.runtime.multiagent.roles.agent_instance import SuccessCriterion


@dataclass
class SubtaskNode:
    """子任务节点. 依赖关系由 SubtaskEdge 权威表达."""
    node_id: str = ""
    description: str = ""
    responsible_role: str = ""
    input_bindings: Dict[str, str] = field(default_factory=dict)
    output_contract: Dict[str, Any] = field(default_factory=dict)
    success_criteria: List[Any] = field(default_factory=list)  # list[SuccessCriterion]
    risk_level: str = "low"
    is_parallel: bool = False
    status: str = "pending"  # pending | running | completed | failed
    result: Optional[Dict[str, Any]] = None


@dataclass
class SubtaskEdge:
    """子任务依赖边."""
    source_node_id: str = ""
    target_node_id: str = ""
    data_mapping: Dict[str, str] = field(default_factory=dict)


@dataclass
class SubtaskGraph:
    """子任务图."""
    graph_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    nodes: Dict[str, SubtaskNode] = field(default_factory=dict)
    edges: List[SubtaskEdge] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # 分层校验
    # ------------------------------------------------------------------

    def validate_dag(self) -> tuple[bool, List[str]]:
        """循环依赖检测（拓扑排序）. 返回 (is_valid, error_messages)."""
        in_degree: Dict[str, int] = {nid: 0 for nid in self.nodes}
        adj: Dict[str, List[str]] = defaultdict(list)
        for edge in self.edges:
            if edge.target_node_id in in_degree:
                in_degree[edge.target_node_id] += 1
            adj[edge.source_node_id].append(edge.target_node_id)

        queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
        visited = 0
        while queue:
            node = queue.popleft()
            visited += 1
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited != len(self.nodes):
            cycle_nodes = [nid for nid, deg in in_degree.items() if deg > 0]
            return False, [f"Cycle detected involving nodes: {cycle_nodes}"]
        return True, []

    def validate_required_fields(self) -> tuple[bool, List[str]]:
        """必填字段检查."""
        errors: List[str] = []
        for nid, node in self.nodes.items():
            if not node.node_id:
                errors.append(f"Node missing node_id")
            if not node.description:
                errors.append(f"Node '{nid}' missing description")
            if not node.responsible_role:
                errors.append(f"Node '{nid}' missing responsible_role")
        return (len(errors) == 0, errors)

    def validate_schema_compliance(self) -> tuple[bool, List[str]]:
        """Schema 合规校验."""
        errors: List[str] = []
        for nid, node in self.nodes.items():
            if not isinstance(node.output_contract, dict):
                errors.append(f"Node '{nid}' output_contract must be dict")
            if not isinstance(node.input_bindings, dict):
                errors.append(f"Node '{nid}' input_bindings must be dict")
        return (len(errors) == 0, errors)

    def validate_role_permissions(
        self, registry: "RoleSpecRegistry"
    ) -> tuple[bool, List[str]]:
        """角色权限校验."""
        errors: List[str] = []
        for nid, node in self.nodes.items():
            spec = registry.get(node.responsible_role)
            if spec is None:
                errors.append(f"Node '{nid}' role '{node.responsible_role}' not registered")
        return (len(errors) == 0, errors)

    # ------------------------------------------------------------------
    # 图操作
    # ------------------------------------------------------------------

    def get_parallel_groups(self) -> List[List[str]]:
        """获取可并行执行的节点组（按拓扑层级）."""
        in_degree: Dict[str, int] = {nid: 0 for nid in self.nodes}
        adj: Dict[str, List[str]] = defaultdict(list)
        for edge in self.edges:
            if edge.target_node_id in in_degree:
                in_degree[edge.target_node_id] += 1
            adj[edge.source_node_id].append(edge.target_node_id)

        groups: List[List[str]] = []
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        while queue:
            groups.append(list(queue))
            next_queue: List[str] = []
            for node in queue:
                for neighbor in adj[node]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_queue.append(neighbor)
            queue = next_queue
        return groups

    def get_downstream_subgraph(self, node_id: str) -> Set[str]:
        """获取指定节点的所有下游依赖节点（含自身）."""
        adj: Dict[str, List[str]] = defaultdict(list)
        for edge in self.edges:
            adj[edge.source_node_id].append(edge.target_node_id)

        visited: Set[str] = set()
        queue = deque([node_id])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            for neighbor in adj[current]:
                if neighbor not in visited:
                    queue.append(neighbor)
        return visited

    def get_ready_nodes(self) -> List[SubtaskNode]:
        """获取依赖已满足的待执行节点."""
        # 构建每个节点的前驱集合
        predecessors: Dict[str, Set[str]] = defaultdict(set)
        for edge in self.edges:
            predecessors[edge.target_node_id].add(edge.source_node_id)

        ready: List[SubtaskNode] = []
        for nid, node in self.nodes.items():
            if node.status != "pending":
                continue
            deps = predecessors.get(nid, set())
            if all(
                self.nodes[d].status == "completed"
                for d in deps
                if d in self.nodes
            ):
                ready.append(node)
        return ready

    def mark_completed(self, node_id: str, result: Dict[str, Any]) -> None:
        """标记节点完成."""
        if node_id in self.nodes:
            self.nodes[node_id].status = "completed"
            self.nodes[node_id].result = result

    def mark_failed(self, node_id: str) -> None:
        """标记节点失败."""
        if node_id in self.nodes:
            self.nodes[node_id].status = "failed"

    def all_completed(self) -> bool:
        """检查所有节点是否完成."""
        return all(n.status == "completed" for n in self.nodes.values())

    # ------------------------------------------------------------------
    # Serialization (for DB persistence and gate resume)
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the entire graph to a JSON-compatible dict."""
        return {
            "graph_id": self.graph_id,
            "nodes": {
                nid: {
                    "node_id": n.node_id,
                    "description": n.description,
                    "responsible_role": n.responsible_role,
                    "input_bindings": n.input_bindings,
                    "output_contract": n.output_contract,
                    "success_criteria": n.success_criteria,
                    "risk_level": n.risk_level,
                    "is_parallel": n.is_parallel,
                    "status": n.status,
                    "result": n.result,
                }
                for nid, n in self.nodes.items()
            },
            "edges": [
                {
                    "source_node_id": e.source_node_id,
                    "target_node_id": e.target_node_id,
                    "data_mapping": e.data_mapping,
                }
                for e in self.edges
            ],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubtaskGraph":
        """Deserialize a graph from a dict (inverse of to_dict)."""
        graph = cls(
            graph_id=data.get("graph_id", str(uuid.uuid4())),
            metadata=data.get("metadata", {}),
        )
        for nid, nd in data.get("nodes", {}).items():
            graph.nodes[nid] = SubtaskNode(
                node_id=nd.get("node_id", nid),
                description=nd.get("description", ""),
                responsible_role=nd.get("responsible_role", ""),
                input_bindings=nd.get("input_bindings", {}),
                output_contract=nd.get("output_contract", {}),
                success_criteria=nd.get("success_criteria", []),
                risk_level=nd.get("risk_level", "low"),
                is_parallel=nd.get("is_parallel", False),
                status=nd.get("status", "pending"),
                result=nd.get("result"),
            )
        for ed in data.get("edges", []):
            graph.edges.append(SubtaskEdge(
                source_node_id=ed.get("source_node_id", ""),
                target_node_id=ed.get("target_node_id", ""),
                data_mapping=ed.get("data_mapping", {}),
            ))
        return graph
