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

from . import config, models, settings, status
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
            self.hud.on_dismiss = self._hud_clicked
        except Exception as exc:  # noqa: BLE001
            print(f"(HUD nedostupný: {exc})")

        # Kartička s upozorněním vedle popoveru/nastavení (chybí model nebo klíč).
        self._notice = None
        # Poslední rozeslaný stav připravenosti — rozesílá se jen při změně.
        self._status_last: dict | None = None

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
        # Po instalaci ukázat jednou nastavení — bez modelu appka nediktuje
        # a uživatel by to jinak zjistil až prvním nefunkčním stiskem klávesy.
        self._welcome_checked = False
        # Ukázat uvítací blok, až uživatel Nastavení sám otevře (viz `_maybe_welcome`).
        self._show_welcome_next_time = False
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

    def _maybe_welcome(self) -> None:
        """Po instalaci si poznamená, že uvítání ještě neproběhlo.

        Okno samo NEOTEVÍRÁ. Dřív ho po instalaci bez modelu vyvolalo z tiku —
        a okno, které vyskočí bez kliknutí, je přesně to, co uživatel nechce.
        Že chybí model, řekne kartička vedle popoveru i okénko při prvním
        pokusu o diktát; uvítací blok se ukáže, až Nastavení otevře sám.
        """
        self._welcome_checked = True
        try:
            if settings.get("seen_setup", False):
                return
            settings.set("seen_setup", True)
            self._show_welcome_next_time = not models.is_ready()
        except Exception:  # noqa: BLE001 — uvítání nesmí shodit start
            pass

    def _broadcast_status(self) -> None:
        """Rozešle stav připravenosti do všech otevřených oken — jen při změně.

        Jediné místo, které stav do oken TLAČÍ. Okna si ho můžou při otevření
        vyzvednout sama (`status.snapshot()`), ale aktualizace za běhu chodí
        odsud. Dřív měl každý povrch vlastní odběr `models.add_download_listener`
        a skládal si stav po svém, takže popover hlásil „Chybí model",
        nastavení zároveň „Stahuji 40 %" a kartička nabízela stažení, které
        už běželo.

        Posílá se z tiku (6,7×/s), ale jen když se stav opravdu změnil —
        `snapshot()` je cachovaný, takže srovnání nic nestojí.
        """
        snap = status.snapshot()
        if snap == self._status_last:
            return
        self._status_last = snap
        win = self._settings
        if win is not None and win.is_visible():
            win.bridge.apply_status(snap)
        pop = getattr(self, "_popover", None)
        if pop is not None and pop.is_shown():
            pop.bridge.apply_status(snap)

    def _notice_windows(self) -> list:
        """Okna kartičky, která k popoveru patří (viz `popover._own_window`)."""
        n = self._notice
        return [n.panel] if n is not None and n.is_visible() else []

    def _notice_target(self):  # noqa: ANN201
        """(okno, jeho VIDITELNÝ obdélník na obrazovce) pro kartičku — nebo None.

        Vrací obdélník obsahu, ne rám okna. Okno popoveru je kolem obsahu větší
        o šipku a o místo na stín, takže zarovnání podle rámu posadilo kartičku
        výš a dál od popoveru, než vypadá správně.
        """
        pop = getattr(self, "_popover", None)
        if pop is not None and pop.is_shown():
            try:
                view = pop.popover.contentViewController().view()
                win = view.window()
                if win is not None and win.isVisible():
                    in_window = view.convertRect_toView_(view.bounds(), None)
                    return (win, win.convertRectToScreen_(in_window))
            except Exception:  # noqa: BLE001
                return None
        win = self._settings
        if win is not None and win.is_visible():
            try:
                # Běžné okno průhledný okraj nemá — rám JE viditelný obdélník.
                return (win.window, win.window.frame())
            except Exception:  # noqa: BLE001
                return None
        return None

    def _update_notice(self) -> None:
        """Kartička visí vedle otevřeného popoveru nebo nastavení; jinak je pryč.

        Tohle je JEDINÉ místo, které rozhoduje o její viditelnosti — kartička
        není potomek rodičovského okna, protože připnutý potomek rozbíjí
        zavírání popoveru klikem mimo (viz `notice.show_beside`).
        """
        snap = status.snapshot()
        target = self._notice_target()
        if target is None or (snap["ready"] and snap["key_ok"]):
            if self._notice is not None:
                self._notice.hide()
            return

        if self._notice is None:
            try:
                from .notice import NoticePanel

                self._notice = NoticePanel()
                self._notice.on_key = self._notice_key_action
            except Exception as exc:  # noqa: BLE001 — bez kartičky se dá žít
                print(f"(upozornění nedostupné: {exc})")
                return
        self._notice.show_beside(*target, snap)

    def _notice_key_action(self, what: str) -> None:
        """Tlačítka u hlášky o API klíči."""
        import time as _t

        if what == "key_snooze":
            settings.set("key_notice_snooze_until", _t.time() + 7 * 24 * 3600)
            status.invalidate()               # projeví se hned, ne až po TTL
            print("🔕 upozornění na API klíč odloženo o týden")
            return
        self.open_settings(None, why="kartička · Zadat klíč")

    def _hud_clicked(self) -> None:
        """Klik na okénko: vždycky ho zavře, a u výzvy ke stažení otevře Nastavení.

        Že klik sem vede do Nastavení, je v pořádku — okno se ale smí otevřít
        JEN když klik opravdu trefil kartu. Dřív bylo okno o 100 px širší než
        karta a průhledný okraj kolem ní bral kliknutí taky; okénko visí přesně
        pod ikonou, takže se do něj trefil i druhý klik z dvojkliku na ikonu.
        Okno teď kartu obepíná (`_fit_to_card`) a než se doměří, myš propadává
        (`_measured`).
        """
        wanted_model = (getattr(self.controller, "model_missing", False)
                        and not getattr(self.controller, "model_notice_hidden", False))
        self.controller.dismiss_notice()
        if wanted_model:
            self.open_settings(None, why="okénko · Chybí model")

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
        """Po dokončení diktátu přetlačit čerstvý stav do otevřeného nastavení.

        Statistiky samy jsou v popoveru, ne v okně nastavení — tohle obnovuje
        stav okna (stav modelu, klíče, přepínače), který se po diktátu mohl
        změnit. Okno se jinak plní jen při `ready`, tj. při prvním načtení
        HTML, takže bez tohohle by viselo na hodnotách z prvního otevření.
        Běží z rumps.Timeru = main thread, takže `evaluateJavaScript` je bezpečné.
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
                on_open_settings=lambda: self.open_settings(None, why="popover · Nastavení"),
                on_open_help=lambda: self.open_settings(None, page="help",
                                                        why="popover · Nápověda"),
                on_quit=lambda: self.quit_app(None),
            )
            # Kartička s upozorněním visí vedle popoveru ve vlastním okně.
            # Bez tohohle by ji hlídač kliků bral jako „venku" a klik na její
            # tlačítko Stáhnout by popover zavřel uprostřed stahování.
            self._popover.extra_windows = self._notice_windows
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
        if not getattr(self, "_welcome_checked", True):
            self._maybe_welcome()
        try:
            pop = getattr(self, "_popover", None)
            if pop is not None:
                pop.close_if_app_inactive()   # ⌘Tab pryč → popover taky
        except Exception:  # noqa: BLE001 — nesmí utnout zbytek tiku
            pass
        try:
            self.controller.check_key_released()
        except Exception:  # noqa: BLE001 — nesmí utnout zbytek tiku
            pass
        try:
            self._broadcast_status()
        except Exception:  # noqa: BLE001 — rozesílání nesmí rozbít zbytek tiku
            pass
        try:
            self._update_notice()
        except Exception:  # noqa: BLE001 — kartička nesmí rozbít zbytek tiku
            pass
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
            # Výzva ke stažení drží, dokud na ni uživatel neklikne — i po
            # návratu do klidu. Přeskočit ji na „Zpracovávám" nedává smysl,
            # protože bez modelu se nic nezpracovává.
            if (getattr(self.controller, "model_missing", False)
                    and not getattr(self.controller, "model_notice_hidden", False)):
                self.hud.show("nomodel")
            elif state == RECORDING:
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

    def open_settings(self, _sender, page: str = "settings", *,
                      welcome: bool = False, why: str = "menu") -> None:  # noqa: ANN001
        """Otevře Nastavení. Volat JEN z akce, kterou uživatel opravdu udělal.

        `why` říká, odkud se kliklo, a zapíše se do logu. Okno vyskakující samo
        od sebe je nejotravnější chyba, jakou tahle aplikace uměla — a bez
        záznamu se hledá špatně, protože se to děje nahodile. Tenhle řádek
        v logu příště ukáže viníka na první pokus.
        """
        print(f"⚙️  otevírám Nastavení ({why})")
        try:
            if self._settings is None:
                from .settings_window import SettingsWindow

                self._settings = SettingsWindow(self.controller)
            if self._show_welcome_next_time:
                welcome = True
                self._show_welcome_next_time = False
            self._settings.show(page, welcome=welcome)
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
