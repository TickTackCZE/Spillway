"""Ukázka formátování — vezme vzorové „syrové přepisy" a pro každý profil
(email / chat-SMS / ai / code / generic) je prožene Claudem a vypíše před→po.

Potřebuje API klíč (Keychain nebo ANTHROPIC_API_KEY). Model se bere z nastavení
(nebo SPILLWAY_LLM_MODEL). Spuštění:

    uv run python spikes/demo_formatting.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from spillway import config  # noqa: E402
from spillway.llm import Cleaner  # noqa: E402

# (popis, profil, syrový přepis z Whisperu, volitelně obsah pole)
SAMPLES = [
    (
        "E-mail kolegovi",
        "email",
        "ahoj tak jsem se koukal na ten report a myslím si že ta čísla za třetí "
        "kvartál nesedí prostě musíme to projít eště jednou než to pošleme klientovi "
        "dej mi vědět kdy máš čas",
        None,
    ),
    (
        "E-mail — navázání na rozepsaný text v poli",
        "email",
        "díky za info zítra dopoledne se mi to hodí",
        "Dobrý den pane Nováku,\n\nděkuji za Vaši nabídku. Rád bych se sešel osobně.",
    ),
    (
        "SMS / chat",
        "chat",
        "hele ta schůzka co jsme měli ve tři se ruší prej to přesouvaj na zejtra ráno",
        None,
    ),
    (
        "Prompt do AI (Claude/ChatGPT)",
        "ai",
        "potřeboval bych napsat funkci v pythonu co vezme seznam čísel a vrátí "
        "průměr ale musí to ošetřit prázdnej seznam a taky ať to má typový anotace",
        None,
    ),
    (
        "Poznámka / editor",
        "code",
        "todo eště dodělat validaci vstupu a přidat test na ten edge case s prázdným "
        "polem commitnul jsem zatím jenom tu základní verzi",
        None,
    ),
    (
        "Hlasový metapokyn (B: „toto je e-mail, formálně")",
        "generic",
        "toto bude formální email napiš doktorko potřebuju přeobjednat termín z pátku "
        "na příští týden děkuju",
        None,
    ),
]


def main() -> None:
    key = config.get_api_key()
    if not key:
        print("Chybí API klíč (Keychain / ANTHROPIC_API_KEY). Nastav ho v aplikaci.")
        return
    model = config.get_model()
    cleaner = Cleaner(key, model=model)
    print(f"Model: {model}\n" + "=" * 70)

    for desc, profile, raw, field in SAMPLES:
        print(f"\n### {desc}   (profil: {profile})")
        if field:
            print(f"[v poli už je]: {field!r}")
        print(f"[ZE-WHISPERU]:  {raw}")
        try:
            out = cleaner.clean(raw, profile=profile, before_text=field)
            print(f"[PO ÚPRAVĚ]:\n{out}")
        except Exception as exc:  # noqa: BLE001
            print(f"  chyba: {exc}")
        print("-" * 70)


if __name__ == "__main__":
    main()
