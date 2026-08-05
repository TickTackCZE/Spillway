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
import time

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
                # follow_symlinks: cache huggingface drží soubory jako symlinky
                # do blobs, takže bez následování by velikost vyšla nula.
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


class Cancelled(Exception):
    """Stahování přerušil uživatel."""


def _remote_files() -> list[tuple[str, int]]:
    """[(jméno souboru, velikost)] v repozitáři. Prázdné = nepodařilo se zjistit."""
    try:
        from huggingface_hub import HfApi

        info = HfApi().model_info(REPO, files_metadata=True)
        return [(sib.rfilename, int(sib.size or 0)) for sib in (info.siblings or [])]
    except Exception:  # noqa: BLE001 — bez sítě/API se to pozná až při stahování
        return []


def _fetch(url: str, dest: str, cancel, on_bytes) -> None:
    """Stáhne jeden soubor proudem, s kontrolou zrušení po každém megabajtu.

    Píše se do `.part` a přejmenovává až po dokončení — nedokončený soubor se
    tak nikdy netváří jako hotový model.
    """
    import urllib.request

    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "Spillway"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp, open(tmp, "wb") as f:
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                on_bytes(len(chunk))
    except BaseException:
        # Rozdělaný kus zahodit: range requesty neděláme, takže navázat na něj
        # stejně nejde a jen by matoucně zabíral místo. HOTOVÉ soubory vedle
        # něj zůstávají — na ty se při dalším pokusu naváže.
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, dest)


def download(on_progress=None, cancel: threading.Event | None = None) -> str:
    """Stáhne model do `model_dir()` a vrátí cestu k němu.

    Stahuje se **po souborech vlastním proudem**, ne přes `snapshot_download`.
    Důvod: ten nemá jak přerušit, takže „Zrušit" by 1,6 GB stáhlo celé a teprve
    pak smazalo — tedy nezrušilo vůbec nic. Takhle se zrušení projeví do vteřiny.

    `on_progress(hotovo_bytes, celkem_bytes)` se volá průběžně.
    Vyhazuje `Cancelled` při zrušení, jinou výjimku při chybě (typicky síť).
    """
    from huggingface_hub import hf_hub_url

    target = model_dir()
    os.makedirs(target, exist_ok=True)

    files = _remote_files()
    if not files:
        raise RuntimeError("nepodařilo se zjistit obsah modelu (síť?)")
    total = sum(sz for _n, sz in files) or _ESTIMATE_BYTES

    done_bytes = 0
    last_report = [0.0, -1]      # [čas, procento] posledního hlášení

    def bump(n: int) -> None:
        nonlocal done_bytes
        done_bytes += n
        if on_progress is None:
            return
        # Hlásit nejvýš 4×/s a jen když se procento změnilo. Bez toho by při
        # 20 MB/s přišlo 20 hlášení za sekundu a každé rozjelo překreslení
        # oken — přesně to sekalo UI a zdržovalo reakci na Zrušit.
        now = time.monotonic()
        pct = int(done_bytes / total * 100) if total else 0
        if pct == last_report[1] and now - last_report[0] < 0.25:
            return
        last_report[0], last_report[1] = now, pct
        try:
            on_progress(done_bytes, total)
        except Exception:  # noqa: BLE001 — ukazatel nesmí shodit stahování
            pass

    try:
        for name, size in files:
            dest = os.path.join(target, name)
            os.makedirs(os.path.dirname(dest) or target, exist_ok=True)
            # Hotový soubor přeskočit. Tohle je to, co dělá zrušení levným:
            # po Zrušit a novém Stáhnout se dotáhne jen zbytek, ne znovu celých
            # 1,6 GB. Dřív tu bylo `remove()` na zrušení, které smazalo celou
            # složku (a k tomu kopii v cache HuggingFace) — komentář o
            # nestahování znovu tehdy prostě nebyl pravda.
            if os.path.exists(dest) and (size == 0 or os.path.getsize(dest) == size):
                bump(size)
                continue
            _fetch(hf_hub_url(REPO, name), dest, cancel, bump)
    except Cancelled:
        # Nedokončený `.part` uklidil `_fetch`; hotové soubory schválně necháme.
        # Poloviční složka se za hotový model vydávat nemůže — `_complete()`
        # trvá na config.json i vahách zároveň.
        raise

    if not _complete(target):
        raise RuntimeError("model se nestáhl kompletně")
    if on_progress is not None:
        try:
            on_progress(total, total)
        except Exception:  # noqa: BLE001
            pass
    return target


class ModelMissing(Exception):
    """Model pro přepis není na stroji. Stáhnout ho smí JEN uživatel vědomě."""


def path_for_transcribe() -> str:
    """Lokální cesta k modelu pro mlx-whisper.

    **Vyhazuje `ModelMissing`, když model chybí.** Dřív se vracelo jméno
    repozitáře jako „záchranná brzda" — jenže mlx si ho pak tiše stáhl sám,
    1,6 GB na GPU vlákně, a celá aplikace na minutu zamrzla bez vysvětlení.
    Stahování patří výhradně do UI, kde je vidět průběh a jde ho zrušit.
    """
    found = find_local()
    if found is None:
        raise ModelMissing(REPO)
    return found[0]


# --- Sdílené stahování ------------------------------------------------------
# Tlačítko „Stáhnout" je na dvou místech (Nastavení i popover). Orchestrace
# je proto tady, ne v UI: běží nejvýš JEDNO stahování a oba posluchači dostávají
# stejný postup. Bez toho by dvojí klik spustil dvě stahování téhož modelu.

_dl_lock = threading.Lock()
_dl_thread: threading.Thread | None = None
_dl_listeners: list = []
_dl_state: dict = {"downloading": False, "percent": 0, "progress_text": ""}
_dl_cancel = threading.Event()


def download_state() -> dict:
    """Aktuální stav stahování (kopie, ať do něj volající nesahá)."""
    with _dl_lock:
        return dict(_dl_state)


def add_download_listener(fn) -> None:
    """Přihlásí se k odběru postupu. Volá se i hned s aktuálním stavem."""
    with _dl_lock:
        if fn not in _dl_listeners:
            _dl_listeners.append(fn)
        snapshot = dict(_dl_state)
    try:
        fn(snapshot)
    except Exception:  # noqa: BLE001
        pass


def remove_download_listener(fn) -> None:
    with _dl_lock:
        if fn in _dl_listeners:
            _dl_listeners.remove(fn)


def _emit(**state) -> None:
    with _dl_lock:
        _dl_state.update(state)
        snapshot, listeners = dict(_dl_state), list(_dl_listeners)
    for fn in listeners:
        try:
            fn(snapshot)
        except Exception:  # noqa: BLE001 — posluchač nesmí shodit stahování
            pass


def cancel_download() -> None:
    """Požádá běžící stahování o ukončení. Nedokončená složka se uklidí.

    Pod zámkem, ať klik přesně v okamžiku startu nového běhu nezruší omylem
    ten nový místo starého. Opakovaný klik je neškodný — příznak je idempotentní.
    """
    with _dl_lock:
        if _dl_thread is None or not _dl_thread.is_alive():
            return
        _dl_cancel.set()
    # Ohlásit hned — jinak by UI drželo „Stahuji X %", než vlákno doběhne.
    _emit(downloading=True, percent=0, progress_text="ruším…")


def download_async() -> bool:
    """Spustí stahování na pozadí. False = už běží, druhé se nespouští."""
    global _dl_thread
    with _dl_lock:
        if _dl_thread is not None and _dl_thread.is_alive():
            return False
        _dl_cancel.clear()

        def run() -> None:
            def progress(done_b: int, total_b: int) -> None:
                pct = int(done_b / total_b * 100) if total_b else 0
                _emit(downloading=True, percent=min(99, pct),
                      progress_text=f"{human_size(done_b)} z {human_size(total_b)}")

            try:
                download(on_progress=progress, cancel=_dl_cancel)
                print(f"⬇️  model stažen ({human_size(size_bytes())})")
            except Exception as exc:  # noqa: BLE001 — chyba sítě nesmí shodit UI
                if isinstance(exc, Cancelled) or _dl_cancel.is_set():
                    print("⏹️  stahování modelu zrušeno")
                else:
                    print(f"❌ stažení modelu selhalo: {exc}")
            _emit(downloading=False, percent=0, progress_text="")

        _dl_thread = threading.Thread(target=run, daemon=True)
        _dl_thread.start()
    _emit(downloading=True, percent=0, progress_text="začínám…")
    return True
