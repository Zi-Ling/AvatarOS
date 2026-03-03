"""
Embedding Service (ONNX-only)

提供全局单例的嵌入模型服务，支持：
- 文本嵌入（单个/批量）
- 语义相似度计算
- 向量缓存（LRU）
- 降级策略（依赖缺失/初始化失败时）

当前实现：ONNX Runtime + HuggingFace tokenizer（适配 BGE-M3 ONNX）。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from functools import lru_cache
from typing import List, Optional, Dict

import numpy as np

from .similarity import SemanticSimilarity
from .models import SemanticMatch

logger = logging.getLogger(__name__)


def _check_dependencies() -> bool:
    """检查必要依赖是否可用（onnxruntime + transformers + numpy）"""
    try:
        import onnxruntime  # noqa: F401
        import transformers  # noqa: F401
        import numpy  # noqa: F401
        return True
    except Exception:
        return False


_DEPENDENCIES_AVAILABLE = _check_dependencies()


class EmbeddingService:
    """
    嵌入服务（全局单例）

    设计目标：
    - ONNX-only：不引入 AutoModel / torch，以免加载慢、依赖重、分支复杂
    - 懒加载：initialize() 时加载
    - 线程安全：推理加锁
    - 缓存：LRU 缓存单条 embedding
    - 降级：不可用时返回 hash 向量
    """

    _instance: Optional["EmbeddingService"] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        # ONNX backend
        self._ort_session = None              # onnxruntime.InferenceSession
        self._tokenizer = None                # transformers.AutoTokenizer
        self._input_names: set[str] = set()   # ONNX 输入名
        self._output_names: list[str] = []    # ONNX 输出名

        # state
        self._model_name: Optional[str] = None
        self._dimension: int = 0
        self._use_semantic: bool = False
        self._model_lock = threading.Lock()

        # stats
        self._call_count = 0
        self._total_time = 0.0
        self._cache_hits = 0

        self._initialized = True

    # ------------------------------------------------------------------ #
    # 初始化
    # ------------------------------------------------------------------ #
    def initialize(self, model_name: str = None, model_path: str = None) -> bool:
        """
        初始化嵌入模型（ONNX Runtime）

        Args:
            model_name: 模型名称（用于日志）
            model_path: ONNX 模型目录路径（应包含 model.onnx）

        Returns:
            bool: 是否初始化成功
        """
        if self._use_semantic and self._ort_session is not None:
            logger.info(f"EmbeddingService already initialized: {self._model_name}")
            return True

        if not _DEPENDENCIES_AVAILABLE:
            logger.warning("EmbeddingService dependencies not available. Install: onnxruntime transformers numpy")
            logger.warning("Semantic features will be disabled (using fallback)")
            return False

        # 从配置读取默认值
        if model_name is None and model_path is None:
            try:
                from app.core.config import config
                if getattr(config, "embedding_use_local", True):
                    model_path = str(config.embedding_model_path)
                model_name = getattr(config, "embedding_model_name", "bge-m3")
            except Exception as e:
                logger.warning(f"Could not load config, using defaults: {e}")
                model_name = "bge-m3"

        logger.info(
            "Initializing EmbeddingService with "
            f"model_name={model_name!r}, model_path={model_path!r}"
        )

        try:
            if not model_path:
                raise ValueError("model_path is required for ONNX backend")

            self._init_onnx_backend(model_path, model_name=model_name)
            return True

        except Exception as e:
            logger.error(f"Failed to initialize EmbeddingService: {e}")
            logger.warning("Semantic features will be disabled (using fallback)")
            self._use_semantic = False
            self._ort_session = None
            self._tokenizer = None
            self._input_names = set()
            self._output_names = []
            self._dimension = 0
            return False

    def _init_onnx_backend(self, model_dir: str, model_name: str = "bge-m3") -> None:
        """
        初始化 ONNX Runtime 后端（model_dir 应包含 model.onnx）
        tokenizer 默认从上级目录加载（与 BGE-M3 常见目录结构匹配）
        """
        import onnxruntime as ort
        from transformers import AutoTokenizer

        model_dir = os.path.normpath(model_dir)
        model_onnx = os.path.join(model_dir, "model.onnx")
        if not os.path.exists(model_onnx):
            raise FileNotFoundError(f"model.onnx not found: {model_onnx}")

        # 优先从 model_dir 加载 tokenizer（ONNX 目录包含所有文件）
        # 如果不存在，fallback 到上级目录
        tokenizer_dir = model_dir
        if not os.path.exists(os.path.join(tokenizer_dir, "tokenizer_config.json")):
            tokenizer_dir = os.path.dirname(model_dir)
            logger.info(f"tokenizer_config.json not in {model_dir}, using parent: {tokenizer_dir}")

        logger.info(f"Loading tokenizer from: {tokenizer_dir}")
        tok = AutoTokenizer.from_pretrained(tokenizer_dir, trust_remote_code=True)

        # provider：默认 CPU（最稳）。你如果装了 onnxruntime-gpu，再把 CUDA 加进去
        providers = ["CPUExecutionProvider"]
        sess = ort.InferenceSession(model_onnx, providers=providers)

        input_names = {i.name for i in sess.get_inputs()}
        output_names = [o.name for o in sess.get_outputs()]

        self._tokenizer = tok
        self._ort_session = sess
        self._input_names = input_names
        self._output_names = output_names

        # 估算维度：跑一次短文本
        vec = self._embed_onnx_batch(["intelliavatar init"], normalize=True)
        self._dimension = int(vec.shape[1])

        self._model_name = f"{model_name}@onnx"
        self._use_semantic = True

        logger.info("✅ EmbeddingService initialized (ONNX backend)")
        logger.info(f"   Inputs    : {sorted(list(self._input_names))}")
        logger.info(f"   Outputs   : {self._output_names}")
        logger.info(f"   Dimension : {self._dimension}")

    # ------------------------------------------------------------------ #
    # 状态查询
    # ------------------------------------------------------------------ #
    def is_available(self) -> bool:
        return bool(self._use_semantic and self._ort_session is not None and self._tokenizer is not None)

    @property
    def model_name(self) -> Optional[str]:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension or 0

    # ------------------------------------------------------------------ #
    # 嵌入接口（单个/批量）
    # ------------------------------------------------------------------ #
    def embed_single(self, text: str, use_cache: bool = True) -> np.ndarray:
        if not self.is_available():
            logger.warning("EmbeddingService not available, using fallback")
            return self._fallback_embed(text)

        if use_cache:
            return self._embed_cached(text)

        return self._embed_uncached(text)

    @lru_cache(maxsize=2000)
    def _embed_cached(self, text: str) -> np.ndarray:
        self._cache_hits += 1
        return self._embed_uncached(text)

    def _embed_uncached(self, text: str) -> np.ndarray:
        start = time.time()
        try:
            with self._model_lock:
                vec = self._embed_onnx_batch([text], normalize=True)[0]

            elapsed = time.time() - start
            self._call_count += 1
            self._total_time += elapsed

            if self._call_count % 200 == 0:
                avg = self._total_time / max(self._call_count, 1)
                hit_rate = self._cache_hits / max(self._call_count, 1)
                logger.info(
                    f"[EmbeddingService] Stats: {self._call_count} calls, "
                    f"avg {avg*1000:.2f}ms, cache hit rate {hit_rate:.1%}"
                )

            return vec
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return self._fallback_embed(text)

    def embed_batch(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        if not self.is_available():
            logger.warning("EmbeddingService not available, using fallback")
            return np.array([self._fallback_embed(t) for t in texts], dtype=np.float32)

        if not texts:
            return np.zeros((0, self.dimension or 1), dtype=np.float32)

        start = time.time()
        try:
            all_vecs = []
            with self._model_lock:
                for i in range(0, len(texts), batch_size):
                    batch = texts[i:i + batch_size]
                    all_vecs.append(self._embed_onnx_batch(batch, normalize=True))
            vectors = np.vstack(all_vecs) if all_vecs else np.zeros((0, self.dimension), dtype=np.float32)

            elapsed = time.time() - start
            self._call_count += len(texts)
            self._total_time += elapsed
            return vectors

        except Exception as e:
            logger.error(f"Batch embedding failed: {e}")
            return np.array([self._fallback_embed(t) for t in texts], dtype=np.float32)

    # ------------------- ONNX core embedding ------------------- #
    def _embed_onnx_batch(self, texts: List[str], normalize: bool = True) -> np.ndarray:
        """
        ONNX batch embedding.
        - 只喂模型需要的输入名（避免 token_type_ids 之类 INVALID_ARGUMENT）
        - 优先使用 sentence_embedding 输出
        """
        inputs = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            return_tensors="np",
            max_length=512,
        )

        # 只喂 ONNX 需要的 input
        ort_inputs: Dict[str, np.ndarray] = {}
        for name in self._input_names:
            if name in inputs:
                ort_inputs[name] = inputs[name].astype(np.int64)

        ort_outputs = self._ort_session.run(None, ort_inputs)
        outputs = dict(zip(self._output_names, ort_outputs))

        if "sentence_embedding" in outputs:
            embeds = outputs["sentence_embedding"]
        else:
            first = ort_outputs[0]
            if first.ndim == 3:
                embeds = first[:, 0, :]
            elif first.ndim == 2:
                embeds = first
            else:
                raise RuntimeError(f"Unknown ONNX output shape: {first.shape}")

        embeds = embeds.astype(np.float32)

        if normalize:
            norms = np.linalg.norm(embeds, axis=1, keepdims=True)
            norms = np.clip(norms, 1e-12, None)
            embeds = embeds / norms

        return embeds

    # ------------------------------------------------------------------ #
    # 相似度 & 检索
    # ------------------------------------------------------------------ #
    def similarity(self, text1: str, text2: str, method: str = "cosine") -> float:
        vec1 = self.embed_single(text1)
        vec2 = self.embed_single(text2)

        if method == "cosine":
            return SemanticSimilarity.cosine_similarity(vec1, vec2)
        if method == "euclidean":
            dist = SemanticSimilarity.euclidean_distance(vec1, vec2)
            return 1.0 / (1.0 + dist)
        if method == "dot":
            return SemanticSimilarity.dot_product_similarity(vec1, vec2)

        raise ValueError(f"Unknown similarity method: {method}")

    def find_most_similar(
        self,
        query: str,
        candidates: List[str],
        threshold: float = 0.0
    ) -> Optional[SemanticMatch]:
        if not candidates:
            return None

        q = self.embed_single(query)
        c = self.embed_batch(candidates)

        idx, score = SemanticSimilarity.find_most_similar(q, c)
        if score < threshold:
            return None

        return SemanticMatch(query=query, matched_text=candidates[idx], score=score, rank=1)

    def rank_by_similarity(
        self,
        query: str,
        candidates: List[str],
        top_k: int = 5,
        threshold: float = 0.0
    ) -> List[SemanticMatch]:
        if not candidates:
            return []

        q = self.embed_single(query)
        c = self.embed_batch(candidates)

        ranked = SemanticSimilarity.rank_by_similarity(q, c, top_k=top_k)

        results: List[SemanticMatch] = []
        for rank, (idx, score) in enumerate(ranked, start=1):
            if score < threshold:
                continue
            results.append(SemanticMatch(query=query, matched_text=candidates[idx], score=score, rank=rank))
        return results

    # ------------------------------------------------------------------ #
    # 降级 & 统计
    # ------------------------------------------------------------------ #
    def _fallback_embed(self, text: str) -> np.ndarray:
        """
        降级方案：简单哈希向量（固定 16 维）
        注意：仅用于“系统还能跑”，不保证语义质量。
        """
        import hashlib
        h = hashlib.md5(text.encode("utf-8")).digest()
        vec = np.frombuffer(h, dtype=np.uint8).astype(np.float32)
        norm = np.linalg.norm(vec)
        return vec / (norm if norm > 0 else 1.0)

    def get_stats(self) -> dict:
        if self._call_count == 0:
            avg_time = 0.0
            cache_rate = 0.0
        else:
            avg_time = self._total_time / self._call_count
            cache_rate = self._cache_hits / self._call_count

        return {
            "available": self.is_available(),
            "model_name": self._model_name,
            "dimension": self.dimension,
            "total_calls": self._call_count,
            "cache_hits": self._cache_hits,
            "cache_hit_rate": cache_rate,
            "avg_time_ms": avg_time * 1000,
        }

    def clear_cache(self) -> None:
        self._embed_cached.cache_clear()
        self._cache_hits = 0
        logger.info("Embedding cache cleared")


# ---------------------------------------------------------------------- #
# 全局单例访问
# ---------------------------------------------------------------------- #
_global_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    global _global_service
    if _global_service is None:
        _global_service = EmbeddingService()
    return _global_service
