"""
CapabilityClassifier — side_effects-based semantic index.

Maps natural language intent to SideEffect values using embedding centroids
derived from skill descriptions grouped by their declared side_effects.
"""

import logging
from typing import Dict, Set, List, Optional
import numpy as np

from app.avatar.skills.base import SideEffect
from app.avatar.skills.registry import skill_registry
from app.avatar.infra.semantic.service import get_embedding_service
from app.avatar.infra.semantic.similarity import SemanticSimilarity

logger = logging.getLogger(__name__)


class CapabilityClassifier:
    """
    Classifies intent text into a set of SideEffect values.

    Warmup builds one embedding centroid per SideEffect by averaging
    the descriptions of all skills that declare that side_effect.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.service = get_embedding_service()
        self.vectors: Dict[str, np.ndarray] = {}   # side_effect.value -> centroid
        self._warmed_up = False
        self._initialized = True

    def warmup(self):
        if self._warmed_up:
            return

        if not self.service.is_available():
            logger.warning("CapabilityClassifier: embedding service unavailable, skipping warmup")
            self._warmed_up = True
            return

        logger.info("CapabilityClassifier: warming up from skill registry...")

        # Group skill descriptions by side_effect
        effect_texts: Dict[str, List[str]] = {}
        for spec in skill_registry.list_specs():
            desc = (spec.description or "").strip()
            if not desc:
                continue
            for effect in spec.side_effects:
                key = effect.value if isinstance(effect, SideEffect) else str(effect)
                effect_texts.setdefault(key, []).append(desc)

        if not effect_texts:
            logger.warning("CapabilityClassifier: no side_effects found in registry, warmup is a no-op")
            self._warmed_up = True
            return

        valid = 0
        for key, texts in effect_texts.items():
            try:
                vecs = self.service.embed_batch(texts)
                if len(vecs) == 0:
                    continue
                centroid = np.mean(vecs, axis=0)
                norm = np.linalg.norm(centroid)
                if norm > 0:
                    centroid = centroid / norm
                self.vectors[key] = centroid
                valid += 1
            except Exception as e:
                logger.error(f"CapabilityClassifier: failed centroid for '{key}': {e}")

        self._warmed_up = True
        logger.info(f"CapabilityClassifier: warmed up with {valid} side_effect centroids")

    def classify(self, text: str, threshold: float = 0.45) -> Set[str]:
        """
        Returns a set of SideEffect value strings matching the given text.
        Returns empty set if classifier is not warmed up or no match above threshold.
        """
        if not self.vectors:
            return set()

        try:
            query_vec = self.service.embed_single(text)
        except Exception as e:
            logger.error(f"CapabilityClassifier.classify failed: {e}")
            return set()

        scores = [
            (key, SemanticSimilarity.cosine_similarity(query_vec, vec))
            for key, vec in self.vectors.items()
        ]
        scores.sort(key=lambda x: x[1], reverse=True)

        if not scores or scores[0][1] < threshold:
            return set()

        best_score = scores[0][1]
        matched = {key for key, score in scores if score >= threshold and (best_score - score) < 0.15}
        return matched


def get_capability_classifier() -> CapabilityClassifier:
    return CapabilityClassifier()
