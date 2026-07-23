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
from .transcribe import Transcriber

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
        # [F2] Vlákno, které otevírá mikrofon; `_process` na něj počká.
        self._start_thread: threading.Thread | None = None

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
        self._cancel.set()
        self._cancel_min_until = time.monotonic() + CANCEL_MIN_VISIBLE_S
        print("🚫 ruším… (nic se nevloží)")
        if take_over:
            # Vlákno tapu drž triviální — těžké `recorder.stop()` udělá `_process`,
            # který rovnou uvidí `_cancel`, uvolní mikrofon a skončí na IDLE.
            self._cancel_watchdog()
            threading.Thread(target=self._process, daemon=True).start()
        return True

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
        self._cancel.clear()  # nový diktát → zahodit staré zrušení
        self._cancel_min_until = 0.0  # ať „Ruším" nepřebíjí nové „Nahrávám"
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
        # [B7] Watchdog: kdyby se ztratil key-up (spánek, lock, Secure Input),
        # po max_seconds nahrávání vynuceně ukončíme, ať appka nezůstane v RECORDING.
        self._arm_watchdog()

    def _start_recording(self) -> None:
        """[F2] Otevření mikrofonu na worker vlákně (ne na tapu). Když uživatel
        stihne pustit klávesu dřív, než se stream otevře, `stop()` v `_process`
        stejně proběhne až po nás — pořadí drží zámek uvnitř Recorderu."""
        try:
            self.recorder.start()
        except Exception as exc:  # noqa: BLE001 — [O6] viditelná chyba, ne tichý pád
            print(f"❌ mikrofon se nepodařilo spustit: {exc}")
            notify("Mikrofon nedostupný", "Nahrávání se nepodařilo spustit.")
            with self._lock:
                self.state = IDLE
            self._cancel_watchdog()

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
        raw = ""
        text = ""
        app_name = None
        domain = None
        profile = "generic"
        outcome = "error"  # přepíše se, jakmile víme, jak to dopadlo
        try:
            # [F2] Počkat, až doběhne otevírání mikrofonu — jinak by `stop()`
            # mohl proběhnout dřív než `start()` a stream by zůstal viset otevřený.
            starter = getattr(self, "_start_thread", None)
            if starter is not None:
                starter.join(timeout=5.0)
            audio = self.recorder.stop()  # [B9] těžké volání až tady, na workeru
            audio_secs = len(audio) / 16000.0
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
            print(f"⏳ přepisuji {secs:.1f} s audia…")
            t0 = time.perf_counter()
            # Slovník do Whisperu (hotwords) jen když si o to uživatel řekne —
            # výchozí VYPNUTO, protože bias vkládá termíny, které nezazněly
            # (viz config.whisper_hotwords). Zkomoleniny opraví bezpečně Claude.
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
            if skip_llm:
                text = basic_cleanup(raw)
                print(f"⚡ krátký diktát ({audio_secs:.1f} s < {min_s:g} s) → bez AI: {_preview(text)}")
            elif self.cleaner is not None:
                # Existující obsah pole jako kontext (jen když povoleno).
                # E-mail → celé pole (cap 3000); jinak okno před kurzorem.
                before = None
                if config.field_context() and field_text:
                    if profile == "email":
                        before = field_text[:3000]
                    elif caret and caret > 0:
                        before = field_text[:caret][-800:]
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

            # Chytrá mezera: jen když kurzor stojí těsně za nemezerovým znakem.
            # `at_line_start` má přednost — rich-text pole (Mail) nevrací koncový
            # konec řádku, takže z textu by to po Enteru vypadalo jako konec slova
            # a vloudila by se mezera navíc na začátek nového řádku.
            if config.auto_space() and not text[:1].isspace():
                at_line_start = context.caret_at_line_start()
                if at_line_start is not True and context.needs_leading_space(
                    field_text, caret
                ):
                    text = " " + text

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
                notify("Text je ve schránce", "Přepnul jsi jinam — vlož ho ⌘V, kam chceš.")
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
                process_seconds=time.perf_counter() - t_start,
                outcome=outcome,
            )
            with self._lock:
                self._pasting = False
                self.state = IDLE


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
