"""PeerToPeerRuntime — P2P collaboration mode for multi-agent consensus.

All agents execute the same task independently, then results are
aggregated via consensus voting. Suited for review/evaluation scenarios
where multiple independent opinions improve quality.

Usage:
    runtime = PeerToPeerRuntime(agents, config, trace)
    result = await runtime.run(executor, task_description)
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Dict, List, Optional

from app.avatar.runtime.multiagent.config import MultiAgentConfig
from app.avatar.runtime.multiagent.core.subtask_graph import SubtaskGraph, SubtaskNode
from app.avatar.runtime.multiagent.observability.trace_integration import TraceIntegration

logger = logging.getLogger(__name__)


@dataclass
class PeerVote:
    """A single peer's vote/result."""
    agent_id: str
    role: str
    result_data: Dict[str, Any] = field(default_factory=dict)
    success: bool = False
    execution_time: float = 0.0
    verdict: str = ""  # free-text verdict for consensus


@dataclass
class ConsensusResult:
    """Aggregated consensus from P2P voting."""
    reached: bool = False
    agreement_ratio: float = 0.0
    majority_verdict: str = ""
    votes: List[PeerVote] = field(default_factory=list)
    dissenting_votes: List[PeerVote] = field(default_factory=list)


# Type alias for P2P executor
P2PExecutor = Callable[
    [SubtaskNode, str, Dict[str, Any], MultiAgentConfig],
    Awaitable["PeerVote"],
]


class PeerToPeerRuntime:
    """P2P collaboration runtime — all agents vote independently.

    Flow:
    1. Create N peer agents (one per node in the graph, or from config)
    2. All peers execute the same task in parallel
    3. Collect results and compute consensus
    4. If consensus reached → return majority result
    5. If not → return all results with disagreement flag
    """

    def __init__(
        self,
        config: MultiAgentConfig,
        trace: Optional[TraceIntegration] = None,
    ) -> None:
        self._cfg = config
        self._trace = trace or TraceIntegration()

    async def run(
        self,
        executor: P2PExecutor,
        task: str,
        peer_roles: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> ConsensusResult:
        """Execute P2P consensus round.

        Args:
            executor: async callback (node, worker_id, context, config) → PeerVote
            task: the task description all peers evaluate
            peer_roles: list of role names for each peer
            context: shared context passed to all peers
        """
        context = context or {}
        n_peers = min(len(peer_roles), self._cfg.p2p_max_agents)
        peer_roles = peer_roles[:n_peers]

        self._trace._emit("p2p.started", {
            "task": task[:200],
            "peer_count": n_peers,
            "roles": peer_roles,
        })

        # Create peer nodes
        peers: List[SubtaskNode] = []
        for i, role in enumerate(peer_roles):
            node = SubtaskNode(
                node_id=f"peer_{i}",
                description=task,
                responsible_role=role,
                status="pending",
            )
            peers.append(node)

        # Execute all peers in parallel
        start = time.monotonic()

        async def _run_peer(node: SubtaskNode) -> PeerVote:
            worker_id = f"p2p_{node.node_id}"
            try:
                return await asyncio.wait_for(
                    executor(node, worker_id, context, self._cfg),
                    timeout=self._cfg.p2p_voting_timeout_seconds,
                )
            except asyncio.TimeoutError:
                return PeerVote(
                    agent_id=worker_id, role=node.responsible_role,
                    success=False, verdict="TIMEOUT",
                )
            except Exception as exc:
                return PeerVote(
                    agent_id=worker_id, role=node.responsible_role,
                    success=False, verdict=f"ERROR: {exc}",
                )

        votes = await asyncio.gather(*[_run_peer(p) for p in peers])
        elapsed = time.monotonic() - start

        # Compute consensus
        successful_votes = [v for v in votes if v.success]
        if not successful_votes:
            self._trace._emit("p2p.no_consensus", {"reason": "all_failed"})
            return ConsensusResult(
                reached=False, agreement_ratio=0.0,
                votes=list(votes),
            )

        # Group by verdict
        verdict_counts: Dict[str, List[PeerVote]] = {}
        for v in successful_votes:
            verdict_counts.setdefault(v.verdict, []).append(v)

        # Find majority
        majority_verdict = max(verdict_counts, key=lambda k: len(verdict_counts[k]))
        majority_count = len(verdict_counts[majority_verdict])
        agreement_ratio = majority_count / len(successful_votes)
        reached = agreement_ratio >= self._cfg.p2p_consensus_threshold

        dissenting = [v for v in successful_votes if v.verdict != majority_verdict]

        self._trace._emit("p2p.completed", {
            "reached": reached,
            "agreement_ratio": round(agreement_ratio, 2),
            "majority_verdict": majority_verdict[:200],
            "total_votes": len(votes),
            "successful_votes": len(successful_votes),
            "elapsed": round(elapsed, 2),
        })

        return ConsensusResult(
            reached=reached,
            agreement_ratio=agreement_ratio,
            majority_verdict=majority_verdict,
            votes=list(votes),
            dissenting_votes=dissenting,
        )
