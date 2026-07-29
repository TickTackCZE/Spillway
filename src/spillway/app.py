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

from . import config, context, stats
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

# [security] Do logu se ve výchozím stavu NEpíše obsah diktátů (log není šifrovaný
# a je v běžném umístění). Plný text jen s SPILLWAY_DEBUG_TEXT=1 na ladění.
import os as _os  # noqa: E402

_LOG_TEXT = _os.environ.get("SPILLWAY_DEBUG_TEXT", "0").lower() not in ("0", "false", "no")


def _preview(text: str) -> str:
    """Bezpečný náhled pro log: buď délka (default), nebo plný text při ladění."""
    return repr(text) if _LOG_TEXT else f"{len(text)} zn."


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
        self.api_key = None if raw_mode else config.get_api_key()
        self.model = config.get_model()
        self.glossary = config.glossary()
        self.language = config.get_language()
        self.cleaner: Cleaner | None = None
        self._build_cleaner()

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

    def clear_awaiting_paste(self) -> None:
        """Lístek „Připraveno k vložení" pryč — uživatel text vložil (⌘V), klikl
        na lístek, nebo začal nový diktát."""
        self.awaiting_paste = False

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
        """[F2] Otevření mikrofonu na worker vlákně (ne na tapu). Když uživatel
        stihne pustit klávesu dřív, než se stream otevře, `stop()` v `_process`
        stejně proběhne až po nás — pořadí drží zámek uvnitř Recorderu."""
        try:
            # Zapamatovat cílovou aplikaci — HUD podle ní pozná odchod jinam.
            # (Tady, ne v `on_press`: to běží na vlákně tapu a musí být triviální.)
            try:
                self.target_bundle = context.frontmost_app()[1]
            except Exception:  # noqa: BLE001
                self.target_bundle = None
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

    def _run_cancellable(self, fn):
        """Spustí `fn` na vlákně a čeká — ale když během běhu přijde Escape,
        přestane čekat a vrátí `_CANCELLED` (vlákno dobíhá na pozadí, výsledek
        se zahodí). Díky tomu je zrušení okamžité i uprostřed přepisu / volání
        Clauda, místo aby se čekalo, až blokující volání doběhne."""
        box: dict = {}

        def _run() -> None:
            try:
                box["r"] = fn()
            except BaseException as exc:  # noqa: BLE001 — přenést na hlavní tok
                box["e"] = exc

        th = threading.Thread(target=_run, daemon=True)
        th.start()
        while th.is_alive():
            if self._cancel.is_set():
                return _CANCELLED
            th.join(0.03)
        if "e" in box:
            raise box["e"]
        return box.get("r")

    def _process(self) -> None:
        t_start = time.perf_counter()
        audio_secs = 0.0
        speech_secs = 0.0  # skutečná řeč bez ticha — pro „tempo řeči"
        raw = ""
        text = ""
        app_name = None
        domain = None
        profile = "generic"
        outcome = "error"  # přepíše se, jakmile víme, jak to dopadlo
        llm_cost = 0.0  # cena AI úpravy tohoto diktátu (0, když se Claude nevolal)
        try:
            # [F2] Počkat, až doběhne otevírání mikrofonu — jinak by `stop()`
            # mohl proběhnout dřív než `start()` a stream by zůstal viset otevřený.
            starter = getattr(self, "_start_thread", None)
            if starter is not None:
                starter.join(timeout=5.0)
            audio = self.recorder.stop()  # [B9] těžké volání až tady, na workeru
            # Počkat, až streamovací vlákno dokončí poslední segment — tím doběhne
            # ještě před dalším diktátem a nezapíše do jeho (resetnutého) seznamu.
            stream_th = getattr(self, "_stream_thread", None)
            if stream_th is not None:
                stream_th.join(timeout=3.0)
            audio_secs = len(audio) / 16000.0
            speech_secs = voiced_seconds(audio)  # bez ticha/pauz → tempo řeči
            print(f"🎙️ audio {audio_secs:.1f} s ({len(audio)} vz.) · řeč {speech_secs:.1f} s")
            if audio.size == 0:
                # Prázdné audio = nic se nenahrálo (stream se neotevřel včas / moc
                # krátký stisk). Diagnostika bugu „diktát se ztratil".
                print("⚠️  prázdné audio — nic se nenahrálo (nic k přepisu).")
            if self._cancel.is_set():
                outcome = "cancelled"
                return  # zrušeno ještě před přepisem → nula tokenů, nula práce
            # [F2/F3] kontext: aktivní aplikace, profil formátování, obsah pole.
            # Sbírá se PARALELNĚ s přepisem — nepotřebuje audio a `browser_context`
            # čeká na `osascript` (až 2 s). Dřív to běželo před přepisem, takže se
            # ta doba čistě přičítala; teď se schová za Whisper.
            ctx: dict = {}

            def _gather_context() -> None:
                try:
                    a_name, a_bundle = context.frontmost_app()
                    ctx["app_name"], ctx["bundle"] = a_name, a_bundle
                    ctx["profile"] = context.app_profile(a_bundle, a_name)
                    ctx["win_target"] = context.is_windows_target(a_bundle, a_name)
                    ctx["field_text"], ctx["caret"] = context.focused_field()
                    ctx["at_line_start"] = context.caret_at_line_start()
                    # Otisk cílového pole — před vložením ověříme, že jsme pořád
                    # v něm (jinak text jen do schránky, viz níž).
                    ctx["field_sig"] = context.focused_field_signature()
                    if config.field_context():
                        b_profile, b_domain = context.browser_context(a_bundle)
                        ctx["domain"] = b_domain
                        if b_profile:
                            ctx["profile"] = b_profile
                except Exception as exc:  # noqa: BLE001 — bez kontextu jedeme dál
                    ctx["error"] = exc

            ctx_thread = threading.Thread(target=_gather_context, daemon=True)
            ctx_thread.start()

            secs = len(audio) / 16000.0
            if not self.transcriber.is_loaded:
                print("💤→🔄 model byl uvolněný z paměti, znovu se načítá…")
            t0 = time.perf_counter()
            # Streaming: segmenty (řez v tichu) se přepsaly už během mluvení —
            # po puštění dopřepíšeme jen poslední úsek a zřetězíme. Když streaming
            # nic nesegmentoval (krátký diktát bez pauz) → committed=0 → přepíše se
            # celé audio (dávka, jako dřív). Slovník (hotwords) jde jen do dávky.
            if stream_th is not None:  # streaming byl aktivní (joinuto po stop())
                # Číst pod zámkem — smyčka zapisuje text a pozici atomicky, takže
                # jen tak dostaneme dvojici, která k sobě patří.
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
                    raw = ""
                    outcome = "cancelled"
                    return
                parts = segments + ([tail_text] if tail_text else [])
                raw = " ".join(p for p in parts if p).strip()
            else:
                print(f"⏳ přepisuji {secs:.1f} s audia…")
                # Cancellable: Escape během přepisu ho okamžitě opustí.
                raw = self._run_cancellable(lambda: self.transcriber.transcribe(
                    audio,
                    language=self.language,
                    hotwords=self.glossary if config.whisper_hotwords() else None,
                ))
                if raw is _CANCELLED:
                    raw = ""  # ať se sentinel nedostane do stats.record (TypeError)
                    outcome = "cancelled"
                    return
            dt = time.perf_counter() - t0
            if not raw:
                print(f"… prázdný přepis ({dt:.1f} s) — nic nevkládám.")
                outcome = "empty"
                return
            print(f"📝 přepis ({dt:.1f} s): {_preview(raw)}")

            # Kontext už se mezitím posbíral souběžně s přepisem.
            ctx_thread.join(timeout=3.0)
            app_name = ctx.get("app_name")
            bundle = ctx.get("bundle")
            profile = ctx.get("profile", "generic")
            win_target = bool(ctx.get("win_target"))
            field_text, caret = ctx.get("field_text"), ctx.get("caret")
            domain = ctx.get("domain")
            app_ctx = f"{app_name} ({domain})" if domain else app_name
            win_note = " · Windows (Ctrl+V)" if win_target else ""
            print(f"   ({app_ctx} · profil: {profile}{win_note})")

            text = raw
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
            elif skip_llm:
                text = basic_cleanup(raw)
                print(f"⚡ krátký diktát ({audio_secs:.1f} s < {min_s:g} s) → bez AI: {_preview(text)}")
            elif self.cleaner is not None:
                # Existující obsah pole jako kontext (jen když povoleno).
                # E-mail → celé pole (cap 3000); jinak okno před kurzorem.
                # Kontext se posílá vždy (pomáhá navázat tón/nezopakovat pozdrav);
                # aby se NEDOSTAL do výstupu (bug „vkládá se text z minula"), hlídá
                # to přísně systémový prompt v llm.py (text z <pole> nikdy neopakovat).
                before = None
                if config.field_context() and field_text:
                    if profile == "email":
                        before = field_text[:3000]
                    elif caret and caret > 0:
                        before = field_text[:caret][-800:]
                if before:
                    print(f"   ↳ kontext pole: {len(before)} zn.")
                try:
                    # Cancellable: Escape během volání Clauda ho okamžitě opustí
                    # (odpověď dobíhá na pozadí a zahodí se). Nejdelší krok pipeline.
                    result = self._run_cancellable(lambda: self.cleaner.clean(
                        raw,
                        app_name=app_ctx,
                        profile=profile,
                        before_text=before,
                        glossary=self.glossary,
                    ))
                    if result is _CANCELLED:
                        outcome = "cancelled"
                        return
                    text = result or raw
                    print(f"✨ upraveno: {_preview(text)}")
                except Exception as exc:  # noqa: BLE001 — [O6] chyba, ale text neztratit
                    print(f"⚠️  AI úprava selhala ({exc}) → vkládám syrový přepis.")
                    notify("AI úprava selhala", "Vložen syrový přepis. Zkontroluj API klíč / kredit.")
                    text = raw
                # Cenu čti hned po volání (na cleaneru se přepíše dalším diktátem) —
                # i po chybě: když volání provolalo tokeny a spadlo až na uříznuté
                # odpovědi (max_tokens), náklad reálně vznikl a musí se započítat.
                llm_cost = getattr(self.cleaner, "last_cost_usd", 0.0) or 0.0

            # Chytrý oddělovač: nic / mezera / nový řádek. Nový řádek jen když
            # navazuji za dokončenou větou ve víceřádkovém poli — tam jde o další
            # záznam pod sebe, ne o pokračování věty.
            # `at_line_start` má přednost — rich-text pole (Mail) nevrací koncový
            # konec řádku, takže z textu by to po Enteru vypadalo jako konec slova
            # a vloudil by se oddělovač navíc na začátek nového řádku.
            if config.auto_space() and not text[:1].isspace():
                at_line_start = context.caret_at_line_start()
                if at_line_start is not True:
                    sig = ctx.get("field_sig")
                    role = sig[0] if sig else None
                    sep = context.leading_separator(
                        field_text, caret,
                        role=role,
                        # RDP/AVD se ťuká znak po znaku → „\n" by byl Enter (odeslání).
                        allow_newline=not win_target,
                    )
                    if sep:
                        text = sep + text
                    if sep == "\n":
                        print(f"   ↳ nový řádek (pole: {role or 'role neznámá'})")

            # [F5] Poslední šance zrušit. Za tímhle bodem už se vkládá a rušit
            # nejde — `_pasting` zajistí, že Escape projde normálně dál a diktát
            # se nezapíše jako zrušený.
            with self._lock:
                if self._cancel.is_set():
                    outcome = "cancelled"
                    return
                self._pasting = True

            # Přepnul uživatel mezitím jinam? Pak text NEVKLÁDAT — spadl by do
            # cizího pole (chat, terminál). Nechat ho ve schránce a říct o tom.
            _, now_bundle = context.frontmost_app()
            if bundle and now_bundle and now_bundle != bundle:
                copy_to_clipboard(text)
                print(f"📋 fokus je jinde ({now_bundle}) → text ve schránce, nevkládám.")
                # Lístek u ikony („Připraveno k vložení") to řekne líp než
                # systémová notifikace — visí, dokud text nevložíš nebo neklikneš.
                self.awaiting_paste = True
                outcome = "clipboard"
                return

            # Zůstal jsi ve stejné APLIKACI, ale odešel z POLE (klik jinam, zavřené
            # okno)? Taky nevkládat — jinak text spadne do cizího pole ve stejné
            # appce. `same_field` vrací None, když otisk nejde získat (web/Electron)
            # — tam se chováme jako dřív a vložíme (jinak by to hlásilo pořád).
            if context.same_field(ctx.get("field_sig"), context.focused_field_signature()) is False:
                copy_to_clipboard(text)
                print("📋 jsi v jiném poli → text ve schránce, nevkládám.")
                self.awaiting_paste = True
                outcome = "clipboard"
                return

            paste_text(text, windows_target=win_target)
            outcome = "pasted"
        except Exception as exc:  # noqa: BLE001
            print(f"❌ chyba v pipeline: {exc}")
            notify("Chyba při vkládání", "Diktát se nepodařilo zpracovat/vložit.")
            outcome = "error"
        finally:
            # Statistiky („kolik jsem ušetřil") — best-effort, nikdy neshodí pipeline.
            # [F6] `outcome` rozliší skutečný diktát od prázdného/zrušeného/pádu,
            # ať se do statistik nepočítá, co nic nevložilo.
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
            # Jednořádkový souhrn diktátu do logu — kotva pro ladění intermitentních
            # chyb (ztracený/zdvojený diktát, zamrznutí). Bez obsahu (jen délky).
            total = time.perf_counter() - t_start
            print(
                f"🏁 diktát: outcome={outcome} audio={audio_secs:.1f}s řeč={speech_secs:.1f}s "
                f"raw={len(raw)}zn final={len(text)}zn app={app_name} "
                f"cena=${llm_cost:.4f} celkem={total:.1f}s"
            )
            with self._lock:
                self._pasting = False
                # Reset stavu jen když pořád „patří" tomuhle běhu. Kdyby watchdog
                # mezitím tvrdě resetoval a uživatel začal NOVÝ diktát (RECORDING),
                # nesmíme mu stav přepsat na IDLE.
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
