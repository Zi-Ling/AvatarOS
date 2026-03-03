import logging
from typing import Dict, Set, List, Optional
import numpy as np

from app.avatar.skills.base import SkillCapability, SkillSpec
from app.avatar.skills.registry import skill_registry
from app.avatar.infra.semantic.service import get_embedding_service
from app.avatar.infra.semantic.similarity import SemanticSimilarity

logger = logging.getLogger(__name__)

class CapabilityClassifier:
    """
    基于语义向量的能力识别器
    将自然语言意图映射到 SkillCapability 枚举
    
    V2: 不再使用硬编码的描述，而是从 SkillRegistry 中收集所有技能的描述，
    自动聚类生成每个 Capability 的语义中心。
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CapabilityClassifier, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.service = get_embedding_service()
        self.vectors: Dict[SkillCapability, np.ndarray] = {}
        self._warmed_up = False
        self._initialized = True

    def warmup(self):
        """
        预热：从 SkillRegistry 中学习能力的语义表示
        
        警告：此方法只应在程序启动时调用一次！
        """
        if self._warmed_up:
            logger.warning("CapabilityClassifier already warmed up, skipping.")
            return
        
        if not self.service.is_available():
            logger.warning("Embedding service unavailable, semantic classification disabled.")
            return

        logger.info("Warming up CapabilityClassifier from Skill Registry...")
        
        # 1. 收集每个 Capability 对应的所有技能描述
        cap_to_texts: Dict[SkillCapability, List[str]] = {cap: [] for cap in SkillCapability}
        
        # 获取所有已注册技能的 Spec
        all_specs: List[SkillSpec] = skill_registry.list_specs()
        
        count_skills = 0
        for spec in all_specs:
            desc = (spec.description or "").strip()
            if not desc:
                continue
            
            # 检查该技能声明了哪些 Capability
            caps = getattr(spec.meta, "capabilities", set()) or set()
            
            if not caps:
                continue
                
            count_skills += 1
            for cap in caps:
                # 只有 SkillCapability 枚举值才算数
                if isinstance(cap, SkillCapability):
                    # 将技能描述加入该 Capability 的语料库
                    # 也可以加入 name/synonyms 来增强语义
                    texts = [desc]
                    if getattr(spec, "synonyms", None):
                        texts.extend(spec.synonyms)
                    cap_to_texts[cap].extend(texts)
        
        logger.info(f"Learned from {count_skills} skills.")

        # 2. 对每个 Capability 计算向量中心 (Centroid)
        valid_caps = 0
        for cap, texts in cap_to_texts.items():
            if not texts:
                # 如果某个能力没有技能支持，就跳过（或者给个默认值？）
                # 暂时跳过，意味着系统此时不具备该能力的语义识别
                continue
                
            try:
                # 批量 Embedding
                # 为了防止某个很长的描述占主导，可以考虑只取前 N 个字符，或者分句
                # 这里简单处理：直接 embed 所有文本
                vecs = self.service.embed_batch(texts)
                
                if len(vecs) > 0:
                    # 计算平均向量作为“能力中心”
                    centroid = np.mean(vecs, axis=0)
                    # 归一化（Cosine Similarity 需要）
                    norm = np.linalg.norm(centroid)
                    if norm > 0:
                        centroid = centroid / norm
                        
                    self.vectors[cap] = centroid
                    valid_caps += 1
            except Exception as e:
                logger.error(f"Failed to calculate centroid for capability {cap}: {e}")

        self._warmed_up = True
        logger.info(f"CapabilityClassifier warmed up with {valid_caps} capabilities.")
        
        # 调试输出：每个能力学到了多少语料
        debug_stats = {cap.value: len(texts) for cap, texts in cap_to_texts.items() if texts}
        logger.debug(f"Capability Corpus Stats: {debug_stats}")

    def classify(self, text: str, threshold: float = 0.45) -> Set[SkillCapability]:
        """
        根据文本推断 SkillCapability
        
        Args:
            text: 用户意图或动作描述 (e.g. "save file", "run python")
            threshold: 相似度阈值 (0-1)，低于此值的匹配将被忽略
            
        Returns:
            Set[SkillCapability]: 匹配的能力集合
        """
        if not self.vectors:
            logger.warning("CapabilityClassifier not warmed up, please call warmup() at startup.")
            return set()
            
        # 获取输入文本的向量
        query_vec = self.service.embed_single(text)
        
        matched = set()
        
        # 计算与每个 Capability 的相似度
        scores = []
        for cap, cap_vec in self.vectors.items():
            score = SemanticSimilarity.cosine_similarity(query_vec, cap_vec)
            scores.append((cap, score))
            
        # 按分数降序排序
        scores.sort(key=lambda x: x[1], reverse=True)
        
        if not scores:
            return set()

        # 记录最匹配的几个以便调试
        debug_info = [f"{cap.value}({score:.2f})" for cap, score in scores[:3]]
        logger.debug(f"Semantic classify '{text}' -> {', '.join(debug_info)}")

        # 策略：
        # 1. 必须超过绝对阈值
        # 2. 支持多标签：如果第二名、第三名跟第一名差距很小，也算上
        
        best_cap, best_score = scores[0]
        
        # 如果连第一名都达不到阈值，说明这个意图不明或不支持
        if best_score < threshold:
            return set()
            
        matched.add(best_cap)
        
        # 相对阈值：允许分差在 0.15 以内的其他选项
        relative_threshold = 0.15
        
        for cap, score in scores[1:]:
            if score >= threshold and (best_score - score) < relative_threshold:
                matched.add(cap)
        
        return matched

# 全局访问点
def get_capability_classifier() -> CapabilityClassifier:
    return CapabilityClassifier()

