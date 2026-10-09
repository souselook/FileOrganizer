"""Панель лога для UI: цветные уровни, ограничение числа строк."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QPlainTextEdit

MAX_LINES = 2000

_COLORS = {
    "info": "#2e7d32",
    "warning": "#c77f00",
    "error": "#d64541",
    "debug": "#6b7480",
}


class LogView(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(MAX_LINES)
        self.setFont(QFont("Consolas", 9))
        self.setObjectName("logView")

    def append_log(self, level: str, message: str) -> None:
        color = _COLORS.get(str(level).lower(), "#1e2229")
        self.appendHtml(
            f'<span style="color:{color}">[{str(level).upper():<7}]</span> '
            f'<span>{message.replace("&", "&amp;").replace("<", "&lt;")}</span>'
        )
