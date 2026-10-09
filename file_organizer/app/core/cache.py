"""SQLite-кэш информации о файлах (пути, размер, mtime, хеши).

Потокобезопасность: соединение создаётся с check_same_thread=False,
все операции под threading.Lock — кэш используется из фоновых потоков.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from app.core import constants
from app.core.logging_utils import get_logger
from app.core.models import FileItem

log = get_logger("cache")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE,
    size INTEGER,
    mtime REAL,
    quick_hash TEXT,
    full_hash TEXT,
    updated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
CREATE INDEX IF NOT EXISTS idx_files_size ON files(size);
CREATE INDEX IF NOT EXISTS idx_files_quick_hash ON files(quick_hash);
"""


def _norm_key(path: Path | str) -> str:
    """Нормализованный ключ пути для SQLite (учёт Windows-регистр/разделители)."""
    p = Path(str(path)).expanduser()
    try:
        resolved = str(p.resolve(strict=False))
    except OSError:
        resolved = str(p)
    # На Windows путь регистронезависимый (drive вида "C:" присутствует только на Windows)
    if Path(resolved).drive:
        resolved = resolved.lower()
    return resolved.replace("\\", "/")


class Cache:
    """Кэш файлов. Явная зависимость: создаётся в main и передаётся в core-функции."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path) if db_path else constants.CACHE_DB
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self.init_db()

    # ---------- lifecycle ----------

    def init_db(self) -> None:
        with self._lock:
            # каталог создаём лениво — constants могут быть переопределены после импорта
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self.db_path), timeout=10, check_same_thread=False
            )
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.commit()
                    self._conn.close()
                except sqlite3.Error as exc:
                    log.warning("Ошибка закрытия кэша: %s", exc)
                finally:
                    self._conn = None

    # ---------- CRUD ----------

    def upsert_file(self, file: FileItem) -> None:
        key = _norm_key(file.path)
        with self._lock:
            assert self._conn is not None, "Cache closed"
            try:
                self._conn.execute(
                    """INSERT INTO files(path, size, mtime, quick_hash, full_hash, updated_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(path) DO UPDATE SET
                         size=excluded.size, mtime=excluded.mtime,
                         quick_hash=excluded.quick_hash, full_hash=excluded.full_hash,
                         updated_at=excluded.updated_at""",
                    (key, file.size, file.mtime, file.quick_hash, file.full_hash, time.time()),
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                log.warning("Ошибка upsert кэша %s: %s", file.path, exc)

    def upsert_many(self, files: list[FileItem]) -> None:
        if not files:
            return
        rows = [
            (_norm_key(f.path), f.size, f.mtime, f.quick_hash, f.full_hash, time.time())
            for f in files
        ]
        with self._lock:
            assert self._conn is not None, "Cache closed"
            try:
                self._conn.executemany(
                    """INSERT INTO files(path, size, mtime, quick_hash, full_hash, updated_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(path) DO UPDATE SET
                         size=excluded.size, mtime=excluded.mtime,
                         quick_hash=excluded.quick_hash, full_hash=excluded.full_hash,
                         updated_at=excluded.updated_at""",
                    rows,
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                log.warning("Ошибка пакетного upsert кэша: %s", exc)

    def get_file(self, path: Path | str) -> FileItem | None:
        key = _norm_key(path)
        with self._lock:
            assert self._conn is not None, "Cache closed"
            cur = self._conn.execute(
                "SELECT path, size, mtime, quick_hash, full_hash FROM files WHERE path=?",
                (key,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return FileItem(
            path=str(path), size=int(row[1]), mtime=float(row[2]),
            quick_hash=row[3] or "", full_hash=row[4] or "",
        )

    def is_stale(self, file: FileItem) -> bool:
        """True, если файл в кэше отсутствует или size/mtime изменились."""
        cached = self.get_file(file.path)
        if cached is None:
            return True
        return cached.size != file.size or abs(cached.mtime - file.mtime) > 1e-6

    def remove_path(self, path: Path | str) -> None:
        key = _norm_key(path)
        with self._lock:
            assert self._conn is not None, "Cache closed"
            try:
                self._conn.execute("DELETE FROM files WHERE path=?", (key,))
                self._conn.commit()
            except sqlite3.Error as exc:
                log.warning("Ошибка удаления из кэша %s: %s", path, exc)

    def clear(self) -> int:
        """Очищает весь кэш. Возвращает количество удалённых записей."""
        with self._lock:
            assert self._conn is not None, "Cache closed"
            n = self._conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            self._conn.execute("DELETE FROM files")
            self._conn.commit()
        log.info("Кэш очищен, удалено записей: %d", n)
        return n

    def count(self) -> int:
        with self._lock:
            assert self._conn is not None, "Cache closed"
            return self._conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
