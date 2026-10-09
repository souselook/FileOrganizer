"""Прогресс-бар с текстом сообщения и состоянием отмены."""
from __future__ import annotations

from PySide6.QtWidgets import QProgressBar


class TaskProgress(QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 100)
        self.setValue(0)
        self.setTextVisible(True)
        self.setFormat("%p%")

    def set_task(self, percent: int, message: str = "") -> None:
        self.setValue(max(0, min(100, int(percent))))
        if message:
            self.setFormat(f"%p% — {message[:80]}")
        else:
            self.setFormat("%p%")

    def start_indeterminate(self, message: str = "Выполняется…") -> None:
        self.setRange(0, 0)
        self.setFormat(message)

    def stop(self) -> None:
        self.setRange(0, 100)
        self.setValue(100)
