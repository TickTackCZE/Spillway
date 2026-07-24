"""Statistiky diktování — „kolik mi to ušetřilo".

Každý dokončený diktát se zapíše jako jeden řádek JSONL do
`~/Library/Application Support/Spillway/history.jsonl`. Formát je schválně
strojově čitelný — je to zároveň podklad pro pozdější export na RPi (viz plán).

Ušetřený čas = odhad, jak dlouho by trvalo text NAPSAT, minus reálný čas
diktování + zpracování. Psaní se počítá přes `TYPING_WPM` (slov za minutu).

Pozn.: ukládá se i text (raw i upravený) — je to lokálně, nešifrovaně, dle
rozhodnutí O5 v plánu. Zápis je best-effort: chyba nikdy neshodí pipeline.
"""

from __future__ import annotations

import json
import os
import threading
import time

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
) -> None:
    """Zapíše jeden diktát do historie. Best-effort — chyby polkne.

    `outcome`: "pasted" (text se vložil) | "cancelled" (Escape) | "empty"
    (prázdný přepis) | "error" (pád pipeline). Do statistik se počítá jen
    "pasted" — jinak by prázdné a zrušené pokusy nafukovaly počty a srážely
    vykázanou úsporu času.

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
            "process_s": round(process_seconds, 2),
            "words": _words(final),
            "raw_chars": len(raw or ""),
            "out_chars": len(final or ""),
            "outcome": outcome,
            "cost_usd": round(float(cost_usd or 0.0), 6),
            "raw": raw,
            "final": final,
        }
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


def _counted(entries: list[dict]) -> list[dict]:
    """Jen skutečně vložené diktáty — do statistik se ostatní nepočítají."""
    return [
        e for e in entries
        if e.get("outcome", "cancelled" if e.get("cancelled") else "pasted") in ("pasted", "clipboard")
    ]


def summary() -> dict:
    """Agregace pro popover a nastavení.

    Počítá jen skutečně vložené diktáty (`outcome == "pasted"`) — zrušené,
    prázdné a spadlé pokusy nic nevložily, takže by jen kazily čísla.
    Starší záznamy (před polem `outcome`) se poznají podle `cancelled`.
    """
    rows = _counted(_entries())
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

    # Průměrné tempo řeči = slova / minuty mluvení (jen z diktátů, kde jsme
    # mluvili aspoň chvíli — pár desetin sekundy dělá nesmyslné špičky).
    spoke = [e for e in rows if float(e.get("audio_s", 0)) >= 0.5 and int(e.get("words", 0)) > 0]
    tempo_words = sum(int(e.get("words", 0)) for e in spoke)
    tempo_min = sum(float(e.get("audio_s", 0)) for e in spoke) / 60.0
    tempo_wpm = int(round(tempo_words / tempo_min)) if tempo_min > 0 else 0

    return {
        "count": len(rows),
        "words": words,
        "dictation_s": dictation,
        "top_apps": top,
        "tempo_wpm": tempo_wpm,
        "cost_month": _cost_this_month(rows),
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


def human_cost(usd: float) -> str:
    """Náklady v USD čitelně („$0,42", „$1,80"). Malé částky nezaokrouhlíme na 0."""
    v = float(usd or 0)
    if v <= 0:
        return "$0,00"
    if v < 0.01:
        return "<$0,01"
    return ("$%.2f" % v).replace(".", ",")


def human_duration(seconds: float) -> str:
    """Sekundy → čitelně (např. „2 h 14 min", „3 min 20 s")."""
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h} h {m} min"
    if m:
        return f"{m} min {sec} s"
    return f"{sec} s"
