"""Spouštěč Spillway (F1). Přidá src/ na path a spustí app.

    uv run python run_spillway.py

Ve fázi F3 nahradí instalovatelný balíček + menu bar .app.
"""

import multiprocessing
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from spillway.app import main  # noqa: E402

if __name__ == "__main__":
    # Ve zabalené .app (PyInstaller) by bez tohoto multiprocessing na macOS
    # (start metoda "spawn") při forku znovu spustil CELÝ tento skript místo
    # jen worker funkce — appka by se sama znovu nastartovala jako podproces
    # (mj. i single-instance zámek by pak kolidoval sám se sebou).
    multiprocessing.freeze_support()
    main()
