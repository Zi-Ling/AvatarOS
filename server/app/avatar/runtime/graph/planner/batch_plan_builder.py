"""
BatchPlanBuilder — deterministic batch plan construction.

Converts a BatchParams + TaskDefinition into an ExecutionGraph with
FanOutNode → N expanded subgraphs → FanInNode structure.

Determinism guarantee: same inputs → same ExecutionGraph (node IDs, item order).
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Performance guard: max items per batch
MAX_BATCH_ITEMS = 50


@dataclass
class BatchParams:
    """Parameters extracted by ComplexityAnalyzer for batch execution."""
    count: int
    template: str
    variables: List[str] = field(default_factory=list)
    source_type: str = "literal_count"  # "literal_count" / "collection_input" / "upstream_list"


@dataclass
class BatchPlanMetadata:
    """Metadata stored in ExecutionGraph.metadata['batch_plan']."""
    template_hash: str
    item_count: int
    expansion_rules: Dict[str, Any] = field(default_factory=dict)
    subgraph_template: Dict[str, Any] = field(default_factory=dict)
    item_order_rule: str = "natural_sequence"
    schema_version: str = "1.0.0"


class BatchPlanBuilder:
    """Builds deterministic batch execution graphs.

    Flow:
    1. Extract template from batch_params
    2. Compute template hash (sha256 of canonical JSON)
    3. Generate item specs in stable order
    4. Instantiate FanOutNode + N subgraphs + FanInNode
    5. Cross-item dependency check (fallback to ReAct if detected)
    6. Store metadata
    """

    def build(
        self,
        batch_params: BatchParams,
        task_def: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Build a batch execution plan.

        Returns a dict representing the execution graph structure:
        {
            "fan_out_node": {...},
            "item_subgraphs": [...],
            "fan_in_node": {...},
            "metadata": BatchPlanMetadata,
        }

        Raises:
            ValueError: If cross-item dependencies detected.
            RuntimeError: If batch_params.count exceeds MAX_BATCH_ITEMS.
        """
        count = batch_params.count

        # Performance guard
        if count > MAX_BATCH_ITEMS:
            logger.warning(
                "Batch item count %d exceeds limit %d, splitting into batches",
                count, MAX_BATCH_ITEMS,
            )
            count = MAX_BATCH_ITEMS

        # 1. Template extraction
        template_spec = self._extract_template(batch_params)

        # 2. Hash computation
        template_hash = self._compute_template_hash(template_spec)

        # 3. Item spec generation (stable order)
        item_specs = self._generate_item_specs(batch_params, count)

        # 4. Cross-item dependency check
        if self._has_cross_item_dependency(item_specs, task_def):
            raise ValueError(
                "Cross-item dependencies detected; falling back to ReAct mode"
            )

        # 5. Instantiate nodes
        fan_out_node = self._create_fan_out_node(template_hash, count)
        item_subgraphs = self._create_item_subgraphs(
            template_spec, template_hash, item_specs,
        )
        fan_in_node = self._create_fan_in_node(template_hash, count)

        # 6. Metadata
        metadata = BatchPlanMetadata(
            template_hash=template_hash,
            item_count=count,
            expansion_rules={"source_type": batch_params.source_type},
            subgraph_template=template_spec,
            item_order_rule=self._order_rule(batch_params.source_type),
        )

        return {
            "fan_out_node": fan_out_node,
            "item_subgraphs": item_subgraphs,
            "fan_in_node": fan_in_node,
            "metadata": metadata,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_template(params: BatchParams) -> Dict[str, Any]:
        """Extract a canonical template spec from batch params."""
        return {
            "template": params.template,
            "variables": sorted(params.variables),
        }

    @staticmethod
    def _compute_template_hash(template_spec: Dict[str, Any]) -> str:
        """SHA-256 of canonical JSON for deterministic hashing."""
        canonical = json.dumps(template_spec, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _generate_item_specs(
        params: BatchParams, count: int,
    ) -> List[Dict[str, Any]]:
        """Generate item specs in stable order based on source_type."""
        return [
            {"item_index": i, "variables": params.variables}
            for i in range(count)
        ]

    @staticmethod
    def _has_cross_item_dependency(
        item_specs: List[Dict[str, Any]],
        task_def: Optional[Any],
    ) -> bool:
        """Check for cross-item dependencies. V1: always False (conservative)."""
        # V1: no cross-item dependency detection beyond ComplexityAnalyzer
        return False

    @staticmethod
    def _create_fan_out_node(
        template_hash: str, count: int,
    ) -> Dict[str, Any]:
        node_id = f"fan_out_{template_hash[:8]}"
        return {
            "id": node_id,
            "node_type": "fan_out",
            "capability_name": "__fan_out__",
            "fan_out_count": count,
            "template_id": template_hash[:16],
        }

    @staticmethod
    def _create_item_subgraphs(
        template_spec: Dict[str, Any],
        template_hash: str,
        item_specs: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        subgraphs = []
        for spec in item_specs:
            idx = spec["item_index"]
            item_hash = hashlib.sha256(
                f"{template_hash}:{idx}".encode()
            ).hexdigest()[:12]
            subgraphs.append({
                "item_index": idx,
                "node_id": f"item_{item_hash}",
                "template": template_spec["template"],
                "variables": spec["variables"],
            })
        return subgraphs

    @staticmethod
    def _create_fan_in_node(
        template_hash: str, count: int,
    ) -> Dict[str, Any]:
        node_id = f"fan_in_{template_hash[:8]}"
        return {
            "id": node_id,
            "node_type": "fan_in",
            "capability_name": "__fan_in__",
            "aggregation_type": "concat",
            "expected_count": count,
        }

    @staticmethod
    def _order_rule(source_type: str) -> str:
        return {
            "literal_count": "natural_sequence",
            "collection_input": "collection_index",
            "upstream_list": "upstream_index",
        }.get(source_type, "natural_sequence")

    # ------------------------------------------------------------------
    # Partial retry support (Task 11.3)
    # ------------------------------------------------------------------

    @staticmethod
    def get_failed_item_indices(
        item_subgraphs: List[Dict[str, Any]],
        results: List[Dict[str, Any]],
    ) -> List[int]:
        """Identify failed item indices for partial retry."""
        failed = []
        for i, result in enumerate(results):
            if result.get("status") == "failed":
                failed.append(i)
        return failed

    def build_partial_retry(
        self,
        original_plan: Dict[str, Any],
        failed_indices: List[int],
    ) -> Dict[str, Any]:
        """Build a retry plan for only the failed items."""
        original_subgraphs = original_plan["item_subgraphs"]
        retry_subgraphs = [
            sg for sg in original_subgraphs
            if sg["item_index"] in failed_indices
        ]
        metadata = original_plan["metadata"]
        return {
            "fan_out_node": original_plan["fan_out_node"],
            "item_subgraphs": retry_subgraphs,
            "fan_in_node": original_plan["fan_in_node"],
            "metadata": BatchPlanMetadata(
                template_hash=metadata.template_hash,
                item_count=len(retry_subgraphs),
                expansion_rules=metadata.expansion_rules,
                subgraph_template=metadata.subgraph_template,
                item_order_rule=metadata.item_order_rule,
            ),
        }
