"""Spillway F1 — MVP pipeline (bez LLM, bez UI).

Propojuje: hotkey (F5, hold-to-talk) → audio (mikrofon) → transcribe
(faster-whisper) → paste (Cmd+V do aktivní aplikace).

Stavový automat: IDLE → RECORDING → (TRANSCRIBING → PASTING) → IDLE.
on_press/on_release běží na vlákně event tapu → drží se triviální; těžká práce
(přepis + vložení) jde na worker vlákno.

Spuštění:  uv run python run_spillway.py
Vyžaduje oprávnění: Microphone, Input Monitoring, Accessibility.
"""

from __future__ import annotations

import signal
import sys
import threading
import time

from . import config, context, diag, models, stats
from .audio import Recorder
from .hotkey import HotkeyListener
from .llm import Cleaner, basic_cleanup
from .paste import copy_to_clipboard, paste_text
from .transcribe import Transcriber, next_segment_boundary, voiced_seconds

IDLE, RECORDING, PROCESSING = "IDLE", "RECORDING", "PROCESSING"

# Minimální doba, po kterou „Ruším" zůstane v HUD i poté, co pipeline doběhne.
# Jen proti probliknutí u okamžitého zrušení — hlavní podmínkou je běžící stav
# (viz `is_cancelling`), ne časovač.
CANCEL_MIN_VISIBLE_S = 0.6

_CANCELLED = object()  # sentinel: běh přerušen Escapem uprostřed


class _Abort(Exception):
    """Řízené ukončení pipeline se známým výsledkem — ne chyba.

    Kroky pipeline jsou samostatné metody, takže „tady skonči a zapiš tenhle
    `outcome`" už nejde udělat prostým `return`. Výjimka to nese až do jediného
    `try/except/finally` v `_process`, kde se zapisuje statistika. Odlišení od
    `Exception` je podstatné: zrušený ani prázdný diktát nesmí uživateli
    vyhodit notifikaci „Chyba při vkládání".
    """

    def __init__(self, outcome: str) -> None:
        super().__init__(outcome)
        self.outcome = outcome


def _call_safely(fn) -> None:
    """Zavolá `fn` (když není None) a nenechá jeho chybu uniknout do pipeline."""
    if fn is None:
        return
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — vedlejší úklid nesmí nic shodit
        print(f"⚠️  vedlejší volání selhalo: {exc}")


def _preview(text: str) -> str:
    """Bezpečný náhled pro log: buď délka (default), nebo plný text při ladění.

    [security] Do logu se ve výchozím stavu NEpíše obsah diktátů — log není
    šifrovaný a leží v běžném umístění. Plný text jen s diagnostickou oblastí
    `text` (viz `diag.py`).
    """
    return repr(text) if diag.enabled("text") else f"{len(text)} zn."


def _setup_logging() -> str | None:
    """Ve zabalené .app (bez terminálu) není kam psát print() — přesměruj
    stdout/stderr do logu, ať je appka diagnostikovatelná. Vrátí cestu k logu."""
    import os

    log_dir = os.path.expanduser("~/Library/Logs/Spillway")
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "spillway.log")
        # [security] Log ořízni, když překročí 1 MB — jinak roste donekonečna
        # (a s ním i množství citlivého obsahu, co v něm skončí).
        try:
            if os.path.getsize(log_path) > 1_000_000:
                os.remove(log_path)
        except OSError:
            pass
        # line-buffered, ať se zápisy objeví hned (ne až po pádu)
        f = open(log_path, "a", buffering=1, encoding="utf-8")
        # Přesměruj jen ve frozen buildu; při vývoji chceme vidět terminál.
        if getattr(sys, "frozen", False):
            sys.stdout = f
            sys.stderr = f
        import datetime

        print(f"\n===== Spillway start {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====")
        return log_path
    except Exception:  # noqa: BLE001
        return None


def _log_permission_diagnostics() -> None:
    """Zapiš do logu, jestli má proces Accessibility a jaká je jeho identita —
    ground truth pro ladění mrtvého event tapu (B23)."""
    try:
        from ApplicationServices import AXIsProcessTrusted

        print(f"🔐 AXIsProcessTrusted (Zpřístupnění): {AXIsProcessTrusted()}")
    except Exception as exc:  # noqa: BLE001
        print(f"🔐 AXIsProcessTrusted nelze zjistit: {exc}")


def notify(title: str, message: str) -> None:
    """[B12] Viditelná chyba i bez terminálu (pod LaunchAgentem). Tichý no-op,
    když nejsme pod běžící rumps app."""
    try:
        import rumps

        rumps.notification("Spillway", title, message)
    except Exception:  # noqa: BLE001
        pass


class Controller:
    def __init__(self, *, raw_mode: bool = False) -> None:
        self.recorder = Recorder()
        self.transcriber = Transcriber()  # načte model (chvíli trvá)
        self.state = IDLE
        self._lock = threading.Lock()
        # Zrušení běžícího zpracování (Escape) — šetří tokeny i čekání, když
        # uživatel po puštění klávesy zjistí, že nadiktoval nesmysl.
        self._cancel = threading.Event()
        # Dokdy (monotonic) držet „Ruším" i po doběhnutí pipeline — jen proti
        # probliknutí; hlavní podmínka je běžící stav (viz `is_cancelling`).
        self._cancel_min_until = 0.0
        # [F5] Bod, za kterým už rušit nejde — vkládání běží (0,25–1,2 s kvůli
        # sleepům). Escape po něm nesmí spolknout klávesu ani označit hotový
        # diktát za zrušený.
        self._pasting = False
        # Kdy (monotonic) začalo PROCESSING — pro watchdog zaseklého zpracování.
        self._processing_since = 0.0
        # Text skončil ve schránce (odešel jsi z pole / přepnul appku) a čeká, až
        # si ho vložíš. Drží lístek „Připraveno k vložení" u ikony v liště.
        self.awaiting_paste = False
        # Aplikace, do které se diktuje (bundle ID). Podle ní HUD pozná, že jsi
        # odešel jinam, a přeskočí od kurzoru nahoru k ikoně v liště.
        self.target_bundle: str | None = None
        # Diktuje se bez zaklikaného pole? Zjistí se JEDNOU na začátku nahrávání
        # a platí pro celý diktát, ať je flow jednotný: okénko visí pod ikonou
        # už při nahrávání a zůstane tam přes zpracování až po lístek
        # „Připraveno k vložení". Bez toho by okénko během diktátu poskakovalo
        # podle toho, co zrovna má fokus.
        self.no_field = False
        # Jak dopadlo zjištění fokusu ("ano"/"ne"/"?") — jde do souhrnu diktátu,
        # ať se dá i bez zapnuté diagnostiky zpětně poznat, proč text skončil
        # ve schránce místo v poli.
        self._focus_field = "?"
        # Chybí model pro přepis? Zjistí se při startu nahrávání a drží po celý
        # diktát — okénko podle toho nabídne stažení místo mlčení.
        self.model_missing = False
        # Uživatel výzvu „Chybí model" schoval (klikem nebo rušicí klávesou).
        # Platí jen pro tenhle pokus — u dalšího diktátu se ukáže znovu, jinak
        # by po prvním schování mlčky mizely všechny další diktáty.
        self.model_notice_hidden = False
        # Vyhlazená hlasitost mikrofonu (0..1) pro animovanou ikonu v liště.
        self._level_smooth = 0.0
        # [F2] Vlákno, které otevírá mikrofon; `_process` na něj počká.
        self._start_thread: threading.Thread | None = None
        # Streaming přepis: vlákno segmentuje řeč v tichu a přepisuje segmenty už
        # během mluvení; `_process` pak dopřepíše jen poslední úsek a zřetězí.
        self._stream_thread: threading.Thread | None = None
        self._stream_committed = 0            # kolik vzorků už je v segmentech
        self._stream_segments: list[str] = []  # přepsané segmenty (v pořadí)
        # Pořadové číslo diktátu. Streamovací smyčka si ho na startu zapamatuje a
        # při každé změně skončí — jinak by smyčka, která nestihla doběhnout do
        # `join` timeoutu, psala segmenty do NÁSLEDUJÍCÍHO diktátu (a zahlcovala
        # GPU frontu). To byl jeden z důvodů zaseknutí po opakovaném stisku klávesy.
        self._dictation_id = 0

        # [F2/F3] AI úprava přes Claude — konfigurovatelná za běhu z menu.
        self.raw_mode = raw_mode
        self.api_key = None
        self.model = config.get_model()
        self.glossary = config.glossary()
        self.language = config.get_language()
        self.cleaner: Cleaner | None = None
        # Klíč z Klíčenky se NEČTE na hlavním vlákně. `SecItemCopyMatching` umí
        # čekat libovolně dlouho — typicky když macOS po přeinstalování .app
        # ukáže dialog „Spillway chce použít Klíčenku". Tohle běží dřív, než
        # vznikne ikona v liště, takže dokud uživatel dialog neodklepne, nemá
        # aplikace ŽÁDNÉ UI: vypadá to, že se vůbec nespustila. (Změřeno na
        # zaseknutém startu: hlavní vlákno stálo v `SecItemCopyMatching`.)
        self._key_thread: threading.Thread | None = None
        if raw_mode:
            self._build_cleaner()
        else:
            self._key_thread = threading.Thread(target=self._load_api_key, daemon=True)
            self._key_thread.start()

    def _load_api_key(self) -> None:
        """Přečte klíč z Klíčenky a postaví cleaner. Běží na vlákně od startu."""
        try:
            self.api_key = config.get_api_key()
        except Exception as exc:  # noqa: BLE001 — bez klíče se dá diktovat dál
            print(f"⚠️  klíč z Klíčenky se nepodařilo přečíst: {exc}")
            self.api_key = None
        self._build_cleaner()

    def _await_api_key(self, timeout: float = 5.0) -> None:
        """Počká, až doběhne čtení klíče (jen na worker vlákně, ne z UI!).

        Za normálních okolností je hotové dávno před prvním diktátem — čeká se
        jen v tom nepravděpodobném případě, kdy uživatel stihne diktovat dřív,
        než odklikne dialog Klíčenky.
        """
        th = self._key_thread
        if th is not None and th.is_alive():
            th.join(timeout)

    def _build_cleaner(self) -> None:
        if self.api_key:
            self.cleaner = Cleaner(self.api_key, model=self.model)
            print(f"🤖 AI úprava zapnuta ({self.model}).")
        else:
            self.cleaner = None
            if not self.raw_mode:
                print("ℹ️  Bez API klíče → raw režim. Klíč vlož v menu (ikona 🎙️).")

    def set_model(self, model: str) -> None:
        self.model = model
        self._build_cleaner()

    def set_api_key(self, key: str) -> None:
        self.api_key = key
        self.raw_mode = False
        self._build_cleaner()

    def set_glossary(self, terms: list[str]) -> None:
        self.glossary = terms

    def set_language(self, language: str) -> None:
        self.language = language

    def request_cancel(self) -> bool:
        """Zruší běžící nahrávání/zpracování. Vrací True, když bylo co rušit —
        podle toho tap pozná, jestli má klávesu spolknout (jinde musí Escape
        fungovat normálně). Volá se z vlákna tapu → drž to triviální."""
        # Výzva „Chybí model" i lístek „Připraveno k vložení" jdou schovat
        # rušicí klávesou. Klávesa se přesto NEspolkne — schování okénka není
        # důvod, aby Escape přestal fungovat ve zbytku systému.
        if self.model_missing:
            self.model_notice_hidden = True
        with self._lock:
            # [F5] Už se vkládá → pozdě. Vrátit False, ať Escape projde do
            # systému normálně a diktát se nezapíše jako zrušený.
            if self.state == IDLE or self._pasting:
                return False
            # Rušení PŘI NAHRÁVÁNÍ musí nahrávání i ukončit. Dřív se jen nastavil
            # příznak a čekalo se na puštění klávesy — jenže do té doby běžel
            # mikrofon dál a HUD visel na „Ruším" bez konce (uživatel: „nešlo
            # zrušit"). Převezmeme řízení od `on_release`.
            take_over = self.state == RECORDING
            if take_over:
                self.state = PROCESSING
                self._processing_since = time.monotonic()
        self._cancel.set()
        self._cancel_min_until = time.monotonic() + CANCEL_MIN_VISIBLE_S
        print("🚫 ruším… (nic se nevloží)")
        if take_over:
            # Vlákno tapu drž triviální — těžké `recorder.stop()` udělá `_process`,
            # který rovnou uvidí `_cancel`, uvolní mikrofon a skončí na IDLE.
            self._cancel_watchdog()
            threading.Thread(target=self._process, daemon=True).start()
        return True

    def clear_model_notice(self) -> None:
        """Schová výzvu „Chybí model" — klik na ni, nebo rušicí klávesa.

        Nesahá na `model_missing`: to je stav pipeline (bez modelu se opravdu
        nedá přepisovat) a přepsat ho jen kvůli tomu, aby okénko zmizelo, dřív
        znamenalo, že se po puštění klávesy rozjela pipeline bez modelu a
        skončila hláškou „Chyba při vkládání".
        """
        self.model_notice_hidden = True

    def clear_awaiting_paste(self) -> None:
        """Lístek „Připraveno k vložení" pryč — uživatel text vložil (⌘V), klikl
        na lístek, nebo začal nový diktát."""
        self.awaiting_paste = False

    def mic_level(self) -> float:
        """Vyhlazená hlasitost mikrofonu 0..1 pro živý ukazatel v ikoně lišty.

        Vyhlazení je záměrně asymetrické (nahoru skokem, dolů pozvolna) — stejně
        jako u studiových ukazatelů. Bez něj by ikona mezi slabikami padala na nulu
        a jen by blikala; takhle sleduje řeč a v tichu klidně klesne.
        Mimo nahrávání vrací 0, ať se nesahá na buffer zbytečně.
        """
        if self.state != RECORDING:
            self._level_smooth = 0.0
            return 0.0
        try:
            raw = self.recorder.level()
        except Exception:  # noqa: BLE001 — ukazatel nikdy nesmí shodit nahrávání
            return self._level_smooth
        self._level_smooth = max(raw, self._level_smooth * 0.65)
        return self._level_smooth

    def is_cancelling(self) -> bool:
        """True, dokud má HUD ukazovat „Ruším".

        Drží se BĚŽÍCÍHO stavu, ne časovače: Whisper ani volání Claude nejdou
        přerušit uprostřed, takže po Escape ještě chvíli dobíhají — a po celou
        tu dobu musí HUD říkat „Ruším", ne se vrátit na „Zpracovávám".
        """
        if not self._cancel.is_set():
            return False
        with self._lock:
            if self._pasting:
                return False  # [F5] vkládá se → rušení už neplatí
            if self.state != IDLE:
                return True  # pipeline ještě dobíhá → pořád rušíme
        # Doběhlo — krátký dojezd, ať hláška neproblikne u okamžitého zrušení.
        return time.monotonic() < self._cancel_min_until

    def on_press(self) -> None:
        with self._lock:
            if self.state != IDLE:
                # Souběh: předchozí nahrávka se ještě zpracovává → nová se ignoruje
                # (žádná fronta — ať se nevloží text do špatného pole). Zkus po chvíli.
                print(f"⏳ zaneprázdněno ({self.state}) — počkej na dokončení.")
                return
            self.state = RECORDING
            self._dictation_id += 1
            dictation_id = self._dictation_id
        self._cancel.clear()  # nový diktát → zahodit staré zrušení
        self._cancel_min_until = 0.0  # ať „Ruším" nepřebíjí nové „Nahrávám"
        self.awaiting_paste = False   # starý lístek pryč, jede nový diktát
        # Popisy cíle z MINULÉHO diktátu musí zmizet hned, ne až je přepíše
        # `_start_recording` na svém vlákně: lišta je čte každý tik (6,7×/s) a
        # do té doby by okénko kotvila podle starého pole a mohla bliknout
        # „Chybí model", i když ho uživatel mezitím stáhl.
        self.target_bundle = None
        self.no_field = False
        self._focus_field = "?"
        self.model_notice_hidden = False
        # `is_ready()` je jen `os.path.exists` — levné i tady, a díky tomu je
        # příznak platný od první chvíle nahrávání (viz `_process`).
        try:
            self.model_missing = not models.is_ready()
        except Exception:  # noqa: BLE001
            self.model_missing = False
        if self.model_missing:
            print("⚠️  model pro přepis chybí — okénko nabídne stažení")
        print("🔴 nahrávám… (drž F5)")
        # [F2] `recorder.start()` otevírá vstupní zařízení — u Bluetooth mikrofonu
        # (přepnutí do HFP) i stovky ms až sekundu. Na vlákně tapu by to hrozilo
        # `kCGEventTapDisabledByTimeout` → ztracený key-up a nepotlačené F5.
        # Stejný důvod jako B9 u `stop()`; stav je nastavený, takže HUD naskočí hned.
        # POZOR: `_process` si na tohle vlákno musí počkat (join) — Recorder
        # nechrání životní cyklus streamu, takže `stop()` před dokončeným
        # `start()` by nechal mikrofon otevřený napořád (viz B2).
        self._start_thread = threading.Thread(target=self._start_recording, daemon=True)
        self._start_thread.start()
        # Předehřát Whisper model, dokud uživatel mluví — po auto-unloadu by se
        # jinak čekalo ~1,6 s až po puštění klávesy. Takhle se reload schová.
        if not self.transcriber.is_loaded:
            threading.Thread(target=self.transcriber.preload, daemon=True).start()
        # Streaming přepis během mluvení (když zapnuto). Krátký diktát bez pauz
        # nevytvoří segmenty → `_process` spadne na dávkový přepis.
        self._stream_committed = 0
        self._stream_segments = []
        if config.streaming():
            self._stream_thread = threading.Thread(
                target=self._stream_loop, args=(dictation_id,), daemon=True
            )
            self._stream_thread.start()
        else:
            self._stream_thread = None
        # [B7] Watchdog: kdyby se ztratil key-up (spánek, lock, Secure Input),
        # po max_seconds nahrávání vynuceně ukončíme, ať appka nezůstane v RECORDING.
        self._arm_watchdog()

    def _start_recording(self) -> None:
        """[F2] Otevření mikrofonu na worker vlákně (ne na tapu).

        Když uživatel stihne pustit klávesu dřív, než se stream otevře, drží
        pořadí DVĚ nezávislé věci: `Recorder._open_lock` zaručí, že `stop()`
        nesáhne na rozdělaný `start()`, a `_await_recorder_start()` v pipeline
        počká, ať se vůbec stihne něco nahrát. Ani jedno samo nestačí — bez
        zámku by `stop()` po vypršení pětisekundového čekání zavřel „nic" a
        mikrofon by zůstal otevřený do restartu (B2).
        """
        try:
            # Zapamatovat cílovou aplikaci — HUD podle ní pozná odchod jinam.
            # (Tady, ne v `on_press`: to běží na vlákně tapu a musí být triviální.)
            try:
                self.target_bundle = context.frontmost_app()[1]
            except Exception:  # noqa: BLE001
                self.target_bundle = None
            # Není kam psát? Pak celý diktát běží „u ikony" (viz `no_field`).
            try:
                snap = context.focus_snapshot()
                self.no_field = snap.ok and not snap.is_input
                self._focus_field = ("ano" if snap.is_input else "ne") if snap.ok else "?"
                why = snap.description
            except Exception:  # noqa: BLE001
                self.no_field = False
                self._focus_field = "?"
                why = "chyba zjišťování fokusu"
            diag.log("focus", f"{why} → okénko {'u ikony' if self.no_field else 'u pole'}")
            self.recorder.start()
        except Exception as exc:  # noqa: BLE001 — [O6] viditelná chyba, ne tichý pád
            print(f"❌ mikrofon se nepodařilo spustit: {exc}")
            notify("Mikrofon nedostupný", "Nahrávání se nepodařilo spustit.")
            with self._lock:
                self.state = IDLE
            self._cancel_watchdog()

    def _stream_loop(self, dictation_id: int) -> None:
        """Během nahrávání segmentuje řeč v tichu a přepisuje segmenty průběžně.
        Výsledky ukládá do `self._stream_segments` / `self._stream_committed`,
        které `_process` po puštění klávesy převezme. Chyba tu nikdy nesmí shodit
        diktát — v nejhorším zůstane committed, kde je, a `_process` dopřepíše zbytek.

        `dictation_id` váže smyčku na KONKRÉTNÍ diktát: jakmile začne další (nebo
        se stav změní), smyčka okamžitě skončí a už nic nezapíše. Bez toho by
        smyčka, která nestihla doběhnout do `join` timeoutu, kontaminovala další
        diktát a hromadila práci v GPU frontě (→ zaseknutí appky)."""
        committed = 0

        def _mine() -> bool:
            with self._lock:
                return self.state == RECORDING and self._dictation_id == dictation_id

        try:
            while True:
                if self._cancel.is_set() or not _mine():
                    return
                time.sleep(0.35)
                if self._cancel.is_set() or not _mine():
                    return
                audio = self.recorder.snapshot()
                while True:
                    if self._cancel.is_set() or not _mine():
                        return
                    # Nezahlcovat GPU frontu: když se předchozí práce ještě nestihla
                    # zpracovat, nech zbytek na `_process` (dopřepíše ho vcelku).
                    if getattr(self.transcriber, "busy", False):
                        break
                    b = next_segment_boundary(audio, committed)
                    if b is None:
                        break
                    seg = audio[committed:b]
                    if seg.size < int(0.3 * 16000):  # < 0,3 s → nech to na `_process`
                        return
                    try:
                        txt = self.transcriber.transcribe(seg, language=self.language)
                    except Exception as exc:  # noqa: BLE001
                        print(f"(streaming segment selhal: {exc}) → zbytek dopřepíše pipeline")
                        return  # committed zůstává → `_process` přepíše vše od něj
                    if not txt:
                        return  # prázdný přepis → radši ať zbytek vezme `_process`
                    # Zápis až po ÚSPĚCHU, ATOMICKY (text + pozice pod jedním zámkem)
                    # a jen když pořád patří tomuhle diktátu. Kdyby se zapsal jen
                    # text, `_process` by ten úsek přepsal znovu → zdvojený text;
                    # kdyby jen pozice, audio by se ztratilo.
                    with self._lock:
                        if self.state != RECORDING or self._dictation_id != dictation_id:
                            return
                        self._stream_segments.append(txt)
                        committed = b
                        self._stream_committed = committed
        except Exception as exc:  # noqa: BLE001 — streaming nesmí shodit diktát
            print(f"(streaming loop error: {exc})")

    def _arm_watchdog(self) -> None:
        self._cancel_watchdog()
        timeout = float(self.recorder.max_frames) / 16000.0 + 2.0
        self._watchdog = threading.Timer(timeout, self._on_watchdog)
        self._watchdog.daemon = True
        self._watchdog.start()

    def _cancel_watchdog(self) -> None:
        wd = getattr(self, "_watchdog", None)
        if wd is not None:
            wd.cancel()
            self._watchdog = None

    def _on_watchdog(self) -> None:
        print("⚠️  watchdog: ztracený key-up → vynucené ukončení nahrávky.")
        self.on_release()

    def on_release(self) -> None:
        with self._lock:
            if self.state != RECORDING:
                return
            self.state = PROCESSING
            self._processing_since = time.monotonic()
        self._cancel_watchdog()
        # [B9] recorder.stop() dělá gc.collect() + restart PortAudia (stovky ms).
        # Nesmí běžet na vlákně event tapu (timeout tapu → nepotlačené F5). Přesuň
        # ho celý na worker vlákno; on_release tak zůstane triviální.
        threading.Thread(target=self._process, daemon=True).start()

    def _run_cancellable(self, fn, on_late=None):
        """Spustí `fn` na vlákně a čeká — ale když během běhu přijde Escape,
        přestane čekat a vrátí `_CANCELLED` (vlákno dobíhá na pozadí, výsledek
        se zahodí). Díky tomu je zrušení okamžité i uprostřed přepisu / volání
        Clauda, místo aby se čekalo, až blokující volání doběhne.

        `on_late` se zavolá právě jednou, a JEN když se výsledek zahodil kvůli
        zrušení. U volání, které něco stálo (provolané tokeny u Clauda), je to
        jediná příležitost náklad zaúčtovat — v hlavním toku už je řádek diktátu
        dávno zapsaný. Zámek `guard` řeší souběh, kdy `fn` doběhne přesně ve
        chvíli zrušení: bez něj by se `on_late` podle toho, kdo byl rychlejší,
        buď nezavolalo vůbec, nebo dvakrát.
        """
        box: dict = {}
        guard = threading.Lock()
        gave_up = [False]
        finished = [False]

        def _run() -> None:
            try:
                box["r"] = fn()
            except BaseException as exc:  # noqa: BLE001 — přenést na hlavní tok
                box["e"] = exc
            with guard:
                finished[0] = True
                orphaned = gave_up[0]
            if orphaned:
                _call_safely(on_late)

        th = threading.Thread(target=_run, daemon=True)
        th.start()
        while th.is_alive():
            if self._cancel.is_set():
                with guard:
                    gave_up[0] = True
                    already_done = finished[0]
                if already_done:
                    # Doběhlo přesně teď — vlákno kolem `on_late` prošlo dřív,
                    # než jsme stihli nastavit příznak. Zaúčtuj to tady.
                    _call_safely(on_late)
                return _CANCELLED
            th.join(0.03)
        if "e" in box:
            raise box["e"]
        return box.get("r")

    # ---- pipeline po puštění klávesy ------------------------------------
    # `_process` drží jen orchestraci; každý krok má vlastní metodu. Kroky na
    # sobě závisí POŘADÍM (audio → kontext → přepis → AI → oddělovač → vložení)
    # a nejde je přeskládat — proč, je vždy u té které metody.

    def _abort_without_model(self) -> None:
        """Zahodí nahrávku, když chybí model. Bez toho by si ho mlx začal TIŠE
        stahovat (1,6 GB na GPU vlákně) a aplikace by na minutu zamrzla."""
        print("⛔ diktát zahozen — chybí model pro přepis")
        self.model_missing = True  # ať okénko i lišta ukazují totéž
        try:
            # [F2] I tady se musí počkat na otevírání mikrofonu — `stop()` před
            # dokončeným `start()` by nechal stream viset otevřený.
            self._await_recorder_start()
            self.recorder.stop()
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️  mikrofon se nepodařilo zavřít: {exc}")
        with self._lock:
            self.state = IDLE
            self._processing_since = 0.0
        self._cancel_watchdog()

    def _await_recorder_start(self) -> None:
        """[F2] Počká, až doběhne otevírání mikrofonu na worker vlákně.

        Musí předcházet KAŽDÉMU `recorder.stop()` v pipeline. Pořadí start/stop
        sice od opravy B2 hlídá `Recorder` sám (`_open_lock`), ale bez čekání by
        se u pomalého Bluetooth mikrofonu zavřel stream hned po otevření a
        diktát by vyšel prázdný.
        """
        starter = getattr(self, "_start_thread", None)
        if starter is not None:
            starter.join(timeout=5.0)

    def _collect_audio(self) -> tuple:
        """Ukončí nahrávání → (audio, běžel streamovací přepis?).

        Pořadí uvnitř je závazné a nesmí se rozpadnout mezi volajícího a tuhle
        metodu: počkat na `start()` → `stop()` → počkat na streamovací vlákno.
        Kdyby `stop()` přišel dřív než dokončený `start()`, zůstane mikrofon
        otevřený napořád (B2); kdyby se nepočkalo na streamovací vlákno, zapíše
        poslední segment až do seznamu DALŠÍHO diktátu.
        """
        self._await_recorder_start()
        audio = self.recorder.stop()  # [B9] těžké volání až tady, na workeru
        stream_th = getattr(self, "_stream_thread", None)
        if stream_th is not None:
            stream_th.join(timeout=3.0)
        return audio, stream_th is not None

    def _start_context_gather(self) -> tuple:
        """Spustí sběr kontextu na vlákně → (vlákno, slovník s výsledkem).

        [F2/F3] Běží PARALELNĚ s přepisem: kontext nepotřebuje audio a
        `browser_context` čeká na `osascript` (až 2 s). Dřív to běželo před
        přepisem a ta doba se čistě přičítala; teď se schová za Whisper.

        Má vedlejší efekt `self.target_bundle` a je to ZÁMĚR, ne nedopatření:
        HUD se řídí `target_bundle` a vkládání `ctx["bundle"]`. Kdyby se z téhle
        metody udělala čistá funkce bez zápisu do stavu, okénko by po přepnutí
        aplikace během držení klávesy hlásilo jiný cíl, než kam text opravdu jde.
        """
        ctx: dict = {}

        def _gather() -> None:
            try:
                a_name, a_bundle = context.frontmost_app()
                ctx["app_name"], ctx["bundle"] = a_name, a_bundle
                self.target_bundle = a_bundle
                ctx["profile"] = context.app_profile(a_bundle, a_name)
                ctx["win_target"] = context.is_windows_target(a_bundle, a_name)
                # JEDEN snímek fokusu pro všechno — obsah pole, kurzor i otisk
                # pole musí pocházet ze stejného okamžiku. Dřív to byly tři
                # nezávislé dotazy a mezi nimi se fokus mohl změnit. Otisk pole
                # slouží k ověření před vložením, že jsme pořád ve stejném poli.
                snap = context.focus_snapshot(want_text=True, want_sig=True)
                ctx["field_text"], ctx["caret"] = snap.text, snap.caret
                ctx["field_sig"] = snap.sig
                if config.field_context():
                    b_profile, b_domain = context.browser_context(a_bundle)
                    ctx["domain"] = b_domain
                    if b_profile:
                        ctx["profile"] = b_profile
            except Exception as exc:  # noqa: BLE001 — bez kontextu jedeme dál
                ctx["error"] = exc

        th = threading.Thread(target=_gather, daemon=True)
        th.start()
        return th, ctx

    def _transcribe_audio(self, audio, streaming: bool) -> str:
        """Audio → text. Zruší-li uživatel, vyhodí `_Abort`.

        Streaming: segmenty (řez v tichu) se přepsaly už během mluvení, takže se
        dopřepíše jen poslední úsek a zřetězí. Když streaming nic
        nesegmentoval (krátký diktát bez pauz) → committed=0 → přepíše se celé
        audio dávkou. Slovník (hotwords) jde jen do dávky.
        """
        if not self.transcriber.is_loaded:
            print("💤→🔄 model byl uvolněný z paměti, znovu se načítá…")
        t0 = time.perf_counter()
        if streaming:
            # Text a pozici čte JEDEN zámek: smyčka je zapisuje atomicky, takže
            # jen tak dostaneme dvojici, která k sobě patří. Rozdělit ta dvě
            # čtení = zdvojený nebo ztracený kus textu.
            with self._lock:
                committed = int(self._stream_committed)
                segments = list(self._stream_segments)
            tail = audio[committed:] if 0 <= committed < audio.size else audio[:0]
            print(f"⏳ přepisuji zbytek {tail.size / 16000.0:.1f} s "
                  f"(streaming: {len(segments)} segm. za mluvení)…")
            tail_text = self._run_cancellable(
                lambda: self.transcriber.transcribe(tail, language=self.language)
            )
            if tail_text is _CANCELLED:
                raise _Abort("cancelled")
            parts = segments + ([tail_text] if tail_text else [])
            raw = " ".join(p for p in parts if p).strip()
        else:
            print(f"⏳ přepisuji {len(audio) / 16000.0:.1f} s audia…")
            # Cancellable: Escape během přepisu ho okamžitě opustí.
            raw = self._run_cancellable(lambda: self.transcriber.transcribe(
                audio,
                language=self.language,
                hotwords=self.glossary if config.whisper_hotwords() else None,
            ))
            if raw is _CANCELLED:
                raise _Abort("cancelled")
        dt = time.perf_counter() - t0
        if not raw:
            print(f"… prázdný přepis ({dt:.1f} s) — nic nevkládám.")
            raise _Abort("empty")
        print(f"📝 přepis ({dt:.1f} s): {_preview(raw)}")
        return raw

    def _read_context(self, ctx_thread, ctx: dict) -> dict:
        """Převezme kontext posbíraný souběžně s přepisem a dopočítá popisky."""
        ctx_thread.join(timeout=3.0)
        app_name = ctx.get("app_name")
        domain = ctx.get("domain")
        profile = ctx.setdefault("profile", "generic")
        ctx["app_ctx"] = f"{app_name} ({domain})" if domain else app_name
        win_note = " · Windows (Ctrl+V)" if ctx.get("win_target") else ""
        print(f"   ({ctx['app_ctx']} · profil: {profile}{win_note})")
        return ctx

    def _apply_ai(self, raw: str, ctx: dict, audio_secs: float) -> tuple:
        """Přepis → hotový text přes Clauda → (text, cena v USD).

        Cena se vrací spolu s textem schválně: `last_cost_usd` je stav sdílený
        mezi diktáty a další diktát ho přepíše. Musí se přečíst na stejném
        volání jako request — a to i po chybě, protože volání, které spadlo až
        na uříznuté odpovědi, tokeny reálně provolalo.
        """
        profile = ctx.get("profile", "generic")
        # Krátký diktát („ok", „díky", „zítra v pět") do Clauda neposíláme —
        # ušetří tokeny i ~1 s čekání. E-mail je výjimka: tam je i u krátké
        # zprávy smyslem doplnit strukturu (oslovení/pozdrav).
        min_s = config.llm_min_seconds()
        skip_llm = min_s > 0 and audio_secs < min_s and profile != "email"
        # Uživatel může AI úpravu úplně vypnout (přepínač „Odesílání do AI
        # modelu") — pak nic neodchází k Anthropic, vloží se jen lokální úprava.
        if not config.ai_edit():
            text = basic_cleanup(raw)
            print(f"🔒 AI úprava vypnutá → bez AI: {_preview(text)}")
            return text, 0.0
        if skip_llm:
            text = basic_cleanup(raw)
            print(f"⚡ krátký diktát ({audio_secs:.1f} s < {min_s:g} s) → bez AI: {_preview(text)}")
            return text, 0.0
        # Čtení klíče běží od startu na vlákně — tady, na workeru, se na něj
        # smí počkat (v UI nikdy: viz `_await_api_key`).
        self._await_api_key()
        if self.cleaner is None:
            return raw, 0.0

        before = self._field_context_for(ctx, profile)
        if before:
            print(f"   ↳ kontext pole: {len(before)} zn.")
        try:
            # Cancellable: Escape během volání Clauda ho okamžitě opustí
            # (odpověď dobíhá na pozadí a zahodí se). Nejdelší krok pipeline.
            # `on_late` zaúčtuje tokeny, které stihlo provolat — cena dorazí až
            # po zrušení, kdy je řádek diktátu dávno zapsaný.
            result = self._run_cancellable(
                lambda: self.cleaner.clean(
                    raw,
                    app_name=ctx.get("app_ctx"),
                    profile=profile,
                    before_text=before,
                    glossary=self.glossary,
                ),
                on_late=self._bill_orphaned_llm_call,
            )
        except Exception as exc:  # noqa: BLE001 — [O6] chyba, ale text neztratit
            print(f"⚠️  AI úprava selhala ({exc}) → vkládám syrový přepis.")
            notify("AI úprava selhala", "Vložen syrový přepis. Zkontroluj API klíč / kredit.")
            return raw, self._llm_cost()
        if result is _CANCELLED:
            raise _Abort("cancelled")  # cenu doúčtuje `on_late`
        text = result or raw
        print(f"✨ upraveno: {_preview(text)}")
        return text, self._llm_cost()

    def _llm_cost(self) -> float:
        return getattr(self.cleaner, "last_cost_usd", 0.0) or 0.0

    def _bill_orphaned_llm_call(self) -> None:
        """Zaúčtuje volání Clauda, jehož odpověď dorazila až po zrušení."""
        cost = self._llm_cost()
        if cost > 0:
            print(f"💸 zrušené volání přesto stálo ${cost:.4f} — účtuji zvlášť")
            stats.record_extra_cost(cost, note="cancelled")

    @staticmethod
    def _field_context_for(ctx: dict, profile: str) -> str | None:
        """Existující obsah pole jako kontext pro Clauda (jen když povoleno).

        E-mail → celé pole (cap 3000); jinak okno před kurzorem. Kontext se
        posílá vždy (pomáhá navázat tón / nezopakovat pozdrav); aby se NEDOSTAL
        do výstupu (bug „vkládá se text z minula"), hlídá to přísně systémový
        prompt v llm.py (text z <pole> nikdy neopakovat).
        """
        field_text = ctx.get("field_text")
        if not (config.field_context() and field_text):
            return None
        if profile == "email":
            return field_text[:3000]
        caret = ctx.get("caret")
        if caret and caret > 0:
            return field_text[:caret][-800:]
        return None

    def _apply_separator(self, text: str, ctx: dict) -> str:
        """Předřadí textu oddělovač: nic / mezera / nový řádek.

        Nový řádek jen když navazuji za dokončenou větou ve víceřádkovém poli —
        tam jde o další záznam pod sebe, ne o pokračování věty.

        POZOR na signaturu: pole se čte ZNOVU, ne z `ctx`. Mezi sběrem kontextu
        a tímhle bodem uběhl přepis i volání Clauda (klidně sekundy) a uživatel
        mohl mezitím v poli sám psát. `ctx` slouží jen jako záloha, když čerstvý
        snímek nic nevrátí — kdyby se rozhodovalo podle něj, vrátí se bug
        „mezera nebo řádek navíc".
        """
        if not (config.auto_space() and not text[:1].isspace()):
            return text
        # `at_line_start` má přednost — rich-text pole (Mail) nevrací koncový
        # konec řádku, takže z textu by to po Enteru vypadalo jako konec slova
        # a vloudil by se oddělovač navíc na začátek nového řádku.
        now = context.focus_snapshot(want_text=True, want_line=True, want_sig=True)
        if now.at_line_start is True:
            return text
        sig = now.sig or ctx.get("field_sig")
        role = sig[0] if sig else None
        fresh = now.text is not None
        sep = context.leading_separator(
            now.text if fresh else ctx.get("field_text"),
            now.caret if fresh else ctx.get("caret"),
            role=role,
            # RDP/AVD se ťuká znak po znaku → „\n" by byl Enter (odeslání).
            allow_newline=not ctx.get("win_target"),
        )
        if sep == "\n":
            print(f"   ↳ nový řádek (pole: {role or 'role neznámá'})")
        return sep + text if sep else text

    def _deliver(self, text: str, ctx: dict) -> str:
        """Vloží text, nebo ho nechá ve schránce → `outcome`.

        Nastavení `_pasting` musí zůstat pod stejným zámkem jako poslední
        kontrola zrušení: mezi nimi je [F5] poslední šance na Escape a jakákoli
        škvíra tam znamená, že Escape spolkne klávesu už rozjetému vkládání.
        """
        with self._lock:
            if self._cancel.is_set():
                raise _Abort("cancelled")
            self._pasting = True

        win_target = bool(ctx.get("win_target"))
        # Vložit, nebo nechat ve schránce? Všechny tři důvody, proč nevkládat,
        # drží pohromadě `context.decide_delivery`.
        deliver, why = context.decide_delivery(
            target_bundle=ctx.get("bundle"),
            field_sig=ctx.get("field_sig"),
            win_target=win_target,
        )
        if not deliver:
            copy_to_clipboard(text)
            print(f"📋 {why} → text ve schránce, nevkládám.")
            # Lístek u ikony („Připraveno k vložení") to řekne líp než
            # systémová notifikace — visí, dokud text nevložíš nebo neklikneš.
            self.awaiting_paste = True
            return "clipboard"

        paste_text(text, windows_target=win_target)
        return "pasted"

    def _process(self) -> None:
        """Pipeline po puštění klávesy: audio → přepis → AI → vložení.

        Zůstává tu jen orchestrace a JEDINÝ `try/except/finally`. Ten se nesmí
        rozdrobit do podmetod: `finally` je jediné místo, kde se zapisuje
        statistika, a jen díky tomu platí, že každý běh zapíše právě jeden
        řádek historie — ať skončí jakkoli.
        """
        # Ptáme se `models.is_ready()` (jen `os.path.exists`), NE příznaku
        # `self.model_missing`: ten se plní jinde a při krátkém ťuknutí do
        # klávesy by se tu četla hodnota z předchozího diktátu.
        if not models.is_ready():
            self._abort_without_model()
            return

        t_start = time.perf_counter()
        audio_secs = 0.0
        speech_secs = 0.0
        raw = ""
        text = ""
        ctx: dict = {}
        outcome = "error"  # přepíše se, jakmile víme, jak to dopadlo
        llm_cost = 0.0  # cena AI úpravy tohoto diktátu (0, když se Claude nevolal)
        try:
            audio, streaming = self._collect_audio()
            audio_secs = len(audio) / 16000.0
            speech_secs = voiced_seconds(audio)  # bez ticha/pauz → tempo řeči
            print(f"🎙️ audio {audio_secs:.1f} s ({len(audio)} vz.) · řeč {speech_secs:.1f} s")
            if audio.size == 0:
                # Prázdné audio = nic se nenahrálo (stream se neotevřel včas /
                # moc krátký stisk). Diagnostika bugu „diktát se ztratil".
                print("⚠️  prázdné audio — nic se nenahrálo (nic k přepisu).")
            if self._cancel.is_set():
                raise _Abort("cancelled")  # zrušeno před přepisem → nula tokenů

            ctx_thread, ctx = self._start_context_gather()
            raw = self._transcribe_audio(audio, streaming)
            text = raw  # od téhle chvíle má i zrušený běh co zapsat do historie
            ctx = self._read_context(ctx_thread, ctx)

            text, llm_cost = self._apply_ai(raw, ctx, audio_secs)
            text = self._apply_separator(text, ctx)
            outcome = self._deliver(text, ctx)
        except _Abort as stop:
            # Řízený konec se známým výsledkem (zrušeno / prázdný přepis) —
            # není to chyba a nesmí spustit notifikaci o pádu.
            outcome = stop.outcome
        except Exception as exc:  # noqa: BLE001
            print(f"❌ chyba v pipeline: {exc}")
            notify("Chyba při vkládání", "Diktát se nepodařilo zpracovat/vložit.")
            outcome = "error"
        finally:
            app_name = ctx.get("app_name")
            domain = ctx.get("domain")
            profile = ctx.get("profile", "generic")
            # Statistiky („kolik jsem ušetřil") — best-effort, nikdy neshodí
            # pipeline. [F6] `outcome` rozliší skutečný diktát od
            # prázdného/zrušeného/spadlého, ať se nepočítá, co nic nevložilo.
            stats.record(
                raw=raw,
                final=text,
                app=app_name,
                domain=domain,
                profile=profile,
                audio_seconds=audio_secs,
                speech_seconds=speech_secs,
                process_seconds=time.perf_counter() - t_start,
                outcome=outcome,
                cost_usd=llm_cost,
            )
            # Jednořádkový souhrn diktátu do logu — kotva pro ladění
            # intermitentních chyb (ztracený/zdvojený diktát, zamrznutí).
            # Bez obsahu (jen délky).
            total = time.perf_counter() - t_start
            print(
                f"🏁 diktát: outcome={outcome} audio={audio_secs:.1f}s řeč={speech_secs:.1f}s "
                f"raw={len(raw)}zn final={len(text)}zn app={app_name} pole={self._focus_field} "
                f"cena=${llm_cost:.4f} celkem={total:.1f}s"
            )
            with self._lock:
                self._pasting = False
                # Reset stavu jen když pořád „patří" tomuhle běhu. Kdyby
                # watchdog mezitím tvrdě resetoval a uživatel začal NOVÝ diktát
                # (RECORDING), nesmíme mu stav přepsat na IDLE.
                if self.state == PROCESSING:
                    self.state = IDLE
                    self._processing_since = 0.0


    def watchdog_check(self) -> None:
        """Odseknutí zaseklého zpracování — volá se z main-thread časovače v trayi.

        Většina zásеků je uvnitř přepisu/volání Clauda (obojí je `_run_cancellable`),
        takže stačí „soft" cancel jako Escape. Kdyby to nepomohlo (zásek jinde),
        po delší době stav tvrdě vrátíme do IDLE, ať appka nezůstane zmrzlá.
        """
        with self._lock:
            if self.state != PROCESSING:
                return
            since = self._processing_since
        stuck = time.monotonic() - since if since > 0 else 0.0
        if stuck < 90:
            return
        if stuck < 120:
            if not self._cancel.is_set():
                print(f"⏱️ zpracování {stuck:.0f}s → soft cancel (odseknutí).")
                self._cancel.set()
                self._cancel_min_until = time.monotonic() + CANCEL_MIN_VISIBLE_S
            return
        print(f"⏱️ zpracování {stuck:.0f}s → TVRDÝ reset do IDLE.")
        notify("Spillway se odseknul", "Zpracování trvalo moc dlouho — vráceno do klidu.")
        # Nastavit i cancel: kdyby zaseklý worker později ožil, jeho kontrola před
        # vložením ho zastaví, aby nevložil text opožděně do (teď už jiného) pole.
        self._cancel.set()
        with self._lock:
            self._pasting = False
            self.state = IDLE
            self._processing_since = 0.0


def main() -> None:
    from . import lifecycle

    _setup_logging()

    # [B5] Single-instance zámek — druhá instance by měla dva event tapy,
    # dva mikrofony a 2× Whisper model. Když už běží, skonči.
    lock = lifecycle.acquire()
    if lock is None:
        print("Spillway už běží (jiná instance). Končím.")
        return

    _log_permission_diagnostics()

    raw_mode = "--raw" in sys.argv
    print(f"Spillway — načítám model (chvíli to trvá)…{'  [raw režim]' if raw_mode else ''}")
    controller = Controller(raw_mode=raw_mode)
    keycode, key_label = config.get_hotkey()

    def _on_tap_failed(msg: str) -> None:
        # POZOR: tohle běží na vlákně tapu JEŠTĚ NEŽ naběhne NSApplication run loop,
        # takže rumps.notification by tady tiše zmizela (to byl původní bug B23).
        # Uživateli to proto ukáže až tray přes `listener.tap_ok` po startu run loopu.
        print(f"❌ {msg}")

    cancel_keycode, cancel_label = config.get_cancel_hotkey()
    listener = HotkeyListener(
        keycode=keycode,
        on_press=controller.on_press,
        on_release=controller.on_release,
        suppress=True,
        on_tap_failed=_on_tap_failed,
        cancel_keycode=cancel_keycode,
        on_cancel_key=controller.request_cancel,
        on_paste_key=controller.clear_awaiting_paste,
    )
    controller.hotkey_listener = listener  # settings okno k němu potřebuje přístup
    listener.start()
    print(
        f"✅ Připraveno. Drž {key_label}, mluv česky, pusť → text se vloží. "
        f"({cancel_label} během zpracování = zrušit)"
    )

    try:
        # [F3] menu bar ikona se stavem (🎙️/🔴/⏳). run() blokuje na main threadu.
        from .tray import SpillwayTray

        print("   Stav najdeš v horní liště (ikona 🎙️). Ukončíš přes menu → Konec.")
        SpillwayTray(controller).run()
    except Exception as exc:  # noqa: BLE001 — fallback bez menu baru
        print(f"(menu bar nedostupný: {exc}) — běžím v terminálu, Ctrl+C = konec.")
        stop = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        while not stop.is_set():
            time.sleep(0.2)
    finally:
        listener.stop()
        controller.recorder.stop()  # uvolnit mikrofon, ať zhasne indikátor
        print("\nKonec.")


if __name__ == "__main__":
    main()
