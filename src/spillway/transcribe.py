"""Lokální přepis řeči přes faster-whisper (large-v3-turbo, CPU).

Model se drží jako singleton v paměti (Spike B: teplé načtení ~1,6 s, RTF ~0,30
na M4). Backend je schválně za jednoduchým rozhraním, aby šel později vyměnit
za mlx-whisper.
"""

from __future__ import annotations

import gc
import threading
import time

import numpy as np

# Známé halucinace na tichu/krátkém audiu (R10). Pozor: [B8] filtr smí zahodit
# jen KRÁTKÝ výstup (jinak zahodí legitimní diktát začínající „Titulky…"/„Překlad…").
_HALLUCINATION_MARKERS = (
    "titulky vytvořil",
    "titulky pro",
    "překlad titulků",
    "www.",
    ".cz",
)
_HALLUCINATION_MAX_LEN = 45


class Transcriber:
    """[R5] Model (~1,5–2 GB RAM) jde uvolnit po nečinnosti a znovu lazy-load
    při dalším diktátu (teplé znovunačtení ze souborové cache ~1,6 s — Spike B)."""

    def __init__(
        self,
        model_name: str = "large-v3-turbo",
        compute_type: str = "int8",
        language: str = "cs",
    ):
        self.model_name = model_name
        self.compute_type = compute_type
        self.language = language
        self._model = None
        self._lock = threading.Lock()
        self._last_used = time.monotonic()
        self._load_model()  # při startu appky natvrdo (ať je první diktát rychlý)

    def _load_model(self) -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(self.model_name, device="cpu", compute_type=self.compute_type)

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def unload_if_idle(self, idle_seconds: float) -> bool:
        """Uvolní model, pokud je nečinný déle než `idle_seconds`. Vrací True,
        když k uvolnění došlo. `idle_seconds <= 0` vypíná auto-unload."""
        if idle_seconds <= 0:
            return False
        with self._lock:
            if self._model is None:
                return False
            if time.monotonic() - self._last_used < idle_seconds:
                return False
            self._model = None
        gc.collect()
        return True

    def transcribe(self, audio: np.ndarray, language: str | None = None) -> str:
        if audio is None or audio.size == 0:
            return ""
        with self._lock:
            if self._model is None:
                self._load_model()
            self._last_used = time.monotonic()
            model = self._model
        segments, _info = model.transcribe(
            audio,
            language=language or self.language,
            vad_filter=True,
            beam_size=1,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        with self._lock:
            self._last_used = time.monotonic()  # dokončení, ne jen start
        return _drop_hallucination(text)


def _drop_hallucination(text: str) -> str:
    # [B8] Zahoď jen krátký výstup, který je celý halucinační marker — u delšího
    # diktátu (i když náhodou začíná „Překlad…") text ponech, ať se neztratí.
    if len(text) > _HALLUCINATION_MAX_LEN:
        return text
    low = text.lower()
    if any(m in low for m in _HALLUCINATION_MARKERS):
        return ""
    return text
