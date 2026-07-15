"""Lokální přepis řeči přes faster-whisper (large-v3-turbo, CPU).

Model se drží jako singleton v paměti (Spike B: teplé načtení ~1,6 s, RTF ~0,30
na M4). Backend je schválně za jednoduchým rozhraním, aby šel později vyměnit
za mlx-whisper.
"""

from __future__ import annotations

import numpy as np

# Známé halucinace na tichu/krátkém audiu (R10) — zahodit, pokud je to celý výstup.
_HALLUCINATION_MARKERS = (
    "titulky vytvořil",
    "titulky pro",
    "překlad ",
)


class Transcriber:
    def __init__(
        self,
        model_name: str = "large-v3-turbo",
        compute_type: str = "int8",
        language: str = "cs",
    ):
        from faster_whisper import WhisperModel

        self.language = language
        self.model = WhisperModel(model_name, device="cpu", compute_type=compute_type)

    def transcribe(self, audio: np.ndarray) -> str:
        if audio is None or audio.size == 0:
            return ""
        segments, _info = self.model.transcribe(
            audio,
            language=self.language,
            vad_filter=True,
            beam_size=1,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return _drop_hallucination(text)


def _drop_hallucination(text: str) -> str:
    low = text.lower()
    if any(low.startswith(m) or low == m.strip() for m in _HALLUCINATION_MARKERS):
        return ""
    return text
