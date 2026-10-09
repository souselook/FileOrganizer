"""Сканирование папки: рекурсивный обход, фильтры, ошибки, прогресс, отмена, кэш.

Функция чистая (без Qt): progress_cb(percent:int, message:str),
log_cb(level:str, message:str), cancel_event: threading.Event.
"""
from __future__ import annotations

import os
import stat as stat_module
import threading
from pathlib import Path

from app.core.cache import Cache
from app.core.logging_utils import get_logger, make_log_bridge
from app.core.models import FileItem, ScanResult, Settings

log = get_logger("scanner")

_PROGRESS_EVERY = 200  # сообщать в UI не на каждый файл


def _is_hidden(path: Path) -> bool:
    """Проверка скрытости: точка в имени (POSIX) или атрибут FILE_ATTRIBUTE_HIDDEN (Windows)."""
    name = path.name
    if name.startswith("."):
        return True
    # ST_ATTR_HIDDEN есть только на Windows; на других ОС проверяем через st_file_attributes
    hidden_attr = getattr(stat_module, "ST_ATTR_HIDDEN", 0)
    try:
        attrs = getattr(path.stat(), "st_file_attributes", 0)
        return bool(hidden_attr and attrs & hidden_attr)
    except OSError:
        return False


def scan_folder(
    settings: Settings,
    cache: Cache | None,
    progress_cb=None,
    log_cb=None,
    cancel_event: threading.Event | None = None,
) -> ScanResult:
    """Сканирует settings.working_folder согласно фильтрам настроек."""
    _log = make_log_bridge(log_cb)
    result = ScanResult(root=settings.working_folder)

    root = Path(settings.working_folder).expanduser()
    if not settings.working_folder or not root.exists() or not root.is_dir():
        result.errors.append(f"Папка не найдена: {settings.working_folder}")
        _log("error", f"Папка не найдена: {settings.working_folder}")
        return result

    _log("info", f"Начало сканирования: {root}")

    excluded_dirs_lower = {d.lower() for d in settings.excluded_dirs}
    excluded_exts = set(settings.excluded_extensions)
    included_exts = set(settings.included_extensions)
    min_size = settings.min_size
    max_size = settings.max_size

    total_seen = 0
    processed = 0
    stack: list[Path] = [root]
    visited_roots: set[str] = set()

    while stack:
        if cancel_event is not None and cancel_event.is_set():
            result.canceled = True
            _log("warning", "Сканирование отменено пользователем")
            break

        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except (PermissionError, OSError) as exc:
            result.errors.append(f"{current}: {exc}")
            _log("warning", f"Нет доступа к папке {current}: {exc}")
            continue

        for entry in entries:
            if cancel_event is not None and cancel_event.is_set():
                result.canceled = True
                break
            try:
                ep = Path(entry.path)
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    result.errors.append(f"{ep}: {exc}")
                    _log("warning", f"Не удалось получить информацию о {ep}: {exc}")
                    continue

                is_link = stat_module.S_ISLNK(st.st_mode)
                if not stat_module.S_ISDIR(st.st_mode):
                    if not stat_module.S_ISREG(st.st_mode):
                        result.skipped_count += 1
                        continue  # сокеты, fifo и пр.
                    total_seen += 1
                    item = _process_file(
                        ep, st, is_link, settings, excluded_dirs_lower,
                        excluded_exts, included_exts, min_size, max_size, cache,
                    )
                    if item is not None:
                        result.files.append(item)
                        result.scanned_count += 1
                    else:
                        result.skipped_count += 1

                    processed += 1
                    if progress_cb and processed % _PROGRESS_EVERY == 0:
                        progress_cb(
                            min(99, int(processed / max(total_seen, 1) * 100)),
                            f"Просканировано файлов: {processed}",
                        )
                else:
                    # Каталог: проверяем исключения и идём дальше
                    if entry.name.lower() in excluded_dirs_lower:
                        result.skipped_count += 1
                        continue
                    if is_link and settings.skip_symlinks:
                        continue
                    if settings.skip_hidden and _is_hidden(ep):
                        continue
                    real = str(ep)
                    if real in visited_roots:
                        continue
                    visited_roots.add(real)
                    if settings.recursive or ep == root:
                        stack.append(ep)
            except Exception as exc:  # noqa: BLE001 — один плохой файл не роняет скан
                result.errors.append(f"{entry.path}: {exc}")
                _log("warning", f"Ошибка обработки {entry.path}: {exc}")

        if result.canceled:
            break

    result.total_files = total_seen
    if cache is not None:
        cache.upsert_many(result.files)

    _log(
        "info",
        f"Сканирование завершено: файлов {result.scanned_count}, "
        f"пропущено {result.skipped_count}, ошибок {len(result.errors)}",
    )
    if progress_cb:
        progress_cb(100, f"Найдено файлов: {result.scanned_count}")
    return result


def _process_file(
    ep: Path,
    st: os.stat_result,
    is_link: bool,
    settings: Settings,
    excluded_dirs_lower: set[str],
    excluded_exts: set[str],
    included_exts: set[str],
    min_size: int,
    max_size: int,
    cache: Cache | None,
) -> FileItem | None:
    """Возвращает FileItem, либо None если файл пропущен по фильтрам."""
    # Пропуск файлов внутри исключённых папок (например C:/Windows/notepad.exe)
    parts_lower = {p.lower() for p in ep.parent.parts}
    if parts_lower & excluded_dirs_lower:
        return None

    if is_link and settings.skip_symlinks:
        return None
    if settings.skip_hidden and _is_hidden(ep):
        return None

    ext = ep.suffix.lower()
    if settings.skip_temp and ext in excluded_exts:
        return None
    if included_exts and ext not in included_exts:
        return None

    size = int(st.st_size)
    if size < min_size:
        return None
    if max_size and size > max_size:
        return None

    item = FileItem(
        path=str(ep),
        size=size,
        mtime=float(st.st_mtime),
        is_hidden=_is_hidden(ep),
    )

    # Используем кэш: если size и mtime не изменились — берём хеши из кэша
    if cache is not None:
        cached = cache.get_file(ep)
        if cached is not None and cached.size == item.size and abs(cached.mtime - item.mtime) < 1e-6:
            item.quick_hash = cached.quick_hash
            item.full_hash = cached.full_hash

    return item
