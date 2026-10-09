"""Сборка FileOrganizer в один .exe (PyInstaller).

Запускать на Windows 10 с Python 3.11:
    pip install pyinstaller
    python build_exe.py
Результат: dist/FileOrganizer.exe
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",          # перезаписывать сборку без вопросов
    "--clean",              # очищать кэш PyInstaller
    "--onefile",            # ОДИН exe
    "--windowed",           # без консольного окна (--noconsole)
    "--name", "FileOrganizer",
    str(ROOT / "run.py"),
]

print("Выполняю:", " ".join(cmd))
result = subprocess.run(cmd, cwd=ROOT)
if result.returncode == 0:
    print("\nOK: dist/FileOrganizer.exe готов.")
else:
    sys.exit(result.returncode)
