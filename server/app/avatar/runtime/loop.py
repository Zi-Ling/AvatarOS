# app/avatar/runtime/loop.py
from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING
import time
import uuid
import logging
import json
import traceback

from app.avatar.runtime.core import TaskContext, AgentLoopResult
from app.avatar.memory.provider import MemoryProvider
from app.avatar.memory.manager import MemoryManager
from app.avatar.perception.manager import PerceptionManager
from app.avatar.skills.guard import SkillGuard
from app.avatar.skills.registry import skill_registry
from app.avatar.learning.logger import LearningLogger
from app.avatar.learning.manager import LearningManager
from app.avatar.planner.base import TaskPlanner
from app.avatar.planner.runners.dag_runner import DagRunner
from app.avatar.planner.runners.artifact.artifact_syncer import ArtifactSyncer
from app.avatar.planner.models import Task, TaskStatus, StepStatus, Step
from app.avatar.planner.models.step import StepResult
from app.avatar.planner.orchestrator import OrchestrationService
from app.avatar.runtime.recovery.repair import CodeRepairManager
from app.avatar.intent.models import IntentSpec, IntentDomain
from app.avatar.infra.semantic import get_embedding_service
from app.avatar.planner.extractor import RetryablePlanningError
from app.core.config import config
from app.services.task_service import task_service

if TYPE_CHECKING:
    from app.avatar.runtime.events import EventBus

try:
    from app.avatar.runtime.events import EventBus, Event, EventType
except ImportError:
    EventBus = None

logger = logging.getLogger(__name__)


class AgentLoop:
    """
    V2 Agent Loop: 轻量级协调器
    
    负责路由到具体的执行器（单任务 vs 编排任务）
    """
    
    # 规则1: Task 中出现 fallback skill → Task 必为 FAILED
    FALLBACK_SKILLS = {"llm.fallback", "fallback", "llm.catch_all"}
    
    def __init__(
        self,
        planner: TaskPlanner,
        dag_runner: DagRunner,
        skill_context: Any,
        *,
        memory_provider: Optional[MemoryProvider] = None,
        memory_manager: Optional[MemoryManager] = None,
        learning_manager: Optional[LearningManager] = None,
        perception: Optional[PerceptionManager] = None,
        skill_guard: Optional[SkillGuard] = None,
        learning_logger: Optional[LearningLogger] = None,
        state_store: Optional[Any] = None,
        event_bus: Optional[EventBus] = None,
        llm_client: Optional[Any] = None,
        max_iterations: int = 5,
    ) -> None:
        self._planner = planner
        self._dag_runner = dag_runner
        self._skill_context = skill_context
        self._memory_provider = memory_provider
        self._memory_manager = memory_manager
        self._learning_manager = learning_manager
        self._perception = perception
        self._skill_guard = skill_guard
        self._learning_logger = learning_logger
        self._state_store = state_store
        self._event_bus = event_bus
        self._llm_client = llm_client
        self._max_iterations = max_iterations
        
        # 初始化修复和编排组件
        if llm_client:
            self._repair_manager = CodeRepairManager(llm_client, max_attempts=2)
            logger.info("[AgentLoop] CodeRepairManager initialized")
            
            # 初始化编排服务
            self._orchestration_service = OrchestrationService(
                llm_client=llm_client,
                embedding_service=get_embedding_service(),
                event_bus=event_bus,
                logger_instance=logger
            )
            logger.info("[AgentLoop] OrchestrationService initialized")
        else:
            self._repair_manager = None
            self._orchestration_service = None
            logger.warning("[AgentLoop] CodeRepairManager and OrchestrationService disabled (no LLM client)")
        
        # 初始化执行器
        from app.avatar.runtime.executor.composite_executor import CompositeTaskExecutor
        from app.avatar.runtime.recovery.repair import SelfCorrector
        from app.avatar.runtime.recovery.replanner import Replanner
        
        self._composite_executor = CompositeTaskExecutor(
            orchestration_service=self._orchestration_service,
            planner=planner,
            dag_runner=dag_runner,
            skill_context=skill_context,
            skill_guard=skill_guard,
            failure_policy=None,  # 使用默认策略
            memory_manager=memory_manager,
            learning_logger=learning_logger,
            event_bus=event_bus,
            llm_client=llm_client,  # 🎯 传递 llm_client，让 CompositeExecutor 创建 SimpleLLMPlanner
        ) if self._orchestration_service else None
        
        self._self_corrector = SelfCorrector(
            repair_manager=self._repair_manager,
            max_repair_attempts=2
        ) if self._repair_manager else None
        
        self._replanner = Replanner(
            planner=planner,
            max_replan_attempts=config.max_replan_attempts
        )

    async def _attempt_self_correction(self, step: Step, error_msg: str, task_goal: str = "", task_context: Any = None) -> bool:
        """委托给 SelfCorrector"""
        if not self._self_corrector:
            return False
        return await self._self_corrector.attempt_correction(step, error_msg, task_goal, task_context)

    async def run(self, user_request: str | IntentSpec, env_context: dict) -> AgentLoopResult:
        """
        主执行循环
        
        Args:
            user_request: IntentSpec（推荐）或 str（兼容旧版）
            env_context: 环境上下文
        """
        # Handle input type - 兼容旧版 str 输入
        if isinstance(user_request, str):
            logger.warning("[AgentLoop] Deprecated: pass IntentSpec instead of str")
            intent = self._create_fallback_intent(user_request)
            raw_request_text = user_request
        else:
            intent = user_request
            raw_request_text = intent.raw_user_input or intent.goal

        self._emit_event(EventType.SYSTEM_START, payload={"user_request": raw_request_text})
        
        # === 路由决策：是否需要任务编排（复用 Router 层的复杂度判断） ===
        is_complex = False
        if hasattr(intent, 'metadata') and intent.metadata:
            is_complex = intent.metadata.get('is_complex', False)
        
        if self._composite_executor and is_complex:
            logger.info(f"[AgentLoop] Request needs orchestration (Router flagged complex): '{raw_request_text[:50]}...'")
            return await self._composite_executor.execute(raw_request_text, intent, env_context)
        
        # IntentCompiler 逻辑已移除 - Router 负责意图理解
        logger.info(f"[AgentLoop] Executing task: goal='{intent.goal}', domain={intent.domain.value}, type='{intent.intent_type}'")

        start_time = time.time()
        
        # 2. Context & Memory Retrieval
        memory_query = intent.goal if intent else raw_request_text
        memory_text = self._memory_provider.get_relevant_memory(memory_query) if self._memory_provider else None
        
        # 3. Initial Planning (with replanner fallback)
        task = None
        initial_plan_attempts = 0
        max_initial_plan_attempts = 3  # 给 planner 3次机会（包括初始尝试）
        
        while initial_plan_attempts < max_initial_plan_attempts:
            initial_plan_attempts += 1
            
            try:
                logger.debug(f"[AgentLoop] Calling planner.make_task (attempt {initial_plan_attempts}/{max_initial_plan_attempts})")
                task = await self._planner.make_task(
                    intent,
                    env_context,
                    ctx=None,
                    memory=memory_text,
                )
                logger.debug(f"[AgentLoop] Planner returned task with {len(task.steps)} steps")
                break  # 成功，退出循环
                
            except RetryablePlanningError as e:
                # 可重试的规划失败（空 plan、校验失败等）
                logger.warning(f"[AgentLoop] RetryablePlanningError on attempt {initial_plan_attempts}: {e.reason}")
                
                if initial_plan_attempts >= max_initial_plan_attempts:
                    # 用尽所有尝试，创建 fallback task
                    logger.error(f"[AgentLoop] Initial planning failed after {max_initial_plan_attempts} attempts, creating fallback task")
                    task = self._create_fallback_task(intent, e.reason, env_context)
                    break
                
                # 继续下一次尝试
                logger.info(f"[AgentLoop] Retrying planning (attempt {initial_plan_attempts + 1}/{max_initial_plan_attempts})...")
                continue
                
            except Exception as e:
                # 其他不可重试的异常
                logger.error(f"[AgentLoop] Planner failed with non-retryable error: {e}")
                logger.error(traceback.format_exc())
                
                from app.avatar.runtime.core import ErrorClassifier
                error_info = ErrorClassifier.classify(str(e), type(e).__name__)
                formatted_error = ErrorClassifier.format_for_frontend(error_info)
                
                self._emit_event(EventType.SYSTEM_ERROR, payload={
                    "error": formatted_error["message"],
                    "error_details": formatted_error
                })
                return AgentLoopResult(False, None, None, error=formatted_error["message"])
        
        if not task:
            # 理论上不应该到这里
            logger.error("[AgentLoop] No task created after planning attempts")
            return AgentLoopResult(False, None, None, error="Planning failed")

        task.metadata["user_request"] = raw_request_text
        
        # ReAct 模式：只在有步骤时才发送 PLAN_GENERATED 事件
        if task.steps:
            safe_plan = _sanitize_task_for_event(task)
            self._emit_event(EventType.PLAN_GENERATED, payload={"plan": safe_plan, "goal": task.goal, "step_count": len(task.steps)})
        else:
            logger.info("[AgentLoop] ReAct mode: No initial plan, will generate steps dynamically")

        # --- Task History: Persist Initial Plan ---
        try:
            db_task_id = getattr(intent, "id", None) or task.id
            task.metadata["intent_id"] = db_task_id 
            task_service.create_task_from_runtime(task)
        except Exception as db_err:
            if "UNIQUE constraint" in str(db_err):
                logger.warning(f"Task History Collision: {db_err}. Skipping history persistence for this run.")
            else:
                logger.error(f"Failed to persist task history: {db_err}")
        
        # 4. Execution Loop
        context = TaskContext.from_task(task, env=env_context)
        if self._memory_manager:
            context.attach("memory_manager", self._memory_manager)
        
        if hasattr(self._skill_context, "execution_context"):
            self._skill_context.execution_context = context
        
        task.status = TaskStatus.RUNNING
        context.mark_running()
        
        iteration = 0
        consecutive_failures = 0  # 连续失败计数器
        max_consecutive_failures = 3  # 连续失败 3 次就放弃
        max_total_iterations = 50 
        
        # 获取取消事件
        cancel_event = env_context.get("cancel_event")
        
        # 检测是否为 ReAct 模式（初始步骤为空）
        is_react_mode = len(task.steps) == 0
        
        while iteration < max_total_iterations:
            iteration += 1
            
            # Cancel Check
            if cancel_event and cancel_event.is_set():
                logger.warning(f"[AgentLoop] Task cancelled by user at iteration {iteration}")
                task.status = TaskStatus.FAILED
                context.mark_finished("FAILED")
                # 标记所有 pending 步骤为 SKIPPED
                for s in task.steps:
                    if s.status == StepStatus.PENDING:
                        s.status = StepStatus.SKIPPED
                        s.result = StepResult(success=False, error="Task cancelled by user")
                        try:
                            task_service.update_step_status(s.id, "skipped", error="Task cancelled by user")
                        except Exception:
                            pass
                break
            
            # Perception Phase
            if self._perception:
                try:
                    screen_model = await self._perception.perceive()
                    env_context["screen_model"] = screen_model
                except Exception as e:
                    logger.warning(f"Perception failed: {e}")
            
            # === ReAct 模式：动态生成下一步 ===
            if is_react_mode:
                try:
                    logger.info(f"[AgentLoop] Generating next step (iteration {iteration})...")
                    next_step = await self._planner.next_step(task, env_context)
                    
                    if next_step is None:
                        # 任务完成
                        logger.info("[AgentLoop] Planner returned None, task finished")
                        task.status = TaskStatus.SUCCESS
                        context.mark_finished("SUCCESS")
                        break
                    
                    # 添加新步骤到任务
                    task.steps.append(next_step)
                    logger.info(f"[AgentLoop] Generated step: {next_step.skill_name} - {next_step.description[:50]}...")
                    
                    # 持久化新步骤
                    try:
                        db_task_id = task.metadata.get("intent_id") or task.id
                        task_service.add_step_to_task(db_task_id, next_step)
                    except Exception as db_err:
                        logger.warning(f"Failed to persist new step: {db_err}")
                    
                    step_to_run = next_step
                    step_index = len(task.steps) - 1
                    
                except Exception as e:
                    logger.error(f"[AgentLoop] Failed to generate next step: {e}")
                    logger.error(traceback.format_exc())
                    task.status = TaskStatus.FAILED
                    context.mark_finished("FAILED")
                    break
            
            # === 传统模式：从 pending 步骤中选择 ===
            else:
                # Identify next pending steps
                pending_steps = [s for s in task.steps if s.status == StepStatus.PENDING]
                
                if not pending_steps:
                    # All done?
                    if any(s.status == StepStatus.FAILED for s in task.steps):
                        task.status = TaskStatus.FAILED
                        context.mark_finished("FAILED")
                    else:
                        task.status = TaskStatus.SUCCESS
                        context.mark_finished("SUCCESS")
                    break

                step_to_run = pending_steps[0]
                
                # Find index for DagRunner
                step_index = task.steps.index(step_to_run)
                
                # Check dependencies
                can_run = True
                for dep_id in step_to_run.depends_on:
                    dep = next((s for s in task.steps if s.id == dep_id), None)
                    if not dep or dep.status != StepStatus.SUCCESS:
                        can_run = False
                        break
                
                if not can_run:
                    dep_failed = any(
                        next((s for s in task.steps if s.id == dep_id), None).status == StepStatus.FAILED
                        for dep_id in step_to_run.depends_on
                        if next((s for s in task.steps if s.id == dep_id), None) is not None
                    )
                    if dep_failed:
                        # 依赖步骤已失败 → 标记当前步骤为 FAILED，让 replan 逻辑处理
                        step_to_run.status = StepStatus.FAILED
                        step_to_run.result = StepResult(
                            success=False,
                            error=f"Dependency failed: {[d for d in step_to_run.depends_on]}"
                        )
                    else:
                        break 

            try:
                task_service.update_step_status(step_to_run.id, "running")
                
                # Execute step via DagRunner
                await self._dag_runner._execute_step(
                    step_to_run,
                    task,
                    self._skill_context,
                    self._skill_guard,
                    step_index=step_index
                )
                
                # Task History: Mark result
                status_str = step_to_run.status.name
                result_dict = None
                if step_to_run.result:
                    from dataclasses import asdict
                    result_dict = asdict(step_to_run.result)
                error_str = step_to_run.result.error if step_to_run.result else None
                
                task_service.update_step_status(step_to_run.id, status_str, result=result_dict, error=error_str)
                
                # Audit logging: 记录步骤执行
                try:
                    from app.services.audit_service import get_audit_service
                    audit_service = get_audit_service()
                    audit_service.log(
                        skill_name=step_to_run.skill_name,
                        operation=step_to_run.skill_name,
                        result="success" if step_to_run.status == StepStatus.SUCCESS else "failed",
                        task_id=task.id,
                        details={
                            "step_id": step_to_run.id,
                            "params": step_to_run.params,
                            "error": error_str
                        }
                    )
                except Exception as audit_err:
                    logger.warning(f"Failed to log audit: {audit_err}")
                
                if self._state_store:
                    self._state_store.save_task(task)
                
                self._emit_event(EventType.TASK_UPDATED, payload={"task": _sanitize_task_for_event(task)})

            except Exception as e:
                logger.error(f"Loop: Exception executing step {step_to_run.id}: {e}")
                logger.error(traceback.format_exc())
                step_to_run.status = StepStatus.FAILED
                step_to_run.result = StepResult(success=False, error=str(e))

            # Memory & Learning Hooks
            if self._memory_manager and step_to_run.status in (StepStatus.SUCCESS, StepStatus.FAILED):
                try:
                    event_type = "success" if step_to_run.status == StepStatus.SUCCESS else "error"
                    detail = ""
                    if step_to_run.result:
                        raw_detail = step_to_run.result.output or step_to_run.result.error or ""
                        if isinstance(raw_detail, str):
                            detail = raw_detail
                        elif raw_detail is None:
                            detail = ""
                        else:
                            try:
                                detail = json.dumps(raw_detail, ensure_ascii=False)
                            except:
                                detail = str(raw_detail)
                    
                    self._memory_manager.remember_skill_event(
                        skill_name=step_to_run.skill_name,
                        event_type=event_type,
                        status=step_to_run.status.name,
                        detail=detail[:200],
                        extra={
                            "task_id": task.id,
                            "step_id": step_to_run.id,
                            "params": step_to_run.params
                        }
                    )
                    
                    if self._learning_manager:
                        self._learning_manager.on_skill_event(
                            skill_name=step_to_run.skill_name,
                            user_id=None,
                            task_id=task.id,
                            event_type=event_type,
                            status=step_to_run.status.name,
                            detail=detail[:200],
                            extra={"params": step_to_run.params}
                        )
                except Exception as skill_mem_err:
                    logger.error(f"Failed to record skill event to memory: {skill_mem_err}")
            
            # Self-Correction Phase
            if step_to_run.status == StepStatus.FAILED and step_to_run.skill_name == "python.run":
                repair_count = getattr(step_to_run, "_repair_count", 0)
                
                if repair_count < 2:
                    logger.info(f"Step {step_to_run.id} failed. Triggering Self-Correction (attempt {repair_count + 1}/2)...")
                    error_msg = step_to_run.result.error if step_to_run.result else "Unknown error"
                    task_goal = task.goal if hasattr(task, 'goal') else "Unknown task"
                    
                    fixed = await self._attempt_self_correction(step_to_run, error_msg, task_goal, context)
                    
                    if fixed:
                        step_to_run.status = StepStatus.PENDING
                        step_to_run.result = None 
                        setattr(step_to_run, "_repair_count", repair_count + 1)
                        self._emit_event(EventType.TASK_UPDATED, payload={"task": _sanitize_task_for_event(task)})
                        continue

            # === ReAct 模式：简化失败处理 ===
            if is_react_mode:
                if step_to_run.status == StepStatus.FAILED:
                    consecutive_failures += 1
                    logger.warning(f"[AgentLoop] Step failed (consecutive failures: {consecutive_failures}/{max_consecutive_failures})")
                    
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error(f"[AgentLoop] Max consecutive failures reached, giving up")
                        task.status = TaskStatus.FAILED
                        context.mark_finished("FAILED")
                        break
                    
                    # 继续循环，让 next_step() 看到失败的 Observation 并生成修复步骤
                    continue
                else:
                    # 成功，重置连续失败计数器
                    consecutive_failures = 0
                    continue
            
            # === 传统模式：Re-Planning Phase ===
            if step_to_run.status == StepStatus.FAILED:
                if replan_count >= max_replan_attempts:
                    logger.warning(f"Step {step_to_run.id} failed. Max replan attempts ({max_replan_attempts}) reached. Giving up.")
                    task.status = TaskStatus.FAILED
                    context.mark_finished("FAILED")
                    break
                
                replan_count += 1
                logger.info(f"Step {step_to_run.id} failed. Triggering Re-plan (attempt {replan_count}/{max_replan_attempts})...")
                
                # 使用 Replanner
                replanned = await self._replanner.replan(task, step_to_run, env_context)
                
                if replanned:
                    safe_plan = _sanitize_task_for_event(task)
                    error_msg = step_to_run.result.error if step_to_run.result else "Unknown error"
                    self._emit_event(EventType.PLAN_UPDATED, payload={
                        "plan": safe_plan, 
                        "reason": "replan_after_error",
                        "replan_count": replan_count,
                        "failed_step": step_to_run.id,
                        "error": error_msg
                    })
                    
                    # Task History: 持久化 replan 产生的新步骤
                    try:
                        task_service.persist_replan_steps(db_task_id, task.steps)
                    except Exception as db_err:
                        logger.warning(f"Failed to persist replan steps: {db_err}")
                    
                    logger.info(f"Re-planning successful. New plan has {len(task.steps)} steps.")
                    continue
                else:
                    logger.error("Re-planning failed")
                    task.status = TaskStatus.FAILED
                    context.mark_finished("FAILED")
                    break

        # Loop finished - Strict State Validation
        has_pending = any(s.status == StepStatus.PENDING for s in task.steps)
        has_failed = any(s.status == StepStatus.FAILED for s in task.steps)
        all_success = all(s.status in (StepStatus.SUCCESS, StepStatus.SKIPPED) for s in task.steps)
        
        # 规则1: 检查是否包含 fallback skill（优先级最高）
        has_fallback = any(s.skill_name in self.FALLBACK_SKILLS for s in task.steps)
        
        if has_fallback:
            # 规则1: Task 中出现 fallback skill → Task 必为 FAILED
            task.status = TaskStatus.FAILED
            if context.status.state != "FAILED": context.mark_finished("FAILED")
            logger.warning(f"Loop: ⚠️ Task marked FAILED due to fallback skill usage (planner/execution failure)")
        elif has_failed:
            task.status = TaskStatus.FAILED
            if context.status.state != "FAILED": context.mark_finished("FAILED")
        elif has_pending:
            task.status = TaskStatus.FAILED 
            if context.status.state != "FAILED": context.mark_finished("FAILED")
            logger.warning(f"Loop: Task marked FAILED due to pending steps (Timeout/Loop Limit).")
        elif all_success and task.steps:
            task.status = TaskStatus.SUCCESS
            if context.status.state != "SUCCESS": context.mark_finished("SUCCESS")
        else:
            if not task.steps:
                task.status = TaskStatus.FAILED
                context.mark_finished("FAILED")
            else:
                task.status = TaskStatus.FAILED
                context.mark_finished("FAILED")

        # 5. Final Event & Learning
        # --- Sync Artifacts to SessionContext (cross-task persistence) ---
        if task.status == TaskStatus.SUCCESS and context.artifacts.items:
            try:
                await ArtifactSyncer.sync_and_index(context, None)
                logger.info(f"[AgentLoop] Synced {len(context.artifacts.items)} artifacts to SessionContext")
            except Exception as sync_err:
                logger.warning(f"[AgentLoop] Artifact sync failed: {sync_err}")
        
        final_payload = {
            "task": _sanitize_task_for_event(task),
            "status": task.status.name
        }
        
        try:
            db_task_id = task.metadata.get("intent_id") or task.id
            error_msg = None
            if task.status == TaskStatus.FAILED:
                # 检查是否因为 fallback
                if has_fallback:
                    fallback_steps = [s for s in task.steps if s.skill_name in self.FALLBACK_SKILLS]
                    error_msg = f"Task used fallback skill (planner/execution failure): {', '.join(s.id for s in fallback_steps)}"
                else:
                    failed_steps = [s for s in task.steps if s.status == StepStatus.FAILED]
                    if failed_steps:
                        error_msg = f"Steps failed: {', '.join(s.id for s in failed_steps)}"
            
            task_service.complete_run(db_task_id, task.status.name, error=error_msg)
        except Exception as db_err:
            logger.error(f"Failed to update task history completion: {db_err}")
        
        if task.status == TaskStatus.SUCCESS:
            self._emit_event(EventType.TASK_COMPLETED, payload=final_payload)
        else:
            self._emit_event(EventType.SYSTEM_ERROR, payload={"error": f"Task execution failed (Status: {task.status.name})", "task": final_payload["task"]})

        if self._learning_logger:
            log_request = intent.goal if intent else (user_request if isinstance(user_request, str) else str(user_request))
            # 传统模式才有 replan_count
            replan_count = 0 if is_react_mode else locals().get('replan_count', 0)
            self._learning_logger.record(
                user_request=log_request,
                plan=task,
                context={
                    "iterations": iteration, 
                    "final_status": task.status.name,
                    "replan_count": replan_count,
                    "self_corrected": replan_count > 0,
                    "mode": "react" if is_react_mode else "traditional"
                }
            )
        
        if self._memory_manager:
            try:
                execution_time = time.time() - start_time if 'start_time' in locals() else 0
                task_summary = f"Goal: {task.goal}"
                if task.status == TaskStatus.SUCCESS:
                    task_summary += f" | Completed {len(task.steps)} steps successfully"
                else:
                    failed_steps = [s for s in task.steps if s.status == StepStatus.FAILED]
                    task_summary += f" | Failed at {len(failed_steps)} step(s)"
                
                # 传统模式才有 replan_count
                replan_count = 0 if is_react_mode else locals().get('replan_count', 0)
                
                self._memory_manager.remember_task_run(
                    task_id=task.id,
                    status=task.status.name,
                    summary=task_summary,
                    extra={
                        "goal": task.goal,
                        "intent_type": intent.intent_type if intent else "unknown",
                        "domain": intent.domain.value if intent else "other",
                        "steps": [{"skill": s.skill_name, "status": s.status.name} for s in task.steps],
                        "step_count": len(task.steps),
                        "replan_count": replan_count,
                        "execution_time": execution_time,
                        "user_request": raw_request_text,
                        "mode": "react" if is_react_mode else "traditional"
                    }
                )
                logger.info(f"✅ Task memory recorded: {task.id}")
            except Exception as mem_err:
                logger.error(f"Failed to record task memory: {mem_err}")
        
        if self._learning_manager:
            try:
                # 传统模式才有 replan_count
                replan_count = 0 if is_react_mode else locals().get('replan_count', 0)
                
                self._learning_manager.on_task_finished(
                    task_id=task.id,
                    user_id=None,
                    status=task.status.name,
                    summary=task_summary if 'task_summary' in locals() else task.goal,
                    extra={
                        "steps": [s.skill_name for s in task.steps],
                        "replan_count": replan_count,
                        "success": task.status == TaskStatus.SUCCESS,
                        "mode": "react" if is_react_mode else "traditional"
                    }
                )
            except Exception as learn_err:
                logger.error(f"Failed to trigger learning hook: {learn_err}")

        return AgentLoopResult(
            success=task.status == TaskStatus.SUCCESS,
            context=context,
            plan=task,
            error=None,
            iterations=iteration
        )

    def _create_fallback_intent(self, text: str) -> IntentSpec:
        """创建降级意图"""
        return IntentSpec(
            id=str(uuid.uuid4()),
            goal=text,
            intent_type="unknown",
            domain=IntentDomain.OTHER,
            raw_user_input=text
        )
    
    def _create_fallback_task(self, intent: IntentSpec, reason: str, env_context: dict) -> Task:
        """
        创建 fallback task（只有在 replanner 用尽所有尝试后才调用）
        
        Args:
            intent: 用户意图
            reason: 失败原因
            env_context: 环境上下文
        
        Returns:
            包含单个 fallback 步骤的 Task
        """
        logger.warning(f"[AgentLoop] Creating fallback task due to: {reason}")
        
        # 创建 fallback 步骤
        fallback_step = Step(
            id=f"fallback_step_{uuid.uuid4().hex[:8]}",
            skill_name="llm.fallback",
            params={
                "user_message": intent.goal,
                "intent": intent.intent_type,
                "reason": reason  # 内部失败原因
            },
            order=0,
            max_retry=0,
            depends_on=[],
            description="System fallback - generate helpful response"
        )
        
        # 生成 task ID
        task_id = f"task_fallback_{uuid.uuid4().hex[:8]}"
        
        # 创建 Task（修复：提供必需的 id 和 intent_id 参数）
        task = Task(
            id=task_id,
            goal=intent.goal,
            steps=[fallback_step],
            intent_id=intent.id,
            metadata={
                "intent_type": intent.intent_type,
                "is_fallback": True,  # 标记为 fallback task
                "fallback_reason": reason
            }
        )
        
        return task

    def _emit_event(self, type: EventType, payload: dict = None, step_id: str = None):
        """发布事件"""
        if self._event_bus:
            payload = payload or {}
            # Removed verbose debug log - too noisy
            # logger.debug(f"[AgentLoop] Emitting event: {type.value}")
            try:
                event = Event(type=type, source="agent_loop", payload=payload, step_id=step_id)
                self._event_bus.publish(event)
            except Exception as e:
                logger.error(f"[AgentLoop] Failed to publish event {type.value}: {e}")


def _sanitize_task_for_event(task_obj: Task) -> dict:
    """清理任务对象以便序列化"""
    task_dict = task_obj.to_dict()
    for step in task_dict.get("steps", []):
        if "result" in step and step["result"]:
            out = step["result"].get("output")
            if out is not None:
                out_str = str(out)
                if len(out_str) > 1000:
                    step["result"]["output"] = out_str[:1000] + "... (truncated)"
        if "params" in step:
            for k, v in step["params"].items():
                v_str = str(v)
                if len(v_str) > 1000:
                    step["params"][k] = v_str[:1000] + "... (truncated)"
    return task_dict

