"""Perzistentní nastavení Spillway (mění je menu v liště).

Ukládá se do `~/Library/Application Support/Spillway/settings.json`. API klíč
sem NEpatří — ten je v Keychain (config.py). Prahové/citlivé věci lze přebít env
proměnnými (viz config.py).
"""

from __future__ import annotations

import json
import os
import threading

_DIR = os.path.expanduser("~/Library/Application Support/Spillway")
_PATH = os.path.join(_DIR, "settings.json")
_lock = threading.Lock()

_DEFAULTS: dict = {
    "model": "claude-haiku-4-5",
    "field_context": True,
    "auto_space": True,
    "glossary": [],
    "theme": "system",   # system | light | dark
    "language": "cs",    # primární jazyk diktování
    "hotkey_keycode": 176,           # nativní diktovací klávesa (viz keymap.py)
    "hotkey_label": "F5 (diktování)",
}


def _load() -> dict:
    try:
        with open(_PATH, encoding="utf-8") as f:
            return {**_DEFAULTS, **json.load(f)}
    except Exception:  # noqa: BLE001
        return dict(_DEFAULTS)


def get(key: str, default=None):
    return _load().get(key, _DEFAULTS.get(key, default))


def set(key: str, value) -> None:  # noqa: A003
    with _lock:
        data = _load()
        data[key] = value
        os.makedirs(_DIR, exist_ok=True)
        # [B11] Atomický zápis: do .tmp a os.replace(), ať pád uprostřed zápisu
        # nepoškodí settings.json (poškozený JSON → tiché ztracení všech nastavení).
        tmp = _PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _PATH)
