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

import os
import platform
import queue
import threading
import time

import numpy as np

from . import models

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
    """mlx na Apple Silicon (když jde importnout), jinak faster-whisper.
    Přebitelné přes SPILLWAY_WHISPER_BACKEND."""
    forced = (os.environ.get("SPILLWAY_WHISPER_BACKEND") or "").strip().lower()
    if forced in ("mlx", "faster"):
        return forced
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        try:
            import mlx_whisper  # noqa: F401

            return "mlx"
        except Exception:  # noqa: BLE001 — mlx nedostupné (nezabalené, chyba) → CPU
            return "faster"
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


class _MlxWorker:
    """Jedno vyhrazené vlákno pro VŠECHNY mlx GPU operace.

    mlx drží GPU stream per-vlákno, takže model načtený na jednom vlákně nejde
    použít na jiném („There is no Stream(gpu, N) in current thread" → spadlý přepis
    = ztracený diktát). Každý `_process` je navíc jiné vlákno. Řešení: načtení,
    přepis i uvolnění posíláme sem a běží serializovaně na jednom stálém vlákně.
    """

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        # Počet právě běžících prací. Sama fronta to neví: jakmile si vlákno
        # položku vyzvedne, `qsize()` je 0, i když se na GPU pořád počítá.
        self._running = 0
        self._n_lock = threading.Lock()
        self._t = threading.Thread(target=self._run, name="mlx-gpu", daemon=True)
        self._t.start()

    def _run(self) -> None:
        while True:
            fn, box, ev = self._q.get()
            with self._n_lock:
                self._running += 1
            try:
                box["r"] = fn()
            except BaseException as exc:  # noqa: BLE001 — přenést na volajícího
                box["e"] = exc
            finally:
                with self._n_lock:
                    self._running -= 1
                ev.set()

    def submit(self, fn, timeout: float | None = None):
        """Spustí `fn` na mlx vlákně a počká na výsledek (výjimku propaguje).

        `timeout` je pojistka proti zatuhnutí: když práce nedoběhne včas, vyhodí
        TimeoutError místo nekonečného čekání (volající se rozhodne, co dál).
        NIKDY nevolat bez timeoutu z hlavního vlákna — zablokovalo by celé UI.
        """
        box: dict = {}
        ev = threading.Event()
        self._q.put((fn, box, ev))
        if not ev.wait(timeout):
            raise TimeoutError("mlx worker neodpověděl včas")
        if "e" in box:
            raise box["e"]
        return box.get("r")

    def submit_async(self, fn) -> None:
        """Zařadí práci a NEČEKÁ na ni — pro volání z hlavního vlákna (UI timery),
        kde by čekání na vytížené GPU vlákno zmrazilo celou aplikaci."""
        self._q.put((fn, {}, threading.Event()))

    def pending(self) -> int:
        """Kolik práce je rozdělané — ve frontě I právě běžící.

        Běžící položku je nutné počítat: `qsize()` je nula od chvíle, kdy si ji
        vlákno vyzvedne, takže sám o sobě by tvrdil „nic se neděje" i uprostřed
        dlouhého přepisu — a streaming by dál sypal segmenty do fronty za ním.
        """
        with self._n_lock:
            return self._q.qsize() + self._running


class Transcriber:
    """[R5] Model (~1,5–2 GB) jde uvolnit po nečinnosti a znovu lazy-loadnout."""

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
        self._model = None  # faster: WhisperModel; mlx: sentinel True po warmu
        self._lock = threading.Lock()
        self._last_used = time.monotonic()
        # Vyhrazené vlákno pro VŠECHNY mlx GPU operace (viz _MlxWorker) — mlx drží
        # stream per-vlákno, takže načtení/přepis/unload musí běžet na jednom vlákně.
        self._mlx = _MlxWorker() if self.backend == "mlx" else None
        # V zabalené .app se mlx Metal shadery (mlx.metallib) můžou nezabalit —
        # ověř, že mlx reálně počítá na GPU, jinak spadni na CPU (žádná regrese).
        # Chybějící model NENÍ porucha mlx — fallback na CPU by tu nepomohl,
        # naopak: `WhisperModel` si tiše stáhne JINÝ model (~1,5 GB) a to při
        # startu na hlavním vlákně. Bez modelu se prostě nic nenačítá a čeká se,
        # až si ho uživatel stáhne z UI.
        self._weights_absent = not models.is_ready()
        # Kontrola proběhla? Bez modelu ji nelze udělat, tak se odloží na dobu,
        # kdy model přibude — jinak by se na rozbité mlx přišlo až prvním
        # diktátem po stažení.
        self._mlx_checked = False
        if self.backend == "mlx" and not self._weights_absent and not self._mlx_ok():
            print("⚠️  mlx nefunguje (shadery?) → fallback na faster-whisper (CPU).")
            self.backend = "faster"
            self._mlx = None
        self._mlx_checked = not self._weights_absent
        print(f"🗣️  Whisper backend: {self.backend}"
              f"{' (' + models.REPO + ')' if self.backend == 'mlx' else ' (CPU large-v3-turbo)'}")
        self._load_model()

    def _mlx_ok(self) -> bool:
        """Skutečně proženeme mlx přes GPU na drobném klipu — odhalí chybějící
        shadery/knihovny v bundlu ještě před prvním diktátem. Běží na mlx vlákně."""
        def _check() -> bool:
            import mlx_whisper

            mlx_whisper.transcribe(
                np.full(4800, 0.02, dtype="float32"),
                path_or_hf_repo=models.path_for_transcribe(), language="cs",
            )
            return True

        try:
            # Timeout: `__init__` běží na hlavním vlákně, takže zatuhlé GPU
            # vlákno by zabránilo startu celé aplikace.
            return bool(self._mlx.submit(_check, timeout=60.0))
        except TimeoutError:
            print("⚠️  mlx health-check neodpověděl do 60 s → fallback na CPU.")
            return False
        except models.ModelMissing:
            return False   # není co kontrolovat; stáhne ho uživatel z UI
        except Exception as exc:  # noqa: BLE001
            print(f"mlx health-check selhal: {exc}")
            return False

    # --- životní cyklus modelu ------------------------------------------------

    def _load_model(self) -> None:
        # Bez modelu nemá co načítat a hlavně: ani jeden backend ho nesmí začít
        # stahovat sám. mlx by sáhl na HF hub, faster-whisper by stáhl dokonce
        # JINÝ model — obojí tiše a na vlákně, které pak nereaguje.
        if not models.is_ready():
            self._weights_absent = True
            self._model = None
            return
        self._weights_absent = False
        if self.backend == "mlx" and not self._mlx_checked:
            # Odložená kontrola: model mezitím přibyl.
            self._mlx_checked = True
            if not self._mlx_ok():
                print("⚠️  mlx nefunguje (shadery?) → fallback na faster-whisper (CPU).")
                self.backend = "faster"
                self._mlx = None
        if self.backend == "mlx":
            # Načtení běží na mlx vlákně (přes worker) a plní ModelHolder — tam ho
            # hledá i mlx_whisper.transcribe, takže se model načte JEDNOU a přepis ho
            # (na stejném vlákně) jen převezme. dtype=float16 musí sedět s `transcribe`
            # (fp16=True). Přes load_models.load_model, ne ModelHolder.get_model (ta
            # v zabalené .app deadlockovala, ctypes/GIL).
            def _load() -> None:
                import mlx.core as mx
                import mlx_whisper
                from mlx_whisper.transcribe import ModelHolder

                # Zjistit cestu JEDNOU — kdyby se model mezi voláními dostáhl,
                # načetlo by se z jednoho místa a do holderu zapsalo jiné.
                path = models.path_for_transcribe()
                if ModelHolder.model is None or ModelHolder.model_path != path:
                    ModelHolder.model = mlx_whisper.load_models.load_model(
                        path, dtype=mx.float16
                    )
                    ModelHolder.model_path = path

            self._mlx.submit(_load)
            self._model = True
        else:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_name, device="cpu",
                                       compute_type=self.compute_type)

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def preload(self) -> None:
        """Načte model dopředu (volá se při stisku klávesy — reload se schová do
        doby, kdy uživatel mluví)."""
        with self._lock:
            if self._model is None:
                self._load_model()

    def unload_if_idle(self, idle_seconds: float) -> bool:
        """Uvolní model po nečinnosti. Volá se z UI časovače na HLAVNÍM vlákně."""
        if idle_seconds <= 0:
            return False
        # Zámek se bere BEZ ČEKÁNÍ. Tentýž zámek drží `preload()` po celou dobu
        # načítání modelu, a to je synchronní čekání na GPU vlákno — změřeno
        # 1,45 s. Když se tik časovače (á 5 s) trefí do načítání po stisku
        # klávesy, zamrzne na tu dobu celé UI: ikona přestane animovat, okénko
        # se nepřekreslí. A není proč čekat: model se zrovna načítá, takže se
        # stejně nemá co uvolňovat — příští tik to zkusí znovu.
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if self._model is None:
                return False
            if time.monotonic() - self._last_used < idle_seconds:
                return False
            self._model = None
        finally:
            self._lock.release()
        # Uvolnění GPU paměti taky na mlx vlákně (tam, kde byl model načten), ale
        # BEZ ČEKÁNÍ: tohle volá UI timer na hlavním vlákně a čekání na vytížené
        # GPU vlákno by zmrazilo celou appku (bug „appka se sekne, nutno vypnout").
        if self.backend == "mlx" and self._mlx is not None:
            self._mlx.submit_async(self._unload_mlx_gpu)
        return True

    @property
    def busy(self) -> bool:
        """Čeká něco ve frontě GPU vlákna? (streaming se podle toho přiškrtí)."""
        return self._mlx is not None and self._mlx.pending() > 0

    @staticmethod
    def _unload_mlx_gpu() -> None:
        """Skutečně uvolní GPU paměť mlx (ověřeno: ~2 GB → 0). mlx drží model
        na `ModelHolder.model` a k tomu má vlastní GPU cache pool — obojí zahodit."""
        try:
            import mlx.core as mx
            from mlx_whisper.transcribe import ModelHolder

            ModelHolder.model = None
            ModelHolder.model_path = None
            mx.clear_cache()
        except Exception:  # noqa: BLE001
            pass

    # --- přepis ---------------------------------------------------------------

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
        lang = language or self.language

        if self.backend == "mlx":
            text = self._transcribe_mlx(audio, lang)
        else:
            text = self._transcribe_faster(audio, lang, hotwords)

        with self._lock:
            self._last_used = time.monotonic()  # dokončení, ne jen start
        return _drop_hallucination(text)

    def _transcribe_mlx(self, audio: np.ndarray, lang: str) -> str:
        if _is_silence(audio):  # brána proti halucinaci na tichu
            return ""

        # Přepis běží na mlx vlákně (stejném, kde je načtený model) — jinak
        # „There is no Stream(gpu, N) in current thread" a spadlý (ztracený) diktát.
        def _do() -> str:
            import mlx_whisper

            res = mlx_whisper.transcribe(
                audio,
                path_or_hf_repo=models.path_for_transcribe(),
                language=lang,
                condition_on_previous_text=False,  # bez přenosu halucinací mezi okny
            )
            return (res.get("text") or "").strip()

        return self._mlx.submit(_do)

    def _transcribe_faster(self, audio: np.ndarray, lang: str,
                           hotwords: list[str] | None) -> str:
        model = self._model
        segments, _info = model.transcribe(
            audio,
            language=lang,
            vad_filter=True,
            beam_size=BEAM_SIZE,
            hotwords=_hotwords_str(hotwords),
        )
        return " ".join(seg.text.strip() for seg in segments).strip()


def _drop_hallucination(text: str) -> str:
    # [B8] Zahoď jen krátký výstup, který je celý halucinační marker.
    if len(text) > _HALLUCINATION_MAX_LEN:
        return text
    low = text.lower()
    if any(m in low for m in _HALLUCINATION_MARKERS):
        return ""
    return text
