"""Хеширование файлов: быстрый хеш первых N байт и полный хеш, потоковое чтение.

Файл не держится в памяти целиком. Ошибки (нет прав, файл занят) —
помечаются на FileItem, операция продолжается.
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from app.core.cache import Cache
from app.core.logging_utils import get_logger, make_log_bridge
from app.core.models import FileItem, Settings

log = get_logger("hasher")

READ_CHUNK = 1024 * 1024  # 1 MiB


def quick_hash_file(path: Path | str, quick_size: int = 4096, algorithm: str = "sha256") -> str:
    """Хеш первых quick_size байт файла."""
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        h.update(f.read(quick_size))
    return h.hexdigest()


def full_hash_file(path: Path | str, algorithm: str = "sha256", cancel_event=None) -> str:
    """Потоковый хеш всего файла (не держим файл в памяти)."""
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("Хеширование отменено")
            chunk = f.read(READ_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def hash_file(
    file: FileItem,
    settings: Settings,
    cache: Cache | None,
    progress_cb=None,
    log_cb=None,
    cancel_event: threading.Event | None = None,
) -> FileItem:
    """Вычисляет недостающие хеши для одного файла с использованием кэша.

    Если размер и mtime совпадают с кэшем — хеши не пересчитываются.
    Модифицирует и возвращает тот же FileItem.
    """
    _log = make_log_bridge(log_cb)
    path = file.p

    need_quick = not file.quick_hash
    need_full = not file.full_hash

    if cache is not None:
        cached = cache.get_file(path)
        if cached is not None and cached.size == file.size and abs(cached.mtime - file.mtime) < 1e-6:
            if cached.quick_hash:
                file.quick_hash = cached.quick_hash
                need_quick = False
            if cached.full_hash:
                file.full_hash = cached.full_hash
                need_full = False

    try:
        if need_quick:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("Хеширование отменено")
            file.quick_hash = quick_hash_file(path, settings.quick_hash_bytes, settings.hash_algorithm)
        if need_full:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("Хеширование отменено")
            file.full_hash = full_hash_file(path, settings.hash_algorithm, cancel_event)
    except InterruptedError:
        file.status = "skipped"
        file.message = "Отменено"
        raise
    except PermissionError as exc:
        file.status = "locked"
        file.message = f"Нет прав / файл занят: {exc}"
        _log("warning", file.message + f" ({path})")
        return file
    except OSError as exc:
        file.status = "error"
        file.message = f"Ошибка чтения: {exc}"
        _log("warning", file.message + f" ({path})")
        return file

    file.status = "ok"
    file.message = ""
    if cache is not None:
        cache.upsert_file(file)
    if progress_cb:
        progress_cb(0, "")  # прогресс уровня списка считается вызывающим кодом
    return file


def hash_files(
    files: list[FileItem],
    settings: Settings,
    cache: Cache | None,
    progress_cb=None,
    log_cb=None,
    cancel_event: threading.Event | None = None,
    full: bool = True,
) -> list[FileItem]:
    """Хеширует список файлов (быстрый хеш всегда; полный — если full=True).

    Возвращает тот же список; статусы/хеши проставлены. Прогресс 0..100.
    """
    _log = make_log_bridge(log_cb)
    total = len(files)
    _log("info", f"Начало хеширования: {total} файлов")
    errors = 0
    for i, f in enumerate(files):
        if cancel_event is not None and cancel_event.is_set():
            _log("warning", "Хеширование отменено пользователем")
            break
        if not f.full_hash or not f.quick_hash:
            try:
                hash_file(f, settings, cache, None, log_cb, cancel_event)
            except InterruptedError:
                break
            if f.status in ("error", "locked"):
                errors += 1
        if progress_cb and total:
            progress_cb(int((i + 1) / total * 100), f"Хеширование: {i + 1}/{total}")
    _log("info", f"Хеширование завершено, ошибок: {errors}")
    return files
