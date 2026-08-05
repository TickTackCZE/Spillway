"""Nahrávání mikrofonu do paměti (16 kHz mono float32).

Audio nikdy neopouští RAM ani se neukládá na disk (privacy). Ve Spike B ověřeno,
že faster-whisper přijímá numpy float32 pole přímo, bez dekódování souboru.
"""

from __future__ import annotations

import gc
import threading

import numpy as np
import sounddevice as sd

from . import diag

SAMPLE_RATE = 16000
MAX_SECONDS_DEFAULT = 300  # 5 min — pojistka proti ztracenému key-up; 5 min ≈ 19 MB RAM

# Rozsah pro živý ukazatel hlasitosti v liště. Ticho v pokoji vyjde kolem -60 dB,
# běžná řeč do mikrofonu v notebooku -35 až -15 dB. Spodní hranici držíme nad
# šumem, ať ikona v tichu opravdu stojí, horní pod klipem, ať se dá „vyjet nahoru".
_LEVEL_DB_MIN = -48.0
_LEVEL_DB_MAX = -14.0


def _rms_to_level(rms: float) -> float:
    """RMS (0..1) → hlasitost 0..1 v dB škále, ořezaná do rozsahu."""
    if rms <= 1e-7:
        return 0.0
    db = 20.0 * np.log10(rms)
    return float(min(1.0, max(0.0, (db - _LEVEL_DB_MIN) / (_LEVEL_DB_MAX - _LEVEL_DB_MIN))))


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

    def level(self, window_s: float = 0.12) -> float:
        """Hlasitost posledního krátkého úseku jako 0..1 — pro živý ukazatel v liště.

        Levné: sáhne jen na konec bufferu (~2 tisíce vzorků), nikdy nezřetězí celou
        nahrávku jako `snapshot()`. Hlasitost se počítá jako RMS a převádí na dB,
        protože sluch (a tím i očekávaný pohyb sloupců) je logaritmický — lineární
        RMS by u běžné řeči skoro nevyjel z nuly.
        """
        need = max(1, int(self.sample_rate * window_s))
        with self._lock:
            if not self._frames:
                return 0.0
            tail, got = [], 0
            for arr in reversed(self._frames):
                tail.append(arr)
                got += arr.shape[0]
                if got >= need:
                    break
        buf = np.concatenate(list(reversed(tail)), axis=0).reshape(-1)[-need:]
        if buf.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(np.square(buf, dtype=np.float64))))
        return _rms_to_level(rms)

    def snapshot(self) -> np.ndarray:
        """Zatím nahrané audio jako 1-D float32, BEZ zastavení streamu (pro
        streaming přepis během mluvení). Levné — jen zřetězení dosavadních rámců."""
        with self._lock:
            if not self._frames:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._frames, axis=0).reshape(-1)

    def stop(self) -> np.ndarray:
        """Zastaví nahrávání, uvolní mikrofon a vrátí audio jako 1-D float32."""
        # Převzetí streamu pod zámkem: `stop()` volá jak pipeline, tak ukončení
        # aplikace. Bez zámku můžou obě větve přečíst tentýž stream dřív, než
        # ho první vynuluje, a zavřít nativní CoreAudio stream dvakrát.
        with self._lock:
            stream = self._stream
            self._stream = None
        if stream is not None:
            for name, op in (("stop", stream.stop), ("close", stream.close)):
                try:
                    op()
                    diag.log("audio", f"{name}() OK")
                except Exception as exc:  # noqa: BLE001
                    diag.log("audio", f"{name}() selhal: {exc}")
            # close() na macOS někdy neuvolní CoreAudio zařízení → oranžový
            # indikátor zůstane svítit. Uvolníme referenci, GC a restart PortAudia.
            del stream
            gc.collect()
            try:
                sd._terminate()
                sd._initialize()
                diag.log("audio", "PortAudio restart OK")
            except Exception as exc:  # noqa: BLE001
                diag.log("audio", f"PortAudio restart selhal: {exc}")
        with self._lock:
            if not self._frames:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._frames, axis=0).reshape(-1)
