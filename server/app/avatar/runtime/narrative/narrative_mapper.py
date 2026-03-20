"""
Narrative_Mapper — pure stateless translator.

Translates internal execution events (step.start, step.end, etc.) into
user-facing NarrativeEventPayload objects using a three-level narrative
priority system:

  1. semantic_label  (highest — explicit human-readable label)
  2. skill_name + params_summary  (contextual description)
  3. generic template  (fallback)

The mapper maintains an event-type registry that can be extended at runtime
via ``register()``.  It never sends events — that responsibility belongs to
NarrativeManager.
"""
from __future__ import annotations

import logging
from typing import Dict

from app.avatar.runtime.narrative.models import (
    EventMapping,
    NarrativeEventPayload,
    TranslationContext,
)

logger = logging.getLogger(__name__)

# ── Maximum description length (chars). Longer text is truncated with "…" ──
_MAX_DESCRIPTION_LENGTH = 80

# ── Default mapping registry ─────────────────────────────────────────────
DEFAULT_MAPPINGS: Dict[str, EventMapping] = {
    "step.start": EventMapping(
        event_type="tool_started",
        level="major",
        phase="executing",
        status="running",
        template="正在{action_desc}",
    ),
    "step.end": EventMapping(
        event_type="tool_completed",
        level="major",
        phase="executing",
        status="completed",
        template="{action_desc}完成",
    ),
    "step.failed": EventMapping(
        event_type="tool_failed",
        level="major",
        phase="executing",
        status="failed",
        template="{action_desc}失败",
    ),
    "artifact.created": EventMapping(
        event_type="artifact_created",
        level="major",
        phase="executing",
        status="completed",
        template="已生成{artifact_label}",
    ),
    "retry.triggered": EventMapping(
        event_type="retry_triggered",
        level="minor",
        phase="retrying",
        status="retrying",
        template="遇到问题，正在重试（第 {retry_count} 次）",
    ),
    "verification.start": EventMapping(
        event_type="verification_started",
        level="major",
        phase="verifying",
        status="running",
        template="正在验证执行结果",
    ),
    "verification.pass": EventMapping(
        event_type="verification_passed",
        level="major",
        phase="verifying",
        status="completed",
        template="验证通过",
    ),
    "verification.fail": EventMapping(
        event_type="verification_failed",
        level="major",
        phase="verifying",
        status="failed",
        template="验证未通过，{reason}",
    ),
    "task.completed": EventMapping(
        event_type="task_completed",
        level="major",
        phase="completed",
        status="completed",
        template="任务完成",
    ),
    "task.failed": EventMapping(
        event_type="task_failed",
        level="major",
        phase="completed",
        status="failed",
        template="任务失败：{reason}",
    ),
    "tool.long_running": EventMapping(
        event_type="long_running_hint",
        level="minor",
        phase="executing",
        status="running",
        template="{skill_desc}仍在运行中...",
    ),
    "approval.requested": EventMapping(
        event_type="approval_requested",
        level="minor",
        phase="waiting",
        status="waiting",
        template="需要你的确认才能继续",
    ),
    "approval.responded": EventMapping(
        event_type="approval_responded",
        level="minor",
        phase="executing",
        status="running",
        template="已收到确认，继续执行",
    ),
    # Recovery events (ReAct loop)
    "recovery.truncation": EventMapping(
        event_type="recovery_truncation",
        level="minor",
        phase="executing",
        status="retrying",
        template="输出过长被截断，正在简化后重试（第 {retry_count} 次）",
    ),
    "recovery.schema": EventMapping(
        event_type="recovery_schema",
        level="minor",
        phase="executing",
        status="retrying",
        template="参数不完整，正在修正后重试（第 {retry_count} 次）",
    ),
    "recovery.dedup": EventMapping(
        event_type="recovery_dedup",
        level="minor",
        phase="executing",
        status="retrying",
        template="检测到重复步骤，正在调整策略",
    ),
    # Phase-level events (PhasedPlanner)
    "phase.start": EventMapping(
        event_type="phase_started",
        level="major",
        phase="executing",
        status="running",
        template="{semantic_label}",
    ),
    "phase.completed": EventMapping(
        event_type="phase_completed",
        level="major",
        phase="executing",
        status="completed",
        template="{semantic_label}",
    ),
    "phase.failed": EventMapping(
        event_type="phase_failed",
        level="major",
        phase="executing",
        status="failed",
        template="{semantic_label}",
    ),
}

# ── Generic fallback mapping for unregistered event types ────────────────
_GENERIC_MAPPING = EventMapping(
    event_type="progress_update",
    level="minor",
    phase="executing",
    status="running",
    template="正在处理...",
)


def _truncate(text: str, max_length: int = _MAX_DESCRIPTION_LENGTH) -> str:
    """Truncate *text* to *max_length* chars, appending '...' when trimmed."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


class NarrativeMapper:
    """Pure translator: Internal_Event + Context → NarrativeEventPayload.

    The mapper is **stateless** — it holds only the registry of event-type
    mappings and the locale string.  It never pushes events or manages
    sequences; that is NarrativeManager's job.
    """

    def __init__(self, locale: str = "zh-CN") -> None:
        self._locale = locale
        self._registry: Dict[str, EventMapping] = {}
        self._register_defaults()

    # ── public API ────────────────────────────────────────────────────────

    def register(self, internal_type: str, mapping: EventMapping) -> None:
        """Register (or override) a mapping for *internal_type* at runtime."""
        self._registry[internal_type] = mapping

    def translate(
        self,
        internal_event_type: str,
        step_id: str,
        context: TranslationContext,
    ) -> NarrativeEventPayload:
        """Translate an internal event into a user-facing payload.

        Three-level narrative priority for *description*:
          1. ``context.semantic_label`` (if provided)
          2. ``skill_name`` + ``params_summary`` (contextual)
          3. Generic template from the registry
        """
        mapping = self._registry.get(internal_event_type)

        if mapping is None:
            logger.warning(
                "NarrativeMapper: unregistered event type %r — "
                "falling back to generic template",
                internal_event_type,
            )
            mapping = _GENERIC_MAPPING

        description = self._build_description(
            internal_event_type, mapping, context,
        )

        return NarrativeEventPayload(
            event_type=mapping.event_type,
            source_event_type=internal_event_type,
            level=mapping.level,
            phase=mapping.phase,
            status=mapping.status,
            description=description,
            step_id=step_id,
            metadata=self._build_metadata(context),
        )

    # ── private helpers ───────────────────────────────────────────────────

    def _register_defaults(self) -> None:
        """Populate the registry with DEFAULT_MAPPINGS."""
        self._registry.update(DEFAULT_MAPPINGS)

    def _build_description(
        self,
        internal_event_type: str,
        mapping: EventMapping,
        ctx: TranslationContext,
    ) -> str:
        """Build the user-facing description using three-level priority."""

        # Priority 1: semantic_label
        if ctx.semantic_label:
            desc = self._apply_semantic_label(mapping, ctx)
            return _truncate(desc)

        # Priority 2: skill_name + params_summary
        if ctx.skill_name and ctx.params_summary:
            desc = self._apply_skill_context(mapping, ctx)
            return _truncate(desc)

        # Priority 3: generic template
        desc = self._apply_template(mapping, ctx)
        return _truncate(desc)

    def _apply_semantic_label(
        self, mapping: EventMapping, ctx: TranslationContext,
    ) -> str:
        """Use semantic_label to fill the template's {action_desc} slot."""
        placeholders = self._context_placeholders(ctx)
        placeholders["action_desc"] = ctx.semantic_label  # type: ignore[assignment]
        return self._safe_format(mapping.template, placeholders)

    def _apply_skill_context(
        self, mapping: EventMapping, ctx: TranslationContext,
    ) -> str:
        """Use skill_name + params_summary for a contextual description."""
        action_desc = f"调用 {ctx.skill_name}（{ctx.params_summary}）"
        placeholders = self._context_placeholders(ctx)
        placeholders["action_desc"] = action_desc
        placeholders["skill_desc"] = f"{ctx.skill_name}（{ctx.params_summary}）"
        return self._safe_format(mapping.template, placeholders)

    def _apply_template(
        self, mapping: EventMapping, ctx: TranslationContext,
    ) -> str:
        """Fill the template with whatever context is available."""
        placeholders = self._context_placeholders(ctx)
        # Provide a neutral action_desc when nothing specific is available
        placeholders.setdefault("action_desc", "处理")
        placeholders.setdefault("skill_desc", "操作")
        return self._safe_format(mapping.template, placeholders)

    @staticmethod
    def _context_placeholders(ctx: TranslationContext) -> Dict[str, str]:
        """Extract template placeholder values from *ctx*."""
        placeholders: Dict[str, str] = {}
        if ctx.artifact_label:
            placeholders["artifact_label"] = ctx.artifact_label
        else:
            placeholders["artifact_label"] = "产物"
        if ctx.retry_count is not None:
            placeholders["retry_count"] = str(ctx.retry_count)
        else:
            placeholders["retry_count"] = "?"
        if ctx.reason:
            placeholders["reason"] = ctx.reason
        elif ctx.error_message:
            placeholders["reason"] = ctx.error_message
        else:
            placeholders["reason"] = "原因未知"
        if ctx.skill_name:
            placeholders["skill_desc"] = ctx.skill_name
        return placeholders

    @staticmethod
    def _safe_format(template: str, placeholders: Dict[str, str]) -> str:
        """Format *template* with *placeholders*, ignoring missing keys."""
        try:
            return template.format(**placeholders)
        except KeyError:
            # If the template references a key we don't have, return as-is
            return template

    @staticmethod
    def _build_metadata(ctx: TranslationContext) -> dict:
        """Build lightweight metadata dict from context."""
        meta: dict = {}
        if ctx.semantic_label:
            meta["semantic_label"] = ctx.semantic_label
        if ctx.artifact_type:
            meta["artifact_type"] = ctx.artifact_type
        if ctx.artifact_label:
            meta["artifact_label"] = ctx.artifact_label
        if ctx.error_message:
            meta["error_message"] = ctx.error_message
        return meta
