"""Точка входа: только инициализация QApplication, создание зависимостей и запуск окна.

Бизнес-логики здесь нет. Явные зависимости (Settings, Cache, History) создаются
здесь и передаются в MainWindow.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Позволяет запускать main.py из любого места
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.core import constants  # noqa: E402
from app.core.cache import Cache  # noqa: E402
from app.core.config import load_settings  # noqa: E402
from app.core.history import History  # noqa: E402
from app.core.logging_utils import setup_logging  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def main() -> int:
    setup_logging(logging.INFO)
    constants.APP_DIR.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv)
    app.setApplicationName(constants.APP_NAME)
    app.setOrganizationName(constants.APP_NAME)

    settings = load_settings()
    try:
        cache = Cache()
        history = History(limit=settings.history_limit)
    except OSError as exc:
        QMessageBox.critical(None, "Ошибка запуска",
                             f"Не удалось создать файлы данных: {exc}")
        return 1

    window = MainWindow(settings, cache, history)
    window.show()
    rc = app.exec()

    cache.close()
    history.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
