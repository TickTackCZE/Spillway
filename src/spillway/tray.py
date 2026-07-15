"""Menu bar ikona (F3) — vizuální stav Spillway v horní liště macOS.

Ikona odráží stav pipeline: 🎙️ idle · 🔴 nahrává · ⏳ přepisuje/upravuje.
Aktualizace jde přes `rumps.Timer` na hlavním vlákně (thread-safe) — jen čte
`controller.state`, který mění hotkey/worker vlákna.

Poznámka: rumps.App.run() blokuje hlavní vlákno (NSApplication run loop), proto
CGEventTap hotkey běží na vlastním vlákně (viz hotkey.py) — tím se nebijí.
"""

from __future__ import annotations

import rumps

from .app import IDLE, PROCESSING, RECORDING

_ICONS = {IDLE: "🎙️", RECORDING: "🔴", PROCESSING: "⏳"}


class SpillwayTray(rumps.App):
    def __init__(self, controller):  # noqa: ANN001
        super().__init__("Spillway", title=_ICONS[IDLE], quit_button="Konec")
        self.controller = controller
        self._timer = rumps.Timer(self._tick, 0.15)
        self._timer.start()

    def _tick(self, _sender) -> None:  # noqa: ANN001
        title = _ICONS.get(self.controller.state, _ICONS[IDLE])
        if self.title != title:
            self.title = title
