"""Дерево папок сканированной директории (строится из списка файлов)."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from app.core.models import FileItem

ROLE_PATH = Qt.UserRole + 1


class FolderTree(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(1)
        self.setHeaderLabels(["Папки"])
        self.setUniformRowHeights(True)

    def rebuild(self, root: str, files: list[FileItem]) -> None:
        self.clear()
        if not root:
            return
        root_norm = str(Path(root))
        root_item = QTreeWidgetItem([Path(root_norm).name or root_norm])
        root_item.setData(0, ROLE_PATH, root_norm)
        self.addTopLevelItem(root_item)
        children: dict[str, QTreeWidgetItem] = {root_norm: root_item}

        # строим дерево папок по относительным путям
        for f in files:
            try:
                rel_parent = Path(f.path).relative_to(Path(root_norm)).parent
            except ValueError:
                continue  # файл вне корня — игнорируем без падения
            cur = root_norm
            for part in rel_parent.parts:
                nxt = str(Path(cur) / part)
                if nxt not in children:
                    item = QTreeWidgetItem([part])
                    item.setData(0, ROLE_PATH, nxt)
                    children[cur].addChild(item)
                    children[nxt] = item
                cur = nxt

        # количество файлов в каждой папке (включая вложенные)
        dir_of_file = [str(Path(f.path).parent) for f in files]
        for path in sorted(children.keys(), key=lambda s: -len(Path(s).parts)):
            norm = path.rstrip("/\\")
            total = sum(
                1 for d in dir_of_file
                if d == norm or d.startswith(norm + "/") or d.startswith(norm + "\\")
            )
            children[path].setText(0, f"{Path(path).name or path}  ({total})")
        self.expandToDepth(1)

    def selected_path(self) -> str | None:
        item = self.currentItem()
        return item.data(0, ROLE_PATH) if item else None
