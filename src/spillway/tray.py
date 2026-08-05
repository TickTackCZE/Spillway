"""Menu bar aplikace (F3) — ikona + okno nastavení.

Ikona v liště je Spillway logo (`baricon.py`), které odráží stav: v klidu stojí,
při nahrávání se hýbe podle hlasitosti mikrofonu, při zpracování jí běží vlna
zleva doprava.
Klik → menu s „Nastavení" (otevře Domovoy okno) a „Konec". Veškeré nastavení je
v okně (`settings_window.py`), ne v menu.

Stav se navíc ukazuje v plovoucím HUD u kurzoru (`hud.py`). Obojí řídí jeden
`rumps.Timer` na hlavním vlákně, takže animace nepotřebuje vlastní časovač.
"""

from __future__ import annotations

import rumps

from . import config
from .app import IDLE, PROCESSING, RECORDING

_BAR_ICON = "🎙️"  # placeholder; Spillway logo přijde s .app bundlem (ikonové assety)


class SpillwayTray(rumps.App):
    def __init__(self, controller):  # noqa: ANN001
        super().__init__("Spillway", title=_BAR_ICON, quit_button=None)
        self.controller = controller

        # Spillway logo (waveform) jako template ikona v liště; fallback = emoji.
        # `_icon_ok` říká, jestli se smí ikona animovat — bez ní jedeme na emoji
        # a přepínání snímků se přeskočí.
        self._icon_ok = False
        self._icon_key: tuple[str, int] | None = None
        self._pulse = 0
        try:
            from . import baricon

            path = baricon.icon_path()
            if path:
                self.template = True
                self.icon = path
                self.title = None
                self._icon_ok = True
                self._icon_key = ("idle", 0)
        except Exception:  # noqa: BLE001
            pass

        # Plovoucí status HUD u kurzoru (když selže, jedeme bez něj).
        self.hud = None
        try:
            from .hud import StatusHUD

            self.hud = StatusHUD()
            # Klik na lístek „Připraveno k vložení" = už ho nechci.
            self.hud.on_dismiss = self.controller.clear_awaiting_paste
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
            rumps.MenuItem("Nastavení", callback=self.open_settings),
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

        # Watchdog zaseklého zpracování — kdyby přepis/Claude zamrzl, po čase to
        # odsekne, ať appka nezůstane viset na „Zpracovávám" a nemusí se vypínat.
        self._stuck_timer = rumps.Timer(self._check_stuck, 5)
        self._stuck_timer.start()

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
                self.menu.insert_before("Nastavení", self._warn_item)
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
            idle_sec = config.get_auto_unload_seconds()
            if self.controller.transcriber.unload_if_idle(idle_sec):
                print(f"💤 Whisper model uvolněn z paměti (nečinný {idle_sec} s).")
        except Exception:  # noqa: BLE001
            pass

    def _left_target_app(self) -> bool:
        """Odešel uživatel z aplikace, do které diktoval (přepnul jinam / zavřel ji)?

        Pak nemá smysl držet okénko u kurzoru v cizí appce — přeskočí k ikoně
        v liště, kde ukáže reálný stav (Zpracovávám → Připraveno k vložení).
        """
        target = getattr(self.controller, "target_bundle", None)
        if not target:
            return False
        try:
            from . import context

            _, now = context.frontmost_app()
        except Exception:  # noqa: BLE001
            return False
        return bool(now) and now != target

    def _check_stuck(self, _sender) -> None:  # noqa: ANN001
        try:
            self.controller.watchdog_check()
        except Exception:  # noqa: BLE001
            pass

    def _install_edit_menu(self) -> None:
        """Přidá do hlavního menu položku Úpravy s Kopírovat/Vložit/… → teprve tím
        začnou v oknech (WKWebView popover i nastavení) fungovat ⌘C/⌘V/⌘X/⌘A.

        Bez hlavního menu nemá ⌘C kam poslat akci `copy:`, takže se běžný text
        v aplikaci nedal zkopírovat. Akce míří na first responder (nil target).
        """
        try:
            from AppKit import NSApp, NSMenu, NSMenuItem

            main = NSApp.mainMenu()
            if main is None:
                main = NSMenu.alloc().init()
                NSApp.setMainMenu_(main)
            for i in range(main.numberOfItems()):
                if main.itemAtIndex_(i).title() == "Úpravy":
                    return  # už tam je
            holder = NSMenuItem.alloc().init()
            holder.setTitle_("Úpravy")
            main.addItem_(holder)
            edit = NSMenu.alloc().initWithTitle_("Úpravy")
            holder.setSubmenu_(edit)
            for title, sel, key in (
                ("Vyjmout", "cut:", "x"),
                ("Kopírovat", "copy:", "c"),
                ("Vložit", "paste:", "v"),
                ("Vybrat vše", "selectAll:", "a"),
            ):
                edit.addItem_(
                    NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, key)
                )
        except Exception as exc:  # noqa: BLE001 — bez Edit menu appka jede dál
            print(f"(Edit menu nedostupné: {exc})")

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
        self._install_edit_menu()  # ať Cmd+C/V/A fungují v oknech (WKWebView)
        if self.hud is not None:
            self.hud.status_button = button  # HUD se podle ní ukotví pod lištu
        try:
            from .popover import PopoverController

            self._popover = PopoverController(
                self.controller,
                on_open_settings=lambda: self.open_settings(None),
                on_open_help=lambda: self.open_settings(None, page="help"),
                on_quit=lambda: self.quit_app(None),
            )
            self._popover.attach_to_button(button)
            item.setMenu_(None)  # klik teď otevře popover, ne menu
            print("🪟 Popover v liště připraven.")
        except Exception as exc:  # noqa: BLE001 — necháme rumps menu jako fallback
            import traceback

            # Ve frozen .app jde print do ~/Library/Logs/Spillway/spillway.log,
            # takže se dá diagnostikovat, proč popover ve zabalené appce nenaskočil.
            print(f"(popover nedostupný: {exc}) — zůstává klasické menu.\n{traceback.format_exc()}")
        self._popover_ready = True

    def _update_icon(self, state, cancelling: bool) -> None:  # noqa: ANN001
        """Snímek ikony podle stavu — živý ukazatel hlasitosti při nahrávání.

        Ikona se přepíše jen když se snímek opravdu změní; v klidu se tak na lištu
        nesahá vůbec a animace nic nestojí.
        """
        if not self._icon_ok:
            return
        from . import baricon

        if cancelling:
            key = ("cancel", 0)
        elif state == RECORDING:
            key = ("rec", baricon.level_step(self.controller.mic_level()))
        elif state == PROCESSING:
            self._pulse = (self._pulse + 1) % baricon.PULSE_FRAMES
            key = ("proc", self._pulse)
        else:
            # Klid i „připraveno k vložení" = základní logo. O čekající text se
            # hlásí lístek u ikony, ikona sama nemá blikat.
            key = ("idle", 0)
        if key == self._icon_key:
            return
        path = baricon.frame_path(*key)
        if path:
            self.icon = path
            self._icon_key = key

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
        # „Ruším" má přednost nad stavem — dokud rušení nedoběhne, nesmí se
        # HUD ani ikona vrátit na „Zpracovávám" (Whisper/Claude nejdou přerušit hned).
        try:
            cancelling = self.controller.is_cancelling()
            state = self.controller.state
        except Exception:  # noqa: BLE001
            return
        try:
            self._update_icon(state, cancelling)
        except Exception:  # noqa: BLE001 — animace ikony nesmí rozbít HUD
            pass
        if self.hud is None:
            return
        try:
            if cancelling:
                self.hud.show("cancel")
                return
            # K ikoně patří okénko ve dvou případech, které mají mít stejný
            # průběh: odešel jsi z cílové aplikace, nebo se diktuje bez
            # zaklikaného pole. Obojí končí lístkem „Připraveno k vložení"
            # na tomtéž místě pod ikonou.
            at_icon = self._left_target_app() or getattr(
                self.controller, "no_field", False
            )
            if state == RECORDING:
                self.hud.show("rec", at_icon=at_icon)
            elif state == PROCESSING:
                self.hud.show("proc", at_icon=at_icon)
            elif getattr(self.controller, "awaiting_paste", False):
                # Text čeká ve schránce → lístek u ikony. Zmizí klikem na něj
                # nebo jakmile uživatel kdekoliv stiskne ⌘V (viz hotkey.py).
                self.hud.show("ready")
            else:
                self.hud.hide()
        except Exception:  # noqa: BLE001
            pass

    def open_settings(self, _sender, page: str = "settings") -> None:  # noqa: ANN001
        try:
            if self._settings is None:
                from .settings_window import SettingsWindow

                self._settings = SettingsWindow(self.controller)
            self._settings.show(page)
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
