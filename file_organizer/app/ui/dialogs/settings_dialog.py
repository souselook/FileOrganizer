"""Диалог настроек: все группы требований (Папки/Фильтры/Дубликаты/Структурирование/
Безопасность/Кэш/История/Интерфейс). Работает с копией Settings, применяет только по «Сохранить»."""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

from app.core import constants
from app.core.models import Settings


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setMinimumSize(560, 640)
        self.settings = copy.deepcopy(settings)
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        panel = QWidget()
        form_host = QVBoxLayout(panel)

        # --- Папки ---
        g1 = QGroupBox("Папки")
        f1 = QFormLayout(g1)
        self.work_edit = QLineEdit()
        pick1 = QPushButton("Обзор…")
        pick1.clicked.connect(lambda: self._pick(self.work_edit))
        row1 = QHBoxLayout(); row1.addWidget(self.work_edit); row1.addWidget(pick1)
        f1.addRow("Рабочая папка:", row1)
        self.target_edit = QLineEdit()
        pick2 = QPushButton("Обзор…")
        pick2.clicked.connect(lambda: self._pick(self.target_edit))
        row2 = QHBoxLayout(); row2.addWidget(self.target_edit); row2.addWidget(pick2)
        f1.addRow("Целевая папка:", row2)
        self.recursive_cb = QCheckBox("Рекурсивный поиск")
        self.subfolders_cb = QCheckBox("Включать подпапки")
        f1.addRow(self.recursive_cb)
        f1.addRow(self.subfolders_cb)

        # --- Фильтры ---
        g2 = QGroupBox("Фильтры")
        f2 = QFormLayout(g2)
        self.skip_hidden_cb = QCheckBox("Пропускать скрытые файлы")
        self.skip_temp_cb = QCheckBox("Пропускать временные файлы")
        self.skip_symlink_cb = QCheckBox("Пропускать симлинки")
        f2.addRow(self.skip_hidden_cb)
        f2.addRow(self.skip_temp_cb)
        f2.addRow(self.skip_symlink_cb)
        self.excl_dirs_edit = QLineEdit()
        self.excl_dirs_edit.setPlaceholderText("через запятую: .git, node_modules, …")
        f2.addRow("Исключённые папки:", self.excl_dirs_edit)
        self.excl_ext_edit = QLineEdit()
        self.excl_ext_edit.setPlaceholderText(".tmp, .bak, …")
        f2.addRow("Исключённые расширения:", self.excl_ext_edit)
        self.incl_ext_edit = QLineEdit()
        self.incl_ext_edit.setPlaceholderText("пусто = все расширения")
        f2.addRow("Только расширения:", self.incl_ext_edit)
        self.min_size_spin = QSpinBox(); self.min_size_spin.setRange(0, 10**9); self.min_size_spin.setSuffix(" байт")
        self.max_size_spin = QSpinBox(); self.max_size_spin.setRange(0, 10**9); self.max_size_spin.setSuffix(" байт")
        f2.addRow("Минимальный размер:", self.min_size_spin)
        f2.addRow("Максимальный размер (0 = без ограничения):", self.max_size_spin)

        # --- Дубликаты ---
        g3 = QGroupBox("Дубликаты")
        f3 = QFormLayout(g3)
        self.mode_combo = QComboBox(); self.mode_combo.addItems(constants.DUPLICATE_MODES)
        f3.addRow("Режим поиска:", self.mode_combo)
        self.algo_combo = QComboBox(); self.algo_combo.addItems(constants.SUPPORTED_HASH_ALGORITHMS)
        f3.addRow("Алгоритм хеша:", self.algo_combo)
        self.quick_bytes_spin = QSpinBox(); self.quick_bytes_spin.setRange(0, 10**7)
        f3.addRow("Размер быстрого хеша (байт):", self.quick_bytes_spin)

        # --- Структурирование ---
        g4 = QGroupBox("Структурирование")
        f4 = QFormLayout(g4)
        self.actions_w = QWidget()
        la = QHBoxLayout(self.actions_w)
        self.action_checks: dict[str, QCheckBox] = {}
        for a in constants.ACTION_TYPES:
            cb = QCheckBox(a)
            self.action_checks[a] = cb
            la.addWidget(cb)
        f4.addRow("Разрешённые действия:", self.actions_w)
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItem("Уникальное имя file (1).txt", "unique_name")
        self.conflict_combo.addItem("Пропускать конфликт", "skip")
        self.conflict_combo.addItem("Спрашивать пользователя", "ask")
        f4.addRow("Политика при конфликте:", self.conflict_combo)
        self.create_folders_cb = QCheckBox("Создавать папки автоматически")
        self.unique_names_cb = QCheckBox("Уникальные имена при конфликте")
        f4.addRow(self.create_folders_cb)
        f4.addRow(self.unique_names_cb)

        # --- Безопасность ---
        g5 = QGroupBox("Безопасность")
        f5 = QFormLayout(g5)
        info = QLabel("Жёсткое удаление запрещено во всех режимах.\n"
                      "Все удаления выполняются только в корзину.")
        info.setStyleSheet("font-weight: 600;")
        f5.addRow(info)
        self.trash_mode_combo = QComboBox()
        self.trash_mode_combo.addItem("Корзина приложения (полный Undo)", "internal")
        self.trash_mode_combo.addItem("Системная корзина Windows (Undo может быть недоступен)", "system")
        f5.addRow("Режим корзины:", self.trash_mode_combo)

        # --- Кэш / История ---
        g6 = QGroupBox("Кэш и история")
        f6 = QFormLayout(g6)
        f6.addRow(QLabel(f"Кэш: {constants.CACHE_DB}"))
        f6.addRow(QLabel(f"История: {constants.HISTORY_DB}"))
        self.history_limit_spin = QSpinBox(); self.history_limit_spin.setRange(10, 100000)
        f6.addRow("Размер истории (записей):", self.history_limit_spin)

        # --- Интерфейс ---
        g7 = QGroupBox("Интерфейс")
        f7 = QFormLayout(g7)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Светлая", "light")
        self.theme_combo.addItem("Тёмная", "dark")
        f7.addRow("Тема:", self.theme_combo)
        self.lang_combo = QComboBox(); self.lang_combo.addItems(["ru"])
        f7.addRow("Язык:", self.lang_combo)

        for g in (g1, g2, g3, g4, g5, g6, g7):
            form_host.addWidget(g)

        scroll.setWidget(panel)
        outer.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self._on_reset)
        outer.addWidget(buttons)

    def _pick(self, edit: QLineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "Выберите папку", edit.text() or str(Path.home()))
        if d:
            edit.setText(d)

    # ---------- значения ----------

    def _load_values(self) -> None:
        s = self.settings
        self.work_edit.setText(s.working_folder)
        self.target_edit.setText(s.target_folder)
        self.recursive_cb.setChecked(s.recursive)
        self.subfolders_cb.setChecked(s.include_subfolders)
        self.skip_hidden_cb.setChecked(s.skip_hidden)
        self.skip_temp_cb.setChecked(s.skip_temp)
        self.skip_symlink_cb.setChecked(s.skip_symlinks)
        self.excl_dirs_edit.setText(", ".join(s.excluded_dirs))
        self.excl_ext_edit.setText(", ".join(s.excluded_extensions))
        self.incl_ext_edit.setText(", ".join(s.included_extensions))
        self.min_size_spin.setValue(s.min_size)
        self.max_size_spin.setValue(s.max_size)
        idx = self.mode_combo.findText(s.duplicate_mode)
        self.mode_combo.setCurrentIndex(max(0, idx))
        idx = self.algo_combo.findText(s.hash_algorithm)
        self.algo_combo.setCurrentIndex(max(0, idx))
        self.quick_bytes_spin.setValue(s.quick_hash_bytes)
        for a, cb in self.action_checks.items():
            cb.setChecked(a in s.allowed_actions)
        idx = self.conflict_combo.findData(s.conflict_policy)
        self.conflict_combo.setCurrentIndex(max(0, idx))
        self.create_folders_cb.setChecked(s.create_folders)
        self.unique_names_cb.setChecked(s.unique_names)
        idx = self.trash_mode_combo.findData(s.trash_mode)
        self.trash_mode_combo.setCurrentIndex(max(0, idx))
        self.history_limit_spin.setValue(s.history_limit)
        idx = self.theme_combo.findData(s.theme)
        self.theme_combo.setCurrentIndex(max(0, idx))

    def collect(self) -> Settings:
        s = self.settings
        s.working_folder = self.work_edit.text().strip()
        s.target_folder = self.target_edit.text().strip()
        s.recursive = self.recursive_cb.isChecked()
        s.include_subfolders = self.subfolders_cb.isChecked()
        s.skip_hidden = self.skip_hidden_cb.isChecked()
        s.skip_temp = self.skip_temp_cb.isChecked()
        s.skip_symlinks = self.skip_symlink_cb.isChecked()
        s.excluded_dirs = [x.strip() for x in self.excl_dirs_edit.text().split(",") if x.strip()]
        s.excluded_extensions = [x.strip() for x in self.excl_ext_edit.text().split(",") if x.strip()]
        s.included_extensions = [x.strip() for x in self.incl_ext_edit.text().split(",") if x.strip()]
        s.min_size = self.min_size_spin.value()
        s.max_size = self.max_size_spin.value()
        s.duplicate_mode = self.mode_combo.currentText()
        s.hash_algorithm = self.algo_combo.currentText()
        s.quick_hash_bytes = self.quick_bytes_spin.value()
        s.allowed_actions = [a for a, cb in self.action_checks.items() if cb.isChecked()]
        s.conflict_policy = self.conflict_combo.currentData()
        s.create_folders = self.create_folders_cb.isChecked()
        s.unique_names = self.unique_names_cb.isChecked()
        s.trash_mode = self.trash_mode_combo.currentData()
        s.history_limit = self.history_limit_spin.value()
        s.theme = self.theme_combo.currentData()
        s.normalized()
        return s

    def _on_save(self) -> None:
        self.collect()
        self.accept()

    def _on_reset(self) -> None:
        from app.core.config import default_settings
        self.settings = default_settings()
        self._load_values()
