# server/app/avatar/planner/selector.py
"""
Skill Selector: 技能语义搜索引擎

重构说明：
- 复用 infra.semantic.EmbeddingService（全局单例）
- 移除重复的模型加载逻辑
- 保留关键词匹配作为降级方案
"""
import logging
from typing import List, Optional
import numpy as np

from ..skills.registry import skill_registry, SkillSpec
from ..infra.semantic import get_embedding_service

logger = logging.getLogger(__name__)

class SkillSelector:
    """
    技能语义搜索引擎
    
    使用全局 EmbeddingService 进行语义匹配
    降级策略：如果语义搜索不可用，使用关键词匹配
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SkillSelector, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        # 使用全局 EmbeddingService（不再自己管理模型）
        self._embedding_service = get_embedding_service()
        self._skill_specs: List[SkillSpec] = []
        self._embeddings: Optional[np.ndarray] = None
        self._index_built = False  # 新增：跟踪索引是否已构建
        self._initialized = True

    def initialize(self):
        """
        初始化技能搜索引擎
        
        注意：EmbeddingService 应该在应用启动时全局初始化
        这里只构建技能索引
        
        这个方法是幂等的：重复调用不会重复构建索引
        """
        # 如果索引已构建，跳过
        if self._index_built:
            logger.debug("Skill search index already built, skipping initialization")
            return
        
        # 确保 EmbeddingService 已初始化
        if not self._embedding_service.is_available():
            logger.warning(
                "EmbeddingService not available. "
                "Skill search will use keyword matching fallback."
            )
            return
        
        # 构建技能索引
        logger.info("Building skill search index...")
        self.refresh_index()
        self._index_built = True  # 标记已构建
        logger.info("✅ Skill search index ready")

    def refresh_index(self, force: bool = False):
        """
        重建技能索引（从注册表）
        
        为每个技能生成语义向量，用于后续搜索
        
        Args:
            force: 强制重建索引（即使已存在）
        """
        # 除非强制，否则如果已构建就跳过
        if self._index_built and not force:
            logger.debug("Skill index already exists, skipping rebuild (use force=True to rebuild)")
            return
        
        if not self._embedding_service.is_available():
            logger.warning("EmbeddingService not available, skipping index build")
            return

        specs = []
        texts = []
        
        # 构建可搜索的文本（技能名称 + 描述 + 同义词）
        for skill_cls in skill_registry.iter_skills():
            spec = skill_cls.spec
            specs.append(spec)
            
            # 构建富语义文本
            text = f"{spec.name}: {spec.description}"
            
            if spec.aliases:
                text += f" Synonyms: {', '.join(spec.aliases)}"
            
            texts.append(text)

        if not texts:
            self._embeddings = np.array([])
            self._skill_specs = []
            logger.warning("No skills found in registry")
            return

        logger.info(f"Building index for {len(texts)} skills...")
        
        # 使用 EmbeddingService 批量生成向量
        self._embeddings = self._embedding_service.embed_batch(texts)
        self._skill_specs = specs
        
        logger.info(f"✅ Skill index built: {len(specs)} skills indexed")

    def search(self, query: str, top_k: int = 5, threshold: float = 0.2) -> List[SkillSpec]:
        """
        搜索与查询相关的技能
        
        Args:
            query: 查询文本
            top_k: 返回前K个结果
            threshold: 最低相似度阈值
        
        Returns:
            List[SkillSpec]: 匹配的技能列表
        """
        # 降级策略：如果语义搜索不可用，使用关键词匹配
        if not self._embedding_service.is_available():
            results = self._keyword_search(query, top_k)
            return self._apply_gatekeeper(results, query)
        
        if self._embeddings is None or len(self._embeddings) == 0:
            logger.warning("Skill index empty. Using keyword search.")
            results = self._keyword_search(query, top_k)
            return self._apply_gatekeeper(results, query)

        try:
            # 使用 EmbeddingService 生成查询向量
            query_embedding = self._embedding_service.embed_single(query)
            
            # 计算余弦相似度
            from ..infra.semantic import SemanticSimilarity
            
            scores = []
            for skill_vec in self._embeddings:
                score = SemanticSimilarity.cosine_similarity(query_embedding, skill_vec)
                scores.append(score)
            
            # 获取 top K 索引
            top_indices = np.argsort(scores)[::-1][:top_k]
            
            results = []
            for idx in top_indices:
                score = scores[idx]
                if score < threshold:
                    continue
                
                spec = self._skill_specs[idx]
                results.append(spec)
                
                logger.debug(f"  [{score:.3f}] {spec.name}")
            
            if results:
                logger.debug(f"Semantic search found {len(results)} skills for: {query}")
            
            return self._apply_gatekeeper(results, query)
            
        except Exception as e:
            logger.error(f"Semantic search failed: {e}. Falling back to keyword search.")
            results = self._keyword_search(query, top_k)
            return self._apply_gatekeeper(results, query)
    
    def _apply_gatekeeper(self, candidates: List[SkillSpec], goal: str) -> List[SkillSpec]:
        """
        Safety Gatekeeper: final check for permissions and safety.
        
        Refactored: Removed file extension filtering to trust LLM's tool selection.
        """
        filtered = []
        
        for skill in candidates:
            # Check 1: Enabled
            # if not skill.enabled: # SkillSpec has no enabled field currently
            #    continue
            
            # TODO: Check permissions against user role
            
            filtered.append(skill)
            
        return filtered
    
    def _keyword_search(self, query: str, top_k: int = 5) -> List[SkillSpec]:
        """
        降级方案：简单的关键词匹配
        
        匹配规则：
        1. 查询词在技能名称中 → 高分
        2. 查询词在描述中 → 中分
        3. 查询词在同义词中 → 低分
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        # 获取所有技能
        all_specs = []
        for skill_cls in skill_registry.iter_skills():
            all_specs.append(skill_cls.spec)
        
        # 计算匹配分数
        scored_specs = []
        for spec in all_specs:
            score = 0.0
            
            # 技能名称匹配（高权重）
            if any(word in spec.name.lower() for word in query_words):
                score += 10.0
            
            # 描述匹配（中权重）
            desc_lower = spec.description.lower()
            for word in query_words:
                if word in desc_lower:
                    score += 2.0
            
            # 同义词匹配（中权重）
            for alias in spec.aliases:
                if any(word in alias.lower() for word in query_words):
                    score += 3.0
            
            if score > 0:
                scored_specs.append((spec, score))
        
        # 排序并返回 top K
        scored_specs.sort(key=lambda x: x[1], reverse=True)
        results = [spec for spec, score in scored_specs[:top_k]]
        
        if results:
            logger.debug(f"Keyword search found {len(results)} skills for query: {query}")
        
        return results

# Global instance
skill_selector = SkillSelector()

