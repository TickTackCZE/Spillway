"""Automatické spuštění po přihlášení (LaunchAgent).

Zapíše `~/Library/LaunchAgents/com.spillway.agent.plist`.

[F4] Příkaz se liší podle toho, jak Spillway běží:
  - zabalená `.app` → přímé spuštění binárky `…/Contents/MacOS/Spillway`;
  - vývojový běh ze zdrojáků → `uv run python run_spillway.py` v projektu.
Dřív se plist psal VŽDY na `run_spillway.py` odvozený z `__file__` — jenže ve
frozen buildu ukazuje `__file__` dovnitř bundlu, kde žádný `run_spillway.py`
není. Login item pak po přihlášení tiše selhal, ale UI hlásilo „zapnuto".

Pozn.: dřív se frozen větev spouštěla přes `open -a <app>`; přešli jsme na
přímé spuštění binárky v bundlu — launchd tak appku vidí jako svůj job a je to
předvídatelnější (žádný mezikrok přes LaunchServices).

Pozn.: dokud běží z Google Drive složky, cesta obsahuje mezery — ošetřeno.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from xml.sax.saxutils import escape

LABEL = "com.spillway.agent"
_PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")


def _project_dir() -> str:
    # src/spillway/autostart.py → o tři úrovně výš je kořen projektu.
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _uv() -> str:
    return shutil.which("uv") or "/opt/homebrew/bin/uv"


def _bundle_executable() -> str | None:
    """Cesta k binárce v bundlu, ze kterého běžíme (jen frozen), jinak None."""
    if not getattr(sys, "frozen", False):
        return None
    p = os.path.abspath(sys.executable)
    # sys.executable ve frozen .app UŽ je …/Spillway.app/Contents/MacOS/Spillway.
    return p if ".app/Contents/MacOS/" in p else None


def _launch_command() -> str:
    exe = _bundle_executable()
    if exe:
        return f'exec "{exe}"'
    return f'cd "{_project_dir()}" && exec "{_uv()}" run python run_spillway.py'


def is_enabled() -> bool:
    return os.path.exists(_PLIST)


def enable() -> None:
    cmd = _launch_command()
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/sh</string>
        <string>-c</string>
        <string>{escape(cmd)}</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>ProcessType</key><string>Interactive</string>
</dict>
</plist>
"""
    os.makedirs(os.path.dirname(_PLIST), exist_ok=True)
    with open(_PLIST, "w", encoding="utf-8") as f:
        f.write(plist)
    # [B5] NEnačítat hned přes `launchctl load` — spustilo by to DRUHOU instanci
    # souběžně s běžící (dva event tapy, dva mikrofony, 2× Whisper model).
    # `RunAtLoad` zajistí start až po příštím přihlášení; teď už appka běží.


def disable() -> None:
    subprocess.run(["launchctl", "unload", _PLIST], capture_output=True)
    try:
        os.remove(_PLIST)
    except FileNotFoundError:
        pass
