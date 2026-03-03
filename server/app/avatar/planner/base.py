# avatar/planner/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, Any, Dict, Optional

from .models import Task, Step


class SkillContext(Protocol):
    """
    Minimal interface used by the planner/runner to call skills.
    """

    async def call_skill(self, name: str, params: Dict[str, Any]) -> Any:
        """
        Call a skill by name with given params, and return the result.
        Exceptions are treated as failures by the runner.
        """
        ...


class StateStore(Protocol):
    """
    State persistence interface (optional).

    MVP: you can start with an in-memory implementation and later
    replace it with a DB / file-based store without changing the planner.
    """

    def save_task(self, task: Task) -> None:
        ...

    def load_task(self, task_id: str) -> Optional[Task]:
        ...


class Planner(ABC):
    """
    Base class for *execution* planners / runners.
    """

    @abstractmethod
    async def run(
        self,
        task: Task,
        *,
        ctx: SkillContext,
        state: Optional[StateStore] = None,
    ) -> Task:
        """
        Execute a Task, chaining multiple steps.
        """
        raise NotImplementedError


class TaskPlanner(ABC):
    """
    High-level *planning* interface (Intent → Task).
    """

    @abstractmethod
    async def make_task(
        self,
        intent: Any,
        env_context: Dict[str, Any],
        ctx: Optional[Any] = None,
        *,
        memory: Optional[str] = None,
    ) -> Task:
        """
        Build a Task asynchronously.
        """
        raise NotImplementedError

    async def re_plan(
        self,
        original_task: Task,
        failed_step: Step,
        error_msg: str,
        env_context: Dict[str, Any],
        *,
        memory: Optional[str] = None,
    ) -> Task:
        """
        Re-plan a failed task asynchronously.
        """
        raise NotImplementedError

    async def next_step(
        self,
        task: Task,
        env_context: Dict[str, Any],
    ) -> Optional[Step]:
        """
        Interactive Planning: Generate the next step based on the current task state.
        Return None if the task is finished.
        """
        # Default implementation for non-interactive planners:
        # Assume they generate the full plan in make_task, so no next_step is needed.
        return None
