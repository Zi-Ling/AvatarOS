"""
Skill Selector Engine

Orchestrates the skill selection process:
- Semantic search
- Adaptive top-k calculation
- Success rate ranking
- Gatekeeper filtering
- Two-stage retrieval
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ....skills.registry import SkillRegistry

from .complexity_analyzer import ComplexityAnalyzer
from .adaptive_topk import AdaptiveTopKCalculator
from .success_ranker import SuccessRateRanker
from ...selector import skill_selector
from ...gatekeeper import ExecutionGatekeeper

logger = logging.getLogger(__name__)


class SkillSelectorEngine:
    """
    技能选择引擎
    
    协调整个技能选择流程：
    1. 复杂度分析
    2. 自适应 Top-K 计算
    3. 语义搜索
    4. 相似度截断
    5. 成功率排序
    6. 网关过滤
    7. 双阶段检索（可选）
    """
    
    
    def __init__(
        self,
        skill_registry: Any,
        llm_client: Optional[Any] = None,
        learning_manager: Optional[Any] = None
    ):
        """
        初始化技能选择引擎
        
        Args:
            skill_registry: 技能注册表
            llm_client: LLM 客户端（用于双阶段检索）
            learning_manager: 学习管理器（获取成功率统计）
        """
        self.skill_registry = skill_registry
        self.llm_client = llm_client
        self.learning_manager = learning_manager
        
        # 确保 skill_selector 已初始化
        try:
            skill_selector.initialize()
        except Exception:
            pass
    
    def select_skills(
        self,
        intent: Any,
        goal_text: str,
        raw_input: str,
        *,
        enable_two_stage: bool = True,
        subtask_type: Optional[Any] = None,
        allow_dangerous: bool = False,
        router_scored_skills: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        选择相关技能
        
        Args:
            intent: IntentSpec 对象
            goal_text: 目标描述
            raw_input: 原始用户输入
            enable_two_stage: 是否启用双阶段检索
            subtask_type: 子任务类型（如果是子任务）
            allow_dangerous: 是否允许危险技能
            router_scored_skills: Router 层已完成的技能搜索结果（避免重复向量搜索）
            
        Returns:
            选中的技能字典 {skill_name: skill_spec}
        """
        # 如果 Router 已经提供了技能搜索结果，直接复用
        if router_scored_skills:
            logger.debug(f"SkillSelector: Reusing {len(router_scored_skills)} skills from Router (skipping vector search)")
            relevant_api_names = {s['name'] for s in router_scored_skills}
            all_skills = self.skill_registry.describe_skills()
            filtered_skills = {k: v for k, v in all_skills.items() if k in relevant_api_names}
            
            if filtered_skills:
                # 跳过复杂度分析、向量搜索、自适应截断，直接进入网关过滤
                # 应用网关过滤
                filtered_skills = ExecutionGatekeeper.filter_skills(intent, filtered_skills)
                
                # 成功率排序
                if self.learning_manager:
                    try:
                        skill_statistics = self.learning_manager.get_skill_statistics()
                        if skill_statistics:
                            filtered_skills = SuccessRateRanker.rank_skills(filtered_skills, skill_statistics)
                    except Exception as e:
                        logger.debug(f"SkillSelector: Failed to apply success ranking: {e}")
                
                if filtered_skills:
                    logger.debug(f"SkillSelector: Final {len(filtered_skills)} skills (from Router cache)")
                    return filtered_skills
            
            # Router 结果为空或过滤后为空，fallthrough 到正常流程
            logger.debug(f"SkillSelector: Router skills empty after filtering, falling back to full search")
        
        # 1. 复杂度分析
        complexity_score, breakdown = ComplexityAnalyzer.analyze_with_breakdown(
            goal_text, raw_input
        )
        
        logger.debug(f"SkillSelector: Complexity={complexity_score:.2f}, "
              f"breakdown={breakdown}")
        
        # 2. 计算初始 Top-K
        initial_k = AdaptiveTopKCalculator.calculate_initial_k(complexity_score)
        
        logger.debug(f"SkillSelector: Initial Top-K={initial_k} "
              f"(range: {AdaptiveTopKCalculator.MIN_K}-{AdaptiveTopKCalculator.MAX_K})")
        
        # 3. 构建搜索查询（零硬编码，动态提取）
        query_parts = [goal_text]  # 目标是最重要的
        
        # 如果有原始输入且与目标不同，添加它
        if raw_input and raw_input != goal_text:
            query_parts.append(raw_input)
        
        # 【零硬编码】如果有子任务类型，从 Policy 中提取自然语言提示
        if subtask_type:
            type_hint = self._extract_natural_hint_from_policy(subtask_type)
            if type_hint:
                query_parts.append(type_hint)
        
        query = " ".join(query_parts)
        
        # 4. 执行语义搜索
        search_candidates = AdaptiveTopKCalculator.get_search_candidates(initial_k)
        relevant_specs = skill_selector.search(query, top_k=search_candidates)
        
        logger.debug(f"SkillSelector: Semantic search found {len(relevant_specs)} skills")
        
        # 5. 自适应截断
        final_k = AdaptiveTopKCalculator.calculate_with_cutoff(relevant_specs, initial_k)
        relevant_specs = relevant_specs[:final_k]
        relevant_api_names = {s.api_name for s in relevant_specs}
        
        logger.debug(f"SkillSelector: After adaptive cutoff: {final_k} skills")
        
        # 6. 从 registry 获取完整技能描述
        all_skills = self.skill_registry.describe_skills()
        filtered_skills = {k: v for k, v in all_skills.items() if k in relevant_api_names}
        
        # 8. 【新增】根据子任务类型过滤技能
        if subtask_type:
            from ...models.types import filter_skills_by_type
            
            original_count = len(filtered_skills)
            filtered_skills = filter_skills_by_type(
                filtered_skills,
                subtask_type,
                allow_dangerous
            )
            logger.debug(f"SkillSelector: Type-based filtering ({subtask_type.value}): "
                  f"{original_count} → {len(filtered_skills)} skills")
            
            # 如果过滤后为空，记录警告但继续（避免完全阻塞）
            if not filtered_skills and original_count > 0:
                logger.warning(
                    f"Type-based filtering removed ALL skills! "
                    f"This might indicate a mismatch between subtask type and available skills."
                )
        
        # 9. 应用网关过滤
        logger.debug(f"SkillSelector: Before gatekeeper: {len(filtered_skills)} skills")
        filtered_skills = ExecutionGatekeeper.filter_skills(intent, filtered_skills)
        logger.debug(f"SkillSelector: After gatekeeper: {len(filtered_skills)} skills")
        
        # 10. 成功率排序
        if self.learning_manager:
            try:
                skill_statistics = self.learning_manager.get_skill_statistics()
                if skill_statistics:
                    filtered_skills = SuccessRateRanker.rank_skills(
                        filtered_skills,
                        skill_statistics
                    )
                    logger.debug(f"SkillSelector: Reordered by success rate")
            except Exception as e:
                logger.debug(f"SkillSelector: Failed to apply success ranking: {e}")
        
        # 11. 双阶段检索（可选）
        if enable_two_stage and len(filtered_skills) > 8 and self.llm_client:
            filtered_skills = self._two_stage_retrieval(
                intent,
                filtered_skills,
                relevant_specs
            )
        
        # 12. 智能降级处理：根据上下文选择合适的 fallback 策略
        if not filtered_skills:
            if subtask_type:
                # 策略1：如果是子任务，fallback 到该类型允许的所有技能
                # 优势：LLM 至少在正确的技能范围内选择，不会违反类型约束
                logger.debug(f"SkillSelector: No skills found, fallback to all skills allowed by type '{subtask_type.value}'")
                
                from ...models.types import filter_skills_by_type
                type_allowed_skills = filter_skills_by_type(
                    all_skills,
                    subtask_type,
                    allow_dangerous
                )
                
                if type_allowed_skills:
                    filtered_skills = type_allowed_skills
                    logger.debug(f"SkillSelector: Fallback to {len(type_allowed_skills)} type-allowed skills")
                else:
                    # 极端情况：该类型没有任何技能可用
                    # 记录错误，但给一个空字典让 Planner 处理
                    logger.error(
                        f"No skills available for type '{subtask_type.value}', "
                        f"this indicates a system configuration issue"
                    )
                    # 不 fallback 到全技能，保持空字典，让 PlanValidator 拦截
                    filtered_skills = {}
            else:
                # 策略2：如果是顶层任务（无类型约束），fallback 到全技能
                logger.debug(f"SkillSelector: No skills found, fallback to all skills (top-level task)")
                filtered_skills = all_skills
        
        return filtered_skills
    
    def _extract_natural_hint_from_policy(self, subtask_type: Any) -> Optional[str]:
        """
        【零硬编码】从 SubTaskTypePolicy 中动态提取自然语言提示
        
        策略：
        1. 提取 Policy 描述中的核心关键词
        2. 从允许的技能名称中提取类别前缀
        3. 使用标准输出字段作为语义提示
        
        完全基于已有的 Policy 配置，无需额外硬编码。
        
        Args:
            subtask_type: 子任务类型
        
        Returns:
            str: 自然语言提示，如果无法提取返回 None
        """
        try:
            from ...models.types import get_policy
            
            policy = get_policy(subtask_type)
            hint_parts = []
            
            # 策略1: 直接使用 Policy 描述（零处理）
            if policy.description:
                # 直接使用原始描述，让向量模型自己理解语义
                hint_parts.append(policy.description)
            
            # 策略2: 从允许的技能中提取类别关键词
            if policy.allowed_skills:
                skill_categories = set()
                for skill_name in list(policy.allowed_skills)[:10]:  # 限制数量
                    # 提取技能前缀（类别）
                    if '.' in skill_name:
                        category = skill_name.split('.')[0]
                        skill_categories.add(category)
                
                # 将类别添加到提示中
                if skill_categories:
                    hint_parts.append(" ".join(sorted(skill_categories)))
            
            # 策略3: 使用标准输出字段（反映任务本质）
            if policy.standard_output_fields:
                # 只取前2个字段，避免过多噪音
                fields = policy.standard_output_fields[:2]
                hint_parts.extend(fields)
            
            # 组合所有提示
            result = " ".join(hint_parts) if hint_parts else None
            
            if result:
                logger.debug(f"SkillSelector: Natural hint for {subtask_type.value}: '{result}'")
            
            return result
            
        except Exception as e:
            logger.debug(f"SkillSelector: Failed to extract natural hint: {e}")
            return None
    
    def _two_stage_retrieval(
        self,
        intent: Any,
        skills: Dict[str, Any],
        relevant_specs: List[Any]
    ) -> Dict[str, Any]:
        """
        双阶段检索
        
        当技能数量过多时，先用 LLM 进行初步筛选
        
        Args:
            intent: IntentSpec 对象
            skills: 候选技能字典
            relevant_specs: 语义搜索的原始结果
            
        Returns:
            精简后的技能字典
        """
        logger.debug(f"SkillSelector: Engaging two-stage retrieval (candidates={len(skills)})")
        
        try:
            # 构建选择 prompt
            selection_prompt = self._build_selection_prompt(intent, skills)
            
            # 调用 LLM
            raw_response = self._call_llm(selection_prompt)
            logger.debug(f"SkillSelector: Selection stage response: {raw_response[:200]}...")
            
            # 解析选择结果
            selected_names = self._parse_selection_response(raw_response)
            logger.debug(f"SkillSelector: Selection stage picked: {selected_names}")
            
            if not selected_names:
                return skills  # 解析失败，返回原始结果
            
            # 构建精简的技能集合
            new_filtered = {}
            
            # 保留语义搜索的 top-1 作为安全锚点
            top_search_skill = relevant_specs[0].api_name if relevant_specs else None
            
            for name in selected_names:
                # 尝试精确匹配
                if name in skills:
                    new_filtered[name] = skills[name]
                else:
                    # 尝试通过别名解析
                    resolved = self.skill_registry.get(name)
                    if resolved and resolved.spec.api_name in skills:
                        new_filtered[resolved.spec.api_name] = skills[resolved.spec.api_name]
            
            # 确保 top-1 被包含
            if top_search_skill and top_search_skill in skills:
                new_filtered[top_search_skill] = skills[top_search_skill]
            
            if new_filtered:
                logger.debug(f"SkillSelector: Refined to {len(new_filtered)} skills")
                return new_filtered
            else:
                logger.debug(f"SkillSelector: Selection stage returned no valid skills, fallback")
                return skills
                
        except Exception as e:
            logger.debug(f"SkillSelector: Two-stage retrieval failed: {e}, fallback")
            return skills
    
    def _build_selection_prompt(self, intent: Any, skills: Dict[str, Any]) -> str:
        """构建技能选择 prompt（仅包含名称和描述）"""
        skill_list_str = ""
        for name, info in skills.items():
            desc = info.get("description", "No description")
            skill_list_str += f"- {name}: {desc}\n"
        
        goal = getattr(intent, 'goal', '')
        raw_input = getattr(intent, 'raw_user_input', '')
        
        return f"""You are an expert task planner. Your job is to select the most relevant tools (skills) to solve the user's request.

USER REQUEST: "{goal}"
Original Input: "{raw_input}"

AVAILABLE TOOLS:
{skill_list_str}

INSTRUCTIONS:
1. Analyze the user's request.
2. Select 1-3 tools from the list above that are absolutely necessary to solve the problem.
3. Return ONLY a JSON list of tool names.

EXAMPLE:
User: "Calculate fibonacci"
Tools:
- python.run: Execute Python code
- file.write: Write file
Response: ["python.run"]

JSON RESPONSE:"""
    
    def _parse_selection_response(self, raw: str) -> List[str]:
        """解析 LLM 选择响应"""
        try:
            # 清理 markdown 代码块
            text = raw.strip()
            if "```" in text:
                matches = re.findall(r'```(?:json)?(.*?)```', text, re.DOTALL)
                if matches:
                    text = matches[0].strip()
            
            # 尝试 JSON 解析
            return json.loads(text)
        except Exception:
            # 降级：正则提取
            matches = re.findall(r'["\']([\w\.]+)["\']', raw)
            return matches
    
    def _call_llm(self, prompt: str) -> str:
        """调用 LLM"""
        if hasattr(self.llm_client, "call"):
            return self.llm_client.call(prompt)
        if hasattr(self.llm_client, "generate"):
            return self.llm_client.generate(prompt)
        if callable(self.llm_client):
            return self.llm_client(prompt)
        raise TypeError("LLM client must be callable")

