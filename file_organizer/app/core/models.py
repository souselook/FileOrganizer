"""Модели данных приложения (чистые dataclass, без Qt).

Все модели сериализуемы в dict/JSON. Пути хранятся как строки
для совместимости с SQLite и JSON; FileItem.path возвращает pathlib.Path.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------- Статусы и действия ----------

STATUS_OK = "ok"
STATUS_SKIPPED = "skipped"
STATUS_CONFLICT = "conflict"
STATUS_ERROR = "error"
STATUS_LOCKED = "locked"
STATUS_PENDING = "pending"

ACTION_MOVE = "move"
ACTION_COPY = "copy"
ACTION_RENAME = "rename"
ACTION_TRASH = "trash"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class FileItem:
    """Один просканированный файл."""

    path: str = ""
    size: int = 0
    mtime: float = 0.0
    quick_hash: str = ""
    full_hash: str = ""
    is_hidden: bool = False
    status: str = STATUS_PENDING
    message: str = ""

    @property
    def p(self) -> Path:
        return Path(self.path)

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def stem(self) -> str:
        return Path(self.path).stem

    @property
    def ext(self) -> str:
        # Всегда нижний регистр с точкой: ".jpg"
        return Path(self.path).suffix.lower()

    @property
    def parent(self) -> str:
        return str(Path(self.path).parent)

    @property
    def mtime_dt(self) -> datetime:
        return datetime.fromtimestamp(self.mtime)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FileItem":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def from_path(cls, path: Path, stat_result=None) -> "FileItem":
        st = stat_result or path.stat()
        return cls(
            path=str(path),
            size=int(st.st_size),
            mtime=float(st.st_mtime),
        )


@dataclass
class DuplicateGroup:
    """Группа дубликатов."""

    group_id: str = field(default_factory=_new_id)
    files: list[FileItem] = field(default_factory=list)
    hash: str = ""
    size: int = 0

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def wasted_size(self) -> int:
        """Место, которое освободится, если оставить по одному файлу в группе."""
        return self.total_size - self.size if self.files else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "hash": self.hash,
            "size": self.size,
            "total_size": self.total_size,
            "wasted_size": self.wasted_size,
            "files": [f.to_dict() for f in self.files],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DuplicateGroup":
        return cls(
            group_id=d.get("group_id", _new_id()),
            hash=d.get("hash", ""),
            size=d.get("size", 0),
            files=[FileItem.from_dict(f) for f in d.get("files", [])],
        )


@dataclass
class Rule:
    """Правило структурирования."""

    id: str = field(default_factory=_new_id)
    type: str = "by_extension"  # by_extension | by_date | by_name_contains | by_size | custom
    name: str = ""
    enabled: bool = True
    priority: int = 100
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Rule":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class ActionPlanItem:
    """Одна операция в плане."""

    source: str = ""
    target: str = ""
    action: str = ACTION_MOVE  # move | copy | rename | trash
    rule_name: str = ""
    status: str = STATUS_PENDING  # ok | skipped | conflict | error | locked | pending
    conflict: bool = False
    message: str = ""

    @property
    def source_path(self) -> Path:
        return Path(self.source)

    @property
    def target_path(self) -> Path:
        return Path(self.target)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ActionPlanItem":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class ActionPlan:
    """План действий (предпросмотр перед применением)."""

    items: list[ActionPlanItem] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)

    def stats(self) -> dict[str, int]:
        s = {"move": 0, "copy": 0, "rename": 0, "trash": 0,
             "conflicts": 0, "errors": 0, "skipped": 0}
        for it in self.items:
            if it.status == STATUS_OK and it.action in s:
                s[it.action] += 1
            if it.conflict or it.status == STATUS_CONFLICT:
                s["conflicts"] += 1
            if it.status == STATUS_ERROR:
                s["errors"] += 1
            if it.status in (STATUS_SKIPPED, STATUS_LOCKED):
                s["skipped"] += 1
        return s

    @property
    def executable_items(self) -> list[ActionPlanItem]:
        return [it for it in self.items if it.status == STATUS_OK]

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "items": [i.to_dict() for i in self.items],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ActionPlan":
        return cls(
            created_at=d.get("created_at", _now_iso()),
            items=[ActionPlanItem.from_dict(i) for i in d.get("items", [])],
        )


@dataclass
class Operation:
    """Запись истории: что было сделано с файлом."""

    id: str = field(default_factory=_new_id)
    batch_id: str = ""
    timestamp: str = field(default_factory=_now_iso)
    action: str = ACTION_MOVE  # move | copy | rename | trash
    source: str = ""   # исходный путь (до операции)
    target: str = ""   # конечный путь (после операции) / путь в корзине
    status: str = STATUS_OK  # ok | undone | failed
    undoable: bool = True
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Operation":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class ScanResult:
    """Результат сканирования папки."""

    root: str = ""
    files: list[FileItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_files: int = 0
    scanned_count: int = 0
    skipped_count: int = 0
    canceled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "files": [f.to_dict() for f in self.files],
            "errors": self.errors,
            "total_files": self.total_files,
            "scanned_count": self.scanned_count,
            "skipped_count": self.skipped_count,
            "canceled": self.canceled,
        }


@dataclass
class ExecutionResult:
    """Результат применения плана."""

    executed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    canceled: bool = False
    batch_id: str = field(default_factory=_new_id)
    operations: list[Operation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "executed": self.executed,
            "skipped": self.skipped,
            "errors": self.errors,
            "canceled": self.canceled,
            "batch_id": self.batch_id,
            "operations": [o.to_dict() for o in self.operations],
        }


@dataclass
class Settings:
    """Настройки приложения. Явные, без глобальных переменных и синглетонов."""

    # Папки
    working_folder: str = ""
    target_folder: str = ""
    recursive: bool = True
    include_subfolders: bool = True

    # Фильтры
    skip_hidden: bool = True
    skip_temp: bool = True
    skip_symlinks: bool = True
    excluded_dirs: list[str] = field(default_factory=list)
    excluded_extensions: list[str] = field(default_factory=list)
    included_extensions: list[str] = field(default_factory=list)  # пусто = все
    min_size: int = 0
    max_size: int = 0

    # Хеширование
    hash_algorithm: str = "sha256"
    quick_hash_bytes: int = 4096

    # Дубликаты
    duplicate_mode: str = "exact"

    # Структурирование / безопасность
    rules: list[Rule] = field(default_factory=list)
    allowed_actions: list[str] = field(default_factory=lambda: ["move"])
    conflict_policy: str = "unique_name"
    create_folders: bool = True
    unique_names: bool = True
    trash_only: bool = True  # жёсткое удаление запрещено всегда
    trash_mode: str = "internal"  # internal | system

    # История
    history_limit: int = 1000

    # Интерфейс
    theme: str = "light"
    language: str = "ru"

    def normalized(self) -> "Settings":
        """Нормализует пути и расширения. Возвращает себя для цепочки."""
        if self.working_folder:
            self.working_folder = str(Path(self.working_folder).expanduser())
        if self.target_folder:
            self.target_folder = str(Path(self.target_folder).expanduser())
        self.excluded_extensions = [
            e if e.startswith(".") else "." + e for e in
            (x.strip().lower() for x in self.excluded_extensions if x and x.strip())
        ]
        self.included_extensions = [
            e if e.startswith(".") else "." + e for e in
            (x.strip().lower() for x in self.included_extensions if x and x.strip())
        ]
        self.excluded_dirs = [d.strip() for d in self.excluded_dirs if d and d.strip()]
        return self

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["rules"] = [r.to_dict() if isinstance(r, Rule) else r for r in self.rules]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Settings":
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in d.items() if k in known}
        rules_raw = clean.pop("rules", [])
        settings = cls(**clean)
        settings.rules = [
            r if isinstance(r, Rule) else Rule.from_dict(r) for r in rules_raw
        ]
        return settings
