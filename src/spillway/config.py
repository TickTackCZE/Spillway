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
    return os.environ.get("SPILLWAY_LLM_MODEL") or settings.get("model", "claude-haiku-4-5")


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


def _flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).lower() not in ("0", "false", "no")


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
    Env SPILLWAY_AUTO_UNLOAD_MIN přebíjí; výchozí 10 minut."""
    raw = os.environ.get("SPILLWAY_AUTO_UNLOAD_MIN") or settings.get("auto_unload_min", 10)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 10.0


def get_api_key() -> str | None:
    """Vrátí Anthropic API klíč z Keychain, nebo z env, nebo None."""
    try:
        import keyring

        key = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        if key:
            return key
    except Exception:  # noqa: BLE001 — keyring může selhat (zamčený Keychain apod.)
        pass
    return os.environ.get("ANTHROPIC_API_KEY")
