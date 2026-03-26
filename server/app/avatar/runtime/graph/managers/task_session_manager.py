# server/app/avatar/runtime/graph/managers/task_session_manager.py
"""
TaskSessionManager — 长任务生命周期的顶层编排者

协调 InterruptManager、ResumeManager、PlanMergeEngine、
CheckpointManager、DeliveryGate 等组件，管理 TaskSession 生命周期。
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from app.db.long_task_models import TaskSession

logger = logging.getLogger(__name__)

# Type alias for the resume executor callback:
# (task_session_id, env_context_patch) → None
ResumeExecutorFn = Callable[[str, Dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class GateResumeConfig:
    """Tunable parameters for gate-resume continuation."""

    # Priority class used when re-enqueuing after gate resolution
    resume_priority_class: str = "resume"
    # Task type for re-enqueue
    resume_task_type: str = "long_task"
    # Key in session config_json where merged gate answers are persisted
    gate_answers_config_key: str = "gate_answers"
    # Key in env_context where gate answers are injected on resume
    gate_answers_env_key: str = "gate_answers"
    # Max chars of serialised gate answers to persist (prevents DB bloat)
    gate_answers_max_chars: int = 50_000
    # Answer validation
    max_answer_keys: int = 50           # max number of answer fields
    max_answer_value_chars: int = 5000  # max chars per answer value
    # Forbidden patterns in answer values (basic injection prevention)
    forbidden_patterns: tuple = (
        "<script", "javascript:", "data:text/html",
        "__import__", "eval(", "exec(",
    )


class TaskSessionManager:
    """长任务生命周期管理器。"""

    def __init__(
        self,
        task_session_store,
        task_scheduler,
        interrupt_manager,
        resume_manager,
        plan_merge_engine,
        checkpoint_manager,
        delivery_gate,
        gate_resume_config: Optional[GateResumeConfig] = None,
    ):
        self._task_session_store = task_session_store
        self._task_scheduler = task_scheduler
        self._interrupt_manager = interrupt_manager
        self._resume_manager = resume_manager
        self._plan_merge_engine = plan_merge_engine
        self._checkpoint_manager = checkpoint_manager
        self._delivery_gate = delivery_gate
        self._gate_resume_config = gate_resume_config or GateResumeConfig()
        # Callback set via set_resume_executor(); decouples from AvatarMain
        self._resume_executor: Optional[ResumeExecutorFn] = None

    # ------------------------------------------------------------------
    # Resume executor registration (called by API / bootstrap layer)
    # ------------------------------------------------------------------

    def set_resume_executor(self, executor: ResumeExecutorFn) -> None:
        """Register the callback that re-enters the execution loop after gate resolution.

        Typically wraps AvatarMain.run_intent or an equivalent entry point.
        Signature: async (task_session_id, env_context_patch) -> None
        """
        self._resume_executor = executor

    async def create_task_session(
        self, goal: str, config: Optional[dict] = None
    ) -> TaskSession:
        """创建新的长任务会话。"""
        config_json = json.dumps(config, ensure_ascii=False) if config else None
        session = self._task_session_store.create(
            goal=goal, config_json=config_json
        )
        logger.info(
            f"[TaskSessionManager] Created task session {session.id}: {goal}"
        )
        return session

    async def start_execution(self, task_session_id: str) -> dict:
        """
        启动执行：transition to planning → executing，入队调度。

        Returns execution context dict.
        """
        session = self._task_session_store.get(task_session_id)
        if session is None:
            raise ValueError(f"TaskSession {task_session_id} not found")

        # Transition: created → planning → executing
        if session.status == "created":
            self._task_session_store.transition(task_session_id, "planning")
            self._task_session_store.transition(task_session_id, "executing")
        elif session.status == "resuming":
            self._task_session_store.transition(task_session_id, "executing")
        else:
            self._task_session_store.transition(task_session_id, "executing")

        # Enqueue for scheduling
        await self._task_scheduler.enqueue(
            task_session_id=task_session_id,
            task_type="long_task",
            priority_class="user_explicit",
        )

        logger.info(
            f"[TaskSessionManager] Started execution for {task_session_id}"
        )
        return {
            "task_session_id": task_session_id,
            "status": "executing",
        }

    async def handle_pause(self, task_session_id: str) -> None:
        """处理暂停请求，委托给 InterruptManager。"""
        logger.info(f"[TaskSessionManager] Handling pause for {task_session_id}")
        await self._interrupt_manager.graceful_pause(task_session_id)

    async def handle_resume(self, task_session_id: str) -> None:
        """处理恢复请求，委托给 ResumeManager。"""
        logger.info(f"[TaskSessionManager] Handling resume for {task_session_id}")

        session = self._task_session_store.get(task_session_id)
        if session is None:
            raise ValueError(f"TaskSession {task_session_id} not found")

        # Transition to resuming
        self._task_session_store.transition(task_session_id, "resuming")

        try:
            resume_report = await self._resume_manager.resume(task_session_id)
            # Transition resuming → executing
            self._task_session_store.transition(task_session_id, "executing")
            logger.info(
                f"[TaskSessionManager] Resume completed for {task_session_id}, "
                f"runnable_set={resume_report.get('runnable_set', [])}"
            )
        except RuntimeError as e:
            # All checkpoints invalid → transition to failed
            logger.error(
                f"[TaskSessionManager] Resume failed for {task_session_id}: {e}"
            )
            self._task_session_store.transition(task_session_id, "failed")
            raise

    async def handle_change_request(
        self, task_session_id: str, change: str
    ) -> dict:
        """处理变更请求，委托给 PlanMergeEngine。"""
        logger.info(
            f"[TaskSessionManager] Handling change request for {task_session_id}"
        )

        # Parse the change request
        parsed = await self._plan_merge_engine.parse_change_request(change)

        # Attempt merge
        result = await self._plan_merge_engine.merge(task_session_id, parsed)

        logger.info(
            f"[TaskSessionManager] Change request result for {task_session_id}: "
            f"status={result.get('status')}"
        )
        return result

    async def handle_cancel(self, task_session_id: str) -> None:
        """取消任务。"""
        logger.info(f"[TaskSessionManager] Cancelling {task_session_id}")
        self._task_session_store.transition(task_session_id, "cancelled")
        await self._task_scheduler.release_slot(task_session_id)

    async def handle_gate_response(
        self,
        task_session_id: str,
        gate_id: str,
        version: int,
        answers: dict,
        approved: Optional[bool] = None,
    ) -> dict:
        """Handle user response to an active gate.

        Flow:
        1. Submit response to GateRuntime (idempotent, version-checked)
        2. Load session context, merge answers into TaskDefinition / env_context
        3. Persist merged answers to session config_json for crash recovery
        4. If still blocked → bump gate version, stay in WAITING_INPUT
        5. If ready → transition to executing, re-enqueue, fire resume executor
        """
        from app.avatar.runtime.task.gate_runtime import (
            GateRuntime, GateResponse,
        )

        gate_runtime = self._get_gate_runtime()
        cfg = self._gate_resume_config

        # 0. Validate and sanitize answers
        validation_error = self._validate_gate_answers(answers, cfg)
        if validation_error:
            return {"status": "rejected", "reason": validation_error}

        # 1. Submit response (idempotent, version-checked)
        response = GateResponse(
            gate_id=gate_id,
            version=version,
            answers=answers,
            approved=approved,
        )
        accepted = gate_runtime.submit_response(response)
        if not accepted:
            return {
                "status": "rejected",
                "reason": "gate not active or version mismatch",
            }

        # 2. Load session context for merge
        session = self._task_session_store.get(task_session_id)
        if session is None:
            return {"status": "error", "reason": "session not found"}

        existing_config: Dict[str, Any] = {}
        if session.config_json:
            try:
                existing_config = json.loads(session.config_json)
            except (json.JSONDecodeError, TypeError):
                existing_config = {}

        env_context = existing_config.get("env_context", {})

        merge_result = gate_runtime.merge_answers(
            gate_id=gate_id,
            env_context=env_context,
        )

        # 3. Check if still blocked
        if merge_result.still_blocked:
            logger.info(
                "[TaskSessionManager] Gate %s still blocked after merge, "
                "updated questions: %d",
                gate_id, len(merge_result.updated_questions),
            )
            return {
                "status": "still_blocked",
                "gate_id": gate_id,
                "updated_questions": merge_result.updated_questions,
            }

        # 4. Persist merged answers to session config_json for crash recovery
        answers_payload = json.dumps(answers, ensure_ascii=False)
        if len(answers_payload) > cfg.gate_answers_max_chars:
            answers_payload = answers_payload[:cfg.gate_answers_max_chars]
            logger.warning(
                "[TaskSessionManager] Gate answers truncated to %d chars",
                cfg.gate_answers_max_chars,
            )

        existing_config[cfg.gate_answers_config_key] = json.loads(answers_payload)
        existing_config["env_context"] = env_context
        updated_config_json = json.dumps(existing_config, ensure_ascii=False)

        # 5. Transition to executing
        try:
            self._task_session_store.transition(
                task_session_id, "executing",
                config_json=updated_config_json,
                last_transition_reason=f"gate_resolved:{gate_id}",
            )
        except Exception as e:
            logger.warning(
                "[TaskSessionManager] Transition to executing failed: %s", e,
            )
            return {
                "status": "transition_failed",
                "reason": str(e),
            }

        # 6. Resume execution (non-blocking)
        env_patch: Dict[str, Any] = {
            cfg.gate_answers_env_key: answers,
            "resumed_from_gate": gate_id,
            "gate_merge_target": merge_result.merge_target,
        }
        # Merge the env_context updates from gate merge
        env_patch.update(env_context)

        await self._resume_after_gate(task_session_id, env_patch)

        logger.info(
            "[TaskSessionManager] Gate %s resolved, resuming %s",
            gate_id, task_session_id,
        )
        return {
            "status": "resumed",
            "gate_id": gate_id,
            "merge_target": merge_result.merge_target,
        }

    async def _resume_after_gate(
        self,
        task_session_id: str,
        env_context_patch: Dict[str, Any],
    ) -> None:
        """Re-enter the execution loop after gate resolution.

        Steps:
        1. Re-enqueue to TaskScheduler with resume priority
        2. Emit GATE_RESUMED event via EventBus
        3. Fire resume executor callback (if registered) in background task
        """
        cfg = self._gate_resume_config

        # 1. Re-enqueue for scheduling
        try:
            await self._task_scheduler.enqueue(
                task_session_id=task_session_id,
                task_type=cfg.resume_task_type,
                priority_class=cfg.resume_priority_class,
            )
        except Exception as e:
            logger.error(
                "[TaskSessionManager] Re-enqueue after gate failed: %s", e,
            )

        # 2. Emit GATE_RESUMED event
        gate_runtime = self._get_gate_runtime()
        gate_runtime._emit_gate_event("gate_resumed", {
            "task_session_id": task_session_id,
            "env_context_keys": list(env_context_patch.keys()),
        })

        # 3. Fire resume executor callback (non-blocking background task)
        if self._resume_executor is not None:
            async def _run_resume() -> None:
                try:
                    await self._resume_executor(task_session_id, env_context_patch)
                except Exception as exc:
                    logger.error(
                        "[TaskSessionManager] Resume executor failed for %s: %s",
                        task_session_id, exc, exc_info=True,
                    )
                    # Transition back to waiting_input so user can retry
                    try:
                        self._task_session_store.transition(
                            task_session_id, "waiting_input",
                            last_transition_reason=f"resume_failed:{exc}",
                        )
                    except Exception:
                        pass

            asyncio.create_task(_run_resume())
        else:
            logger.warning(
                "[TaskSessionManager] No resume_executor registered; "
                "session %s transitioned to executing but execution not started. "
                "Call set_resume_executor() during bootstrap.",
                task_session_id,
            )

    @staticmethod
    def _validate_gate_answers(
        answers: dict,
        cfg: GateResumeConfig,
    ) -> Optional[str]:
        """Validate and sanitize gate answers. Returns error message or None."""
        if not isinstance(answers, dict):
            return "answers must be a dict"

        if len(answers) > cfg.max_answer_keys:
            return f"too many answer fields ({len(answers)} > {cfg.max_answer_keys})"

        for key, value in answers.items():
            if not isinstance(key, str):
                return f"answer key must be string, got {type(key).__name__}"
            sv = str(value)
            if len(sv) > cfg.max_answer_value_chars:
                return f"answer '{key}' too long ({len(sv)} > {cfg.max_answer_value_chars})"
            sv_lower = sv.lower()
            for pattern in cfg.forbidden_patterns:
                if pattern.lower() in sv_lower:
                    return f"answer '{key}' contains forbidden pattern"

        return None

    def _get_gate_runtime(self):
        """Lazy-load GateRuntime instance."""
        if not hasattr(self, '_gate_runtime') or self._gate_runtime is None:
            from app.avatar.runtime.task.gate_runtime import GateRuntime
            self._gate_runtime = GateRuntime()
        return self._gate_runtime

    def _get_isolation_context(self, task_session_id: str) -> dict:
        """
        获取任务隔离上下文。

        每个 TaskSession 独立：
        - workspace 目录
        - Plan_Graph
        - Artifact 命名空间
        - event stream（不交叉）
        - task-local memory（不共享）
        """
        return {
            "workspace_prefix": f"task_{task_session_id}",
            "graph_namespace": task_session_id,
            "artifact_namespace": task_session_id,
            "event_stream_id": f"events_{task_session_id}",
            "memory_scope": f"memory_{task_session_id}",
        }

    async def finalize(self, task_session_id: str) -> dict:
        """
        通过 DeliveryGate 检查后生成交付包。

        对于 failed/cancelled：仍生成包含部分产物和原因的交付包。
        """
        session = self._task_session_store.get(task_session_id)
        if session is None:
            raise ValueError(f"TaskSession {task_session_id} not found")

        terminal_status = session.status

        if terminal_status not in ("completed", "failed", "cancelled"):
            # Run delivery gate evaluation
            gate_result = await self._delivery_gate.evaluate(task_session_id)

            if gate_result["passed"]:
                self._task_session_store.transition(task_session_id, "completed")
                terminal_status = "completed"
            else:
                logger.warning(
                    f"[TaskSessionManager] Delivery gate failed for "
                    f"{task_session_id}: {gate_result['reasons']}"
                )
                # Don't transition — return gate result for caller to decide
                return {
                    "task_session_id": task_session_id,
                    "delivery_gate": gate_result,
                    "package": None,
                }

        # Generate delivery package (works for all terminal statuses)
        package = await self._delivery_gate.generate_delivery_package(
            task_session_id, terminal_status
        )

        # Release scheduler slot
        await self._task_scheduler.release_slot(task_session_id)

        logger.info(
            f"[TaskSessionManager] Finalized {task_session_id} "
            f"with status={terminal_status}"
        )
        return {
            "task_session_id": task_session_id,
            "terminal_status": terminal_status,
            "package": package,
        }
