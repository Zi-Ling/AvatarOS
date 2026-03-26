"""MultiAgentConfig — centralised configuration for multi-agent runtime.

All tunable parameters for task decomposition, role dispatch, budget
allocation, and execution constraints in one place.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List


@dataclass(frozen=True)
class MultiAgentConfig:
    """All tunable parameters for multi-agent execution."""

    # ── Task decomposition ──────────────────────────────────────────
    max_subtasks: int = 12
    param_preview_max_chars: int = 500

    # ── Budget allocation ───────────────────────────────────────────
    # Child task planner budget as fraction of parent remaining budget
    child_budget_ratio: float = 0.3
    child_budget_min: int = 10
    child_budget_max: int = 50

    # ── Execution constraints ───────────────────────────────────────
    max_execution_depth: int = 2
    deep_subtask_max_iterations: int = 15
    default_complexity_threshold: int = 3
    default_max_rounds: int = 50
    default_timeout_seconds: float = 3600.0
    max_concurrent_subtasks: int = 4

    # ── Role dispatch: node_type → role_name ────────────────────────
    role_dispatch_table: Dict[str, str] = field(default_factory=lambda: {
        "planner_node": "planner",
        "research_node": "researcher",
        "verification_node": "verifier",
        "recovery_node": "recovery",
        "write_node": "writer",
    })
    default_role: str = "executor"

    # ── Decomposition LLM prompt ────────────────────────────────────
    decompose_system_prompt: str = (
        "You are a task decomposition planner for a multi-agent system. "
        "Given a user's goal, decompose it into semantically independent sub-tasks "
        "that can be assigned to different specialist agents.\n\n"
        "Available roles:\n"
        "- researcher: information gathering, web search, fact-finding. Read-only tools only.\n"
        "- executor: file creation, code execution, desktop automation. Can use all tools.\n"
        "- writer: document generation, report formatting, file output. Write-focused tools.\n\n"
        "Output a JSON array. Each element:\n"
        "{{\n"
        '  "task_id": "t_0",\n'
        '  "goal": "concise sub-task description",\n'
        '  "suggested_role": "researcher|executor|writer",\n'
        '  "expected_output": {{\n'
        '    "type": "artifact|data|text",\n'
        '    "format": "docx|json|txt|null",\n'
        '    "description": "what this task produces"\n'
        "  }},\n"
        '  "depends_on": ["t_0"],\n'
        '  "input_bindings": {{"binding_name": "t_0.output"}},\n'
        '  "acceptance_criteria": ["criterion 1", "criterion 2"],\n'
        '  "parallelizable": true\n'
        "}}\n\n"
        "Rules:\n"
        "- task_id must be t_0, t_1, etc. in order\n"
        "- depends_on references earlier task_ids only (no cycles)\n"
        "- Tasks with no dependencies and parallelizable=true can run concurrently\n"
        "- researcher tasks MUST NOT produce final deliverables (files, documents)\n"
        "- writer tasks MUST produce file artifacts\n"
        "- Keep sub-tasks coarse-grained (2-5 tasks typical, max 8)\n"
        "- Return ONLY the JSON array, no other text"
    )
    decompose_temperature: float = 0.3

    # ── Text truncation limits for intent building ──────────────────
    intent_summary_max_chars: int = 300
    intent_original_goal_max_chars: int = 200
    intent_binding_max_chars: int = 100
    intent_log_preview_chars: int = 120
    intent_max_artifact_refs: int = 5

    # ── Allowed skills per role (used by RoleRunner) ────────────────
    researcher_allowed_skills: FrozenSet[str] = frozenset({
        "web.search", "fs.read", "fs.list", "net.get",
        "llm.fallback", "state.get",
    })
    writer_allowed_skills: FrozenSet[str] = frozenset({
        "fs.write", "fs.read", "fs.list", "python.run",
        "llm.fallback", "state.get", "state.set",
    })
    # executor: all skills allowed (no restriction)

    # ── Per-role budget multipliers (fraction of child_budget) ──────
    researcher_budget_multiplier: float = 0.5
    writer_budget_multiplier: float = 0.8
    executor_budget_multiplier: float = 1.0

    # ── Streaming dispatch loop ───────────────────────────────────
    dispatch_event_min_wait: float = 0.1          # floor for asyncio.wait_for when waiting on in-flight tasks

    # ── SupervisorRuntime dispatch loop ─────────────────────────────
    dispatch_poll_interval: float = 0.05          # seconds between ready-node scans
    dispatch_max_consecutive_empty: int = 3       # empty polls before checking termination
    dispatch_idle_backoff_factor: float = 2.0     # backoff multiplier on consecutive empties

    # ── Worker instance management ──────────────────────────────────
    worker_idle_timeout_seconds: float = 120.0    # idle worker auto-cleanup threshold
    worker_reuse_enabled: bool = True             # reuse idle workers for same role

    # ── Retry / reroute policy ──────────────────────────────────────
    max_task_retries: int = 2                     # per-subtask retry limit
    retry_backoff_base: float = 1.0               # base seconds for exponential backoff
    retry_backoff_max: float = 30.0               # cap on retry delay
    reroute_on_failure: bool = True               # try different worker on failure

    # ── Repair loop (P1) ───────────────────────────────────────────
    repair_enabled: bool = True
    repair_max_actions_per_task: int = 3          # max repair attempts per failed task
    repair_action_order: List[str] = field(default_factory=lambda: [
        "retry_same", "reroute", "split", "review_first", "replan",
    ])

    # ── Health monitor (P1) ─────────────────────────────────────────
    health_consecutive_failure_threshold: int = 3
    health_avg_completion_time_window: int = 10   # rolling window size
    health_compliance_rate_threshold: float = 0.5 # below this → DEGRADED
    health_stuck_timeout_seconds: float = 300.0   # no progress → STUCK

    # ── Worker pool (P1) ───────────────────────────────────────────
    pool_min_workers: int = 0
    pool_max_workers: int = 15
    pool_quarantine_threshold: int = 5            # failures before quarantine
    pool_drain_timeout_seconds: float = 60.0

    # ── Reviewer (P2) ──────────────────────────────────────────────
    reviewer_enabled: bool = False
    reviewer_budget_multiplier: float = 0.3
    reviewer_allowed_skills: FrozenSet[str] = frozenset({
        "fs.read", "fs.list", "llm.fallback", "state.get",
    })

    # ── Decision advisor (rule-based thresholds) ────────────────────
    advisor_split_criteria_threshold: int = 3     # acceptance_criteria count to trigger split
    advisor_replan_failure_ratio: float = 0.5     # failed/total ratio to trigger replan

    # ── Feedback-driven dynamic adjudication ────────────────────────
    feedback_enabled: bool = True                  # process worker feedback at all
    feedback_min_confidence: float = 0.6           # ignore feedback below this confidence
    # Actions that trigger re-evaluation (others are logged but not acted on)
    feedback_actionable_actions: FrozenSet[str] = frozenset({
        "RETRY_SEARCH", "RETRY_TASK", "REPLAN_DOWNSTREAM", "ABORT_DOWNSTREAM",
    })
    # Max feedback-triggered retries per node (prevents infinite loops)
    feedback_max_retries_per_node: int = 1

    # ── Worker feedback generation prompt ───────────────────────────
    # Injected into every role runner's goal_tracker_hint so the LLM
    # emits a structured JSON feedback block at the end of its output.
    feedback_generation_enabled: bool = True
    feedback_json_tag: str = "WORKER_FEEDBACK"     # delimiter tag for parsing
    feedback_prompt_template: str = (
        "\n\n--- FEEDBACK PROTOCOL ---\n"
        "After completing your task, append a JSON block wrapped in "
        "<{tag}> ... </{tag}> tags.\n"
        "Schema:\n"
        '{{\n'
        '  "suggestion": "free-text observation or recommendation",\n'
        '  "action": "NONE | RETRY_SEARCH | RETRY_TASK | REPLAN_DOWNSTREAM | ABORT_DOWNSTREAM",\n'
        '  "confidence": 0.0 to 1.0,\n'
        '  "context": {{}}\n'
        '}}\n'
        "Rules:\n"
        '- action=NONE if the task completed successfully with no issues.\n'
        '- action=RETRY_SEARCH if search results were insufficient and a retry with different keywords may help.\n'
        '- action=RETRY_TASK if the task partially failed and a full retry may succeed.\n'
        '- action=REPLAN_DOWNSTREAM if downstream tasks need adjustment based on your findings.\n'
        '- action=ABORT_DOWNSTREAM if your findings make downstream tasks impossible.\n'
        '- confidence reflects how certain you are about the suggested action.\n'
        "- Always include this block, even if action=NONE.\n"
        "--- END FEEDBACK PROTOCOL ---"
    )

    # ── Parent session result aggregation ───────────────────────────
    # Max chars of output_data to aggregate per subtask (prevents memory bloat)
    aggregation_output_max_chars: int = 5000
    # Max total subtask outputs to store in graph metadata
    aggregation_max_subtask_outputs: int = 20
    # Max chars of node result text to capture per subtask
    aggregation_result_text_max_chars: int = 2000

    # ── P2P (Peer-to-Peer) collaboration mode ──────────────────────
    # When enabled, all agents in a SubtaskGraph with no edges execute
    # as peers and their results are aggregated via consensus voting.
    p2p_consensus_threshold: float = 0.67   # fraction of agents that must agree
    p2p_max_agents: int = 5                 # max agents in P2P mode (broadcast cost)
    p2p_voting_timeout_seconds: float = 60.0  # timeout for consensus round

    # ── Shared memory namespace ─────────────────────────────────────
    shared_memory_enabled: bool = True
    shared_memory_max_entries: int = 200     # max entries per namespace
    shared_memory_max_value_chars: int = 10_000  # max chars per value

    # ── Result cache ────────────────────────────────────────────────
    result_cache_enabled: bool = True
    result_cache_ttl_seconds: float = 3600.0  # 1 hour default TTL
    result_cache_max_entries: int = 500
