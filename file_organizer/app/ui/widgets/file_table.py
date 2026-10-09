"""Виртуальная таблица файлов для больших папок (10 000+).

QAbstractTableModel — данные не копируются в виджеты, сортировка через
QSortFilterProxyModel + фильтры по статусу/расширению/размеру.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from app.core.models import FileItem

COLUMNS = ["Имя", "Путь", "Расширение", "Размер", "Дата изменения", "Статус", "Действие"]

_STATUS_COLORS = {
    "ok": None,
    "error": QColor("#d64541"),
    "locked": QColor("#c77f00"),
    "skipped": QColor("#8a939e"),
    "conflict": QColor("#b8352f"),
}


def human_size(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024 or unit == "ТБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


class FileTableModel(QAbstractTableModel):
    def __init__(self, files: list[FileItem] | None = None, parent=None):
        super().__init__(parent)
        self._files: list[FileItem] = files or []

    # ---- API ----
    def set_files(self, files: list[FileItem]) -> None:
        self.beginResetModel()
        self._files = files
        self.endResetModel()

    def file_at(self, row: int) -> FileItem | None:
        if 0 <= row < len(self._files):
            return self._files[row]
        return None

    def files(self) -> list[FileItem]:
        return self._files

    # ---- model protocol ----
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._files)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        f = self._files[index.row()]
        col = index.column()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == 0:
                return f.name
            if col == 1:
                return f.parent
            if col == 2:
                return f.ext or "—"
            if col == 3:
                return f.size  # EditRole для числовой сортировки
            if col == 4:
                try:
                    return f.mtime_dt.strftime("%Y-%m-%d %H:%M")
                except (OSError, ValueError):
                    return "—"
            if col == 5:
                return f.status
            if col == 6:
                return f.message
        if role == Qt.ItemDataRole.DisplayRole and col == 3:
            return human_size(f.size)
        if role == Qt.ItemDataRole.ForegroundRole and col == 5:
            return _STATUS_COLORS.get(f.status)
        return None

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self.layoutAboutToBeChanged.emit()
        key_map = {
            0: lambda f: f.name.lower(),
            1: lambda f: f.parent.lower(),
            2: lambda f: f.ext,
            3: lambda f: f.size,
            4: lambda f: f.mtime,
            5: lambda f: f.status,
        }
        key = key_map.get(column, key_map[0])
        try:
            self._files.sort(key=key, reverse=(order == Qt.SortOrder.DescendingOrder))
        except TypeError:
            pass
        self.layoutChanged.emit()


class FileFilterProxy(QSortFilterProxyModel):
    """Фильтры: текст, статус, расширение, диапазон размера."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._status = ""
        self._ext = ""
        self._min_size = 0
        self._max_size = 0

    def set_filters(self, text: str = "", status: str = "", ext: str = "",
                    min_size: int = 0, max_size: int = 0) -> None:
        self._text = (text or "").lower()
        self._status = (status or "").lower()
        self._ext = (ext or "").lower().lstrip(".")
        self._min_size = int(min_size or 0)
        self._max_size = int(max_size or 0)
        self.invalidateFilterRows()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        f = model.file_at(source_row)  # type: ignore[attr-defined]
        if f is None:
            return False
        if self._text and self._text not in f.name.lower() and self._text not in f.path.lower():
            return False
        if self._status and self._status != "все" and f.status != self._status:
            return False
        if self._ext and f.ext.lstrip(".") != self._ext:
            return False
        if self._min_size and f.size < self._min_size:
            return False
        if self._max_size and f.size > self._max_size:
            return False
        return True
