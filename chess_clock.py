from __future__ import annotations

import math
import time
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class ChessClock(QObject):
    updated = pyqtSignal()
    flag = pyqtSignal(str)

    def __init__(
        self,
        base_seconds: int = 600,
        increment: int = 0,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.base_seconds = base_seconds
        self.increment = increment
        self.remaining = {"w": float(base_seconds), "b": float(base_seconds)}
        self.active: Optional[str] = None
        self._last = 0.0
        self._flagged = False
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._tick)

    def reset(
        self, base_seconds: Optional[int] = None, increment: Optional[int] = None
    ) -> None:
        self.timer.stop()
        if base_seconds is not None:
            self.base_seconds = max(1, int(base_seconds))
        if increment is not None:
            self.increment = max(0, int(increment))
        self.remaining = {
            "w": float(self.base_seconds),
            "b": float(self.base_seconds),
        }
        self.active = None
        self._flagged = False
        self.updated.emit()

    def start(self, color: str) -> None:
        self.active = color
        self._last = time.monotonic()
        self._flagged = False
        self.timer.start()
        self.updated.emit()

    def set_turn(self, color: str) -> None:
        if self.active is None:
            self.start(color)
            return
        if color == self.active:
            return
        now = time.monotonic()
        self._consume(now)
        if self._flagged:
            return
        self.active = color
        self._last = now
        self.updated.emit()

    def complete_move(self, next_color: str) -> None:
        if self.active is None:
            self.start(next_color)
            return
        now = time.monotonic()
        mover = self.active
        self._consume(now)
        if self._flagged:
            return
        if self.increment:
            self.remaining[mover] += self.increment
        self.active = next_color
        self._last = now
        self.updated.emit()

    def set_time_control(
        self, base_seconds: int, increment: int
    ) -> None:
        self.base_seconds = max(60, int(base_seconds))
        self.increment = max(0, int(increment))
        self.remaining = {
            "w": float(self.base_seconds),
            "b": float(self.base_seconds),
        }
        self._flagged = False
        self.updated.emit()

    def stop(self, add_increment: bool = False) -> None:
        if self.active is not None:
            color = self.active
            self._consume(time.monotonic(), check_flag=False)
            if add_increment and self.increment:
                self.remaining[color] += self.increment
        self.active = None
        self.timer.stop()
        self.updated.emit()

    def is_running(self) -> bool:
        return self.active is not None

    def remaining_seconds(self, color: str) -> float:
        return max(0.0, self.remaining[color])

    def display(self, color: str) -> str:
        seconds = max(0, int(math.ceil(self.remaining_seconds(color))))
        minutes, seconds = divmod(seconds, 60)
        if minutes >= 100:
            hours, minutes = divmod(minutes, 60)
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _tick(self) -> None:
        if self.active is None:
            return
        self._consume(time.monotonic())
        self.updated.emit()

    def _consume(self, now: float, check_flag: bool = True) -> None:
        if self.active is None:
            return
        elapsed = max(0.0, now - self._last)
        self._last = now
        color = self.active
        self.remaining[color] = max(0.0, self.remaining[color] - elapsed)
        if (
            check_flag
            and not self._flagged
            and self.remaining[color] <= 0.0
        ):
            self._flagged = True
            self.timer.stop()
            self.flag.emit(color)
