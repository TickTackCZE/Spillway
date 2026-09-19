"""Nahrávání mikrofonu do paměti (16 kHz mono float32).

Audio nikdy neopouští RAM ani se neukládá na disk (privacy). Ve Spike B ověřeno,
že faster-whisper přijímá numpy float32 pole přímo, bez dekódování souboru.
"""

from __future__ import annotations

import gc
import threading

import numpy as np
import sounddevice as sd

from . import diag

SAMPLE_RATE = 16000
MAX_SECONDS_DEFAULT = 300  # 5 min — pojistka proti ztracenému key-up; 5 min ≈ 19 MB RAM

# Jak dlouho čekat na čisté zavření mikrofonu, než ho necháme dozavřít na pozadí.
# Běžně to trvá desítky ms; zaseknutí je vzácné, ale bez limitu bere s sebou celou
# appku (`sounddevice#394`, `portaudio#367` — obojí otevřené, bez opravy upstream).
_CLOSE_BUDGET_S = 0.8
# Jak dlouho čekat před NOVÝM nahráváním, než se předchozí zavírání dokončí.
# Musí zůstat výrazně pod `app._await_recorder_start` (5 s), jinak by se `stop()`
# rozjel dřív, než `start()` projde bránou, a otevřel by stream, co nikdo nezavře.
_REOPEN_BUDGET_S = 3.0
# Jak dlouho čekat na oživení PortAudia po selhaném otevření mikrofonu. Jsou to
# tatáž nativní volání jako v `_teardown`, takže se umí zaseknout stejně —
# proto ohraničené a na vlastním vlákně.
_REVIVE_BUDGET_S = 2.0


class MicrophoneUnavailable(RuntimeError):
    """Mikrofon nejde otevřít a `Recorder` to sám spravit neumí.

    Vlastní typ, ne holý `RuntimeError`: appka podle něj pozná, že má uživateli
    říct „mikrofon nedostupný" a naplánovat restart — místo aby tvářila, že
    nahrává, a nezachytila nic (přesně tak se ten bug projevoval).

    Že je to JEDINÝ typ pro „nejde nahrávat", je záměr: rozhodnutí, co ještě
    jde spravit zevnitř procesu, patří sem k PortAudiu, ne do `Controller`.
    Dokud tuhle výjimku vyhazovalo jen zaseklé dozavírání, propadla selhaná
    `sd.InputStream()` ven jako obyčejná výjimka — a appka o restart vůbec
    nepožádala. V logu je za to jedenáct stisků po sobě se stejnou chybou
    (`PaErrorCode -9986`) a bez jediného pokusu o zotavení.
    """

# Rozsah pro živý ukazatel hlasitosti v liště. Ticho v pokoji vyjde kolem -60 dB,
# běžná řeč do mikrofonu v notebooku -35 až -15 dB. Spodní hranici držíme nad
# šumem, ať ikona v tichu opravdu stojí, horní pod klipem, ať se dá „vyjet nahoru".
_LEVEL_DB_MIN = -48.0
_LEVEL_DB_MAX = -14.0


def _restart_portaudio() -> bool:
    """`Pa_Terminate()` + `Pa_Initialize()` — jediné místo, kde se zvuková
    vrstva obnovuje. Blokující; ohraničení si řeší volající.

    Používá to úklid po nahrávání (`Recorder._teardown`) i zotavení po
    selhaném otevření (`Recorder._open_stream`). Dvě kopie by znamenaly, že se
    jedna z nich časem rozejde s druhou — a přitom je to přesně to volání,
    které umí celý proces zaseknout, takže se mu má rozumět z jednoho místa.
    """
    try:
        sd._terminate()
        sd._initialize()
        diag.log("audio", "PortAudio restart OK")
        return True
    except Exception as exc:  # noqa: BLE001
        diag.log("audio", f"PortAudio restart selhal: {exc}")
        return False


def _rms_to_level(rms: float) -> float:
    """RMS (0..1) → hlasitost 0..1 v dB škále, ořezaná do rozsahu."""
    if rms <= 1e-7:
        return 0.0
    db = 20.0 * np.log10(rms)
    return float(min(1.0, max(0.0, (db - _LEVEL_DB_MIN) / (_LEVEL_DB_MAX - _LEVEL_DB_MIN))))


class Recorder:
    """Push-to-talk nahrávání. `start()` otevře stream, `stop()` vrátí audio."""

    def __init__(self, sample_rate: int = SAMPLE_RATE, max_seconds: int = MAX_SECONDS_DEFAULT):
        self.sample_rate = sample_rate
        self.max_frames = max_seconds * sample_rate
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        # [B2] Odděleně od `_lock`: ten bere i audio callback na svém vlákně a
        # nesmí čekat na otevírání zařízení (u Bluetooth i sekundu). `_open_lock`
        # drží jen pořadí start/stop, `_lock` chrání buffer.
        self._open_lock = threading.Lock()
        self._total = 0
        # Dozavřel se předchozí stream ÚPLNĚ (až za `close()`)? Nový `start()` na
        # to čeká, protože dokud starý stream žije, jeho callback pořád píše do
        # `self._frames` — a `start()` je nuluje. Bez brány by do nové nahrávky
        # prosákly vzorky ze staré.
        self._teardown_done = threading.Event()
        self._teardown_done.set()  # na začátku není co dozavírat
        # Vypršelo čekání na dozavření aspoň jednou? Pak se na ně už nečeká
        # znovu — zaseklé nativní volání se samo nerozmyslí a další čekání by
        # jen po tři sekundy předstíralo uživateli, že se nahrává.
        self._teardown_stuck = False

    def _callback(self, indata, frames, time_info, status):  # noqa: ANN001
        # Voláno na audio vlákně — drž triviální.
        with self._lock:
            if self._total < self.max_frames:
                self._frames.append(indata.copy())
                self._total += frames

    def start(self) -> None:
        """Otevře mikrofon. Smí běžet souběžně se `stop()` — viz `_open_lock`.

        Nejdřív ale počká, až se dozavře PŘEDCHOZÍ stream: `sd._terminate()`
        /`_initialize()` přenastavuje PortAudio globálně, takže otevírat nový
        stream, dokud tohle běží, znamená dva thready na sdíleném stavu. A dokud
        starý stream žije, jeho callback pořád zapisuje do `self._frames`.

        Když se nahrávání otevřít nedá, letí ven vždycky `MicrophoneUnavailable`
        — viz její docstring.
        """
        self._await_teardown()
        with self._lock:
            self._frames = []
            self._total = 0
        # [B2] Otevření a přiřazení streamu drží `_open_lock`, který `stop()`
        # taky bere. Bez něj `stop()`, který přijde uprostřed otevírání, uvidí
        # `self._stream` ještě jako None, nic nezavře — a stream, který se
        # dokončí o chvíli později, už nikdo nezastaví: mikrofon zůstane
        # otevřený (oranžová tečka) až do restartu aplikace.
        with self._open_lock:
            stream = self._open_stream()
            with self._lock:
                self._stream = stream

    def _await_teardown(self) -> None:
        """Brána před novým nahráváním: počká na dozavření předchozího streamu.

        Čeká se ale jen JEDNOU. Když čekání vypršelo, visí `_teardown` v
        nativním volání, ze kterého se sám nevrátí — a další stisk, který by na
        něj zase tři sekundy čekal, by uživateli jen ukázal okénko „Nahrávám",
        nic nenahrál a po třech sekundách ho zase schoval. Přesně takhle se to
        v logu projevovalo. Od druhého pokusu se proto selhává hned; okamžitá
        odpověď je zároveň to, co dovolí appce se sama restartovat (dokud stav
        po tři sekundy visel na RECORDING, odpočet klidu se pořád nuloval).
        """
        if self._teardown_done.is_set():
            return
        if self._teardown_stuck:
            raise MicrophoneUnavailable(
                "předchozí nahrávání zůstalo zaseknuté v systému"
            )
        if not self._teardown_done.wait(_REOPEN_BUDGET_S):
            self._teardown_stuck = True
            raise MicrophoneUnavailable(
                f"předchozí nahrávání se nedozavřelo do {_REOPEN_BUDGET_S:.0f} s"
            )

    def _open_stream(self):  # noqa: ANN201 — sd.InputStream
        """Otevře vstupní stream; při selhání JEDNOU oživí PortAudio a zkusí znovu.

        Seznam zařízení si PortAudio drží od `Pa_Initialize()`. Když se mezi
        dvěma diktáty změní vstup (odpojená sluchátka, uspání, cizí appka, co si
        mikrofon vzala), otevírání skončí `paInternalError` — a protože jediné
        místo, kde se zvuková vrstva obnovovala, byl úklid PO nahrávání, který
        se po selhaném otevření nespustí, zůstala appka rozbitá až do ručního
        restartu. Oživení a jeden další pokus tohle spraví, aniž by o tom
        uživatel vůbec věděl.
        """
        try:
            return self._new_stream()
        except Exception as exc:  # noqa: BLE001 — druhý pokus po oživení
            diag.log("audio", f"otevření selhalo ({exc}) → oživuji PortAudio")
            if not self._revive_portaudio():
                raise MicrophoneUnavailable(f"mikrofon nejde otevřít: {exc}") from exc
            try:
                return self._new_stream()
            except Exception as retry_exc:  # noqa: BLE001
                raise MicrophoneUnavailable(
                    f"mikrofon nejde otevřít ani po restartu zvukové vrstvy: {retry_exc}"
                ) from retry_exc

    def _new_stream(self):  # noqa: ANN201 — sd.InputStream
        """Jeden pokus o otevření a rozběhnutí streamu.

        Když selže až `start()`, je zařízení otevřené a nikdo by ho nezavřel
        (`self._stream` se přiřazuje až po návratu) — proto úklid rovnou tady.
        """
        stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        try:
            stream.start()
        except Exception:  # noqa: BLE001 — zařízení nesmí zůstat otevřené
            try:
                stream.close()
            except Exception as exc:  # noqa: BLE001
                diag.log("audio", f"úklid po neúspěšném startu selhal: {exc}")
            raise
        return stream

    def _revive_portaudio(self) -> bool:
        """Oživení zvukové vrstvy na ohraničeném vlákně. True = stihlo se.

        Ohraničení je ze stejného důvodu jako u `_teardown`: `Pa_Terminate()` se
        umí zaseknout a čekat na něj bez limitu znamená, že se appka na místo
        krátké chyby zasekne celá. Zaseklé vlákno tu necháváme dobíhat —
        přerušit ho nejde a druhé pouštět nesmíme.
        """
        done = threading.Event()
        ok: list[bool] = []

        def _run() -> None:
            try:
                if _restart_portaudio():
                    ok.append(True)
            finally:
                done.set()

        threading.Thread(
            target=_run, name="spillway-audio-revive", daemon=True
        ).start()
        if not done.wait(_REVIVE_BUDGET_S):
            diag.log("audio", "oživení PortAudia se nestihlo v limitu")
            return False
        return bool(ok)

    def level(self, window_s: float = 0.12) -> float:
        """Hlasitost posledního krátkého úseku jako 0..1 — pro živý ukazatel v liště.

        Levné: sáhne jen na konec bufferu (~2 tisíce vzorků), nikdy nezřetězí celou
        nahrávku jako `snapshot()`. Hlasitost se počítá jako RMS a převádí na dB,
        protože sluch (a tím i očekávaný pohyb sloupců) je logaritmický — lineární
        RMS by u běžné řeči skoro nevyjel z nuly.
        """
        need = max(1, int(self.sample_rate * window_s))
        with self._lock:
            if not self._frames:
                return 0.0
            tail, got = [], 0
            for arr in reversed(self._frames):
                tail.append(arr)
                got += arr.shape[0]
                if got >= need:
                    break
        buf = np.concatenate(list(reversed(tail)), axis=0).reshape(-1)[-need:]
        if buf.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(np.square(buf, dtype=np.float64))))
        return _rms_to_level(rms)

    def snapshot(self) -> np.ndarray:
        """Zatím nahrané audio jako 1-D float32, BEZ zastavení streamu (pro
        streaming přepis během mluvení). Levné — jen zřetězení dosavadních rámců."""
        with self._lock:
            if not self._frames:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._frames, axis=0).reshape(-1)

    def _teardown(self, stream) -> None:  # noqa: ANN001
        """Skutečné zavření streamu. Běží na vlastním vlákně, ať jde ohraničit.

        Když se to nestihne v limitu, běží tohle vlákno dál — a je to ZÁMĚR:
        zaseklé nativní volání nejde přerušit a druhé vlákno pouštět na tentýž
        stream nesmíme (dva thready v CoreAudiu nad jedním handle, k tomu jeden
        z nich uprostřed globálního `sd._terminate()`). Nikdo další na ten stream
        nesahá, takže se v nejhorším případě jen pozdě dopočítá.
        """
        try:
            for name, op in (("stop", stream.stop), ("close", stream.close)):
                try:
                    op()
                    diag.log("audio", f"{name}() OK")
                except Exception as exc:  # noqa: BLE001
                    diag.log("audio", f"{name}() selhal: {exc}")
            # close() na macOS někdy neuvolní CoreAudio zařízení → oranžový
            # indikátor zůstane svítit. Uvolníme referenci, GC a restart PortAudia.
            # (Pozn.: `sounddevice#140` dokládá, že tenhle restart nechává po sobě
            # systémová vlákna. Necháváme ho — bez něj se vrací svítící indikátor —
            # ale je to důvod navíc, proč se appka po zaseknutí umí restartovat.)
            del stream
            gc.collect()
            _restart_portaudio()
        finally:
            # Pořadí je závazné: příznak zhasnout DŘÍV, než se pustí čekající
            # `start()`. Opožděný úklid, který nakonec doběhl, tím zároveň
            # vrátí bránu do normálu a další diktát se zase chová jako obvykle.
            self._teardown_stuck = False
            self._teardown_done.set()

    def stop(self) -> np.ndarray:
        """Zastaví nahrávání, uvolní mikrofon a vrátí audio jako 1-D float32.

        Nahrané audio se vrátí i tehdy, když se mikrofon nestihne zavřít
        v `_CLOSE_BUDGET_S` — zbytek úklidu doběhne na pozadí. Diktát je totiž
        v tu chvíli už kompletně v paměti (naplnil ho audio callback) a čekat
        s ním na hardware znamenalo zamrznutí celé appky na desítky sekund.
        """
        # Převzetí streamu pod zámkem: `stop()` volá jak pipeline, tak ukončení
        # aplikace. Bez zámku můžou obě větve přečíst tentýž stream dřív, než
        # ho první vynuluje, a zavřít nativní CoreAudio stream dvakrát.
        # `_open_lock` navíc počká, když se zrovna otevírá — jinak by se
        # zavíralo nic a otevřený stream by zůstal viset (B2).
        with self._open_lock:
            with self._lock:
                stream = self._stream
                self._stream = None
        if stream is not None:
            self._teardown_done.clear()
            th = threading.Thread(
                target=self._teardown, args=(stream,),
                name="spillway-audio-teardown", daemon=True,
            )
            th.start()
            if not self._teardown_done.wait(_CLOSE_BUDGET_S):
                print(f"⚠️  mikrofon se nezavřel do {_CLOSE_BUDGET_S:.1f} s "
                      f"— dozavírá se na pozadí, diktát pokračuje")
        with self._lock:
            if not self._frames:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._frames, axis=0).reshape(-1)
