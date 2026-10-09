"""Настройка логирования приложения.

Логи пишутся в файл %APPDATA%/FileOrganizer/logs/app.log и в консоль.
Core-функции дополнительно принимают log_cb(level, message) для показа
лога в UI — это здесь не настраивается, только общий logger.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from app.core.constants import LOG_FILE, LOGS_DIR

MAX_LOG_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3

_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Настраивает корневой логгер приложения. Идемпотентна."""
    global _configured
    logger = logging.getLogger(APP_LOGGER_NAME)
    if _configured:
        logger.setLevel(level)
        return logger

    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=MAX_LOG_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        )
        logger.addHandler(file_handler)
    except OSError:
        # Не роняем приложение из-за невозможности писать лог на диск
        pass

    stream = logging.StreamHandler(sys.stderr)
    stream.setLevel(level)
    stream.setFormatter(logging.Formatter("%(levelname)-8s | %(message)s"))
    logger.addHandler(stream)

    logger.setLevel(level)
    logger.propagate = False
    _configured = True
    return logger


APP_LOGGER_NAME = "fileorganizer"


def get_logger(name: str | None = None) -> logging.Logger:
    """Возвращает логгер приложения (или дочерний по имени)."""
    base = logging.getLogger(APP_LOGGER_NAME)
    if not name:
        return base
    return base.getChild(name)


def make_log_bridge(log_cb):
    """Возвращает функцию log(level, message), которая пишет и в logger, и в UI-колбэк.

    Ошибки UI-колбэка не должны ронять фоновую операцию.
    """

    def _log(level: str, message: str) -> None:
        lvl = getattr(logging, str(level).upper(), logging.INFO)
        get_logger().log(lvl, message)
        if log_cb is not None:
            try:
                log_cb(str(level).lower(), message)
            except Exception:  # noqa: BLE001 — UI-колбэк не должен ломать ядро
                get_logger().exception("Ошибка UI-колбэка лога")

    return _log
