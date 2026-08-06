"""Jedna pravda o tom, jestli je Spillway připravený.

Připravenost („je model?", „stahuje se?", „kolik procent?", „je klíč?") čtou
čtyři místa: okénko u kurzoru, popover, kartička s upozorněním a okno
nastavení. Dokud si ji každé skládalo samo, ukazovala každé něco jiného —
popover „Chybí model", nastavení zároveň „Stahuji 40 %" a kartička nabízela
stažení, které už běželo.

Tenhle modul je pro všechny jediný zdroj. Kdo chce vědět, jak na tom appka je,
zavolá `snapshot()`; kdo stav změní, zavolá `invalidate()`. Rozesílání do oken
má na starosti jedno místo v `tray` — modul sám nic nekreslí.

**Proč cache:** `snapshot()` volá časovač lišty 6,7×/s a je za ním sahání na
disk (`find_local`, a hlavně `size_bytes`, které prochází celou složku modelu).
Bez cache to znamenalo zbytečné čtení disku několikrát za sekundu po celou dobu
běhu. Velikost se proto počítá jen tehdy, když se model objeví nebo zmizí.
"""

from __future__ import annotations

import threading
import time

from . import config, models, settings

_TTL_S = 1.0

_lock = threading.Lock()
_cache: dict | None = None
_cache_at = 0.0
_dirty = True
# Velikost modelu se počítá průchodem složky — drží se, dokud se nezmění, kde
# model leží. Klíč je `where`, protože jiné umístění = jiná velikost.
_size_for: str | None = None
_size_text = ""
_subscribed = False


def invalidate() -> None:
    """Zahodí cache — po stažení, smazání modelu nebo uložení klíče."""
    global _dirty
    with _lock:
        _dirty = True


def _subscribe_once() -> None:
    """Postup stahování musí cache shodit, jinak by procenta zamrzla na 1 s."""
    global _subscribed
    if _subscribed:
        return
    _subscribed = True
    try:
        models.add_download_listener(lambda _st: invalidate())
    except Exception:  # noqa: BLE001 — bez odběru se stav jen obnoví po TTL
        pass


def snapshot() -> dict:
    """Kompletní stav připravenosti. Levné — výsledek se cachuje.

    Klíče (všechna okna kreslí právě z těchhle):
      `ready`       model je k dispozici
      `where`       „složka Spillway" / „cache HuggingFace" / ""
      `size`        velikost na disku, lidsky; "" když model není
      `repo`        odkud se stahuje
      `downloading`, `percent`, `progress_text`, `error`  — průběh stahování
      `has_key`     API klíč je zadaný
      `key_known`   Klíčenka už odpověděla (dokud ne, nemá se na klíč upozorňovat)
      `key_ok`      nemá se na klíč upozorňovat (má ho / odloženo / nevíme)
    """
    global _cache, _cache_at, _dirty, _size_for, _size_text
    _subscribe_once()
    now = time.monotonic()
    with _lock:
        if _cache is not None and not _dirty and now - _cache_at < _TTL_S:
            return _cache

    found = models.find_local()
    where = found[1] if found else ""
    # Průchod složkou jen při změně umístění — viz poznámka nahoře.
    if where != _size_for:
        _size_for = where
        _size_text = models.human_size(models.size_bytes()) if found else ""

    # Klíčenku se ptáme, jen když už odpověděla. `get_api_key()` umí čekat
    # libovolně dlouho (systémový dialog) a tohle běží i z hlavního vlákna.
    key_known = config.api_key_known()
    has_key = bool(config.get_api_key()) if key_known else False
    key_ok = True
    if key_known and not has_key:
        # Chybějící klíč jde umlčet na týden — klíč je volitelný.
        try:
            key_ok = time.time() < float(settings.get("key_notice_snooze_until", 0) or 0)
        except (TypeError, ValueError):
            key_ok = False

    snap = {
        "ready": found is not None,
        "where": where,
        "size": _size_text,
        "repo": models.REPO,
        "has_key": has_key,
        "key_known": key_known,
        "key_ok": key_ok,
        **models.download_state(),
    }
    with _lock:
        _cache, _cache_at, _dirty = snap, now, False
    return snap
