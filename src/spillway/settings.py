"""Perzistentní nastavení Spillway (mění je menu v liště).

Ukládá se do `~/Library/Application Support/Spillway/settings.json`. API klíč
sem NEpatří — ten je v Keychain (config.py). Prahové/citlivé věci lze přebít env
proměnnými (viz config.py).
"""

from __future__ import annotations

import json
import os
import threading

_DIR = os.path.expanduser("~/Library/Application Support/Spillway")
_PATH = os.path.join(_DIR, "settings.json")
_lock = threading.Lock()

_DEFAULTS: dict = {
    "model": "claude-sonnet-5",
    "field_context": True,
    "auto_space": True,
    "glossary": [],
    "theme": "system",   # system | light | dark
    "language": "cs",    # primární jazyk diktování
    "hotkey_keycode": 176,           # nativní diktovací klávesa (viz keymap.py)
    "hotkey_label": "F5 (diktování)",
    # Zrušení běžícího zpracování (šetří tokeny, když jsem nadiktoval blbost).
    # Potlačí se JEN během zpracování — jinde klávesa funguje normálně.
    "cancel_keycode": 53,            # Escape
    "cancel_label": "Escape",
    # [R5] Uvolnit Whisper model po N SEKUNDÁCH nečinnosti; reload je levný
    # (~1,6 s). 60 s je vědomé rozhodnutí (změřeno na reálném provozu — viz
    # _doc/spillway-rozvoj-a-napady.md): kratší práh sráží model uprostřed
    # aktivní práce. Tenhle údaj je JEDINÝ zdroj pravdy — `config.py` z něj čte.
    "auto_unload_sec": 60,
    "llm_min_seconds": 5.0,          # kratší diktát → jen lokální úprava, bez volání Clauda
    # Diagnostika (viz `diag.py`) — standardně vypnutá, ať log nenaroste a
    # nezapisuje se víc, než je potřeba. "all" nebo výčet: "focus,hud,audio,text".
    # Pozor: "text" zapisuje do logu PŘEPSANÝ TEXT, ne jen jeho délku.
    "diagnostics": "",
    # Ukládat do historie i text diktátů? Vypnutím zůstanou jen čísla (počty,
    # délky, tempo, náklady) — „Poslední diktáty" pak budou prázdné. Viz stats.py.
    "keep_dictation_texts": True,
    # Uvítání po instalaci se ukáže jednou; pak se klíč přepne na True.
    "seen_setup": False,
    # Do kdy (unix čas) neotravovat s chybějícím API klíčem. Klíč je
    # volitelný, takže musí jít umlčet — ale jen dočasně, ne navždy.
    "key_notice_snooze_until": 0,
}


def _migrate(raw: dict) -> dict:
    """Převod starších podob nastavení na aktuální.

    Práh uvolnění modelu se dřív ukládal v minutách (`auto_unload_min`), teď je
    v sekundách — uživatel ho zadává v sekundách, tak ať v nich i leží. Bez
    převodu by se komukoliv s uloženou hodnotou tiše vrátil výchozí práh.
    """
    if "auto_unload_sec" not in raw and "auto_unload_min" in raw:
        try:
            raw["auto_unload_sec"] = int(round(float(raw["auto_unload_min"]) * 60))
        except (TypeError, ValueError):
            pass
    raw.pop("auto_unload_min", None)
    return raw


# Poslední načtená podoba souboru + otisk, podle kterého se pozná změna.
# Bez cache četl `get()` soubor při KAŽDÉM volání — a protože přes něj chodí
# i `diag.log()`, znamenalo to ~13–27 otevření a parsování JSONu za sekundu po
# celou dobu, co svítí okénko (časovač lišty tiká 6,7×/s a na každý tik připadá
# několik diagnostických řádků). Otisk je `os.stat`, tedy zlomek ceny čtení, a
# na rozdíl od časového vypršení nikdy nevrátí zastaralou hodnotu: okno
# nastavení zapisuje a lišta hned čte, takže cache musí být přesná, ne „skoro".
_cache: dict | None = None
_cache_stamp: tuple | None = None


def _stamp() -> tuple | None:
    try:
        st = os.stat(_PATH)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _load() -> dict:
    global _cache, _cache_stamp
    stamp = _stamp()
    if _cache is not None and stamp == _cache_stamp:
        return _cache
    try:
        with open(_PATH, encoding="utf-8") as f:
            data = {**_DEFAULTS, **_migrate(json.load(f))}
    except Exception:  # noqa: BLE001
        data = dict(_DEFAULTS)
    # Otisk se bere až PO čtení: kdyby soubor mezitím někdo přepsal, uloží se
    # otisk staršího obsahu a příští volání načte znovu. Opačné pořadí by
    # naopak označilo nový otisk za platný pro starý obsah.
    _cache, _cache_stamp = data, _stamp() if stamp is not None else None
    return data


def get(key: str, default=None):
    return _load().get(key, _DEFAULTS.get(key, default))


def set(key: str, value) -> None:  # noqa: A003
    with _lock:
        data = _load()
        data[key] = value
        os.makedirs(_DIR, exist_ok=True)
        # [B11] Atomický zápis: do .tmp a os.replace(), ať pád uprostřed zápisu
        # nepoškodí settings.json (poškozený JSON → tiché ztracení všech nastavení).
        tmp = _PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _PATH)
        # Zahodit cache výslovně, ne se spoléhat na změnu otisku: kdyby zápis
        # trefil stejnou nanosekundu i velikost jako předchozí, zůstala by v
        # paměti stará hodnota a nastavení by se navenek „neuložilo".
        global _cache, _cache_stamp
        _cache, _cache_stamp = None, None
