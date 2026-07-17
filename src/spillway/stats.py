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

# Průměrná rychlost psaní na klávesnici. 40 slov/min je běžný odhad pro
# netrénovaného pisatele; konzervativní (spíš podhodnotí úsporu).
TYPING_WPM = 40.0

_MAX_LINES = 5000  # rotace, ať soubor neroste donekonečna


def _words(text: str) -> int:
    return len([w for w in (text or "").split() if w.strip()])


def typing_seconds(text: str) -> float:
    """Odhad, jak dlouho by trvalo text napsat na klávesnici."""
    return _words(text) / TYPING_WPM * 60.0


def record(
    *,
    raw: str,
    final: str,
    app: str | None,
    profile: str,
    audio_seconds: float,
    process_seconds: float,
    cancelled: bool = False,
) -> None:
    """Zapíše jeden diktát do historie. Best-effort — chyby polkne."""
    try:
        entry = {
            "ts": time.time(),
            "app": app or "?",
            "profile": profile,
            "audio_s": round(audio_seconds, 2),
            "process_s": round(process_seconds, 2),
            "words": _words(final),
            "raw_chars": len(raw or ""),
            "out_chars": len(final or ""),
            "typing_s": round(typing_seconds(final), 1),
            "cancelled": cancelled,
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


def summary() -> dict:
    """Agregace pro kartu Statistiky v nastavení."""
    rows = [e for e in _entries() if not e.get("cancelled")]
    if not rows:
        return {
            "count": 0, "words": 0, "saved_s": 0.0, "spoken_s": 0.0,
            "typing_s": 0.0, "prompt_saving_pct": None, "top_apps": [],
        }

    spoken = sum(float(e.get("audio_s", 0)) + float(e.get("process_s", 0)) for e in rows)
    typing = sum(float(e.get("typing_s", 0)) for e in rows)

    # Efektivita promptu: jen profil "ai", kde je cílem zhutnit diktát na prompt.
    ai = [
        e for e in rows
        if e.get("profile") == "ai" and e.get("raw_chars") and e.get("out_chars")
    ]
    pct = None
    if ai:
        raw_total = sum(int(e["raw_chars"]) for e in ai)
        out_total = sum(int(e["out_chars"]) for e in ai)
        if raw_total:
            pct = round((1 - out_total / raw_total) * 100)

    counts: dict[str, int] = {}
    for e in rows:
        counts[e.get("app", "?")] = counts.get(e.get("app", "?"), 0) + 1
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:5]

    return {
        "count": len(rows),
        "words": sum(int(e.get("words", 0)) for e in rows),
        "saved_s": max(0.0, typing - spoken),
        "spoken_s": spoken,
        "typing_s": typing,
        "prompt_saving_pct": pct,
        "top_apps": top,
    }


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
