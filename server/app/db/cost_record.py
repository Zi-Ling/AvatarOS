"""
CostRecord — SQLModel persistence for BudgetAccount cost records.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class CostRecordDB(SQLModel, table=True):
    """
    Persistent record for cost tracking entries.
    Maps to the cost_records table.
    """
    __tablename__ = "cost_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    step_id: str = Field(index=True)
    task_id: str = Field(index=True)
    session_id: str = Field(index=True)
    declared_estimate: float = Field(default=0.0)
    measured_runtime_cost: float = Field(default=0.0)
    llm_cost: float = Field(default=0.0)
    skill_cost: float = Field(default=0.0)
    token_count: int = Field(default=0)
    model: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
