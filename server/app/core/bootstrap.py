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
        self._warmup_skills()
        await self._init_data_layer()
        self._warmup_executors()
        self._init_runtime(llm_client)
        self._init_router(llm_client, llm_logger)
        self._init_log_aggregator(llm_logger)
        self._init_socket_bridge()
        self._init_scheduler()
        self._init_long_task_runtime()
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
