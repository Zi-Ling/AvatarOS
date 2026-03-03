"""
风险分析器
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .levels import RiskLevel
from .rules import SKILL_RISK_RULES, ParamPatternMatcher
from .rules.skill_rules import get_skill_risk

logger = logging.getLogger(__name__)


class RiskAnalyzer:
    """
    风险分析器
    
    综合分析：
    - 技能风险
    - 参数风险
    - 上下文风险
    - 历史表现
    """
    
    def __init__(self):
        self._param_matcher = ParamPatternMatcher()
    
    def analyze(
        self,
        skill_name: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Tuple[RiskLevel, List[str]]:
        """
        综合风险分析
        
        Args:
            skill_name: 技能名称
            params: 参数字典
            context: 上下文（可选）
        
        Returns:
            (risk_level, warnings): 风险等级和警告列表
        """
        all_warnings = []
        
        # 1. 技能级别风险
        skill_risk = get_skill_risk(skill_name)
        logger.debug(f"Skill risk for '{skill_name}': {skill_risk}")
        
        # 2. 参数模式风险
        param_risk, param_warnings = self._param_matcher.analyze_params(params)
        all_warnings.extend(param_warnings)
        logger.debug(f"Param risk: {param_risk}, warnings: {len(param_warnings)}")
        
        # 3. 上下文风险（可选）
        context_risk = RiskLevel.LOW
        if context:
            context_risk, context_warnings = self._analyze_context(context)
            all_warnings.extend(context_warnings)
        
        # 取最高风险
        final_risk = max(skill_risk, param_risk, context_risk)
        
        logger.info(
            f"Risk analysis for {skill_name}: {final_risk} "
            f"(skill={skill_risk}, params={param_risk}, context={context_risk})"
        )
        
        return final_risk, all_warnings
    
    def _analyze_context(
        self,
        context: Dict[str, Any]
    ) -> Tuple[RiskLevel, List[str]]:
        """
        分析上下文风险
        
        Args:
            context: 上下文字典
        
        Returns:
            (risk_level, warnings)
        """
        warnings = []
        risk = RiskLevel.LOW
        
        # 检查是否在生产环境
        if context.get("environment") == "production":
            risk = RiskLevel.MEDIUM
            warnings.append("Operation in production environment")
        
        # 检查是否有重要数据标记
        if context.get("contains_important_data"):
            risk = max(risk, RiskLevel.HIGH)
            warnings.append("Operation on important data")
        
        return risk, warnings

