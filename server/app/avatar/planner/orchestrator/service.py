"""
编排服务（Orchestration Service）

职责：
- 任务分解（调用 TaskDecomposer）
- Intent 构造（调用 IntentFactory）
- 依赖解析（调用 DependencyResolver）
- 输出收集（调用 OutputCollector）

这是编排层的唯一入口，所有编排相关的操作都通过这个服务。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..models.subtask import CompositeTask, SubTask
from ..models import Task

logger = logging.getLogger(__name__)


class OrchestrationService:
    """
    编排服务（门面模式）
    
    组合所有编排相关的组件，提供统一的接口。
    """
    
    def __init__(
        self,
        llm_client: Any,
        embedding_service: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        logger_instance: Optional[Any] = None
    ):
        """
        初始化编排服务
        
        Args:
            llm_client: LLM 客户端（用于任务分解）
            embedding_service: 向量服务（用于输出提取和依赖推断）
            event_bus: 事件总线
            logger_instance: 日志实例
        """
        self._llm = llm_client
        self._embedding_service = embedding_service
        self._event_bus = event_bus
        self._logger = logger_instance or logger
        
        # 延迟初始化子组件（避免循环导入）
        self._decomposer = None
        self._intent_factory = None
        self._dependency_resolver = None
        self._output_collector = None
        self._dependency_inferrer = None  # 【方案1】新增
    
    def _ensure_components(self):
        """延迟初始化所有子组件"""
        if self._decomposer is None:
            from .decomposer.llm_decomposer import TaskDecomposer
            from .intent_factory import IntentFactory
            from .dependency_resolver import DependencyResolver
            from .output_collector import OutputCollector
            from .output.extractor import OutputExtractor
            from .dependency_inferrer import DependencyInferrer  # 【方案1】新增
            
            self._decomposer = TaskDecomposer(
                self._llm, self._event_bus, self._logger
            )
            self._intent_factory = IntentFactory()
            self._dependency_resolver = DependencyResolver()
            self._output_collector = OutputCollector(
                OutputExtractor(self._embedding_service)
            )
            self._dependency_inferrer = DependencyInferrer(
                self._embedding_service
            )  # 【方案1】新增
    
    async def decompose(
        self,
        user_request: str,
        intent: Any,
        env_context: Dict[str, Any]
    ) -> CompositeTask:
        """
        任务分解
        
        将用户请求分解为多个子任务。
        
        Args:
            user_request: 用户请求
            intent: 原始 Intent
            env_context: 环境上下文
        
        Returns:
            CompositeTask: 分解后的复合任务
        """
        self._ensure_components()
        
        self._logger.info(f"[OrchestrationService] Decomposing: '{user_request[:50]}...'")
        
        # 委托给 TaskDecomposer
        composite = await self._decomposer.decompose(user_request, intent, env_context)
        
        self._logger.info(
            f"[OrchestrationService] Decomposed into {len(composite.subtasks)} subtasks"
        )
        
        # 【方案1】智能依赖推断
        composite = self._dependency_inferrer.infer_and_补充(composite)
        
        self._logger.info(
            f"[OrchestrationService] After dependency inference: "
            f"{len([st for st in composite.subtasks if st.inputs])} subtasks have inputs"
        )
        
        # 🌉 【Bridge层】自动修正类型不匹配
        from .bridge_injector import BridgeInjector
        composite = BridgeInjector.apply(composite)
        
        return composite
    
    def create_subtask_intent(
        self,
        subtask: SubTask,
        composite: CompositeTask,
        original_intent: Any,
        completed_subtasks: Dict[str, SubTask]
    ) -> Any:
        """
        创建子任务的 Intent
        
        这是唯一创建子任务 Intent 的地方，metadata 在这里一次性设置完整。
        
        步骤：
        1. 解析依赖（DependencyResolver）
        2. 构造 Intent（IntentFactory）
        
        Args:
            subtask: 当前子任务
            composite: 所属的复合任务
            original_intent: 原始 Intent
            completed_subtasks: 已完成的子任务（用于依赖解析）
        
        Returns:
            IntentSpec: 构造好的 Intent（包含完整的 metadata）
        """
        self._ensure_components()
        
        # 1. 解析依赖
        resolved_inputs = self._dependency_resolver.resolve(
            subtask, completed_subtasks
        )
        
        # 🎯 增强日志：显示实际值的预览
        resolved_preview = {}
        for k, v in resolved_inputs.items():
            if isinstance(v, str):
                preview = v[:100] + "..." if len(v) > 100 else v
            else:
                preview = str(v)[:100] + "..." if len(str(v)) > 100 else str(v)
            resolved_preview[k] = preview
        
        self._logger.debug(
            f"[OrchestrationService] Resolved inputs for {subtask.id}: "
            f"{list(resolved_inputs.keys())}"
        )
        
        if resolved_inputs:
            self._logger.info(
                f"[OrchestrationService] Resolved input values for {subtask.id}: "
                f"{resolved_preview}"
            )
        
        # 2. 构造 Intent（一次性设置完整 metadata）
        intent = self._intent_factory.create(
            subtask, composite, original_intent, resolved_inputs
        )
        
        # 验证关键信息
        if hasattr(intent, 'metadata') and intent.metadata:
            self._logger.info(
                f"[OrchestrationService] Created Intent for {subtask.id}: "
                f"type={intent.metadata.get('subtask_type')}, "
                f"resolved_inputs={list(resolved_inputs.keys())}"
            )
        
        return intent
    
    def collect_subtask_outputs(
        self,
        subtask: SubTask,
        task: Task,
        composite: CompositeTask
    ) -> Dict[str, Any]:
        """
        收集子任务输出
        
        从执行完成的 Task 中提取输出，更新 SubTask 的 actual_outputs。
        
        Args:
            subtask: 当前子任务
            task: 执行完成的 Task
            composite: 所属的复合任务
        
        Returns:
            Dict[str, Any]: 提取的输出字典
        """
        self._ensure_components()
        
        # 委托给 OutputCollector
        outputs = self._output_collector.collect(subtask, task, composite)
        
        self._logger.info(
            f"[OrchestrationService] Collected outputs for {subtask.id}: "
            f"{list(outputs.keys())}"
        )
        
        return outputs

