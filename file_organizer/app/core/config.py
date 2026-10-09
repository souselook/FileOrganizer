"""Загрузка/сохранение настроек из JSON (%APPDATA%/FileOrganizer/settings.json).

Никаких глобальных объектов-настроек: функции принимают явный path.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.core import constants
from app.core.logging_utils import get_logger
from app.core.models import Rule, Settings

log = get_logger("config")


def default_settings() -> Settings:
    """Настройки по умолчанию."""
    return Settings(
        skip_hidden=True,
        skip_temp=True,
        skip_symlinks=True,
        excluded_dirs=list(constants.DEFAULT_EXCLUDED_DIRS),
        excluded_extensions=list(constants.DEFAULT_EXCLUDED_EXTENSIONS),
        min_size=constants.DEFAULT_MIN_SIZE,
        max_size=constants.DEFAULT_MAX_SIZE,
        hash_algorithm=constants.HASH_ALGORITHM,
        quick_hash_bytes=constants.QUICK_HASH_BYTES,
        duplicate_mode=constants.DEFAULT_DUPLICATE_MODE,
        allowed_actions=list(constants.DEFAULT_ALLOWED_ACTIONS),
        conflict_policy=constants.DEFAULT_CONFLICT_POLICY,
        trash_mode=constants.DEFAULT_TRASH_MODE,
        history_limit=constants.DEFAULT_HISTORY_LIMIT,
        theme=constants.DEFAULT_THEME,
        rules=[],
    )


def validate_settings(settings: Settings) -> list[str]:
    """Возвращает список ошибок. Пустой список — настройки валидны.

    Некорректные значения исправляются на безопасные по умолчанию.
    """
    errors: list[str] = []

    if settings.hash_algorithm not in constants.SUPPORTED_HASH_ALGORITHMS:
        errors.append(f"Неизвестный алгоритм хеша: {settings.hash_algorithm}")
        settings.hash_algorithm = constants.HASH_ALGORITHM

    if settings.duplicate_mode not in constants.DUPLICATE_MODES:
        errors.append(f"Неизвестный режим дубликатов: {settings.duplicate_mode}")
        settings.duplicate_mode = constants.DEFAULT_DUPLICATE_MODE

    if settings.theme not in constants.THEMES:
        errors.append(f"Неизвестная тема: {settings.theme}")
        settings.theme = constants.DEFAULT_THEME

    if settings.trash_mode not in constants.TRASH_MODES:
        errors.append(f"Неизвестный режим корзины: {settings.trash_mode}")
        settings.trash_mode = constants.DEFAULT_TRASH_MODE

    if settings.conflict_policy not in constants.CONFLICT_POLICIES:
        settings.conflict_policy = constants.DEFAULT_CONFLICT_POLICY

    bad_actions = [a for a in settings.allowed_actions if a not in constants.ACTION_TYPES]
    if bad_actions:
        errors.append(f"Недопустимые действия: {bad_actions}")
        settings.allowed_actions = [
            a for a in settings.allowed_actions if a in constants.ACTION_TYPES
        ]

    if settings.quick_hash_bytes < 0:
        settings.quick_hash_bytes = constants.QUICK_HASH_BYTES
    if settings.min_size < 0:
        settings.min_size = 0
    if settings.max_size < 0:
        settings.max_size = 0
    if settings.min_size and settings.max_size and settings.max_size < settings.min_size:
        errors.append("max_size меньше min_size — ограничение снято")
        settings.max_size = 0

    if settings.history_limit < 1:
        settings.history_limit = constants.DEFAULT_HISTORY_LIMIT

    # Безопасность: жёсткое удаление запрещено всегда
    settings.trash_only = True

    valid_rules: list[Rule] = []
    for r in settings.rules:
        if r.type not in constants.RULE_TYPES:
            errors.append(f"Правило '{r.name}': неизвестный тип {r.type}")
            continue
        valid_rules.append(r)
    settings.rules = valid_rules

    return errors


def load_settings(path: Path | None = None) -> Settings:
    """Читает settings.json. При повреждении/отсутствии — дефолтные настройки."""
    path = Path(path) if path else constants.SETTINGS_FILE
    if not path.exists():
        return default_settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        settings = Settings.from_dict(raw).normalized()
        errors = validate_settings(settings)
        for e in errors:
            log.warning("Валидация настроек: %s", e)
        return settings
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        log.error("Не удалось прочитать настройки %s: %s. Используются значения по умолчанию.", path, exc)
        return default_settings()


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """Атомарно сохраняет настройки (запись во временный файл + replace)."""
    path = Path(path) if path else constants.SETTINGS_FILE
    validate_settings(settings)
    settings.normalized()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError as exc:
        log.error("Не удалось сохранить настройки %s: %s", path, exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
