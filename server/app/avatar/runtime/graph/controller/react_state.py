"""
ReactLoopState — shared mutable state for the ReAct execution loop.

Holds all variables that were previously local to _execute_react_mode,
enabling clean decomposition into multiple mixins without passing dozens
of parameters between methods.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult
    from app.avatar.runtime.graph.controller.long_task_helpers import LongTaskContext


@dataclass
class ReactLoopState:
    """Mutable state bag for the ReAct execution loop."""

    # ── Core references ─────────────────────────────────────────────────
    intent: str = ""
    graph: Any = None  # ExecutionGraph
    env_context: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    shared_context: Any = None  # ExecutionContext

    # ── Session identifiers ─────────────────────────────────────────────
    exec_session_id: str = ""
    session_id: Optional[str] = None

    # ── Lifecycle & narrative ───────────────────────────────────────────
    lifecycle: Any = None  # ExecutionLifecycle
    narrative_manager: Any = None  # NarrativeManager

    # ── Goals & deliverables ────────────────────────────────────────────
    sub_goals: List[str] = field(default_factory=list)
    deliverables: List[Any] = field(default_factory=list)

    # ── Task understanding ──────────────────────────────────────────────
    task_def: Any = None
    readiness: Any = None
    complexity: Any = None
    task_runtime_state: Any = None

    # ── Workspace ───────────────────────────────────────────────────────
    workspace: Any = None

    # ── Loop counters & limits ──────────────────────────────────────────
    planner_invocations: int = 0
    max_react_iterations: int = 200
    max_graph_nodes: int = 200
    consecutive_failures: int = 0
    MAX_CONSECUTIVE_FAILURES: int = 3

    # ── Control handle ──────────────────────────────────────────────────
    control_handle: Any = None

    # ── Result tracking ─────────────────────────────────────────────────
    lifecycle_status: str = "failed"
    result_status: str = "unknown"
    error_message: Optional[str] = None
    final_result: Optional[Any] = None  # ExecutionResult
    verification_passed: bool = False

    # ── Evolution ───────────────────────────────────────────────────────
    evo_trace_id: Optional[str] = None

    # ── Long-task ───────────────────────────────────────────────────────
    lt_ctx: Optional[Any] = None  # LongTaskContext

    # ── Per-iteration transient state ───────────────────────────────────
    pending_node_ids: Set[str] = field(default_factory=set)

    # ── FINISH rejection tracking ──────────────────────────────────────
    consecutive_finish_rejections: int = 0
    MAX_CONSECUTIVE_FINISH_REJECTIONS: int = 3

    # ── SelfMonitor progress tracking ──────────────────────────────────
    _prev_completed_count: int = 0

    # ── Direct reply from Planner (FINISH with message, no skill needed) ─
    direct_reply: Optional[str] = None
