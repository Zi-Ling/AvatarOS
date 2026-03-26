"""RoleRunner implementations — researcher, executor, writer.

Each RoleRunner shapes execution behavior through:
- Independent prompt template (injected as goal_tracker_hint)
- Skill whitelist (enforced via env_context._skill_hint)
- Budget multiplier
- Output format expectations

The RoleRunner does NOT execute skills directly — it configures
env_context and intent for GraphController._execute_react_mode,
which handles actual skill dispatch.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Optional

from app.avatar.runtime.multiagent.config import MultiAgentConfig

logger = logging.getLogger(__name__)


class BaseRoleRunner:
    """Base class for role-specific execution configuration.

    Subclasses override `configure()` to shape the execution context
    before it's passed to GraphController._execute_react_mode.
    """

    role_name: str = "base"

    def __init__(self, config: Optional[MultiAgentConfig] = None) -> None:
        self._cfg = config or MultiAgentConfig()

    def _build_feedback_prompt(self) -> str:
        """Build the feedback generation prompt from config template.

        Returns empty string if feedback generation is disabled.
        """
        if not self._cfg.feedback_generation_enabled:
            return ""
        return self._cfg.feedback_prompt_template.format(
            tag=self._cfg.feedback_json_tag,
        )

    def configure(
        self,
        intent: str,
        env_context: Dict[str, Any],
        subtask_spec: Dict[str, Any],
    ) -> tuple[str, Dict[str, Any]]:
        """Configure intent and env_context for this role.

        Returns (modified_intent, modified_env_context).
        Subclasses override to inject role-specific behavior.
        """
        return intent, env_context

    def get_budget_multiplier(self) -> float:
        return 1.0


class ResearcherRunner(BaseRoleRunner):
    """Researcher: information gathering, read-only tools only.

    Shapes execution by:
    - Restricting skills to read-only set
    - Injecting research-focused prompt hint
    - Requiring structured output (facts, sources, conclusion)
    - Lower budget (research should be fast)
    """

    role_name = "researcher"

    # Structured output schema for research results
    RESEARCH_OUTPUT_SCHEMA = (
        "Structure your findings as:\n"
        "- facts: key findings and data points\n"
        "- sources: URLs or references for each fact\n"
        "- constraints: limitations or caveats discovered\n"
        "- conclusion: brief synthesis of findings"
    )

    def configure(
        self,
        intent: str,
        env_context: Dict[str, Any],
        subtask_spec: Dict[str, Any],
    ) -> tuple[str, Dict[str, Any]]:
        env = {**env_context}

        # Skill whitelist
        env["_skill_hint"] = {
            "preferred": sorted(self._cfg.researcher_allowed_skills),
            "prohibited": [],
            "reason": "Researcher role: read-only tools for information gathering",
        }

        # Research-focused prompt hint + feedback protocol
        env["goal_tracker_hint"] = (
            "You are a RESEARCHER agent. Your job is to gather information, "
            "search for facts, and organize findings. "
            "You MUST NOT create files, write documents, or execute code that "
            "produces deliverables. Output your findings as structured text. "
            "Focus on: completeness of information, source reliability, "
            "and clear organization of facts.\n\n"
            + self.RESEARCH_OUTPUT_SCHEMA
            + self._build_feedback_prompt()
        )

        # Enhance intent with output expectations
        expected = subtask_spec.get("expected_output", {})
        if expected:
            intent += (
                f"\n\nExpected output: {expected.get('description', 'structured research findings')}"
                f"\nOutput type: {expected.get('type', 'text')}"
            )

        return intent, env

    def get_budget_multiplier(self) -> float:
        return self._cfg.researcher_budget_multiplier


class ExecutorRunner(BaseRoleRunner):
    """Executor: general-purpose task execution, all tools available.

    Shapes execution by:
    - No skill restrictions (full access)
    - Action-oriented prompt hint
    - Full budget allocation
    """

    role_name = "executor"

    def configure(
        self,
        intent: str,
        env_context: Dict[str, Any],
        subtask_spec: Dict[str, Any],
    ) -> tuple[str, Dict[str, Any]]:
        env = {**env_context}

        env["goal_tracker_hint"] = (
            "You are an EXECUTOR agent. Your job is to perform concrete actions: "
            "run code, operate desktop applications, manipulate files, "
            "and produce tangible results. Focus on completing the task "
            "efficiently using the most appropriate tools."
            + self._build_feedback_prompt()
        )

        expected = subtask_spec.get("expected_output", {})
        if expected:
            intent += (
                f"\n\nExpected output: {expected.get('description', 'task completion')}"
                f"\nOutput type: {expected.get('type', 'data')}"
            )

        return intent, env

    def get_budget_multiplier(self) -> float:
        return self._cfg.executor_budget_multiplier


class WriterRunner(BaseRoleRunner):
    """Writer: document generation, report formatting, file output.

    Shapes execution by:
    - Restricting to write-focused skills
    - Document-oriented prompt hint
    - Requiring file artifact output
    """

    role_name = "writer"

    def configure(
        self,
        intent: str,
        env_context: Dict[str, Any],
        subtask_spec: Dict[str, Any],
    ) -> tuple[str, Dict[str, Any]]:
        env = {**env_context}

        env["_skill_hint"] = {
            "preferred": sorted(self._cfg.writer_allowed_skills),
            "prohibited": ["web.search", "state.get", "net.get"],
            "reason": "Writer role: document generation and file output. "
                       "Do NOT search or fetch — use upstream results only.",
        }

        env["goal_tracker_hint"] = (
            "You are a WRITER agent. Your job is to generate documents, "
            "format reports, and produce file outputs. "
            "You MUST produce a concrete file artifact as your output. "
            "You MUST NOT use web.search, state.get, or any search/fetch skills. "
            "All information you need is provided in upstream results. "
            "Use fs.write or python.run to create the output file."
            + self._build_feedback_prompt()
        )

        expected = subtask_spec.get("expected_output", {})
        fmt = expected.get("format", "")
        if fmt:
            intent += f"\n\nYou MUST produce a .{fmt} file as output."
        if expected.get("description"):
            intent += f"\nExpected: {expected['description']}"

        return intent, env

    def get_budget_multiplier(self) -> float:
        return self._cfg.writer_budget_multiplier


class ReviewerRunner(BaseRoleRunner):
    """Reviewer: checks acceptance_criteria on completed subtask outputs.

    Shapes execution by:
    - Read-only skill set (no mutations)
    - Review-focused prompt with acceptance checklist
    - Low budget (review should be fast)
    - Only enabled when config.reviewer_enabled is True
    """

    role_name = "reviewer"

    def configure(
        self,
        intent: str,
        env_context: Dict[str, Any],
        subtask_spec: Dict[str, Any],
    ) -> tuple[str, Dict[str, Any]]:
        env = {**env_context}

        env["_skill_hint"] = {
            "preferred": sorted(self._cfg.reviewer_allowed_skills),
            "prohibited": [],
            "reason": "Reviewer role: read-only verification of acceptance criteria",
        }

        # Build acceptance checklist from subtask spec
        criteria = subtask_spec.get("acceptance_criteria", [])
        checklist = ""
        if criteria:
            checklist = "\n\nAcceptance criteria to verify:\n" + "\n".join(
                f"- [ ] {c}" for c in criteria
            )

        env["goal_tracker_hint"] = (
            "You are a REVIEWER agent. Your job is to verify that a completed "
            "task meets its acceptance criteria. "
            "You MUST NOT modify any files or produce new artifacts. "
            "Read the outputs, check each criterion, and report a structured "
            "verdict: PASS (all criteria met), PARTIAL (some met), or FAIL."
            + checklist
            + self._build_feedback_prompt()
        )

        intent = f"Review the output of the completed task and verify acceptance criteria.\n\n{intent}"

        return intent, env

    def get_budget_multiplier(self) -> float:
        return self._cfg.reviewer_budget_multiplier


# ── Role runner registry ────────────────────────────────────────────

_ROLE_RUNNERS: Dict[str, type] = {
    "researcher": ResearcherRunner,
    "executor": ExecutorRunner,
    "writer": WriterRunner,
    "reviewer": ReviewerRunner,
}

# Custom specs storage for dynamically registered roles
_CUSTOM_SPECS: Dict[str, 'RoleRunnerSpec'] = {}
_CUSTOM_SPECS_LOCK = threading.Lock()


def get_role_runner(
    role_name: str,
    config: Optional[MultiAgentConfig] = None,
) -> BaseRoleRunner:
    """Get a RoleRunner instance for the given role name.

    Checks custom specs first, then built-in runners, falls back to ExecutorRunner.
    """
    with _CUSTOM_SPECS_LOCK:
        spec = _CUSTOM_SPECS.get(role_name)
    if spec is not None:
        return ConfigurableRoleRunner(spec=spec, config=config)
    runner_cls = _ROLE_RUNNERS.get(role_name, ExecutorRunner)
    return runner_cls(config=config)


# ── Configurable role runner (dynamic registration) ─────────────────

@dataclass
class RoleRunnerSpec:
    """Declarative specification for a custom role runner.

    Allows defining new roles via config without writing Python classes.
    """
    role_name: str
    system_prompt: str  # injected as goal_tracker_hint
    allowed_skills: FrozenSet[str] = frozenset()  # empty = all allowed
    prohibited_skills: FrozenSet[str] = frozenset()
    budget_multiplier: float = 1.0
    skill_reason: str = ""


class ConfigurableRoleRunner(BaseRoleRunner):
    """Role runner created from a RoleRunnerSpec at runtime.

    Supports dynamic role registration without code changes.
    """

    def __init__(
        self,
        spec: RoleRunnerSpec,
        config: Optional[MultiAgentConfig] = None,
    ) -> None:
        super().__init__(config=config)
        self._spec = spec
        self.role_name = spec.role_name

    def configure(
        self,
        intent: str,
        env_context: Dict[str, Any],
        subtask_spec: Dict[str, Any],
    ) -> tuple[str, Dict[str, Any]]:
        env = {**env_context}

        if self._spec.allowed_skills:
            env["_skill_hint"] = {
                "preferred": sorted(self._spec.allowed_skills),
                "prohibited": sorted(self._spec.prohibited_skills),
                "reason": self._spec.skill_reason or f"{self._spec.role_name} role",
            }

        env["goal_tracker_hint"] = (
            self._spec.system_prompt + self._build_feedback_prompt()
        )

        expected = subtask_spec.get("expected_output", {})
        if expected.get("description"):
            intent += f"\n\nExpected: {expected['description']}"

        return intent, env

    def get_budget_multiplier(self) -> float:
        return self._spec.budget_multiplier


def register_role_runner(spec: RoleRunnerSpec) -> None:
    """Register a custom role runner from a declarative spec.

    After registration, get_role_runner(spec.role_name) returns a
    ConfigurableRoleRunner instance.
    """
    with _CUSTOM_SPECS_LOCK:
        _CUSTOM_SPECS[spec.role_name] = spec
    logger.info("[RoleRunners] Registered custom role: %s", spec.role_name)


def unregister_role_runner(role_name: str) -> None:
    """Remove a custom role runner registration."""
    with _CUSTOM_SPECS_LOCK:
        _CUSTOM_SPECS.pop(role_name, None)
