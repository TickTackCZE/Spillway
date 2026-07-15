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

        # [F2] AI úprava přes Claude — jen pokud je klíč a není raw režim.
        self.cleaner: Cleaner | None = None
        if not raw_mode:
            api_key = config.get_api_key()
            if api_key:
                model = config.get_model()
                self.cleaner = Cleaner(api_key, model=model)
                print(f"🤖 AI úprava zapnuta ({model}).")
            else:
                print("ℹ️  Bez API klíče → raw režim. Klíč nastav: uv run python set_api_key.py")

    def on_press(self) -> None:
        with self._lock:
            if self.state != IDLE:
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

            secs = len(audio) / 16000.0
            print(f"⏳ přepisuji {secs:.1f} s audia…  ({app_name} · profil: {profile})")
            t0 = time.perf_counter()
            raw = self.transcriber.transcribe(audio)
            dt = time.perf_counter() - t0
            if not raw:
                print(f"… prázdný přepis ({dt:.1f} s) — nic nevkládám.")
                return
            print(f"📝 přepis ({dt:.1f} s): {raw!r}")

            text = raw
            if self.cleaner is not None:
                # Existující text pole před kurzorem jako kontext (jen když povoleno).
                before = None
                if config.field_context() and field_text and caret and caret > 0:
                    before = field_text[:caret][-600:]
                try:
                    text = (
                        self.cleaner.clean(
                            raw, app_name=app_name, profile=profile, before_text=before
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
    listener = HotkeyListener(
        on_press=controller.on_press,
        on_release=controller.on_release,
        suppress=True,
    )
    listener.start()
    print("✅ Připraveno. Drž F5, mluv česky, pusť → text se vloží.")

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
