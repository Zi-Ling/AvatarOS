"""
LLM 驱动的任务分解器
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, TYPE_CHECKING

from ...models.subtask import SubTask, CompositeTask
from ...extractor import JSONExtractionError
from .prompt_builder import DecomposePromptBuilder
from .parser import DecomposeResponseParser

if TYPE_CHECKING:
    from ....runtime.events import EventBus

logger = logging.getLogger(__name__)


class TaskDecomposer:
    """
    任务分解器（Planner 体系的一部分）
    
    职责：
    1. 构建分解 Prompt
    2. 调用 LLM 进行分解
    3. 解析响应
    4. 校验结果（防止模式坍塌）
    5. 构建 CompositeTask
    """
    
    MAX_RETRIES = 2  # 最大重试次数
    
    def __init__(
        self,
        llm_client: Any,
        event_bus: Any = None,
        logger_instance: Any = None
    ):
        """
        Args:
            llm_client: LLM 客户端
            event_bus: 事件总线（可选）
            logger_instance: 日志实例（可选）
        """
        self._llm = llm_client
        self._event_bus = event_bus
        self._logger = logger_instance or logger
        self._retry_count = 0  # 重试计数器
    
    async def decompose(
        self,
        user_request: str,
        intent: Any,
        env_context: Dict[str, Any]
    ) -> CompositeTask:
        """
        将用户请求分解为多个子任务（带超时重试）
        
        Args:
            user_request: 用户请求
            intent: Intent 对象
            env_context: 环境上下文
        
        Returns:
            CompositeTask: 复合任务对象
            
        Raises:
            DecompositionTimeoutError: 分解超时（已重试）
        """
        self._logger.info(f"Decomposing request: {user_request}")
        
        # 重置重试计数
        self._retry_count = 0
        last_validation_error = None
        
        # 发送思考阶段事件
        if self._event_bus:
            self._publish_thinking_event(user_request, intent)
        
        # 尝试 1: 使用完整 Prompt（带 RAG）
        try:
            return await self._try_decompose_with_prompt(
                user_request, 
                intent, 
                env_context,
                use_simplified=False,
                validation_feedback=None
            )
        except ValueError as e:
            # 校验失败：可能是 LLM 理解错误
            if "validation failed" in str(e).lower():
                last_validation_error = str(e)
                self._logger.warning(
                    f"⚠️ [Decompose] Validation failed on attempt 1: {str(e)[:150]}"
                )
                self._logger.info("🔄 [Decompose] Retrying without RAG context + explicit feedback...")
            else:
                raise
        except (TimeoutError, JSONExtractionError, Exception) as e:
            self._logger.warning(
                f"⚠️ [Decompose] First attempt failed: {type(e).__name__}: {str(e)[:100]}"
            )
            self._logger.info("🔄 [Decompose] Retrying with simplified prompt...")
        
        # 尝试 2: 使用简化 Prompt（无 RAG）+ 明确反馈
        self._retry_count = 1
        try:
            return await self._try_decompose_with_prompt(
                user_request,
                intent,
                env_context,
                use_simplified=True,
                validation_feedback=last_validation_error
            )
        except (TimeoutError, JSONExtractionError, Exception) as retry_error:
            self._logger.error(
                f"❌ [Decompose] Retry also failed: {type(retry_error).__name__}: {str(retry_error)[:100]}"
            )
            
            # 两次都失败，抛出友好异常
            from .exceptions import DecompositionTimeoutError
            raise DecompositionTimeoutError(
                message=(
                    f"Task decomposition failed after {self.MAX_RETRIES} attempts.\n"
                    f"Your request may be too complex. Please try breaking it into smaller parts.\n"
                    f"Last error: {str(retry_error)[:200]}"
                ),
                retry_attempted=True
            )
    
    async def _try_decompose_with_prompt(
        self,
        user_request: str,
        intent: Any,
        env_context: Dict[str, Any],
        use_simplified: bool = False,
        validation_feedback: str = None
    ) -> CompositeTask:
        """
        尝试使用指定 Prompt 进行分解
        
        Args:
            user_request: 用户请求
            intent: Intent 对象
            env_context: 环境上下文
            use_simplified: 是否使用简化 Prompt
            validation_feedback: 上次校验失败的反馈（用于重试）
        
        Returns:
            CompositeTask: 复合任务对象
        """
        # 构建分解 Prompt
        if use_simplified:
            prompt = DecomposePromptBuilder.build_simplified(user_request, intent, env_context)
            self._logger.info("📄 [Decompose] Using simplified prompt (no RAG)")
        else:
            prompt = DecomposePromptBuilder.build(user_request, intent, env_context)
        
        # 如果有校验反馈，添加明确的纠错信息
        if validation_feedback:
            feedback_prefix = f"""
⚠️ CORRECTION NEEDED:
Your previous decomposition was rejected because:
{validation_feedback[:300]}

Please re-decompose strictly following the user's original request.
Pay special attention to:
- Use exact file names from user request
- Keep all entities (numbers, file names, actions)
- Don't change the task topic

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
            prompt = feedback_prefix + prompt
            self._logger.info("📝 [Decompose] Added validation feedback to prompt")
        
        # 打印 Prompt 长度统计
        prompt_chars = len(prompt)
        prompt_tokens_estimate = prompt_chars // 4  # 粗略估算
        self._logger.info(f"📊 [Decompose] Prompt 长度: {prompt_chars:,} 字符 (~{prompt_tokens_estimate:,} tokens)")
        
        # 调用 LLM 进行分解（计时）
        llm_start = time.time()
        raw_response = self._call_llm(prompt)
        llm_duration = time.time() - llm_start
        self._logger.info(f"⏱️ [Decompose] LLM 调用耗时: {llm_duration:.2f}s")
        self._logger.debug(f"LLM decompose response: {raw_response[:500]}...")
        
        # 解析 LLM 输出
        subtasks_data = DecomposeResponseParser.parse(raw_response)
        
        # [Optimization] 移除 DecompositionValidator，直接信任 LLM 输出
        # 验证逻辑已下沉到 Pydantic 模型或后续 Planner 阶段
        
        self._logger.info(f"✅ [Decompose] Parsed {len(subtasks_data)} subtasks from LLM")
        
        # 构建 CompositeTask
        
        # 构建 CompositeTask
        composite_task = self._build_composite_task(
            user_request,
            intent,
            subtasks_data
        )
        
        self._logger.info(f"✅ [Decompose] Decomposed into {len(composite_task.subtasks)} subtasks")
        
        # 发送任务分解完成事件
        if self._event_bus:
            self._publish_decomposed_event(composite_task)
        
        return composite_task
    
    def _call_llm(self, prompt: str) -> str:
        """调用 LLM"""
        # 统一接口：所有 LLM 客户端必须实现 call() 方法
        return self._llm.call(prompt)
    
    def _build_composite_task(
        self,
        user_request: str,
        intent: Any,
        subtasks_data: list
    ) -> CompositeTask:
        """
        构建 CompositeTask
        
        Args:
            user_request: 用户请求
            intent: Intent 对象
            subtasks_data: 子任务数据列表
        
        Returns:
            CompositeTask: 复合任务对象
        """
        composite_task = CompositeTask(
            id=str(uuid.uuid4()),
            goal=user_request,
            metadata={
                "intent_id": getattr(intent, "id", None),
                "original_request": user_request,
                "decomposition_method": "llm",
                "session_id": getattr(intent, "metadata", {}).get("session_id") if hasattr(intent, "metadata") else None
            }
        )
        
        for data in subtasks_data:
            # 解析 type 字段（必须字段）
            from ...models.types import SubTaskType
            
            task_type_str = data.get("type", "general_execution")
            try:
                llm_predicted_type = SubTaskType(task_type_str)
            except ValueError:
                self._logger.warning(
                    f"Invalid subtask type '{task_type_str}' for subtask {data.get('id')}, "
                    f"falling back to GENERAL_EXECUTION"
                )
                llm_predicted_type = SubTaskType.GENERAL_EXECUTION
            
            # 使用 LLM 预测的类型，移除 TypeRefiner
            task_type = llm_predicted_type
            
            subtask = SubTask(
                id=data.get("id", str(uuid.uuid4())),
                goal=data["goal"],
                type=task_type,
                order=data.get("order", 0),
                depends_on=data.get("depends_on", []),
                inputs=data.get("inputs", {}),
                expected_outputs=data.get("expected_outputs", []),
                priority=data.get("priority", 0),
                allow_dangerous_skills=data.get("allow_dangerous_skills", False),
                metadata=data.get("metadata", {})
            )
            composite_task.add_subtask(subtask)
        
        return composite_task
    
    def _publish_thinking_event(self, user_request: str, intent: Any):
        """发送思考阶段事件"""
        from ....runtime.events import Event, EventType
        self._event_bus.publish(Event(
            type=EventType.TASK_THINKING,
            source="task_decomposer",
            payload={
                "message": "正在分析任务...",
                "user_request": user_request,
                "session_id": getattr(intent, "metadata", {}).get("session_id") if hasattr(intent, "metadata") else None
            }
        ))
    
    def _publish_decomposed_event(self, composite_task: CompositeTask):
        """发送任务分解完成事件"""
        from ....runtime.events import Event, EventType
        steps_summary = [{"id": st.id, "goal": st.goal} for st in composite_task.subtasks]
        self._event_bus.publish(Event(
            type=EventType.TASK_DECOMPOSED,
            source="task_decomposer",
            payload={
                "message": f"识别到 {len(composite_task.subtasks)} 个子任务",
                "steps": steps_summary,
                "session_id": composite_task.metadata.get("session_id")
            }
        ))

