"""Menu bar aplikace (F3) — ikona + okno nastavení.

Ikona v liště je statická (Spillway logo, zatím emoji placeholder). Klik → menu
s „Nastavení…" (otevře Domovoy okno) a „Konec". Veškeré nastavení je v okně
(`settings_window.py`), ne v menu.

Stav nahrávání/zpracování se ukazuje v plovoucím HUD u kurzoru (`hud.py`),
řízeném přes `rumps.Timer` na hlavním vlákně.
"""

from __future__ import annotations

import rumps

from . import config
from .app import PROCESSING, RECORDING

_BAR_ICON = "🎙️"  # placeholder; Spillway logo přijde s .app bundlem (ikonové assety)


class SpillwayTray(rumps.App):
    def __init__(self, controller):  # noqa: ANN001
        super().__init__("Spillway", title=_BAR_ICON, quit_button=None)
        self.controller = controller

        # Spillway logo (waveform) jako template ikona v liště; fallback = emoji.
        try:
            from . import baricon

            path = baricon.icon_path()
            if path:
                self.template = True
                self.icon = path
                self.title = None
        except Exception:  # noqa: BLE001
            pass

        # Plovoucí status HUD u kurzoru (když selže, jedeme bez něj).
        self.hud = None
        try:
            from .hud import StatusHUD

            self.hud = StatusHUD()
        except Exception as exc:  # noqa: BLE001
            print(f"(HUD nedostupný: {exc})")

        # Okno nastavení (Domovoy design) — vytvoří se líně při prvním otevření.
        self._settings = None

        self.menu = [
            rumps.MenuItem("Nastavení…", callback=self.open_settings),
            None,
            rumps.MenuItem("Konec", callback=self.quit_app),
        ]

        self._timer = rumps.Timer(self._tick, 0.15)
        self._timer.start()

        # [R5] Periodicky uvolnit Whisper model po nečinnosti (~1,5–2 GB RAM).
        self._unload_timer = rumps.Timer(self._check_unload, 30)
        self._unload_timer.start()

    def _check_unload(self, _sender) -> None:  # noqa: ANN001
        try:
            if getattr(self.controller, "state", "IDLE") != "IDLE":
                return  # neuvolňovat uprostřed nahrávání/zpracování
            idle_min = config.get_auto_unload_minutes()
            if self.controller.transcriber.unload_if_idle(idle_min * 60):
                print(f"💤 Whisper model uvolněn z paměti (nečinný {idle_min:.0f} min).")
        except Exception:  # noqa: BLE001
            pass

    def _tick(self, _sender) -> None:  # noqa: ANN001
        if self.hud is None:
            return
        try:
            state = self.controller.state
            if state == RECORDING:
                self.hud.show("rec")
            elif state == PROCESSING:
                self.hud.show("proc")
            else:
                self.hud.hide()
        except Exception:  # noqa: BLE001
            pass

    def open_settings(self, _sender) -> None:  # noqa: ANN001
        try:
            if self._settings is None:
                from .settings_window import SettingsWindow

                self._settings = SettingsWindow(self.controller)
            self._settings.show()
        except Exception as exc:  # noqa: BLE001
            rumps.alert("Nastavení nelze otevřít", str(exc))

    def quit_app(self, _sender) -> None:  # noqa: ANN001
        # [B19] Uvolnit event tap a mikrofon PŘED ukončením — rumps.quit_application()
        # ukončí proces uvnitř run(), takže finally v app.main() se nespustí.
        try:
            listener = getattr(self.controller, "hotkey_listener", None)
            if listener is not None:
                listener.stop()
            self.controller.recorder.stop()
        except Exception:  # noqa: BLE001
            pass
        rumps.quit_application()
