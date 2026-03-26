# runtime/main.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
import logging
from platform import system
import json
import asyncio

from app.avatar.intent import IntentSpec
from app.avatar.planner.models import Task
from app.avatar.skills import SkillContext
from app.avatar.skills.registry import skill_registry
from app.db import TaskStore, RunStore, Run as RunRecord
from app.avatar.runtime.monitoring import StepLogger
from app.avatar.runtime.monitoring.loggers import DatabaseStepLogger
from app.avatar.runtime.core import TaskContext, StepContext, ExecutionContext
from app.avatar.memory.manager import MemoryManager
from app.avatar.memory.provider import MemoryProvider
from app.avatar.skills.guard import PolicySkillGuard
from app.avatar.runtime.events import EventBus, EventType

logger = logging.getLogger(__name__)


@dataclass
class _SkillCaller:
    """
    Pure V2 Adapter.
    """

    base_path: Path
    dry_run: bool = False
    memory_manager: Optional[Any] = None
    learning_manager: Optional[Any] = None
    step_logger: Optional[StepLogger] = None
    run_id: Optional[str] = None
    execution_context: Optional[TaskContext] = None
    workspace_manager: Optional[Any] = None
    user_request: Optional[str] = None  # 原始用户请求，用于意图检测

    def __getstate__(self):
        """
        自定义序列化：排除不可序列化的对象
        
        ProcessExecutor 需要通过 pickle 传递 _SkillCaller 到子进程。
        """
        state = {
            'base_path': self.base_path,
            'dry_run': self.dry_run,
            'user_request': self.user_request,
            # 不序列化：memory_manager, learning_manager, step_logger, run_id, execution_context, workspace_manager
        }
        return state

    def __setstate__(self, state):
        """
        自定义反序列化：恢复可序列化的字段
        """
        self.base_path = state.get('base_path')
        self.dry_run = state.get('dry_run', False)
        self.user_request = state.get('user_request')
        # 不可序列化的字段设置为 None
        self.memory_manager = None
        self.learning_manager = None
        self.step_logger = None
        self.run_id = None
        self.execution_context = None
        self.workspace_manager = None

    async def call_skill(self, name: str, params: Dict[str, Any], step_ctx: Optional[StepContext] = None) -> Any:
        skill_cls = skill_registry.get(name)
        if not skill_cls:
            raise ValueError(f"Skill not found: {name}")
        
        # Validation: Enforce V2 Spec
        if not hasattr(skill_cls, 'spec') or not skill_cls.spec.input_model:
             raise ValueError(f"Skill '{name}' is not a valid V2 skill (missing input_model).")

        skill_instance = skill_cls()

        # 动态获取当前 workspace（用户可能已通过 UI 切换），
        # 仅在 base_path 未显式设置（测试/隔离场景）时 fallback
        from app.core.workspace.manager import get_current_workspace
        try:
            current_workspace = get_current_workspace()
        except Exception:
            current_workspace = None
        if current_workspace is None:
            if self.base_path is not None:
                current_workspace = self.base_path
            else:
                current_workspace = Path.cwd()

        ctx = SkillContext(
            base_path=current_workspace,
            workspace_root=current_workspace,
            dry_run=self.dry_run,
            memory_manager=self.memory_manager,
            learning_manager=self.learning_manager,
            execution_context=self.execution_context,
            extra={
                "step_ctx": step_ctx,
                "user_request": self.user_request
            } if step_ctx else {"user_request": self.user_request}
        )
        
        # Parameter Alias Mapping — 基于 spec.aliases 做参数名容错
        # aliases 是 skill 名称别名，不是参数别名，所以这里直接跳过

        # Pydantic Validation
        try:
            input_obj = skill_cls.spec.input_model(**params)
        except Exception as e:
            raise ValueError(f"Invalid parameters for skill '{name}': {e}")

        # Run (Async)
        result = skill_instance.run(ctx, input_obj)
        if asyncio.iscoroutine(result):
            return await result
        return result


class AvatarMain:
    def __init__(
        self,
        base_path: str | Path,
        *,
        memory_manager: Optional[MemoryManager] = None,
        learning_manager: Optional[Any] = None,
        runner: Optional[Any] = None,
        task_planner: Optional[Any] = None,
        llm_client: Optional[Any] = None,
        state_store: Optional[Any] = None,
        step_logger: Optional[StepLogger] = None,
        dry_run: bool = False,
        event_bus: Optional[EventBus] = None,
        workspace_manager: Optional[Any] = None,
        use_tool_calling: bool = False,  # deprecated, kept for backward compat
        compiler: Optional[Any] = None,  # deprecated, kept for backward compat
    ) -> None:
        self.base_path = Path(base_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.dry_run = dry_run
        self.llm_client = llm_client
        self.workspace_manager = workspace_manager

        # Initialize Memory Manager if not provided
        if memory_manager is None:
            from app.avatar.memory.manager import MemoryManagerConfig
            from app.core.config import AVATAR_MEMORY_DIR
            memory_config = MemoryManagerConfig(
                root_dir=AVATAR_MEMORY_DIR,
                use_inmemory_working_state=True
            )
            self.memory_manager = MemoryManager.from_local_dir(memory_config)
        else:
            self.memory_manager = memory_manager
        self.memory_provider = MemoryProvider(self.memory_manager)
        self.learning_manager = learning_manager
        
        # Initialize Memory Cleanup Task (optional)
        self.cleanup_task = None
        try:
            from app.avatar.memory.cleanup_task import MemoryCleanupTask
            self.cleanup_task = MemoryCleanupTask(
                memory_manager=self.memory_manager,
                interval_hours=24,  # 每 24 小时清理一次
                days_to_keep=30,    # 保留最近 30 天
                keep_successful_tasks=True,  # 永久保留成功任务
            )
            logger.info("Memory cleanup task initialized")
        except Exception as cleanup_err:
            logger.warning(f"Failed to initialize cleanup task: {cleanup_err}")
        # Use the global StepLogger configuration which is centralized in logging config
        # But for now we default to DatabaseStepLogger
        self.step_logger = step_logger or DatabaseStepLogger()
        
        # Ensure our global logger is configured for runtime
        # This is where we could hook in SocketLogHandler if it wasn't global
        
        self.event_bus = event_bus or EventBus()
        
        # runner 参数保留向后兼容，实际执行走 GraphController
        if runner is not None:
            self.runner = runner
        else:
            self.runner = None
        
        if task_planner is not None:
            self.task_planner = task_planner
        elif llm_client is not None:
            from app.avatar.planner.registry import create_planner
            # 🎯 使用 InteractiveLLMPlanner（ReAct Pattern）
            self.task_planner = create_planner(
                "interactive_llm", 
                llm_client=llm_client
            )
        else:
            self.task_planner = None

        if state_store is None:
            from app.avatar.planner.base import StateStore
            class _SimpleMemoryStateStore:
                def __init__(self):
                    self._tasks = {}
                def save_task(self, task: Task) -> None:
                    self._tasks[task.id] = task
                def load_task(self, task_id: str) -> Optional[Task]:
                    return self._tasks.get(task_id)
            self.state = _SimpleMemoryStateStore()
        else:
            self.state = state_store

        self.skill_guard = PolicySkillGuard()

        self._base_skill_caller = _SkillCaller(
            base_path=self.base_path,
            dry_run=self.dry_run,
            memory_manager=self.memory_manager,
            learning_manager=self.learning_manager,
            step_logger=self.step_logger,
            workspace_manager=self.workspace_manager,
        )

        if self.task_planner:
            # Use GraphController (new architecture) instead of AgentLoop
            from app.avatar.runtime.graph.controller.graph_controller import GraphController
            from app.avatar.runtime.graph.scheduler.scheduler import Scheduler
            from app.avatar.runtime.graph.executor.graph_executor import GraphExecutor
            from app.avatar.runtime.graph.executor.node_runner import NodeRunner
            from app.avatar.runtime.graph.runtime.graph_runtime import GraphRuntime
            from app.avatar.runtime.graph.planner.graph_planner import GraphPlanner

            scheduler = Scheduler()

            # SessionWorkspace + ArtifactCollector + StepTraceStore（可选）
            _workspace = None
            _artifact_collector = None
            _trace_store = None
            try:
                from app.avatar.runtime.workspace import get_session_workspace_manager
                from app.avatar.runtime.workspace.artifact_collector import ArtifactCollector
                from app.avatar.runtime.graph.storage.artifact_store import ArtifactStore
                from app.avatar.runtime.graph.storage.step_trace_store import get_step_trace_store
                from app.avatar.runtime.graph.storage.artifact_store import LocalStorageBackend
                from app.core.config import AVATAR_ARTIFACTS_DIR

                _artifact_backend = LocalStorageBackend(
                    base_path=str(AVATAR_ARTIFACTS_DIR)
                )
                _artifact_store = ArtifactStore(backend=_artifact_backend)
                _artifact_collector = ArtifactCollector(artifact_store=_artifact_store)
                _trace_store = get_step_trace_store()
                logger.info("[AvatarMain] ArtifactCollector + StepTraceStore ready")
            except Exception as ws_err:
                logger.warning(f"[AvatarMain] Artifact/Trace init failed (non-critical): {ws_err}")

            # P0/P2: ArtifactRegistry、PolicyEngine、BudgetAccount（可选）
            _artifact_registry = None
            _policy_engine = None
            _budget_account = None
            try:
                from app.avatar.runtime.artifact.registry import PersistentArtifactRegistry
                from app.avatar.runtime.policy.policy_engine import PolicyEngine
                from app.avatar.runtime.policy.budget_account import BudgetAccount
                _artifact_registry = PersistentArtifactRegistry(session_id="global")
                _policy_engine = PolicyEngine()
                _budget_account = BudgetAccount(trace_store=_trace_store)
                logger.info("[AvatarMain] PolicyEngine + BudgetAccount + ArtifactRegistry ready")
            except Exception as pe_err:
                logger.warning(f"[AvatarMain] PolicyEngine/BudgetAccount init failed (non-critical): {pe_err}")

            # 核心组件：GraphExecutor / NodeRunner / GraphRuntime（失败则 re-raise）
            self._graph_executor = GraphExecutor(
                base_path=self.base_path,
                memory_manager=self.memory_manager,
                learning_manager=self.learning_manager,
                workspace=None,
                artifact_registry=_artifact_registry,
                trace_store=_trace_store,
                policy_engine=_policy_engine,
                budget_account=_budget_account,
            )
            graph_executor = self._graph_executor
            node_runner = NodeRunner(
                executor=graph_executor,
                workspace=None,
                artifact_collector=_artifact_collector,
                trace_store=_trace_store,
            )
            graph_runtime = GraphRuntime(
                scheduler=scheduler,
                node_runner=node_runner,
                event_bus=self.event_bus,
            )
            graph_planner = GraphPlanner(llm_client=self.llm_client)

            # PlannerGuard（失败则 re-raise，安全组件不可缺）
            from app.avatar.runtime.graph.guard.planner_guard import PlannerGuard, GuardConfig
            from app.services.approval_service import get_approval_service
            _guard = PlannerGuard(
                config=GuardConfig(
                    workspace_root=str(self.base_path),
                    enforce_workspace_isolation=True,
                ),
                approval_manager=get_approval_service(),
            )

            # complex-task-execution-quality 组件（可选）
            _task_def_engine = None
            _clarification_engine = None
            _complexity_analyzer = None
            _batch_plan_builder = None
            _phased_planner = None
            _collaboration_gate = None
            try:
                from app.avatar.runtime.task.task_definition import TaskDefinitionEngine
                from app.avatar.runtime.task.clarification import ClarificationEngine
                from app.avatar.planner.composite.analyzer.complexity import ComplexityAnalyzer
                from app.avatar.runtime.graph.planner.batch_plan_builder import BatchPlanBuilder
                from app.avatar.runtime.task.phased_planner import PhasedPlanner
                from app.avatar.runtime.task.collaboration_gate import CollaborationGate

                _task_def_engine = TaskDefinitionEngine()
                _clarification_engine = ClarificationEngine()
                _complexity_analyzer = ComplexityAnalyzer(llm_client=self.llm_client)
                _batch_plan_builder = BatchPlanBuilder()
                _phased_planner = PhasedPlanner()
                _collaboration_gate = CollaborationGate()
                logger.info("[AvatarMain] Task understanding components ready")
            except Exception as tu_err:
                logger.warning(f"[AvatarMain] Task understanding components init failed (non-critical): {tu_err}")

            self._graph_controller = GraphController(
                planner=graph_planner,
                runtime=graph_runtime,
                guard=_guard,
                evolution_pipeline=self._init_evolution_pipeline(),
                budget_account=_budget_account,
                task_def_engine=_task_def_engine,
                clarification_engine=_clarification_engine,
                complexity_analyzer=_complexity_analyzer,
                batch_plan_builder=_batch_plan_builder,
                phased_planner=_phased_planner,
                collaboration_gate=_collaboration_gate,
            )
            # AgentLoop removed - _agent_loop kept as None for backward compat
            self._agent_loop = None
        else:
            self._graph_controller = None
            self._agent_loop = None

        # ── RuntimeKernel initialization (feature-flag protected) ──
        self._runtime_kernel = None
        self._runtime_kernel_enabled = False
        try:
            from .feature_flags import get_capability_registry
            registry = get_capability_registry()
            self._runtime_kernel_enabled = registry.is_available("runtime_kernel")
            if self._runtime_kernel_enabled:
                self._init_runtime_kernel()
        except Exception as rk_err:
            logger.debug(f"[AvatarMain] RuntimeKernel init skipped: {rk_err}")
            self._runtime_kernel_enabled = False

    async def handle_request(self, user_request: str) -> Any:
        """同步入口已废弃，改为 async。实际调用路径走 run_intent。"""
        if not self._graph_controller:
            raise RuntimeError("GraphController not initialized (missing LLM/TaskPlanner)")
        return await self._graph_controller.execute(user_request, mode="react")

    def _init_runtime_kernel(self) -> None:
        """Initialize RuntimeKernel and register all subsystems.

        Only called when runtime_kernel feature flag is enabled.

        Subsystems registered:
        - graph_adapter (GraphControllerAdapter)
        - environment_model (EnvironmentModel)
        - event_bus (EventBus with buffer/trigger/source capabilities)
        - memory_system (MemorySystem)
        - self_monitor (SelfMonitor)
        - policy_engine_v2 (PolicyEngineV2)
        - action_plane (ActionPlane)
        - collaboration_hub (CollaborationHub)
        - task_scheduler (TaskScheduler)

        AgentLoop.tick() drives: sense → schedule → execute → monitor → decide → apply

        Requirements: 1.1, 1.2, 1.3, 1.4, 2.8, 6.7, 12.4, 12.6
        """
        try:
            from .kernel.runtime_kernel import RuntimeKernel
            from .kernel.agent_loop import AgentLoop
            from .kernel.graph_controller_adapter import GraphControllerAdapter
            from app.avatar.memory.environment_model import EnvironmentModel

            self._runtime_kernel = RuntimeKernel()

            # ── GraphControllerAdapter ──
            adapter = None
            if self._graph_controller is not None:
                adapter = GraphControllerAdapter(graph_controller=self._graph_controller)
                self._runtime_kernel.register_subsystem("graph_adapter", adapter)

            # ── EnvironmentModel ──
            env_model = EnvironmentModel(workspace_path=self.base_path)
            self._runtime_kernel.register_subsystem("environment_model", env_model)

            # ── EventBus (sense phase event source) ──
            # EventBus now has built-in buffer/trigger/source capabilities
            # Register the main event_bus as the sense phase source
            try:
                self._runtime_kernel.register_subsystem("event_bus", self.event_bus)
            except Exception as e:
                logger.debug("[AvatarMain] EventBus registration skipped: %s", e)

            # ── MemorySystem ──
            memory_system = None
            try:
                from app.avatar.memory.system import MemorySystem
                memory_system = MemorySystem(memory_manager=self.memory_manager)
                self._runtime_kernel.register_subsystem("memory_system", memory_system)
            except Exception as e:
                logger.debug("[AvatarMain] MemorySystem init skipped: %s", e)

            # ── CollaborationHub ──
            collaboration_hub = None
            try:
                from .collaboration.collaboration_hub import CollaborationHub
                collaboration_hub = CollaborationHub()
                self._runtime_kernel.register_subsystem("collaboration_hub", collaboration_hub)
            except Exception as e:
                logger.debug("[AvatarMain] CollaborationHub init skipped: %s", e)

            # ── PolicyEngineV2 ──
            policy_engine_v2 = None
            try:
                from .policy.policy_engine import PolicyEngineV2
                policy_engine_v2 = PolicyEngineV2()
                self._runtime_kernel.register_subsystem("policy_engine_v2", policy_engine_v2)
            except Exception as e:
                logger.debug("[AvatarMain] PolicyEngineV2 init skipped: %s", e)

            # ── ActionPlane ──
            try:
                from .action_plane.action_plane import ActionPlane
                action_plane = ActionPlane(
                    policy_engine=policy_engine_v2,
                    collaboration_hub=collaboration_hub,
                )
                self._runtime_kernel.register_subsystem("action_plane", action_plane)
            except Exception as e:
                logger.debug("[AvatarMain] ActionPlane init skipped: %s", e)

            # ── SelfMonitor (monitor phase) ──
            self_monitor = None
            try:
                from .selfmonitor.self_monitor import SelfMonitor
                from .observability.debug_event_stream import get_debug_event_stream
                self_monitor = SelfMonitor(
                    debug_event_stream=get_debug_event_stream(),
                )
                self._runtime_kernel.register_subsystem("self_monitor", self_monitor)
                # Register BudgetMonitor so RuntimeKernel._apply_shrink_budget can find it
                self._runtime_kernel.register_subsystem("budget_monitor", self_monitor._budget)
            except Exception as e:
                logger.debug("[AvatarMain] SelfMonitor init skipped: %s", e)

            # ── TaskScheduler (schedule phase) ──
            task_scheduler = None
            try:
                from .scheduler.task_scheduler import TaskScheduler
                from .agenda.work_queue import WorkQueue
                from .agenda.agenda_manager import AgendaManager
                work_queue = WorkQueue()
                agenda_manager = AgendaManager()
                task_scheduler = TaskScheduler(
                    work_queue=work_queue,
                    agenda_manager=agenda_manager,
                )
                self._runtime_kernel.register_subsystem("work_queue", work_queue)
                self._runtime_kernel.register_subsystem("agenda_manager", agenda_manager)
                self._runtime_kernel.register_subsystem("task_scheduler", task_scheduler)
            except Exception as e:
                logger.debug("[AvatarMain] TaskScheduler init skipped: %s", e)

            # ── Multi-Agent Runtime subsystems ──
            self._multi_agent_registry = None
            self._multi_agent_spawn_policy = None
            self._multi_agent_artifact_store = None
            try:
                from .multiagent import RoleSpecRegistry, SpawnPolicy, ArtifactStore as MArtifactStore
                self._multi_agent_registry = RoleSpecRegistry()
                self._multi_agent_spawn_policy = SpawnPolicy()
                self._multi_agent_artifact_store = MArtifactStore()
                self._runtime_kernel.register_subsystem("role_spec_registry", self._multi_agent_registry)
                self._runtime_kernel.register_subsystem("spawn_policy", self._multi_agent_spawn_policy)
                self._runtime_kernel.register_subsystem("multi_agent_artifact_store", self._multi_agent_artifact_store)
                logger.info("[AvatarMain] Multi-Agent Runtime subsystems registered")
                # 将 Kernel 实例传递给 GraphController，避免 _execute_multi_agent_mode 重复创建
                if self._graph_controller is not None:
                    self._graph_controller._multi_agent_registry = self._multi_agent_registry
                    self._graph_controller._multi_agent_spawn_policy = self._multi_agent_spawn_policy
                    self._graph_controller._multi_agent_artifact_store = self._multi_agent_artifact_store
            except Exception as e:
                logger.debug("[AvatarMain] Multi-Agent Runtime init skipped: %s", e)

            # ── AgentLoop (heartbeat driver, full mode) ──
            # All phases run: sense → schedule → execute → monitor.
            # Execute phase is cooperative — only runs when kernel has an
            # active_task_id assigned by the scheduler, avoiding conflict
            # with GraphController's user-initiated execution.
            self._runtime_agent_loop = AgentLoop(
                kernel=self._runtime_kernel,
                scheduler=task_scheduler,
                monitor=self_monitor,
                graph_adapter=adapter,
                environment_model=env_model,
                monitor_only=False,
            )

            self._runtime_kernel.start()

            # Start AgentLoop as background task (non-blocking)
            self._agent_loop_task = None
            try:
                import asyncio
                loop = asyncio.get_running_loop()
                self._agent_loop_task = loop.create_task(
                    self._runtime_agent_loop.run(interval_s=10.0),
                )
                logger.info("[AvatarMain] AgentLoop started (full mode, 10s interval)")
            except RuntimeError:
                logger.info("[AvatarMain] AgentLoop deferred (no running event loop)")

            logger.info("[AvatarMain] RuntimeKernel initialized with all subsystems")
        except Exception as exc:
            logger.warning(f"[AvatarMain] RuntimeKernel init failed: {exc}")
            self._runtime_kernel = None
            self._runtime_kernel_enabled = False

    async def _legacy_execute(
        self, intent: IntentSpec, task_mode: str, control_handle: Any, on_graph_created: Any
    ) -> RunRecord:
        """Preserve existing execution path for backward compatibility."""
        return await self._run_intent_legacy(intent, task_mode, control_handle, on_graph_created)

    def _init_evolution_pipeline(self):
        """
        Initialize EvolutionPipeline if all dependencies are available.
        Returns None on failure (non-blocking).
        """
        try:
            from app.avatar.evolution.pipeline import EvolutionPipeline
            from app.avatar.evolution.config import EvolutionConfig
            from app.avatar.evolution.trace_collector import TraceCollector
            from app.avatar.evolution.outcome_classifier import OutcomeClassifier
            from app.avatar.evolution.cost_telemetry import CostTelemetryAggregator
            from app.avatar.evolution.reflection_gating import ReflectionGating
            from app.db.database import engine as db_engine

            config = EvolutionConfig()
            trace_collector = TraceCollector(db_engine=db_engine, config=config)
            outcome_classifier = OutcomeClassifier()
            cost_aggregator = CostTelemetryAggregator()
            reflection_gating = ReflectionGating(config=config)

            # Phase 2 components (optional)
            reflection_engine = None
            learning_store = None
            audit_logger = None
            try:
                from app.avatar.evolution.reflection_engine import ReflectionEngine
                from app.avatar.evolution.learning_store import LearningStore
                from app.avatar.evolution.audit_logger import EvolutionAuditLogger
                reflection_engine = ReflectionEngine(
                    llm_factory=self.llm_client,
                    config=config,
                )
                learning_store = LearningStore(db_engine=db_engine, config=config)
                audit_logger = EvolutionAuditLogger()
            except Exception:
                logger.debug("[AvatarMain] Evolution phase 2 components not available, running phase 1 only")

            # Phase 3 components (optional)
            validation_gate = None
            promotion_manager = None
            rollback_manager = None
            try:
                from app.avatar.evolution.validation_gate import ValidationGate
                from app.avatar.evolution.promotion_manager import PromotionManager
                from app.avatar.evolution.rollback_manager import RollbackManager as EvolutionRollbackManager
                validation_gate = ValidationGate(config=config, learning_store=learning_store)
                promotion_manager = PromotionManager(
                    config=config,
                    db_engine=db_engine,
                    learning_store=learning_store,
                )
                rollback_manager = EvolutionRollbackManager(
                    promotion_manager=promotion_manager,
                    learning_store=learning_store,
                    audit_logger=audit_logger,
                )
            except Exception:
                logger.debug("[AvatarMain] Evolution phase 3 components not available, running phase 2 only")

            pipeline = EvolutionPipeline(
                trace_collector=trace_collector,
                outcome_classifier=outcome_classifier,
                cost_aggregator=cost_aggregator,
                reflection_gating=reflection_gating,
                config=config,
                reflection_engine=reflection_engine,
                learning_store=learning_store,
                audit_logger=audit_logger,
                validation_gate=validation_gate,
                promotion_manager=promotion_manager,
                rollback_manager=rollback_manager,
            )
            logger.info(f"[AvatarMain] EvolutionPipeline initialized (phase={pipeline.phase})")
            return pipeline
        except Exception as e:
            logger.debug(f"[AvatarMain] EvolutionPipeline init skipped: {e}")
            return None

    async def run_intent(self, intent: IntentSpec, task_mode: str = "one_shot", control_handle=None, on_graph_created=None) -> RunRecord:
        # Backup metadata (TaskStore/DB serialization might strip non-standard fields)
        original_metadata = intent.metadata.copy()
        
        # ... (Keep existing legacy IntentSpec logic but use V2 skills)
        
        task_record = TaskStore.create(intent, task_mode=task_mode)
        run_record = RunStore.create(task_record.id)
        
        try:
            # ── TaskScheduler admission check ──
            # Check if the new task should be queued or can run immediately
            await self._check_task_admission(task_record.id, intent.goal)

            RunStore.update_status(run_record.id, "running")
            
            if self._graph_controller:
                # New architecture: use GraphController
                if original_metadata:
                    intent.metadata.update(original_metadata)

                env_context = self._build_env_context(user_request=intent.goal)
                env_context["run_id"] = run_record.id
                # Propagate workspace_path from intent metadata (overrides global workspace)
                _intent_workspace = intent.metadata.get("workspace_path")
                if _intent_workspace:
                    env_context["workspace_path"] = _intent_workspace
                # Propagate session_id so NodeRunner can resolve the correct session workspace
                session_id = intent.metadata.get("session_id")
                if session_id:
                    env_context["session_id"] = session_id
                if on_graph_created:
                    env_context["on_graph_created"] = on_graph_created

                # 注入完整对话历史：让 Planner 用 LLM 自身的多轮理解能力做指代消解
                chat_history = intent.metadata.get("chat_history", [])
                if chat_history:
                    env_context["chat_history"] = chat_history

                # 注入对话摘要（两层记忆：事实摘要 + 对话摘要）
                # 覆盖滑动窗口之外的历史上下文
                _memory_mgr = intent.metadata.get("_memory_manager")
                if _memory_mgr and session_id and chat_history:
                    try:
                        from app.avatar.memory.conversation_summary import (
                            get_conversation_summary, should_update_summary,
                            build_summary_from_history, save_conversation_summary,
                        )
                        if should_update_summary(_memory_mgr, session_id, len(chat_history)):
                            existing = get_conversation_summary(_memory_mgr, session_id)
                            summary = build_summary_from_history(chat_history, existing)
                            save_conversation_summary(_memory_mgr, session_id, summary)
                            env_context["conversation_summary"] = summary
                        else:
                            existing = get_conversation_summary(_memory_mgr, session_id)
                            if existing:
                                env_context["conversation_summary"] = existing
                    except Exception as _cs_err:
                        logger.debug(f"[AvatarMain] Conversation summary failed: {_cs_err}")

                # 注入确定性指代消解结果（由 task_executor 预计算，Planner 直接使用）
                resolved_inputs = intent.metadata.get("resolved_inputs")
                if resolved_inputs:
                    env_context["resolved_inputs"] = resolved_inputs

                # 注入 gate resume 上下文（gate 回答后重新进入执行循环）
                gate_env_patch = intent.metadata.get("gate_env_patch")
                if gate_env_patch and isinstance(gate_env_patch, dict):
                    env_context.update(gate_env_patch)
                    env_context["_gate_resumed"] = True

                # is_complex no longer gates budget — planner self-regulates

                # ── 执行模式选择（纯自动路由） ──
                # 用户无需感知执行模式，系统根据任务复杂度自动判定
                # 参考：OpenAI Assistants / Claude / Cursor 的设计理念
                # 内部调试开关：env_context["force_multi_agent"] = True（绕过判定）
                _exec_mode = "react"
                _is_complex_task = False
                if env_context.get("force_multi_agent"):
                    _exec_mode = "multi_agent"
                    _is_complex_task = True
                else:
                    try:
                        from app.avatar.runtime.multiagent.core.supervisor import ComplexityEvaluator
                        _evaluator = ComplexityEvaluator(llm_client=self.llm_client)
                        _assessment = _evaluator.evaluate(intent.goal, env_context)
                        if _assessment.mode == "multi_agent":
                            _exec_mode = "multi_agent"
                            _is_complex_task = True
                        logger.info(
                            "[AvatarMain] Auto-route: mode=%s, reason=%s",
                            _exec_mode, _assessment.reasoning,
                        )
                    except Exception as _route_err:
                        logger.warning("[AvatarMain] Auto-route fallback to react: %s", _route_err)

                # ── 长任务激活链路 ──
                # 为复杂任务自动创建 TaskSession 并启用长任务模式
                task_session_id = env_context.get("task_session_id")
                if not task_session_id and _is_complex_task:
                    try:
                        # 尝试获取 TaskSessionManager 实例
                        import sys
                        from app.core.application import get_app
                        app = get_app()
                        task_session_mgr = getattr(app.state, 'task_session_manager', None)
                        if task_session_mgr:
                            # 创建新的 TaskSession
                            task_session = await task_session_mgr.create_task_session(
                                goal=intent.goal,
                                config={
                                    "env_context": env_context,
                                    "task_mode": task_mode,
                                    "run_id": run_record.id,
                                }
                            )
                            task_session_id = task_session.id
                            env_context["task_session_id"] = task_session_id
                            env_context["_long_task_enabled"] = True
                            logger.info(
                                "[AvatarMain] Created TaskSession for complex task",
                                extra={"task_session_id": task_session_id, "run_id": run_record.id, "exec_mode": _exec_mode},
                            )
                            # 启动执行
                            await task_session_mgr.start_execution(task_session_id)
                        else:
                            logger.error(
                                "[AvatarMain] LONG_TASK_DISABLED: TaskSessionManager not available on app.state. "
                                "Check startup order — task_session_manager must be initialized before first request. "
                                "run_id=%s, exec_mode=%s",
                                run_record.id, _exec_mode,
                            )
                    except Exception as _ts_err:
                        logger.error(
                            "[AvatarMain] LONG_TASK_DISABLED: TaskSession creation failed — long task mode will not activate. "
                            "run_id=%s, exec_mode=%s, error=%s",
                            run_record.id, _exec_mode, _ts_err,
                            exc_info=True,
                        )
                elif task_session_id:
                    # 已有 TaskSession（如从 gate resume 恢复），启用长任务模式
                    env_context["_long_task_enabled"] = True
                    logger.info(f"[AvatarMain] Using existing TaskSession {task_session_id}")

                graph_result = await self._graph_controller.execute(
                    intent.goal, mode=_exec_mode, env_context=env_context,
                    control_handle=control_handle,
                )

                if graph_result.final_status == "failed":
                    # 把 graph 挂到 run_record 上，让外部 catch 能读取节点错误信息
                    _fail_result = RunStore.get(run_record.id)
                    if _fail_result:
                        _fail_result._graph = graph_result.graph
                        err = RuntimeError(graph_result.error_message or "GraphController execution failed")
                        err._run_record = _fail_result
                        raise err
                    raise RuntimeError(graph_result.error_message or "GraphController execution failed")

                RunStore.update_status(run_record.id, "completed", summary=graph_result.summary or f"✅ 成功完成任务：{task_record.title}")
            elif self.task_planner is not None:
                pass  # no planner without controller
            else:
                raise RuntimeError("Cannot execute intent without an active GraphController/Planner.")

        except Exception as e:
            RunStore.update_status(run_record.id, "failed", summary=f"❌ 任务执行失败: {str(e)}", error_message=str(e))
            # Re-raise so API returns 500 or catches it
            raise
        finally:
            # Clear active task in RuntimeKernel so AgentLoop stops monitoring it
            if self._runtime_kernel and self._runtime_kernel_enabled:
                self._runtime_kernel._active_task_id = None
        
        result = RunStore.get(run_record.id)
        # 把 graph 挂到 run_record 上，供 task_executor 读取节点输出
        if self._graph_controller and 'graph_result' in locals() and graph_result.graph:
            result._graph = graph_result.graph
        else:
            result._graph = None
        return result

    def load_task(self, task_id: str) -> Optional[Task]:
        return self.state.load_task(task_id)

    def _build_env_context(self, user_request: str = None) -> Dict[str, Any]:
        # 动态获取当前 workspace（用户可能已通过 UI 切换）
        from app.core.workspace.manager import get_current_workspace
        try:
            current_workspace = get_current_workspace()
        except Exception as e:
            logger.warning(f"Failed to get current workspace: {e}")
            current_workspace = self.base_path if self.base_path is not None else Path.cwd()
        
        # 架构重构：移除 Runtime 层的技能搜索
        # 职责下放：让 Planner 自己搜索技能（符合"谁决策，谁搜索"原则）
        # 参考：LangChain, OpenAI Assistants, Semantic Kernel
        
        # 为 InteractiveLLMPlanner 提供 available_skills
        available_skills = {}
        for skill_cls in skill_registry.iter_skills():
            spec = skill_cls.spec
            skill_name = spec.name

            # 获取参数 schema (input)
            params_schema = {}
            if spec.input_model:
                try:
                    input_schema = spec.input_model.model_json_schema()
                    params_schema = input_schema.get("properties", {})
                except Exception as e:
                    logger.debug(f"Failed to get params schema for {skill_name}: {e}")

            # 获取输出 schema (output) — 让 Planner 知道返回字段名
            output_schema = {}
            if spec.output_model:
                try:
                    out_schema = spec.output_model.model_json_schema()
                    output_schema = out_schema.get("properties", {})
                except Exception as e:
                    logger.debug(f"Failed to get output schema for {skill_name}: {e}")

            available_skills[skill_name] = {
                "description": spec.description,
                "params_schema": params_schema,
                "output_schema": output_schema,
            }
        
        # 注入运行时环境信息，让 Planner 生成正确的平台路径
        import os as _os
        import getpass as _getpass
        _platform = system().lower()  # 'windows' / 'linux' / 'darwin'
        _home = _os.path.expanduser("~")
        try:
            _username = _getpass.getuser()
        except Exception:
            _username = _os.environ.get("USERNAME") or _os.environ.get("USER") or "user"

        # 平台标准目录（确定性，不做猜测）
        if _platform == "windows":
            _desktop = _os.path.join(_home, "Desktop")
            _downloads = _os.path.join(_home, "Downloads")
            _documents = _os.path.join(_home, "Documents")
        elif _platform == "darwin":
            _desktop = _os.path.join(_home, "Desktop")
            _downloads = _os.path.join(_home, "Downloads")
            _documents = _os.path.join(_home, "Documents")
        else:  # linux
            _desktop = _os.path.join(_home, "Desktop")
            _downloads = _os.path.join(_home, "Downloads")
            _documents = _os.path.join(_home, "Documents")

        _system_context = {
            "platform": _platform,
            "username": _username,
            "home_dir": _home,
            "desktop_dir": _desktop,
            "downloads_dir": _downloads,
            "documents_dir": _documents,
            "path_separator": _os.sep,
        }

        return {
            "skill_registry": skill_registry,  # 提供注册表引用，而非预过滤的技能列表
            "available_skills": available_skills,  # 为 ReAct 模式提供 skill 列表
            "workspace_path": str(current_workspace),  # 为文件系统扫描提供路径
            "os": system(),
            "system": _system_context,  # 完整运行时环境，供 Planner 生成正确路径
            "default_paths": {
                "workspace": str(current_workspace),
                "home": _home,
                "desktop": _desktop,
                "downloads": _downloads,
                "documents": _documents,
            },
        }

    def _serialize_result(self, result: Any) -> dict:
        if result is None: return {"type": "none", "value": None}
        if isinstance(result, (str, int, float, bool)): return {"type": type(result).__name__, "value": result}
        if isinstance(result, dict): return {"type": "dict", "value": result}
        if isinstance(result, list): return {"type": "list", "value": result}
        return {"type": "object", "value": str(result)}

    async def _check_task_admission(self, task_id: str, goal: str) -> None:
        """Check TaskScheduler for admission control before executing a task.

        If RuntimeKernel is active, registers the task and evaluates whether
        it should run immediately or be queued. Currently logs warnings for
        resource conflicts but does not block execution (soft enforcement).
        """
        if not self._runtime_kernel or not self._runtime_kernel_enabled:
            return

        try:
            task_scheduler = self._runtime_kernel.get_subsystem("task_scheduler")
            if task_scheduler is None:
                return

            # Register task with kernel for state tracking
            self._runtime_kernel.register_task(task_id)
            # Set as active task so AgentLoop monitor can track it
            self._runtime_kernel._active_task_id = task_id

            # Evaluate scheduling signals
            signals = task_scheduler.evaluate(task_id)
            if signals:
                from app.avatar.runtime.kernel.signals import SignalType
                for sig in signals:
                    if sig.signal_type == SignalType.SWITCH_TASK:
                        logger.warning(
                            "[TaskScheduler] Task switch suggested: %s", sig.reason,
                        )
                    elif sig.signal_type == SignalType.SUSPEND_TASK:
                        logger.warning(
                            "[TaskScheduler] Task suspension suggested: %s", sig.reason,
                        )
                    else:
                        logger.info(
                            "[TaskScheduler] Signal: %s - %s",
                            sig.signal_type, sig.reason,
                        )
        except Exception as e:
            logger.debug("[AvatarMain] TaskScheduler admission check skipped: %s", e)

    def get_capabilities(self) -> Dict[str, Any]:
        """
        Deprecated for Router usage, kept for backward compatibility or other consumers.
        """
        skills_info = []
        # Use describe_skills to get the authoritative list of available skills (by api_name)
        descriptions = skill_registry.describe_skills()
        
        for api_name, info in descriptions.items():
            # Re-format params to match the expected output structure for the prompt
            params = {}
            properties = info.get("params_schema", {})
            required_list = info.get("required", [])
            
            for param_name, prop in properties.items():
                 params[param_name] = {
                     "type": prop.get("type", "string"),
                     "required": param_name in required_list,
                 }
            
            skills_info.append({
                "name": api_name,
                "description": info.get("description", ""),
                "params": params,
            })
        return {"skills": skills_info}

    def get_capabilities_json(self) -> str:
        """
        [Roadmap Phase 1]: Directly return the simple string format from Registry.
        Significantly reduces Router prompt size.
        """
        return skill_registry.describe_skills_simple()
    
    # -------------------------------------------------------------------------
    # Memory Cleanup Management
    # -------------------------------------------------------------------------
    async def start_cleanup(self) -> None:
        """启动后台内存清理任务"""
        if self.cleanup_task:
            await self.cleanup_task.start()
    
    async def stop_cleanup(self) -> None:
        """停止后台内存清理任务 + AgentLoop 后台任务"""
        if self.cleanup_task:
            await self.cleanup_task.stop()

        # Cancel AgentLoop background task
        if hasattr(self, '_agent_loop_task') and self._agent_loop_task is not None:
            self._agent_loop_task.cancel()
            try:
                await self._agent_loop_task
            except asyncio.CancelledError:
                pass
            self._agent_loop_task = None
            logger.info("[AvatarMain] AgentLoop background task cancelled")

        # Stop RuntimeKernel
        if self._runtime_kernel is not None:
            try:
                self._runtime_kernel.shutdown()
            except Exception as e:
                logger.debug("[AvatarMain] RuntimeKernel shutdown: %s", e)
    
    def cleanup_now(self) -> dict:
        """立即执行一次清理（同步版本）"""
        if self.cleanup_task:
            return self.cleanup_task.cleanup_now()
        return {"error": "Cleanup task not initialized"}
    
    async def _try_runtime_fallback(
        self,
        user_request: str,
        error_msg: str,
        env_context: dict
    ) -> Optional[Dict[str, Any]]:
        """
        运行时 Fallback 兜底（用于捕获编排任务失败）
        
        Args:
            user_request: 原始用户请求
            error_msg: 错误消息
            env_context: 环境上下文
        
        Returns:
            Fallback 执行结果，如果失败则返回 None
        """
        try:
            from app.avatar.skills.registry import skill_registry
            
            # 通过 tag 查找 fallback/answer skill（不硬编码 skill 名称）
            fallback_skill_cls = skill_registry.find_by_tags(skill_registry.ANSWER_TAGS)
            if not fallback_skill_cls:
                logger.warning("[Runtime] Fallback skill not found in registry")
                return None
            
            # 准备 fallback 参数
            fallback_params = {
                "user_message": user_request,
                "intent": "runtime_error",
                "reason": error_msg[:500]  # 截断
            }
            
            # 创建 SkillContext
            from app.avatar.skills.context import SkillContext
            fallback_ctx = SkillContext(
                base_path=self.base_path,
                workspace_root=self.base_path,
                dry_run=self.dry_run,
                memory_manager=self.memory_manager,
                learning_manager=self.learning_manager
            )
            
            # 执行 fallback
            fallback_skill = fallback_skill_cls()
            input_obj = fallback_skill_cls.spec.input_model(**fallback_params)
            result = fallback_skill.run(fallback_ctx, input_obj)
            
            # 处理异步结果
            import asyncio
            if asyncio.iscoroutine(result):
                result = await result
            
            # 转换为字典
            if hasattr(result, 'model_dump'):
                return result.model_dump()
            elif isinstance(result, dict):
                return result
            else:
                return {"success": True, "message": str(result)}
                
        except Exception as e:
            logger.error(f"[Runtime] Fallback execution failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
