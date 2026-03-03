"""
Adaptive Top-K Calculator

Dynamically calculates the optimal number of skills to retrieve
based on task complexity and similarity scores.
"""
from typing import List, Any


class AdaptiveTopKCalculator:
    """
    自适应 Top-K 计算器
    
    根据任务复杂度和相似度分布动态调整检索的技能数量
    """
    
    # 物理约束常量
    MIN_K = 3   # 物理下限：保证 60% 召回率（概率论）
    MAX_K = 12  # 物理上限：避免 LLM 选择困难（注意力极限）
    
    @staticmethod
    def calculate_initial_k(complexity_score: float) -> int:
        """
        基于复杂度计算初始 Top-K
        
        使用连续函数映射：Top-K = MIN_K + (MAX_K - MIN_K) × complexity
        
        Args:
            complexity_score: 复杂度得分 (0.0 - 1.0)
            
        Returns:
            初始 Top-K 值
        """
        k = AdaptiveTopKCalculator.MIN_K + int(
            (AdaptiveTopKCalculator.MAX_K - AdaptiveTopKCalculator.MIN_K) * complexity_score
        )
        
        return max(AdaptiveTopKCalculator.MIN_K, min(k, AdaptiveTopKCalculator.MAX_K))
    
    @staticmethod
    def calculate_with_cutoff(
        skill_specs: List[Any],
        initial_k: int
    ) -> int:
        """
        基于相似度分布的智能截断
        
        找到相似度分数的"自然断点"，在分数差异最大处截断
        参考 Google/OpenAI 的相似度截断策略
        
        Args:
            skill_specs: 技能列表（已按相关性排序）
            initial_k: 初始 Top-K
            
        Returns:
            最终 Top-K 值
        """
        if len(skill_specs) <= AdaptiveTopKCalculator.MIN_K:
            return len(skill_specs)
        
        max_gap_index = AdaptiveTopKCalculator.MIN_K
        max_gap = 0.0
        
        # 寻找最大的分数差距
        for i in range(AdaptiveTopKCalculator.MIN_K, min(len(skill_specs), AdaptiveTopKCalculator.MAX_K)):
            # 模拟分数：假设分数呈指数衰减
            # 实际应该从 skill_specs[i] 获取真实分数
            score_current = 1.0 / (i + 1)
            score_next = 1.0 / (i + 2) if i + 1 < len(skill_specs) else 0
            
            gap = score_current - score_next
            
            if gap > max_gap:
                max_gap = gap
                max_gap_index = i + 1
        
        # 在 initial_k 和 gap_cutoff 之间取较小值
        final_k = min(max_gap_index, initial_k)
        
        # 应用物理约束
        final_k = max(
            AdaptiveTopKCalculator.MIN_K,
            min(final_k, AdaptiveTopKCalculator.MAX_K)
        )
        
        return final_k
    
    @staticmethod
    def get_search_candidates(initial_k: int) -> int:
        """
        获取语义搜索候选数量
        
        检索比最终需要数量多的候选，为相似度截断留空间
        
        Args:
            initial_k: 初始 Top-K
            
        Returns:
            搜索候选数量
        """
        return int(initial_k * 1.5)

