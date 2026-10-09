"""Построение плана действий (только предпросмотр, никаких изменений на диске).

Учитывает: разрешённые действия, конфликты имён, запрет перезаписи,
уникальные имена file (1).txt, запрет перемещения в себя, защиту от
вложенности цели внутри источника при move.
"""
from __future__ import annotations

from pathlib import Path

from app.core.logging_utils import get_logger, make_log_bridge
from app.core.models import (
    ACTION_COPY,
    ACTION_MOVE,
    ACTION_RENAME,
    ActionPlan,
    ActionPlanItem,
    FileItem,
    Settings,
    STATUS_CONFLICT,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_SKIPPED,
)
from app.core.rules import RuleMatcher

log = get_logger("organizer")

_WINDOWS_FORBIDDEN = set('<>:"/\\|?*')


def unique_target(target: Path, taken: set[str], policy: str) -> tuple[Path, bool]:
    """Возвращает (свободный путь, был ли конфликт).

    policy unique_name -> file.txt, file (1).txt, file (2).txt ...
    policy skip        -> возвращает исходный target с флагом конфликта.
    """
    conflict = str(target).lower() in taken or target.exists()
    if not conflict:
        return target, False
    if policy != "unique_name":
        return target, True
    stem, suffix = target.stem, target.suffix
    parent = target.parent
    i = 1
    while True:
        candidate = parent / f"{stem} ({i}){suffix}"
        if not (str(candidate).lower() in taken or candidate.exists()):
            return candidate, True
        i += 1


def build_plan(
    files: list[FileItem],
    rules: RuleMatcher,
    settings: Settings,
    progress_cb=None,
    log_cb=None,
) -> ActionPlan:
    """Строит ActionPlan по файлам и правилам. Диск не изменяется."""
    _log = make_log_bridge(log_cb)
    plan = ActionPlan()
    allowed = set(settings.allowed_actions)
    action = next((a for a in (ACTION_MOVE, ACTION_COPY, ACTION_RENAME) if a in allowed), None)
    if action is None:
        _log("error", "В настройках не выбрано ни одного разрешённого действия")
        return plan

    target_root = Path(rules.target_root)
    _log("info", f"Построение плана: файлов {len(files)}, действие '{action}'")

    # Занятые целевые пути (учитываем и существующие файлы, и уже запланированные цели)
    taken: set[str] = {str(f.p).lower() for f in files}

    total = len(files)
    for idx, f in enumerate(files):
        item = ActionPlanItem(source=f.path, action=action, status=STATUS_OK)
        src = f.p

        if not src.exists():
            item.status = STATUS_ERROR
            item.message = "Файл недоступен"
            plan.items.append(item)
            continue

        rule = rules.match_file(f)
        item.rule_name = rule.name if rule else "Other"

        try:
            tgt = rules.build_target(f, rule, target_root)
        except Exception as exc:  # noqa: BLE001
            item.status = STATUS_ERROR
            item.message = f"Ошибка построения пути: {exc}"
            plan.items.append(item)
            continue

        # Проверка безопасности целевого имени
        if any(c in tgt.name for c in _WINDOWS_FORBIDDEN - {":"}):
            item.status = STATUS_ERROR
            item.message = f"Недопустимое имя файла: {tgt.name}"
            plan.items.append(item)
            continue

        same_path = _same_path(src, tgt)

        if action == ACTION_MOVE:
            if same_path:
                item.status = STATUS_SKIPPED
                item.message = "Файл уже находится в целевой папке"
                item.target = str(tgt)
                plan.items.append(item)
                continue
            # запрет бесконечной вложенности: нельзя переместить папку внутрь неё самой
            if _is_within(tgt, src):
                item.status = STATUS_ERROR
                item.message = "Целевая папка находится внутри перемещаемого файла"
                plan.items.append(item)
                continue
            resolved, had_conflict = unique_target(tgt, taken, settings.conflict_policy)
            if had_conflict and settings.conflict_policy != "unique_name":
                item.status = STATUS_CONFLICT
                item.conflict = True
                item.target = str(tgt)
                item.message = "Конфликт имён (перезапись запрещена)"
                plan.items.append(item)
                continue
            item.target = str(resolved)
            taken.add(str(resolved).lower())

        elif action == ACTION_COPY:
            if same_path:
                item.status = STATUS_SKIPPED
                item.message = "Источник и цель совпадают"
                item.target = str(tgt)
                plan.items.append(item)
                continue
            resolved, had_conflict = unique_target(tgt, taken, settings.conflict_policy)
            if had_conflict and settings.conflict_policy != "unique_name":
                item.status = STATUS_CONFLICT
                item.conflict = True
                item.target = str(tgt)
                item.message = "Конфликт имён (перезапись запрещена)"
                plan.items.append(item)
                continue
            item.target = str(resolved)
            taken.add(str(resolved).lower())

        else:  # rename — переименование в той же папке
            new_name = tgt.name
            resolved = src.with_name(new_name)
            if _same_path(src, resolved):
                resolved, had_conflict = unique_target(resolved, taken, settings.conflict_policy)
                if had_conflict and settings.conflict_policy != "unique_name":
                    item.status = STATUS_CONFLICT
                    item.conflict = True
                    item.message = "Конфликт имён"
                    plan.items.append(item)
                    continue
            item.target = str(resolved)
            taken.add(str(resolved).lower())

        plan.items.append(item)

        if progress_cb and total and idx % 200 == 0:
            progress_cb(int(idx / total * 100), f"План: {idx}/{total}")

    s = plan.stats()
    _log(
        "info",
        f"План построен: переместить {s['move']}, копировать {s['copy']}, "
        f"переименовать {s['rename']}, конфликтов {s['conflicts']}, ошибок {s['errors']}",
    )
    if progress_cb:
        progress_cb(100, f"План готов: {len(plan.executable_items)} операций")
    return plan


def _same_path(a: Path, b: Path) -> bool:
    try:
        return str(a.resolve(strict=False)).lower() == str(b.resolve(strict=False)).lower()
    except OSError:
        return str(a).lower() == str(b).lower()


def _is_within(child: Path, parent: Path) -> bool:
    """True, если child лежит внутри parent (для файлов проверяется родительская папка)."""
    try:
        c = str(Path(child).parent.resolve(strict=False)).lower()
        p = str(Path(parent).resolve(strict=False)).lower()
    except OSError:
        c, p = str(child.parent).lower(), str(parent).lower()
    try:
        return Path(c) == Path(p) or Path(p) in Path(c).parents
    except ValueError:
        # разные диски на Windows
        return False
