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

**Existující kopie se hledá i jinde** (`find_local`). Model si do cache
huggingface stahuje samo `mlx-whisper` a stahovaly ho tam i starší verze
Spillway — bez toho by aplikace hlásila „není stažený" nad plnohodnotnou
kopií a uživatel by zbytečně stahoval druhých 1,5 GB.
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
    """Kam model stahujeme MY. Jméno z repozitáře, ať jde mít víc modelů."""
    return os.path.join(_DIR, REPO.split("/")[-1])


def _complete(d: str) -> bool:
    """Je ve složce kompletní model? (nedokončené stažení se nesmí počítat)"""
    if not d or not os.path.isdir(d):
        return False
    if not all(os.path.exists(os.path.join(d, f)) for f in _REQUIRED):
        return False
    # Váhy mají jedno ze dvou jmen podle toho, jak byl model publikovaný.
    return any(
        os.path.exists(os.path.join(d, w)) for w in ("weights.safetensors", "weights.npz")
    )


def _hf_cache_dir() -> str | None:
    """Snapshot v cache huggingface, když už si ho někdo stáhl dřív.

    Důležité: model si do téhle cache stahuje samo `mlx-whisper` a stahovaly ho
    tam i starší verze Spillway. Bez tohohle hledání by aplikace hlásila
    „není stažený" nad plnohodnotnou kopií a uživatel by stahoval **druhých
    1,5 GB** zbytečně.
    """
    try:
        from huggingface_hub import try_to_load_from_cache

        hit = try_to_load_from_cache(REPO, "config.json")
        if isinstance(hit, str) and os.path.exists(hit):
            return os.path.dirname(hit)
    except Exception:  # noqa: BLE001 — bez knihovny prostě cache nehledáme
        pass
    return None


def find_local() -> tuple[str, str] | None:
    """(cesta, odkud) k použitelnému modelu na tomhle stroji, nebo None.

    Naše složka má přednost — je pod naší kontrolou a jde ji smazat jedním
    tlačítkem. Cache huggingface je plnohodnotná záloha.
    """
    ours = model_dir()
    if _complete(ours):
        return (ours, "složka Spillway")
    cached = _hf_cache_dir()
    if _complete(cached or ""):
        return (cached, "cache HuggingFace")  # type: ignore[return-value]
    return None


def is_ready() -> bool:
    """Je model použitelný — ať leží kdekoliv?"""
    return find_local() is not None


def _dir_size(d: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(d):
        for f in files:
            try:
                # `os.stat` bez follow_symlinks: cache huggingface je samé
                # symlinky do blobs a přes ně by se soubory počítaly dvakrát.
                st = os.stat(os.path.join(root, f), follow_symlinks=True)
                total += st.st_size
            except OSError:
                pass
    return total


def size_bytes() -> int:
    """Kolik model na disku zabírá (0 = není)."""
    found = find_local()
    return _dir_size(found[0]) if found else 0


def human_size(n: int) -> str:
    if n <= 0:
        return "0 MB"
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def remove() -> bool:
    """Smaže model odkudkoliv, kde leží. Vrátí True, když bylo co mazat.

    Maže i kopii v cache huggingface — jinak by uživatel klikl na Smazat,
    místo se neuvolnilo a aplikace by dál hlásila „připraven".
    """
    removed = False
    ours = model_dir()
    if os.path.isdir(ours):
        shutil.rmtree(ours, ignore_errors=True)
        removed = True

    cached = _hf_cache_dir()
    if cached:
        # Snapshot leží v .../hub/models--<org>--<jméno>/snapshots/<hash>/;
        # smazat je potřeba celou složku repozitáře i s blobs, jinak zabírá dál.
        repo_root = cached
        marker = "models--" + REPO.replace("/", "--")
        while repo_root and os.path.basename(repo_root) != marker:
            parent = os.path.dirname(repo_root)
            if parent == repo_root:
                repo_root = ""
                break
            repo_root = parent
        if repo_root and os.path.isdir(repo_root):
            shutil.rmtree(repo_root, ignore_errors=True)
            removed = True
    return removed


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
                    # `_dir_size(target)`, ne `size_bytes()` — to hledá
                    # existující kopii kdekoliv a ukazovalo by cizí velikost.
                    on_progress(_dir_size(target), total)
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
    if not _complete(target):
        raise RuntimeError("model se nestáhl kompletně")
    if on_progress is not None:
        try:
            on_progress(_dir_size(target), total)
        except Exception:  # noqa: BLE001
            pass
    return target


def path_for_transcribe() -> str:
    """Co předat mlx-whisperu.

    Když je model kdekoliv na stroji, vrátí **lokální cestu** (mlx ji použije
    přímo, bez sítě). Když ne, vrátí jméno repozitáře — mlx si ho stáhne sám.
    To je záchranná brzda, ne běžná cesta: bez ukazatele průběhu vypadá první
    diktát, jako by aplikace zamrzla.
    """
    found = find_local()
    return found[0] if found else REPO
