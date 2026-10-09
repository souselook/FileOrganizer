"""История операций и undo. SQLite (%APPDATA%/FileOrganizer/history.db).

undo_last / undo_batch выполняют действия в обратном порядке:
- move   -> вернуть файл обратно
- rename -> вернуть старое имя
- copy   -> удалить скопированный файл в корзину (не жёстко!)
- trash  -> восстановить из внутренней корзины; для системной — честно сообщаем
"""
from __future__ import annotations

import csv
import shutil
import sqlite3
import threading
import uuid
from pathlib import Path

from app.core import constants
from app.core.logging_utils import get_logger
from app.core.models import (
    ACTION_COPY,
    ACTION_MOVE,
    ACTION_RENAME,
    ACTION_TRASH,
    FileItem,
    Operation,
)

log = get_logger("history")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS operations(
    id TEXT PRIMARY KEY,
    batch_id TEXT,
    timestamp TEXT,
    action TEXT,
    source TEXT,
    target TEXT,
    status TEXT,
    undoable INTEGER,
    message TEXT,
    seq INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ops_batch ON operations(batch_id);
CREATE INDEX IF NOT EXISTS idx_ops_seq ON operations(seq);
"""


class History:
    def __init__(self, db_path: Path | None = None, limit: int = constants.DEFAULT_HISTORY_LIMIT):
        self.db_path = Path(db_path) if db_path else constants.HISTORY_DB
        self.limit = max(1, int(limit))
        self._lock = threading.Lock()
        # каталог создаём лениво — constants могут быть переопределены после импорта
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), timeout=10, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---------- запись ----------

    def record_operation(self, operation: Operation) -> None:
        self.record_batch([operation], operation.batch_id or uuid.uuid4().hex)

    def record_batch(self, operations: list[Operation], batch_id: str) -> None:
        with self._lock:
            cur = self._conn.cursor()
            last = cur.execute("SELECT COALESCE(MAX(seq), 0) FROM operations").fetchone()[0]
            for i, op in enumerate(operations):
                op.batch_id = batch_id
                cur.execute(
                    "INSERT OR REPLACE INTO operations"
                    "(id, batch_id, timestamp, action, source, target, status, undoable, message, seq)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (op.id, op.batch_id, op.timestamp, op.action, op.source, op.target,
                     op.status, int(op.undoable), op.message, last + 1 + i),
                )
            self._conn.commit()
        self._trim()

    def _trim(self) -> None:
        """Храним не больше settings.history_limit последних записей."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM operations WHERE seq <= ("
                " SELECT MAX(seq) - ? FROM operations)",
                (self.limit,),
            )
            self._conn.commit()

    # ---------- чтение ----------

    def get_recent(self, limit: int = 100) -> list[Operation]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,batch_id,timestamp,action,source,target,status,undoable,message,seq"
                " FROM operations ORDER BY seq DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            Operation(id=r[0], batch_id=r[1], timestamp=r[2], action=r[3], source=r[4],
                      target=r[5], status=r[6], undoable=bool(r[7]), message=r[8])
            for r in rows
        ]

    def last_batch_id(self) -> str | None:
        ops = self.get_recent(1)
        return ops[0].batch_id if ops else None

    # ---------- undo ----------

    def undo_last(self) -> tuple[int, list[str]]:
        """Отменяет последний batch. Возвращает (отменено, список проблем)."""
        batch = self.last_batch_id()
        if not batch:
            return 0, ["История пуста — отменять нечего"]
        return self.undo_batch(batch)

    def undo_batch(self, batch_id: str) -> tuple[int, list[str]]:
        """Отменяет операции batch в обратном порядке."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,batch_id,timestamp,action,source,target,status,undoable,message,seq"
                " FROM operations WHERE batch_id=? AND status='ok' ORDER BY seq DESC",
                (batch_id,),
            ).fetchall()
        undone, problems = 0, []
        for r in rows:
            op = Operation(id=r[0], batch_id=r[1], timestamp=r[2], action=r[3], source=r[4],
                           target=r[5], status=r[6], undoable=bool(r[7]), message=r[8])
            if not op.undoable:
                problems.append(
                    f"{op.source}: Undo для удаления в системную корзину недоступен"
                )
                continue
            err = self._undo_one(op)
            if err:
                problems.append(err)
            else:
                undone += 1
                with self._lock:
                    self._conn.execute(
                        "UPDATE operations SET status='undone' WHERE id=?", (op.id,)
                    )
                    self._conn.commit()
        log.info("Undo batch %s: отменено %d, проблем %d", batch_id, undone, len(problems))
        return undone, problems

    def _undo_one(self, op: Operation) -> str | None:
        """Возвращает сообщение об ошибке или None при успехе."""
        try:
            if op.action in (ACTION_MOVE, ACTION_RENAME):
                src_now, original = Path(op.target), Path(op.source)
                if not src_now.exists():
                    return f"Не найден файл для возврата: {src_now}"
                if original.exists():
                    return f"Место возврата занято: {original}"
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src_now), str(original))
                return None

            if op.action == ACTION_COPY:
                copied = Path(op.target)
                if not copied.exists():
                    return f"Скопированный файл не найден: {copied}"
                # Удаление только в корзину!
                trash = Path(constants.TRASH_DIR) / ("copy_undo_" + uuid.uuid4().hex[:8])
                trash.mkdir(parents=True, exist_ok=True)
                shutil.move(str(copied), str(trash / copied.name))
                return None

            if op.action == ACTION_TRASH:
                in_trash = Path(op.target)
                original = Path(op.source)
                if not in_trash.exists():
                    return f"Файл не найден в корзине: {in_trash}"
                if original.exists():
                    return f"Исходный путь уже занят: {original}"
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(in_trash), str(original))
                return None

            return f"Неизвестное действие для undo: {op.action}"
        except (OSError, shutil.Error) as exc:
            return f"Ошибка undo для {op.source}: {exc}"

    # ---------- обслуживание ----------

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM operations")
            self._conn.commit()
        log.info("История очищена")

    def export_csv(self, path: Path | str) -> int:
        path = Path(path)
        ops = self.get_recent(limit=self.limit)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Время", "Действие", "Файл", "Исходный путь", "Конечный путь", "Статус"])
            for op in reversed(ops):
                w.writerow([op.timestamp, op.action, Path(op.source).name,
                            op.source, op.target, op.status])
        return len(ops)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    def __enter__(self) -> "History":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
