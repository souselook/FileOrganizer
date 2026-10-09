"""Диалог предпросмотра плана: таблица «текущий путь -> новый путь», статусы, конфликты."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableView, QVBoxLayout,
)

from app.core.models import ActionPlan

HEADERS = ["Текущий путь", "Новый путь", "Правило", "Действие", "Статус", "Сообщение"]


class PreviewDialog(QDialog):
    def __init__(self, plan: ActionPlan, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Предпросмотр плана")
        self.setMinimumSize(980, 560)
        self._accepted = False

        lay = QVBoxLayout(self)
        s = plan.stats()
        summary = QLabel(
            f"Всего пунктов: {len(plan.items)}   "
            f"Переместить: {s['move']}   Копировать: {s['copy']}   "
            f"Переименовать: {s['rename']}   В корзину: {s['trash']}   "
            f"Конфликтов: {s['conflicts']}   Ошибок: {s['errors']}   Пропущено: {s['skipped']}"
        )
        summary.setWordWrap(True)
        lay.addWidget(summary)
        warn = QLabel("Это предпросмотр. Никакие файлы не изменены.")
        warn.setStyleSheet("font-weight: 600;")
        lay.addWidget(warn)

        model = QStandardItemModel(0, len(HEADERS))
        model.setHorizontalHeaderLabels(HEADERS)
        for it in plan.items:
            row = [
                QStandardItem(it.source),
                QStandardItem(it.target or "—"),
                QStandardItem(it.rule_name),
                QStandardItem(it.action),
                QStandardItem(it.status),
                QStandardItem(it.message),
            ]
            for c in row:
                c.setEditable(False)
            model.appendRow(row)

        table = QTableView()
        table.setModel(model)
        table.setSortingEnabled(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.setColumnWidth(0, 340)
        table.setColumnWidth(1, 340)
        table.verticalHeader().setVisible(False)
        lay.addWidget(table)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        apply_btn = QPushButton("Применить")
        apply_btn.setObjectName("dangerBtn" if s["trash"] else "applyBtn")
        apply_btn.clicked.connect(self._on_apply)
        if not plan.executable_items:
            apply_btn.setEnabled(False)
            apply_btn.setToolTip("Нет исполнимых операций")
        btns.addWidget(cancel)
        btns.addWidget(apply_btn)
        lay.addLayout(btns)

    def _on_apply(self) -> None:
        self._accepted = True
        self.accept()

    def confirmed(self) -> bool:
        return self._accepted
