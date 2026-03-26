"""SupervisorAgent — LLM-powered orchestrator that manages worker agents.

The SupervisorAgent is the "main agent" that:
- Observes graph state, worker health, and execution progress each round
- Makes strategic decisions: spawn/terminate/reassign/split/replan
- Uses DecisionAdvisor (rule-based or LLM) for split/replan decisions
- Dynamically adjusts the worker pool based on runtime conditions
- Can decompose failed tasks into smaller pieces
- Can terminate underperforming workers and spawn replacements

All prompts and thresholds from MultiAgentConfig.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.avatar.runtime.multiagent.roles.agent_instance import AgentInstanceStatus
from app.avatar.runtime.multiagent.config import MultiAgentConfig
from app.avatar.runtime.multiagent.resilience.decision_advisor import (
    AdvisoryAction, Advisory, AdvisorContext,
    DecisionAdvisor, RuleOnlyAdvisor,
)
from app.avatar.runtime.multiagent.resilience.health_monitor import AgentHealthMonitor, HealthStatus
from app.avatar.runtime.multiagent.core.subtask_graph import SubtaskGraph, SubtaskNode, SubtaskEdge
from app.avatar.runtime.multiagent.core.supervisor_runtime import (
    SupervisorRuntime, WorkerInstance, TaskResult, RuntimeResult, SubtaskExecutor,
)
from app.avatar.runtime.multiagent.observability.trace_integration import TraceIntegration
from app.avatar.runtime.multiagent.execution.worker_pool import WorkerPoolManager

logger = logging.getLogger(__name__)


# ── Supervisor command types ────────────────────────────────────────

class SupervisorAction(str, Enum):
    NOOP = "noop"
    SPAWN_WORKER = "spawn_worker"
    TERMINATE_WORKER = "terminate_worker"
    REASSIGN_TASK = "reassign_task"
    SPLIT_TASK = "split_task"
    REPLAN = "replan"


@dataclass
class SupervisorDecision:
    """A single decision from the SupervisorAgent."""
    action: SupervisorAction
    target_node_id: str = ""
    target_worker_id: str = ""
    role_name: str = ""
    reason: str = ""
    sub_tasks: List[Dict[str, Any]] = field(default_factory=list)


class SupervisorAgent:
    """LLM-powered orchestrator that wraps SupervisorRuntime.

    Usage:
        agent = SupervisorAgent(runtime, config, advisor=...)
        result = await agent.run(executor)

    Each dispatch round, the agent:
    1. Builds a status snapshot (graph state, worker health, progress)
    2. Evaluates decisions (rule-based + optional LLM advisor)
    3. Executes decisions (spawn/terminate/reassign/split)
    4. Then lets SupervisorRuntime do the normal dispatch
    """

    def __init__(
        self,
        runtime: SupervisorRuntime,
        config: Optional[MultiAgentConfig] = None,
        advisor: Optional[DecisionAdvisor] = None,
    ) -> None:
        self._runtime = runtime
        self._cfg = config or MultiAgentConfig()
        self._advisor = advisor or RuleOnlyAdvisor(self._cfg)
        self._decisions_log: List[SupervisorDecision] = []
        self._intervention_count = 0

    @property
    def runtime(self) -> SupervisorRuntime:
        return self._runtime

    @property
    def decisions_log(self) -> List[SupervisorDecision]:
        return list(self._decisions_log)

    @property
    def intervention_count(self) -> int:
        return self._intervention_count

    async def run(self, executor: SubtaskExecutor) -> RuntimeResult:
        """Run with supervisor agent oversight."""
        await self._pre_run_evaluation()
        result = await self._runtime.run(executor)
        await self._post_run_evaluation(result)
        return result

    async def _pre_run_evaluation(self) -> None:
        """Evaluate graph before execution starts."""
        graph = self._runtime.graph
        if not graph.nodes:
            return
        roles_needed = {n.responsible_role for n in graph.nodes.values()}
        logger.info(
            "[SupervisorAgent] Pre-run: %d nodes, roles=%s",
            len(graph.nodes), roles_needed,
        )

    async def _post_run_evaluation(self, result: RuntimeResult) -> None:
        """Evaluate results after execution — trigger split/replan if needed."""
        graph = self._runtime.graph
        failed_nodes = [
            nid for nid, n in graph.nodes.items()
            if n.status == "failed" and not (n.result or {}).get("replaced_by")
        ]
        if not failed_nodes:
            return

        # Ask advisor about each failed node
        for nid in failed_nodes:
            node = graph.nodes[nid]
            retries = self._runtime._node_retries.get(nid, 0)
            ctx = AdvisorContext(
                node_id=nid,
                node_description=node.description,
                node_role=node.responsible_role,
                failure_count=retries,
                error_messages=[
                    (node.result or {}).get("error", "unknown"),
                ],
                acceptance_criteria=node.success_criteria,
                pending_node_count=sum(
                    1 for n in graph.nodes.values() if n.status == "pending"
                ),
                failed_node_count=len(failed_nodes),
                completed_node_count=sum(
                    1 for n in graph.nodes.values() if n.status == "completed"
                ),
            )
            advisory = await self._advisor.advise_split(ctx)
            if advisory.action == AdvisoryAction.SPLIT_TASK and advisory.sub_tasks:
                decision = SupervisorDecision(
                    action=SupervisorAction.SPLIT_TASK,
                    target_node_id=nid,
                    reason=advisory.reason,
                    sub_tasks=advisory.sub_tasks,
                )
                self.execute_decisions([decision])

        # Check if replan is warranted
        total = len(graph.nodes)
        failed_count = sum(
            1 for n in graph.nodes.values() if n.status == "failed"
        )
        completed_count = sum(
            1 for n in graph.nodes.values() if n.status == "completed"
        )
        replan_ctx = AdvisorContext(
            pending_node_count=total - failed_count - completed_count,
            failed_node_count=failed_count,
            completed_node_count=completed_count,
            stalled=failed_count > 0 and completed_count == 0,
        )
        replan_advisory = await self._advisor.advise_replan(replan_ctx)
        if replan_advisory.action == AdvisoryAction.REPLAN_SUBGRAPH:
            logger.info(
                "[SupervisorAgent] Replan advised: %s", replan_advisory.reason,
            )


    # ── Status snapshot ─────────────────────────────────────────────

    def build_status_snapshot(self) -> Dict[str, Any]:
        """Build a structured status report."""
        graph = self._runtime.graph
        health = self._runtime._health
        pool = self._runtime._pool

        nodes_by_status: Dict[str, List[str]] = {}
        for nid, node in graph.nodes.items():
            nodes_by_status.setdefault(node.status, []).append(nid)

        worker_summary = []
        for wid, w in self._runtime._workers.items():
            entry: Dict[str, Any] = {
                "id": wid, "role": w.role_name,
                "busy": w.is_busy, "assigned": w.assigned_node,
            }
            if health:
                wh = health.get(wid)
                if wh:
                    entry["health"] = wh.health_status.value
                    entry["consecutive_failures"] = wh.consecutive_failures
            if pool:
                entry["quarantined"] = pool.is_quarantined(wid)
            worker_summary.append(entry)

        return {
            "round": self._runtime._round,
            "nodes_total": len(graph.nodes),
            "nodes_by_status": nodes_by_status,
            "workers": worker_summary,
            "results_collected": len(self._runtime._results),
            "interventions_so_far": self._intervention_count,
        }

    # ── Rule-based decisions ────────────────────────────────────────

    def decide_with_rules(self) -> List[SupervisorDecision]:
        """Rule-based decisions for worker lifecycle management."""
        decisions: List[SupervisorDecision] = []
        health = self._runtime._health
        pool = self._runtime._pool
        graph = self._runtime.graph

        if not health:
            return [SupervisorDecision(action=SupervisorAction.NOOP)]

        # Rule 1: Terminate BROKEN/STUCK workers
        for wid, w in list(self._runtime._workers.items()):
            wh = health.get(wid)
            if wh and wh.health_status in (HealthStatus.BROKEN, HealthStatus.STUCK):
                if not pool.is_quarantined(wid):
                    decisions.append(SupervisorDecision(
                        action=SupervisorAction.TERMINATE_WORKER,
                        target_worker_id=wid,
                        role_name=w.role_name,
                        reason=f"worker {wh.health_status.value}",
                    ))

        # Rule 2: Spawn replacements for roles with pending tasks but no workers
        pending_roles = {
            n.responsible_role for n in graph.nodes.values()
            if n.status == "pending"
        }
        active_roles = {
            w.role_name for w in self._runtime._workers.values()
            if (not w.is_busy
                and w.agent.state.status != AgentInstanceStatus.TERMINATED
                and not pool.is_quarantined(w.instance_id))
        }
        for role in pending_roles - active_roles:
            if pool.can_spawn(role):
                decisions.append(SupervisorDecision(
                    action=SupervisorAction.SPAWN_WORKER,
                    role_name=role,
                    reason=f"no available worker for role={role}",
                ))

        if not decisions:
            decisions.append(SupervisorDecision(action=SupervisorAction.NOOP))
        return decisions

    # ── Decision execution ──────────────────────────────────────────

    def execute_decisions(self, decisions: List[SupervisorDecision]) -> List[str]:
        """Execute decisions. Returns action summaries."""
        summaries: List[str] = []
        for d in decisions:
            if d.action == SupervisorAction.NOOP:
                continue
            self._decisions_log.append(d)
            self._intervention_count += 1

            if d.action == SupervisorAction.TERMINATE_WORKER:
                summaries.append(self._exec_terminate(d))
            elif d.action == SupervisorAction.SPAWN_WORKER:
                summaries.append(self._exec_spawn(d))
            elif d.action == SupervisorAction.REASSIGN_TASK:
                summaries.append(self._exec_reassign(d))
            elif d.action == SupervisorAction.SPLIT_TASK:
                summaries.append(self._exec_split(d))
            elif d.action == SupervisorAction.REPLAN:
                summaries.append(self._exec_replan(d))
            else:
                summaries.append(f"unknown action: {d.action}")
        return summaries

    def _exec_terminate(self, d: SupervisorDecision) -> str:
        wid = d.target_worker_id
        worker = self._runtime._workers.get(wid)
        if not worker:
            return f"terminate: worker {wid} not found"
        worker.terminate()
        if self._runtime._pool:
            self._runtime._pool.quarantine(wid, reason=d.reason)
        self._runtime._trace.agent_terminated(wid, worker.role_name)
        return f"terminated {wid} ({worker.role_name}): {d.reason}"

    def _exec_spawn(self, d: SupervisorDecision) -> str:
        role = d.role_name
        try:
            agent = self._runtime._instance_manager.spawn(
                role_name=role, task_id=f"supervisor_spawn_{role}",
            )
            if agent is None:
                return f"spawn denied for role={role}"
            worker = WorkerInstance(agent, self._cfg)
            self._runtime._workers[worker.instance_id] = worker
            if self._runtime._pool:
                self._runtime._pool.register(worker.instance_id, role)
            if self._runtime._health:
                self._runtime._health.register(worker.instance_id, role)
            self._runtime._trace.agent_created(worker.instance_id, role)
            return f"spawned {worker.instance_id} for role={role}"
        except Exception as exc:
            return f"spawn failed for role={role}: {exc}"

    def _exec_reassign(self, d: SupervisorDecision) -> str:
        graph = self._runtime.graph
        node = graph.nodes.get(d.target_node_id)
        if not node:
            return f"reassign: node {d.target_node_id} not found"
        old_role = node.responsible_role
        node.responsible_role = d.role_name
        if node.status == "failed":
            node.status = "pending"
            node.result = None
            # Reset downstream nodes blocked by this failure
            downstream = graph.get_downstream_subgraph(d.target_node_id) - {d.target_node_id}
            for did in downstream:
                dnode = graph.nodes.get(did)
                if dnode and dnode.status == "failed":
                    blocked_error = (dnode.result or {}).get("error", "")
                    if "blocked" in blocked_error:
                        dnode.status = "pending"
                        dnode.result = None
        return f"reassigned {d.target_node_id}: {old_role} → {d.role_name}"

    def _exec_split(self, d: SupervisorDecision) -> str:
        graph = self._runtime.graph
        node = graph.nodes.get(d.target_node_id)
        if not node:
            return f"split: node {d.target_node_id} not found"
        if not d.sub_tasks:
            return f"split: no sub_tasks for {d.target_node_id}"

        original_id = d.target_node_id
        node.status = "completed"
        node.result = {"replaced_by": []}

        new_ids: List[str] = []
        for i, spec in enumerate(d.sub_tasks):
            new_id = f"{original_id}_split_{i}"
            new_node = SubtaskNode(
                node_id=new_id,
                description=spec.get("goal", f"Sub-task {i} of {original_id}"),
                responsible_role=spec.get("role", node.responsible_role),
                output_contract=spec.get("expected_output", node.output_contract),
                success_criteria=spec.get("acceptance_criteria", []),
            )
            graph.nodes[new_id] = new_node
            new_ids.append(new_id)
            node.result["replaced_by"].append(new_id)

        # Chain sub-tasks sequentially
        for j in range(1, len(new_ids)):
            graph.edges.append(SubtaskEdge(
                source_node_id=new_ids[j - 1], target_node_id=new_ids[j],
            ))

        # Re-wire downstream: original → last_new
        last_new = new_ids[-1] if new_ids else original_id
        first_new = new_ids[0] if new_ids else original_id
        for edge in graph.edges:
            if edge.source_node_id == original_id and edge.target_node_id not in new_ids:
                edge.source_node_id = last_new
            if edge.target_node_id == original_id:
                edge.target_node_id = first_new

        # Reset downstream nodes that were blocked by the original failure
        downstream = graph.get_downstream_subgraph(last_new) - {last_new} - set(new_ids)
        for did in downstream:
            dnode = graph.nodes.get(did)
            if dnode and dnode.status == "failed":
                blocked_error = (dnode.result or {}).get("error", "")
                if "blocked" in blocked_error or f"upstream {original_id}" in blocked_error:
                    dnode.status = "pending"
                    dnode.result = None

        return f"split {original_id} into {len(new_ids)} sub-tasks: {new_ids}"

    def _exec_replan(self, d: SupervisorDecision) -> str:
        pending = sum(
            1 for n in self._runtime.graph.nodes.values()
            if n.status == "pending"
        )
        return f"replan requested for {pending} pending nodes (requires LLM decomposition)"

    # ── Summary ─────────────────────────────────────────────────────

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_interventions": self._intervention_count,
            "decisions": [
                {"action": d.action.value, "target_node": d.target_node_id,
                 "target_worker": d.target_worker_id, "role": d.role_name,
                 "reason": d.reason}
                for d in self._decisions_log
            ],
        }
