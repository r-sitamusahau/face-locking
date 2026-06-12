"""
Motor command smoothing and hysteresis for MQTT publish (BENAX).
Reduces jitter at deadband edges by requiring stable frames before switching.
"""

from __future__ import annotations


# Commands that must publish immediately (safety / assessor visibility)
IMMEDIATE = frozenset({"SCAN", "OUT_OF_FRAME", "STOPPED"})


class MotorCommandSmoother:
    def __init__(self, hold_frames: int = 4):
        self.hold_frames = max(1, hold_frames)
        self._pending: str | None = None
        self._pending_count = 0
        self.stable: str = "SCAN"

    def filter(self, raw_command: str, *, immediate: bool = False) -> str:
        if immediate or raw_command in IMMEDIATE:
            self.stable = raw_command
            self._pending = raw_command
            self._pending_count = self.hold_frames
            return self.stable

        if raw_command == self._pending:
            self._pending_count += 1
        else:
            self._pending = raw_command
            self._pending_count = 1

        if self._pending_count >= self.hold_frames:
            self.stable = raw_command

        return self.stable
