"""
RepairLoop — structured repair feedback after verification failure.

Strategy selection:
  1. rerun_last_step  — file missing, re-run producer step
  2. patch_file       — file exists but format error, patch only
  3. full_retry       — multi-step failure or local repair exhausted

Integrates with RepairState from core.context and ArtifactRegistry (P0).
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.avatar.runtime.verification.models import (
    FailureCategory,
    RepairFeedback,
    StructuredFailureAttribution,
    VerificationResult,
    VerificationStatus,
)

if TYPE_CHECKING:
    from app.avatar.runtime.core.context import RepairState
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.storage.step_trace_store import StepTraceStore
    from app.avatar.runtime.artifact.registry import ArtifactRegistry

logger = logging.getLogger(__name__)


class RepairLoop:
    """
    Generates structured RepairFeedback from failed VerificationResults.

    Usage:
        loop = RepairLoop(trace_store, max_repair_attempts=3)
        feedback = loop.trigger_repair(failed_results, graph, repair_state, session_id)
    """

    def __init__(
        self,
        trace_store: "StepTraceStore",
        max_repair_attempts: int = 3,
        artifact_registry: Optional["ArtifactRegistry"] = None,
        repair_policy: Optional[Any] = None,
        idempotency_store: Optional[Any] = None,
    ) -> None:
        self._trace_store = trace_store
        self.max_repair_attempts = max_repair_attempts
        self._artifact_registry = artifact_registry
        self._repair_policy = repair_policy
        self._idempotency_store = idempotency_store

    def trigger_repair(
        self,
        failed_results: List[VerificationResult],
        graph: "ExecutionGraph",
        repair_state: "RepairState",
        session_id: str,
    ) -> RepairFeedback:
        """
        Analyze failures and produce RepairFeedback.

        Side effects:
        - Updates repair_state.is_repairing, current_attempt, repair_history
        - Writes "repair_triggered" event to StepTraceStore
        """
        # ── Verifier mismatch detection ─────────────────────────────────
        # If the verifier type doesn't match the target file extension,
        # repairing the file content is futile. Short-circuit immediately.
        mismatch_detected = self._detect_verifier_mismatch(failed_results)
        if mismatch_detected:
            logger.warning(
                f"[RepairLoop] Verifier mismatch detected: {mismatch_detected}. "
                f"Skipping repair — the verification plan is wrong, not the file."
            )
            attributions = self._build_attributions(failed_results, [])
            for attr in attributions:
                attr.strategy_exhausted = True
            feedback = RepairFeedback(
                failed_verifications=failed_results,
                repair_hints=[
                    f"Verifier mismatch: {mismatch_detected}. "
                    f"The file content is likely correct but the wrong verifier was applied. "
                    f"Do NOT modify the file. Re-evaluate the goal and select appropriate verifiers.",
                ],
                suggested_strategy="full_retry",
                attributions=attributions,
                affected_step_ids=[],
                producer_step_ids=[],
                context_patch={"repair_exhausted": True, "verifier_mismatch": True},
            )
            self._write_repair_event(session_id, feedback)
            return feedback

        strategy = self._select_strategy(failed_results, repair_state)
        producer_step_ids = self._locate_producers(failed_results, graph)
        repair_hints = self._build_hints(failed_results, strategy)
        attributions = self._build_attributions(failed_results, producer_step_ids)

        context_patch: Dict[str, Any] = {}
        strategy_exhausted = repair_state.current_attempt >= self.max_repair_attempts

        # P1: Idempotency check — skip if same key already executed
        if self._idempotency_store and not strategy_exhausted:
            from app.avatar.runtime.verification.repair_policy import IdempotencyKey
            target_path = next(
                (r.target.path for r in failed_results if r.target.path), None
            )
            idem_key = IdempotencyKey.from_repair_context(
                skill_name=producer_step_ids[0] if producer_step_ids else "unknown",
                params={},
                target_path=target_path,
                task_id=session_id,
                attempt_number=repair_state.current_attempt + 1,
            )
            if self._idempotency_store.has_executed(idem_key):
                prev = self._idempotency_store.get_result(idem_key)
                logger.info(
                    f"[RepairLoop] Skipping idempotent repair (key={idem_key.compute()})"
                )
                # Upgrade strategy if filesystem state unchanged
                strategy = "patch_file" if strategy == "rerun_last_step" else strategy

        if strategy_exhausted:
            context_patch["repair_exhausted"] = True
            strategy = "full_retry"
            # Mark all attributions as strategy_exhausted
            for attr in attributions:
                attr.strategy_exhausted = True
            logger.warning(
                f"[RepairLoop] Max repair attempts ({self.max_repair_attempts}) reached"
            )
        else:
            repair_state.current_attempt += 1
            repair_state.is_repairing = True
            repair_state.last_repair_at = time.time()

            from app.avatar.runtime.core.context import RepairAttempt
            attempt = RepairAttempt(
                attempt_number=repair_state.current_attempt,
                timestamp=time.time(),
                patch_type="verification_repair",
                patch_data={"strategy": strategy, "failed_count": len(failed_results)},
                result="pending",
            )
            repair_state.repair_history.append(attempt)

        # Build context_patch based on strategy
        if strategy == "rerun_last_step" and producer_step_ids:
            context_patch["producer_step_id"] = producer_step_ids[0]
        elif strategy == "patch_file":
            for result in failed_results:
                if result.target.path:
                    context_patch["target_path"] = result.target.path
                    context_patch["expected_format"] = result.target.mime_type or "unknown"
                    break

        feedback = RepairFeedback(
            failed_verifications=failed_results,
            repair_hints=repair_hints,
            suggested_strategy=strategy,
            attributions=attributions,
            affected_step_ids=list({r.target.producer_step_id for r in failed_results if r.target.producer_step_id}),
            producer_step_ids=producer_step_ids,
            context_patch=context_patch,
        )

        self._write_repair_event(session_id, feedback)
        return feedback

    # ------------------------------------------------------------------
    # Verifier mismatch detection
    # ------------------------------------------------------------------

    # Map of verifier condition types to the file extensions they are valid for
    _VERIFIER_VALID_EXTENSIONS: Dict[str, set] = {
        "json_parseable": {".json"},
        "csv_has_data": {".csv", ".tsv"},
        "image_openable": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"},
    }

    def _detect_verifier_mismatch(
        self, failed_results: List[VerificationResult]
    ) -> Optional[str]:
        """
        Check if any failed verifier is fundamentally incompatible with the
        target file extension. Returns a human-readable mismatch description
        or None if no mismatch detected.
        """
        import re as _re

        def _to_snake(name: str) -> str:
            """Convert CamelCase verifier name to snake_case for matching."""
            s = _re.sub(r'([A-Z])', r'_\1', name).lower().strip('_')
            return s.replace('__', '_')

        for result in failed_results:
            if result.status != VerificationStatus.FAILED:
                continue
            verifier_name = (result.verifier_name or "").lower()
            # Normalize: "JsonParseableVerifier" → "json_parseable_verifier"
            verifier_snake = _to_snake(result.verifier_name or "")
            target_path = result.target.path or ""
            if not target_path:
                continue

            # Extract extension
            dot = target_path.rfind(".")
            if dot == -1:
                continue
            ext = target_path[dot:].lower().split("?")[0]

            # Check each known verifier type
            for condition_type, valid_exts in self._VERIFIER_VALID_EXTENSIONS.items():
                # Match against both raw lowercase and snake_case normalized name
                if (condition_type in verifier_name or condition_type in verifier_snake) and ext not in valid_exts:
                    return (
                        f"{condition_type} verifier applied to '{ext}' file "
                        f"({target_path}), but it only makes sense for "
                        f"{', '.join(sorted(valid_exts))}"
                    )
        return None

    # ------------------------------------------------------------------
    # Structured attribution (P0)
    # ------------------------------------------------------------------

    def _build_attributions(
        self,
        failed_results: List[VerificationResult],
        producer_step_ids: List[str],
    ) -> List[StructuredFailureAttribution]:
        """Build StructuredFailureAttribution for each failed result."""
        attributions = []
        producer_iter = iter(producer_step_ids)

        for result in failed_results:
            category = self._categorize_failure(result)
            producer_step_id = result.target.producer_step_id or next(producer_iter, None)

            # Try ArtifactRegistry lookup for producer_step_id
            if not producer_step_id and result.target.artifact_ref and self._artifact_registry:
                try:
                    artifact = self._artifact_registry.get(result.target.artifact_ref)
                    producer_step_id = artifact.producer_step
                except Exception:
                    pass

            hint = result.repair_hint or result.reason[:200] if result.reason else "unknown failure"
            attributions.append(StructuredFailureAttribution(
                failed_verifier_name=result.verifier_name,
                failure_category=category,
                repair_hint=hint,
                target_path=result.target.path,
                producer_step_id=producer_step_id,
                strategy_exhausted=False,
            ))
        return attributions

    @staticmethod
    def _categorize_failure(result: VerificationResult) -> FailureCategory:
        """Infer FailureCategory from VerificationResult reason."""
        reason = (result.reason or "").lower()
        if "not found" in reason or "no such file" in reason or "missing" in reason:
            return FailureCategory.FILE_NOT_FOUND
        if any(kw in reason for kw in ("parse", "json", "csv", "format", "invalid", "corrupt")):
            return FailureCategory.FORMAT_ERROR
        if "permission" in reason or "access denied" in reason:
            return FailureCategory.PERMISSION_DENIED
        if "timeout" in reason or "timed out" in reason:
            return FailureCategory.TIMEOUT
        if any(kw in reason for kw in ("content", "semantic", "expected", "mismatch")):
            return FailureCategory.CONTENT_INVALID
        return FailureCategory.UNKNOWN

    # ------------------------------------------------------------------
    # Strategy selection
    # ------------------------------------------------------------------

    def _select_strategy(
        self,
        failed_results: List[VerificationResult],
        repair_state: "RepairState",
    ) -> str:
        """
        Select repair strategy.
        If RepairPolicy is configured, use its strategy_sequence strictly.
        Otherwise fall back to heuristic selection.
        """
        if repair_state.current_attempt >= self.max_repair_attempts:
            return "full_retry"

        # P1: Use RepairPolicy strategy_sequence if available
        if self._repair_policy:
            strategy = self._repair_policy.get_strategy_for_attempt(
                repair_state.current_attempt + 1
            )
            return strategy.value

        # Heuristic fallback
        file_missing = any(
            r.status == VerificationStatus.FAILED and "not found" in r.reason.lower()
            for r in failed_results
        )
        if file_missing:
            return "rerun_last_step"

        format_error = any(
            r.status == VerificationStatus.FAILED and any(
                kw in r.reason.lower()
                for kw in ("parse", "json", "csv", "format", "invalid", "corrupt")
            )
            for r in failed_results
        )
        if format_error and len(failed_results) == 1:
            return "patch_file"

        return "full_retry"

    # ------------------------------------------------------------------
    # Producer step location
    # ------------------------------------------------------------------

    def _locate_producers(
        self,
        failed_results: List[VerificationResult],
        graph: "ExecutionGraph",
    ) -> List[str]:
        """
        Locate producer step IDs for failed targets.
        Priority: ArtifactRegistry lookup → target.producer_step_id → graph lookup.
        """
        producers: List[str] = []
        seen: set = set()

        for result in failed_results:
            target = result.target

            # P0: ArtifactRegistry lookup via artifact_ref
            if target.artifact_ref and self._artifact_registry:
                try:
                    artifact = self._artifact_registry.get(target.artifact_ref)
                    step_id = artifact.producer_step
                    if step_id and step_id not in seen:
                        producers.append(step_id)
                        seen.add(step_id)
                        continue
                except Exception:
                    pass

            # Direct annotation
            if target.producer_step_id and target.producer_step_id not in seen:
                producers.append(target.producer_step_id)
                seen.add(target.producer_step_id)
                continue

            # Graph lookup
            if target.path:
                step_id = self._find_producer_in_graph(target.path, graph)
                if step_id and step_id not in seen:
                    producers.append(step_id)
                    seen.add(step_id)

        return producers

    @staticmethod
    def _find_producer_in_graph(file_path: str, graph: "ExecutionGraph") -> Optional[str]:
        """
        Find the most recent succeeded node whose output_contract references file_path.

        Phase 2: enhanced lookup — also checks node outputs dict and artifact write records.
        """
        try:
            from app.avatar.runtime.graph.models.step_node import NodeStatus
            for node in reversed(list(graph.nodes.values())):
                if node.status != NodeStatus.SUCCESS:
                    continue
                contract = getattr(node, "output_contract", None) or {}

                # Check output_contract paths
                for key in ("file_path", "output_path"):
                    fp = contract.get(key)
                    if fp and str(fp) == file_path:
                        return node.id

                # Phase 2: check typed_artifacts list
                typed_artifacts = contract.get("typed_artifacts") or contract.get("artifacts") or []
                if isinstance(typed_artifacts, list):
                    for art in typed_artifacts:
                        if isinstance(art, dict):
                            art_path = art.get("path") or art.get("file_path")
                            if art_path and str(art_path) == file_path:
                                return node.id

                # Phase 2: check node.outputs dict for file paths
                outputs = getattr(node, "outputs", None) or {}
                for v in outputs.values():
                    if isinstance(v, str) and v == file_path:
                        return node.id
                    if isinstance(v, dict):
                        for vv in v.values():
                            if isinstance(vv, str) and vv == file_path:
                                return node.id
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Hint generation
    # ------------------------------------------------------------------

    @staticmethod
    def _build_hints(
        failed_results: List[VerificationResult],
        strategy: str,
    ) -> List[str]:
        hints: List[str] = []
        for r in failed_results:
            if r.repair_hint:
                hints.append(r.repair_hint)
            else:
                hints.append(
                    f"[{r.verifier_name}] {r.reason} "
                    f"(target: {r.target.path or r.target.kind})"
                )
        hints.append(f"Suggested repair strategy: {strategy}")
        return hints

    # ------------------------------------------------------------------
    # Trace
    # ------------------------------------------------------------------

    def _write_repair_event(self, session_id: str, feedback: RepairFeedback) -> None:
        try:
            self._trace_store.record_event(
                session_id=session_id,
                event_type="repair_triggered",
                payload={
                    "strategy": feedback.suggested_strategy,
                    "failed_count": len(feedback.failed_verifications),
                    "producer_step_ids": feedback.producer_step_ids,
                    "repair_exhausted": feedback.context_patch.get("repair_exhausted", False),
                    "hints": feedback.repair_hints[:5],  # cap to avoid bloat
                },
            )
        except Exception as exc:
            logger.warning(f"[RepairLoop] Failed to write repair_triggered event: {exc}")
