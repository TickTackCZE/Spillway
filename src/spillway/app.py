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
from .smart_spacing import leading_space_needed
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
            # [F2] kontext = název aktivní aplikace (zachytit před vložením).
            app_name, _bundle = context.frontmost_app()
            secs = len(audio) / 16000.0
            print(f"⏳ přepisuji {secs:.1f} s audia…  (aktivní: {app_name})")
            t0 = time.perf_counter()
            raw = self.transcriber.transcribe(audio)
            dt = time.perf_counter() - t0
            if not raw:
                print(f"… prázdný přepis ({dt:.1f} s) — nic nevkládám.")
                return
            print(f"📝 přepis ({dt:.1f} s): {raw!r}")

            text = raw
            if self.cleaner is not None:
                try:
                    text = self.cleaner.clean(raw, app_name=app_name) or raw
                    print(f"✨ upraveno: {text!r}")
                except Exception as exc:  # noqa: BLE001 — [O6] chyba, ale text neztratit
                    print(f"⚠️  AI úprava selhala ({exc}) → vkládám syrový přepis.")
                    text = raw

            # Chytrá mezera: když kurzor stojí za nemezerovým znakem, oddělit.
            if config.auto_space() and leading_space_needed():
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
    print("✅ Připraveno. Drž F5, mluv česky, pusť → text se vloží. Ctrl+C = konec.")

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        while not stop.is_set():
            time.sleep(0.2)
    finally:
        listener.stop()
        controller.recorder.stop()  # uvolnit mikrofon, ať zhasne indikátor
        print("\nKonec.")


if __name__ == "__main__":
    main()
