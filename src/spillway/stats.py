"""Statistiky diktování — „kolik mi to ušetřilo".

Každý dokončený diktát se zapíše jako jeden řádek JSONL do
`~/Library/Application Support/Spillway/history.jsonl`. Formát je schválně
strojově čitelný — je to zároveň podklad pro pozdější export na RPi (viz plán).

Ušetřený čas = odhad, jak dlouho by trvalo text NAPSAT, minus reálný čas
diktování + zpracování. Psaní se počítá přes `TYPING_WPM` (slov za minutu).

**Soukromí:** standardně se ukládá i text diktátu (syrový i upravený) — lokálně
a nešifrovaně. Je to vědomé rozhodnutí (O5 v plánu): bez textů by nešly
„Poslední diktáty" v popoveru. Kdo to nechce, vypne v nastavení „Ukládat texty
diktátů" (`keep_dictation_texts`) — čísla fungují dál, jen se přestane zapisovat
obsah. Zápis je best-effort: chyba nikdy neshodí pipeline.
"""

from __future__ import annotations

import json
import os
import threading
import time

from . import settings

_DIR = os.path.expanduser("~/Library/Application Support/Spillway")
_PATH = os.path.join(_DIR, "history.jsonl")
_lock = threading.Lock()

_MAX_LINES = 5000  # rotace, ať soubor neroste donekonečna


def _words(text: str) -> int:
    return len([w for w in (text or "").split() if w.strip()])


def record(
    *,
    raw: str,
    final: str,
    app: str | None,
    profile: str,
    audio_seconds: float,
    process_seconds: float,
    outcome: str = "pasted",
    domain: str | None = None,
    cost_usd: float = 0.0,
    speech_seconds: float = 0.0,
) -> None:
    """Zapíše jeden diktát do historie. Best-effort — chyby polkne.

    `outcome`: "pasted" (text se vložil) | "cancelled" (Escape) | "empty"
    (prázdný přepis) | "error" (pád pipeline) | "clipboard" (text skončil ve
    schránce, protože nebylo kam vložit). Do statistik se počítají "pasted"
    a "clipboard" — obojí je hotový, použitelný diktát. Prázdné a zrušené
    pokusy ne, nafukovaly by počty a srážely vykázanou úsporu času.

    `app` je jen název aplikace; `domain` (u prohlížeče) se ukládá zvlášť, ať se
    „Chrome (claude.ai)" a „Chrome (gmail.com)" neroztříští v žebříčku aplikací.
    """
    try:
        entry = {
            "ts": time.time(),
            "app": app or "?",
            "domain": domain,
            "profile": profile,
            "audio_s": round(audio_seconds, 2),
            "speech_s": round(float(speech_seconds or 0.0), 2),
            "process_s": round(process_seconds, 2),
            "words": _words(final),
            "raw_chars": len(raw or ""),
            "out_chars": len(final or ""),
            "outcome": outcome,
            "cost_usd": round(float(cost_usd or 0.0), 6),
        }
        # Texty diktátů jsou to nejcitlivější, co aplikace má, a na rozdíl od
        # logu ležely v historii natrvalo a nešifrovaně. Kdo si kupuje Spillway
        # kvůli soukromí, musí mít možnost je neukládat vůbec — čísla (počty,
        # délky, tempo, náklady) fungují i bez nich. Výchozí je ukládat, ať
        # „Poslední diktáty" v nastavení dál k něčemu jsou.
        if _keep_texts():
            entry["raw"] = raw
            entry["final"] = final
        os.makedirs(_DIR, exist_ok=True)
        with _lock:
            with open(_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            _rotate()
    except Exception:  # noqa: BLE001 — statistika nesmí nikdy shodit diktování
        pass


def _rotate() -> None:
    try:
        with open(_PATH, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= _MAX_LINES:
            return
        tmp = _PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(lines[-_MAX_LINES:])
        os.replace(tmp, _PATH)
    except Exception:  # noqa: BLE001
        pass


def _entries() -> list[dict]:
    try:
        with open(_PATH, encoding="utf-8") as f:
            out = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue  # poškozený řádek přeskoč, o statistiku nepřijdeme
            return out
    except FileNotFoundError:
        return []
    except Exception:  # noqa: BLE001
        return []


def _keep_texts() -> bool:
    """Smí se do historie zapisovat text diktátů? (nastavení „Ukládat texty")"""
    try:
        return bool(settings.get("keep_dictation_texts", True))
    except Exception:  # noqa: BLE001 — při pochybnosti radši neukládat
        return False


def record_extra_cost(cost_usd: float, note: str = "") -> None:
    """Zaúčtuje náklad volání, jehož výsledek se zahodil (zrušený diktát).

    Zrušení je okamžité — pipeline na odpověď Clauda nečeká. Request ale už
    odešel a tokeny se provolají, takže se cena dozvíme až o pár sekund později,
    kdy je řádek diktátu dávno zapsaný. Zapíše se proto samostatný záznam, který
    se počítá JEN do nákladů (`outcome` ho drží mimo počty diktátů).
    """
    try:
        usd = round(float(cost_usd or 0.0), 6)
    except (TypeError, ValueError):
        return
    if usd <= 0:
        return
    try:
        os.makedirs(_DIR, exist_ok=True)
        entry = {"ts": time.time(), "outcome": "cost_only", "cost_usd": usd, "note": note}
        with _lock:
            with open(_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            _rotate()
    except Exception:  # noqa: BLE001 — účtování nesmí shodit diktování
        pass


def _counted(entries: list[dict]) -> list[dict]:
    """Jen skutečně vložené diktáty — do statistik se ostatní nepočítají."""
    return [
        e for e in entries
        if e.get("outcome", "cancelled" if e.get("cancelled") else "pasted") in ("pasted", "clipboard")
    ]


def _stats_since() -> float:
    """Časová hranice pro statistiky (reset statistik). Záznamy starší se do čísel
    nepočítají — historie nahrávek (`recent`) se tím ale neřídí, ta je nezávislá."""
    try:
        return float(settings.get("stats_reset_ts", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def summary() -> dict:
    """Agregace pro popover a nastavení.

    Počítá jen hotové diktáty — `outcome` „pasted" nebo „clipboard" (viz
    `_counted`); obojí skončilo použitelným textem. Zrušené, prázdné a spadlé
    pokusy nic nevložily, takže by jen kazily čísla. Starší záznamy (před polem
    `outcome`) se poznají podle `cancelled`.

    Výjimka jsou NÁKLADY: ty se sčítají i z pokusů, které nic nevložily. Zrušený
    diktát mohl stihnout provolat tokeny a ty zaplatíš bez ohledu na to, že se
    výsledek zahodil — vykázat je jako nulu by bylo lhaní do vlastní kapsy.
    """
    since = _stats_since()
    fresh = [e for e in _entries() if float(e.get("ts", 0) or 0) >= since]
    rows = _counted(fresh)
    if not rows:
        return {
            "count": 0, "words": 0, "dictation_s": 0.0, "top_apps": [],
            "tempo_wpm": 0, "cost_month": 0.0, "activity_7d": _empty_activity(),
        }

    # Jen fakta: kolik jsem toho reálně namluvil. „Ušetřený čas" se dřív dopočítával
    # z hádané rychlosti psaní (40 slov/min) — to celé číslo nadhodnocovalo pro
    # rychlé pisatele, tak ho neukazujeme.
    dictation = sum(float(e.get("audio_s", 0)) for e in rows)
    words = sum(int(e.get("words", 0)) for e in rows)

    counts: dict[str, int] = {}
    for e in rows:
        counts[e.get("app", "?")] = counts.get(e.get("app", "?"), 0) + 1
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:5]

    # Průměrné tempo řeči přes všechny (započítané) diktáty = slova / minuty
    # SKUTEČNÉ řeči. Bereme `speech_s` (délka bez ticha/pauz); u starších záznamů
    # bez toho pole padáme zpět na `audio_s`. Jen z diktátů, kde se aspoň chvíli
    # mluvilo — pár desetin sekundy dělá nesmyslné špičky.
    def _speech(e: dict) -> float:
        s = float(e.get("speech_s", 0) or 0)
        return s if s > 0 else float(e.get("audio_s", 0) or 0)

    spoke = [e for e in rows if _speech(e) >= 0.5 and int(e.get("words", 0)) > 0]
    tempo_words = sum(int(e.get("words", 0)) for e in spoke)
    tempo_min = sum(_speech(e) for e in spoke) / 60.0
    tempo_wpm = int(round(tempo_words / tempo_min)) if tempo_min > 0 else 0

    return {
        "count": len(rows),
        "words": words,
        "dictation_s": dictation,
        "top_apps": top,
        "tempo_wpm": tempo_wpm,
        "cost_month": _cost_this_month(fresh),
        "activity_7d": _activity_7d(rows),
    }


_CZ_DAYS = ("po", "út", "st", "čt", "pá", "so", "ne")


def _empty_activity() -> list[dict]:
    import datetime

    today = datetime.date.today()
    days = [today - datetime.timedelta(days=i) for i in range(6, -1, -1)]
    return [{"d": _CZ_DAYS[d.weekday()], "v": 0} for d in days]


def _activity_7d(rows: list[dict]) -> list[dict]:
    """Počet diktátů za posledních 7 dní (nejstarší → dnešek), s popiskem dne."""
    import datetime

    today = datetime.date.today()
    buckets: dict[datetime.date, int] = {}
    for e in rows:
        try:
            d = datetime.date.fromtimestamp(float(e.get("ts", 0)))
        except (ValueError, OSError, OverflowError):
            continue
        buckets[d] = buckets.get(d, 0) + 1
    days = [today - datetime.timedelta(days=i) for i in range(6, -1, -1)]
    return [{"d": _CZ_DAYS[d.weekday()], "v": buckets.get(d, 0)} for d in days]


def _cost_this_month(rows: list[dict]) -> float:
    """Součet nákladů na AI úpravu za aktuální kalendářní měsíc (USD)."""
    import datetime

    now = datetime.datetime.now()
    total = 0.0
    for e in rows:
        try:
            when = datetime.datetime.fromtimestamp(float(e.get("ts", 0)))
        except (ValueError, OSError, OverflowError):
            continue
        if when.year == now.year and when.month == now.month:
            total += float(e.get("cost_usd", 0) or 0)
    return round(total, 4)


def _age_label(ts: float) -> str:
    """Relativní stáří záznamu, česky krátce („2 m", „3 h", „včera", „2 d")."""
    delta = max(0.0, time.time() - float(ts or 0))
    mins = int(delta // 60)
    if mins < 1:
        return "teď"
    if mins < 60:
        return f"{mins} m"
    hours = mins // 60
    if hours < 24:
        return f"{hours} h"
    days = hours // 24
    if days == 1:
        return "včera"
    return f"{days} d"


def recent(limit: int = 10) -> list[dict]:
    """Poslední vložené diktáty pro popover (klik = zkopírovat).

    Vrací od nejnovějšího. `text` je plný výsledek ke zkopírování, `snippet`
    zkrácený náhled do seznamu, `avatar` první písmeno aplikace.
    """
    rows = _counted(_entries())
    out: list[dict] = []
    for e in reversed(rows):
        final = str(e.get("final", "") or "")
        if not final.strip():
            continue
        app = str(e.get("app", "?") or "?")
        snippet = " ".join(final.split())
        if len(snippet) > 64:
            snippet = snippet[:63].rstrip() + "…"
        out.append({
            "app": app,
            "avatar": (app[:1] or "?").upper(),
            "snippet": snippet,
            "text": final,
            "age": _age_label(e.get("ts", 0)),
        })
        if len(out) >= limit:
            break
    return out


def reset_stats() -> None:
    """Vynuluje statistiky (počty, tempo, náklady, aktivita) — nastaví časovou
    hranici, od které se počítá. Uložené texty diktátů (historie) zůstávají."""
    settings.set("stats_reset_ts", time.time())


def clear_recordings() -> None:
    """Smaže uložené TEXTY diktátů (raw i final) z historie → seznam „Historie"
    v popoveru se vyprázdní. Číselné statistiky (words/audio_s/cost) zůstávají,
    počítají se z uložených polí, ne z textu."""
    with _lock:
        try:
            entries = _entries()
        except Exception:  # noqa: BLE001
            return
        if not entries:
            return
        try:
            tmp = _PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for e in entries:
                    e["raw"] = ""
                    e["final"] = ""
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            os.replace(tmp, _PATH)
        except Exception:  # noqa: BLE001 — mazání je best-effort, nesmí shodit UI
            pass


def human_cost(usd: float) -> str:
    """Náklady v USD čitelně („$0,42", „$1,80"). Malé částky nezaokrouhlíme na 0."""
    v = float(usd or 0)
    if v <= 0:
        return "$0,00"
    if v < 0.01:
        return "<$0,01"
    return ("$%.2f" % v).replace(".", ",")
