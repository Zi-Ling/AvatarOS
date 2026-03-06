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
from app.intent_router.router import AvatarRouter
from app.llm import create_llm_client, load_llm_config
from app.io.manager import SocketManager
from app.avatar.runtime.events.bridge import SocketBridge

logger = logging.getLogger(__name__)


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
        self._init_embedding()
        self._warmup_skills()
        self._warmup_executors()  # 新增：预热执行器
        self._warmup_classifier()
        self._init_runtime(llm_client)
        self._init_router(llm_client, llm_logger)
        self._init_log_aggregator(llm_logger)
        self._init_socket_bridge()
        self._init_scheduler()
        self._init_socket_log_handler()
        self._init_fs_watcher()
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
                scheduler_service.stop()
                logger.info("  ├─ Scheduler 已停止")
            except Exception as e:
                logger.warning(f"  ├─ Scheduler 停止失败: {e}")

        if self._bridge:
            try:
                self._bridge.stop()
                logger.info("  ├─ SocketBridge 已停止")
            except Exception as e:
                logger.warning(f"  ├─ SocketBridge 停止失败: {e}")

        if hasattr(self.app.state, "avatar_runtime"):
            try:
                await self.app.state.avatar_runtime.stop_cleanup()
                logger.info("  └─ AvatarMain 已清理")
            except Exception as e:
                logger.warning(f"  └─ AvatarMain 清理失败: {e}")

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

    def _init_embedding(self):
        logger.info("🧬 初始化语义服务...")
        from app.avatar.infra.semantic import get_embedding_service
        try:
            svc = get_embedding_service()
            svc.initialize()
            logger.info("  ✅ 语义服务已启用")
        except Exception as e:
            logger.warning(f"  ⚠️ 语义服务初始化失败（将使用降级方案）: {e}")

    def _warmup_skills(self):
        logger.info("🔥 预热技能索引...")
        from app.avatar.skills.registry import skill_registry
        from app.avatar.planner.selector import skill_selector

        start_time = time.time()
        try:
            skill_registry._ensure_vector_index()
            elapsed = (time.time() - start_time) * 1000
            count = len(skill_registry._skill_names) if skill_registry._index_ready else 0
            if skill_registry._index_ready:
                logger.info(f"  ✅ 技能索引预热完成：{count} 个技能，耗时 {elapsed:.0f}ms")
            else:
                logger.warning("  ⚠️ 技能索引未就绪（将使用降级方案）")
        except Exception as e:
            logger.warning(f"  ⚠️ 技能索引预热失败: {e}")

        try:
            skill_selector.initialize()
            logger.info("  ✅ 技能选择器已就绪")
        except Exception as e:
            logger.warning(f"  ⚠️ 技能选择器初始化失败: {e}")
    
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

    def _warmup_classifier(self):
        logger.info("🔥 预热能力分类器...")
        from app.avatar.infra.semantic.classifier import get_capability_classifier
        start_time = time.time()
        try:
            classifier = get_capability_classifier()
            classifier.warmup()
            elapsed = (time.time() - start_time) * 1000
            cap_count = len(classifier.vectors)
            if cap_count > 0:
                logger.info(f"  ✅ 能力分类器预热完成：{cap_count} 个能力，耗时 {elapsed:.0f}ms")
            else:
                logger.warning("  ⚠️ 能力分类器未就绪（将使用降级方案）")
        except Exception as e:
            logger.warning(f"  ⚠️ 能力分类器预热失败: {e}")

    def _init_runtime(self, llm_client):
        logger.info("🚀 初始化 Avatar 运行时...")
        self.app.state.avatar_runtime = AvatarMain(
            base_path=config.avatar_workspace,
            memory_manager=self.app.state.memory_manager,
            learning_manager=self.app.state.learning_manager,
            llm_client=llm_client,
            dry_run=False,
            workspace_manager=self.app.state.workspace_manager,
        )

    def _init_router(self, llm_client, llm_logger):
        logger.info("🧭 初始化智能路由...")
        from app.intent_router.logging import create_default_router_logger
        from app.avatar.intent import IntentExtractor

        router_logger = create_default_router_logger()
        intent_compiler = IntentExtractor(llm_client)

        self.app.state.avatar_router = AvatarRouter(
            runtime=self.app.state.avatar_runtime,
            llm=llm_client,
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
