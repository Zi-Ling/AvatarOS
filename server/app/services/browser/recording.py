# server/app/services/browser/recording.py
"""操作录制与回放。"""
from __future__ import annotations

from typing import Any

from app.services.browser.models import (
    ActionResult,
    PlaybackFailurePolicy,
    PlaybackResult,
    Recording,
    RecordingEntry,
    RecordingMetadata,
)


class RecordingEngine:
    """操作录制。"""

    def __init__(self):
        self._metadata: RecordingMetadata | None = None
        self._entries: list[RecordingEntry] = []
        self._recording: bool = False

    def start_recording(self, metadata: RecordingMetadata) -> None:
        self._metadata = metadata
        self._entries = []
        self._recording = True

    def record_action(self, entry: RecordingEntry) -> None:
        if self._recording:
            self._entries.append(entry)

    def stop_recording(self) -> Recording:
        self._recording = False
        if not self._metadata:
            raise RuntimeError("Recording not started")
        recording = Recording(
            metadata=self._metadata,
            entries=list(self._entries),
        )
        self._entries = []
        return recording


class PlaybackEngine:
    """操作回放。"""

    async def playback(
        self,
        recording: Recording,
        dispatcher: Any,
        page: Any,
        policy: Any = None,
        on_failure: PlaybackFailurePolicy = PlaybackFailurePolicy.ABORT,
    ) -> PlaybackResult:
        total = len(recording.entries)
        completed = 0

        for i, entry in enumerate(recording.entries):
            try:
                result: ActionResult = await dispatcher.execute_action(
                    entry.action, page, policy
                )
            except Exception as exc:
                result = ActionResult(success=False, error=str(exc))

            if result.success:
                completed += 1
                continue

            # 失败处理
            if on_failure == PlaybackFailurePolicy.ABORT:
                return PlaybackResult(
                    success=False,
                    completed_entries=completed,
                    total_entries=total,
                    failed_entry_index=i,
                    error=result.error,
                )
            elif on_failure == PlaybackFailurePolicy.SKIP:
                completed += 1  # 跳过但计入已处理
                continue
            elif on_failure == PlaybackFailurePolicy.RETRY:
                # 重试一次
                try:
                    retry_result = await dispatcher.execute_action(
                        entry.action, page, policy
                    )
                except Exception as exc:
                    retry_result = ActionResult(success=False, error=str(exc))

                if retry_result.success:
                    completed += 1
                else:
                    return PlaybackResult(
                        success=False,
                        completed_entries=completed,
                        total_entries=total,
                        failed_entry_index=i,
                        error=retry_result.error,
                    )

        return PlaybackResult(
            success=True,
            completed_entries=completed,
            total_entries=total,
        )
