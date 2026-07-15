"""Nahrávání mikrofonu do paměti (16 kHz mono float32).

Audio nikdy neopouští RAM ani se neukládá na disk (privacy). Ve Spike B ověřeno,
že faster-whisper přijímá numpy float32 pole přímo, bez dekódování souboru.
"""

from __future__ import annotations

import gc
import os
import threading

import numpy as np
import sounddevice as sd

_DEBUG = os.environ.get("SPILLWAY_DEBUG_AUDIO", "0").lower() not in ("0", "false", "no")

SAMPLE_RATE = 16000
MAX_SECONDS_DEFAULT = 120


class Recorder:
    """Push-to-talk nahrávání. `start()` otevře stream, `stop()` vrátí audio."""

    def __init__(self, sample_rate: int = SAMPLE_RATE, max_seconds: int = MAX_SECONDS_DEFAULT):
        self.sample_rate = sample_rate
        self.max_frames = max_seconds * sample_rate
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._total = 0

    def _callback(self, indata, frames, time_info, status):  # noqa: ANN001
        # Voláno na audio vlákně — drž triviální.
        with self._lock:
            if self._total < self.max_frames:
                self._frames.append(indata.copy())
                self._total += frames

    def start(self) -> None:
        with self._lock:
            self._frames = []
            self._total = 0
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        """Zastaví nahrávání, uvolní mikrofon a vrátí audio jako 1-D float32."""
        stream = self._stream
        self._stream = None
        if stream is not None:
            for name, op in (("stop", stream.stop), ("close", stream.close)):
                try:
                    op()
                    if _DEBUG:
                        print(f"[audio] {name}() OK")
                except Exception as exc:  # noqa: BLE001
                    if _DEBUG:
                        print(f"[audio] {name}() selhal: {exc}")
            # close() na macOS někdy neuvolní CoreAudio zařízení → oranžový
            # indikátor zůstane svítit. Uvolníme referenci, GC a restart PortAudia.
            del stream
            gc.collect()
            try:
                sd._terminate()
                sd._initialize()
                if _DEBUG:
                    print("[audio] PortAudio restart OK")
            except Exception as exc:  # noqa: BLE001
                if _DEBUG:
                    print(f"[audio] PortAudio restart selhal: {exc}")
        with self._lock:
            if not self._frames:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._frames, axis=0).reshape(-1)
