"""Menu bar aplikace (F3) — ikona + rozbalovací menu.

Ikona v liště: 🎙️ idle · 🔴 (červená) při nahrávání · ⏳ při zpracování.
Menu: přepnutí modelu, slovník, API klíč, autostart, kontext pole, Konec.

Stav ikony se aktualizuje přes `rumps.Timer` na hlavním vlákně (thread-safe) —
jen čte `controller.state`, který mění hotkey/worker vlákna.
"""

from __future__ import annotations

import keyring
import rumps

from . import autostart, config, settings
from .app import IDLE, PROCESSING, RECORDING
from .config import KEYRING_ACCOUNT, KEYRING_SERVICE

_ICON = {IDLE: "🎙️", RECORDING: "🔴", PROCESSING: "⏳"}
_MODELS = [
    ("Haiku (rychlé, levné)", "claude-haiku-4-5"),
    ("Sonnet (chytřejší, dražší)", "claude-sonnet-5"),
]


class SpillwayTray(rumps.App):
    def __init__(self, controller):  # noqa: ANN001
        super().__init__("Spillway", title=_ICON[IDLE], quit_button=None)
        self.controller = controller

        self._model_items = {
            mid: rumps.MenuItem(f"Model: {label}", callback=self._make_model_cb(mid))
            for label, mid in _MODELS
        }
        self._autostart_item = rumps.MenuItem(
            "Spouštět po přihlášení", callback=self.on_autostart
        )
        self._fieldctx_item = rumps.MenuItem(
            "Číst kontext pole", callback=self.on_fieldctx
        )
        self.menu = [
            *self._model_items.values(),
            None,
            rumps.MenuItem("Slovník výrazů…", callback=self.on_glossary),
            rumps.MenuItem("Nastavit API klíč…", callback=self.on_apikey),
            None,
            self._autostart_item,
            self._fieldctx_item,
            None,
            rumps.MenuItem("Konec", callback=lambda _: rumps.quit_application()),
        ]
        self._refresh_states()

        self._timer = rumps.Timer(self._tick, 0.15)
        self._timer.start()

    # --- stav ikony -------------------------------------------------------
    def _tick(self, _sender) -> None:  # noqa: ANN001
        title = _ICON.get(self.controller.state, _ICON[IDLE])
        if self.title != title:
            self.title = title

    def _refresh_states(self) -> None:
        current = config.get_model()
        for mid, item in self._model_items.items():
            item.state = 1 if mid == current else 0
        try:
            self._autostart_item.state = 1 if autostart.is_enabled() else 0
        except Exception:  # noqa: BLE001
            self._autostart_item.state = 0
        self._fieldctx_item.state = 1 if config.field_context() else 0

    # --- callbacky menu ---------------------------------------------------
    def _make_model_cb(self, mid: str):
        def cb(_sender) -> None:  # noqa: ANN001
            settings.set("model", mid)
            self.controller.set_model(mid)
            self._refresh_states()
            rumps.notification("Spillway", "Model změněn", mid)

        return cb

    def on_glossary(self, _sender) -> None:  # noqa: ANN001
        current = ", ".join(settings.get("glossary", []))
        resp = rumps.Window(
            message="Termíny oddělené čárkou (zůstanou beze změny, opraví se k nim přeslechy):",
            title="Slovník výrazů",
            default_text=current,
            ok="Uložit",
            cancel="Zrušit",
            dimensions=(380, 120),
        ).run()
        if resp.clicked:
            terms = [t.strip() for t in resp.text.split(",") if t.strip()]
            settings.set("glossary", terms)
            self.controller.set_glossary(terms)

    def on_apikey(self, _sender) -> None:  # noqa: ANN001
        resp = rumps.Window(
            message="Vlož Anthropic API klíč (uloží se do Keychain, ne do souboru):",
            title="API klíč",
            default_text="",
            ok="Uložit",
            cancel="Zrušit",
            dimensions=(380, 60),
        ).run()
        if resp.clicked and resp.text.strip():
            key = resp.text.strip()
            keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, key)
            self.controller.set_api_key(key)
            rumps.notification("Spillway", "API klíč uložen", "AI úprava je aktivní.")

    def on_autostart(self, _sender) -> None:  # noqa: ANN001
        try:
            if autostart.is_enabled():
                autostart.disable()
            else:
                autostart.enable()
        except Exception as exc:  # noqa: BLE001
            rumps.alert("Autostart selhal", str(exc))
        self._refresh_states()

    def on_fieldctx(self, _sender) -> None:  # noqa: ANN001
        settings.set("field_context", not config.field_context())
        self._refresh_states()
