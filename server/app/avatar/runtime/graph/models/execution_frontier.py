"""
ExecutionFrontier — DAG 执行进度的精确快照。

不需要独立数据库表，它是从 StepState 聚合计算的视图，
序列化后存入 Checkpoint.execution_frontier_json。

核心职责：
  - 追踪已完成/运行中/就绪节点
  - 根据 DAG 依赖关系计算下一批可执行节点
  - 支持 JSON round-trip 序列化
  - 支持从 StepState 列表重建（恢复场景）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Set, Optional
from datetime import datetime, timezone
import json


@dataclass
class CompletedNodeInfo:
    """已完成节点的结构化信息"""
    output_digest: str
    completed_at: str
    commit_status: str = "committed"  # "pending" / "committed"
    failure_reason: Optional[str] = None


@dataclass
class RunningNodeInfo:
    """运行中节点的结构化信息"""
    worker_id: str
    started_at: str
    attempt_id: Optional[str] = None


@dataclass
class ExecutionFrontier:
    """执行前沿 — DAG 执行进度的精确快照"""

    completed_nodes: Dict[str, CompletedNodeInfo] = field(default_factory=dict)
    running_nodes: Dict[str, RunningNodeInfo] = field(default_factory=dict)
    ready_nodes: Set[str] = field(default_factory=set)

    # ── 节点生命周期更新 ──────────────────────────────────────────

    def on_node_started(self, node_id: str, worker_id: str, attempt_id: Optional[str] = None) -> None:
        """节点开始执行时更新前沿"""
        self.running_nodes[node_id] = RunningNodeInfo(
            worker_id=worker_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            attempt_id=attempt_id,
        )
        self.ready_nodes.discard(node_id)

    def on_node_completed(
        self,
        node_id: str,
        output_digest: str,
        completed_at: Optional[str] = None,
        failure_reason: Optional[str] = None,
    ) -> None:
        """节点完成时更新前沿"""
        self.completed_nodes[node_id] = CompletedNodeInfo(
            output_digest=output_digest,
            completed_at=completed_at or datetime.now(timezone.utc).isoformat(),
            commit_status="committed",
            failure_reason=failure_reason,
        )
        self.running_nodes.pop(node_id, None)
        self.ready_nodes.discard(node_id)

    def on_node_failed(self, node_id: str, reason: str) -> None:
        """节点失败时更新前沿（记录为已完成但带 failure_reason）"""
        self.on_node_completed(
            node_id=node_id,
            output_digest="",
            failure_reason=reason,
        )

    # ── DAG 就绪节点计算 ─────────────────────────────────────────

    def compute_ready_nodes(self, graph_edges: Dict[str, list]) -> Set[str]:
        """
        根据 DAG 依赖关系重新计算就绪节点。

        Args:
            graph_edges: node_id → [依赖的 node_id 列表] 的邻接表
                         即 incoming dependencies，例如 {"C": ["A", "B"]} 表示 C 依赖 A 和 B

        Returns:
            就绪节点集合（所有依赖已完成且自身未完成/未运行）
        """
        terminal = set(self.completed_nodes.keys())
        in_progress = set(self.running_nodes.keys())
        ready = set()

        for node_id, deps in graph_edges.items():
            if node_id in terminal or node_id in in_progress:
                continue
            if all(d in terminal for d in deps):
                ready.add(node_id)

        self.ready_nodes = ready
        return ready

    # ── 序列化 ───────────────────────────────────────────────────

    def to_json(self) -> str:
        """序列化为 JSON — 结构化格式，与 from_json 严格对应"""
        data = {
            "completed_nodes": {
                nid: {
                    "output_digest": info.output_digest,
                    "completed_at": info.completed_at,
                    "commit_status": info.commit_status,
                    "failure_reason": info.failure_reason,
                }
                for nid, info in self.completed_nodes.items()
            },
            "running_nodes": {
                nid: {
                    "worker_id": info.worker_id,
                    "started_at": info.started_at,
                    "attempt_id": info.attempt_id,
                }
                for nid, info in self.running_nodes.items()
            },
            "ready_nodes": sorted(self.ready_nodes),
        }
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> ExecutionFrontier:
        """从 JSON 反序列化 — 与 to_json 格式严格对应"""
        data = json.loads(json_str)
        frontier = cls()

        for nid, info in data.get("completed_nodes", {}).items():
            frontier.completed_nodes[nid] = CompletedNodeInfo(
                output_digest=info["output_digest"],
                completed_at=info["completed_at"],
                commit_status=info.get("commit_status", "committed"),
                failure_reason=info.get("failure_reason"),
            )

        for nid, info in data.get("running_nodes", {}).items():
            frontier.running_nodes[nid] = RunningNodeInfo(
                worker_id=info["worker_id"],
                started_at=info["started_at"],
                attempt_id=info.get("attempt_id"),
            )

        frontier.ready_nodes = set(data.get("ready_nodes", []))
        return frontier

    # ── 从 StepState 重建 ────────────────────────────────────────

    @classmethod
    def from_step_states(cls, step_states: list) -> ExecutionFrontier:
        """
        从 StepState 列表重建 Execution Frontier（恢复场景）。

        StepState 状态映射：
          success/failed/skipped/cancelled → completed_nodes
          running                         → running_nodes（标记为需要恢复）
          pending/ready/blocked           → 不加入 frontier，由 compute_ready_nodes 计算
        """
        frontier = cls()
        terminal_statuses = {"success", "failed", "skipped", "cancelled"}

        for ss in step_states:
            status = ss.status if isinstance(ss.status, str) else ss.status.value

            if status in terminal_statuses:
                frontier.completed_nodes[ss.id] = CompletedNodeInfo(
                    output_digest=ss.input_hash or "",
                    completed_at=(ss.ended_at or ss.updated_at).isoformat()
                    if hasattr(ss, "ended_at") and ss.ended_at
                    else ss.updated_at.isoformat()
                    if hasattr(ss, "updated_at")
                    else datetime.now(timezone.utc).isoformat(),
                    commit_status="committed",
                    failure_reason=ss.error_message if status == "failed" else None,
                )
            elif status == "running":
                frontier.running_nodes[ss.id] = RunningNodeInfo(
                    worker_id="recovery",
                    started_at=(ss.started_at or ss.updated_at).isoformat()
                    if hasattr(ss, "started_at") and ss.started_at
                    else datetime.now(timezone.utc).isoformat(),
                    attempt_id=ss.attempt_id if hasattr(ss, "attempt_id") else None,
                )

        return frontier

    # ── 辅助方法 ─────────────────────────────────────────────────

    def is_node_completed(self, node_id: str) -> bool:
        return node_id in self.completed_nodes

    def is_node_running(self, node_id: str) -> bool:
        return node_id in self.running_nodes

    def all_completed(self, node_ids: Set[str]) -> bool:
        """检查给定节点是否全部完成"""
        return all(nid in self.completed_nodes for nid in node_ids)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ExecutionFrontier):
            return NotImplemented
        return (
            self.completed_nodes == other.completed_nodes
            and self.running_nodes == other.running_nodes
            and self.ready_nodes == other.ready_nodes
        )
