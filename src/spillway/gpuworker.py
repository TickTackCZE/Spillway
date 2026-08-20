"""Kód, který běží v PODPROCESU pro přepis (mlx na GPU / faster-whisper na CPU).

Proč vlastní proces, a ne vlákno jako dřív: `mlx_whisper.transcribe()` se občas
zasekne uvnitř nativního volání (známý, neopravený upstream bug
ml-explore/mlx-examples#1373 — bez jakéhokoli API na zrušení). Zaseklé VLÁKNO
nejde z Pythonu nikdy ukončit, jen opustit — a pak navždy drží GPU paměť
(na Apple Silicon sdílenou se systémovou RAM) a blokuje každý další přepis,
protože mlx váže GPU stream na vlákno. Zaseklý PROCES se zabít dá: změřeno, že
SIGKILL vrátí celou paměť (~1 GB) za 43 ms.

**Tenhle modul nesmí importovat zbytek Spillway** (`app`, `audio`, rumps,
AppKit, keyring, sounddevice). Podproces se startuje přes „spawn", takže každý
import se v něm provede znovu — a `sounddevice` volá `Pa_Initialize()` už při
importu, čímž by si každý worker zbytečně otevřel klienta CoreAudia a pak ho
při zabití držel. Kvůli témuž se sem NEIMPORTUJE `faster_whisper` na úrovni
modulu: přitáhne torch (+199 MB), a to i když se jede na mlx.

Přes hranici procesu chodí jen prosté typy — numpy pole dovnitř, `str` ven.
Nikdy `mx.array`: podle mlx#2457 (od správce mlx) to na Metalu končí nečistě.
"""

from __future__ import annotations

import multiprocessing
import os


def _redirect_output_to_log() -> None:
    """Výstup podprocesu → tentýž log jako appka, na úrovni file descriptorů.

    Musí to být PRVNÍ věc v modulu, ještě před importem mlx: kdyby se import
    nepodařil (chybějící Metal shadery v zabalené .app), traceback jde na fd 2 —
    a ten pod LaunchAgentem míří do /dev/null. Bez tohohle by po pádu workeru
    nezůstala ani řádka a appka by jen mlčky hlásila „nepovedlo se".

    `dup2` (ne `sys.stdout = ...`): přesměrovat Pythonní objekt nestačí, nativní
    knihovna píše rovnou do fd. Rotace logu appce nevadí — dělá se jen jednou
    při startu (`app._setup_logging`), tedy dřív, než vůbec nějaký worker vznikne.
    """
    try:
        path = os.path.expanduser("~/Library/Logs/Spillway/spillway.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.dup2(fd, 1)
        os.dup2(fd, 2)
        if fd > 2:
            os.close(fd)
    except OSError:
        pass  # bez logu se dá žít, bez přepisu ne


# JEN v podprocesu. Rodič si tenhle modul importuje taky (potřebuje odkazy na
# `init_worker`/`transcribe_chunk`, aby je mohl předat poolu) — a tomu se fd 1/2
# přepsat nesmí, jinak by se při vývoji ztratil výstup z terminálu.
if multiprocessing.parent_process() is not None:
    _redirect_output_to_log()

# Stav workeru — model se načte JEDNOU v `init_worker` a všechny další úlohy ho
# jen převezmou. Drží se v modulu (ne v předávaném objektu): pebble pouští
# inicializaci i úlohy na tomtéž vlákně téhož procesu, což je přesně to, co mlx
# vyžaduje (GPU stream je thread-local).
_backend = ""
_model = None


class WorkerInitError(RuntimeError):
    """Worker se nepodařilo připravit (chybí model, nefunguje GPU)."""


def init_worker(backend: str, model_path: str) -> None:
    """Načte model. Běží jednou při vzniku workeru; výjimka = worker nevznikne."""
    global _backend, _model
    _backend = backend
    if backend == "mlx":
        import mlx.core as mx
        import mlx_whisper
        import numpy as np
        from mlx_whisper.transcribe import ModelHolder

        ModelHolder.model = mlx_whisper.load_models.load_model(model_path, dtype=mx.float16)
        ModelHolder.model_path = model_path
        # Skutečný průchod GPU na drobném klipu — odhalí chybějící Metal shadery
        # TEĎ (worker se pak nenastartuje a je to v logu vidět), ne až prvním
        # diktátem. Dřív tahle kontrola běžela v hlavním procesu appky, čímž si
        # do něj tahala celý mlx/Metal stack, který tam nemá co dělat.
        mlx_whisper.transcribe(
            np.zeros(SAMPLE_RATE, dtype="float32"),
            path_or_hf_repo=model_path,
            language="cs",
        )
        _model = True
    else:
        from faster_whisper import WhisperModel

        _model = WhisperModel(model_path, device="cpu", compute_type="int8")
    print(f"🧠 worker připraven (backend={backend}, pid={os.getpid()})", flush=True)


SAMPLE_RATE = 16000
BEAM_SIZE = 5


def transcribe_chunk(
    audio,  # noqa: ANN001 — numpy float32, netypováno kvůli importu numpy až v procesu
    language: str,
    hotwords: str | None = None,
    beam_size: int = BEAM_SIZE,
) -> str:
    """Audio → text. Volá se v podprocesu; vrací se jen `str`."""
    if _model is None:
        raise WorkerInitError("worker nemá načtený model")
    if _backend == "mlx":
        import mlx_whisper
        from mlx_whisper.transcribe import ModelHolder

        res = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=ModelHolder.model_path,
            language=language,
            condition_on_previous_text=False,  # bez přenosu halucinací mezi okny
        )
        return (res.get("text") or "").strip()
    segments, _info = _model.transcribe(
        audio,
        language=language,
        vad_filter=True,
        beam_size=beam_size,
        hotwords=hotwords,
    )
    return " ".join(seg.text.strip() for seg in segments).strip()
