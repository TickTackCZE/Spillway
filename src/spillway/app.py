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

from .audio import Recorder
from .hotkey import HotkeyListener
from .paste import paste_text
from .transcribe import Transcriber

IDLE, RECORDING, PROCESSING = "IDLE", "RECORDING", "PROCESSING"


class Controller:
    def __init__(self) -> None:
        self.recorder = Recorder()
        self.transcriber = Transcriber()  # načte model (chvíli trvá)
        self.state = IDLE
        self._lock = threading.Lock()

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
            secs = len(audio) / 16000.0
            print(f"⏳ přepisuji {secs:.1f} s audia…")
            t0 = time.perf_counter()
            text = self.transcriber.transcribe(audio)
            dt = time.perf_counter() - t0
            if text:
                print(f"✅ ({dt:.1f} s): {text!r}")
                paste_text(text)
            else:
                print(f"… prázdný přepis ({dt:.1f} s) — nic nevkládám.")
        except Exception as exc:  # noqa: BLE001
            print(f"❌ chyba v pipeline: {exc}")
        finally:
            with self._lock:
                self.state = IDLE


def main() -> None:
    print("Spillway F1 — načítám model (chvíli to trvá)…")
    controller = Controller()
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
        print("\nKonec.")


if __name__ == "__main__":
    main()
