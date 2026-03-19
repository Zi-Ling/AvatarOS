from __future__ import annotations

"""LoopDetector — detects repetitive plan→execute→fail→replan cycles.

3 consecutive cycles with patch similarity > 90% (based on capability_name +
params structural comparison) → LOOP_ALERT.

Requirements: 9.3, 9.4
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from ..kernel.monitor_context import MonitorContext
from ..kernel.signals import RuntimeSignal, SignalType

logger = logging.getLogger(__name__)

# Default number of consecutive similar patches to trigger a loop alert.
DEFAULT_LOOP_THRESHOLD = 3
# Default similarity ratio above which patches are considered "the same".
DEFAULT_SIMILARITY_THRESHOLD = 0.90


@dataclass
class PatchRecord:
    """Lightweight record of a plan patch for similarity comparison."""

    capability_name: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_name": self.capability_name,
            "params": dict(self.params),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PatchRecord:
        return cls(
            capability_name=data.get("capability_name", ""),
            params=dict(data.get("params") or {}),
        )


def _flatten_dict(d: dict[str, Any], prefix: str = "") -> set[str]:
    """Flatten a nested dict into a set of 'key=value' strings for comparison."""
    items: set[str] = set()
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            items.update(_flatten_dict(v, full_key))
        else:
            items.add(f"{full_key}={v!r}")
    return items


def compute_patch_similarity(a: PatchRecord, b: PatchRecord) -> float:
    """Compute structural similarity between two patch records.

    Similarity is based on capability_name match and Jaccard similarity
    of flattened params key-value pairs.  Returns a float in [0.0, 1.0].
    """
    if a.capability_name != b.capability_name:
        return 0.0

    set_a = _flatten_dict(a.params)
    set_b = _flatten_dict(b.params)

    if not set_a and not set_b:
        # Both empty params with same capability → identical.
        return 1.0

    union = set_a | set_b
    if not union:
        return 1.0

    intersection = set_a & set_b
    return len(intersection) / len(union)


class LoopDetector:
    """Detects repetitive plan→execute→fail→replan loops.

    When ``loop_threshold`` consecutive patches have pairwise similarity
    above ``similarity_threshold``, a ``LOOP_ALERT`` signal is emitted.
    """

    def __init__(
        self,
        loop_threshold: int = DEFAULT_LOOP_THRESHOLD,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> None:
        self._loop_threshold = max(2, loop_threshold)
        self._similarity_threshold = similarity_threshold
        # Per-task patch history
        self._history: dict[str, list[PatchRecord]] = {}

    @property
    def loop_threshold(self) -> int:
        return self._loop_threshold

    @property
    def similarity_threshold(self) -> float:
        return self._similarity_threshold

    def record_patch(self, task_id: str, patch: PatchRecord) -> None:
        """Record a new patch for the given task."""
        history = self._history.setdefault(task_id, [])
        history.append(patch)
        # Keep only the most recent patches needed for detection.
        max_keep = self._loop_threshold + 1
        if len(history) > max_keep:
            self._history[task_id] = history[-max_keep:]

    def check(self, ctx: MonitorContext) -> list[RuntimeSignal]:
        """Check recent patches from MonitorContext and detect loops.

        Patches are extracted from ``ctx.recent_patches`` (list of dicts
        with ``capability_name`` and ``params``).  If the last
        ``loop_threshold`` patches are all pairwise similar above
        ``similarity_threshold``, a LOOP_ALERT is emitted.
        """
        # Ingest any new patches from context.
        for raw_patch in ctx.recent_patches:
            record = PatchRecord.from_dict(raw_patch)
            self.record_patch(ctx.task_id, record)

        return self._evaluate(ctx.task_id)

    def _evaluate(self, task_id: str) -> list[RuntimeSignal]:
        history = self._history.get(task_id, [])
        if len(history) < self._loop_threshold:
            return []

        recent = history[-self._loop_threshold:]

        # Check all consecutive pairs for similarity.
        all_similar = True
        for i in range(len(recent) - 1):
            sim = compute_patch_similarity(recent[i], recent[i + 1])
            if sim < self._similarity_threshold:
                all_similar = False
                break

        if not all_similar:
            return []

        signal = RuntimeSignal(
            signal_type=SignalType.LOOP_ALERT,
            source_subsystem="LoopDetector",
            target_task_id=task_id,
            priority=4,
            reason=(
                f"Detected {self._loop_threshold} consecutive similar patches "
                f"(similarity > {self._similarity_threshold:.0%})"
            ),
            metadata={
                "loop_threshold": self._loop_threshold,
                "similarity_threshold": self._similarity_threshold,
                "recent_patches": [p.to_dict() for p in recent],
            },
        )
        logger.warning(
            "[LoopDetector] task=%s loop detected (%d similar patches)",
            task_id,
            self._loop_threshold,
        )
        return [signal]

    def reset(self, task_id: str) -> None:
        """Reset patch history for a task."""
        self._history.pop(task_id, None)
