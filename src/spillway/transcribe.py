"""Lokální přepis řeči přes faster-whisper (large-v3-turbo, CPU).

Model se drží jako singleton v paměti (Spike B: teplé načtení ~1,6 s, RTF ~0,30
na M4). Backend je schválně za jednoduchým rozhraním, aby šel později vyměnit
za mlx-whisper.
"""

from __future__ import annotations

import gc
import os
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

def _beam_size() -> int:
    """Doporučený default faster-whisperu je 5 (dřív tu byla greedy 1 = méně
    přesné). Přebitelné přes SPILLWAY_BEAM_SIZE, kdyby latence vadila víc."""
    try:
        return max(1, int(os.environ.get("SPILLWAY_BEAM_SIZE", "5")))
    except (TypeError, ValueError):
        return 5


BEAM_SIZE = _beam_size()


def _hotwords_str(terms: list[str] | None) -> str | None:
    """Slovník → jeden řetězec pro faster-whisper `hotwords` (biasuje dekodér).
    Prázdný slovník → None (žádný bias)."""
    if not terms:
        return None
    cleaned = [t.strip() for t in terms if t and t.strip()]
    return ", ".join(cleaned) if cleaned else None


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

    def preload(self) -> None:
        """Načte model dopředu. Volá se při STISKU klávesy — než domluvíš, model
        je připravený, takže se reload (~1,6 s po auto-unloadu) schová do doby,
        kdy stejně mluvíš, místo aby se čekalo až po puštění klávesy."""
        with self._lock:
            if self._model is None:
                self._load_model()

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

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        hotwords: list[str] | None = None,
    ) -> str:
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
            # beam_size=5 je doporučený default faster-whisperu (dřív tu byla 1 =
            # greedy). Přesnější dekódování za cenu trochy latence — na M4 se to
            # v praxi vejde do desítek ms navíc (změřeno).
            beam_size=BEAM_SIZE,
            # [F-c] Uživatelský slovník biasuje PŘEPIS ke správnému znění termínů
            # („pull request", názvy projektů) — dřív to musel dohánět až Claude.
            hotwords=_hotwords_str(hotwords),
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
