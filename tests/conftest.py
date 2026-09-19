"""Sdílené nastavení testů — přidá src/ na path a staví Controller bez __init__."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))


def controller_stub(state):
    """Controller bez `__init__` (nechceme načítat Whisper model).

    Nastavuje VŠECHNA pole, na která sahá kód mimo pipeline — jinak každé nové
    pole shodí půlku sady na `AttributeError` v místě, které s ním nesouvisí.
    Test si pak přepíše jen to, o čem doopravdy je.

    Bydlí v `conftest`, ne v jednom z test souborů: sahá na něj logika i UI a
    druhá kopie by se s první rozešla přesně ve chvíli, kdy `Controller`
    přibude pole.
    """
    import threading

    from spillway.app import Controller

    c = Controller.__new__(Controller)
    c.state = state
    c._lock = threading.Lock()
    c._cancel = threading.Event()
    c._cancel_min_until = 0.0  # [F10] skutečné jméno atributu, ne staré cancel_notice_until
    c._pasting = False
    c.model_missing = False
    c.model_notice_hidden = False
    c.awaiting_paste = False
    c.mic_unavailable = False
    c.mic_notice_hidden = False
    c._mic_worked = False
    c._needs_restart = False
    c._restart_urgent = False
    c._restart_reason = ""
    return c
