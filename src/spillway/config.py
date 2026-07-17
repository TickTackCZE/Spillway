"""Konfigurace a přístup k API klíči.

API klíč se čte z macOS Keychain (přes `keyring`, služba "spillway", účet
"anthropic"), s fallbackem na proměnnou prostředí ANTHROPIC_API_KEY. Klíč NIKDY
není v repu ani v config souboru. Nastavení klíče: `python set_api_key.py`.

Ostatní konfigurace (hotkey, model, slovník) přijde v TOML ve fázi F3 — zatím
výchozí hodnoty v kódu.
"""

from __future__ import annotations

import os

from . import settings

KEYRING_SERVICE = "spillway"
KEYRING_ACCOUNT = "anthropic"


def get_model() -> str:
    """Model pro AI úpravu (z nastavení v liště). Env SPILLWAY_LLM_MODEL má přednost."""
    return os.environ.get("SPILLWAY_LLM_MODEL") or settings.get("model", "claude-sonnet-5")


def glossary() -> list[str]:
    """Uživatelský slovník termínů (zůstanou beze změny). [B17] odolné vůči
    špatnému typu v settings.json."""
    g = settings.get("glossary", [])
    if isinstance(g, str):
        return [t.strip() for t in g.split(",") if t.strip()]
    if isinstance(g, list):
        return [str(t) for t in g]
    return []


def get_language() -> str:
    """Primární jazyk diktování (Whisper). Env SPILLWAY_LANGUAGE má přednost."""
    return os.environ.get("SPILLWAY_LANGUAGE") or settings.get("language", "cs")


def get_theme() -> str:
    """Vzhled okna: system | light | dark."""
    return settings.get("theme", "system")


def get_hotkey() -> tuple[int, str]:
    """(keycode, čitelný název) klávesy pro hold-to-talk. [B17] Odolné vůči
    poškozené/špatně typované hodnotě v settings.json — fallback na F5 (176)."""
    try:
        keycode = int(settings.get("hotkey_keycode", 176))
    except (TypeError, ValueError):
        keycode = 176
    label = settings.get("hotkey_label", "F5 (diktování)")
    if not isinstance(label, str):
        label = "F5 (diktování)"
    return (keycode, label)


def get_cancel_hotkey() -> tuple[int, str]:
    """(keycode, název) klávesy, která zruší běžící zpracování diktátu.
    Výchozí Escape (53). [B17] odolné vůči poškozené hodnotě v settings.json."""
    try:
        keycode = int(settings.get("cancel_keycode", 53))
    except (TypeError, ValueError):
        keycode = 53
    label = settings.get("cancel_label", "Escape")
    if not isinstance(label, str):
        label = "Escape"
    return (keycode, label)


def _flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).lower() not in ("0", "false", "no")


def whisper_hotwords() -> bool:
    """Předat slovník i Whisperu jako `hotwords` (bias dekodéru)?

    VÝCHOZÍ VYPNUTO — bias vkládá termíny do promptu dekodéru, takže na
    akusticky nejednoznačném místě může termín „doslechnout", i když nezazněl.
    V přepisu už to nikdo nechytí (porušení B1 na nejnižší vrstvě).

    Pozn.: hlášené vložení „Domovoy" ve skutečnosti NEZPŮSOBIL Whisper — historie
    ukázala, že v raw přepisu termín nebyl a přidal ho až Claude (slovník v
    promptu bral jako téma). Opraveno v `llm.py` orámováním slovníku jako čistě
    pravopisné pomůcky. Hotwords zůstávají vypnuté jako opatrný default: opravu
    zkomolenin zvládá Claude bezpečně (ověřeno „komitnul→commitnul",
    „pool request→pull request") a druhá, riskantnější cesta k témuž není nutná.

    Zapnout: SPILLWAY_WHISPER_HOTWORDS=1.
    """
    return _flag("SPILLWAY_WHISPER_HOTWORDS", "0")


def auto_space() -> bool:
    """Mezera před textem, když kurzor stojí za nemezerovým znakem. Env přebíjí nastavení."""
    if "SPILLWAY_AUTO_SPACE" in os.environ:
        return _flag("SPILLWAY_AUTO_SPACE")
    return bool(settings.get("auto_space", True))


def field_context() -> bool:
    """Posílat Claudeovi existující obsah pole jako kontext (odchází k Anthropic).
    Env SPILLWAY_FIELD_CONTEXT přebíjí nastavení v liště."""
    if "SPILLWAY_FIELD_CONTEXT" in os.environ:
        return _flag("SPILLWAY_FIELD_CONTEXT")
    return bool(settings.get("field_context", True))


def get_auto_unload_minutes() -> float:
    """[R5] Po kolika minutách nečinnosti uvolnit Whisper model z paměti
    (~1,5–2 GB RAM); znovu se lazy-loadne při dalším diktátu (~1,6 s). 0 = nikdy.
    Env SPILLWAY_AUTO_UNLOAD_MIN přebíjí; výchozí 0,25 min (15 s) — nejde na
    0 s (viz plán): krátká pauza mezi větami by pak platila 1,6s reload pokaždé."""
    raw = os.environ.get("SPILLWAY_AUTO_UNLOAD_MIN") or settings.get("auto_unload_min", 0.25)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.25


_UNSET = object()
_api_key_cache = _UNSET  # cache napříč voláními — Keychain se dotážeme JEDNOU za běh appky


def get_api_key() -> str | None:
    """Vrátí Anthropic API klíč z Keychain, nebo z env, nebo None. Výsledek se
    cachuje v paměti procesu — opakovaná volání (settings okno, Controller,
    kontrola stavu) NESMÍ znovu a znovu otravovat Keychain dialogem (ad-hoc
    podpis appky nemá stabilní identitu napříč rebuildy, takže si to macOS
    "nepamatuje" mezi verzemi appky — v jednom běhu se ale ptát stačí jednou)."""
    global _api_key_cache
    if _api_key_cache is not _UNSET:
        return _api_key_cache
    key = None
    try:
        import keyring

        key = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except Exception:  # noqa: BLE001 — keyring může selhat (zamčený Keychain apod.)
        pass
    if not key:
        key = os.environ.get("ANTHROPIC_API_KEY")
    _api_key_cache = key
    return key


def set_api_key_cache(key: str | None) -> None:
    """Nastaví cache přímo (po uložení/smazání klíče v UI) — ať se hned neptá
    Keychain znovu, jen aby potvrdil to, co jsme sami právě zapsali."""
    global _api_key_cache
    _api_key_cache = key
