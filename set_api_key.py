"""Uloží Anthropic API klíč do macOS Keychain (služba "spillway").

    uv run python set_api_key.py

Klíč zadáváš ty; skript ho čte skrytě (getpass — nezobrazí se ani v historii
terminálu) a uloží do Keychain. Nikdy se neukládá do repa ani do config souboru.
"""

import getpass
import os
import sys

import keyring

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from spillway.config import KEYRING_ACCOUNT, KEYRING_SERVICE  # noqa: E402


def main() -> None:
    print("Vlož Anthropic API klíč (začíná 'sk-ant-…'). Nezobrazí se.")
    key = getpass.getpass("API klíč: ").strip()
    if not key:
        print("Nic nezadáno — končím.")
        return
    keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, key)
    print("✅ Uloženo do Keychain (služba 'spillway', účet 'anthropic').")


if __name__ == "__main__":
    main()
