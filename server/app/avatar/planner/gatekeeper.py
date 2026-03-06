# server/app/avatar/planner/gatekeeper.py
"""
Execution Gatekeeper V2: Metadata-Driven Capability Routing
"""

import logging
from typing import Any, Dict, Set
from app.avatar.skills.base import SkillSpec, SkillDomain, SkillCapability
from app.avatar.skills.registry import skill_registry

logger = logging.getLogger(__name__)

class ExecutionGatekeeper:
    """
    执行网关：决策是否允许某些"万能"技能（如 python.run）参与选择
    
    逻辑升级：
    - V1: 基于关键词猜测 (Fragile)
    - V2: 基于 Capability Routing (Robust)
    - V3: 基于评分系统 (Intelligent) - 避免硬编码，使用元数据驱动
    """
    
    @staticmethod
    def calculate_skill_match_score(intent: Any, skill_spec: Any) -> float:
        """
        计算技能与意图的匹配分数（0-1）
        
        评分维度：
        1. Domain 匹配度 (40%)
        2. Capability 覆盖度 (40%)
        3. 关键词相关度 (20%)
        
        🔧 V3.1: python.run 永远吃一点劣势，鼓励优先使用专用技能
        
        Returns:
            float: 0.0-1.0 的匹配分数
        """
        score = 0.0
        
        # 1. Domain 匹配 (40%)
        intent_domain = ExecutionGatekeeper._resolve_domain(intent)
        if hasattr(skill_spec, 'meta') and skill_spec.meta:
            skill_domain = skill_spec.meta.domain
            if skill_domain == intent_domain:
                score += 0.4
            elif skill_domain == SkillDomain.SYSTEM or skill_domain == SkillDomain.OTHER:
                score += 0.2  # 通用领域部分匹配
        
        # 2. Capability 覆盖度 (40%)
        intent_actions = ExecutionGatekeeper._infer_actions(intent)
        if hasattr(skill_spec, 'meta') and skill_spec.meta and intent_actions:
            skill_caps = skill_spec.meta.capabilities
            matched_caps = intent_actions.intersection(skill_caps)
            if intent_actions:
                coverage = len(matched_caps) / len(intent_actions)
                score += 0.4 * coverage
        
        # 3. 关键词相关度 (20%)
        goal = getattr(intent, 'goal', '').lower()
        raw = getattr(intent, 'raw_user_input', '').lower()
        text = f"{goal} {raw}"
        
        if hasattr(skill_spec, 'synonyms') and skill_spec.synonyms:
            # 检查是否有同义词匹配
            matched_keywords = sum(1 for syn in skill_spec.synonyms if syn.lower() in text)
            if matched_keywords > 0:
                # 至少匹配1个词得10分，3个以上满分
                keyword_score = min(matched_keywords / 3.0, 1.0)
                score += 0.2 * keyword_score
        
        # 🔧 [Gatekeeper V3.1: 降权而非必杀]
        # python.run 作为"重型武器"，永远吃一点劣势，让专用技能优先
        skill_name = getattr(skill_spec, 'name', '') or getattr(skill_spec, 'api_name', '')
        if skill_name == 'python.run':
            penalty = 0.15  # 降低 15% 分数，让其他技能更容易胜出
            score = max(0.0, score - penalty)
        
        return min(score, 1.0)  # 确保不超过1.0
    
    @staticmethod
    def should_allow_python_run(intent: Any, filtered_skills: Dict[str, Any]) -> bool:
        """
        判断是否应该在候选列表中保留 python.run
        
        🔧 V3.2 策略：基于 SubTaskType 的白名单控制（防止乱入）
        
        核心理念：
        - python.run 只能在特定 SubTaskType 中使用（白名单）
        - 在非白名单类型中，Gatekeeper 直接拦截（不给 LLM 选择机会）
        - 白名单：general_execution, content_generation
        - 黑名单：file_io, gui_operation, information_extraction, schedule
        
        Args:
            intent: Intent 对象
            filtered_skills: 技能字典（键是技能名称，值是字典格式的技能描述）
        """
        # 🎯 [防止 python.run 乱入] 步骤1：基于 SubTaskType 的白名单检查
        if hasattr(intent, 'metadata') and intent.metadata:
            subtask_type_str = intent.metadata.get('subtask_type', '')
            
            # 定义黑名单（这些类型中不允许 python.run）
            PYTHON_RUN_BLOCKED_TYPES = {
                "delete_operation",
                "gui_operation",  # 如果你的 gui_operation 真的是 click/type，那可以挡
                "schedule",  # 外部触发/定时
            }

            if subtask_type_str in PYTHON_RUN_BLOCKED_TYPES:
                logger.info(f"[Gatekeeper] python.run blocked for dangerous SubTaskType '{subtask_type_str}'")
                return False
        
        # 1. 检查 python.run 是否在候选列表中
        if 'python.run' not in filtered_skills:
            return False
        
        # 2. 获取 python.run 的 SkillSpec
        python_skill_cls = skill_registry.get('python.run')
        if not python_skill_cls or not hasattr(python_skill_cls, 'spec'):
            return False
        
        python_spec = python_skill_cls.spec
        
        # 3. 计算匹配分数（已包含降权 penalty）
        match_score = ExecutionGatekeeper.calculate_skill_match_score(intent, python_spec)
        
        # 4. 从元数据读取最低阈值（配置驱动，非硬编码）
        min_threshold = python_spec.meta.min_match_score if hasattr(python_spec.meta, 'min_match_score') else 0.3
        
        logger.debug(f"[Gatekeeper] python.run match score: {match_score:.2f}, threshold: {min_threshold:.2f}")
        
        # 5. 安全策略优先：检查是否有专用技能覆盖危险操作
        intent_domain = ExecutionGatekeeper._resolve_domain(intent)
        intent_actions = ExecutionGatekeeper._infer_actions(intent)
        
        # 收集专用技能
        specialized_skills = []
        for skill_name in filtered_skills.keys():
            if skill_name == 'python.run':
                continue
            
            skill_cls = skill_registry.get(skill_name)
            if skill_cls and hasattr(skill_cls, 'spec'):
                spec = skill_cls.spec
                if hasattr(spec.meta, 'is_generic') and not spec.meta.is_generic:
                    specialized_skills.append((skill_name, spec))
        
        # 危险操作检测
        dangerous_actions = {SkillCapability.WRITE, SkillCapability.DELETE, SkillCapability.MODIFY}
        required_danger_actions = intent_actions.intersection(dangerous_actions)
        
        if required_danger_actions:
            # 检查是否有专用技能覆盖
            covered_by_specialized = False
            for skill_name, spec in specialized_skills:
                # Domain 匹配 且 Capability 覆盖
                if spec.meta.domain == intent_domain or spec.meta.domain == SkillDomain.SYSTEM:
                    if required_danger_actions.issubset(spec.meta.capabilities):
                        logger.info(f"[Gatekeeper] Dangerous action covered by specialized skill '{skill_name}', blocking python.run for safety")
                        covered_by_specialized = True
                        break
            
            if covered_by_specialized:
                return False
            
            # 如果是 FILE 领域的危险操作，但没有专用技能 -> 也不允许 Python（安全优先）
            if intent_domain == SkillDomain.FILE:
                logger.info(f"[Gatekeeper] Uncovered FILE domain dangerous action, blocking python.run for safety")
                return False
        
        # 6. 🆕 分数评估（智能策略：检查专用技能是否真的适合）
        if match_score < min_threshold:
            # 检查是否有其他可用的专用技能
            if specialized_skills:
                # 🎯 检查专用技能的匹配分数
                # 如果所有专用技能的分数都很低，说明它们也不适合，应该允许 python.run
                best_specialized_score = 0.0
                for skill_name, spec in specialized_skills:
                    spec_score = ExecutionGatekeeper.calculate_skill_match_score(intent, spec)
                    best_specialized_score = max(best_specialized_score, spec_score)
                
                # 如果最好的专用技能分数也很低（< 0.4），说明没有真正适合的专用技能
                if best_specialized_score < 0.4:
                    logger.warning(f"[Gatekeeper] python.run score low ({match_score:.2f}), "
                          f"but best specialized skill score also low ({best_specialized_score:.2f}), "
                          f"allowing python.run as fallback")
                    return True
                
                # 有高分的专用技能，拒绝 python.run
                logger.info(f"[Gatekeeper] python.run score low ({match_score:.2f} < {min_threshold:.2f}), "
                      f"and {len(specialized_skills)} specialized skill(s) available (best: {best_specialized_score:.2f}), blocking python.run")
                return False
            else:
                # 没有专用技能，python.run 是唯一选择
                logger.warning(f"[Gatekeeper] python.run score low ({match_score:.2f} < {min_threshold:.2f}), "
                      f"but no specialized skills available, allowing as last resort")
                return True  # 作为救命稻草保留
        
        # 7. 通过所有检查，允许出场
        logger.info(f"[Gatekeeper] python.run passed all checks (score: {match_score:.2f}), allowing")
        return True

    @staticmethod
    def _resolve_domain(intent: Any) -> SkillDomain:
        """解析 Intent Domain"""
        raw_domain = getattr(intent, 'domain', '')
        # 处理 Enum 或 String
        domain_str = raw_domain.name.lower() if hasattr(raw_domain, 'name') else str(raw_domain).lower()
        
        # 映射到 SkillDomain
        if 'file' in domain_str: return SkillDomain.FILE
        if 'web' in domain_str: return SkillDomain.WEB
        if 'office' in domain_str: return SkillDomain.OFFICE
        if 'excel' in domain_str: return SkillDomain.OFFICE # Excel 归类为 Office
        if 'compute' in domain_str: return SkillDomain.COMPUTE
        return SkillDomain.OTHER

    @staticmethod
    def _infer_actions(intent: Any) -> Set[SkillCapability]:
        """
        从 Intent 中解析 Action (Semantic Version)
        
        利用语义向量匹配，将用户的 Intent 映射到 SkillCapability。
        不再依赖硬编码的关键词字典。
        """
        try:
            from app.avatar.infra.semantic.classifier import get_capability_classifier
            
            # 1. 构造查询文本
            # 优先使用 action_type (Router 的直接判断)
            # 辅以 goal (用户的原始需求) 以增加语义上下文
            parts = []
            if hasattr(intent, 'action_type') and intent.action_type:
                 parts.append(str(intent.action_type))
            
            if hasattr(intent, 'goal') and intent.goal:
                parts.append(intent.goal)
                
            query = " ".join(parts).strip()
            
            if not query:
                return set()
                
            # 2. 调用语义分类
            classifier = get_capability_classifier()
            return classifier.classify(query)
            
        except ImportError:
            logger.warning("[Gatekeeper] Semantic module not found, semantic classification disabled.")
            return set()
        except Exception as e:
            logger.error(f"[Gatekeeper] Semantic classification failed: {e}")
            return set()

    @staticmethod
    def filter_skills(intent: Any, skills: Dict[str, Any]) -> Dict[str, Any]:
        """
        过滤技能列表，移除不应该使用的通用技能（如 python.run）
        
        Args:
            intent: Intent 对象
            skills: 技能字典（键是技能名称，值是字典格式的技能描述）
        
        Returns:
            过滤后的技能字典
        """
        result = skills.copy()
        
        if 'python.run' in result:
            if not ExecutionGatekeeper.should_allow_python_run(intent, result):
                result.pop('python.run')
                # print(f"[Gatekeeper] 🚫 Removed python.run")
        
        return result

