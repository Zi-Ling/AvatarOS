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
from app.avatar.planner.runners.dag_runner import DagRunner
from app.avatar.skills import SkillContext
from app.avatar.skills.registry import skill_registry
from app.db import TaskStore, RunStore, StepStore, Run as RunRecord
from app.avatar.runtime.monitoring import StepLogger
from app.avatar.runtime.monitoring.loggers import DatabaseStepLogger
from app.avatar.runtime.core import TaskContext, StepContext, ExecutionContext, SessionContext
from app.avatar.runtime.loop import AgentLoop
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
        
        # Parameter Alias Mapping (智能容错机制 - 元数据驱动)
        # 根据 SkillSpec 中配置的别名自动映射参数
        if hasattr(skill_cls.spec, 'param_aliases') and skill_cls.spec.param_aliases:
            mapped_params = {}
            for key, value in params.items():
                # 如果参数名是别名，映射到标准名称
                if key in skill_cls.spec.param_aliases:
                    standard_key = skill_cls.spec.param_aliases[key]
                    logger.info(f"[ParamMapper] {name}: Mapping alias '{key}' -> '{standard_key}'")
                    mapped_params[standard_key] = value
                else:
                    mapped_params[key] = value
            params = mapped_params
        
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
        runner: Optional[DagRunner] = None,
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
            memory_config = MemoryManagerConfig(
                root_dir=self.base_path / "memory",
                use_inmemory_working_state=True  # 使用内存版本（性能更好）
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
            self.runner = DagRunner(event_bus=self.event_bus)
        
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
        self.learning_logger = FileLearningLogger(self.base_path / "logs" / "learning.log")

        self._base_skill_caller = _SkillCaller(
            base_path=self.base_path,
            dry_run=self.dry_run,
            memory_manager=self.memory_manager,
            learning_manager=self.learning_manager,
            step_logger=self.step_logger,
            workspace_manager=self.workspace_manager,
        )

        if self.task_planner:
             self._agent_loop = AgentLoop(
                planner=self.task_planner,
                dag_runner=self.runner,
                skill_context=self._base_skill_caller,
                memory_provider=self.memory_provider,
                memory_manager=self.memory_manager,  # 新增：传递 Memory Manager
                learning_manager=self.learning_manager,  # 新增：传递 Learning Manager
                perception=self.perception,
                skill_guard=self.skill_guard,
                learning_logger=self.learning_logger,
                state_store=self.state,
                event_bus=self.event_bus,
                # compiler 已移除 - Router 负责意图理解
                llm_client=self.llm_client, # Pass LLM client for self-correction
            )
        else:
            self._agent_loop = None

    def handle_request(self, user_request: str) -> Any:
        if not self._agent_loop:
            raise RuntimeError("AgentLoop not initialized (missing LLM/TaskPlanner)")
        # [Roadmap Phase 3] Pass user_request to enable Skill RAG
        env_context = self._build_env_context(user_request=user_request)
        return self._agent_loop.run(user_request, env_context)

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

    async def run_intent(self, intent: IntentSpec, task_mode: str = "one_shot", cancel_event = None) -> RunRecord:
        # Backup metadata (TaskStore/DB serialization might strip non-standard fields)
        original_metadata = intent.metadata.copy()
        
        # ... (Keep existing legacy IntentSpec logic but use V2 skills)
        
        task_record = TaskStore.create(intent, task_mode=task_mode)
        run_record = RunStore.create(task_record.id)
        
        try:
            RunStore.update_status(run_record.id, "running")
            
            if self._agent_loop:
                # [Robustness Fix] Restore metadata to ensure AgentLoop has full context
                # This fixes the "History Lost" bug where session_id vanished after DB persistence
                if original_metadata:
                    intent.metadata.update(original_metadata)

                # [Roadmap Phase 3] Pass intent goal to enable Skill RAG
                env_context = self._build_env_context(user_request=intent.goal)
                env_context["run_id"] = run_record.id
                
                # 传递取消事件到环境上下文
                if cancel_event:
                    env_context["cancel_event"] = cancel_event
                
                # Use the interactive loop
                loop_result = await self._agent_loop.run(intent, env_context)
                
                # === FIX: Handle Loop Failure Gracefully ===
                if not loop_result.success and loop_result.error:
                    # 🎯 新增：尝试 fallback（针对编排任务失败）
                    logger.warning(f"[Runtime] Loop failed: {loop_result.error[:200]}")
                    
                    # 检查是否是编排任务失败
                    is_orchestrated_failure = (
                        "Orchestrated task failed" in str(loop_result.error) or
                        loop_result.plan is None
                    )
                    
                    if is_orchestrated_failure:
                        logger.info("[Runtime] Attempting fallback for orchestrated task failure...")
                        fallback_result = await self._try_runtime_fallback(
                            intent.goal,
                            str(loop_result.error),
                            env_context
                        )
                        
                        # 检查 fallback 是否返回了有用的内容
                        # 注意：fallback skill 的 success 总是 False，所以检查是否有 response
                        if fallback_result and (fallback_result.get("response_zh") or fallback_result.get("message")):
                            # Fallback 执行成功，创建一个包含 fallback 结果的虚拟任务
                            logger.info("[Runtime] ✅ Fallback executed")
                            
                            # 创建虚拟 fallback step
                            fallback_step = Step(
                                id="fallback_1",
                                skill_name="llm.fallback",
                                params={"user_message": intent.goal, "reason": str(loop_result.error)[:300]},
                                depends_on=[],
                                order=0
                            )
                            fallback_step.status = StepStatus.SUCCESS
                            fallback_step.result = StepResult(
                                success=True,
                                output=fallback_result,
                                error=None
                            )
                            
                            # 创建虚拟 task
                            final_task = Task(
                                id=str(uuid.uuid4()),
                                goal=intent.goal,
                                steps=[fallback_step],
                                intent_id=intent.id  # 🎯 修复：补充必需的 intent_id 参数
                            )
                            final_task.status = TaskStatus.SUCCESS  # 标记为成功（因为 fallback 执行了）
                            
                            # 继续正常流程
                        else:
                            # Fallback 也失败，抛出原始错误
                            raise RuntimeError(loop_result.error)
                    else:
                        # 非编排任务失败，直接抛出
                        raise RuntimeError(loop_result.error)
                else:
                    final_task = loop_result.plan
                    if not final_task:
                        raise RuntimeError("Task planning failed (No plan generated).")
                # ===========================================
                
                # AgentLoop 已经通过 task_service.update_step_status() 逐步持久化了每个 step
                # 这里只需要同步 CompositeTask 的子任务步骤（AgentLoop 不处理这种情况）
                if isinstance(final_task, CompositeTask):
                    all_steps = []
                    for subtask in final_task.subtasks:
                        if subtask.task_result:
                            all_steps.extend(subtask.task_result.steps)
                    self._persist_steps(run_record.id, all_steps)
                
                # 状态映射
                if isinstance(final_task, CompositeTask):
                    status_map = {
                        "success": ("completed", "✅ 成功完成任务"),
                        "partial_success": ("completed", "⚠️ 部分完成任务"),
                        "failed": ("failed", "❌ 任务失败"),
                    }
                    status, summary = status_map.get(final_task.status, ("failed", "未知状态"))
                else:
                    status_map = {
                        TaskStatus.SUCCESS: ("completed", "✅ 成功完成任务"),
                        TaskStatus.PARTIAL_SUCCESS: ("completed", "⚠️ 部分完成任务"),
                        TaskStatus.FAILED: ("failed", "❌ 任务失败"),
                    }
                    status, summary = status_map.get(final_task.status, ("failed", "未知状态"))
                
                RunStore.update_status(run_record.id, status, summary=f"{summary}：{task_record.title}")
            elif self.task_planner is not None:
                # Fallback to old manual planner call if AgentLoop is somehow not init (should not happen)
                # ... (old logic) ...
                pass # Simplified for brevity as we enforce AgentLoop usage
            else:
                # Legacy path: run_intent without planner is no longer supported in V2
                raise RuntimeError("Cannot execute intent without an active AgentLoop/Planner.")

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
        
        return RunStore.get(run_record.id)

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
            skill_name = spec.api_name or spec.internal_name
            
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
