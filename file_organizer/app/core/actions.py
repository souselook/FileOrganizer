"""Выполнение плана действий: move / copy / rename / trash.

Жёсткое удаление запрещено: trash — только в корзину (внутреннюю или системную).
Каждая успешная операция записывается в History как Operation для undo.
Ошибки одного файла не роняют выполнение — помечаются и идут дальше.
"""
from __future__ import annotations

import shutil
import threading
import time
import uuid
from pathlib import Path

from app.core import constants
from app.core.history import History
from app.core.logging_utils import get_logger, make_log_bridge
from app.core.models import (
    ACTION_COPY,
    ACTION_MOVE,
    ACTION_RENAME,
    ACTION_TRASH,
    ActionPlan,
    ActionPlanItem,
    ExecutionResult,
    Operation,
    Settings,
    STATUS_ERROR,
    STATUS_LOCKED,
    STATUS_OK,
)
from app.core.organizer import unique_target

log = get_logger("actions")


def execute_plan(
    plan: ActionPlan,
    settings: Settings,
    history: History,
    progress_cb=None,
    log_cb=None,
    cancel_event: threading.Event | None = None,
) -> ExecutionResult:
    """Выполняет исполнимые пункты плана. Возвращает ExecutionResult с batch_id."""
    _log = make_log_bridge(log_cb)
    result = ExecutionResult(batch_id=uuid.uuid4().hex)
    items = plan.executable_items
    total = len(items)
    _log("info", f"Применение плана: {total} операций, batch {result.batch_id}")

    for idx, item in enumerate(items):
        if cancel_event is not None and cancel_event.is_set():
            result.canceled = True
            _log("warning", "Выполнение остановлено пользователем")
            break
        try:
            op = _run_item(item, settings, _log)
        except PermissionError as exc:
            item.status = STATUS_LOCKED
            item.message = f"Файл занят или нет прав: {exc}"
            result.skipped += 1
            result.errors.append(f"{item.source}: {exc}")
            _log("warning", item.message)
            continue
        except OSError as exc:
            item.status = STATUS_ERROR
            item.message = f"Ошибка: {exc}"
            result.errors.append(f"{item.source}: {exc}")
            _log("error", item.message)
            continue
        except Exception as exc:  # noqa: BLE001
            item.status = STATUS_ERROR
            item.message = f"Неизвестная ошибка: {exc}"
            result.errors.append(f"{item.source}: {exc}")
            _log("error", item.message)
            continue

        if op is None:
            result.skipped += 1
            item.status = "skipped"
        else:
            result.executed += 1
            result.operations.append(op)
            history.record_operation(op)

        if progress_cb and total:
            progress_cb(int((idx + 1) / total * 100), f"Выполнено: {idx + 1}/{total}")

    _log(
        "info",
        f"Выполнение завершено: успешно {result.executed}, "
        f"пропущено {result.skipped}, ошибок {len(result.errors)}",
    )
    return result


def _run_item(item: ActionPlanItem, settings: Settings, _log) -> Operation | None:
    src = Path(item.source)
    if not src.exists():
        item.status = STATUS_ERROR
        item.message = "Источник исчез"
        return None

    action = item.action
    if action == ACTION_MOVE:
        return _do_move(item, settings, _log)
    if action == ACTION_COPY:
        return _do_copy(item, settings, _log)
    if action == ACTION_RENAME:
        return _do_rename(item, settings, _log)
    if action == ACTION_TRASH:
        return _do_trash(item, settings, _log)
    raise ValueError(f"Неизвестное действие: {action}")


def _ensure_parent(target: Path, settings: Settings) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)


def _no_overwrite(src: Path, dst: Path, settings: Settings) -> Path:
    """Никогда не перезаписываем существующий файл без разрешения: уникальное имя."""
    if str(src).lower() == str(dst).lower():
        raise ValueError("Перемещение/копирование файла в самого себя запрещено")
    if dst.exists():
        policy = settings.conflict_policy
        if policy == "skip":
            return dst  # вызывающий код проверит и пропустит
        dst, _ = unique_target(dst, set(), "unique_name")
    return dst


def _do_move(item: ActionPlanItem, settings: Settings, _log) -> Operation | None:
    src, dst = Path(item.source), Path(item.target)
    final = _no_overwrite(src, dst, settings)
    if final.exists():  # политика skip
        item.status = "skipped"
        item.message = "Цель существует, перезапись запрещена"
        return None
    _ensure_parent(final, settings)
    shutil.move(str(src), str(final))
    item.target = str(final)
    item.status = STATUS_OK
    _log("info", f"Перемещено: {src} -> {final}")
    return Operation(action=ACTION_MOVE, source=str(src), target=str(final))


def _do_copy(item: ActionPlanItem, settings: Settings, _log) -> Operation | None:
    src, dst = Path(item.source), Path(item.target)
    final = _no_overwrite(src, dst, settings)
    if final.exists():
        item.status = "skipped"
        item.message = "Цель существует, перезапись запрещена"
        return None
    _ensure_parent(final, settings)
    shutil.copy2(str(src), str(final))
    item.target = str(final)
    item.status = STATUS_OK
    _log("info", f"Скопировано: {src} -> {final}")
    return Operation(action=ACTION_COPY, source=str(src), target=str(final))


def _do_rename(item: ActionPlanItem, settings: Settings, _log) -> Operation | None:
    src, dst = Path(item.source), Path(item.target)
    if src == dst:
        item.status = "skipped"
        return None
    final = src.with_name(dst.name)
    if final.exists():
        final, _ = unique_target(final, set(), "unique_name")
    src.rename(final)
    item.target = str(final)
    item.status = STATUS_OK
    _log("info", f"Переименовано: {src.name} -> {final.name}")
    return Operation(action=ACTION_RENAME, source=str(src), target=str(final))


def _do_trash(item: ActionPlanItem, settings: Settings, _log) -> Operation | None:
    """Удаление ТОЛЬКО в корзину. Жёсткое удаление недоступно в принципе."""
    src = Path(item.source)
    if settings.trash_mode == "system":
        try:
            from send2trash import send2trash  # type: ignore
        except ImportError:
            # Fallback: всё равно во внутреннюю корзину, а не удалять жёстко
            _log("warning", "send2trash недоступен, используется внутренняя корзина")
            return _trash_internal(item, settings, _log)
        send2trash(str(src))
        item.status = STATUS_OK
        _log("info", f"Перемещено в системную корзину: {src}")
        return Operation(
            action=ACTION_TRASH, source=str(src), target="",
            undoable=False, message="Undo для системной корзины недоступен",
        )
    return _trash_internal(item, settings, _log)


def _trash_internal(item: ActionPlanItem, settings: Settings, _log) -> Operation:
    src = Path(item.source)
    trash_root = Path(constants.TRASH_DIR)
    # Корзина на том же диске, если возможно — иначе в APPDATA
    try:
        same_drive = src.drive.lower() == trash_root.drive.lower() if src.drive else True
    except AttributeError:
        same_drive = True
    if not same_drive:
        trash_root = trash_root / (src.drive.replace(":", "") or "other")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    rel_parent = trash_root / stamp.replace("_", "") / src.parent.name
    rel_parent.mkdir(parents=True, exist_ok=True)
    dst = rel_parent / src.name
    if dst.exists():
        dst, _ = unique_target(dst, set(), "unique_name")
    shutil.move(str(src), str(dst))
    item.target = str(dst)
    item.status = STATUS_OK
    _log("info", f"Перемещено в корзину приложения: {src} -> {dst}")
    return Operation(action=ACTION_TRASH, source=str(src), target=str(dst), undoable=True)
