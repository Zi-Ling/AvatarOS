from __future__ import annotations

"""AgentLoop — heartbeat driver for the RuntimeKernel.

Drives the fixed phase sequence: sense → schedule → execute → monitor.
Collects RuntimeSignals from each phase, merges via RuntimeKernel, and
applies the resulting decision atomically.

AgentLoop does NOT execute decisions itself — it only produces signals.
"""

import asyncio
import logging
import time
from typing import Any, Optional

from .signals import RuntimeSignal, SignalType, SliceResult

logger = logging.getLogger(__name__)

# Default configuration
_DEFAULT_TICK_TIMEOUT_S = 30.0
_DEFAULT_GOAL_REVIEW_INTERVAL = 60  # ticks


class AgentLoop:
    """Heartbeat driver. Does not execute decisions — only produces signals."""

    def __init__(
        self,
        kernel: Any,  # RuntimeKernel (avoid circular import)
        scheduler: Any = None,  # TaskScheduler
        monitor: Any = None,  # SelfMonitor
        graph_adapter: Any = None,  # GraphControllerAdapter
        environment_model: Any = None,  # EnvironmentModel
        max_tick_duration: float = _DEFAULT_TICK_TIMEOUT_S,
        goal_review_interval: int = _DEFAULT_GOAL_REVIEW_INTERVAL,
        monitor_only: bool = False,
    ) -> None:
        self._kernel = kernel
        self._scheduler = scheduler
        self._monitor = monitor
        self._graph_adapter = graph_adapter
        self._environment_model = environment_model
        self._max_tick_duration = max_tick_duration
        self._goal_review_interval = goal_review_interval
        self._monitor_only = monitor_only
        self._wake_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def tick(self) -> None:
        """Single heartbeat: sense → schedule → execute → monitor → decide.

        Timeout protection: the entire tick is bounded by max_tick_duration.
        """
        try:
            await asyncio.wait_for(
                self._tick_inner(),
                timeout=self._max_tick_duration,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[AgentLoop] tick timed out after %.1fs", self._max_tick_duration
            )
            # Record timeout but don't crash
            self._kernel.loop_state.tick_count += 1

    async def run(self, interval_s: float = 5.0) -> None:
        """Continuous loop until kernel.shutdown().

        Checks AgentLoopState.is_paused — skips tick when paused.
        Supports event-triggered immediate wake via ``wake()``.
        """
        loop_state = self._kernel.loop_state
        while loop_state.is_running:
            if loop_state.is_paused:
                await asyncio.sleep(interval_s)
                continue

            await self.tick()

            # Wait for interval or wake event
            self._wake_event.clear()
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=interval_s)
            except asyncio.TimeoutError:
                pass  # Normal interval elapsed

    async def wake(self) -> None:
        """Event-triggered immediate wake."""
        self._wake_event.set()

    # ------------------------------------------------------------------
    # Internal tick implementation
    # ------------------------------------------------------------------

    async def _tick_inner(self) -> None:
        """Core tick logic without timeout wrapper.

        Full mode: sense → schedule → execute → monitor → goal_review.
        Monitor-only mode: sense + monitor phases only.

        In full mode, the execute phase only runs when the kernel has an
        active_task_id assigned by the scheduler (cooperative with
        GraphController's user-initiated execution).
        """
        signals: list[RuntimeSignal] = []

        # Phase 1: Sense (always runs)
        signals += await self._sense_phase()

        if not self._monitor_only:
            # Phase 2: Schedule
            signals += await self._schedule_phase()

            # Phase 3: Execute (only if kernel has an active task)
            if self._kernel.active_task_id is not None:
                slice_result = await self._execute_phase()
                signals += slice_result.signals
            else:
                slice_result = SliceResult(terminal=False)
        else:
            slice_result = SliceResult(terminal=False)

        # Phase 4: Monitor (always runs)
        signals += await self._monitor_phase(slice_result)

        # Goal review (every N ticks, only in full mode)
        tick_count = self._kernel.loop_state.tick_count
        if not self._monitor_only and tick_count > 0 and tick_count % self._goal_review_interval == 0:
            signals += await self._goal_review()

        # Merge and apply
        decision = self._kernel.merge_signals(signals)
        self._kernel.apply_decision(decision)

        self._kernel.loop_state.tick_count += 1

    # ------------------------------------------------------------------
    # Tick phases
    # ------------------------------------------------------------------

    async def _sense_phase(self) -> list[RuntimeSignal]:
        """Pull pending events from EventBus, match TriggerRules, convert to signals.

        Flow:
        1. drain_pending() from EventBus
        2. For each event, match TriggerRules via EventBus.match_trigger_rules()
        3. For matched rules:
           - create_task action → WorkQueue entry
           - emit_signal action → RuntimeSignal
        4. Record matching results to AuditTrail (rule ID, event ID, executed action)

        Returns empty list if no event bus is registered.
        Requirements: 4.6, 4.8
        """
        event_bus = self._kernel.get_subsystem("event_bus")
        if event_bus is None:
            return []

        signals: list[RuntimeSignal] = []
        try:
            if not hasattr(event_bus, "drain_pending"):
                return signals

            events = await event_bus.drain_pending()
            audit_trail = self._kernel.get_subsystem("audit_trail")
            work_queue = self._kernel.get_subsystem("work_queue")

            for evt in events:
                # Match trigger rules (cooldown + idempotency filtered)
                matched_rules = []
                if hasattr(event_bus, "match_trigger_rules"):
                    matched_rules = event_bus.match_trigger_rules(evt)

                if not matched_rules:
                    # No rule matched — emit a basic status update signal
                    signals.append(
                        RuntimeSignal(
                            signal_type=SignalType.EMIT_STATUS_UPDATE,
                            source_subsystem="event_bus",
                            reason=f"event: {getattr(evt, 'event_type', 'unknown')}",
                            metadata={"event_id": getattr(evt, "event_id", "")},
                        )
                    )
                    continue

                for rule in matched_rules:
                    action = rule.action
                    event_id = getattr(evt, "event_id", "")

                    if action == "create_task" and work_queue is not None:
                        # Create a WorkQueue entry from rule action_params
                        from ..agenda.work_queue import WorkQueueEntry

                        params = rule.action_params
                        entry = WorkQueueEntry(
                            task_id=params.get("task_id", f"trigger_{rule.rule_id}_{event_id}"),
                            priority_score=params.get("priority_score", 0.5),
                            deadline=params.get("deadline"),
                            dependencies=params.get("dependencies", []),
                            resource_budget=params.get("resource_budget", {}),
                        )
                        work_queue.push(entry)
                        signals.append(
                            RuntimeSignal(
                                signal_type=SignalType.CREATE_FOLLOWUP_TASK,
                                source_subsystem="event_bus",
                                reason=f"trigger rule {rule.rule_id} → create_task",
                                metadata={
                                    "event_id": event_id,
                                    "rule_id": rule.rule_id,
                                    "task_id": entry.task_id,
                                },
                            )
                        )

                    elif action == "emit_signal":
                        # Convert to RuntimeSignal from action_params
                        params = rule.action_params
                        sig_type_str = params.get("signal_type", "emit_status_update")
                        try:
                            sig_type = SignalType(sig_type_str)
                        except ValueError:
                            sig_type = SignalType.EMIT_STATUS_UPDATE
                        signals.append(
                            RuntimeSignal(
                                signal_type=sig_type,
                                source_subsystem="event_bus",
                                target_task_id=params.get("target_task_id"),
                                priority=params.get("priority", rule.priority),
                                reason=params.get("reason", f"trigger rule {rule.rule_id}"),
                                metadata={
                                    "event_id": event_id,
                                    "rule_id": rule.rule_id,
                                },
                            )
                        )

                    else:
                        # Other actions (update_priority, notify_user) — basic signal
                        signals.append(
                            RuntimeSignal(
                                signal_type=SignalType.EMIT_STATUS_UPDATE,
                                source_subsystem="event_bus",
                                reason=f"trigger rule {rule.rule_id} → {action}",
                                metadata={
                                    "event_id": event_id,
                                    "rule_id": rule.rule_id,
                                    "action": action,
                                    "action_params": rule.action_params,
                                },
                            )
                        )

                    # Record to AuditTrail (best-effort)
                    self._record_trigger_audit(
                        audit_trail, rule.rule_id, event_id, action
                    )

        except Exception as exc:
            logger.warning("[AgentLoop] sense_phase error: %s", exc)
        return signals

    @staticmethod
    def _record_trigger_audit(
        audit_trail: Any,
        rule_id: str,
        event_id: str,
        action: str,
    ) -> None:
        """Best-effort audit recording for trigger rule matches."""
        if audit_trail is None:
            return
        try:
            if hasattr(audit_trail, "append"):
                audit_trail.append({
                    "type": "trigger_match",
                    "rule_id": rule_id,
                    "event_id": event_id,
                    "action": action,
                })
        except Exception as exc:
            logger.warning(
                "[AgentLoop] failed to record trigger audit: %s", exc
            )

    async def _schedule_phase(self) -> list[RuntimeSignal]:
        """Call TaskScheduler.evaluate(), produce scheduling signals."""
        if self._scheduler is None:
            return []

        signals: list[RuntimeSignal] = []
        try:
            current_task_id = self._kernel.active_task_id
            result = self._scheduler.evaluate(current_task_id)
            if isinstance(result, list):
                signals.extend(result)
        except Exception as exc:
            logger.warning("[AgentLoop] schedule_phase error: %s", exc)
        return signals

    async def _execute_phase(self) -> SliceResult:
        """Delegate to GraphControllerAdapter for bounded execution slice.

        If no adapter is available or no active task, returns a no-op SliceResult.
        Detects blocked signals and generates SUSPEND_TASK accordingly.
        """
        if self._graph_adapter is None or self._kernel.active_task_id is None:
            return SliceResult(terminal=False)

        try:
            # Merge environment context if available
            env_context: dict[str, Any] = {}
            if self._environment_model is not None:
                task_id = self._kernel.active_task_id
                # Use task_id as scope hint (V1 simple)
                env_context = self._environment_model.get_context(task_id or "")

            slice_result = await self._graph_adapter.execute(
                task_id=self._kernel.active_task_id,
                env_context=env_context,
                timeout_s=self._max_tick_duration,
            )

            # Detect blocked signals → generate SUSPEND_TASK
            blocked_signals = [
                s for s in slice_result.signals
                if s.signal_type in (SignalType.STUCK_ALERT, SignalType.LOOP_ALERT)
            ]
            if blocked_signals:
                slice_result.signals.append(
                    RuntimeSignal(
                        signal_type=SignalType.SUSPEND_TASK,
                        source_subsystem="agent_loop",
                        target_task_id=self._kernel.active_task_id,
                        reason="blocked signal detected in execution",
                        metadata={"target_state": "blocked"},
                    )
                )

            return slice_result

        except Exception as exc:
            logger.warning("[AgentLoop] execute_phase error: %s", exc)
            return SliceResult(
                terminal=True,
                signals=[
                    RuntimeSignal(
                        signal_type=SignalType.SUSPEND_TASK,
                        source_subsystem="agent_loop",
                        target_task_id=self._kernel.active_task_id,
                        reason=f"execution error: {exc}",
                        metadata={"target_state": "suspended"},
                    )
                ],
            )

    async def _monitor_phase(self, slice_result: SliceResult) -> list[RuntimeSignal]:
        """Call SelfMonitor.check(), produce monitoring signals."""
        if self._monitor is None:
            return []

        signals: list[RuntimeSignal] = []
        try:
            # Skip monitoring when no task is active — avoids false stuck alerts
            task_id = self._kernel.active_task_id
            if not task_id:
                return []

            # Build MonitorContext from current state
            from .monitor_context import MonitorContext

            ctx = MonitorContext(
                task_id=task_id,
                tick_count=self._kernel.loop_state.tick_count,
                completed_items_count=0,
                completed_items_delta=0,
                slice_result=slice_result,
            )
            result = self._monitor.check(ctx)
            if isinstance(result, list):
                signals.extend(result)
        except Exception as exc:
            logger.warning("[AgentLoop] monitor_phase error: %s", exc)
        return signals

    async def _goal_review(self) -> list[RuntimeSignal]:
        """Every N ticks, review goals for active/waiting tasks."""
        signals: list[RuntimeSignal] = []
        try:
            agenda = self._kernel.get_subsystem("agenda_manager")
            if agenda is None:
                return signals

            # Check active task
            active = getattr(agenda, "active", None)
            if active:
                signals.append(
                    RuntimeSignal(
                        signal_type=SignalType.EMIT_STATUS_UPDATE,
                        source_subsystem="agent_loop",
                        target_task_id=active,
                        reason="periodic goal review",
                    )
                )

            # Check waiting tasks
            waiting = getattr(agenda, "waiting", [])
            for tid in waiting:
                signals.append(
                    RuntimeSignal(
                        signal_type=SignalType.EMIT_STATUS_UPDATE,
                        source_subsystem="agent_loop",
                        target_task_id=tid,
                        reason="periodic goal review (waiting)",
                    )
                )
        except Exception as exc:
            logger.warning("[AgentLoop] goal_review error: %s", exc)
        return signals
