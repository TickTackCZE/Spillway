"""Lokální přepis řeči.

Dva backendy za jedním rozhraním:
  • **mlx** — mlx-whisper na Apple GPU/ANE (RTF ~0,08 na M4, ~4,5× rychlejší než
    CPU při stejné kvalitě — změřeno). Výchozí na Apple Silicon.
  • **faster** — faster-whisper na CPU. Fallback (jiný HW, budoucí Windows, nebo
    když mlx nejde načíst). Má VAD zabudovaný.

mlx VAD nemá → ticho by halucinovalo („Titulky vytvořil…"). Řešíme bránou přes
silero VAD z faster_whisper (onnx už je v bundlu) + post-filtrem `_drop_hallucination`.

Přepnutí: `SPILLWAY_WHISPER_BACKEND=mlx|faster`. Model uvolnitelný po nečinnosti (R5).
"""

from __future__ import annotations

import importlib.util
import multiprocessing
import os
import platform
import threading
import time

import numpy as np

from . import gpuworker, models

# Známé halucinace na tichu/krátkém audiu (R10). [B8] filtr smí zahodit jen
# KRÁTKÝ výstup (jinak zahodí legitimní diktát začínající „Titulky…"/„Překlad…").
_HALLUCINATION_MARKERS = (
    "titulky vytvořil",
    "titulky pro",
    "překlad titulků",
    "www.",
    ".cz",
)
_HALLUCINATION_MAX_LEN = 45

# Odkud brát váhy: `models.path_for_transcribe()` vrátí LOKÁLNÍ složku, a když
# model stažený není, vyhodí `ModelMissing`. Žádná „záchrana" jménem
# repozitáře — to byla přesně ta past, kvůli které si mlx začal na pozadí tiše
# stahovat 1,6 GB a aplikace na minutu zamrzla. Model stahuje jedině uživatel
# z UI. Čte se při každém použití, ne jednou při importu — jinak by se po
# stažení modelu za běhu pořád sahalo do staré cache.
SAMPLE_RATE = 16000  # Whisper i Recorder jedou na 16 kHz mono


def _beam_size() -> int:
    try:
        return max(1, int(os.environ.get("SPILLWAY_BEAM_SIZE", "5")))
    except (TypeError, ValueError):
        return 5


BEAM_SIZE = _beam_size()


def _hotwords_str(terms: list[str] | None) -> str | None:
    """Slovník → jeden řetězec pro faster-whisper `hotwords`. Prázdný → None."""
    if not terms:
        return None
    cleaned = [t.strip() for t in terms if t and t.strip()]
    return ", ".join(cleaned) if cleaned else None


def _pick_backend() -> str:
    """mlx na Apple Silicon (když je k dispozici), jinak faster-whisper.
    Přebitelné přes SPILLWAY_WHISPER_BACKEND.

    Jen `find_spec`, nikdy skutečný import: ten stojí 1,57 s (měřeno) a natáhl by
    do HLAVNÍHO procesu celý mlx/Metal stack, který od téhle chvíle patří výhradně
    do podprocesu (`gpuworker`). Jestli mlx opravdu počítá na GPU, se pozná až
    tam — při startu workeru, ne tady.
    """
    forced = (os.environ.get("SPILLWAY_WHISPER_BACKEND") or "").strip().lower()
    if forced in ("mlx", "faster"):
        return forced
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "mlx" if importlib.util.find_spec("mlx_whisper") is not None else "faster"
    return "faster"


_SPEECH_MIN_S = 0.25   # míň řeči než tohle = opravdu není co přepisovat
_FRAME_MS = 30
_SPEECH_RMS = 0.01     # hlasitost rámce, od které se počítá jako řeč


def _frame_rms(audio: np.ndarray, frame_ms: int = _FRAME_MS) -> np.ndarray:
    """Hlasitost po rámcích (RMS). Prázdné pole, když je audio kratší než rámec."""
    n = int(SAMPLE_RATE * frame_ms / 1000)
    if audio is None or n <= 0 or audio.size < n:
        return np.zeros(0, dtype=np.float32)
    usable = audio.size - (audio.size % n)
    frames = audio[:usable].astype(np.float32).reshape(-1, n)
    return np.sqrt(np.mean(frames ** 2, axis=1))


def _is_silence(audio: np.ndarray) -> bool:
    """Je v nahrávce vůbec něco k přepsání? Brána proti halucinaci mlx na tichu
    („Titulky vytvořil…"); mlx vlastní VAD nemá. Silero VAD se sem záměrně
    nedává — na CPU by ukusoval z GPU zrychlení.

    Rozhoduje ABSOLUTNÍ délka řeči, ne její podíl na nahrávce. Podíl byl chyba:
    práh 1 % znamenal, že u 300s nahrávky je potřeba 3 s řeči, kdežto u 10s
    stačí 0,1 s. Čím déle člověk nahrával, tím spíš mu appka zahodila i to, co
    opravdu řekl — a zahodila to CELÉ, přepis se ani nespustil.
    """
    if audio is None or audio.size < 1600:  # < 0,1 s → nic k přepisu
        return True
    return voiced_seconds(audio) < _SPEECH_MIN_S


def voiced_seconds(audio: np.ndarray, frame_ms: int = _FRAME_MS,
                   thresh: float = _SPEECH_RMS) -> float:
    """Odhad délky SKUTEČNÉ řeči (bez ticha a pauz) — pro „tempo řeči". Sečte
    30ms rámce, jejichž RMS překročí práh; levné, bez VAD modelu. Ticho/pauzy
    (RMS pod prahem) se nezapočítají, takže tempo = slova / minuty MLUVENÍ."""
    if audio is None or audio.size == 0:
        return 0.0
    rms = _frame_rms(audio, frame_ms)
    if rms.size == 0:
        return float(audio.size) / SAMPLE_RATE
    return int(np.count_nonzero(rms > thresh)) * frame_ms / 1000.0


def level_summary(audio: np.ndarray) -> str:
    """Hlasitost nahrávky do logu: špička · pozadí · práh.

    Bez toho nejde po ztraceném diktátu poznat, jestli mikrofon nezachytil nic,
    nebo jen tiše — a to je rozdíl mezi mrtvým vstupem a špatným zařízením
    (AirPods v režimu HFP jsou znatelně tišší než vestavěný mikrofon).
    """
    rms = _frame_rms(audio)
    if rms.size == 0:
        return "bez signálu"
    return (f"špička {float(rms.max()):.4f} · pozadí "
            f"{float(np.percentile(rms, 10)):.4f} · práh {_SPEECH_RMS:.4f}")


def next_segment_boundary(
    audio: np.ndarray,
    start: int,
    *,
    min_speech_s: float = 2.0,
    min_silence_s: float = 0.45,
    thresh: float = 0.01,
    frame_ms: int = 30,
) -> int | None:
    """Řez segmentu pro streaming přepis: index vzorku > `start` **uprostřed
    dostatečně dlouhého ticha**, které přišlo po dostatečné řeči. `None`, když
    takový řez zatím není (mluví se dál / ještě málo řeči).

    Řeže se ZÁMĚRNĚ v tichu (ne fixně) — slova se tak nesekají uprostřed a
    segmenty jdou prostě zřetězit (viz research: VAD řez kvalitu nezhoršuje)."""
    if audio is None or start < 0 or start >= audio.size:
        return None
    n = int(SAMPLE_RATE * frame_ms / 1000)
    tail = audio[start:]
    usable = tail.size - (tail.size % n)
    if usable < n:
        return None
    rms = np.sqrt(np.mean(tail[:usable].astype(np.float32).reshape(-1, n) ** 2, axis=1))
    voiced = rms > thresh
    min_speech_frames = max(1, int(min_speech_s * 1000 / frame_ms))
    min_silence_frames = max(1, int(min_silence_s * 1000 / frame_ms))
    voiced_count = 0
    i = 0
    m = len(voiced)
    while i < m:
        if voiced[i]:
            voiced_count += 1
            i += 1
            continue
        j = i
        while j < m and not voiced[j]:
            j += 1
        if voiced_count >= min_speech_frames and (j - i) >= min_silence_frames:
            cut_frame = i + (j - i) // 2  # řez doprostřed ticha
            return start + cut_frame * n
        i = j
    return None


class TranscribeFailed(RuntimeError):
    """Přepis se nepovedl (zásek → zabitý worker, nebo rozbitý pool).

    Vlastní typ, ne holý `RuntimeError`: pipeline podle něj pozná, že má smysl
    zkusit to ještě jednou na čerstvém workeru, a odliší to od chyby v datech.
    """


# Po kolika DIKTÁTECH vyměnit worker i bez zaseknutí. mlx roste ~10 MB na volání
# (mlx-examples#1254) a při souvislém používání se appka na klidovou pauzu — a tím
# na uvolnění workeru — nemusí dostat celé hodiny.
# Záměrně se počítají diktáty, ne úlohy: `max_tasks` z pebble počítá úlohy, jenže
# streaming pošle za JEDEN dlouhý diktát klidně 100 úseků — worker by se tak
# vyměnil několikrát uprostřed diktátu, pokaždé s novým načtením modelu.
_RECYCLE_AFTER_DICTATIONS = 25

# Kolik nechat na start workeru + načtení modelu (~1,9 s měřeno, s velkou rezervou
# na studený disk). Musí to hlídat volající: `pool.schedule(timeout=)` z pebble
# běží až od chvíle, kdy úlohu převezme worker, takže zaseklé NAČÍTÁNÍ modelu by
# jinak nehlídal nikdo — a přitom je to přesně ta operace, co se zasekává.
_WARMUP_DEADLINE_S = 35.0

# Pebble posílá zaseklému workeru nejdřív SIGTERM a čeká `term_timeout` (3 s), než
# sáhne po SIGKILL. Nativně zaseklý proces se k obsluze SIGTERMu nedostane, takže
# se zabití reálně opozdí o tuhle dobu — měřeno 4,15 s u limitu 1 s. Připočítává
# se k limitům, ať appka nehlásí zásek dřív, než ho pebble stihne uklidit.
_KILL_GRACE_S = 5.0


def transcribe_deadline(audio_secs: float, backend: str) -> float:
    """Kolik sekund nechat přepisu, než se prohlásí za zaseknutý.

    Úměrně délce zvuku, ne pevně: jedno číslo nemůže sedět krátkému „zbytku" po
    streamování (2–11 s) i celé 300s nahrávce bez jediné pauzy. Vychází ze
    změřené rychlosti (RTF ~0,08 na mlx, ~0,22 na CPU) s ~4× rezervou, ať se
    pomalý-ale-zdravý přepis nikdy nezabije jen proto, že je dlouhý.

    JEDNO místo pravdy: tutéž hodnotu si bere i strop kroku ve watchdogu
    (`app.Controller.watchdog_check`), aby si dva nezávislé limity neodporovaly.
    """
    # mlx 0,35 = ~4,4× rezerva nad měřeným RTF 0,08; CPU 0,6 = ~2,7× nad měřeným
    # RTF 0,219 (a ~1,7× nad 0,36, které plyne z dokumentovaného poměru 4,5×).
    rate = 0.35 if backend == "mlx" else 0.6
    return max(30.0, 8.0 + audio_secs * rate)


def _kill_stray_workers() -> None:
    """Pojistka: dorazit procesy poolu, které nezemřely při jeho zavírání.

    `pool.join()` umí zatuhnout (čeká na vlákno, které samo může viset v zápisu),
    takže na něj nikdy nespoléháme jako na jedinou cestu. Tohle je levné a jisté.
    """
    for child in multiprocessing.active_children():
        if "pebble" in (child.name or "").lower():
            try:
                child.kill()
            except Exception:  # noqa: BLE001 — úklid nikdy nesmí nic shodit
                pass


class Transcriber:
    """Přepis v samostatném, zabitelném procesu (viz `gpuworker`).

    Navenek se chová stejně jako dřív (`transcribe`, `preload`, `is_loaded`,
    `busy`, `unload_if_idle`) — jen se práce nedělá na vlákně uvnitř appky, ale
    v podprocesu, který jde při zaseknutí zabít. Vlastní frontu ani vlákna už
    nedržíme: životní cyklus workeru, zabití po vypršení limitu i restart řeší
    `pebble.ProcessPool`.
    """

    def __init__(
        self,
        model_name: str = "large-v3-turbo",
        compute_type: str = "int8",
        language: str = "cs",
    ):
        self.model_name = model_name
        self.compute_type = compute_type
        self.language = language
        self.backend = _pick_backend()
        self._pool = None
        self._lock = threading.Lock()
        self._last_used = time.monotonic()
        self._ready = False          # worker doopravdy načetl model
        self._starting = False       # pool se právě zakládá / zahřívá
        self._inflight = 0           # kolik přepisů zrovna běží
        self._dictations = 0         # pro obměnu po N diktátech
        self._recycle_due = False
        # Zavolá se, když je appka po zaseknutí v takovém stavu, že jí prospěje
        # restart (viz `app.Controller._needs_restart`). Nastavuje `Controller`.
        self.on_needs_restart = None
        print(f"🗣️  Whisper backend: {self.backend}"
              f"{' (' + models.REPO + ')' if self.backend == 'mlx' else ' (CPU large-v3-turbo)'}")

    # --- životní cyklus workeru ----------------------------------------------

    def _model_path(self) -> str:
        """Odkud vzít váhy. Pro CPU backend je to jméno modelu (faster-whisper si
        ho najde ve své cache), pro mlx lokální složka, kterou spravuje `models`."""
        if self.backend == "mlx":
            return models.path_for_transcribe()
        return self.model_name

    def _new_pool(self):  # noqa: ANN201 — pebble typy až za importem
        from pebble import ProcessPool

        # „spawn" natvrdo: po `fork` Apple u vyšších frameworků negarantuje nic
        # (a zděděné file descriptory by navíc rozbily poznání, že worker umřel).
        return ProcessPool(
            max_workers=1,
            context=multiprocessing.get_context("spawn"),
            initializer=gpuworker.init_worker,
            initargs=(self.backend, self._model_path()),
        )

    def _discard_pool(self, pool) -> None:  # noqa: ANN001
        """Zahodit pool i s workerem. Zavírání běží na vlákně na pozadí.

        Pebble po nečistém úmrtí workeru označí pool za rozbitý a už ho nikdy
        neoživí — proto se nikdy „neopravuje", vždycky se zakládá nový. Zavírání
        nesmí blokovat volajícího: `join()` na zavřeném poolu nemá účinný limit
        a čeká i na vlákno, které samo může viset v odesílání dat.
        """
        if pool is None:
            return

        def _close() -> None:
            try:
                pool.stop()
                pool.join(timeout=3.0)
            except Exception:  # noqa: BLE001
                pass
            _kill_stray_workers()

        threading.Thread(target=_close, name="spillway-pool-close", daemon=True).start()

    def _ensure_pool(self):  # noqa: ANN201
        """Vrátí živý pool; založí ho, když chybí nebo je na výměnu. Pod zámkem."""
        with self._lock:
            if self._pool is not None and not self._recycle_due:
                return self._pool
            old, self._pool = self._pool, None
            self._ready = False
            if self._recycle_due and old is not None:
                print(f"♻️  worker vyměněn po {self._dictations} diktátech")
            self._recycle_due = False
            self._dictations = 0
            self._starting = True
        self._discard_pool(old)
        pool = self._new_pool()
        with self._lock:
            self._pool = pool
        return pool

    def _drop_pool(self, reason: str) -> None:
        """Zahodit pool po chybě a říct appce, že se stalo něco nedobrého."""
        with self._lock:
            old, self._pool = self._pool, None
            self._ready = False
            self._starting = False
        self._discard_pool(old)
        print(f"💥 worker zahozen ({reason}) — příští diktát startuje čerstvý")
        cb = self.on_needs_restart
        if cb is not None:
            try:
                cb(reason)
            except Exception:  # noqa: BLE001 — hlášení nikdy nesmí shodit přepis
                pass

    @property
    def is_loaded(self) -> bool:
        """Je model připravený k okamžitému použití?

        Ptá se i na to, jestli proces vůbec žije — jinak by `on_press` přeskočil
        předehřátí a studený start (~1,9 s) by spadl doprostřed diktátu.
        """
        pool = self._pool
        if pool is None or not self._ready:
            return False
        try:
            return bool(pool.active)
        except Exception:  # noqa: BLE001
            return False

    @property
    def busy(self) -> bool:
        """Dělá se na GPU zrovna něco? Streaming se podle toho přiškrtí.

        Musí být `True` i během startu workeru a načítání modelu — ne jen když
        běží přepis. Bez toho by streamovací smyčka během načítání sypala úseky
        do fronty a nahromadila práci, kterou GPU nestíhá (přesně to, čemu má
        brzdění zabránit).
        """
        return self._inflight > 0 or self._starting

    def preload(self) -> None:
        """Nastartovat worker a načíst model dopředu (volá se při stisku klávesy,
        aby se čekání schovalo do doby, kdy uživatel ještě mluví)."""
        if self.is_loaded:
            return
        try:
            self._warmup()
        except Exception as exc:  # noqa: BLE001 — předehřátí nikdy neshodí diktát
            print(f"⚠️  předehřátí selhalo: {exc}")

    def _warmup(self) -> None:
        """Počká, až worker doopravdy načte model (nebo to vzdá a pool zahodí).

        Limit hlídáme MY přes `result(timeout=)`, ne `schedule(timeout=)`: ten
        z pebble začíná běžet až ve chvíli, kdy úlohu převezme worker, takže
        zaseklé načítání modelu by nehlídal vůbec nikdo.
        """
        from concurrent.futures import TimeoutError as _FutureTimeout

        pool = self._ensure_pool()
        # Prázdné pole → `transcribe_chunk` se vůbec nedostane k modelu; úloha tu
        # slouží jen k tomu, aby se počkalo na dokončený `init_worker`.
        future = pool.schedule(
            gpuworker.transcribe_chunk,
            args=(np.zeros(0, dtype=np.float32), self.language),
            timeout=_WARMUP_DEADLINE_S + _KILL_GRACE_S,
        )
        try:
            future.result(timeout=_WARMUP_DEADLINE_S)
        except _FutureTimeout:
            self._drop_pool(f"načítání modelu nedoběhlo do {_WARMUP_DEADLINE_S:.0f} s")
            raise TranscribeFailed("worker se nestihl připravit") from None
        except gpuworker.WorkerInitError:
            pass  # prázdné audio → model JE načtený, jen nebylo co přepisovat
        except Exception as exc:
            self._drop_pool(f"worker se nepodařilo připravit: {exc}")
            raise TranscribeFailed(str(exc)) from exc
        with self._lock:
            self._ready = True
            self._starting = False
            self._last_used = time.monotonic()

    def unload_if_idle(self, idle_seconds: float) -> bool:
        """Uvolnit model po nečinnosti = ukončit celý worker.

        Proti dřívějšímu `mx.clear_cache()` je to zaručené (změřeno: SIGKILL vrátí
        ~1 GB za 43 ms), ne „nejlepší snaha". Volá se z časovače na hlavním vlákně,
        takže se tu nesmí na nic čekat — zavírání si `_discard_pool` odnese na
        vlastní vlákno.

        Tohle zároveň dělá obměnu workeru při delší pauze: další diktát dostane
        čerstvý proces. Samostatná „obnova po N minutách klidu" by proto nedělala
        nic navíc a v kódu není.
        """
        if idle_seconds <= 0:
            return False
        with self._lock:
            if self._pool is None or self._inflight > 0 or self._starting:
                return False
            if time.monotonic() - self._last_used < idle_seconds:
                return False
            pool, self._pool = self._pool, None
            self._ready = False
        self._discard_pool(pool)
        return True

    def note_dictation_done(self) -> None:
        """Diktát doběhl — po N diktátech si řekne o výměnu workeru.

        Výměna se NEDĚLÁ hned: proběhne až při zakládání dalšího diktátu, ať se
        načítání modelu (~1,9 s) schová do doby, kdy uživatel teprve mluví.
        """
        with self._lock:
            self._dictations += 1
            if self._dictations >= _RECYCLE_AFTER_DICTATIONS:
                self._recycle_due = True

    def shutdown(self) -> None:
        """Ukončit worker při zavírání appky.

        Musí to udělat appka sama: `rumps.quit_application()` ukončí proces mimo
        běžný úklid Pythonu, takže `atexit` v multiprocessing nikdy neproběhne a
        worker by osiřel i s celým modelem v paměti.
        """
        with self._lock:
            pool, self._pool = self._pool, None
            self._ready = False
        self._discard_pool(pool)
        _kill_stray_workers()

    # --- přepis ---------------------------------------------------------------

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        hotwords: list[str] | None = None,
    ) -> str:
        """Audio → text. Zaseklý worker se zabije a přepis skončí `TranscribeFailed`.

        Opakování se tu ZÁMĚRNĚ nedělá: jestli má smysl zkusit to ještě jednou,
        ví jen pipeline (`app._transcribe_audio`) — ta jediná zná zbývající
        rozpočet celého diktátu. Kdyby se opakovalo tady, dva limity by si
        odporovaly a diktát by přerostl vlastní watchdog appky.
        """
        from concurrent.futures import TimeoutError as _FutureTimeout

        if audio is None or audio.size == 0:
            return ""
        if _is_silence(audio):  # brána proti halucinaci na tichu; levné, bez IPC
            return ""
        lang = language or self.language
        if not self.is_loaded:
            self._warmup()  # vyhodí TranscribeFailed, když se nepovede

        deadline = transcribe_deadline(audio.size / SAMPLE_RATE, self.backend)
        pool = self._ensure_pool()
        with self._lock:
            self._inflight += 1
            self._last_used = time.monotonic()
        try:
            future = pool.schedule(
                gpuworker.transcribe_chunk,
                args=(audio, lang, _hotwords_str(hotwords), BEAM_SIZE),
                timeout=deadline + _KILL_GRACE_S,
            )
            try:
                text = future.result(timeout=deadline + _KILL_GRACE_S * 2)
            except _FutureTimeout:
                self._drop_pool(f"přepis nedoběhl do {deadline:.0f} s")
                raise TranscribeFailed("přepis se zasekl") from None
            except Exception as exc:  # i pád workeru je pro nás zásek
                self._drop_pool(f"worker spadl: {exc}")
                raise TranscribeFailed(str(exc)) from exc
        finally:
            with self._lock:
                self._inflight = max(0, self._inflight - 1)
                self._last_used = time.monotonic()
        return _drop_hallucination(text or "")


def _drop_hallucination(text: str) -> str:
    # [B8] Zahoď jen krátký výstup, který je celý halucinační marker.
    if len(text) > _HALLUCINATION_MAX_LEN:
        return text
    low = text.lower()
    if any(m in low for m in _HALLUCINATION_MARKERS):
        return ""
    return text
