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

        # 动态获取当前工作目录（统一入口）
        from app.core.workspace.manager import get_current_workspace
        try:
            current_workspace = get_current_workspace()
        except Exception as e:
            logger.warning(f"Failed to get current workspace, using default: {e}")
            current_workspace = self.base_path

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
            try:
                from app.avatar.runtime.graph.controller.graph_controller import GraphController
                from app.avatar.runtime.graph.scheduler.scheduler import Scheduler
                from app.avatar.runtime.graph.executor.graph_executor import GraphExecutor
                from app.avatar.runtime.graph.executor.node_runner import NodeRunner
                from app.avatar.runtime.graph.runtime.graph_runtime import GraphRuntime
                from app.avatar.runtime.graph.planner.graph_planner import GraphPlanner

                scheduler = Scheduler()

                # SessionWorkspace + ArtifactCollector + StepTraceStore
                _workspace = None
                _artifact_collector = None
                _trace_store = None
                try:
                    from app.avatar.runtime.workspace import get_session_workspace_manager
                    from app.avatar.runtime.workspace.artifact_collector import ArtifactCollector
                    from app.avatar.runtime.graph.storage.artifact_store import ArtifactStore
                    from app.avatar.runtime.graph.storage.step_trace_store import StepTraceStore
                    from app.avatar.runtime.graph.storage.artifact_store import LocalStorageBackend
                    from app.core.config import AVATAR_ARTIFACTS_DIR

                    # workspace 不在 init 时绑定具体 session。
                    # GraphController._execute_react_mode 会从 env_context["session_id"]
                    # 动态创建正确的 SessionWorkspace，并注入到 ExecutionContext。
                    # 这里只初始化无状态的 ArtifactCollector 和 TraceStore（可复用）。
                    _artifact_backend = LocalStorageBackend(
                        base_path=str(AVATAR_ARTIFACTS_DIR)
                    )
                    _artifact_store = ArtifactStore(backend=_artifact_backend)
                    _artifact_collector = ArtifactCollector(artifact_store=_artifact_store)
                    _trace_store = StepTraceStore()
                    logger.info("[AvatarMain] ArtifactCollector + StepTraceStore ready")
                except Exception as ws_err:
                    logger.warning(f"[AvatarMain] Artifact/Trace init failed: {ws_err}")
                    _artifact_collector = None
                    _trace_store = None

                # P0/P2: 初始化 ArtifactRegistry、PolicyEngine、BudgetAccount
                _artifact_registry = None
                _policy_engine = None
                _budget_account = None
                try:
                    from app.avatar.runtime.artifact.registry import PersistentArtifactRegistry
                    from app.avatar.runtime.policy.policy_engine import PolicyEngine
                    from app.avatar.runtime.policy.budget_account import BudgetAccount
                    # ArtifactRegistry 用 "global" session 作为共享注册表
                    _artifact_registry = PersistentArtifactRegistry(session_id="global")
                    # PolicyEngine 默认无规则（ALLOW all），规则可通过 /api/policy 热加载
                    _policy_engine = PolicyEngine()
                    _budget_account = BudgetAccount(trace_store=_trace_store)
                    logger.info("[AvatarMain] PolicyEngine + BudgetAccount + ArtifactRegistry ready")
                except Exception as pe_err:
                    logger.warning(f"[AvatarMain] PolicyEngine/BudgetAccount init failed: {pe_err}")

                self._graph_executor = GraphExecutor(
                    base_path=self.base_path,  # fallback（WorkspaceManager 未初始化时）
                    memory_manager=self.memory_manager,
                    learning_manager=self.learning_manager,
                    workspace=None,  # workspace 由 GraphController 按 session_id 动态注入
                    artifact_registry=_artifact_registry,
                    trace_store=_trace_store,
                    policy_engine=_policy_engine,
                    budget_account=_budget_account,
                )
                graph_executor = self._graph_executor
                node_runner = NodeRunner(
                    executor=graph_executor,
                    workspace=None,  # workspace 由 ExecutionContext 携带，NodeRunner 从 context 取
                    artifact_collector=_artifact_collector,
                    trace_store=_trace_store,
                )
                graph_runtime = GraphRuntime(
                    scheduler=scheduler,
                    node_runner=node_runner,
                    event_bus=self.event_bus,
                )
                graph_planner = GraphPlanner(llm_client=self.llm_client)

                # PlannerGuard with ApprovalService
                from app.avatar.runtime.graph.guard.planner_guard import PlannerGuard, GuardConfig
                from app.services.approval_service import get_approval_service
                _guard = PlannerGuard(
                    config=GuardConfig(
                        workspace_root=str(self.base_path),
                        enforce_workspace_isolation=True,
                    ),
                    approval_manager=get_approval_service(),
                )

                # ── complex-task-execution-quality 组件初始化 ──
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
                    logger.info("[AvatarMain] Task understanding components ready "
                                "(TaskDef/Clarification/Complexity/Batch/Phased/Collaboration)")
                except Exception as tu_err:
                    logger.warning(f"[AvatarMain] Task understanding components init failed: {tu_err}")

                self._graph_controller = GraphController(
                    planner=graph_planner,
                    runtime=graph_runtime,
                    guard=_guard,
                    evolution_pipeline=self._init_evolution_pipeline(),
                    task_def_engine=_task_def_engine,
                    clarification_engine=_clarification_engine,
                    complexity_analyzer=_complexity_analyzer,
                    batch_plan_builder=_batch_plan_builder,
                    phased_planner=_phased_planner,
                    collaboration_gate=_collaboration_gate,
                )
            except Exception as gc_err:
                logger.warning(f"[AvatarMain] GraphController init failed: {gc_err}")
                self._graph_controller = None
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

    def handle_request(self, user_request: str) -> Any:
        if not self._graph_controller:
            raise RuntimeError("GraphController not initialized (missing LLM/TaskPlanner)")
        env_context = self._build_env_context(user_request=user_request)
        # Delegate to GraphController for new architecture
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self._graph_controller.execute(user_request, mode="react")
        )

    def _init_runtime_kernel(self) -> None:
        """Initialize RuntimeKernel and register all subsystems.

        Only called when runtime_kernel feature flag is enabled.

        Subsystems registered:
        - graph_adapter (GraphControllerAdapter)
        - environment_model (EnvironmentModel)
        - event_bus_v2 (EventBusV2)
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

            # ── EventBusV2 (sense phase event source) ──
            event_bus_v2 = None
            try:
                from .events.event_bus_v2 import EventBusV2
                event_bus_v2 = EventBusV2()
                self._runtime_kernel.register_subsystem("event_bus_v2", event_bus_v2)
            except Exception as e:
                logger.debug("[AvatarMain] EventBusV2 init skipped: %s", e)

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

            # ── AgentLoop (heartbeat driver) ──
            # tick() flow: sense → schedule → execute → monitor → decide → apply
            self._runtime_agent_loop = AgentLoop(
                kernel=self._runtime_kernel,
                scheduler=task_scheduler,
                monitor=self_monitor,
                graph_adapter=adapter,
                environment_model=env_model,
            )

            self._runtime_kernel.start()
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
            RunStore.update_status(run_record.id, "running")
            
            if self._graph_controller:
                # New architecture: use GraphController
                if original_metadata:
                    intent.metadata.update(original_metadata)

                env_context = self._build_env_context(user_request=intent.goal)
                env_context["run_id"] = run_record.id
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

                # 注入确定性指代消解结果（由 task_executor 预计算，Planner 直接使用）
                resolved_inputs = intent.metadata.get("resolved_inputs")
                if resolved_inputs:
                    env_context["resolved_inputs"] = resolved_inputs

                # is_complex no longer gates budget — planner self-regulates

                graph_result = await self._graph_controller.execute(
                    intent.goal, mode="react", env_context=env_context,
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

                RunStore.update_status(run_record.id, "completed", summary=f"✅ 成功完成任务：{task_record.title}")
            elif self.task_planner is not None:
                pass  # no planner without controller
            else:
                raise RuntimeError("Cannot execute intent without an active GraphController/Planner.")

        except Exception as e:
            RunStore.update_status(run_record.id, "failed", summary=f"❌ 任务执行失败: {str(e)}", error_message=str(e))
            # Re-raise so API returns 500 or catches it
            raise
        
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
        from app.core.workspace.manager import get_current_workspace
        try:
            current_workspace = get_current_workspace()
        except Exception as e:
            logger.warning(f"Failed to get current workspace, using default: {e}")
            current_workspace = self.base_path
        
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
        """停止后台内存清理任务"""
        if self.cleanup_task:
            await self.cleanup_task.stop()
    
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
            
            # 获取 fallback skill
            fallback_skill_cls = skill_registry.get("llm.fallback")
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
