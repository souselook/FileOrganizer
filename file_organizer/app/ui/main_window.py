"""Главное окно приложения. Только Qt и диспетчеризация в core через workers."""
from __future__ import annotations

import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QSplitter, QTableView, QTextEdit,
    QVBoxLayout, QWidget,
)

from app.core import constants
from app.core.cache import Cache
from app.core.config import load_settings, save_settings
from app.core.history import History
from app.core.logging_utils import get_logger, setup_logging
from app.core.models import ActionPlan, DuplicateGroup, ScanResult, Settings
from app.core.rules import RuleMatcher
from app.ui.dialogs.confirm_dialog import confirm_apply, confirm_clear_cache, confirm_trash
from app.ui.dialogs.preview_dialog import PreviewDialog
from app.ui.dialogs.rules_dialog import RulesDialog
from app.ui.dialogs.settings_dialog import SettingsDialog
from app.ui.styles import qss_for
from app.ui.widgets.file_table import FileFilterProxy, FileTableModel, human_size
from app.ui.widgets.folder_tree import FolderTree
from app.ui.widgets.log_view import LogView
from app.ui.widgets.progress_bar import TaskProgress
from app.ui.workers import (
    ActionWorker, BaseWorker, DuplicateWorker, HashWorker, OrganizeWorker, ScanWorker,
)

log = get_logger("ui")


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, cache: Cache, history: History):
        super().__init__()
        self.settings = settings
        self.cache = cache
        self.history = history
        self.worker: BaseWorker | None = None
        self.scan_result: ScanResult | None = None
        self.duplicates: list[DuplicateGroup] = []
        self.plan: ActionPlan | None = None

        self.setWindowTitle(f"{constants.APP_NAME} {constants.APP_VERSION}")
        self.resize(1280, 800)
        self._build_ui()
        self.apply_theme(self.settings.theme)
        self.statusBar().showMessage("Готово")

    # ================= UI =================

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        # --- панель папок ---
        folders = QHBoxLayout()
        folders.addWidget(QLabel("Папка:"))
        self.folder_edit = QLineEdit(self.settings.working_folder)
        self.folder_edit.setPlaceholderText("Выберите папку для анализа…")
        btn_pick = QPushButton("Обзор…")
        btn_pick.clicked.connect(self._pick_folder)
        folders.addWidget(self.folder_edit, 1)
        folders.addWidget(btn_pick)
        folders.addWidget(QLabel("Цель:"))
        self.target_edit = QLineEdit(self.settings.target_folder)
        self.target_edit.setPlaceholderText("Куда складывать (пусто = подпапки в рабочей)")
        btn_pick2 = QPushButton("Обзор…")
        btn_pick2.clicked.connect(self._pick_target)
        folders.addWidget(self.target_edit, 1)
        folders.addWidget(btn_pick2)
        root.addLayout(folders)

        # --- кнопки действий ---
        bar = QHBoxLayout()
        self.btn_scan = QPushButton("Сканировать")
        self.btn_scan.clicked.connect(self.on_scan)
        self.btn_dupes = QPushButton("Найти дубликаты")
        self.btn_dupes.clicked.connect(self.on_find_duplicates)
        self.btn_rules = QPushButton("Правила…")
        self.btn_rules.clicked.connect(self.on_rules)
        self.btn_preview = QPushButton("Предпросмотр плана")
        self.btn_preview.clicked.connect(self.on_build_plan)
        self.btn_undo = QPushButton("Отменить последнее действие")
        self.btn_undo.clicked.connect(self.on_undo)
        self.btn_stop = QPushButton("Остановить")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setObjectName("dangerBtn")
        self.btn_stop.clicked.connect(self.on_stop)
        for b in (self.btn_scan, self.btn_dupes, self.btn_rules,
                  self.btn_preview, self.btn_undo, self.btn_stop):
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)

        self.progress = TaskProgress()
        root.addWidget(self.progress)

        # --- фильтры таблицы ---
        filters = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск по имени/пути…")
        self.search_edit.textChanged.connect(self._apply_filters)
        self.status_combo = QComboBox()
        self.status_combo.addItems(["Все", "ok", "skipped", "error", "locked", "conflict"])
        self.status_combo.currentTextChanged.connect(self._apply_filters)
        self.ext_edit = QLineEdit()
        self.ext_edit.setPlaceholderText("Расширение (например jpg)")
        self.ext_edit.textChanged.connect(self._apply_filters)
        self.size_min_edit = QLineEdit(); self.size_min_edit.setPlaceholderText("мин. размер, байт")
        self.size_max_edit = QLineEdit(); self.size_max_edit.setPlaceholderText("макс. размер, байт")
        for w in (self.search_edit, self.status_combo, self.ext_edit,
                  self.size_min_edit, self.size_max_edit):
            filters.addWidget(w, 1)
        root.addLayout(filters)

        # --- центральная область: дерево + таблица ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = FolderTree()
        splitter.addWidget(self.tree)

        table_host = QWidget()
        th = QVBoxLayout(table_host)
        th.setContentsMargins(0, 0, 0, 0)
        self.model = FileTableModel()
        self.proxy = FileFilterProxy()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setColumnWidth(0, 240)
        self.table.setColumnWidth(1, 380)
        th.addWidget(self.table)
        self.selection_label = QLabel("Выбрано: 0 файлов, 0 Б")
        th.addWidget(self.selection_label)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)
        splitter.addWidget(table_host)
        splitter.setSizes([280, 900])
        root.addWidget(splitter, 1)

        # --- лог ---
        self.log_view = LogView()
        self.log_view.setMaximumHeight(140)
        root.addWidget(self.log_view)

        self.setCentralWidget(central)
        self._build_menu()

    def _build_menu(self) -> None:
        m_file = self.menuBar().addMenu("&Файл")
        act_settings = QAction("На&стройки…", self)
        act_settings.setShortcut(QKeySequence("Ctrl+,"))
        act_settings.triggered.connect(self.on_settings)
        m_file.addAction(act_settings)
        act_clear_cache = QAction("Очистить &кэш", self)
        act_clear_cache.triggered.connect(self.on_clear_cache)
        m_file.addAction(act_clear_cache)
        act_exit = QAction("&Выход", self)
        act_exit.triggered.connect(self.close)
        m_file.addAction(act_exit)

        m_tools = self.menuBar().addMenu("&Сервис")
        act_hash = QAction("&Хешировать выбранные файлы", self)
        act_hash.triggered.connect(self.on_hash_selected)
        m_tools.addAction(act_hash)
        act_trash = QAction("Удалить выбранное в &корзину", self)
        act_trash.triggered.connect(self.on_trash_selected)
        m_tools.addAction(act_trash)

        m_help = self.menuBar().addMenu("&Справка")
        act_about = QAction("О &программе", self)
        act_about.triggered.connect(self._about)
        m_help.addAction(act_about)

    # ================= слоты =================

    def _pick_folder(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "Выберите папку",
                                             self.folder_edit.text() or str(Path.home()))
        if d:
            self.folder_edit.setText(d)

    def _pick_target(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "Целевая папка",
                                             self.target_edit.text() or self.folder_edit.text())
        if d:
            self.target_edit.setText(d)

    def _sync_settings_folders(self) -> None:
        self.settings.working_folder = self.folder_edit.text().strip()
        self.settings.target_folder = self.target_edit.text().strip()
        self.settings.normalized()

    # ---- запуск фоновых задач ----

    def _start_worker(self, worker: BaseWorker, on_done) -> bool:
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Занято",
                                    "Уже выполняется операция. Дождитесь окончания или нажмите «Остановить».")
            return False
        self.worker = worker
        worker.progress.connect(self._on_progress)
        worker.log.connect(self.log_view.append_log)
        worker.finished_with_result.connect(on_done)
        worker.error.connect(self._on_worker_error)
        worker.canceled.connect(lambda: self.statusBar().showMessage("Операция отменена"))
        self._set_busy(True)
        worker.start()
        return True

    def _set_busy(self, busy: bool) -> None:
        for b in (self.btn_scan, self.btn_dupes, self.btn_preview, self.btn_undo):
            b.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)
        if not busy:
            self.progress.stop()

    def _on_progress(self, percent: int, message: str) -> None:
        self.progress.set_task(percent, message)
        if message:
            self.statusBar().showMessage(message)

    def _on_worker_error(self, text: str) -> None:
        log.error(text)
        self.log_view.append_log("error", text.splitlines()[0] if text else "Неизвестная ошибка")
        QMessageBox.critical(self, "Ошибка операции", text[:2000] or "Неизвестная ошибка")

    # ---- сканирование ----

    def on_scan(self) -> None:
        self._sync_settings_folders()
        if not self.settings.working_folder:
            QMessageBox.warning(self, "Нет папки", "Сначала выберите папку для анализа.")
            return
        try:
            save_settings(self.settings)
        except OSError as exc:
            self.log_view.append_log("warning", f"Не удалось сохранить настройки: {exc}")
        self._start_worker(ScanWorker(self.settings, self.cache), self._on_scan_done)

    def _on_scan_done(self, result: ScanResult) -> None:
        self._set_busy(False)
        self.scan_result = result
        self.model.set_files(result.files)
        self.tree.rebuild(result.root, result.files)
        self.duplicates = []
        msg = (f"Сканирование завершено: {result.scanned_count} файлов, "
               f"пропущено {result.skipped_count}, ошибок {len(result.errors)}")
        self.statusBar().showMessage(msg)
        if result.errors:
            self.log_view.append_log("warning", f"Ошибки сканирования: {len(result.errors)}")

    # ---- хеширование / дубликаты ----

    def on_hash_selected(self) -> None:
        files = self._selected_files()
        if not files:
            files = self.model.files()
        if not files:
            QMessageBox.information(self, "Пусто", "Сначала просканируйте папку.")
            return
        self._start_worker(HashWorker(self.settings, self.cache, files), self._on_hash_done)

    def _on_hash_done(self, files) -> None:
        self._set_busy(False)
        self.model.beginResetModel()
        self.model.endResetModel()
        self.statusBar().showMessage("Хеширование завершено")

    def on_find_duplicates(self) -> None:
        if not self.model.files():
            QMessageBox.information(self, "Пусто", "Сначала просканируйте папку.")
            return
        self._sync_settings_folders()
        self._start_worker(
            DuplicateWorker(self.settings, self.cache, self.model.files()),
            self._on_dupes_done,
        )

    def _on_dupes_done(self, groups: list[DuplicateGroup]) -> None:
        self._set_busy(False)
        self.duplicates = groups
        n = len(groups)
        wasted = sum(g.wasted_size for g in groups)
        self.statusBar().showMessage(
            f"Дубликаты: групп {n}, освобождается ~{human_size(wasted)}")
        if n == 0:
            QMessageBox.information(self, "Дубликаты", "Дубликаты не найдены.")

    # ---- правила / план / применение ----

    def on_rules(self) -> None:
        dlg = RulesDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.result_settings()
            try:
                save_settings(self.settings)
            except OSError as exc:
                QMessageBox.warning(self, "Настройки", f"Не удалось сохранить: {exc}")
            active = [r for r in self.settings.rules if r.enabled]
            self.log_view.append_log("info", f"Активных правил: {len(active)}")

    def on_build_plan(self) -> None:
        files = self._files_for_action()
        if not files:
            QMessageBox.information(self, "Пусто", "Нет файлов. Просканируйте папку.")
            return
        self._sync_settings_folders()
        rules = RuleMatcher.load_rules(self.settings)
        self._start_worker(OrganizeWorker(self.settings, self.cache, files, rules),
                           self._on_plan_ready)

    def _on_plan_ready(self, plan: ActionPlan) -> None:
        self._set_busy(False)
        self.plan = plan
        dlg = PreviewDialog(plan, self)
        if not dlg.exec():
            return
        stats = plan.stats()
        if stats["trash"] and not confirm_trash(self, stats["trash"], self.settings.trash_mode):
            return
        if not confirm_apply(self, stats, len(plan.items)):
            return
        self._start_worker(
            ActionWorker(self.settings, self.cache, plan, self.history),
            self._on_executed,
        )

    def _on_executed(self, result) -> None:
        self._set_busy(False)
        # обновляем таблицу: отмечаем выполненные пункты
        by_src = {it.source: it for it in self.plan.items} if self.plan else {}
        for f in self.model.files():
            it = by_src.get(f.path)
            if it is not None:
                f.status = it.status
                f.message = it.message
        self.model.beginResetModel()
        self.model.endResetModel()
        msg = (f"Выполнено: {result.executed}, пропущено: {result.skipped}, "
               f"ошибок: {len(result.errors)}")
        self.statusBar().showMessage(msg)
        if result.errors:
            QMessageBox.warning(self, "Результат с ошибками", "\n".join(result.errors[:50]))
        if result.operations:
            self.log_view.append_log("info", "Для отмены нажмите «Отменить последнее действие»")

    # ---- корзина выбранных ----

    def on_trash_selected(self) -> None:
        files = self._selected_files()
        if not files:
            QMessageBox.information(self, "Ничего не выбрано",
                                    "Выделите файлы в таблице (Ctrl/Shift).")
            return
        if not confirm_trash(self, len(files), self.settings.trash_mode):
            return
        from app.core.models import ACTION_TRASH, ActionPlanItem, STATUS_OK
        plan = ActionPlan(items=[
            ActionPlanItem(source=f.path, target="", action=ACTION_TRASH,
                           rule_name="Ручное удаление", status=STATUS_OK)
            for f in files
        ])
        self.plan = plan
        self._start_worker(ActionWorker(self.settings, self.cache, plan, self.history),
                           self._on_executed)

    # ---- undo ----

    def on_undo(self) -> None:
        last = self.history.get_recent(1)
        if not last:
            QMessageBox.information(self, "История пуста", "Отменять нечего.")
            return
        box = QMessageBox.question(
            self, "Отменить последнее действие?",
            "Будет отменён последний пакет операций.\nПродолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if box != QMessageBox.StandardButton.Yes:
            return
        undone, problems = self.history.undo_last()
        msg = f"Undo: отменено {undone}"
        if problems:
            msg += ", проблем: " + str(len(problems))
            self.log_view.append_log("warning", "; ".join(problems[:20]))
        self.statusBar().showMessage(msg)
        self.log_view.append_log("info", msg)
        if self.scan_result:
            self.on_scan()  # пересканируем, чтобы отобразить реальное состояние

    # ---- кэш / настройки / тема ----

    def on_clear_cache(self) -> None:
        n = self.cache.count()
        if not confirm_clear_cache(self, n):
            return
        removed = self.cache.clear()
        self.log_view.append_log("info", f"Кэш очищен ({removed} записей)")
        self.statusBar().showMessage(f"Кэш очищен: {removed} записей")

    def on_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.collect()
            try:
                save_settings(self.settings)
            except OSError as exc:
                QMessageBox.warning(self, "Настройки", f"Не удалось сохранить: {exc}")
            self.apply_theme(self.settings.theme)
            self.folder_edit.setText(self.settings.working_folder)
            self.target_edit.setText(self.settings.target_folder)

    def apply_theme(self, theme: str) -> None:
        QApplication.instance().setStyleSheet(qss_for(theme))

    def on_stop(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.btn_stop.setEnabled(False)
            self.statusBar().showMessage("Остановка запрошена…")

    # ---- утилиты ----

    def _selected_files(self) -> list:
        rows = {idx.row() for idx in self.table.selectionModel().selectedRows()}
        out = []
        for row in sorted(rows):
            src = self.proxy.mapToSource(self.proxy.index(row, 0))
            f = self.model.file_at(src.row())
            if f is not None:
                out.append(f)
        return out

    def _files_for_action(self) -> list:
        sel = self._selected_files()
        return sel if sel else self.model.files()

    def _on_selection(self) -> None:
        files = self._selected_files()
        total = sum(f.size for f in files)
        self.selection_label.setText(
            f"Выбрано: {len(files)} файлов, {human_size(total)}")

    def _apply_filters(self) -> None:
        try:
            mn = int(self.size_min_edit.text() or 0)
            mx = int(self.size_max_edit.text() or 0)
        except ValueError:
            mn = mx = 0
        self.proxy.set_filters(
            text=self.search_edit.text(),
            status=self.status_combo.currentText(),
            ext=self.ext_edit.text(),
            min_size=mn, max_size=mx,
        )

    def _about(self) -> None:
        QMessageBox.about(
            self, f"О программе {constants.APP_NAME}",
            f"<b>{constants.APP_NAME} {constants.APP_VERSION}</b><br>"
            "Структурирование файлов и поиск дубликатов.<br><br>"
            "Безопасно: анализ → предпросмотр → подтверждение → выполнение.<br>"
            "Жёсткое удаление запрещено — только корзина.",
        )

    def closeEvent(self, event) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        try:
            save_settings(self.settings)
        except OSError:
            pass
        self.cache.close()
        self.history.close()
        super().closeEvent(event)
