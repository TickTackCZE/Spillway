"""Predikce měsíčního spendu Claude API pro Spillway.

Odhad podle typických token counts na jeden diktát. Bez prompt cachingu —
systémový prompt (~600 tokenů) je pod minimem cachovatelného prefixu (Haiku 4096).

Spuštění:  uv run python spikes/spend_estimate.py
"""

from __future__ import annotations

# Ceny $ za 1M tokenů (in, out) — dle claude-api skillu.
PRICES = {
    "Haiku 4.5":        (1.0, 5.0),
    "Sonnet 5 (intro)": (2.0, 10.0),   # zaváděcí do 31.8.2026
    "Sonnet 5 (std)":   (3.0, 15.0),
}

# Odhad tokenů na jeden diktát.
SYSTEM_TOKENS = 600          # systémový prompt + profil (čeština tokenizuje hůř)
TRANSCRIPT_IN = 100          # ~15 s řeči
OUTPUT_TOKENS = 130          # upravený text
FIELD_CONTEXT_IN = 1200      # e-mail: obsah pole (cap 3000 znaků) jako kontext

DAILY = [20, 50, 100, 200]   # počet diktátů denně
DAYS = 30


def per_dictation(prices, with_context: bool) -> float:
    pin, pout = prices
    tok_in = SYSTEM_TOKENS + TRANSCRIPT_IN + (FIELD_CONTEXT_IN if with_context else 0)
    return (tok_in * pin + OUTPUT_TOKENS * pout) / 1_000_000


def main() -> None:
    for with_ctx in (False, True):
        label = "S kontextem pole (e-mail)" if with_ctx else "Bez kontextu pole"
        print(f"\n### {label}")
        head = "diktátů/den".ljust(14) + "".join(m.ljust(20) for m in PRICES)
        print(head)
        print("-" * len(head))
        for d in DAILY:
            row = f"{d}/den".ljust(14)
            for model, prices in PRICES.items():
                monthly = per_dictation(prices, with_ctx) * d * DAYS
                row += f"${monthly:,.2f}/měs".ljust(20)
            print(row)

    print("\nPozn.: 1 diktát ≈", SYSTEM_TOKENS + TRANSCRIPT_IN, "vstupních +",
          OUTPUT_TOKENS, "výstupních tokenů (bez kontextu).")
    print("Whisper běží lokálně = 0 $. Pro srovnání Wispr Flow Pro ~$12–15/měs.")


if __name__ == "__main__":
    main()
