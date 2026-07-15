"""
Spike B — benchmark faster-whisper na Apple Silicon (riziko R2).

Měří na daném audiu: čas načtení modelu, čas přepisu, real-time factor (RTF),
špičkovou paměť a vypíše přepis (kvůli code-switching CZ+EN kvalitě).

POZOR: ctranslate2 na Apple Silicon běží CPU-only (nemá Metal). Tenhle spike
zjišťuje, jestli je to na M4 dost rychlé. WER kvalita se syntetickým (say) audiem
NENÍ reprezentativní — pro reálné WER je potřeba skutečná nahrávka (viz plán).

Audio se načítá přes stdlib `wave` (16 kHz mono PCM16) → numpy, aby nebyl potřeba
PyAV/ffmpeg. Model se drží v paměti (v ostré app singleton).

Použití:
    uv run python spikes/spike_b_whisper.py /cesta/sample.wav [model] [compute_type]
    # model default: large-v3-turbo   compute_type default: int8
"""

import resource
import sys
import time
import wave

import numpy as np


def load_wav_16k_mono(path: str) -> np.ndarray:
    """Načte 16 kHz mono PCM16 wav do float32 [-1, 1]."""
    with wave.open(path, "rb") as wf:
        assert wf.getframerate() == 16000, f"čekám 16 kHz, mám {wf.getframerate()}"
        assert wf.getnchannels() == 1, "čekám mono"
        assert wf.getsampwidth() == 2, "čekám PCM16"
        frames = wf.readframes(wf.getnframes())
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return audio


def peak_rss_mb() -> float:
    # macOS: ru_maxrss je v bajtech (na Linuxu v kB).
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)


def main() -> None:
    if len(sys.argv) < 2:
        print("Použití: spike_b_whisper.py <sample.wav> [model] [compute_type]")
        return
    audio_path = sys.argv[1]
    model_name = sys.argv[2] if len(sys.argv) > 2 else "large-v3-turbo"
    compute_type = sys.argv[3] if len(sys.argv) > 3 else "int8"

    from faster_whisper import WhisperModel

    audio = load_wav_16k_mono(audio_path)
    duration_s = len(audio) / 16000.0

    print("── Spike B: faster-whisper benchmark ──────────")
    print(f"Audio:        {audio_path}  ({duration_s:.1f} s)")
    print(f"Model:        {model_name}  (compute_type={compute_type}, CPU)")
    print("Načítám model (první běh stahuje ~1,5 GB)…", flush=True)

    t0 = time.perf_counter()
    model = WhisperModel(model_name, device="cpu", compute_type=compute_type)
    load_s = time.perf_counter() - t0
    print(f"  → načteno za {load_s:.1f} s")

    print("Přepisuji…", flush=True)
    t1 = time.perf_counter()
    segments, info = model.transcribe(
        audio,
        language="cs",
        vad_filter=True,
        beam_size=1,
    )
    text = " ".join(seg.text.strip() for seg in segments)
    transcribe_s = time.perf_counter() - t1

    rtf = transcribe_s / duration_s if duration_s else float("nan")
    print("\n── Výsledky ───────────────────────────────────")
    print(f"Načtení modelu:   {load_s:6.1f} s")
    print(f"Přepis:           {transcribe_s:6.1f} s pro {duration_s:.1f} s audia")
    print(f"Real-time factor: {rtf:6.2f}  (< 1.0 = rychlejší než realtime)")
    print(f"Špičková RAM:     {peak_rss_mb():6.0f} MB")
    print(f"\nPřepis:\n{text}\n")


if __name__ == "__main__":
    main()
