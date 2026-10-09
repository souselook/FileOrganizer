"""Редактор правил структурирования.

Пользователь выбирает тип правила из списка и заполняет параметры —
произвольный код не вводится. Правила сохраняются в settings.rules.
"""
from __future__ import annotations

import copy

from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from app.core.models import Rule, Settings
from app.core.rules import safe_format, _ALLOWED_VARS

TYPE_NAMES = {
    "by_extension": "По расширению",
    "by_date": "По дате",
    "by_name_contains": "По имени",
    "by_size": "По размеру",
    "custom": "Пользовательское",
}


class RulesDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Правила структурирования")
        self.setMinimumSize(720, 480)
        self.settings = copy.deepcopy(settings)
        self.rules: list[Rule] = copy.deepcopy(self.settings.rules) or copy.deepcopy(
            _builtin_defaults())
        self._build_ui()
        self._reload_list()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        body = QHBoxLayout()

        # список правил
        left = QVBoxLayout()
        self.listw = QListWidget()
        self.listw.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.listw.currentRowChanged.connect(self._on_select)
        left.addWidget(QLabel("Правила (по приоритету сверху вниз):"))
        left.addWidget(self.listw)
        btns = QHBoxLayout()
        for text, slot in (
            ("Добавить", self._add), ("Удалить", self._delete),
            ("Вверх", lambda: self._move(-1)), ("Вниз", lambda: self._move(1)),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        left.addLayout(btns)
        body.addLayout(left, 1)

        # панель параметров
        right = QVBoxLayout()
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.type_label = QLabel()
        self.enabled_cb = QCheckBox("Включено")
        self.priority_spin = QSpinBox(); self.priority_spin.setRange(1, 9999)
        form.addRow("Название:", self.name_edit)
        form.addRow("Тип:", self.type_label)
        form.addRow("Приоритет:", self.priority_spin)
        form.addRow(self.enabled_cb)

        self.ext_edit = QLineEdit()
        self.ext_edit.setPlaceholderText(".jpg, .png, .gif")
        self.folder_tpl_edit = QLineEdit()
        self.folder_tpl_edit.setPlaceholderText("Images или {year}/{month}")
        self.name_contains_edit = QLineEdit()
        self.min_size_edit = QLineEdit(); self.min_size_edit.setPlaceholderText("0")
        self.max_size_edit = QLineEdit(); self.max_size_edit.setPlaceholderText("0 (без ограничения)")
        self.name_tpl_edit = QLineEdit()
        self.name_tpl_edit.setPlaceholderText("{stem}_{day}.{ext}")

        form.addRow("Расширения:", self.ext_edit)
        form.addRow("Целевая папка (шаблон):", self.folder_tpl_edit)
        form.addRow("Имя содержит:", self.name_contains_edit)
        form.addRow("Мин. размер (байт):", self.min_size_edit)
        form.addRow("Макс. размер (байт):", self.max_size_edit)
        form.addRow("Шаблон имени (custom):", self.name_tpl_edit)
        hint = QLabel(
            "Разрешённые переменные шаблона: "
            + ", ".join("{" + v + "}" for v in sorted(_ALLOWED_VARS))
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        right.addLayout(form)
        right.addStretch(1)
        body.addLayout(right, 2)
        lay.addLayout(body)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    # ---------- список ----------

    def _reload_list(self, select_index: int = -1) -> None:
        self.listw.blockSignals(True)
        self.listw.clear()
        for r in sorted(self.rules, key=lambda x: x.priority):
            item = QListWidgetItem(f"[{'x' if r.enabled else ' '}] {r.name} "
                                   f"(p.{r.priority}, {TYPE_NAMES.get(r.type, r.type)})")
            item.setData(0, r.id)
            self.listw.addItem(item)
        self.listw.blockSignals(False)
        if 0 <= select_index < self.listw.count():
            self.listw.setCurrentRow(select_index)

    def _current_rule(self) -> Rule | None:
        row = self.listw.currentRow()
        if row < 0:
            return None
        rid = self.listw.item(row).data(0)
        return next((r for r in self.rules if r.id == rid), None)

    def _on_select(self, row: int) -> None:
        # сначала сохранить предыдущий выбор в старый rule
        r = self._current_rule()
        if r is None:
            for w in (self.name_edit, self.ext_edit, self.folder_tpl_edit,
                      self.name_contains_edit, self.min_size_edit, self.max_size_edit,
                      self.name_tpl_edit):
                w.setEnabled(False)
            return
        for w in (self.name_edit, self.ext_edit, self.folder_tpl_edit,
                  self.name_contains_edit, self.min_size_edit, self.max_size_edit,
                  self.name_tpl_edit):
            w.setEnabled(True)
        self.name_edit.setText(r.name)
        self.type_label.setText(TYPE_NAMES.get(r.type, r.type))
        self.enabled_cb.setChecked(r.enabled)
        self.priority_spin.setValue(r.priority)
        p = r.params or {}
        self.ext_edit.setText(", ".join(p.get("extensions", [])))
        self.folder_tpl_edit.setText(str(p.get("target_template") or p.get("folder_template") or ""))
        self.name_contains_edit.setText(str(p.get("name_contains", "")))
        self.min_size_edit.setText(str(p.get("min_size", "")))
        self.max_size_edit.setText(str(p.get("max_size", "")))
        self.name_tpl_edit.setText(str(p.get("name_template", "")))

    # ---------- действия ----------

    def _apply_edits(self) -> None:
        r = self._current_rule()
        if r is None:
            return
        r.name = self.name_edit.text().strip() or r.name
        r.enabled = self.enabled_cb.isChecked()
        r.priority = self.priority_spin.value()
        p = dict(r.params or {})
        if r.type == "by_extension":
            p["extensions"] = [x.strip().lower() for x in self.ext_edit.text().split(",") if x.strip()]
            p["target_template"] = self.folder_tpl_edit.text().strip() or "{ext}"
        elif r.type == "by_date":
            p["target_template"] = self.folder_tpl_edit.text().strip() or "{year}/{month}"
            p.setdefault("date_format", "%Y/%m")
        elif r.type == "by_name_contains":
            p["name_contains"] = self.name_contains_edit.text().strip()
            p["target_template"] = self.folder_tpl_edit.text().strip() or r.name
        elif r.type == "by_size":
            p["min_size"] = int(self.min_size_edit.text() or 0)
            p["max_size"] = int(self.max_size_edit.text() or 0)
            p["target_template"] = self.folder_tpl_edit.text().strip() or r.name
        elif r.type == "custom":
            p["folder_template"] = self.folder_tpl_edit.text().strip() or r.name
            if self.name_tpl_edit.text().strip():
                p["name_template"] = self.name_tpl_edit.text().strip()
        r.params = p

    def _validate_templates(self) -> bool:
        values = {"ext": "txt", "year": "2026", "month": "01", "day": "01",
                  "stem": "file", "name": "file.txt", "size": "1"}
        for r in self.rules:
            for key in ("target_template", "folder_template", "name_template"):
                tpl = str((r.params or {}).get(key, "") or "")
                if not tpl:
                    continue
                try:
                    safe_format(tpl, values)
                except ValueError as exc:
                    QMessageBox.warning(self, "Некорректный шаблон",
                                        f"Правило «{r.name}», поле «{key}»:\n{exc}")
                    return False
        return True

    def _add(self) -> None:
        types = list(TYPE_NAMES.values())
        choice, ok = QInputDialog.getItem(self, "Новое правило", "Тип правила:", types, 0, False)
        if not ok:
            return
        rtype = next(k for k, v in TYPE_NAMES.items() if v == choice)
        r = Rule(type=rtype, name=f"Новое правило ({choice})",
                 priority=max([x.priority for x in self.rules], default=0) + 10,
                 enabled=True, params={})
        self.rules.append(r)
        idx = self.listw.count()
        self._reload_list()
        # выбрать добавленное
        for i in range(self.listw.count()):
            if self.listw.item(i).data(0) == r.id:
                self.listw.setCurrentRow(i)
                break

    def _delete(self) -> None:
        r = self._current_rule()
        if r is None:
            return
        self.rules.remove(r)
        self._reload_list()

    def _move(self, delta: int) -> None:
        r = self._current_rule()
        if r is None:
            return
        self._apply_edits()
        ordered = sorted(self.rules, key=lambda x: x.priority)
        i = ordered.index(r)
        j = max(0, min(len(ordered) - 1, i + delta))
        if i == j:
            return
        ordered[i], ordered[j] = ordered[j], ordered[i]
        for pos, rule in enumerate(ordered):
            rule.priority = (pos + 1) * 10
        self._reload_list()
        self.listw.setCurrentRow(j)

    def _on_save(self) -> None:
        self._apply_edits()
        if not self._validate_templates():
            return
        self.settings.rules = self.rules
        self.accept()

    def result_settings(self) -> Settings:
        return self.settings


def _builtin_defaults() -> list[Rule]:
    from app.core.rules import default_rules
    return default_rules()
