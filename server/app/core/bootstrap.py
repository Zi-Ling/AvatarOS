# app/bootstrap.py
"""
应用启动引导：将 lifespan 中的 12+ 组件初始化拆分为独立方法，
统一错误处理和关闭逻辑。
"""
import asyncio
import logging
import time

from app.core.config import config
from app.db import init_db
from app.core.workspace.manager import init_workspace_manager
from app.avatar.memory import MemoryManager, MemoryManagerConfig
from app.avatar.learning import (
    LearningManager, LearningManagerConfig,
    InMemoryNotebook, SkillStatsLearner, UserPreferenceLearner,
)
from app.avatar.runtime.main import AvatarMain
from app.router.router import AvatarRouter
from app.llm import create_llm_client, load_llm_config
from app.io.manager import SocketManager
from app.avatar.runtime.events.bridge import SocketBridge

logger = logging.getLogger(__name__)

# 全局 AvatarMain 实例引用（供 ReplayEngine 等内部组件访问）
_avatar_main_instance: "AvatarMain | None" = None


def get_avatar_main() -> "AvatarMain | None":
    """返回全局 AvatarMain 实例，未初始化时返回 None。"""
    return _avatar_main_instance


class AppBootstrap:
    """应用组件的初始化和关闭管理"""

    def __init__(self, app):
        self.app = app
        self._bridge: SocketBridge | None = None
        self._scheduler_started = False

    async def startup(self):
        """按依赖顺序初始化所有组件"""
        self._init_workspace()
        self._init_database()
        self._init_memory()
        self._init_learning()
        llm_logger = self._init_llm_logger()
        llm_client = self._init_llm_client(llm_logger)
        self.app.state.llm_client = llm_client
        self._warmup_skills()
        await self._init_data_layer()
        self._warmup_executors()
        self._init_runtime(llm_client)
        self._init_router(llm_client, llm_logger)
        self._init_log_aggregator(llm_logger)
        self._init_socket_bridge()
        self._init_scheduler()
        self._init_long_task_runtime()
        self._init_workflow_orchestration()
        self._init_socket_log_handler()
        self._init_fs_watcher()

        # 长任务启动恢复（异步，不阻塞启动）
        if hasattr(self.app.state, "startup_recovery"):
            try:
                report = await self.app.state.startup_recovery.recover_on_startup()
                logger.info(
                    f"  └─ 启动恢复完成: {report['total']} 个非终态会话, "
                    f"{len(report['interrupted'])} 个被标记为 interrupted"
                )
            except Exception as e:
                logger.warning(f"  └─ 启动恢复失败: {e}")

        logger.info("✅ 所有组件初始化完成")

    async def shutdown(self):
        """按逆序关闭所有组件"""
        logger.info("👋 应用关闭，正在清理资源...")

        if hasattr(self.app.state, "fs_watcher"):
            try:
                self.app.state.fs_watcher.stop()
                logger.info("  ├─ FileSystemWatcher 已停止")
            except Exception as e:
                logger.warning(f"  ├─ FileSystemWatcher 停止失败: {e}")

        if self._scheduler_started:
            try:
                from app.services.scheduler_service import scheduler_service
                scheduler_service.scheduler.shutdown(wait=False)
                logger.info("  ├─ Scheduler 已停止")
            except Exception as e:
                logger.warning(f"  ├─ Scheduler 停止失败: {e}")

        if self._bridge:
            try:
                if hasattr(self._bridge, 'stop'):
                    self._bridge.stop()
                elif hasattr(self._bridge, 'disconnect'):
                    self._bridge.disconnect()
                logger.info("  ├─ SocketBridge 已停止")
            except Exception as e:
                logger.warning(f"  ├─ SocketBridge 停止失败: {e}")

        if hasattr(self.app.state, "avatar_runtime"):
            try:
                await self.app.state.avatar_runtime.stop_cleanup()
                logger.info("  ├─ AvatarMain 已清理")
            except Exception as e:
                logger.warning(f"  ├─ AvatarMain 清理失败: {e}")

        # 清理浏览器会话
        if hasattr(self.app.state, "browser_session_manager"):
            try:
                mgr = self.app.state.browser_session_manager
                for sid in list(mgr._sessions.keys()):
                    await mgr.destroy_session(sid)
                logger.info("  ├─ BrowserSessionManager 已清理")
            except Exception as e:
                logger.warning(f"  ├─ BrowserSessionManager 清理失败: {e}")

        # 清理所有执行器（容器池 shutdown、移除容器）
        try:
            from app.avatar.runtime.executor.factory import ExecutorFactory
            ExecutorFactory.cleanup_all()
            logger.info("  └─ ExecutorFactory 已清理")
        except Exception as e:
            logger.warning(f"  └─ ExecutorFactory 清理失败: {e}")

    # ── 各组件初始化方法 ──

    def _init_workspace(self):
        logger.info("📁 初始化工作目录管理器...")
        workspace_mgr = init_workspace_manager(config.avatar_workspace)
        self.app.state.workspace_manager = workspace_mgr
        logger.info(f"  ├─ 当前工作目录: {workspace_mgr.get_workspace()}")

        # 初始化 SessionWorkspaceManager（sandbox session IO 边界，固定在 ~/.avatar/sessions）
        from app.avatar.runtime.workspace import init_session_workspace_manager
        from app.core.config import AVATAR_SESSIONS_DIR
        session_ws_mgr = init_session_workspace_manager(base_path=AVATAR_SESSIONS_DIR)
        self.app.state.session_workspace_manager = session_ws_mgr
        logger.info(f"  └─ Session workspace base: {AVATAR_SESSIONS_DIR}")

    def _init_database(self):
        logger.info("🔧 初始化数据库...")
        init_db()

    def _init_memory(self):
        logger.info("🧠 初始化记忆管理器...")
        from app.core.config import AVATAR_MEMORY_DIR
        self.app.state.memory_manager = MemoryManager.from_local_dir(
            MemoryManagerConfig(
                root_dir=AVATAR_MEMORY_DIR,
                use_inmemory_working_state=True,
            )
        )
        from app.avatar.memory.provider import set_memory_manager
        set_memory_manager(self.app.state.memory_manager)

    def _init_learning(self):
        logger.info("📚 初始化学习管理器...")
        from app.core.config import AVATAR_LEARNING_DIR
        learning_root = AVATAR_LEARNING_DIR
        self.app.state.learning_manager = LearningManager(
            config=LearningManagerConfig(workspace_root=learning_root),
            memory_manager=self.app.state.memory_manager,
        )
        from app.avatar.learning.provider import set_learning_manager
        set_learning_manager(self.app.state.learning_manager)

        self.app.state.learning_manager.register(InMemoryNotebook())
        self.app.state.learning_manager.register(SkillStatsLearner())
        self.app.state.learning_manager.register(UserPreferenceLearner())
        logger.info("  ├─ InMemoryNotebook / SkillStatsLearner / UserPreferenceLearner")

    def _init_llm_logger(self):
        logger.info("📝 初始化 LLM 日志...")
        from app.llm.logging import create_default_llm_logger
        return create_default_llm_logger(source="general")

    def _init_llm_client(self, llm_logger):
        logger.info("🤖 初始化 LLM 客户端...")
        llm_config = load_llm_config()
        return create_llm_client(config=llm_config, logger=llm_logger)

    def _warmup_skills(self):
        logger.info("🔥 预热技能注册表...")
        from app.avatar.skills.registry import skill_registry
        count = len(list(skill_registry.iter_skills()))
        logger.info(f"  ✅ 技能注册表就绪：{count} 个技能")

    async def _init_data_layer(self):
        """初始化结构化数据层（建表、schema 迁移）"""
        logger.info("📊 初始化结构化数据层...")
        try:
            from app.services.data import ensure_initialized
            await ensure_initialized()
            logger.info("  ✅ 结构化数据层就绪")
        except Exception as e:
            logger.warning(f"  ⚠️ 结构化数据层初始化失败: {e}")
    
    def _warmup_executors(self):
        """预热执行器（避免首次执行延迟）"""
        logger.info("🔥 预热执行器...")
        from app.avatar.runtime.executor import ExecutorFactory
        
        start_time = time.time()
        try:
            ExecutorFactory.preload_executors()
            elapsed = (time.time() - start_time) * 1000
            logger.info(f"  ✅ 执行器预热完成，耗时 {elapsed:.0f}ms")
        except Exception as e:
            logger.warning(f"  ⚠️ 执行器预热失败: {e}")

    def _init_runtime(self, llm_client):
        logger.info("🚀 初始化 Avatar 运行时...")

        # Initialize resilience primitives
        try:
            from app.core.resilience import ResilienceRegistry, CircuitBreakerConfig
            resilience = ResilienceRegistry.get_instance()
            resilience.get_or_create_breaker(
                "llm", CircuitBreakerConfig(failure_threshold=5, recovery_timeout_s=60.0),
            )
            resilience.get_or_create_breaker(
                "skill_execution", CircuitBreakerConfig(failure_threshold=10, recovery_timeout_s=30.0),
            )
            resilience.get_or_create_bulkhead("graph_execution", max_concurrent=10, max_queue=20)
            logger.info("  ✅ Resilience primitives initialized")
        except Exception as res_err:
            logger.warning(f"  ⚠️ Resilience init failed: {res_err}")

        # Probe feature flags before AvatarMain init
        try:
            from app.avatar.runtime.feature_flags import probe_modules
            probe_modules()
            logger.info("  ✅ Feature flags probed")
        except Exception as ff_err:
            logger.warning(f"  ⚠️ Feature flags probe failed: {ff_err}")

        global _avatar_main_instance
        self.app.state.avatar_runtime = AvatarMain(
            base_path=config.avatar_workspace,
            memory_manager=self.app.state.memory_manager,
            learning_manager=self.app.state.learning_manager,
            llm_client=llm_client,
            dry_run=False,
            workspace_manager=self.app.state.workspace_manager,
        )
        _avatar_main_instance = self.app.state.avatar_runtime

    def _init_router(self, llm_client, llm_logger):
        logger.info("🧭 初始化智能路由...")
        from app.router.logging import create_default_router_logger
        from app.avatar.intent import IntentExtractor

        router_logger = create_default_router_logger()
        intent_compiler = IntentExtractor(llm_client)

        self.app.state.avatar_router = AvatarRouter(
            runtime=self.app.state.avatar_runtime,
            memory_manager=self.app.state.memory_manager,
            logger=router_logger,
            intent_compiler=intent_compiler,
        )
        self._router_logger = router_logger

    def _init_log_aggregator(self, llm_logger):
        logger.info("📊 初始化日志聚合器...")
        from app.log import LogAggregator
        self.app.state.log_aggregator = LogAggregator(
            router_logger=self._router_logger,
            llm_logger=llm_logger,
            runtime_logger=self.app.state.avatar_runtime.step_logger,
        )

    def _init_socket_bridge(self):
        logger.info("🔌 启动 Socket 桥接器...")
        socket_manager = SocketManager.get_instance()
        self._bridge = SocketBridge(
            event_bus=self.app.state.avatar_runtime.event_bus,
            socket_manager=socket_manager,
        )
        self._bridge.start()

    def _init_scheduler(self):
        logger.info("⏰ 初始化任务调度器...")
        from app.services.scheduler_service import scheduler_service
        scheduler_service.start(avatar_runtime=self.app.state.avatar_runtime)
        self._scheduler_started = True

    def _init_long_task_runtime(self):
        """初始化长任务运行时：组装所有 Manager 并注入 API 层。"""
        logger.info("🔗 初始化长任务运行时...")

        from app.services.task_session_store import TaskSessionStore
        from app.services.step_state_store import StepStateStore
        from app.services.plan_graph_store import PlanGraphStore
        from app.services.artifact_store import ArtifactStore
        from app.services.checkpoint_store import CheckpointStore
        from app.avatar.runtime.graph.artifact_dep_graph import ArtifactDependencyGraph
        from app.avatar.runtime.graph.managers.interrupt_manager import InterruptManager
        from app.avatar.runtime.graph.managers.checkpoint_manager import CheckpointManager
        from app.avatar.runtime.graph.managers.resume_manager import ResumeManager
        from app.avatar.runtime.graph.managers.plan_merge_engine import PlanMergeEngine
        from app.avatar.runtime.graph.managers.delivery_gate import DeliveryGate
        from app.avatar.runtime.graph.managers.task_scheduler import TaskScheduler
        from app.avatar.runtime.graph.managers.task_session_manager import TaskSessionManager
        from app.avatar.runtime.graph.managers.startup_recovery import StartupRecovery

        # Store 层都是静态方法类，直接使用
        # 构建 Manager 依赖图（自底向上）
        artifact_dep_graph = ArtifactDependencyGraph()
        checkpoint_mgr = CheckpointManager(
            checkpoint_store=CheckpointStore,
            step_state_store=StepStateStore,
            plan_graph_store=PlanGraphStore,
        )
        interrupt_mgr = InterruptManager(
            task_session_store=TaskSessionStore,
            step_state_store=StepStateStore,
            checkpoint_manager=checkpoint_mgr,
        )
        resume_mgr = ResumeManager(
            checkpoint_manager=checkpoint_mgr,
            step_state_store=StepStateStore,
            plan_graph_store=PlanGraphStore,
            artifact_store=ArtifactStore,
            task_session_store=TaskSessionStore,
        )
        plan_merge_engine = PlanMergeEngine(
            plan_graph_store=PlanGraphStore,
            checkpoint_manager=checkpoint_mgr,
            step_state_store=StepStateStore,
        )
        delivery_gate = DeliveryGate(
            artifact_dep_graph=artifact_dep_graph,
            step_state_store=StepStateStore,
        )
        task_scheduler = TaskScheduler()

        # 顶层编排器
        task_session_mgr = TaskSessionManager(
            task_session_store=TaskSessionStore,
            task_scheduler=task_scheduler,
            interrupt_manager=interrupt_mgr,
            resume_manager=resume_mgr,
            plan_merge_engine=plan_merge_engine,
            checkpoint_manager=checkpoint_mgr,
            delivery_gate=delivery_gate,
        )

        # 注入 API 层
        from app.api.task_session import set_task_session_manager
        from app.api.task_scheduler_api import set_scheduler
        set_task_session_manager(task_session_mgr)
        set_scheduler(task_scheduler)

        # 保存到 app.state 供其他组件访问
        self.app.state.task_session_manager = task_session_mgr
        self.app.state.task_scheduler = task_scheduler
        self.app.state.artifact_dep_graph = artifact_dep_graph
        self.app.state.interrupt_manager = interrupt_mgr

        # 启动恢复流程
        startup_recovery = StartupRecovery(
            task_session_store=TaskSessionStore,
            interrupt_manager=interrupt_mgr,
            resume_manager=resume_mgr,
        )
        self.app.state.startup_recovery = startup_recovery

        logger.info("  ├─ TaskSessionManager 就绪")
        logger.info("  ├─ TaskScheduler 就绪 (long=1, simple=2)")
        logger.info("  └─ 长任务运行时初始化完成")

    def _init_workflow_orchestration(self):
        """初始化工作流编排层：组装所有 StepExecutor 并注入 InstanceManager。"""
        logger.info("⚙️  初始化工作流编排层...")

        from app.services.workflow.step_executor import (
            OutputContractValidator,
            SkillStepExecutor,
            TaskSessionStepExecutor,
            PollingCompletionWaiter,
        )
        from app.services.workflow.dag_scheduler import WorkflowDAGScheduler
        from app.services.workflow.param_resolver import ParamResolver
        from app.services.workflow.instance_manager import InstanceManager

        # ── 基础组件 ──
        output_validator = OutputContractValidator()
        dag_scheduler = WorkflowDAGScheduler()
        param_resolver = ParamResolver()

        # ── Skill StepExecutor ──
        from app.avatar.skills.registry import skill_registry
        skill_executor = SkillStepExecutor(skill_registry, output_validator)

        # ── TaskSession StepExecutor ──
        from app.services.task_session_store import TaskSessionStore
        task_session_executor = TaskSessionStepExecutor(
            task_session_store=TaskSessionStore,
            avatar_runtime=self.app.state.avatar_runtime,
            completion_waiter=PollingCompletionWaiter(TaskSessionStore),
            output_validator=output_validator,
        )

        # ── Browser Automation StepExecutor ──
        browser_executor = None
        try:
            from app.services.browser.session_manager import SessionManager
            from app.services.browser.executor import BrowserAutomationStepExecutor
            session_manager = SessionManager()
            browser_executor = BrowserAutomationStepExecutor(
                session_manager=session_manager,
                output_validator=output_validator,
            )
            self.app.state.browser_session_manager = session_manager
            logger.info("  ├─ BrowserAutomationStepExecutor 就绪")
        except Exception as e:
            logger.warning(f"  ├─ BrowserAutomationStepExecutor 初始化跳过: {e}")

        # ── L1 Native Adapter StepExecutor ──
        native_adapter_executor = None
        try:
            from app.services.adapter.registry import AdapterRegistry
            from app.services.adapter.security_policy import SecurityPolicy
            from app.services.adapter.executor import NativeAdapterStepExecutor
            from app.services.adapter.examples.file_system import FileSystemAdapter
            from app.services.adapter.examples.http_api import HttpApiAdapter
            from app.services.adapter.examples.shell_command import ShellCommandAdapter

            adapter_registry = AdapterRegistry()
            adapter_registry.register(FileSystemAdapter())
            adapter_registry.register(HttpApiAdapter())
            adapter_registry.register(ShellCommandAdapter())

            security_policy = SecurityPolicy()
            native_adapter_executor = NativeAdapterStepExecutor(
                registry=adapter_registry,
                security_policy=security_policy,
                output_validator=output_validator,
            )
            self.app.state.adapter_registry = adapter_registry
            logger.info(f"  ├─ NativeAdapterStepExecutor 就绪 ({len(adapter_registry.list_all())} adapters)")
        except Exception as e:
            logger.warning(f"  ├─ NativeAdapterStepExecutor 初始化跳过: {e}")

        # ── Execution Routing (RoutingStepExecutor) ──
        routed_executor = None
        try:
            from app.services.adapter.models import ExecutionLayer
            from app.services.execution.strategy_router import StrategyRouter
            from app.services.execution.executor import RoutingStepExecutor

            strategy_router = StrategyRouter(
                adapter_registry=adapter_registry if native_adapter_executor else AdapterRegistry(),
            )

            # 注册各层执行器到 StrategyRouter
            if native_adapter_executor:
                async def _l1_executor(req):
                    """L1 层：委托 NativeAdapterStepExecutor。"""
                    from app.services.execution.strategy_router import LayerResult
                    from app.services.workflow.models import WorkflowStepDef
                    step = WorkflowStepDef(
                        step_id="routing_l1", name="L1 routed",
                        executor_type="native_adapter",
                        params={
                            "adapter_name": req.params.get("adapter_name", ""),
                            "operation_name": req.params.get("operation_name", ""),
                            "operation_params": req.params.get("operation_params", {}),
                        },
                    )
                    result = await native_adapter_executor.execute(step, {}, "routing")
                    return LayerResult(
                        success=result.success,
                        outputs=result.outputs,
                        error_code=result.error or "",
                        degradable=result.success is False,
                    )
                strategy_router.register_layer_executor(ExecutionLayer.L1_NATIVE, _l1_executor)

            if browser_executor:
                async def _l2_executor(req):
                    """L2 层：委托 BrowserAutomationStepExecutor。"""
                    from app.services.execution.strategy_router import LayerResult
                    from app.services.workflow.models import WorkflowStepDef
                    step = WorkflowStepDef(
                        step_id="routing_l2", name="L2 routed",
                        executor_type="browser_automation",
                        params={"actions": req.params.get("actions", [])},
                    )
                    result = await browser_executor.execute(step, {}, "routing")
                    return LayerResult(
                        success=result.success,
                        outputs=result.outputs,
                        error_code=result.error or "",
                        degradable=result.success is False,
                    )
                strategy_router.register_layer_executor(ExecutionLayer.L2_BROWSER, _l2_executor)

            # ── L4 Computer Use ──
            computer_use_runtime = None
            try:
                from app.services.computer.runtime import ComputerUseRuntime
                from app.services.artifact_store import ArtifactStore
                from app.services.approval_service import get_approval_service

                _event_bus = self.app.state.avatar_runtime.event_bus
                _interrupt_mgr = getattr(self.app.state, "interrupt_manager", None)
                _llm_client = self.app.state.llm_client

                computer_use_runtime = ComputerUseRuntime(
                    llm_client=_llm_client,
                    event_bus=_event_bus,
                    artifact_store=ArtifactStore,
                    approval_service=get_approval_service(),
                    interrupt_manager=_interrupt_mgr,
                )

                async def _l4_executor(req):
                    """L4 层：委托 ComputerUseRuntime。"""
                    from app.services.execution.strategy_router import LayerResult
                    result = await computer_use_runtime.execute(
                        goal=req.params.get("goal", ""),
                        ctx=req.params.get("context"),
                    )
                    return LayerResult(
                        success=result.success,
                        outputs={"result_summary": result.result_summary, "steps_taken": result.steps_taken},
                        error_code=result.failure_reason or "",
                        degradable=False,  # L4 是最后一层，不可再降级
                    )
                strategy_router.register_layer_executor(ExecutionLayer.L4_COMPUTER_USE, _l4_executor)
                self.app.state.computer_use_runtime = computer_use_runtime
                logger.info("  ├─ L4 ComputerUseRuntime 已注册到 StrategyRouter")
            except Exception as e:
                logger.warning(f"  ├─ L4 ComputerUseRuntime 注册跳过: {e}")

            routed_executor = RoutingStepExecutor(strategy_router, output_validator)
            self.app.state.strategy_router = strategy_router
            logger.info("  ├─ RoutingStepExecutor 就绪")
        except Exception as e:
            logger.warning(f"  ├─ RoutingStepExecutor 初始化跳过: {e}")

        # ── 组装 InstanceManager ──
        instance_manager = InstanceManager(
            dag_scheduler=dag_scheduler,
            param_resolver=param_resolver,
            skill_executor=skill_executor,
            task_session_executor=task_session_executor,
            browser_automation_executor=browser_executor,
            native_adapter_executor=native_adapter_executor,
            routed_executor=routed_executor,
        )

        # 注入 API 层
        from app.api.workflow.instances import set_instance_manager
        set_instance_manager(instance_manager)
        self.app.state.instance_manager = instance_manager

        logger.info("  └─ 工作流编排层初始化完成")

    def _init_socket_log_handler(self):
        logger.info("📡 初始化 SocketLogHandler...")
        from app.log.socket_handler import SocketLogHandler

        app_logger = logging.getLogger("app")
        app_logger.setLevel(logging.INFO)

        # 避免重复挂载
        socket_handler = None
        for h in app_logger.handlers:
            if isinstance(h, SocketLogHandler):
                socket_handler = h
                break

        if not socket_handler:
            socket_handler = SocketLogHandler()
            socket_handler.setLevel(logging.INFO)
            socket_handler.setFormatter(logging.Formatter("%(message)s"))
            app_logger.addHandler(socket_handler)

        # 确保所有 app.* 子 logger 传播日志
        propagated_count = 0
        for logger_name in logging.Logger.manager.loggerDict:
            if logger_name.startswith("app."):
                child = logging.getLogger(logger_name)
                child.propagate = True
                if child.level == logging.NOTSET or child.level > logging.INFO:
                    child.setLevel(logging.DEBUG)
                propagated_count += 1

        logger.info(f"  ├─ 已配置 {propagated_count} 个子模块的日志传播")

        try:
            socket_handler.loop = asyncio.get_running_loop()
            logger.info("  └─ 已注入 asyncio event loop")
        except RuntimeError:
            logger.info("  └─ Event loop 将在运行时动态获取")

    def _init_fs_watcher(self):
        logger.info("👀 初始化文件系统监控...")
        from app.core.workspace.watcher import FileSystemWatcher
        from app.avatar.runtime.events import Event

        main_loop = asyncio.get_running_loop()
        runtime_event_bus = self.app.state.avatar_runtime.event_bus

        def on_fs_event_safe(event_type, payload):
            try:
                event = Event(type=event_type, source="watcher", payload=payload)
                main_loop.call_soon_threadsafe(runtime_event_bus.publish, event)
            except Exception as e:
                logger.error(f"Error dispatching fs event: {e}")

        fs_watcher = FileSystemWatcher(on_fs_event_safe)
        workspace_mgr = self.app.state.workspace_manager
        current_workspace = workspace_mgr.get_workspace()

        logger.info(f"  ├─ 监控目录: {current_workspace}")
        try:
            fs_watcher.start(current_workspace)
            logger.info("  └─ FileSystemWatcher 启动成功")
        except Exception as e:
            logger.error(f"  └─ FileSystemWatcher 启动失败: {e}")

        workspace_mgr.add_change_listener(fs_watcher.update_path)
        self.app.state.fs_watcher = fs_watcher
