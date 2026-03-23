# app/services/computer/audit_recorder.py
"""AuditRecorder — 全链路操作证据记录器.

每步记录固定 schema 的 AuditStep：
- 环境上下文（窗口、输入法）
- 定位策略和证据
- 动作和参数
- 前后状态（控制面）
- 验证结果
- 截图
- 干预事件
- 耗时

失败时自动 dump 完整证据链。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .desktop_models import (
    AuditSession,
    AuditStep,
    DesktopSnapshot,
    InterruptEvent,
    LocatorStrategy,
)

logger = logging.getLogger(__name__)


class AuditRecorder:
    """全链路操作证据记录器."""

    def __init__(
        self,
        session_id: Optional[str] = None,
        goal: str = "",
        output_dir: Optional[Path] = None,
    ) -> None:
        self._session = AuditSession(
            session_id=session_id or uuid.uuid4().hex[:12],
            goal=goal,
        )
        self._output_dir = output_dir
        self._step_counter = 0
        self._current_step: Optional[AuditStep] = None
        self._step_start_time: float = 0.0

    @property
    def session_id(self) -> str:
        return self._session.session_id

    @property
    def steps(self) -> list[AuditStep]:
        return self._session.steps

    def set_environment(self, snapshot: DesktopSnapshot) -> None:
        """记录环境快照."""
        self._session.environment = snapshot

    def begin_step(
        self,
        action: str,
        target: str = "",
        locator_strategy: Optional[LocatorStrategy] = None,
    ) -> AuditStep:
        """开始记录一步操作."""
        self._step_counter += 1
        self._step_start_time = time.time()

        step = AuditStep(
            step_id=self._step_counter,
            action=action,
            locator_target=target,
            locator_strategy=locator_strategy,
        )
        self._current_step = step
        return step

    def record_pre_state(
        self,
        window_title: str = "",
        window_hwnd: int = 0,
        ime_state: str = "",
        control_state: Optional[dict[str, Any]] = None,
    ) -> None:
        """记录操作前的控制面状态."""
        if self._current_step is None:
            return
        self._current_step.active_window_title = window_title
        self._current_step.active_window_hwnd = window_hwnd
        self._current_step.ime_state = ime_state
        self._current_step.pre_state = control_state

    def record_locator(
        self,
        strategy: LocatorStrategy,
        evidence: Optional[dict[str, Any]] = None,
        confidence: float = 0.0,
        target_coords: Optional[tuple[int, int]] = None,
    ) -> None:
        """记录定位结果."""
        if self._current_step is None:
            return
        self._current_step.locator_strategy = strategy
        self._current_step.locator_evidence = evidence
        self._current_step.locator_confidence = confidence
        self._current_step.target_coords = target_coords

    def record_action(self, params: dict[str, Any]) -> None:
        """记录动作参数."""
        if self._current_step is None:
            return
        self._current_step.action_params = params

    def record_screenshot(
        self,
        before: Optional[str] = None,
        after: Optional[str] = None,
    ) -> None:
        """记录截图路径/artifact ID."""
        if self._current_step is None:
            return
        if before:
            self._current_step.screenshot_before = before
        if after:
            self._current_step.screenshot_after = after

    def record_verification(
        self,
        passed: bool,
        details: str = "",
        post_state: Optional[dict[str, Any]] = None,
    ) -> None:
        """记录验证结果."""
        if self._current_step is None:
            return
        self._current_step.verification_passed = passed
        self._current_step.verification_details = details
        self._current_step.post_state = post_state

    def record_interrupt(self, event: InterruptEvent) -> None:
        """记录干预事件."""
        if self._current_step is None:
            return
        self._current_step.interrupt_detected = event

    def end_step(
        self,
        success: bool,
        error: Optional[str] = None,
    ) -> AuditStep:
        """结束当前步骤."""
        if self._current_step is None:
            raise RuntimeError("No active step to end")

        self._current_step.success = success
        self._current_step.error = error
        self._current_step.duration_ms = round(
            (time.time() - self._step_start_time) * 1000, 2
        )

        step = self._current_step
        self._session.steps.append(step)
        self._current_step = None

        log_level = logging.INFO if success else logging.WARNING
        logger.log(
            log_level,
            f"[Audit] step={step.step_id} action={step.action} "
            f"target='{step.locator_target}' success={success} "
            f"time={step.duration_ms}ms"
            f"{f' error={error}' if error else ''}"
        )
        return step

    def finish(self, success: bool, failure_reason: Optional[str] = None) -> AuditSession:
        """结束审计会话."""
        self._session.ended_at = datetime.now(timezone.utc).isoformat()
        self._session.total_steps = len(self._session.steps)
        self._session.success = success
        self._session.failure_reason = failure_reason

        if self._output_dir:
            self._dump_to_file()

        return self._session

    def dump_on_failure(self) -> Optional[Path]:
        """失败时 dump 完整证据链到文件."""
        if not self._output_dir:
            return None
        return self._dump_to_file()

    def _dump_to_file(self) -> Path:
        """写入 JSON 审计日志."""
        if self._output_dir is None:
            self._output_dir = Path(".")
        self._output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"audit_{self._session.session_id}.json"
        path = self._output_dir / filename

        data = self._session.model_dump(mode="json")
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"Audit log written: {path}")
        return path

    def get_session(self) -> AuditSession:
        """获取当前审计会话."""
        return self._session

    def get_last_step(self) -> Optional[AuditStep]:
        """获取最后一步."""
        if self._session.steps:
            return self._session.steps[-1]
        return None
