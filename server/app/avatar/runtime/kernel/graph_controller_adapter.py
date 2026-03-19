from __future__ import annotations

"""GraphControllerAdapter — adapts GraphController.execute() → SliceResult.

Maps GraphController execution results to the SliceResult data model used
by AgentLoop, handling exceptions, blocked states, and timeouts.
"""

import asyncio
import logging
import time
from typing import Any, Optional

from .signals import RuntimeSignal, SignalType, SliceResult

logger = logging.getLogger(__name__)


class GraphControllerAdapter:
    """Adapts GraphController.execute() into a bounded SliceResult.

    Responsibilities:
    * Call GraphController.execute() with timeout.
    * Map execution results to SliceResult fields.
    * Handle exceptions → SliceResult.terminal=True + error signals.
    * Extract blocked/timeout states → corresponding RuntimeSignal.
    """

    def __init__(self, graph_controller: Any = None) -> None:
        self._graph_controller = graph_controller

    async def execute(
        self,
        task_id: str,
        env_context: Optional[dict[str, Any]] = None,
        timeout_s: float = 30.0,
    ) -> SliceResult:
        """Execute a bounded slice via GraphController.

        Args:
            task_id: The task being executed.
            env_context: Environment context to merge into the execution.
            timeout_s: Maximum time for this execution slice.

        Returns:
            SliceResult with terminal status, signals, and elapsed time.
        """
        if self._graph_controller is None:
            return SliceResult(
                terminal=False,
                signals=[
                    RuntimeSignal(
                        signal_type=SignalType.EMIT_STATUS_UPDATE,
                        source_subsystem="graph_controller_adapter",
                        target_task_id=task_id,
                        reason="no graph controller available",
                    )
                ],
            )

        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._execute_graph_controller(task_id, env_context or {}),
                timeout=timeout_s,
            )
            elapsed = time.monotonic() - start
            return self._map_result(task_id, result, elapsed)

        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            logger.warning(
                "[GraphControllerAdapter] execution timed out for task %s (%.1fs)",
                task_id,
                elapsed,
            )
            return SliceResult(
                terminal=False,
                signals=[
                    RuntimeSignal(
                        signal_type=SignalType.SUSPEND_TASK,
                        source_subsystem="graph_controller_adapter",
                        target_task_id=task_id,
                        reason=f"execution timeout ({elapsed:.1f}s)",
                        metadata={"target_state": "suspended"},
                    )
                ],
                elapsed_s=elapsed,
            )

        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.error(
                "[GraphControllerAdapter] execution error for task %s: %s",
                task_id,
                exc,
            )
            return SliceResult(
                terminal=True,
                signals=[
                    RuntimeSignal(
                        signal_type=SignalType.SUSPEND_TASK,
                        source_subsystem="graph_controller_adapter",
                        target_task_id=task_id,
                        reason=f"execution error: {exc}",
                        metadata={"target_state": "blocked"},
                    )
                ],
                elapsed_s=elapsed,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _execute_graph_controller(
        self, task_id: str, env_context: dict[str, Any]
    ) -> Any:
        """Call the underlying GraphController.execute()."""
        gc = self._graph_controller
        # GraphController.execute(goal, mode, env_context)
        # We pass task_id as the goal for the slice
        result = await gc.execute(
            task_id,
            mode="react",
            env_context=env_context,
        )
        return result

    def _map_result(
        self, task_id: str, result: Any, elapsed: float
    ) -> SliceResult:
        """Map a GraphController result to SliceResult."""
        signals: list[RuntimeSignal] = []
        terminal = False
        checkpoint_id: Optional[str] = None

        # Extract status from GraphController result
        final_status = getattr(result, "final_status", None)
        graph = getattr(result, "graph", None)

        if final_status == "completed" or final_status == "success":
            terminal = True
        elif final_status == "failed":
            terminal = True
            error_msg = getattr(result, "error_message", "unknown error")
            signals.append(
                RuntimeSignal(
                    signal_type=SignalType.SUSPEND_TASK,
                    source_subsystem="graph_controller_adapter",
                    target_task_id=task_id,
                    reason=f"graph execution failed: {error_msg}",
                    metadata={"target_state": "blocked"},
                )
            )
        elif final_status == "blocked" or final_status == "waiting_input":
            signals.append(
                RuntimeSignal(
                    signal_type=SignalType.SUSPEND_TASK,
                    source_subsystem="graph_controller_adapter",
                    target_task_id=task_id,
                    reason=f"graph execution {final_status}",
                    metadata={"target_state": "blocked"},
                )
            )

        # Extract checkpoint if available
        if graph is not None:
            checkpoint_id = getattr(graph, "id", None) or getattr(
                graph, "graph_id", None
            )

        return SliceResult(
            terminal=terminal,
            checkpoint_id=checkpoint_id,
            execution_result=result,
            signals=signals,
            elapsed_s=elapsed,
        )
