"""
DedupGuard — Intent-equivalent call deduplication for graph patches.

Extracted from GraphController. Detects when Planner proposes nodes that are
semantically equivalent to already-succeeded nodes and filters them out.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, TYPE_CHECKING, Set
import logging
import re
from difflib import SequenceMatcher

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.models.graph_patch import GraphPatch

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DedupGuardConfig:
    """All tunable parameters for DedupGuard in one place."""

    # Fuzzy match similarity threshold (SequenceMatcher ratio)
    fuzzy_similarity_threshold: float = 0.92

    # Max chars for normalized param values in fingerprints
    param_value_max_chars: int = 200


class DedupGuard:
    """
    Filters out intent-equivalent ADD_NODE actions from a patch.

    Logic:
    - Builds a "call fingerprint" per node: skill + key-param digest.
    - Compares new nodes against already-succeeded nodes.
    - Exact-match mode for LLM skills (prompt hash), fuzzy for others (>= threshold).
    - Skips dedup for fs.write/copy/move/delete (always unique intent).
    - Skips dedup for nodes with incoming edges (depend on new upstream data).
    """

    def __init__(self, config: Optional[DedupGuardConfig] = None) -> None:
        self._cfg = config or DedupGuardConfig()

    # Dedup mode is now read from SkillSpec.dedup_mode at runtime.
    # No hardcoded skill name sets.

    # ── Fingerprint helpers ─────────────────────────────────────────────

    @staticmethod
    def _get_dedup_mode(skill: str) -> str:
        """Get dedup_mode from SkillSpec via registry. Default: 'fuzzy'."""
        try:
            from app.avatar.skills.registry import skill_registry
            cls = skill_registry.get(skill)
            if cls and hasattr(cls.spec, "dedup_mode"):
                return cls.spec.dedup_mode
        except Exception:
            pass
        return "fuzzy"

    def _normalize_param_value(self, v: Any) -> str:
        if v is None:
            return ""
        s = str(v).strip()
        s = re.sub(r'\s+', ' ', s)
        return s[:self._cfg.param_value_max_chars]

    @staticmethod
    def _get_skill_key_params(skill: str) -> Optional[List[str]]:
        """Dynamically fetch param names from skill registry."""
        try:
            from app.avatar.skills.registry import skill_registry
            cls = skill_registry.get(skill)
            if cls is None:
                return None
            input_model = getattr(cls.spec, "input_model", None)
            if input_model is None:
                return None
            schema = input_model.model_json_schema()
            props = schema.get("properties", {})
            required = set(schema.get("required", []))
            return sorted(props.keys(), key=lambda k: (k not in required, k))
        except Exception:
            return None

    def _node_call_fingerprint(self, skill: str, params: Dict[str, Any]) -> str:
        """Generate call fingerprint: skill + key-param digest."""
        key_params = self._get_skill_key_params(skill)
        if key_params is None:
            key_params = list(params.keys())[:2]
        parts = [skill]
        for k in key_params:
            v = params.get(k)
            if v is not None:
                dedup_mode = self._get_dedup_mode(skill)
                if dedup_mode == "exact":
                    import hashlib
                    full_val = re.sub(r'\s+', ' ', str(v).strip())
                    parts.append(f"{k}={hashlib.md5(full_val.encode()).hexdigest()}")
                else:
                    parts.append(f"{k}={self._normalize_param_value(v)}")
        return "|".join(parts)

    # ── Main API ────────────────────────────────────────────────────────

    def deduplicate_patch(
        self,
        patch: 'GraphPatch',
        graph: 'ExecutionGraph',
    ) -> Optional['GraphPatch']:
        """
        Filter out ADD_NODE actions that duplicate already-succeeded nodes.

        Returns:
        - Original or filtered patch if some nodes survive.
        - ``None`` if ALL new nodes were filtered (signals GraphController
          to give Planner a replan chance with a dedup hint, instead of
          directly terminating the task).
        """
        from app.avatar.runtime.graph.models.graph_patch import (
            PatchOperation, PatchAction, GraphPatch as GP,
        )

        # Collect succeeded fingerprints
        succeeded_fps: Set[str] = set()
        for node in graph.nodes.values():
            if node.status.value == "success":
                fp = self._node_call_fingerprint(node.capability_name, node.params or {})
                succeeded_fps.add(fp)

        if not succeeded_fps:
            return patch

        filtered_actions = []
        skipped = 0
        add_node_count = 0

        for action in patch.actions:
            if action.operation == PatchOperation.ADD_NODE and action.node:
                add_node_count += 1
                skill = action.node.capability_name
                new_params = action.node.params or {}

                # Skip dedup for write-type skills (dedup_mode == "skip")
                dedup_mode = self._get_dedup_mode(skill)
                if dedup_mode == "skip":
                    filtered_actions.append(action)
                    continue

                # Skip dedup for nodes with incoming edges
                new_node_id = action.node.id
                has_incoming = any(
                    a.operation == PatchOperation.ADD_EDGE
                    and a.edge and a.edge.target_node == new_node_id
                    for a in patch.actions
                )
                if has_incoming:
                    filtered_actions.append(action)
                    continue

                new_fp = self._node_call_fingerprint(skill, new_params)
                is_dup = self._is_duplicate(skill, new_fp, succeeded_fps)
                if is_dup:
                    skipped += 1
                    continue

            filtered_actions.append(action)

        if skipped == 0:
            return patch

        # All ADD_NODEs filtered → return None to signal replan opportunity
        if skipped >= add_node_count:
            logger.info(
                "[DedupGuard] All %d new node(s) are duplicates → requesting replan",
                add_node_count,
            )
            return None

        patch.actions = filtered_actions
        return patch

    @staticmethod
    def _extract_skill_prefix(fp: str) -> str:
        """Return the skill name portion of a fingerprint ('skill|k=v|…' → 'skill')."""
        return fp.split("|", 1)[0]

    def _is_duplicate(self, skill: str, new_fp: str, succeeded_fps: Set[str]) -> bool:
        """Check if new_fp matches any succeeded fingerprint.

        Rules:
        - dedup_mode == "exact": exact fingerprint match only.
        - Same skill name: fuzzy match (SequenceMatcher >= threshold).
        - Different skill names: NO fuzzy match — only exact fingerprint
          match.  This prevents cross-skill false positives like
          net.get vs net.download being wrongly deduped.
        """
        dedup_mode = self._get_dedup_mode(skill)
        for existing_fp in succeeded_fps:
            if dedup_mode == "exact":
                if new_fp == existing_fp:
                    logger.info(f"[DedupGuard] Exact-duplicate: skill={skill}")
                    return True
            else:
                existing_skill = self._extract_skill_prefix(existing_fp)
                if existing_skill == skill:
                    # Same skill → fuzzy match allowed
                    similarity = SequenceMatcher(None, new_fp, existing_fp).ratio()
                    if similarity >= self._cfg.fuzzy_similarity_threshold:
                        logger.info(
                            f"[DedupGuard] Intent-equivalent (same skill): skill={skill}, "
                            f"similarity={similarity:.2f}"
                        )
                        return True
                else:
                    # Different skill → exact match only
                    if new_fp == existing_fp:
                        logger.info(
                            f"[DedupGuard] Exact cross-skill duplicate: "
                            f"{skill} vs {existing_skill}"
                        )
                        return True
        return False
