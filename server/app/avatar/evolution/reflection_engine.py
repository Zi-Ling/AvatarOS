"""
reflection_engine.py — 结构化反思引擎

从 ExecutionTrace 中提取根因模式，输出固定 schema 的 ReflectionOutput。
优先使用小模型，confidence 低于阈值时升级到大模型。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, List, Optional

from app.avatar.evolution.config import EvolutionConfig
from app.avatar.evolution.models import (
    CandidateRule,
    CandidateType,
    EvidenceLink,
    ExecutionTrace,
    OutcomeStatus,
    PatternType,
    ReflectionOutput,
)

logger = logging.getLogger(__name__)


class ReflectionEngine:
    """
    结构化反思引擎。
    优先使用小模型执行反思，confidence 低于阈值时升级到大模型。
    仅输出固定 schema 的结构化数据。
    """

    def __init__(
        self,
        llm_factory: Any = None,
        config: Optional[EvolutionConfig] = None,
    ) -> None:
        self._llm_factory = llm_factory
        self._config = config or EvolutionConfig()

    async def reflect(
        self,
        trace: ExecutionTrace,
    ) -> ReflectionOutput:
        """
        从 ExecutionTrace 提取根因模式。
        输出固定 schema 的 ReflectionOutput。
        """
        # 先用小模型
        result = await self._reflect_with_model(trace, model_tier="small")

        # confidence 低于阈值时升级到大模型
        if result.confidence < self._config.small_model_confidence_threshold:
            logger.info(
                f"[ReflectionEngine] small model confidence={result.confidence:.2f} "
                f"< threshold={self._config.small_model_confidence_threshold}, upgrading to large"
            )
            result = await self._reflect_with_model(trace, model_tier="large")

        return result

    async def _reflect_with_model(
        self,
        trace: ExecutionTrace,
        model_tier: str,
    ) -> ReflectionOutput:
        """使用指定模型层级执行反思。"""
        # 确定 pattern_type
        pattern_type = PatternType.SUCCESS_PATTERN
        if trace.outcome and trace.outcome.status in (OutcomeStatus.FAILED, OutcomeStatus.PARTIAL):
            pattern_type = PatternType.FAILURE_PATTERN

        # 构建 evidence_links
        evidence_links = self._build_evidence_links(trace)

        # 尝试通过 LLM 提取根因
        root_cause = "inconclusive"
        transferable_pattern = ""
        confidence = 0.0
        candidate_rules: List[CandidateRule] = []

        if self._llm_factory:
            try:
                llm_result = await self._call_llm(trace, model_tier)
                root_cause = llm_result.get("root_cause", "inconclusive")
                transferable_pattern = llm_result.get("transferable_pattern", "")
                confidence = float(llm_result.get("confidence", 0.0))
                candidate_rules = self._parse_candidate_rules(llm_result.get("candidate_rules", []))
            except Exception as exc:
                logger.warning(f"[ReflectionEngine] LLM call failed ({model_tier}): {exc}")
                confidence = 0.0
                root_cause = "inconclusive"
        else:
            # 无 LLM 时使用规则提取
            root_cause, transferable_pattern, confidence, candidate_rules = (
                self._rule_based_reflect(trace, pattern_type)
            )

        # 无法确定根因时 confidence 设为 low
        if root_cause == "inconclusive":
            confidence = min(confidence, 0.1)

        return ReflectionOutput(
            reflection_id=str(uuid.uuid4()),
            trace_id=trace.trace_id,
            root_cause=root_cause,
            pattern_type=pattern_type,
            transferable_pattern=transferable_pattern,
            evidence_links=evidence_links,
            candidate_rules=candidate_rules,
            confidence=confidence,
        )

    def _build_evidence_links(self, trace: ExecutionTrace) -> List[EvidenceLink]:
        """从 trace 构建结构化证据引用。"""
        links = [EvidenceLink(trace_id=trace.trace_id, description="source trace")]
        # 添加失败步骤的引用
        for step in trace.steps:
            if step.status == "failed":
                links.append(EvidenceLink(
                    trace_id=trace.trace_id,
                    step_id=step.step_id,
                    description=f"failed step: {step.skill_name}",
                ))
        # 添加 artifact 引用
        for artifact in trace.artifacts:
            links.append(EvidenceLink(
                trace_id=trace.trace_id,
                artifact_id=artifact.artifact_id,
                description=f"artifact: {artifact.artifact_type}",
            ))
        return links

    def _rule_based_reflect(
        self,
        trace: ExecutionTrace,
        pattern_type: PatternType,
    ) -> tuple:
        """规则提取（无 LLM 时的降级方案）。"""
        root_cause = "inconclusive"
        transferable_pattern = ""
        confidence = 0.3
        candidate_rules: List[CandidateRule] = []

        failed_steps = [s for s in trace.steps if s.status == "failed"]

        if pattern_type == PatternType.FAILURE_PATTERN and failed_steps:
            # 分析失败步骤
            step = failed_steps[0]
            if step.error:
                root_cause = f"step_failure: {step.skill_name}: {step.error[:200]}"
                transferable_pattern = f"avoid {step.skill_name} when error pattern matches"
                confidence = 0.4
                candidate_rules.append(CandidateRule(
                    type=CandidateType.PLANNER_RULE,
                    scope=step.skill_name,
                    content={"before_value": None, "after_value": f"caution: {step.error[:100]}"},
                    confidence=confidence,
                    rationale=root_cause,
                ))
        elif pattern_type == PatternType.SUCCESS_PATTERN and trace.steps:
            root_cause = "successful_execution"
            skill_sequence = [s.skill_name for s in trace.steps]
            transferable_pattern = f"skill_sequence: {' -> '.join(skill_sequence)}"
            confidence = 0.5

        return root_cause, transferable_pattern, confidence, candidate_rules

    async def _call_llm(self, trace: ExecutionTrace, model_tier: str) -> dict:
        """
        Call LLM for structured reflection.

        Builds a prompt from the ExecutionTrace, calls BaseLLMClient.call()
        with a JSON schema constraint, and parses the structured response.

        BaseLLMClient.call() is synchronous — we use asyncio.to_thread to
        avoid blocking the event loop. Note: to_thread cannot truly cancel
        the underlying blocking call, but it prevents the event loop from
        stalling while the LLM request is in flight.
        """
        import asyncio
        import json as _json

        prompt = self._build_reflection_prompt(trace, model_tier)

        json_schema = {
            "type": "object",
            "properties": {
                "root_cause": {"type": "string"},
                "transferable_pattern": {"type": "string"},
                "confidence": {"type": "number"},
                "candidate_rules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "scope": {"type": "string"},
                            "content": {"type": "object"},
                            "confidence": {"type": "number"},
                            "rationale": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["root_cause", "confidence"],
        }

        # Offload synchronous LLM call to thread pool to avoid blocking
        # the async event loop. We use a lambda to preserve the keyword
        # argument signature (json_schema=...) that BaseLLMClient.call expects.
        # The default thread pool size limits concurrency naturally; for
        # heavier loads a dedicated ThreadPoolExecutor with explicit
        # max_workers is recommended.
        raw_response = await asyncio.to_thread(
            lambda: self._llm_factory.call(prompt, json_schema=json_schema)
        )

        try:
            result = _json.loads(raw_response)
        except (_json.JSONDecodeError, TypeError):
            # LLM returned non-JSON — treat as inconclusive
            logger.warning(
                f"[ReflectionEngine] LLM returned non-JSON ({model_tier}), "
                f"falling back to inconclusive"
            )
            result = {"root_cause": "inconclusive", "confidence": 0.0}

        return result

    def _build_reflection_prompt(self, trace: ExecutionTrace, model_tier: str) -> str:
        """Build a structured reflection prompt from an ExecutionTrace."""
        import json as _json

        # Outcome summary
        outcome_str = "unknown"
        failure_cat = ""
        if trace.outcome:
            outcome_str = trace.outcome.status.value
            if trace.outcome.failure_category:
                failure_cat = trace.outcome.failure_category.value

        # Step summaries (compact)
        step_lines = []
        for s in trace.steps[:20]:  # cap at 20 steps to avoid token explosion
            line = f"  - [{s.status}] {s.skill_name}"
            if s.error:
                line += f" error={s.error[:120]}"
            step_lines.append(line)
        steps_block = "\n".join(step_lines) if step_lines else "  (no steps)"

        # Cost summary
        cost_str = ""
        if trace.cost_telemetry:
            ct = trace.cost_telemetry
            cost_str = (
                f"tokens={ct.total_tokens}, time={ct.total_time_ms}ms, "
                f"steps={ct.total_steps}, retries={ct.retry_count}"
            )

        prompt = (
            "You are a structured reflection engine for an autonomous agent runtime.\n"
            "Analyze the following task execution trace and extract the root cause pattern.\n"
            "Output ONLY valid JSON matching the schema.\n\n"
            f"Task: {trace.goal}\n"
            f"Task Type: {trace.task_type}\n"
            f"Outcome: {outcome_str}\n"
        )
        if failure_cat:
            prompt += f"Failure Category: {failure_cat}\n"
        if cost_str:
            prompt += f"Cost: {cost_str}\n"
        prompt += (
            f"\nExecution Steps:\n{steps_block}\n\n"
            "Instructions:\n"
            "1. Identify the root cause (or 'inconclusive' if unclear)\n"
            "2. Extract a transferable pattern that can prevent similar issues\n"
            "3. Set confidence between 0.0 and 1.0\n"
            "4. Optionally propose candidate_rules (type: planner_rule|policy_hint|"
            "skill_score|workflow_template|memory_fact)\n"
        )
        if model_tier == "large":
            prompt += "\nNote: This is a second-pass analysis with a larger model. Be thorough.\n"

        return prompt

    def _parse_candidate_rules(self, raw_rules: List[dict]) -> List[CandidateRule]:
        """解析 LLM 输出的候选规则。"""
        rules = []
        for raw in raw_rules:
            try:
                # LLM 可能返回 content 为字符串而非 dict，做防御性转换
                content = raw.get("content", {})
                if not isinstance(content, dict):
                    content = {"after_value": str(content)}
                rules.append(CandidateRule(
                    type=CandidateType(raw.get("type", "planner_rule")),
                    scope=raw.get("scope", ""),
                    content=content,
                    confidence=float(raw.get("confidence", 0.0)),
                    rationale=raw.get("rationale", ""),
                ))
            except (ValueError, KeyError) as exc:
                logger.warning(f"[ReflectionEngine] skip invalid candidate rule: {exc}")
        return rules
