"""Qt-воркеры: тонкие переносчики вызовов core-функций в фоновые потоки.

Бизнес-логики здесь нет. Сигналы:
  progress(int, str), log(str, str), finished(object), error(str), canceled()
UI обновляется только через сигналы в main thread.
"""
from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QThread, Signal

from app.core.actions import execute_plan
from app.core.cache import Cache
from app.core.duplicates import find_duplicates
from app.core.hasher import hash_files
from app.core.history import History
from app.core.models import Settings
from app.core.organizer import build_plan
from app.core.rules import RuleMatcher
from app.core.scanner import scan_folder


class BaseWorker(QThread):
    progress = Signal(int, str)
    log = Signal(str, str)
    finished_with_result = Signal(object)
    error = Signal(str)
    canceled = Signal()

    def __init__(self, settings: Settings, cache: Cache | None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.cache = cache
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    # --- служебное: колбэки core превращаем в Qt-сигналы ---
    def _progress_cb(self, percent: int, message: str) -> None:
        self.progress.emit(int(percent), str(message))

    def _log_cb(self, level: str, message: str) -> None:
        self.log.emit(str(level), str(message))

    def _is_canceled(self) -> bool:
        return self.cancel_event.is_set()


class ScanWorker(BaseWorker):
    def __init__(self, settings, cache, parent=None):
        super().__init__(settings, cache, parent)

    def run(self) -> None:
        try:
            result = scan_folder(
                self.settings, self.cache,
                self._progress_cb, self._log_cb, self.cancel_event,
            )
            if self._is_canceled():
                self.canceled.emit()
            self.finished_with_result.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"{exc}\n{traceback.format_exc()}")


class HashWorker(BaseWorker):
    def __init__(self, settings, cache, files, parent=None):
        super().__init__(settings, cache, parent)
        self.files = files

    def run(self) -> None:
        try:
            result = hash_files(
                self.files, self.settings, self.cache,
                self._progress_cb, self._log_cb, self.cancel_event, full=True,
            )
            if self._is_canceled():
                self.canceled.emit()
            self.finished_with_result.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"{exc}\n{traceback.format_exc()}")


class DuplicateWorker(BaseWorker):
    def __init__(self, settings, cache, files, parent=None):
        super().__init__(settings, cache, parent)
        self.files = files

    def run(self) -> None:
        try:
            groups = find_duplicates(
                self.files, self.settings, self.cache,
                self._progress_cb, self._log_cb, self.cancel_event,
            )
            if self._is_canceled():
                self.canceled.emit()
            self.finished_with_result.emit(groups)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"{exc}\n{traceback.format_exc()}")


class OrganizeWorker(BaseWorker):
    """Строит план (предпросмотр). Диск не изменяется."""

    def __init__(self, settings, cache, files, rules: RuleMatcher, parent=None):
        super().__init__(settings, cache, parent)
        self.files = files
        self.rules = rules

    def run(self) -> None:
        try:
            plan = build_plan(
                self.files, self.rules, self.settings,
                self._progress_cb, self._log_cb,
            )
            self.finished_with_result.emit(plan)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"{exc}\n{traceback.format_exc()}")


class ActionWorker(BaseWorker):
    """Выполняет подтверждённый план."""

    def __init__(self, settings, cache, plan, history: History, parent=None):
        super().__init__(settings, cache, parent)
        self.plan = plan
        self.history = history

    def run(self) -> None:
        try:
            result = execute_plan(
                self.plan, self.settings, self.history,
                self._progress_cb, self._log_cb, self.cancel_event,
            )
            if self._is_canceled():
                self.canceled.emit()
            self.finished_with_result.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"{exc}\n{traceback.format_exc()}")
