"""Ověření opravy přeřeknutí (self-repair) proti reálnému API.

Testuje OBA směry — jinak by „oprava" tiše zahazovala informace:
  • REPAIR  — mluvčí se opravil („teda v 5") → smí zůstat JEN opravená hodnota;
  • KEEP    — skutečná volba („ve 4 nebo v 5") → musí zůstat OBĚ (regrese!);
  • FACTS   — běžný diktát → fakta/čísla se nesmí ztratit.

Potřebuje API klíč (Keychain nebo ANTHROPIC_API_KEY). Spuštění:

    uv run python spikes/check_self_repair.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from spillway import config  # noqa: E402
from spillway.llm import Cleaner  # noqa: E402

# (druh, profil, syrový přepis, musí obsahovat, nesmí obsahovat)
CASES = [
    # --- mluvčí se opravil → nechat jen opravu ---
    ("REPAIR", "chat", "ahoj sejdeme se ve 4 nebo teda v 5 hodin", ["5"], ["4"]),
    ("REPAIR", "chat", "pošli to honzovi vlastně petrovi", ["Petr"], ["Honz"]),
    ("REPAIR", "chat", "bude to v úterý pardon ve středu", ["střed"], ["úter"]),
    ("REPAIR", "chat", "stojí to 200 korun no teda 300 korun", ["300"], ["200"]),
    # --- skutečná volba → nechat obě (tady se to nesmí „opravit" ---
    ("KEEP", "chat", "sejdeme se ve 4 nebo v 5 jak ti to vyjde", ["4", "5"], []),
    ("KEEP", "chat", "přijď v úterý nebo ve středu podle toho jak budeš moct", ["úter", "střed"], []),
    ("KEEP", "chat", "můžeme to poslat honzovi nebo petrovi ať to vidí oba", ["Honz", "Petr"], []),
    # --- běžný diktát → fakta zůstávají ---
    ("FACTS", "chat", "sejdeme se v 5 hodin u kina a vezmi 200 korun", ["5", "200"], []),
    ("FACTS", "email", "schůzka je 15. ledna v 9 30 v zasedačce ve druhém patře",
     ["15", "9", "30"], []),
]


def main() -> int:
    key = config.get_api_key()
    if not key:
        print("❌ Chybí API klíč (Keychain / ANTHROPIC_API_KEY).")
        return 2
    model = config.get_model()
    cleaner = Cleaner(key, model=model)
    print(f"Model: {model}\n")

    failures = 0
    for kind, profile, raw, must, must_not in CASES:
        out = cleaner.clean(raw, app_name="Zprávy", profile=profile)
        low = out.lower()
        missing = [m for m in must if m.lower() not in low]
        present = [m for m in must_not if m.lower() in low]
        ok = not missing and not present
        if not ok:
            failures += 1
        print(f"[{'OK ' if ok else 'FAIL'}] {kind}: {raw}")
        print(f"        → {out!r}")
        if missing:
            print(f"        ⚠️  chybí: {missing}")
        if present:
            print(f"        ⚠️  nemělo zůstat: {present}")
        print()

    total = len(CASES)
    print(f"{'✅' if not failures else '❌'} {total - failures}/{total} prošlo.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
