# runtime/main.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
import logging
from platform import system
import json
import asyncio
import traceback
import uuid

from app.avatar.intent import IntentSpec, IntentExtractor # Replaced IntentTaskCompiler
from app.avatar.planner.models import Task, TaskStatus, Step, StepStatus
from app.avatar.planner.models.step import StepResult
from app.avatar.planner.models.subtask import CompositeTask
try:
    from app.avatar.planner.runners.dag_runner import DagRunner  # deprecated
except ImportError:
    DagRunner = None  # type: ignore
from app.avatar.skills import SkillContext
from app.avatar.skills.registry import skill_registry
from app.db import TaskStore, RunStore, StepStore, Run as RunRecord
from app.avatar.runtime.monitoring import StepLogger
from app.avatar.runtime.monitoring.loggers import DatabaseStepLogger
from app.avatar.runtime.core import TaskContext, StepContext, ExecutionContext, SessionContext
try:
    from app.avatar.runtime.loop import AgentLoop  # deprecated, replaced by GraphController
except ImportError:
    AgentLoop = None  # type: ignore
from app.avatar.memory.manager import MemoryManager
from app.avatar.memory.provider import MemoryProvider
# Use new perception manager
from app.avatar.perception.manager import PerceptionManager
from app.avatar.perception.backends.uia import UIABackend
from app.avatar.perception.drivers.web_driver import PlaywrightPerceptionBackend
from app.avatar.skills.guard import AllowAllSkillGuard, PolicySkillGuard
from app.avatar.learning.logger import FileLearningLogger
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

        # 动态获取当前工作目录
        current_workspace = self.base_path
        if self.workspace_manager:
            try:
                current_workspace = self.workspace_manager.get_workspace()
            except Exception as e:
                logger.warning(f"Failed to get workspace from manager, using default: {e}")

        ctx = SkillContext(
            base_path=current_workspace,
            dry_run=self.dry_run,
            memory_manager=self.memory_manager,
            learning_manager=self.learning_manager,
            execution_context=self.execution_context,
            extra={
                "step_ctx": step_ctx,
                "user_request": self.user_request  # 传递用户原始请求
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
        compiler: Optional[IntentExtractor] = None,
        step_logger: Optional[StepLogger] = None,
        dry_run: bool = False,
        event_bus: Optional[EventBus] = None,
        workspace_manager: Optional[Any] = None,
        use_tool_calling: bool = False,
    ) -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.dry_run = dry_run
        self.llm_client = llm_client
        self.workspace_manager = workspace_manager
        self.use_tool_calling = use_tool_calling

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
        
        # 根据 use_tool_calling 选择 runner
        if runner is not None:
            self.runner = runner
        elif use_tool_calling:
            from app.avatar.planner.runners.tool_runner import ToolRunner
            self.runner = ToolRunner(event_bus=self.event_bus)
        else:
            # DagRunner deleted - use GraphRuntime via GraphController
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

        if compiler:
            self.compiler = compiler
        elif llm_client:
            self.compiler = IntentExtractor(llm_client)
        else:
            # Fallback if no LLM, but this shouldn't happen in normal flow
            self.compiler = None 
        
        # Initialize Hybrid Perception System
        self.perception = PerceptionManager()
        # Register Backends (UIA is first)
        self.perception.register_backend(UIABackend())
        # Register Web Backend (Playwright)
        self.perception.register_backend(PlaywrightPerceptionBackend())
        
        self.skill_guard = PolicySkillGuard()
        from app.core.config import AVATAR_LOGS_DIR
        self.learning_logger = FileLearningLogger(AVATAR_LOGS_DIR / "learning.log")

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

                    _ws_mgr = get_session_workspace_manager()
                    _workspace = _ws_mgr.get_or_create("default")
                    _artifact_backend = LocalStorageBackend(
                        base_path=str(AVATAR_ARTIFACTS_DIR)
                    )
                    _artifact_store = ArtifactStore(backend=_artifact_backend)
                    _artifact_collector = ArtifactCollector(artifact_store=_artifact_store)
                    _trace_store = StepTraceStore()
                    logger.info("[AvatarMain] Workspace + ArtifactCollector + StepTraceStore ready")
                except Exception as ws_err:
                    logger.warning(f"[AvatarMain] Workspace/Artifact/Trace init failed: {ws_err}")

                graph_executor = GraphExecutor(
                    base_path=self.base_path,
                    memory_manager=self.memory_manager,
                    workspace=_workspace,
                )
                node_runner = NodeRunner(
                    executor=graph_executor,
                    workspace=_workspace,
                    artifact_collector=_artifact_collector,
                    trace_store=_trace_store,
                )
                graph_runtime = GraphRuntime(
                    scheduler=scheduler,
                    node_runner=node_runner,
                    event_bus=self.event_bus,
                )
                graph_planner = GraphPlanner(llm_client=self.llm_client)
                self._graph_controller = GraphController(
                    planner=graph_planner,
                    runtime=graph_runtime,
                )
            except Exception as gc_err:
                logger.warning(f"[AvatarMain] GraphController init failed: {gc_err}")
                self._graph_controller = None
            # AgentLoop removed - _agent_loop kept as None for backward compat
            self._agent_loop = None
        else:
            self._graph_controller = None
            self._agent_loop = None

    def handle_request(self, user_request: str) -> Any:
        if not self._graph_controller:
            raise RuntimeError("GraphController not initialized (missing LLM/TaskPlanner)")
        env_context = self._build_env_context(user_request=user_request)
        # Delegate to GraphController for new architecture
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self._graph_controller.execute(user_request, mode="react")
        )

    def _create_or_load_context(self, task: Task, env: Dict[str, Any]) -> TaskContext:
        """
        Factory method to create or restore TaskContext.
        Injects Session Variables from MemoryManager.
        """
        ctx = TaskContext.from_task(task, env=env)
        if self.memory_manager:
            ctx.attach("memory_manager", self.memory_manager)
            
            # === SESSION INJECTION ===
            session_id = ctx.identity.session_id
            if not session_id and hasattr(task, "metadata"):
                session_id = task.metadata.get("session_id")
            
            if session_id:
                try:
                    session_data = self.memory_manager.get_session_context(session_id)
                    if session_data:
                        session_ctx = SessionContext.from_dict(session_data)
                        
                        # Inject ALL session variables into TaskContext variables
                        # This makes last_output available as $vars.last_output
                        for k, v in session_ctx.variables.items():
                            ctx.variables.set(k, v)
                        
                        logger.info(f"Injected session variables into task context: {list(session_ctx.variables.keys())}")
                except Exception as e:
                    logger.warning(f"Failed to inject session context: {e}")
            # =========================
            
        return ctx

    async def run_task(self, task: Task) -> Task:
        from platform import system as get_os
        # 动态获取当前工作目录
        current_workspace = self.base_path
        if self.workspace_manager:
            try:
                current_workspace = self.workspace_manager.get_workspace()
            except Exception as e:
                logger.warning(f"Failed to get workspace from manager, using default: {e}")
        
        env = {
            "os": get_os(),
            "base_path": str(current_workspace),
        }
        
        # Use centralized context creation (with Session Injection)
        task_ctx = self._create_or_load_context(task, env)
        
        if self.learning_manager:
            task_ctx.attach("learning_manager", self.learning_manager)
        
        # Update SkillCaller with new context
        caller = _SkillCaller(
            base_path=self.base_path,
            dry_run=self.dry_run,
            memory_manager=self.memory_manager,
            learning_manager=self.learning_manager,
            execution_context=task_ctx,
            workspace_manager=self.workspace_manager,
        )

        # Lifecycle management
        task_ctx.mark_running()
        try:
            result_task = await self.runner.run(task, ctx=caller, state=self.state, skill_guard=self.skill_guard, event_bus=self.event_bus)
            
            # Final status update based on runner result
            if result_task.status == TaskStatus.SUCCESS:
                task_ctx.mark_finished("SUCCESS")
            elif result_task.status == TaskStatus.PARTIAL_SUCCESS:
                task_ctx.mark_finished("PARTIAL_SUCCESS")
            else:
                task_ctx.mark_finished("FAILED")
                if hasattr(task_ctx.status, "error"):
                     # Try to find error from steps if not set
                     failed_steps = [s for s in result_task.steps if s.status.name == "FAILED"]
                     if failed_steps:
                         last_error = failed_steps[-1].result.error if failed_steps[-1].result else "Unknown error"
                         task_ctx.status.error = {"message": str(last_error)}
            
            return result_task
        except Exception as e:
            task_ctx.status.error = {"message": str(e), "traceback": traceback.format_exc()}
            task_ctx.mark_finished("FAILED")
            raise

    async def run_intent(self, intent: IntentSpec, task_mode: str = "one_shot", cancel_event = None, on_graph_created = None) -> RunRecord:
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
                if cancel_event:
                    env_context["cancel_event"] = cancel_event
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

                graph_result = await self._graph_controller.execute(
                    intent.goal, mode="react", env_context=env_context
                )

                if graph_result.final_status == "failed":
                    raise RuntimeError(graph_result.error_message or "GraphController execution failed")

                RunStore.update_status(run_record.id, "completed", summary=f"✅ 成功完成任务：{task_record.title}")
            elif self.task_planner is not None:
                pass  # no planner without controller
            else:
                raise RuntimeError("Cannot execute intent without an active GraphController/Planner.")

            if self.learning_logger:
                self.learning_logger.record(
                    user_request=intent.goal,
                    plan=final_task if 'final_task' in locals() else intent,
                    context={"run_id": run_record.id}
                )

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
        # 动态获取当前工作目录
        current_workspace = self.base_path
        if self.workspace_manager:
            try:
                current_workspace = self.workspace_manager.get_workspace()
            except Exception as e:
                logger.warning(f"Failed to get workspace from manager, using default: {e}")
        
        # 架构重构：移除 Runtime 层的技能搜索
        # 职责下放：让 Planner 自己搜索技能（符合"谁决策，谁搜索"原则）
        # 参考：LangChain, OpenAI Assistants, Semantic Kernel
        
        # 为 InteractiveLLMPlanner 提供 available_skills
        available_skills = {}
        for skill_cls in skill_registry.iter_skills():
            spec = skill_cls.spec
            skill_name = spec.name

            # 获取参数 schema
            params_schema = {}
            if spec.input_model:
                try:
                    input_schema = spec.input_model.model_json_schema()
                    params_schema = input_schema.get("properties", {})
                except Exception as e:
                    logger.debug(f"Failed to get params schema for {skill_name}: {e}")
            
            available_skills[skill_name] = {
                "description": spec.description,
                "params_schema": params_schema
            }
        
        return {
            "skill_registry": skill_registry,  # 提供注册表引用，而非预过滤的技能列表
            "available_skills": available_skills,  # 为 ReAct 模式提供 skill 列表
            "workspace_path": str(current_workspace),  # 为文件系统扫描提供路径
            "os": system(),
            "default_paths": {"workspace": str(current_workspace)},
        }

    _STEP_STATUS_MAP = {
        "SUCCESS": "completed",
        "FAILED": "failed",
        "SKIPPED": "skipped",
        "PENDING": "pending",
        "RUNNING": "running",
    }

    def _persist_steps(self, run_id: str, steps: list):
        """将 steps 持久化到 DB（通用方法，适用于普通任务和编排任务）"""
        for i, step in enumerate(steps):
            step_record = StepStore.create(
                run_id=run_id,
                step_index=i,
                step_name=step.skill_name,
                skill_name=step.skill_name,
                input_params=step.params,
            )
            db_status = self._STEP_STATUS_MAP.get(step.status.name, "pending")
            output = step.result.output if step.result else None
            error = step.result.error if step.result else None
            StepStore.update_status(
                step_record.id,
                status=db_status,
                output_result=self._serialize_result(output),
                error_message=error,
            )

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
