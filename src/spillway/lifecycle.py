"""Single-instance zámek [B5] — zabrání dvěma běžícím Spillway naráz.

Dvě instance = dva event tapy na hotkey, dva `Recorder` o mikrofon, 2× Whisper
model v paměti. `acquire()` získá výhradní zámek přes `fcntl.flock`; když už
běží jiná instance, vrátí None a volající se má ukončit.

Zámek drží otevřený file descriptor po celou dobu běhu procesu — handle proto
neuvolňuj, dokud appka běží (OS ho pustí při ukončení procesu).
"""

from __future__ import annotations

import fcntl
import os

_DIR = os.path.expanduser("~/Library/Application Support/Spillway")
_LOCK = os.path.join(_DIR, "spillway.lock")


def acquire():  # -> file object | None
    """Vrátí drženou zámkovou handle, nebo None, když už jiná instance běží."""
    handle = None
    try:
        os.makedirs(_DIR, exist_ok=True)
        handle = open(_LOCK, "w")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.write(str(os.getpid()))
        handle.flush()
        return handle
    except BlockingIOError:
        return None
    except Exception:  # noqa: BLE001 — při chybě zámku raději pustit (neblokovat běh)
        return handle
