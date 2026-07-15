"""Konfigurace a přístup k API klíči.

API klíč se čte z macOS Keychain (přes `keyring`, služba "spillway", účet
"anthropic"), s fallbackem na proměnnou prostředí ANTHROPIC_API_KEY. Klíč NIKDY
není v repu ani v config souboru. Nastavení klíče: `python set_api_key.py`.

Ostatní konfigurace (hotkey, model, slovník) přijde v TOML ve fázi F3 — zatím
výchozí hodnoty v kódu.
"""

from __future__ import annotations

import os

KEYRING_SERVICE = "spillway"
KEYRING_ACCOUNT = "anthropic"


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
