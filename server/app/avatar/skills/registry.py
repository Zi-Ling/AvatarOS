# app/avatar/skills/registry.py

from __future__ import annotations

from typing import Dict, Type, List, Optional, Any, Iterator
from dataclasses import dataclass, field
import logging
import numpy as np

from .base import BaseSkill, SkillSpec
from .resolver import ToolResolver
from ..infra.semantic import get_embedding_service, SemanticSimilarity

logger = logging.getLogger(__name__)

@dataclass
class SkillRegistry:
    _by_internal: Dict[str, Type[BaseSkill]] = field(default_factory=dict)
    _by_api: Dict[str, str] = field(default_factory=dict)       # api_name -> internal_name
    _by_alias: Dict[str, str] = field(default_factory=dict)     # alias -> internal_name
    
    # Resolver instance
    resolver: ToolResolver = field(init=False)
    
    # Vector Index state (使用 EmbeddingService + numpy，替代 ChromaDB)
    _embeddings: Optional[np.ndarray] = field(init=False, default=None)  # 技能向量矩阵
    _skill_names: List[str] = field(init=False, default_factory=list)    # 与向量对应的技能名称
    _skill_texts: List[str] = field(init=False, default_factory=list)    # 与向量对应的描述文本
    _index_ready: bool = field(init=False, default=False)
    _embedding_service: Optional[Any] = field(init=False, default=None)

    def __post_init__(self):
        self.resolver = ToolResolver(self, enable_fuzzy=True)
        # 获取全局 EmbeddingService
        self._embedding_service = get_embedding_service()

    def _ensure_vector_index(self):
        """
        Lazy initialization of the in-memory vector index for skills.
        
        使用 EmbeddingService + numpy 替代 ChromaDB：
        - 更快（纯内存计算，无 DB 开销）
        - 更简单（统一向量化服务）
        - 更轻量（无额外依赖）
        """
        if self._index_ready:
            return
        
        # 检查 EmbeddingService 是否可用
        if not self._embedding_service.is_available():
            logger.warning(
                "SkillRegistry: EmbeddingService not available. "
                "Skill semantic search will use fallback (keyword matching)."
            )
            self._index_ready = True  # 标记为已初始化，避免重复尝试
            return

        try:
            skill_names = []
            skill_texts = []
            
            for api_name, internal_name in self._by_api.items():
                cls = self._by_internal[internal_name]
                spec = cls.spec
                
                try:
                    # 构建丰富的语义表示（与之前 ChromaDB 版本相同）
                    text_parts = [
                        f"Skill: {api_name}",
                        f"Description: {spec.description or ''}",
                        f"Aliases: {', '.join(str(a) for a in spec.aliases)}"
                    ]
                    
                    # 参数关键词
                    if spec.input_model:
                        try:
                            param_keys = list(spec.input_model.model_fields.keys())
                            text_parts.append(f"Parameters: {', '.join(str(k) for k in param_keys)}")
                        except Exception as e:
                            logger.debug(f"Skipping parameters for {api_name}: {e}")
                    
                    # 元信息
                    if spec.meta:
                        try:
                            domain = spec.meta.domain.value if hasattr(spec.meta.domain, 'value') else str(spec.meta.domain)
                            caps = []
                            for c in spec.meta.capabilities:
                                if c is None:
                                    continue
                                cap_str = c.value if hasattr(c, 'value') else str(c)
                                if cap_str and not cap_str.startswith('_'):
                                    caps.append(cap_str)
                            
                            text_parts.append(f"Domain: {domain}")
                            if caps:
                                text_parts.append(f"Capabilities: {', '.join(caps)}")
                        except Exception as e:
                            logger.debug(f"Skipping meta info for {api_name}: {e}")
                    
                    full_text = "\n".join(text_parts)
                    
                    if full_text.strip():
                        skill_names.append(api_name)
                        skill_texts.append(full_text)
                
                except Exception as e:
                    logger.debug(f"Skipping skill {api_name} in vector index due to error: {e}")
                    continue
            
            if not skill_names:
                logger.warning("SkillRegistry: No skills to index")
                self._index_ready = True
                return
            
            # 使用 EmbeddingService 批量生成向量
            logger.debug(f"SkillRegistry: Embedding {len(skill_names)} skills...")
            self._embeddings = self._embedding_service.embed_batch(skill_texts)
            self._skill_names = skill_names
            self._skill_texts = skill_texts
            
            logger.info(f"✅ SkillRegistry: Built in-memory vector index for {len(skill_names)} skills (via EmbeddingService)")
            logger.debug(f"   Vector dimension: {self._embeddings.shape[1] if len(self._embeddings.shape) > 1 else 'N/A'}")
            
            self._index_ready = True
            
        except Exception as e:
            logger.error(f"SkillRegistry: Failed to build vector index: {e}", exc_info=True)
            logger.warning("Skill semantic search will use fallback (keyword matching)")
            self._index_ready = True  # 标记为已初始化，避免重复尝试

    def search_skills(self, query: str, limit: int = 15) -> Dict[str, Any]:
        """
        语义搜索技能（使用 EmbeddingService）
        
        返回与查询最相关的 top-K 技能描述
        """
        # 如果查询为空或太短，返回所有技能
        if not query or len(query.strip()) < 2:
            return self.describe_skills()
        
        self._ensure_vector_index()
        
        # 如果向量索引不可用（降级）
        if not self._index_ready or self._embeddings is None:
            logger.debug("SkillRegistry: Vector index not ready, returning all skills")
            return self.describe_skills()

        try:
            # 使用 EmbeddingService 生成查询向量
            query_vec = self._embedding_service.embed_single(query)
            
            # 计算余弦相似度
            scores = []
            for skill_vec in self._embeddings:
                score = SemanticSimilarity.cosine_similarity(query_vec, skill_vec)
                scores.append(score)
            
            # 获取 top-K 索引
            top_k = min(limit, len(self._skill_names))
            top_indices = np.argsort(scores)[::-1][:top_k]
            
            # 获取对应的技能名称
            top_skill_names = [self._skill_names[idx] for idx in top_indices]
            
            # 返回这些技能的完整描述
            all_skills = self.describe_skills()
            filtered_skills = {k: v for k, v in all_skills.items() if k in top_skill_names}
            
            logger.debug(f"SkillRegistry: Semantic search: Query='{query}' -> Found {len(filtered_skills)} skills: {list(filtered_skills.keys())}")
            return filtered_skills
            
        except Exception as e:
            logger.error(f"SkillRegistry: Semantic search failed: {e}")
            return self.describe_skills()
    
    def search_skills_with_scores(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        """
        搜索技能并返回相似度分数（使用 EmbeddingService）
        
        返回格式: [
            {"name": "file.write", "score": 0.85, "description": "..."},
            {"name": "time.now", "score": 0.72, "description": "..."},
            ...
        ]
        
        Note: score 越大表示越相似（余弦相似度，范围 0-1）
        """
        if not query or len(query.strip()) < 2:
            return []
        
        self._ensure_vector_index()
        
        # 如果向量索引不可用（降级）
        if not self._index_ready or self._embeddings is None:
            logger.debug("SkillRegistry: Vector index not ready, cannot compute scores")
            return []

        try:
            # 使用 EmbeddingService 生成查询向量
            query_vec = self._embedding_service.embed_single(query)
            
            # 计算余弦相似度
            scores = []
            for skill_vec in self._embeddings:
                score = SemanticSimilarity.cosine_similarity(query_vec, skill_vec)
                scores.append(float(score))  # 确保是 Python float
            
            # 获取 top-K 索引
            top_k = min(limit, len(self._skill_names))
            top_indices = np.argsort(scores)[::-1][:top_k]
            
            # 获取技能描述
            all_skills = self.describe_skills()
            
            # 组装结果
            scored_skills = []
            for idx in top_indices:
                skill_name = self._skill_names[idx]
                score = scores[idx]
                
                if skill_name in all_skills:
                    scored_skills.append({
                        "name": skill_name,
                        "score": score,
                        "description": all_skills[skill_name].get("description", ""),
                    })
            
            logger.debug(f"SkillRegistry: Semantic search with scores: Query='{query}' -> Top-{len(scored_skills)} skills")
            if scored_skills:
                logger.debug(f"  Top skill: {scored_skills[0]['name']} (score={scored_skills[0]['score']:.3f})")
            
            return scored_skills
            
        except Exception as e:
            logger.error(f"SkillRegistry: Semantic search with scores failed: {e}")
            return []

    def register(self, skill_cls: Type[BaseSkill]) -> None:
        if not hasattr(skill_cls, 'spec') or not isinstance(skill_cls.spec, SkillSpec):
            raise ValueError(f"Skill class {skill_cls.__name__} must have a valid 'spec' attribute.")

        spec = skill_cls.spec
        
        # 1. Register by internal_name (Primary Key)
        if spec.internal_name in self._by_internal:
            raise ValueError(f"Duplicate internal_name: {spec.internal_name}")
        self._by_internal[spec.internal_name] = skill_cls

        # 2. Register by api_name
        if spec.api_name:
            if spec.api_name in self._by_api:
                # Warn but allow overwrite? Or strict? Strict for now.
                raise ValueError(f"Duplicate api_name: {spec.api_name} (used by {self._by_api[spec.api_name]})")
            self._by_api[spec.api_name] = spec.internal_name
        
        # 3. Register by aliases
        for alias in spec.aliases:
            if alias in self._by_alias:
                logger.warning(f"Duplicate alias '{alias}' for skill '{spec.internal_name}'. Previous owner: {self._by_alias[alias]}")
                # Allow overwrite or ignore?
                continue
            self._by_alias[alias] = spec.internal_name

        logger.debug(f"Registered skill: {spec.internal_name} (api={spec.api_name}, aliases={spec.aliases})")

    def get(self, name: str) -> Optional[Type[BaseSkill]]:
        """
        Smart get using Resolver.
        """
        result = self.resolver.resolve(name)
        if result.skill_cls:
            # Removed verbose debug log - only log errors or warnings
            # logger.debug(f"Registry resolved '{name}' -> {result.normalized_name} ({result.matched_as})")
            return result.skill_cls
        return None
    
    def get_instance(self, name: str) -> BaseSkill:
        """Helper to get an instance of the skill."""
        cls = self.get(name)
        if not cls:
            raise ValueError(f"Skill not found: {name}")
        return cls()

    # ---- Internal Accessors for Resolver ----
    def get_by_internal(self, internal_name: str) -> Optional[Type[BaseSkill]]:
        return self._by_internal.get(internal_name)

    def get_internal_name_by_api(self, api_name: str) -> Optional[str]:
        return self._by_api.get(api_name)

    def get_internal_name_by_alias(self, alias: str) -> Optional[str]:
        return self._by_alias.get(alias)
        
    def iter_skills(self) -> Iterator[Type[BaseSkill]]:
        return iter(self._by_internal.values())

    # ---- Metadata Accessors ----
    def list_specs(self) -> List[SkillSpec]:
        return [cls.spec for cls in self._by_internal.values()]

    def describe_skills(self) -> Dict[str, Any]:
        """
        Returns a JSON-serializable description of all skills for LLM/Tools usage.
        Converts Pydantic schemas to JSON Schema.
        Includes output schema to help LLM generate correct variable references.
        Includes meta field for capability routing (Gatekeeper V2).
        """
        result = {}
        # We iterate by API Name (what LLM sees)
        for api_name, internal_name in self._by_api.items():
            cls = self._by_internal[internal_name]
            spec = cls.spec
            
            input_schema = spec.input_model.model_json_schema()
            output_schema = spec.output_model.model_json_schema()
            
            category_val = spec.category
            if hasattr(spec.category, 'value'):
                category_val = spec.category.value
            
            # Serialize meta field for capability routing
            meta = spec.meta
            meta_dict = {
                "domain": meta.domain.value if hasattr(meta.domain, 'value') else str(meta.domain),
                "capabilities": [cap.value if hasattr(cap, 'value') else str(cap) for cap in meta.capabilities],
                "risk_level": meta.risk_level,
                "is_generic": meta.is_generic,
            }
            
            result[api_name] = {
                "description": spec.description,
                "category": category_val,
                "params_schema": input_schema.get("properties", {}),
                "required": input_schema.get("required", []),
                # "full_schema": input_schema, # Too verbose
                # "output_schema": output_schema.get("properties", {}), # Often redundant
                "meta": meta_dict,  # Add meta field for Gatekeeper V2
            }
        return result

    def describe_skills_simple(self) -> str:
        """
        [Roadmap Phase 1]: Returns a lightweight string summary of skills for the Router.
        Format:
        - skill_name: description
        
        Reduces token usage significantly compared to full JSON schema.
        This format is optimized for Prefix Caching as it remains static unless skills change.
        """
        lines = []
        # Sort for stability (crucial for Prefix Caching)
        sorted_skills = sorted(self._by_api.items())
        
        for api_name, internal_name in sorted_skills:
            cls = self._by_internal[internal_name]
            spec = cls.spec
            # Simplify description: take first line only if it's multiline
            desc = spec.description.split('\n')[0] if spec.description else "No description"
            lines.append(f"- {api_name}: {desc}")
            
        return "\n".join(lines)

# Global singleton
skill_registry = SkillRegistry()

def register_skill(skill_cls: Type[BaseSkill]) -> Type[BaseSkill]:
    """
    Decorator to register a skill class.
    
    @register_skill
    class MySkill(BaseSkill): ...
    """
    skill_registry.register(skill_cls)
    return skill_cls
