"""Menu bar aplikace (F3) — ikona + okno nastavení.

Ikona v liště je statická (Spillway logo, zatím emoji placeholder). Klik → menu
s „Nastavení…" (otevře Domovoy okno) a „Konec". Veškeré nastavení je v okně
(`settings_window.py`), ne v menu.

Stav nahrávání/zpracování se ukazuje v plovoucím HUD u kurzoru (`hud.py`),
řízeném přes `rumps.Timer` na hlavním vlákně.
"""

from __future__ import annotations

import os
import time as _time

import rumps

from . import config
from .app import IDLE, PROCESSING, RECORDING

_BAR_ICON = "🎙️"  # placeholder; Spillway logo přijde s .app bundlem (ikonové assety)

# Ladicí zápis napojení popoveru do souboru — ve vývoji (bez frozen .app) jdou
# printy do terminálu, takže bychom je jinak z tohohle prostředí nepřečetli.
_DBG_PATH = os.path.expanduser("~/Library/Logs/Spillway/popover-debug.log")


def _dbg(msg: str) -> None:
    try:
        os.makedirs(os.path.dirname(_DBG_PATH), exist_ok=True)
        with open(_DBG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{_time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:  # noqa: BLE001
        pass


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

        # Popover pod ikonou (přehled + historie + model) — napojí se na tlačítko
        # status itemu až po startu run loopu (status item vzniká uvnitř run()).
        self._popover = None
        self._popover_ready = False

        # Varovná položka (skrytá, dokud nezjistíme mrtvý event tap — B23).
        self._warn_item = rumps.MenuItem(
            "⚠️ Klávesa nefunguje — povol oprávnění", callback=self._open_privacy
        )
        self.menu = [
            rumps.MenuItem("Nastavení…", callback=self.open_settings),
            None,
            rumps.MenuItem("Konec", callback=self.quit_app),
        ]

        self._timer = rumps.Timer(self._tick, 0.15)
        self._timer.start()

        # [B23] Jednorázová kontrola stavu event tapu AŽ po startu run loopu —
        # dřív se notifikace o mrtvém tapu posílala moc brzy a tiše mizela.
        self._tap_checked = False
        self._tapcheck_timer = rumps.Timer(self._check_tap, 1.0)
        self._tapcheck_timer.start()

        # [R5] Periodicky uvolnit Whisper model po nečinnosti (~1,5–2 GB RAM).
        # Kontrola po 5 s, ať uvolnění nezpozdí víc než samotný idle práh.
        self._unload_timer = rumps.Timer(self._check_unload, 5)
        self._unload_timer.start()

    def _check_tap(self, _sender) -> None:  # noqa: ANN001
        listener = getattr(self.controller, "hotkey_listener", None)
        if listener is None or listener.tap_ok is None:
            return  # ještě nevíme (tap se zakládá na jiném vlákně) — zkusíme za 1 s
        self._tap_checked = True
        self._tapcheck_timer.stop()
        if listener.tap_ok is False:
            # Trvale viditelné: notifikace + položka v menu + vykřičník v liště.
            rumps.notification(
                "Spillway", "Klávesa nefunguje",
                "Chybí Zpřístupnění / Monitorování vstupu. Klikni v menu na ⚠️.",
            )
            if self._warn_item.title not in self.menu:
                self.menu.insert_before("Nastavení…", self._warn_item)
            try:
                if not getattr(self, "template", False):
                    self.title = "🎙️⚠️"
            except Exception:  # noqa: BLE001
                pass
            print(f"⚠️ {listener.tap_error}")

    def _open_privacy(self, _sender) -> None:  # noqa: ANN001
        """Otevře přímo Nastavení systému → Soukromí → Zpřístupnění."""
        import subprocess

        try:
            subprocess.Popen([
                "open",
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            ])
        except Exception:  # noqa: BLE001
            pass

    def _check_unload(self, _sender) -> None:  # noqa: ANN001
        try:
            if getattr(self.controller, "state", "IDLE") != "IDLE":
                return  # neuvolňovat uprostřed nahrávání/zpracování
            idle_min = config.get_auto_unload_minutes()
            if self.controller.transcriber.unload_if_idle(idle_min * 60):
                print(f"💤 Whisper model uvolněn z paměti (nečinný {idle_min * 60:.0f} s).")
        except Exception:  # noqa: BLE001
            pass

    def _refresh_stats_when_done(self) -> None:
        """Po dokončení diktátu obnovit kartu Statistiky, je-li okno otevřené.

        `stats.record` zapíše data hned, ale okno se plní jen při `ready` (tj.
        při prvním načtení HTML) — bez tohohle by čísla naskočila až po zavření
        a znovuotevření nastavení. Běží z rumps.Timeru = main thread, takže
        `evaluateJavaScript` je bezpečné.
        """
        state = getattr(self.controller, "state", IDLE)
        prev = getattr(self, "_prev_state", state)
        self._prev_state = state
        if state != IDLE or prev == IDLE:
            return  # zajímá nás jen přechod „něco běželo" → hotovo
        win = self._settings
        if win is not None and win.is_visible():
            win.refresh()
        pop = getattr(self, "_popover", None)
        if pop is not None and pop.is_shown():
            pop.bridge.push_state()  # čerstvá čísla/historie, když je popover zrovna otevřený

    def _setup_popover(self) -> None:
        """Jednorázově: přesměruj klik na ikonu na vlastní popover místo rumps menu.

        Status item (a jeho tlačítko) vzniká až uvnitř `run()`, takže to nejde
        udělat v __init__ — zkoušíme to z prvního ticku. Když se to nepovede,
        necháme původní menu (fallback) a už to nezkoušíme donekonečna.
        """
        nsapp = getattr(self, "_nsapp", None)
        item = getattr(nsapp, "nsstatusitem", None) if nsapp is not None else None
        button = item.button() if item is not None else None
        if button is None:
            return  # status item ještě není — zkusíme za další tick
        try:
            from .popover import PopoverController

            self._popover = PopoverController(
                self.controller,
                on_open_settings=lambda: self.open_settings(None),
                on_quit=lambda: self.quit_app(None),
            )
            self._popover.attach_to_button(button)
            item.setMenu_(None)  # klik teď otevře popover, ne menu
            print("🪟 Popover v liště připraven.")
        except Exception as exc:  # noqa: BLE001 — necháme rumps menu jako fallback
            import traceback

            # Chybu zapiš i do souboru — ve frozen .app jde print jinam a takhle
            # se dá diagnostikovat, proč popover ve zabalené appce nenaskočil.
            _dbg("setup FAIL\n" + traceback.format_exc())
            print(f"(popover nedostupný: {exc}) — zůstává klasické menu.")
        self._popover_ready = True

    def _tick(self, _sender) -> None:  # noqa: ANN001
        if not getattr(self, "_popover_ready", False):
            try:
                self._setup_popover()
            except Exception:  # noqa: BLE001
                self._popover_ready = True  # nezkoušet donekonečna
        try:
            self._refresh_stats_when_done()
        except Exception:  # noqa: BLE001 — statistika nesmí rozbít HUD
            pass
        if self.hud is None:
            return
        try:
            # „Ruším" má přednost nad stavem — dokud rušení nedoběhne, nesmí se
            # HUD vrátit na „Zpracovávám" (Whisper/Claude nejdou přerušit hned).
            if self.controller.is_cancelling():
                self.hud.show("cancel")
                return
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
