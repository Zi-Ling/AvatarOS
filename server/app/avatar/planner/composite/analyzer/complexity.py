"""
复杂度分析器 - 判断是否需要分解任务
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ComplexityResult:
    """复杂度分析结果"""
    is_complex: bool
    connector_score: float = 0.0
    verb_count: int = 0
    segment_count: int = 0
    reason: str = ""


class ComplexityAnalyzer:
    """
    任务复杂度分析器
    
    职责：
    1. 语义复杂度检测（使用 embedding）
    2. 关键词检测（降级方案）
    3. Intent 元数据判断
    4. 复杂任务快速检测（方案A+B）
    """
    
    # [方案A] 复杂任务连接词/箭头
    COMPLEX_CONNECTOR_TOKENS = [
        "→", "->", "然后", "接着", "再", "并且", "最后", ";", "；", 
        "and then", "接下来", "之后", "同时", "另外", "还要", "以及"
    ]
    
    # 常见动词（用于检测多动词任务）
    COMMON_VERBS = [
        "计算", "保存", "绘制", "打开", "创建", "生成", "分析", "下载",
        "上传", "处理", "转换", "合并", "拆分", "导出", "导入", "发送",
        "读取", "写入", "查询", "搜索", "统计", "汇总", "排序", "过滤"
    ]
    
    def __init__(self, embedding_service: Optional[Any] = None):
        """
        Args:
            embedding_service: 语义向量服务（可选）
        """
        self._embedding_service = embedding_service
        
        # 保留旧的关键词列表以兼容
        self._decompose_keywords = self.COMPLEX_CONNECTOR_TOKENS
    
    def is_complex_task(self, text: str) -> ComplexityResult:
        """
        [方案A] 快速检测是否为复杂任务（多步骤）
        
        检测策略：
        1. 连接词/箭头特征（明确的步骤连接）
        2. 多动词特征（多个动作）
        3. 句子分段数量（逻辑分段）
        
        Args:
            text: 用户输入文本
        
        Returns:
            ComplexityResult: 包含是否复杂及详细分析
        """
        # 1. 连接词/箭头检测
        connector_count = 0
        for token in self.COMPLEX_CONNECTOR_TOKENS:
            connector_count += text.count(token)
        
        # 连接词评分（归一化到0-1）
        connector_score = min(1.0, connector_count * 0.33)  # 3个及以上=1.0
        
        if connector_count > 0:
            logger.debug(f"[ComplexityAnalyzer] 检测到 {connector_count} 个连接词，connector_score={connector_score:.2f}")
            return ComplexityResult(
                is_complex=True,
                connector_score=connector_score,
                reason=f"detected {connector_count} connectors"
            )
        
        # 2. 多动词检测
        verb_count = sum(1 for verb in self.COMMON_VERBS if verb in text)
        
        if verb_count >= 2:
            logger.debug(f"[ComplexityAnalyzer] 检测到 {verb_count} 个动词（多步骤任务）")
            return ComplexityResult(
                is_complex=True,
                verb_count=verb_count,
                reason=f"detected {verb_count} verbs (multi-action)"
            )
        
        # 3. 句子分段检测（按标点分割）
        # Only split on strong separators (。；;) — commas (，,) are often used
        # within a single coherent sentence in Chinese and should NOT trigger
        # multi-step classification by themselves.
        segments = re.split(r'[。；;]', text)
        segments = [s.strip() for s in segments if s.strip() and len(s.strip()) > 3]
        segment_count = len(segments)
        
        if segment_count >= 3:
            logger.debug(f"[ComplexityAnalyzer] 检测到 {segment_count} 个逻辑分段（复杂任务）")
            return ComplexityResult(
                is_complex=True,
                segment_count=segment_count,
                reason=f"detected {segment_count} segments"
            )
        
        # 4. 都不满足 → 简单任务
        logger.debug(f"[ComplexityAnalyzer] 简单任务: connector={connector_count}, verbs={verb_count}, segments={segment_count}")
        return ComplexityResult(
            is_complex=False,
            connector_score=connector_score,
            verb_count=verb_count,
            segment_count=segment_count,
            reason="simple task"
        )
    
    def should_decompose(self, user_request: str, intent: Any = None) -> bool:
        """
        判断是否需要任务分解（向后兼容方法）
        
        策略（优先级从高到低）：
        1. 快速复杂度检测（is_complex_task）
        2. 语义复杂度检测（如果服务可用）
        3. Intent 元数据判断
        
        Args:
            user_request: 用户请求
            intent: Intent 对象（可选）
        
        Returns:
            bool: True 表示需要分解
        """
        # 策略1：快速复杂度检测（新方法，优先级最高）
        complexity_result = self.is_complex_task(user_request)
        if complexity_result.is_complex:
            logger.info(f"[ComplexityAnalyzer] 检测到复杂任务: {complexity_result.reason}")
            return True
        
        # 策略2：语义复杂度检测（如果服务可用）
        if self._embedding_service and self._embedding_service.is_available():
            semantic_result = self._semantic_complexity_check(user_request)
            if semantic_result is not None:
                return semantic_result
        
        # 策略3：基于 Intent 的判断
        if intent and hasattr(intent, 'metadata'):
            complexity = intent.metadata.get('complexity')
            if complexity == 'high':
                logger.info("Intent metadata indicates high complexity")
                return True
        
        return False
    
    def _semantic_complexity_check(self, user_request: str) -> Optional[bool]:
        """
        语义复杂度检测
        
        原理：
        1. 按标点和连接词切分句子
        2. 计算句子间的语义相似度
        3. 如果相似度低（< 0.6），说明包含多个不相关的目标
        
        Returns:
            Optional[bool]: True=需要分解, False=不需要, None=无法判断
        """
        try:
            # 切分句子（按标点和连接词）
            separators = r'[。；;]|然后|接着|之后|并且|同时|另外|还要|以及'
            segments = re.split(separators, user_request)
            segments = [s.strip() for s in segments if s.strip() and len(s.strip()) > 2]
            
            if len(segments) < 2:
                # 只有一个句子，不需要分解
                logger.debug("Single segment detected, no decomposition needed")
                return False
            
            # 计算句子间的平均相似度
            similarities = []
            for i in range(len(segments) - 1):
                sim = self._embedding_service.similarity(segments[i], segments[i + 1])
                similarities.append(sim)
            
            avg_similarity = sum(similarities) / len(similarities)
            
            logger.info(
                f"Semantic complexity check: {len(segments)} segments, "
                f"avg similarity={avg_similarity:.3f}"
            )
            
            # 阈值：平均相似度 < 0.6 认为是多个不相关的任务
            if avg_similarity < 0.6:
                logger.info("Low semantic similarity → decomposition needed")
                return True
            else:
                logger.info("High semantic similarity → single task")
                return False
                
        except Exception as e:
            logger.warning(f"Semantic complexity check failed: {e}")
            return None  # 无法判断，回退到关键词检测
    
    def _keyword_detection(self, user_request: str) -> bool:
        """
        关键词检测（降级方案）
        
        Args:
            user_request: 用户请求
        
        Returns:
            bool: True 表示检测到分解关键词
        """
        for keyword in self._decompose_keywords:
            if keyword in user_request:
                logger.info(f"Detected decompose keyword: '{keyword}' in request")
                return True
        
        return False

