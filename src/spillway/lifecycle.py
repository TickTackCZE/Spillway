"""Single-instance zámek [B5] — zabrání dvěma běžícím Spillway naráz.

Dvě instance = dva event tapy na hotkey, dva `Recorder` o mikrofon, 2× Whisper
model v paměti. `acquire()` získá výhradní zámek přes `fcntl.flock`; když už
běží jiná instance, vrátí None a volající se má ukončit.

Zámek drží otevřený file descriptor po celou dobu běhu procesu — handle proto
neuvolňuj, dokud appka běží (OS ho pustí při ukončení procesu). JEDINÁ výjimka je
`release()` před tichým restartem: tam se appka právě chystá spustit svou náhradu,
a ta by na obsazený zámek narazila dřív, než tenhle proces stihne skončit.
"""

from __future__ import annotations

import fcntl
import os

_DIR = os.path.expanduser("~/Library/Application Support/Spillway")
_LOCK = os.path.join(_DIR, "spillway.lock")


_handle = None  # drží se po celou dobu běhu; `release()` ho pustí před restartem


def release() -> None:
    """Pustit zámek — jen před tichým restartem, aby ho nová instance dostala.

    Bez tohohle by nová instance našla zámek obsazený a `main()` ji rovnou
    ukončí (žádné opakování tam není) — po „restartu" by neběželo nic.
    """
    global _handle
    handle, _handle = _handle, None
    if handle is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
    except Exception:  # noqa: BLE001 — proces stejně za chvíli končí
        pass


def acquire():  # -> file object | None
    """Vrátí drženou zámkovou handle, nebo None, když už jiná instance běží."""
    global _handle
    handle = None
    try:
        os.makedirs(_DIR, exist_ok=True)
        handle = open(_LOCK, "w")
        # FD_CLOEXEC: kdyby proces ještě někdy prošel execve (i mimo náš
        # multiprocessing.freeze_support() fix), ať zámek nepřežije do dalšího
        # obrazu procesu a nekoliduje sám se sebou.
        fcntl.fcntl(handle.fileno(), fcntl.F_SETFD, fcntl.FD_CLOEXEC)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.write(str(os.getpid()))
        handle.flush()
        _handle = handle
        return handle
    except BlockingIOError:
        return None
    except Exception:  # noqa: BLE001 — při chybě zámku raději pustit (neblokovat běh)
        # `_handle` se schválně NEnastavuje: zámek se nezískal, takže není co
        # uvolňovat — a `release()` by pak zavíral handle, který nic nedrží.
        return handle
