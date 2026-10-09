"""Базовые константы приложения FileOrganizer.

Не содержит зависимостей от Qt. Пути переносимы между ОС,
на Windows используются %APPDATA%/FileOrganizer.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "FileOrganizer"
APP_VERSION = "1.0.0"


def _appdata_dir() -> Path:
    """Каталог данных приложения (%APPDATA%/FileOrganizer на Windows)."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    # Fallback для разработки на Linux/macOS
    base = os.environ.get("FILEORGANIZER_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


APP_DIR = _appdata_dir()
SETTINGS_FILE = APP_DIR / "settings.json"
CACHE_DB = APP_DIR / "cache.db"
HISTORY_DB = APP_DIR / "history.db"
TRASH_DIR = APP_DIR / "trash"
LOGS_DIR = APP_DIR / "logs"
LOG_FILE = LOGS_DIR / "app.log"

# Папки, которые пропускаются по умолчанию (регистронезависимо)
DEFAULT_EXCLUDED_DIRS = [
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "$RECYCLE.BIN",
    "System Volume Information",
    "AppData",
    "Windows",
]

# Временные/служебные расширения, пропускаемые по умолчанию
DEFAULT_EXCLUDED_EXTENSIONS = [
    ".tmp", ".temp", ".bak", ".swp", ".dmp", ".lnk", ".part", ".crdownload",
]

# Ограничения размера по умолчанию (байты); 0 = не ограничивать
DEFAULT_MIN_SIZE = 0
DEFAULT_MAX_SIZE = 0

# Сколько первых байт использовать для быстрого хеша
QUICK_HASH_BYTES = 4096

HASH_ALGORITHM = "sha256"
SUPPORTED_HASH_ALGORITHMS = ["sha256", "sha1", "md5"]

# Режимы поиска дубликатов
DUPLICATE_MODES = ["exact", "name_size", "name_only", "size_only"]
DEFAULT_DUPLICATE_MODE = "exact"

# Разрешённые действия
ACTION_TYPES = ["move", "copy", "rename", "trash"]
DEFAULT_ALLOWED_ACTIONS = ["move"]

# Политики разрешения конфликтов имён
CONFLICT_POLICIES = ["unique_name", "skip", "ask"]
DEFAULT_CONFLICT_POLICY = "unique_name"

# Темы интерфейса
THEMES = ["light", "dark"]
DEFAULT_THEME = "light"

# Корзина: внутренняя корзина приложения (undo доступен полностью)
# или системная корзина Windows через send2trash (undo может быть недоступен)
TRASH_MODES = ["internal", "system"]
DEFAULT_TRASH_MODE = "internal"

DEFAULT_HISTORY_LIMIT = 1000

# Типы правил структурирования
RULE_TYPES = ["by_extension", "by_date", "by_name_contains", "by_size", "custom"]

# Разрешённые переменные шаблона целевого пути
TEMPLATE_VARIABLES = ["ext", "year", "month", "day", "stem", "name", "size"]

FALLBACK_RULE_NAME = "Other"
