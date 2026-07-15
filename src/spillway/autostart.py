"""Automatické spuštění po přihlášení (LaunchAgent).

Zapíše `~/Library/LaunchAgents/com.spillway.agent.plist`, který po přihlášení
spustí `uv run python run_spillway.py` v adresáři projektu. Ve fázi F3 (zabalení
do .app) tohle nahradí `SMAppService`.

Pozn.: dokud běží z Google Drive složky, cesta obsahuje mezery — ošetřeno.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from xml.sax.saxutils import escape

LABEL = "com.spillway.agent"
_PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")


def _project_dir() -> str:
    # src/spillway/autostart.py → o tři úrovně výš je kořen projektu.
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _uv() -> str:
    return shutil.which("uv") or "/opt/homebrew/bin/uv"


def is_enabled() -> bool:
    return os.path.exists(_PLIST)


def enable() -> None:
    project = _project_dir()
    cmd = f'cd "{project}" && exec "{_uv()}" run python run_spillway.py'
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
    # Načíst hned (jinak by se spustil až po dalším přihlášení).
    subprocess.run(["launchctl", "unload", _PLIST], capture_output=True)
    subprocess.run(["launchctl", "load", _PLIST], capture_output=True)


def disable() -> None:
    subprocess.run(["launchctl", "unload", _PLIST], capture_output=True)
    try:
        os.remove(_PLIST)
    except FileNotFoundError:
        pass
