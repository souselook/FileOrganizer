"""Поиск дубликатов.

Пайплайн режима exact: размер -> быстрый хеш -> полный хеш.
Другие режимы: name_size, name_only, size_only.
Хеши берутся из кэша, если файл не менялся (см. hasher).
"""
from __future__ import annotations

import threading
from collections import defaultdict

from app.core.cache import Cache
from app.core.hasher import hash_files
from app.core.logging_utils import get_logger, make_log_bridge
from app.core.models import DuplicateGroup, FileItem, Settings

log = get_logger("duplicates")


def find_duplicates(
    files: list[FileItem],
    settings: Settings,
    cache: Cache | None,
    progress_cb=None,
    log_cb=None,
    cancel_event: threading.Event | None = None,
) -> list[DuplicateGroup]:
    """Возвращает группы дубликатов, отсортированные по убыванию wasted_size."""
    _log = make_log_bridge(log_cb)
    mode = settings.duplicate_mode
    _log("info", f"Поиск дубликатов, режим: {mode}, файлов: {len(files)}")

    groups: list[list[FileItem]] = []

    if mode == "name_only":
        by_key: dict[tuple, list[FileItem]] = defaultdict(list)
        for f in files:
            by_key[f.name.lower()].append(f)
        groups = [g for g in by_key.values() if len(g) > 1]

    elif mode == "size_only":
        by_size = defaultdict(list)
        for f in files:
            by_size[f.size].append(f)
        groups = [g for g in by_size.values() if len(g) > 1]

    elif mode == "name_size":
        by_key = defaultdict(list)
        for f in files:
            by_key[(f.name.lower(), f.size)].append(f)
        groups = [g for g in by_key.values() if len(g) > 1]

    else:  # exact: size -> quick hash -> full hash
        groups = _find_exact(files, settings, cache, progress_cb, log_cb, cancel_event)

    result: list[DuplicateGroup] = []
    for g in groups:
        size = g[0].size
        digest = g[0].full_hash or g[0].quick_hash or str(size)
        result.append(DuplicateGroup(files=g, size=size, hash=digest))

    result.sort(key=lambda dg: dg.wasted_size, reverse=True)
    wasted = sum(dg.wasted_size for dg in result)
    _log(
        "info",
        f"Найдено групп дубликатов: {len(result)}, "
        f"освобождаемое место: {wasted} байт",
    )
    if progress_cb:
        progress_cb(100, f"Групп дубликатов: {len(result)}")
    return result


def _find_exact(files, settings, cache, progress_cb, log_cb, cancel_event):
    _log = make_log_bridge(log_cb)

    # 1. Группировка по размеру — дешёвая операция, отсекает большинство файлов
    by_size: dict[int, list[FileItem]] = defaultdict(list)
    for f in files:
        by_size[f.size].append(f)
    candidates = [g for g in by_size.values() if len(g) > 1]
    candidate_files = [f for g in candidates for f in g]
    if not candidate_files:
        return []

    # 2. Быстрые хеши только для кандидатов
    hash_files(candidate_files, settings, cache, progress_cb, log_cb, cancel_event, full=False)
    if cancel_event is not None and cancel_event.is_set():
        return []

    # 3. Группировка по (размер, быстрый хеш)
    by_quick: dict[tuple, list[FileItem]] = defaultdict(list)
    for f in candidate_files:
        if f.quick_hash:
            by_quick[(f.size, f.quick_hash)].append(f)
    q_groups = [g for g in by_quick.values() if len(g) > 1]

    # 4. Полный хеш только там, где быстрый хеш совпал
    need_full = [f for g in q_groups for f in g if not f.full_hash]
    if need_full:
        total = len(need_full)
        done = 0
        for f in need_full:
            if cancel_event is not None and cancel_event.is_set():
                _log("warning", "Поиск дубликатов отменён")
                return []
            from app.core.hasher import hash_file
            try:
                hash_file(f, settings, cache, None, log_cb, cancel_event)
            except InterruptedError:
                return []
            done += 1
            if progress_cb and total:
                progress_cb(int(done / total * 100), f"Проверка содержимого: {done}/{total}")

    by_full: dict[tuple, list[FileItem]] = defaultdict(list)
    for g in q_groups:
        for f in g:
            if f.full_hash:
                by_full[(f.size, f.full_hash)].append(f)
    return [grp for grp in by_full.values() if len(grp) > 1]
