"""Diagnostický režim — podrobné výpisy do logu, standardně vypnuté.

Za běžného provozu se do logu píše jen jednořádkový souhrn diktátu. Když je
potřeba zjistit, PROČ se diktát zachoval, jak se zachoval (kam se ukotvilo
okénko, co Accessibility hlásila o poli, proč se nezavřel mikrofon), zapne se
diagnostika a přibudou podrobné řádky.

Zapíná se buď v nastavení (`diagnostics`), nebo proměnnou prostředí
`SPILLWAY_DIAG` — ta má přednost, ať jde appku spustit s diagnostikou
jednorázově, bez zásahu do uloženého nastavení:

    SPILLWAY_DIAG=all  open -a Spillway     # všechno
    SPILLWAY_DIAG=focus,hud  ...            # jen vybrané oblasti

Oblasti (`AREAS`) jsou schválně hrubé — jemnější dělení by nutilo hádat, co
zapnout. Dřív měla každá oblast vlastní proměnnou (`SPILLWAY_DEBUG_HUD`,
`SPILLWAY_DEBUG_AUDIO`, `SPILLWAY_DEBUG_TEXT`) a vlastní kopii kódu na jejich
načtení; tenhle modul to nahrazuje jedním místem.

**Pozor na soukromí:** oblast `text` zapíná výpis PŘEPSANÉHO TEXTU do logu.
Standardně se loguje jen délka. Zapínej ji jen na dobu ladění.
"""

from __future__ import annotations

import os

from . import settings

# Oblasti diagnostiky. Krátké názvy schválně — píšou se do proměnné prostředí.
AREAS = (
    "focus",   # co Accessibility hlásí o zaměřeném poli, kam se ukotvilo okénko
    "hud",     # souřadnice plovoucího okénka
    "audio",   # otevírání/zavírání mikrofonu a PortAudia
    "text",    # PŘEPSANÝ TEXT do logu (jinak jen délka) — soukromí!
)

_ENV = "SPILLWAY_DIAG"
_ALL = "all"


def _parse(raw: str | None) -> frozenset[str]:
    """„all" / „focus,hud" / „" → množina zapnutých oblastí."""
    if not raw:
        return frozenset()
    parts = {p.strip().lower() for p in str(raw).replace(";", ",").split(",")}
    parts.discard("")
    if _ALL in parts or "1" in parts or "true" in parts:
        return frozenset(AREAS)
    return frozenset(p for p in parts if p in AREAS)


def active() -> frozenset[str]:
    """Právě zapnuté oblasti. Proměnná prostředí přebíjí uložené nastavení.

    Čte se při každém volání schválně: diagnostika se dá zapnout v nastavení
    za běhu a nemá smysl kvůli tomu restartovat aplikaci.
    """
    if _ENV in os.environ:
        return _parse(os.environ[_ENV])
    try:
        return _parse(settings.get("diagnostics", ""))
    except Exception:  # noqa: BLE001 — diagnostika nikdy nesmí shodit provoz
        return frozenset()


def enabled(area: str) -> bool:
    """Je zapnutá diagnostika téhle oblasti?"""
    return area in active()


def log(area: str, msg: str) -> None:
    """Diagnostický řádek do logu — jen když je oblast zapnutá.

    Prefix `[oblast]` drží řádky rozlišitelné, když je zapnutých víc oblastí.
    """
    if enabled(area):
        print(f"[{area}] {msg}")
