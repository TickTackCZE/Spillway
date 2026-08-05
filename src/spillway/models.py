"""Kde leží model pro přepis a jak se stáhne.

**Model NENÍ součástí aplikace.** Váží ~1,5 GB a stahuje se při prvním spuštění
do `~/Library/Application Support/Spillway/models/`. Důvody proti zabalení do
`.app`:

- bundle by narostl z 500 MB na ~2 GB a **každá aktualizace** by znamenala
  stáhnout je celé znovu, i když se změnil jen kód;
- podepisování a notarizace 1,5 GB vah zdržují každý build;
- model takhle **přežije přeinstalaci i aktualizaci** aplikace — stáhne se jednou.

Proti dřívějšímu stavu (cache huggingface v `~/.cache`) je tohle umístění
viditelné a spravovatelné: v Nastavení jde ukázat, kolik zabírá, a smazat ho.
`mlx_whisper.load_model()` přijme lokální cestu, takže si o stažení říkáme sami
a nespoléháme na to, kam a kdy si soubory uloží knihovna.
"""

from __future__ import annotations

import os
import shutil
import threading

REPO = os.environ.get("SPILLWAY_MLX_MODEL") or "mlx-community/whisper-large-v3-turbo"

_DIR = os.path.expanduser("~/Library/Application Support/Spillway/models")
# Odhad pro ukazatel průběhu, když se nepodaří zjistit skutečnou velikost z API.
_ESTIMATE_BYTES = 1_600_000_000
# Bez tohohle souboru je stažení neúplné — podle něj se pozná hotový model.
_REQUIRED = ("config.json",)


def model_dir() -> str:
    """Složka s modelem. Jméno se odvozuje z repozitáře, ať jde mít víc modelů."""
    return os.path.join(_DIR, REPO.split("/")[-1])


def is_ready() -> bool:
    """Je model kompletně stažený a použitelný?"""
    d = model_dir()
    if not all(os.path.exists(os.path.join(d, f)) for f in _REQUIRED):
        return False
    # Váhy mají jedno ze dvou jmen podle toho, jak byl model publikovaný.
    return any(
        os.path.exists(os.path.join(d, w)) for w in ("weights.safetensors", "weights.npz")
    )


def size_bytes() -> int:
    """Kolik model na disku zabírá (0 = není)."""
    total = 0
    for root, _dirs, files in os.walk(model_dir()):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def human_size(n: int) -> str:
    if n <= 0:
        return "0 MB"
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def remove() -> bool:
    """Smaže stažený model. Vrátí True, když bylo co mazat."""
    d = model_dir()
    if not os.path.isdir(d):
        return False
    shutil.rmtree(d, ignore_errors=True)
    return True


def _expected_bytes() -> int:
    """Celková velikost ke stažení; při chybě odhad, ať ukazatel nezamrzne."""
    try:
        from huggingface_hub import HfApi

        info = HfApi().model_info(REPO, files_metadata=True)
        total = sum(s.size or 0 for s in (info.siblings or []))
        return total or _ESTIMATE_BYTES
    except Exception:  # noqa: BLE001 — bez sítě/API jedeme na odhad
        return _ESTIMATE_BYTES


def download(on_progress=None, cancel: threading.Event | None = None) -> str:
    """Stáhne model do `model_dir()` a vrátí cestu k němu.

    `on_progress(hotovo_bytes, celkem_bytes)` se volá ~2× za sekundu z pomocného
    vlákna. Průběh se odvozuje z velikosti složky, ne z vnitřností stahovací
    knihovny — je to odolnější vůči tomu, že si mění chování mezi verzemi.

    Vyhazuje výjimku, když stažení selže (nejčastěji chybějící síť).
    """
    from huggingface_hub import snapshot_download

    target = model_dir()
    os.makedirs(target, exist_ok=True)
    total = _expected_bytes()

    done = threading.Event()

    def _watch() -> None:
        while not done.wait(0.5):
            if on_progress is not None:
                try:
                    on_progress(size_bytes(), total)
                except Exception:  # noqa: BLE001 — ukazatel nesmí shodit stahování
                    pass

    watcher = threading.Thread(target=_watch, daemon=True)
    watcher.start()
    try:
        snapshot_download(
            repo_id=REPO,
            local_dir=target,
            # Bez symlinků do sdílené cache — chceme soběstačnou složku, kterou
            # jde celou smazat jedním tlačítkem.
            max_workers=4,
        )
    finally:
        done.set()

    if cancel is not None and cancel.is_set():
        remove()
        raise RuntimeError("stahování zrušeno")
    if not is_ready():
        raise RuntimeError("model se nestáhl kompletně")
    if on_progress is not None:
        try:
            on_progress(size_bytes(), total)
        except Exception:  # noqa: BLE001
            pass
    return target


def path_for_transcribe() -> str:
    """Co předat mlx-whisperu.

    Když je model stažený u nás, vrátí **lokální cestu** (mlx ji použije přímo).
    Když ne, vrátí jméno repozitáře — mlx si ho stáhne sám do své cache. To je
    záchranná brzda, ne běžná cesta: bez ukazatele průběhu vypadá první diktát
    jako by aplikace zamrzla.
    """
    return model_dir() if is_ready() else REPO
