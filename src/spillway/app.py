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
import threading
import time

from . import config, context
from .audio import Recorder
from .hotkey import HotkeyListener
from .llm import Cleaner
from .paste import paste_text
from .transcribe import Transcriber

IDLE, RECORDING, PROCESSING = "IDLE", "RECORDING", "PROCESSING"


class Controller:
    def __init__(self, *, raw_mode: bool = False) -> None:
        self.recorder = Recorder()
        self.transcriber = Transcriber()  # načte model (chvíli trvá)
        self.state = IDLE
        self._lock = threading.Lock()

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

    def on_press(self) -> None:
        with self._lock:
            if self.state != IDLE:
                # Souběh: předchozí nahrávka se ještě zpracovává → nová se ignoruje
                # (žádná fronta — ať se nevloží text do špatného pole). Zkus po chvíli.
                print(f"⏳ zaneprázdněno ({self.state}) — počkej na dokončení.")
                return
            self.state = RECORDING
        print("🔴 nahrávám… (drž F5)")
        self.recorder.start()

    def on_release(self) -> None:
        with self._lock:
            if self.state != RECORDING:
                return
            self.state = PROCESSING
        audio = self.recorder.stop()
        threading.Thread(target=self._process, args=(audio,), daemon=True).start()

    def _process(self, audio) -> None:  # noqa: ANN001
        try:
            # [F2/F3] kontext: aktivní aplikace, profil formátování, obsah pole.
            app_name, bundle = context.frontmost_app()
            profile = context.app_profile(bundle, app_name)
            field_text, caret = context.focused_field()  # lokální AX čtení

            # Prohlížeč: doména aktivní karty (AppleScript/Automation) může upřesnit profil.
            domain = None
            if config.field_context():
                browser_profile, domain = context.browser_context(bundle)
                if browser_profile:
                    profile = browser_profile
            app_ctx = f"{app_name} ({domain})" if domain else app_name

            secs = len(audio) / 16000.0
            print(f"⏳ přepisuji {secs:.1f} s audia…  ({app_ctx} · profil: {profile})")
            t0 = time.perf_counter()
            raw = self.transcriber.transcribe(audio, language=self.language)
            dt = time.perf_counter() - t0
            if not raw:
                print(f"… prázdný přepis ({dt:.1f} s) — nic nevkládám.")
                return
            print(f"📝 přepis ({dt:.1f} s): {raw!r}")

            text = raw
            if self.cleaner is not None:
                # Existující obsah pole jako kontext (jen když povoleno).
                # E-mail → celé pole (cap 3000); jinak okno před kurzorem.
                before = None
                if config.field_context() and field_text:
                    if profile == "email":
                        before = field_text[:3000]
                    elif caret and caret > 0:
                        before = field_text[:caret][-800:]
                try:
                    text = (
                        self.cleaner.clean(
                            raw,
                            app_name=app_ctx,
                            profile=profile,
                            before_text=before,
                            glossary=self.glossary,
                        )
                        or raw
                    )
                    print(f"✨ upraveno: {text!r}")
                except Exception as exc:  # noqa: BLE001 — [O6] chyba, ale text neztratit
                    print(f"⚠️  AI úprava selhala ({exc}) → vkládám syrový přepis.")
                    text = raw

            # Chytrá mezera: kurzor za nemezerovým znakem (a ne první text v poli).
            if (
                config.auto_space()
                and field_text
                and caret
                and 0 < caret <= len(field_text)
                and not field_text[caret - 1].isspace()
            ):
                text = " " + text

            paste_text(text)
        except Exception as exc:  # noqa: BLE001
            print(f"❌ chyba v pipeline: {exc}")
        finally:
            with self._lock:
                self.state = IDLE


def main() -> None:
    import sys

    raw_mode = "--raw" in sys.argv
    print(f"Spillway — načítám model (chvíli to trvá)…{'  [raw režim]' if raw_mode else ''}")
    controller = Controller(raw_mode=raw_mode)
    keycode, key_label = config.get_hotkey()
    listener = HotkeyListener(
        keycode=keycode,
        on_press=controller.on_press,
        on_release=controller.on_release,
        suppress=True,
    )
    controller.hotkey_listener = listener  # settings okno k němu potřebuje přístup
    listener.start()
    print(f"✅ Připraveno. Drž {key_label}, mluv česky, pusť → text se vloží.")

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
