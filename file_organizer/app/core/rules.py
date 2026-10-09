"""Правила структурирования: сопоставление файла с правилом и построение целевого пути.

Пользователь не пишет код — только выбирает тип правила и параметры.
Шаблоны строк проходят whitelist переменных {ext} {year} {month} {day} {stem} {name} {size}.
"""
from __future__ import annotations

import re
from pathlib import Path
from string import Formatter
from typing import Any

from app.core import constants
from app.core.logging_utils import get_logger
from app.core.models import FileItem, Rule, Settings

log = get_logger("rules")

_ALLOWED_VARS = set(constants.TEMPLATE_VARIABLES)
_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def safe_format(template: str, values: dict[str, Any]) -> str:
    """Форматирование шаблона только разрешёнными переменными.

    Неизвестные переменные оставляются как есть (без выполнения кода).
    """
    for name in _VAR_RE.findall(template):
        if name not in _ALLOWED_VARS:
            raise ValueError(f"Запрещённая переменная шаблона: {{{name}}}")
    # Ограничиваем поля формата: поддерживаем только {var}, без spec/attr
    fields = [f[1] for f in Formatter().parse(template)]
    for fld in fields:
        if fld is None:
            continue
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", str(fld)):
            raise ValueError(f"Недопустимый синтаксис шаблона: {template!r}")
    return template.format(**{k: v for k, v in values.items() if k in _ALLOWED_VARS})


class RuleMatcher:
    """Сопоставляет файлы с правилами и строит целевые пути."""

    def __init__(self, rules: list[Rule], target_root: Path | str):
        self.target_root = Path(str(target_root)).expanduser()
        self.rules = sorted(
            [r for r in rules if r.enabled], key=lambda r: (r.priority, r.name)
        )

    # ---------- загрузка ----------

    @staticmethod
    def load_rules(settings: Settings) -> "RuleMatcher":
        target = settings.target_folder or settings.working_folder
        return RuleMatcher(settings.rules, target or Path.cwd())

    # ---------- сопоставление ----------

    def match_file(self, file: FileItem) -> Rule | None:
        """Первое подходящее правило по приоритету; None — если не подходит."""
        for rule in self.rules:
            try:
                if self._matches(rule, file):
                    return rule
            except Exception as exc:  # noqa: BLE001 — плохое правило не роняет план
                log.warning("Ошибка правила '%s' на файле %s: %s", rule.name, file.path, exc)
        return None

    def _matches(self, rule: Rule, file: FileItem) -> bool:
        p = rule.params or {}
        if rule.type == "by_extension":
            exts = {e.lower() if e.startswith(".") else "." + e.lower()
                    for e in p.get("extensions", [])}
            return file.ext in exts
        if rule.type == "by_name_contains":
            sub = str(p.get("name_contains", "")).lower()
            return bool(sub) and sub in file.name.lower()
        if rule.type == "by_size":
            mn = int(p.get("min_size", 0) or 0)
            mx = int(p.get("max_size", 0) or 0)
            if file.size < mn:
                return False
            return not (mx and file.size > mx)
        if rule.type == "by_date":
            # by_date всегда матчится (раскладка по дате mtime), но может иметь фильтр годов
            years = p.get("years") or []
            if years:
                return file.mtime_dt.year in {int(y) for y in years}
            return True
        if rule.type == "custom":
            cond = p.get("condition", {})
            if "extensions" in cond:
                exts = {e.lower() if e.startswith(".") else "." + e.lower()
                        for e in cond["extensions"]}
                if file.ext not in exts:
                    return False
            if "name_contains" in cond:
                if str(cond["name_contains"]).lower() not in file.name.lower():
                    return False
            return bool(p.get("folder_template") or p.get("name_template"))
        return False

    # ---------- целевой путь ----------

    def template_values(self, file: FileItem) -> dict[str, Any]:
        dt = file.mtime_dt
        return {
            "ext": file.ext.lstrip("."),
            "year": f"{dt.year:04d}",
            "month": f"{dt.month:02d}",
            "day": f"{dt.day:02d}",
            "stem": file.stem,
            "name": file.name,
            "size": str(file.size),
        }

    def build_target(self, file: FileItem, rule: Rule | None, target_root: Path | str | None = None) -> Path:
        """Строит полный целевой путь файла для правила (None = Other)."""
        root = Path(str(target_root)).expanduser() if target_root else self.target_root
        values = self.template_values(file)

        if rule is None:
            folder = root / constants.FALLBACK_RULE_NAME
            return folder / file.name

        p = rule.params or {}
        if rule.type == "by_extension":
            folder_tpl = p.get("target_template", "{ext}")
        elif rule.type == "by_date":
            folder_tpl = p.get("target_template", "{year}/{month}")
        elif rule.type == "by_name_contains":
            folder_tpl = p.get("target_template", rule.name or "ByName")
        elif rule.type == "by_size":
            folder_tpl = p.get("target_template", rule.name or "BySize")
        else:  # custom
            folder_tpl = p.get("folder_template", rule.name or "Custom")

        try:
            rel_folder = safe_format(str(folder_tpl), values)
        except ValueError as exc:
            log.warning("Некорректный шаблон '%s': %s — используется Other", folder_tpl, exc)
            return (root / constants.FALLBACK_RULE_NAME) / file.name

        new_name = file.name
        if rule.type == "custom" and p.get("name_template"):
            try:
                candidate = safe_format(str(p["name_template"]), values)
                if candidate and _is_safe_name(candidate):
                    new_name = candidate
            except ValueError as exc:
                log.warning("Некорректный шаблон имени '%s': %s", p["name_template"], exc)

        folder = _sanitize_rel(root, rel_folder)
        return folder / new_name


def _is_safe_name(name: str) -> bool:
    """Имя файла не должно содержать путей/запрещённых символов Windows."""
    if not name or name in (".", ".."):
        return False
    bad = '<>:"/\\|?*'
    return not any(c in bad for c in name)


def _sanitize_rel(root: Path, rel: str) -> Path:
    """Безопасно склеивает root и относительный шаблон папки.

    Запрещает выход за пределы root (.. или абсолютные пути).
    """
    rel = rel.replace("\\", "/").strip("/")
    parts = []
    for part in rel.split("/"):
        if part in ("", ".", ".."):
            continue
        if _is_safe_name(part):
            parts.append(part)
    return root.joinpath(*parts) if parts else root


def default_rules() -> list[Rule]:
    """Набор правил для первого запуска (все выключены, чтобы пользователь включал сам)."""
    return [
        Rule(type="by_extension", name="Изображения", priority=10,
             params={"extensions": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"],
                     "target_template": "Images"}, enabled=False),
        Rule(type="by_extension", name="Документы", priority=20,
             params={"extensions": [".pdf", ".docx", ".xlsx", ".pptx", ".txt"],
                     "target_template": "Documents"}, enabled=False),
        Rule(type="by_extension", name="Архивы", priority=30,
             params={"extensions": [".zip", ".rar", ".7z", ".tar", ".gz"],
                     "target_template": "Archives"}, enabled=False),
        Rule(type="by_extension", name="Медиа", priority=40,
             params={"extensions": [".mp3", ".wav", ".flac", ".mp4", ".mkv", ".avi"],
                     "target_template": "Media"}, enabled=False),
        Rule(type="by_date", name="По датам", priority=50,
             params={"target_template": "{year}/{month}", "date_format": "%Y/%m"}, enabled=False),
        Rule(type="by_size", name="Большие файлы (>1 ГБ)", priority=60,
             params={"min_size": 1024 ** 3, "max_size": 0, "target_template": "BigFiles"}, enabled=False),
    ]
