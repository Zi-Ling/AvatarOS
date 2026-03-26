"""
BudgetAccount — cost tracking and budget enforcement.

Tracks LLM + skill costs at step / task / session granularity.
Integrates with PolicyEngine for budget-exceeded decisions.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.policy.policy_engine import PolicyDecision

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CostRecord:
    """Single cost record for one step execution."""
    step_id: str
    task_id: str
    session_id: str
    declared_estimate: float = 0.0       # pre-declared cost estimate
    measured_runtime_cost: float = 0.0   # actual measured cost
    llm_cost: float = 0.0
    skill_cost: float = 0.0
    token_count: int = 0
    model: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class BudgetAccountEntry:
    """Aggregated cost entry for a step / task / session."""
    total_cost: float = 0.0
    llm_cost: float = 0.0
    skill_cost: float = 0.0
    token_count: int = 0
    declared_estimate: float = 0.0
    measured_runtime_cost: float = 0.0
    data_incomplete: bool = False        # True if any record_cost() failed


# ---------------------------------------------------------------------------
# BudgetAccount
# ---------------------------------------------------------------------------

class BudgetAccount:
    """
    Tracks costs at step / task / session level.
    Non-blocking: write failures are logged and flagged, never raise.
    """

    def __init__(
        self,
        session_budget_limit: Optional[float] = None,
        task_budget_limit: Optional[float] = None,
        trace_store: Optional[Any] = None,
    ) -> None:
        self.session_budget_limit = session_budget_limit
        self.task_budget_limit = task_budget_limit
        self.trace_store = trace_store

        # In-memory aggregations keyed by id
        self._session_entries: Dict[str, BudgetAccountEntry] = {}
        self._task_entries: Dict[str, BudgetAccountEntry] = {}
        self._step_entries: Dict[str, BudgetAccountEntry] = {}

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record_cost(self, record: CostRecord) -> None:
        """
        Accumulate cost from a CostRecord.
        Also persists to CostRecordDB (non-blocking, failure-tolerant).
        On failure: logs cost_record_failed event, marks data_incomplete=True.
        Never raises — does not block main execution flow.
        """
        try:
            self._accumulate(self._step_entries, record.step_id, record)
            self._accumulate(self._task_entries, record.task_id, record)
            self._accumulate(self._session_entries, record.session_id, record)
        except Exception as exc:
            logger.error(f"[BudgetAccount] record_cost failed: {exc}", exc_info=True)
            # Mark data_incomplete on all affected entries
            for key, store in [
                (record.step_id, self._step_entries),
                (record.task_id, self._task_entries),
                (record.session_id, self._session_entries),
            ]:
                entry = store.setdefault(key, BudgetAccountEntry())
                entry.data_incomplete = True

        # Persist to DB (non-blocking, failure-tolerant)
        try:
            from app.db.cost_record import CostRecordDB
            from app.db.database import get_session
            db_record = CostRecordDB(
                step_id=record.step_id,
                task_id=record.task_id,
                session_id=record.session_id,
                declared_estimate=record.declared_estimate,
                measured_runtime_cost=record.measured_runtime_cost,
                llm_cost=record.llm_cost,
                skill_cost=record.skill_cost,
                token_count=record.token_count,
                model=record.model,
            )
            with get_session() as db:
                db.add(db_record)
                db.commit()
        except Exception as _db_err:
            logger.debug("[BudgetAccount] DB persist failed (non-blocking): %s", _db_err)
            # Emit trace event if available
            if self.trace_store:
                try:
                    self.trace_store.record_event(
                        session_id=record.session_id,
                        task_id=record.task_id,
                        step_id=record.step_id,
                        event_type="cost_record_failed",
                        payload={"error": str(exc)},
                    )
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_session_cost(self, session_id: str) -> BudgetAccountEntry:
        return self._session_entries.get(session_id, BudgetAccountEntry())

    def get_task_cost(self, task_id: str) -> BudgetAccountEntry:
        return self._task_entries.get(task_id, BudgetAccountEntry())

    def get_step_cost(self, step_id: str) -> BudgetAccountEntry:
        return self._step_entries.get(step_id, BudgetAccountEntry())

    # ------------------------------------------------------------------
    # Budget check
    # ------------------------------------------------------------------

    def check_budget(
        self,
        session_id: str,
        task_id: str,
    ) -> "PolicyDecision":
        """
        Check budget limits and return a PolicyDecision.

        - session total_cost > session_budget_limit → DENY (budget_exceeded)
        - task total_cost > task_budget_limit → REQUIRE_APPROVAL
        - otherwise → ALLOW
        """
        from app.avatar.runtime.policy.policy_engine import PolicyDecision

        if self.session_budget_limit is not None:
            session_entry = self.get_session_cost(session_id)
            if session_entry.total_cost > self.session_budget_limit:
                logger.warning(
                    f"[BudgetAccount] session {session_id} budget exceeded: "
                    f"{session_entry.total_cost:.4f} > {self.session_budget_limit:.4f}"
                )
                return PolicyDecision.DENY

        if self.task_budget_limit is not None:
            task_entry = self.get_task_cost(task_id)
            if task_entry.total_cost > self.task_budget_limit:
                logger.warning(
                    f"[BudgetAccount] task {task_id} budget exceeded: "
                    f"{task_entry.total_cost:.4f} > {self.task_budget_limit:.4f}"
                )
                return PolicyDecision.REQUIRE_APPROVAL

        return PolicyDecision.ALLOW

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _accumulate(
        self,
        store: Dict[str, BudgetAccountEntry],
        key: str,
        record: CostRecord,
    ) -> None:
        entry = store.setdefault(key, BudgetAccountEntry())
        entry.total_cost += record.llm_cost + record.skill_cost
        entry.llm_cost += record.llm_cost
        entry.skill_cost += record.skill_cost
        entry.token_count += record.token_count
        entry.declared_estimate += record.declared_estimate
        entry.measured_runtime_cost += record.measured_runtime_cost
