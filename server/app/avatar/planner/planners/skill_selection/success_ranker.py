"""
Success Rate Ranker

Ranks skills based on historical success rates from the Learning system.
"""
from typing import Dict, Any, List, Tuple, Optional


class SuccessRateRanker:
    """
    成功率排名器
    
    基于历史成功率对技能进行排序
    """
    
    # 最小执行次数阈值（少于此次数不参考成功率）
    MIN_EXECUTION_COUNT = 3
    
    # 默认成功率（无历史数据时）
    DEFAULT_SUCCESS_RATE = 0.5
    
    @staticmethod
    def rank_skills(
        skills: Dict[str, Any],
        skill_statistics: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        根据成功率对技能进行排序
        
        Args:
            skills: 技能字典 {skill_name: skill_spec}
            skill_statistics: 技能统计数据 {skill_name: {success, total, success_rate}}
            
        Returns:
            排序后的技能字典
        """
        # 为每个技能添加成功率信息
        enriched_skills = {}
        
        for skill_name, skill_spec in skills.items():
            stat = skill_statistics.get(skill_name)
            
            # 复制技能规范（避免修改原始数据）
            enriched_spec = skill_spec.copy()
            
            if stat and stat.get("total", 0) >= SuccessRateRanker.MIN_EXECUTION_COUNT:
                # 有足够的历史数据
                enriched_spec["_success_rate"] = stat["success_rate"]
                enriched_spec["_execution_count"] = stat["total"]
            else:
                # 使用默认成功率
                enriched_spec["_success_rate"] = SuccessRateRanker.DEFAULT_SUCCESS_RATE
                enriched_spec["_execution_count"] = stat.get("total", 0) if stat else 0
            
            enriched_skills[skill_name] = enriched_spec
        
        # 按成功率排序（成功率高的在前）
        sorted_skills = sorted(
            enriched_skills.items(),
            key=lambda x: (
                x[1].get("_success_rate", SuccessRateRanker.DEFAULT_SUCCESS_RATE),
                x[1].get("_execution_count", 0)  # 成功率相同时，执行次数多的优先
            ),
            reverse=True
        )
        
        return dict(sorted_skills)
    
    @staticmethod
    def get_skill_ranking_info(
        skills: Dict[str, Any],
        skill_statistics: Dict[str, Dict[str, Any]]
    ) -> List[Tuple[str, float, int]]:
        """
        获取技能排名信息
        
        Returns:
            [(skill_name, success_rate, execution_count), ...]
        """
        ranking = []
        
        for skill_name, skill_spec in skills.items():
            stat = skill_statistics.get(skill_name)
            
            if stat and stat.get("total", 0) >= SuccessRateRanker.MIN_EXECUTION_COUNT:
                success_rate = stat["success_rate"]
                execution_count = stat["total"]
            else:
                success_rate = SuccessRateRanker.DEFAULT_SUCCESS_RATE
                execution_count = stat.get("total", 0) if stat else 0
            
            ranking.append((skill_name, success_rate, execution_count))
        
        # 按成功率排序
        ranking.sort(key=lambda x: (x[1], x[2]), reverse=True)
        
        return ranking

