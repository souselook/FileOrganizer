"""Диалог подтверждения применения плана / удаления в корзину."""
from __future__ import annotations

from PySide6.QtWidgets import QDialogButtonBox, QLabel, QMessageBox, QVBoxLayout, QDialog


def confirm_apply(parent, plan_stats: dict, total_items: int) -> bool:
    """Предпросмотр итогов плана + «Вы уверены?». Возвращает True если применено."""
    text = (
        f"План будет применён. Всего пунктов: {total_items}\n\n"
        f"Будет перемещено:  {plan_stats.get('move', 0)}\n"
        f"Будет скопировано: {plan_stats.get('copy', 0)}\n"
        f"Будет переименовано: {plan_stats.get('rename', 0)}\n"
        f"Будет удалено в корзину: {plan_stats.get('trash', 0)}\n"
        f"Конфликтов: {plan_stats.get('conflicts', 0)}\n"
        f"Ошибок/пропущено: {plan_stats.get('errors', 0)}/{plan_stats.get('skipped', 0)}\n\n"
        "Перезапись существующих файлов не выполняется.\n"
        "Вы уверены?"
    )
    box = QMessageBox(QMessageBox.Icon.Question, "Применить план?", text,
                      QMessageBox.StandardButton.Apply | QMessageBox.StandardButton.Cancel, parent)
    box.button(QMessageBox.StandardButton.Apply).setText("Применить")
    box.button(QMessageBox.Cancel).setText("Отмена")
    return box.exec() == QMessageBox.StandardButton.Apply


def confirm_trash(parent, count: int, trash_mode: str) -> bool:
    extra = ""
    if trash_mode == "system":
        extra = "\nUndo для удаления в системную корзину недоступен."
    text = ("Файлы будут перемещены в корзину. Жёсткое удаление не выполняется."
            f"\nФайлов: {count}." + extra + "\n\nПродолжить?")
    box = QMessageBox(QMessageBox.Icon.Warning, "Подтверждение удаления", text,
                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, parent)
    box.button(QMessageBox.StandardButton.Yes).setText("Да, в корзину")
    box.button(QMessageBox.StandardButton.No).setText("Отмена")
    return box.exec() == QMessageBox.StandardButton.Yes


def confirm_clear_cache(parent, records: int) -> bool:
    box = QMessageBox(QMessageBox.Icon.Question, "Очистить кэш?",
                      f"Будет удалено записей: {records}.\n"
                      "Следующее сканирование будет медленнее.\nВы уверены?",
                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, parent)
    return box.exec() == QMessageBox.StandardButton.Yes
