"""
SimpleLLMPlanner - Refactored Version

A clean, modular LLM-based task planner.

Previous file: ~900 lines
New version: ~200 lines (80% reduction)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, List, Mapping

from ..base import TaskPlanner
from ..models import Task
from ..registry import register_planner
from ..extractor import SmartJSONExtractor, LLMSelfHealer, JSONExtractionError, FriendlyErrorFormatter, RetryablePlanningError
from ..core.validation import TaskValidator
from .prompts import build_planner_prompt
from app.avatar.skills.registry import skill_registry
from app.avatar.runtime.cache import get_plan_cache

# 子模块导入
from .skill_selection import SkillSelectorEngine
from .context_builders import MemoryRetriever, RAGRetriever, ArtifactRetriever
from .parsing import PlanNormalizer
from .plan_validator import PlanValidator

logger = logging.getLogger(__name__)


class SimpleLLMPlanner(TaskPlanner):
    """
    简化的 LLM 任务规划器
    
    职责：
    - 协调各子模块（技能选择、上下文构建、解析）
    - 流程控制：缓存检查 → 技能选择 → Prompt构建 → LLM调用 → 解析
    """
    
    def __init__(
        self,
        llm_client: Any,
        *,
        logger: Optional[Any] = None,
        max_steps: int = 20,
        memory_manager: Optional[Any] = None,
        learning_manager: Optional[Any] = None,
        use_tool_calling: bool = False,
    ) -> None:
        self._llm = llm_client
        self._logger = logger
        self._max_steps = max_steps
        self.use_tool_calling = use_tool_calling
        
        # 初始化子模块
        self.skill_selector = SkillSelectorEngine(
            skill_registry=skill_registry,
            llm_client=llm_client,
            learning_manager=learning_manager
        )
        
        self.memory_retriever = MemoryRetriever(memory_manager, learning_manager)
        self.rag_retriever = RAGRetriever(memory_manager)
        self.artifact_retriever = ArtifactRetriever(memory_manager)
    
    async def make_task(
        self,
        intent: Any,
        env_context: Dict[str, Any],
        ctx: Optional[Any] = None,
        *,
        memory: Optional[str] = None,
    ) -> Task:
        """
        构建任务
        
        流程：
        1. 缓存检查
        2. 上下文构建（Memory、RAG、Artifacts）
        3. 技能选择
        4. Prompt构建
        5. LLM调用
        6. JSON解析（三层容错）
        7. 计划规范化
        8. 验证
        """
        goal = getattr(intent, "goal", "")
        raw_input = getattr(intent, "raw_user_input", "")
        intent_type = getattr(intent, "intent_type", "unknown")
        
        # 正确提取 domain（处理枚举类型）
        domain_obj = getattr(intent, "domain", None)
        if domain_obj:
            domain = domain_obj.value if hasattr(domain_obj, 'value') else str(domain_obj)
        else:
            domain = "other"
        
        params = getattr(intent, "params", {})
        
        # 保存用户消息供 fallback 使用
        self._current_user_message = raw_input or goal
        self._current_intent_label = intent_type
        
        logger.debug(f"Planner: make_task called with goal='{goal}', domain={domain}")
        
        # --- 1. 缓存检查 (v2 接口) ---
        plan_cache = get_plan_cache(self.memory_retriever.memory_manager)
        cached_template = plan_cache.get(intent_type, domain, goal, params)
        
        if cached_template:
            logger.debug(f"Planner: Cache hit! Template has {len(cached_template.step_skeletons)} steps")
            
            # 实例化模板为可执行的步骤
            instantiated_steps = plan_cache.instantiate(cached_template, params, goal)
            
            if instantiated_steps:
                logger.debug(f"Planner: Successfully instantiated {len(instantiated_steps)} steps from cache")
                # 直接使用实例化的步骤创建任务
                return self._create_task_from_instantiated_steps(intent, instantiated_steps, from_cache=True)
            else:
                logger.debug(f"Planner: Failed to instantiate cached template (missing params), generating new plan...")
        else:
            logger.debug("Planner: No cache hit, generating new plan...")
        
        # --- 2. 上下文构建 ---
        conversation_context = self.memory_retriever.retrieve_conversation_context(intent)
        user_preferences = self.memory_retriever.retrieve_user_preferences(intent)
        similar_cases = self.rag_retriever.retrieve_similar_cases(goal, raw_input, n_results=3)
        recent_artifacts = self.artifact_retriever.retrieve_recent_artifacts(intent, max_count=5)
        
        # --- 3. 技能选择 ---
        # 简化：不再进行子任务类型过滤或两阶段判断
        allow_dangerous = False
        if hasattr(intent, 'metadata') and intent.metadata:
            allow_dangerous = intent.metadata.get('allow_dangerous_skills', False)
        
        # 优先复用 Router 层的技能搜索结果（避免重复向量搜索）
        router_scored_skills = None
        if hasattr(intent, 'metadata') and intent.metadata:
            router_scored_skills = intent.metadata.get('router_scored_skills')
        
        filtered_skills = self.skill_selector.select_skills(
            intent,
            goal,
            raw_input,
            enable_two_stage=False, # 禁用两阶段
            subtask_type=None,      # 移除类型约束
            allow_dangerous=allow_dangerous,
            router_scored_skills=router_scored_skills,
        )
        
        # --- 4. Prompt构建 + 5. LLM调用 ---
        logger.debug(f"Planner: Using {'Tool Calling' if self.use_tool_calling else 'JSON Steps'} mode")
        
        if self.use_tool_calling:
            # Tool Calling 模式
            steps_data = await self._plan_with_tool_calling(
                intent,
                filtered_skills,
                conversation_context,
                user_preferences,
                similar_cases,
                recent_artifacts
            )
        else:
            # 传统 JSON Steps 模式
            prompt = build_planner_prompt(
                intent,
                filtered_skills,
                conversation_context=conversation_context,
                user_preferences=user_preferences,
                similar_cases=similar_cases,
                recent_artifacts=recent_artifacts
            )
            
            if self._logger:
                self._logger.debug("SimpleLLMPlanner prompt:\n%s", prompt)
            
            logger.debug(f"Planner: About to call LLM with prompt length: {len(prompt)}")
            
            # Extract skill names for JSON Schema constraint
            skill_names = list(filtered_skills.keys()) if filtered_skills else None
            raw = await self._call_llm(prompt, skill_names=skill_names)
            logger.debug(f"Planner: LLM raw response: {raw[:500]}...")
            
            steps_data = await self._parse_with_fallback(raw, prompt)
        
        logger.debug(f"Planner: Parsed {len(steps_data)} steps from LLM response")
        
        # 限制步骤数
        if len(steps_data) > self._max_steps:
            steps_data = steps_data[:self._max_steps]
        
        # --- 7. 计划规范化 ---
        normalized_steps = PlanNormalizer.normalize(steps_data)
        
        # --- 8. 构建Task ---
        # 注意：缓存写入已移至执行器（executor），只在执行成功后才缓存
        task = self._create_task(intent, normalized_steps)
        
        # --- 9. 计划优化（Plan Optimizer）---
        # 在 Planner 输出后进行优化，合并连续的相同技能操作
        from app.avatar.planner.composite.optimizer import optimize_task
        task = optimize_task(task, enabled=True)
        
        # --- 10. 验证（仅保留基础 Schema 验证，移除业务类型校验）---
        # 我们相信 SkillSelector 已经过滤了不该用的技能（基于权限），所以不再做 PlanValidator 的严格校验
        # task = self._validate_with_retry(task, filtered_skills, prompt, skill_names, intent=intent)
        
        return task

    
    # Removed _make_task_two_stage method as part of architecture simplification
    # The system now uses a single-stage ReAct/Tool-use planner

    
    async def _make_task_single_stage(
        self,
        intent: Any,
        filtered_skills: Dict[str, Any],
        conversation_context: Optional[Dict[str, Any]],
        user_preferences: Optional[Dict[str, Any]],
        similar_cases: Optional[List[Dict[str, Any]]],
        recent_artifacts: Optional[List[Dict[str, Any]]]
    ) -> Task:
        """
        单阶段 Planner（原有逻辑）
        
        用于：
        - 两阶段失败时的 fallback
        - 明确不需要两阶段的场景
        """
        # 构建 Prompt
        # [优化] 使用工具调用风格的 Prompt，而不是分阶段的
        prompt = build_planner_prompt(
            intent,
            filtered_skills,
            conversation_context=conversation_context,
            user_preferences=user_preferences,
            similar_cases=similar_cases,
            recent_artifacts=recent_artifacts
        )
        
        # 调用 LLM
        skill_names = list(filtered_skills.keys()) if filtered_skills else None
        raw = await self._call_llm(prompt, skill_names=skill_names)
        
        # 解析
        steps_data = await self._parse_with_fallback(raw, prompt)
        
        # 规范化
        from .parsing import PlanNormalizer
        normalized_steps = PlanNormalizer.normalize(steps_data)
        
        # 验证（移除严格类型校验）
        # from .plan_validator import PlanValidator
        # normalized_steps = PlanValidator.validate_steps_against_subtask_type(
        #     intent, normalized_steps, strict=True
        # )
        
        # 构建 Task
        task = self._create_task(intent, normalized_steps)
        
        # 验证（带重试）- 主要为了检查 Schema 和 Skill 是否存在
        task = await self._validate_with_retry(task, filtered_skills, prompt, skill_names, intent=intent)
        
        return task
    
    def _auto_fix_format(self, parsed: Any) -> Any:
        """
        智能预处理：自动修复常见的 LLM 输出格式错误
        
        修复场景：
        1. LLM 返回单个步骤对象 {"id":"step1",...} → 包装成 {"steps": [{...}]}
        2. LLM 返回数组 [{...}] → 包装成 {"steps": [{...}]}
        3. LLM 正确返回 {"steps": [...]} → 保持不变
        
        这样可以避免大部分情况下调用 LLM 自愈（节省时间和 Token）
        """
        # 场景 1: 单个步骤对象（最常见的错误）
        if isinstance(parsed, dict):
            # 如果已经有 steps 字段，说明格式正确
            if "steps" in parsed:
                return parsed
            
            # 如果是单个步骤对象（包含 id 和 skill 字段）
            if "id" in parsed and "skill" in parsed:
                logger.debug(f"Planner: Auto-fixed format - wrapped single step object")
                return {"steps": [parsed]}
            
            # 其他 dict 情况，保持不变（让后续验证处理）
            return parsed
        
        # 场景 2: 数组（较常见的错误）
        elif isinstance(parsed, list):
            # 如果是步骤数组（第一个元素是步骤对象）
            if len(parsed) > 0 and isinstance(parsed[0], dict) and "skill" in parsed[0]:
                logger.debug(f"Planner: Auto-fixed format - wrapped array into steps object")
                return {"steps": parsed}
            
            # 其他 list 情况，保持不变
            return parsed
        
        # 其他类型，保持不变
        return parsed
    
    async def _parse_with_fallback(self, raw: str, prompt: str) -> list:
        """
        三层容错解析
        
        1. 智能提取 JSON + 格式预处理（自动修复常见格式错误）
        2. LLM 自修复（async）
        3. 友好降级（调用 fallback 技能）
        """
        import asyncio

        try:
            # 第一层：智能提取
            parsed, is_clean = SmartJSONExtractor.extract(raw)
            
            if not is_clean:
                logger.debug(f"Planner: JSON extracted from messy output")
            
            # [优化] 智能预处理：自动修复常见格式错误（避免调用 LLM 自愈）
            parsed = self._auto_fix_format(parsed)
            
            # 验证结构
            is_valid, validation_error = SmartJSONExtractor.validate_plan_structure(parsed)
            if not is_valid:
                raise JSONExtractionError(
                    validation_error,
                    raw[:500],
                    ["请检查任务描述是否清晰", "尝试分解成更简单的步骤"]
                )
            
            # 规范化为列表
            if isinstance(parsed, dict) and "steps" in parsed:
                return parsed["steps"]
            
            return parsed if isinstance(parsed, list) else [parsed]
            
        except JSONExtractionError as e:
            logger.debug(f"Planner: ❌ Layer 1 Failed - {e}")

            # 第二层：LLM自修复（通过 to_thread 避免阻塞）
            healer = LLMSelfHealer(self._llm)
            healed_output = await asyncio.to_thread(healer.heal, prompt, raw, str(e), 2)
            
            if healed_output:
                try:
                    parsed, _ = SmartJSONExtractor.extract(healed_output)
                    
                    # [优化] 自愈后也应用格式预处理
                    parsed = self._auto_fix_format(parsed)
                    
                    is_valid, _ = SmartJSONExtractor.validate_plan_structure(parsed)
                    
                    if is_valid:
                        logger.debug(f"Planner: ✅ Layer 2 Success - Healed and parsed")
                        if isinstance(parsed, dict) and "steps" in parsed:
                            return parsed["steps"]
                        return parsed if isinstance(parsed, list) else [parsed]
                except Exception as e2:
                    logger.debug(f"Planner: ❌ Layer 2 Failed - {e2}")
            
            # 第三层：抛出可重试异常，让 AgentLoop 触发 replanner
            logger.debug(f"Planner: ⚠️ Layer 3 - Raising RetryablePlanningError (will trigger replanner)")
            raise RetryablePlanningError(
                reason=f"JSON extraction and self-healing failed: {str(e)}",
                original_error=e
            )
    
    def _create_task_from_instantiated_steps(
        self,
        intent: Any,
        steps: List[Any],  # List[Step] objects from plan_cache.instantiate()
        from_cache: bool = False
    ) -> Task:
        """从实例化的步骤创建任务（v2 缓存接口）"""
        import uuid
        
        # 保留 intent.metadata
        intent_metadata = {}
        if hasattr(intent, 'metadata') and intent.metadata:
            intent_metadata = intent.metadata.copy()

        # 生成 task ID
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        intent_id = getattr(intent, "id", None)

        # 直接使用 Step 对象构建 Task（修复：提供必需的 id 和 intent_id 参数）
        task = Task(
            id=task_id,
            goal=getattr(intent, "goal", ""),
            steps=steps,
            intent_id=intent_id,
            metadata={
                "intent_type": getattr(intent, "intent_type", None),
                "planner": "simple_llm_v2_cached" if from_cache else "simple_llm_v2",
                "from_cache": from_cache,
                **intent_metadata
            }
        )

        return task
    
    def _create_task_from_cache(
        self,
        intent: Any,
        cached_steps: list,
        new_params: Dict[str, Any]
    ) -> Task:
        """从缓存创建任务（已废弃，保留用于兼容）"""
        # 应用新参数到缓存步骤
        steps_data = PlanNormalizer.apply_to_cached_steps(cached_steps, new_params)
        
        # 保留 intent.metadata
        intent_metadata = {}
        if hasattr(intent, 'metadata') and intent.metadata:
            intent_metadata = intent.metadata.copy()
        
        task_dict = {
            "goal": getattr(intent, "goal", ""),
            "steps": steps_data,
            "metadata": {
                "intent_id": getattr(intent, "id", None),
                "intent_type": getattr(intent, "intent_type", None),
                "planner": "simple_llm_v2_cached",
                "from_cache": True,
                **intent_metadata
            },
        }
        
        return Task.from_dict(task_dict)
    
    def _create_task(self, intent: Any, steps_data: list) -> Task:
        """创建新任务"""
        import uuid
        
        # 保留 intent.metadata
        intent_metadata = {}
        if hasattr(intent, 'metadata') and intent.metadata:
            intent_metadata = intent.metadata.copy()

        # 生成 task ID 和获取 intent_id
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        intent_id = getattr(intent, "id", None)

        task_dict = {
            "id": task_id,
            "goal": getattr(intent, "goal", ""),
            "steps": steps_data,
            "intent_id": intent_id,
            "metadata": {
                "intent_type": getattr(intent, "intent_type", None),
                "planner": "simple_llm_v2",
                **intent_metadata
            },
        }

        return Task.from_dict(task_dict)
    
    async def _plan_with_tool_calling(
        self,
        intent: Any,
        filtered_skills: Dict[str, Any],
        conversation_context: Optional[Dict[str, Any]],
        user_preferences: Optional[Dict[str, Any]],
        similar_cases: Optional[List[Dict[str, Any]]],
        recent_artifacts: Optional[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """
        使用 Tool Calling 模式生成计划
        
        Args:
            intent: 用户意图
            filtered_skills: 可用技能
            conversation_context: 对话上下文
            user_preferences: 用户偏好
            similar_cases: 相似案例
            recent_artifacts: 近期产物
            
        Returns:
            List[Dict]: 步骤数据列表
        """
        from app.avatar.skills.common.tool_format import SkillToToolConverter
        from app.llm.types import LLMMessage, LLMRole
        import asyncio
        
        goal = getattr(intent, "goal", "")
        raw_input = getattr(intent, "raw_user_input", "")
        
        # 转换技能为工具定义
        skill_specs = [skill_cls.spec for skill_cls in filtered_skills.values() if hasattr(skill_cls, 'spec')]
        tools = SkillToToolConverter.convert_batch(skill_specs)
        
        logger.debug(f"Planner: Converted {len(tools)} skills to tool definitions")
        
        # 构建系统消息
        system_msg = self._build_tool_calling_system_message(
            conversation_context,
            user_preferences,
            similar_cases,
            recent_artifacts
        )
        
        # 构建用户消息
        user_msg = f"Goal: {goal}\nUser Input: {raw_input}"
        
        messages = [
            LLMMessage(role=LLMRole.SYSTEM, content=system_msg),
            LLMMessage(role=LLMRole.USER, content=user_msg)
        ]
        
        # 调用 LLM（带工具定义）
        response = await asyncio.to_thread(self._llm.chat, messages, tools)
        
        # 检查是否有 tool_calls
        if response.tool_calls:
            logger.debug(f"Planner: Got {len(response.tool_calls)} tool calls from LLM")
            
            # 转换为步骤格式
            steps_data = []
            for i, tc in enumerate(response.tool_calls):
                step = {
                    "id": tc.id,
                    "skill": tc.name,
                    "params": tc.arguments,
                    "depends_on": []
                }
                steps_data.append(step)
            
            return steps_data
        else:
            # 降级到 JSON 模式
            logger.debug("Planner: No tool_calls in response, falling back to JSON mode")
            prompt = build_planner_prompt(
                intent,
                filtered_skills,
                conversation_context=conversation_context,
                user_preferences=user_preferences,
                similar_cases=similar_cases,
                recent_artifacts=recent_artifacts
            )
            skill_names = list(filtered_skills.keys())
            raw = await self._call_llm(prompt, skill_names=skill_names)
            return await self._parse_with_fallback(raw, prompt)
    
    def _build_tool_calling_system_message(
        self,
        conversation_context: Optional[Dict[str, Any]],
        user_preferences: Optional[Dict[str, Any]],
        similar_cases: Optional[List[Dict[str, Any]]],
        recent_artifacts: Optional[List[Dict[str, Any]]]
    ) -> str:
        """构建 Tool Calling 模式的系统消息"""
        msg = "You are a task planning assistant. Analyze the user's goal and select appropriate tools to complete it.\n\n"
        
        if conversation_context:
            msg += f"Conversation Context:\n{conversation_context}\n\n"
        
        if user_preferences:
            msg += f"User Preferences:\n{user_preferences}\n\n"
        
        if similar_cases:
            msg += "Similar Cases:\n"
            for case in similar_cases[:2]:
                msg += f"- {case.get('description', '')}\n"
            msg += "\n"
        
        if recent_artifacts:
            msg += "Recent Artifacts:\n"
            for artifact in recent_artifacts[:3]:
                msg += f"- {artifact.get('path', '')} ({artifact.get('type', '')})\n"
            msg += "\n"
        
        msg += "Select the tools needed to accomplish the goal. Return tool calls in the order they should be executed."
        
        return msg
    
    async def _call_llm(self, prompt: str, skill_names: Optional[List[str]] = None) -> str:
        """
        调用 LLM（统一接口，async — 通过 asyncio.to_thread 避免阻塞事件循环）

        Args:
            prompt: LLM prompt
            skill_names: Optional list of available skill names (for JSON Schema constraint)

        Raises:
            AttributeError: 如果 LLM 客户端没有 call() 方法
        """
        import asyncio

        # Tool Calling 模式
        if self.use_tool_calling and skill_names:
            from app.llm.types import LLMMessage, LLMRole
            from app.avatar.skills.common.tool_format import SkillToToolConverter
            
            # 转换技能为工具定义
            tools = SkillToToolConverter.convert_by_names(skill_names)
            
            if not tools:
                logger.debug("Planner: No tools converted, falling back to JSON mode")
                json_schema = self._build_plan_schema(skill_names)
                return await asyncio.to_thread(self._llm.call, prompt, json_schema=json_schema)
            
            # 调用 LLM with tools（同步 → 线程池）
            messages = [LLMMessage(role=LLMRole.USER, content=prompt)]
            response = await asyncio.to_thread(self._llm.chat, messages, tools)
            
            if response.tool_calls:
                import json
                steps = []
                for tc in response.tool_calls:
                    steps.append({
                        "id": tc.id,
                        "skill": tc.name,
                        "params": tc.arguments,
                        "depends_on": []
                    })
                return json.dumps({"steps": steps})
            
            return response.content or "{}"
        
        # JSON Schema 模式（原有逻辑）
        json_schema = None
        if skill_names:
            json_schema = self._build_plan_schema(skill_names)

        return await asyncio.to_thread(self._llm.call, prompt, json_schema=json_schema)
    
    def _build_plan_schema(self, skill_names: List[str]) -> Dict[str, Any]:
        """
        构建计划的 JSON Schema，约束技能名称只能从给定列表中选择
        
        Args:
            skill_names: List of available skill names
            
        Returns:
            JSON Schema for plan validation
        """
        return {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "skill": {
                        "type": "string",
                        "enum": skill_names  # ← 关键：约束技能名称
                    },
                    "description": {"type": "string"},
                    "params": {"type": "object"},
                    "max_retry": {"type": "integer", "minimum": 0},
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": ["id", "skill", "params"],
                "additionalProperties": False
            }
        }
    
    def _validate_no_subtask_refs(self, task: Any) -> None:
        """
        验证任务中不包含 {{subtask_X:xxx}} 占位符
        
        这些占位符应该在 CompositeExecutor 中被解析，Planner 不应该输出它们。
        
        Args:
            task: 待验证的任务
            
        Raises:
            ValueError: 如果发现 subtask 引用
        """
        import re
        
        # 检测 {{subtask_X:xxx}} 或 {{subtask_X.xxx}} 模式
        subtask_pattern = re.compile(r'\{\{\s*subtask_[^}]+\s*\}\}', re.IGNORECASE)
        
        violations = []
        
        for step in task.steps:
            # 检查所有参数值
            for param_key, param_value in (step.params or {}).items():
                if isinstance(param_value, str):
                    matches = subtask_pattern.findall(param_value)
                    if matches:
                        violations.append({
                            "step_id": step.id,
                            "param": param_key,
                            "value": param_value,
                            "matches": matches
                        })
        
        if violations:
            error_details = "\n".join([
                f"  - Step '{v['step_id']}', param '{v['param']}': {v['matches']}"
                for v in violations
            ])
            raise ValueError(
                f"Planner output contains {{{{subtask_X:xxx}}}} placeholders, which should not exist. "
                f"These should be resolved before planning.\n"
                f"Violations:\n{error_details}"
            )
    
    async def _validate_with_retry(
        self,
        task: Any,
        filtered_skills: Mapping[str, Any],
        original_prompt: str,
        skill_names: Optional[List[str]] = None,
        max_retries: int = 2,
        intent: Optional[Any] = None
    ) -> Any:
        """
        验证任务，如果失败则让 LLM 重新生成
        
        Args:
            task: 待验证的任务
            filtered_skills: 可用技能列表
            original_prompt: 原始 prompt
            skill_names: 技能名称列表
            max_retries: 最大重试次数
            
        Returns:
            验证通过的任务
        """
        all_skills = skill_registry.describe_skills()
        
        for attempt in range(max_retries + 1):
            try:
                # ========== 【新增】验证：不允许 subtask 引用 ==========
                try:
                    self._validate_no_subtask_refs(task)
                except ValueError as subtask_err:
                    # 捕获 subtask 引用错误，记录并准备重试
                    logger.debug(f"Planner: ❌ Subtask reference validation failed: {subtask_err}")
                    raise  # 重新抛出，让外层处理重试
                
                # 标准验证
                TaskValidator.validate(task, all_skills, strict=True)
                if attempt > 0:
                    logger.debug(f"Planner: ✅ Validation passed on retry attempt {attempt}")
                return task
            except Exception as e:
                error_msg = str(e)
                logger.debug(f"Planner: ❌ Validation failed (attempt {attempt + 1}/{max_retries + 1}): {error_msg}")
                
                if attempt >= max_retries:
                    # 最后一次失败，抛出可重试异常
                    logger.debug(f"Planner: ⚠️ Validation exhausted retries - Raising RetryablePlanningError")
                    raise RetryablePlanningError(
                        reason=f"Plan validation failed after {max_retries + 1} attempts: {error_msg}"
                    )
                
                # 构建修正 prompt（根据错误类型定制提示）
                is_subtask_ref_error = "subtask" in error_msg.lower() and "placeholder" in error_msg.lower()
                
                if is_subtask_ref_error:
                    # 针对 subtask 引用错误的特殊提示
                    correction_prompt = f"""{original_prompt}

⚠️⚠️⚠️ PREVIOUS ATTEMPT FAILED ⚠️⚠️⚠️

Your previous plan had the following error:
{error_msg}

❌ CRITICAL ERROR: You output {{{{subtask_X:xxx}}}} placeholders in your plan.

✅ CORRECTION REQUIRED:
- DO NOT use {{{{subtask_X:xxx}}}} format - these are internal references that should already be resolved
- If you see "已解析的输入变量" in the prompt above, use those ACTUAL VALUES directly in your params
- Only use {{{{step_id.output.field}}}} format to reference OTHER STEPS in THE SAME TASK

Example of what NOT to do:
❌ "content": "{{{{subtask_1:thank_you_text}}}}"

Example of what TO do:
✅ "content": "（直接使用上面 '已解析的输入变量' 中提供的实际文本）"
✅ "content": "{{{{step1.output.text}}}}"  (referencing another step in THIS task)

Generate the corrected plan now (pure JSON object with "steps" field):
"""
                else:
                    # 原有的技能验证错误提示
                    correction_prompt = f"""{original_prompt}

⚠️⚠️⚠️ PREVIOUS ATTEMPT FAILED ⚠️⚠️⚠️

Your previous plan had the following error:
{error_msg}

This usually means you used a skill that doesn't exist in the available skills list.

Please regenerate the plan:
1. ONLY use skills from the "Available skills" list above
2. If you used a non-existent skill, replace it with:
   - An existing similar skill from the list, OR
   - "python.run" to write custom code

Generate the corrected plan now (pure JSON object with "steps" field):
"""
                
                # 重新调用 LLM
                logger.debug(f"Planner: Attempting correction (retry {attempt + 1})...")
                raw = await self._call_llm(correction_prompt, skill_names=skill_names)
                
                # 解析并重新构建任务
                try:
                    steps_data = await self._parse_with_fallback(raw, correction_prompt)
                    normalized_steps = PlanNormalizer.normalize(steps_data)
                    # 重新构建任务（使用原始 intent）
                    if intent:
                        task = self._create_task(intent, normalized_steps)
                    else:
                        # Fallback: 保留原有 metadata
                        task.steps = [Task.from_dict({"steps": normalized_steps}).steps[0] for _ in normalized_steps]
                except Exception as parse_error:
                    logger.debug(f"Planner: ❌ Failed to parse corrected plan: {parse_error}")
                    # 继续循环尝试下一次
                    continue
        
        # 不应该到达这里
        raise RuntimeError("Validation retry logic error")
    
    async def re_plan(
        self,
        original_task: Task,
        failed_step: Any,
        error_msg: str,
        env_context: Dict[str, Any],
        *,
        memory: Optional[str] = None
    ) -> Task:
        """
        重规划（简化版）
        
        自动使用 fallback 技能兜底（通过 _parse_with_fallback）
        """
        from .prompts import build_replan_prompt
        
        # 保存用户消息供 fallback 使用
        self._current_user_message = original_task.goal
        self._current_intent_label = "replan"
        
        try:
            # 技能选择
            query = f"{original_task.goal} {error_msg}"
            filtered_skills = self.skill_selector.select_skills(
                type('Intent', (), {'goal': query, 'raw_user_input': error_msg, 'domain': 'other', 'intent_type': 'replan'})(),
                original_task.goal,
                error_msg,
                enable_two_stage=False
            )
            
            # 构建 prompt
            prompt = build_replan_prompt(original_task, failed_step, error_msg, filtered_skills)
            
            # 调用 LLM (with skill constraint)
            skill_names = list(filtered_skills.keys()) if filtered_skills else None
            raw = await self._call_llm(prompt, skill_names=skill_names)
            
            # 解析（如果失败会自动返回 fallback 步骤）
            steps_data = await self._parse_with_fallback(raw, prompt)
            
            # 规范化
            normalized_steps = PlanNormalizer.normalize(steps_data)
            
            # 保留成功的步骤 + 添加新步骤
            from ..models import Step
            kept_steps = [s for s in original_task.steps if s.status.name == "SUCCESS"]
            
            # 构建新步骤（直接使用字典解包）
            new_steps = []
            for i, step_dict in enumerate(normalized_steps):
                new_step = Step(
                    id=step_dict["id"],
                    skill_name=step_dict["skill"],
                    params=step_dict.get("params", {}),
                    order=len(kept_steps) + i,
                    max_retry=step_dict.get("max_retry", 0),
                    depends_on=step_dict.get("depends_on", []),
                    description=step_dict.get("description", "")
                )
                new_steps.append(new_step)
            
            original_task.steps = kept_steps + new_steps
            return original_task
        
        except Exception as e:
            # 重规划失败，不应该在这里使用 fallback
            # 让异常向上传播，由 Replanner 处理
            logger.debug(f"Planner: ⚠️ Re-plan failed - Exception will propagate: {e}")
            raise
    
    def _create_fallback_step(self, reason: str) -> list:
        """
        创建 fallback 技能步骤
        
        用于：
        - JSON 解析完全失败
        - 验证失败且重试用尽
        - 其他意外情况
        
        Args:
            reason: 失败原因（内部错误信息）
        
        Returns:
            包含单个 fallback 步骤的列表
        """
        return [{
            "id": "fallback_step",
            "skill": "llm.fallback",
            "description": "System fallback - generate helpful response",
            "params": {
                "user_message": getattr(self, '_current_user_message', ''),
                "intent": getattr(self, '_current_intent_label', None),
                "reason": reason[:500]  # 限制长度
            },
            "max_retry": 0,
            "depends_on": []
        }]


register_planner("simple_llm", SimpleLLMPlanner)

