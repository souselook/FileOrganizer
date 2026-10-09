"""QSS-стили светлой и тёмной темы. Только строки, без логики."""
from __future__ import annotations

LIGHT_QSS = """
QWidget { background: #f5f6f8; color: #1e2229; font-size: 13px; }
QMainWindow, QDialog { background: #f5f6f8; }
QToolBar { background: #ffffff; border-bottom: 1px solid #d7dbe0; spacing: 6px; padding: 4px; }
QToolButton { background: #eef1f4; border: 1px solid #cfd6dd; border-radius: 6px;
              padding: 6px 10px; }
QToolButton:hover { background: #e2e8ef; }
QToolButton:disabled { color: #9aa4af; background: #f0f2f5; }
QPushButton { background: #2d6cdf; color: white; border: none; border-radius: 6px;
              padding: 7px 14px; }
QPushButton:hover { background: #2459b8; }
QPushButton:disabled { background: #b6c6de; color: #eef; }
QPushButton#dangerBtn { background: #d64541; }
QPushButton#dangerBtn:hover { background: #b8352f; }
QTabBar::tab { background: #e8ecf1; padding: 7px 16px; border: 1px solid #d0d6dd;
               border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; }
QTabBar::tab:selected { background: #ffffff; font-weight: 600; }
QTreeView, QTableView, QListView { background: #ffffff; border: 1px solid #d0d6dd;
                                   alternate-background-color: #f6f8fa; }
QHeaderView::section { background: #eaeef3; padding: 5px; border: 1px solid #d0d6dd;
                       font-weight: 600; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
    background: #ffffff; border: 1px solid #c8d0d8; border-radius: 5px; padding: 4px 6px; }
QProgressBar { border: 1px solid #c8d0d8; border-radius: 6px; background: #ffffff;
               text-align: center; height: 18px; }
QProgressBar::chunk { background: #2d6cdf; border-radius: 5px; }
QStatusBar { background: #eceff3; }
QGroupBox { border: 1px solid #d0d6dd; border-radius: 8px; margin-top: 10px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #2d6cdf;
                   font-weight: 600; }
"""

DARK_QSS = """
QWidget { background: #23262b; color: #dde2e8; font-size: 13px; }
QMainWindow, QDialog { background: #23262b; }
QToolBar { background: #2a2e34; border-bottom: 1px solid #3a4048; spacing: 6px; padding: 4px; }
QToolButton { background: #33383f; border: 1px solid #444b54; border-radius: 6px;
              padding: 6px 10px; color: #dde2e8; }
QToolButton:hover { background: #3d434c; }
QToolButton:disabled { color: #6b7480; background: #2c3036; }
QPushButton { background: #3d7bfd; color: white; border: none; border-radius: 6px;
              padding: 7px 14px; }
QPushButton:hover { background: #5589ff; }
QPushButton:disabled { background: #39424f; color: #7b8593; }
QPushButton#dangerBtn { background: #d64541; }
QTabBar::tab { background: #2c3036; padding: 7px 16px; border: 1px solid #3a4048;
               border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; }
QTabBar::tab:selected { background: #23262b; font-weight: 600; }
QTreeView, QTableView, QListView { background: #1d2024; border: 1px solid #3a4048;
                                   alternate-background-color: #24282d; color: #dde2e8; }
QHeaderView::section { background: #2c3036; padding: 5px; border: 1px solid #3a4048;
                       font-weight: 600; color: #dde2e8; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
    background: #1d2024; border: 1px solid #3a4048; border-radius: 5px;
    padding: 4px 6px; color: #dde2e8; }
QProgressBar { border: 1px solid #3a4048; border-radius: 6px; background: #1d2024;
               text-align: center; color: #dde2e8; height: 18px; }
QProgressBar::chunk { background: #3d7bfd; border-radius: 5px; }
QStatusBar { background: #2a2e34; }
QGroupBox { border: 1px solid #3a4048; border-radius: 8px; margin-top: 10px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #79a3ff;
                   font-weight: 600; }
QToolTip { background: #2c3036; color: #dde2e8; border: 1px solid #444b54; }
"""


def qss_for(theme: str) -> str:
    return DARK_QSS if theme == "dark" else LIGHT_QSS
