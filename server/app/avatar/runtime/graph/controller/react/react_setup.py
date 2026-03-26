"""
ReAct mode setup helpers for GraphController.

Handles session creation, workspace setup, goal decomposition, deliverable
extraction, task understanding (TaskDefinition, Clarification, Complexity),
and complexity-based routing.

Extracted from graph_controller._execute_react_mode to reduce the main
controller file size.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any, FrozenSet, List, Optional, Tuple, TYPE_CHECKING
from pathlib import Path
import logging

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.context.execution_context import ExecutionContext

logger = logging.getLogger(__name__)


# ── Configurable setup parameters ───────────────────────────────────

@dataclass
class ReactSetupConfig:
    """All tunable parameters for ReactSetupMixin in one place.

    Centralises vision skill sets, desktop skill lists, capability gap
    messages, and planner hints that were previously hardcoded inline.
    """

    # Skills that require Vision LLM — gated when vision is unavailable
    vision_skills: FrozenSet[str] = frozenset({"computer.read_screen", "computer.use"})

    # Non-vision desktop skills (fallback when vision is gated)
    non_vision_desktop_skills: Tuple[str, ...] = (
        "computer.app.launch", "computer.keyboard", "computer.mouse",
        "computer.window.focus", "computer.window.list",
    )

    # Planner hint template when vision is unavailable.
    # {gated} = comma-separated gated skill names
    # {available} = comma-separated available desktop skill names
    vision_unavailable_hint: str = (
        "Vision skills ({gated}) are UNAVAILABLE. "
        "For desktop automation, use ONLY: {available}. "
        "If the task requires visual screen reading or pixel-level interaction, "
        "report that the capability is not available instead of guessing."
    )

    # Capability gap messages (Chinese, user-facing)
    gap_vision_required_message: str = (
        "抱歉，当前环境不支持屏幕视觉识别功能（Vision LLM 不可用）。"
        "该任务需要读取屏幕内容进行视觉判断，暂时无法执行。"
        "请确认 Vision LLM 配置后重试。"
    )
    gap_desktop_unavailable_message: str = (
        "抱歉，当前环境没有可用的桌面自动化技能。"
        "请检查 computer.app.launch / computer.keyboard 等技能是否已注册。"
    )

    # Desktop skill prefix patterns for extracting desktop skills from registry
    desktop_skill_prefixes: Tuple[str, ...] = ("computer.", "desktop.")


class ReactSetupResult:
    """Container for all setup results needed by the ReAct loop."""
    __slots__ = (
        "exec_session_id", "lifecycle", "graph", "shared_context",
        "workspace", "session_id", "sub_goals", "deliverables",
        "task_def", "readiness", "complexity", "task_runtime_state",
        "narrative_manager", "env_context",
    )

    def __init__(self):
        self.exec_session_id: str = ""
        self.lifecycle: Any = None
        self.graph: Any = None
        self.shared_context: Any = None
        self.workspace: Any = None
        self.session_id: Optional[str] = None
        self.sub_goals: List[str] = []
        self.deliverables: List[Any] = []
        self.task_def: Any = None
        self.readiness: Any = None
        self.complexity: Any = None
        self.task_runtime_state: Any = None
        self.narrative_manager: Any = None
        self.env_context: Dict[str, Any] = {}


class ReactSetupMixin:
    """Mixin providing ReAct mode setup methods for GraphController."""

    # Subclasses (GraphController) may override via __init__ or class attr.
    _react_setup_config: ReactSetupConfig = ReactSetupConfig()

    async def _setup_react_session(
        self,
        intent: str,
        env_context: Dict[str, Any],
        config: Dict[str, Any],
    ) -> ReactSetupResult:
        """Create execution session, graph, workspace, and all setup state."""
        from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
        from app.avatar.runtime.graph.lifecycle.execution_lifecycle import ExecutionLifecycle
        from app.services.session_store import ExecutionSessionStore

        result = ReactSetupResult()
        max_react_iterations = config.get('max_react_iterations', 200)
        max_graph_nodes = config.get('max_graph_nodes', 200)

        # ── Session setup ───────────────────────────────────────────────
        _workspace_path = env_context.get("workspace_path") or (
            str(self.guard.config.workspace_root)
            if self.guard and self.guard.config.workspace_root else ""
        )
        _policy_snap = None
        _runtime_config_snap = {
            "max_concurrent_graphs": self.max_concurrent_graphs,
            "max_planner_invocations_per_graph": self.max_planner_invocations_per_graph,
            "max_planner_tokens": self.max_planner_tokens,
            "max_planner_calls": self.max_planner_calls,
            "max_planner_cost": self.max_planner_cost,
            "max_execution_cost": self.max_execution_cost,
            "max_react_iterations": max_react_iterations,
            "max_graph_nodes": max_graph_nodes,
        }
        if self.guard:
            _policy_snap = {
                "workspace_root": str(self.guard.config.workspace_root),
                "enforce_workspace_isolation": self.guard.config.enforce_workspace_isolation,
                "default_policy": self.guard.config.default_policy,
                "max_nodes_per_patch": self.guard.config.max_nodes_per_patch,
            }
        _exec_session = ExecutionSessionStore.create(
            goal=intent,
            run_id=env_context.get("run_id"),
            task_id=env_context.get("task_id"),
            request_id=env_context.get("request_id"),
            trace_id=env_context.get("trace_id"),
            conversation_id=env_context.get("session_id"),
            workspace_path=_workspace_path,
            policy_snapshot=_policy_snap,
            runtime_config_snapshot=_runtime_config_snap,
        )
        result.exec_session_id = _exec_session.id
        result.lifecycle = ExecutionLifecycle(result.exec_session_id)
        await result.lifecycle.on_session_start()

        env_context = dict(env_context)
        env_context["exec_session_id"] = result.exec_session_id

        # ── Graph + workspace ───────────────────────────────────────────
        graph = ExecutionGraph(goal=intent, nodes={}, edges={})
        graph.metadata["session_id"] = env_context.get("session_id")
        graph.metadata["env"] = env_context
        result.graph = graph

        on_graph_created = env_context.get("on_graph_created")
        if on_graph_created:
            try:
                on_graph_created(str(graph.id))
            except Exception as _e:
                logger.warning(f"[GraphController] on_graph_created failed: {_e}")

        from app.avatar.runtime.graph.context.execution_context import ExecutionContext as _ExecCtx
        result.session_id = env_context.get("session_id")
        _workspace = None
        _ws_session_id = result.session_id or result.exec_session_id
        if _ws_session_id:
            try:
                from app.avatar.runtime.workspace import get_session_workspace_manager
                _ws_mgr = get_session_workspace_manager()
                if _ws_mgr is not None:
                    _safe_session_id = _ws_session_id.replace(":", "-")
                    # Task-scoped workspace isolation: if running inside a
                    # TaskExecutionPlan unit, append the unit_id to the
                    # session key so each unit gets its own sandbox.
                    _scoped_root = env_context.get("_task_scoped_output_root")
                    if _scoped_root:
                        _safe_session_id = f"{_safe_session_id}_{_scoped_root}"
                    _workspace = _ws_mgr.get_or_create(_safe_session_id)
                    logger.debug(f"[GraphController] SessionWorkspace for {_safe_session_id}: {_workspace.root}")
            except Exception as _ws_err:
                logger.warning(f"[GraphController] SessionWorkspace failed: {_ws_err}")

        if _workspace is not None and hasattr(_workspace, "root"):
            env_context = dict(env_context)
            env_context["session_workspace_path"] = str(Path(_workspace.root).resolve())

        result.workspace = _workspace
        result.shared_context = _ExecCtx(
            graph_id=graph.id,
            goal_desc=intent,
            inputs=env_context,
            session_id=result.exec_session_id,
            task_id=graph.id,
            env=env_context,
            workspace=_workspace,
        )

        # ── Goal decomposition ──────────────────────────────────────────
        result.sub_goals = self._goal_tracker.decompose_goal(intent)
        logger.info(f"[GoalTracker] Decomposed '{intent}' into {len(result.sub_goals)} sub-goals: {result.sub_goals}")

        # ── Deliverable extraction ──────────────────────────────────────
        try:
            from app.avatar.runtime.verification.goal_normalizer import GoalNormalizer as _GN
            _ng = _GN().normalize(intent)
            # ── Unify sub-goal source ───────────────────────────────────
            # GoalTracker (controller layer) is the single source of truth
            # for sub-goal decomposition.  Override GoalNormalizer's independent
            # _decompose_sub_goals result so that verification/coverage uses
            # the exact same list, preventing coverage/finish drift.
            _ng.sub_goals = list(result.sub_goals)
            result.deliverables = _ng.deliverables or []
            env_context["normalized_goal"] = _ng
            if result.deliverables:
                logger.info(
                    f"[GoalTracker] {len(result.sub_goals)} sub-goal(s), "
                    f"{len(result.deliverables)} deliverable(s): "
                    f"{[f'{d.id}:{d.format}' for d in result.deliverables]}"
                )
        except Exception as _del_err:
            logger.debug(f"[GoalTracker] Deliverable extraction failed: {_del_err}")

        result.env_context = env_context
        # ── Vision capability gating ────────────────────────────────────
        # Detect vision LLM availability at setup time and remove vision-
        # dependent skills from available_skills so Planner never plans them.
        _setup_cfg = self._react_setup_config
        _vision_skills = _setup_cfg.vision_skills
        _vision_available = True
        try:
            from app.llm.factory import create_vision_llm_client
            _vlm = create_vision_llm_client()
            if not getattr(_vlm, "supports_vision", False):
                raise NotImplementedError("vision not supported")
        except Exception:
            _vision_available = False
            # Vision unavailable — gate the skills
            _avail = env_context.get("available_skills")
            if isinstance(_avail, dict):
                for _vs in _vision_skills:
                    _avail.pop(_vs, None)
            env_context["_vision_unavailable"] = True

            # ── Capability-aware routing info for Planner ───────────────
            _non_vision_desktop_skills = list(_setup_cfg.non_vision_desktop_skills)
            # Filter to only actually available skills
            if isinstance(_avail, dict):
                _non_vision_desktop_skills = [
                    s for s in _non_vision_desktop_skills if s in _avail
                ]
            _gated_str = ", ".join(_vision_skills)
            _avail_str = ", ".join(_non_vision_desktop_skills) or "none available"
            env_context["_capability_context"] = {
                "vision_available": False,
                "gated_skills": list(_vision_skills),
                "available_desktop_skills": _non_vision_desktop_skills,
                "planner_hint": _setup_cfg.vision_unavailable_hint.format(
                    gated=_gated_str, available=_avail_str,
                ),
            }

            # ── Detect capability gap: task needs vision but it's blocked ──
            from app.avatar.runtime.task.intent_classifier import classify_intent
            _intent_signals = classify_intent(intent)
            if _intent_signals.has_vision_dependency and _intent_signals.has_desktop_entity:
                env_context["_capability_gap"] = "vision_required"
                env_context["_capability_gap_message"] = _setup_cfg.gap_vision_required_message
            elif _intent_signals.requires_desktop_automation and not _non_vision_desktop_skills:
                env_context["_capability_gap"] = "desktop_skills_unavailable"
                env_context["_capability_gap_message"] = _setup_cfg.gap_desktop_unavailable_message

            logger.info(
                "[VisionGate] Vision LLM unavailable — gated skills: %s, "
                "available desktop: %s, capability_gap: %s",
                _vision_skills,
                _non_vision_desktop_skills,
                env_context.get("_capability_gap", "none"),
            )
        else:
            env_context["_capability_context"] = {
                "vision_available": True,
                "gated_skills": [],
                "available_desktop_skills": [],
                "planner_hint": "",
            }
        return result

    async def _setup_task_understanding(
        self,
        intent: str,
        env_context: Dict[str, Any],
        graph: Any,
    ) -> Tuple[Any, Any, Any, Any]:
        """Run task understanding layer: TaskDef, Clarification, Complexity, RuntimeState.

        Returns (task_def, readiness, complexity, task_runtime_state).
        """
        _task_def = None
        _readiness = None
        _complexity = None
        _task_runtime_state = None

        # 18.A1: TaskDefinitionEngine.parse()
        if self._task_def_engine is not None:
            try:
                _task_def = await self._task_def_engine.parse(intent)
                try:
                    from app.avatar.runtime.observability.debug_event_stream import get_debug_event_stream
                    get_debug_event_stream().emit("created", "TaskDefinition", f"task_{id(graph)}", f"objective={(_task_def.objective.text if _task_def else '')[:100]}")
                except Exception:
                    pass
            except Exception as _tde_err:
                logger.warning(f"[GraphController] TaskDefinitionEngine failed: {_tde_err}")

        # 18.A2: ClarificationEngine.assess()
        # Skip re-assessment when resuming from a gate — answers are already
        # merged into env_context, re-assessing would re-trigger the gate.
        if (
            _task_def is not None
            and self._clarification_engine is not None
            and not env_context.get("_gate_resumed")
        ):
            try:
                _readiness = self._clarification_engine.assess(_task_def)
                if _readiness.status == "blocked":
                    # ── Persistent gate: create durable WAITING_INPUT state ──
                    _gate_runtime = getattr(self, '_gate_runtime', None)
                    if _gate_runtime is not None:
                        _questions = [
                            {"question": q.question, "priority": q.priority.value,
                             "related_field": q.related_field}
                            for q in _readiness.blocking_questions
                        ]
                        _assumptions = []
                        if _readiness.suggested_assumptions:
                            _assumptions = [
                                {"text": getattr(a, "text", str(a)),
                                 "confidence": getattr(a, "confidence_level", "medium")}
                                for a in _readiness.suggested_assumptions
                            ]
                        _gate_ctx = _gate_runtime.create_gate(
                            task_session_id=env_context.get("task_session_id", ""),
                            session_id=env_context.get("session_id", ""),
                            gate_type="clarification",
                            trigger_reason="pre_execution_blocked",
                            blocking_questions=_questions,
                            pending_assumptions=_assumptions,
                        )
                        # Signal caller to end execution round
                        env_context["_gate_waiting"] = True
                        env_context["_gate_context"] = {
                            "gate_id": _gate_ctx.gate_id,
                            "gate_type": _gate_ctx.gate_type,
                            "blocking_questions": _gate_ctx.blocking_questions,
                        }
                        logger.info(
                            "[GateRuntime] Execution blocked: gate %s created, "
                            "session should transition to WAITING_INPUT",
                            _gate_ctx.gate_id,
                        )
                    elif self._collaboration_gate is not None:
                        # Fallback: legacy in-memory suspend
                        from app.avatar.runtime.task.collaboration_gate import GateRequest, GateType
                        _gate_req = GateRequest(
                            gate_type=GateType.CLARIFICATION,
                            trigger_reason="pre_execution_blocked",
                            required_info={
                                "blocking_questions": [
                                    {"question": q.question, "priority": q.priority.value,
                                     "related_field": q.related_field}
                                    for q in _readiness.blocking_questions
                                ]
                            },
                        )
                        await self._collaboration_gate.suspend(_gate_req, env_context)
                        _readiness = self._clarification_engine.assess(_task_def)
                elif _readiness.status == "conditional":
                    # Auto-adopt assumptions: merge into TaskDefinition and
                    # remove the corresponding open_questions so downstream
                    # consumers see a clean, ready-to-execute definition.
                    if _readiness.suggested_assumptions:
                        _adopted = []
                        for a in _readiness.suggested_assumptions:
                            _adopted.append({
                                "text": getattr(a, "text", str(a)),
                                "confidence": getattr(a, "confidence_level", "medium"),
                            })
                            # Merge into TaskDefinition.assumptions
                            if _task_def is not None and a not in _task_def.assumptions:
                                _task_def.assumptions.append(a)
                        # Remove adopted questions from open_questions
                        if _task_def is not None:
                            _adopted_texts = {a["text"] for a in _adopted}
                            _task_def.open_questions = [
                                q for q in _task_def.open_questions
                                if q not in _adopted_texts
                            ]
                        env_context["_adopted_assumptions"] = _adopted
                        logger.info(
                            "[ClarificationEngine] Auto-adopted %d assumptions "
                            "(conditional → ready): %s",
                            len(_adopted),
                            [a["text"][:80] for a in _adopted],
                        )
            except Exception as _ce_err:
                logger.warning(f"[GraphController] ClarificationEngine failed: {_ce_err}")

        # 18.A3: ComplexityAnalyzer
        if self._complexity_analyzer is not None and not env_context.get("_skip_complexity") and not env_context.get("_gate_resumed"):
            try:
                # ── Complexity unification: if upstream (e.g. ComplexityEvaluator
                # in Supervisor/main.py) already computed a result, reuse it
                # instead of re-classifying. This prevents the dual-standard
                # problem where upstream says "simple" and downstream says "complex".
                _upstream_complexity = env_context.get("_upstream_complexity_result")
                if _upstream_complexity is not None:
                    _complexity = _upstream_complexity
                    logger.info(
                        "[ComplexityAnalyzer] Reusing upstream result: type=%s",
                        getattr(_complexity, "task_type", "unknown"),
                    )
                elif _task_def is not None:
                    _complexity = self._complexity_analyzer.classify_from_task_definition(_task_def)
                else:
                    _complexity = self._complexity_analyzer.classify_from_text(intent)

                # Observability: record complexity analysis in graph metadata
                if _complexity is not None and hasattr(graph, 'metadata') and graph.metadata is not None:
                    graph.metadata["complexity_analysis"] = {
                        "task_type": getattr(_complexity, "task_type", "unknown"),
                        "estimated_phases": getattr(_complexity, "estimated_phases", 0),
                        "phase_hints": getattr(_complexity, "phase_hints", []),
                        "signals": getattr(_complexity, "signals", []),
                        "why": getattr(_complexity, "reasoning", "") or getattr(_complexity, "explanation", ""),
                    }
                    logger.info(
                        "[ComplexityAnalyzer] Result: type=%s, phases=%d, signals=%s",
                        _complexity.task_type,
                        getattr(_complexity, "estimated_phases", 0),
                        getattr(_complexity, "signals", []),
                    )

                # ── Store as single source of truth in env_context ──────
                # All downstream consumers (router, planner, plan_executor)
                # MUST read this instead of re-classifying.
                if _complexity is not None:
                    env_context["_complexity_result"] = _complexity

                try:
                    from app.avatar.runtime.observability.debug_event_stream import get_debug_event_stream
                    get_debug_event_stream().emit("created", "ComplexityResult", f"task_{id(graph)}", f"type={_complexity.task_type if _complexity else 'unknown'}")
                except Exception:
                    pass
            except Exception as _ca_err:
                logger.warning(f"[GraphController] ComplexityAnalyzer failed: {_ca_err}")

        # 18.A4: TaskRuntimeState
        try:
            from app.avatar.runtime.task.runtime_state import TaskRuntimeState
            _task_runtime_state = TaskRuntimeState()
            env_context["task_runtime_state"] = _task_runtime_state
        except Exception as _trs_err:
            logger.warning(f"[GraphController] TaskRuntimeState creation failed: {_trs_err}")

        return _task_def, _readiness, _complexity, _task_runtime_state

    def _setup_narrative_manager(
        self,
        session_id: Optional[str],
        exec_session_id: str,
        graph_id: str,
        intent: str,
        sub_goals: List[str],
    ) -> Any:
        """Initialize NarrativeManager with fallback degradation."""
        try:
            from app.avatar.runtime.narrative.execution_narrative import NarrativeManager as _NM
            from app.avatar.runtime.narrative.narrative_mapper import NarrativeMapper as _NMapper
            from app.io.manager import SocketManager
            _socket_mgr = SocketManager.get_instance()
            _event_bus = self.runtime.event_bus
            return _NM(
                session_id=session_id or exec_session_id,
                task_id=graph_id,
                goal=intent,
                mapper=_NMapper(),
                socket_manager=_socket_mgr,
                event_bus=_event_bus,
                sub_goals=sub_goals,
            )
        except Exception as _nm_err:
            logger.warning(f"[GraphController] NarrativeManager init failed: {_nm_err}")
            try:
                from app.avatar.runtime.narrative.execution_narrative import FallbackNarrativeManager as _FNM
                from app.io.manager import SocketManager
                _socket_mgr = SocketManager.get_instance()
                _event_bus = self.runtime.event_bus
                return _FNM(
                    session_id=session_id or exec_session_id,
                    task_id=graph_id,
                    socket_manager=_socket_mgr,
                    event_bus=_event_bus,
                )
            except Exception as _fb_err:
                logger.warning(f"[GraphController] FallbackNarrativeManager also failed: {_fb_err}")
                from app.avatar.runtime.narrative.execution_narrative import FallbackNarrativeManager as _FNM
                _event_bus = getattr(self.runtime, 'event_bus', None)
                return _FNM(
                    session_id=session_id or exec_session_id,
                    task_id=graph_id,
                    event_bus=_event_bus,
                )
