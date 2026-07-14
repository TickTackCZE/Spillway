"""
Spike A — ověření nejrizikovější části Spillway: univerzální vložení textu.

Cíl (dle plánu §5, riziko R1):
  - zapsat text do schránky + deklarovat Transient/Concealed typy
    (aby clipboard manageri jako Maccy/Raycast záznam ignorovali),
  - simulovat Cmd+V přes CGEvent,
  - po fixním delay obnovit původní obsah schránky
    (POZOR: `changeCount` NEdetekuje dokončení vložení — Cmd+V schránku jen čte,
     nemění; proto fixní delay, ne pollování).

Kritérium úspěchu: paste OK v ≥ 6/6 běžných polí (Safari, Chrome, VS Code,
Terminal, Slack/Electron, Mail); obnova schránky bez ztráty i s běžícím Maccy;
do password pole se očekává selhání → změřit, jak vypadá.

PŘEDPOKLAD OPRÁVNĚNÍ (TCC):
  CGEventPost vyžaduje, aby aplikace spouštějící tento skript (Terminal / iTerm /
  VS Code) měla povolení System Settings → Privacy & Security → Accessibility.
  Bez toho `CGEventPost` TIŠE nic neudělá — nejčastější "záhadný" fail.

Použití:
    uv run python spikes/spike_a_paste.py ["vlastní text"]

Skript odpočítá pár sekund — během nich klikni do cílového textového pole.
"""

import sys
import time

from AppKit import NSPasteboard, NSPasteboardTypeString
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)

# Marker typy, které respektují clipboard manageri (Maccy, Raycast, …):
# přítomnost těchto typů = "tohle si neukládej do historie".
NSPASTEBOARD_TRANSIENT = "org.nspasteboard.TransientType"
NSPASTEBOARD_CONCEALED = "org.nspasteboard.ConcealedType"

V_KEYCODE = 9  # ANSI pozice klávesy "V" (poziční keycode, nezávislé na rozložení)

DEFAULT_TEXT = "Příliš žluťoučký kůň — commitnul jsem to do repository. 🐎"
FOCUS_COUNTDOWN_S = 4.0   # čas na kliknutí do cílového pole
PASTE_SETTLE_S = 0.25     # fixní delay před obnovou schránky (viz R1)


def get_clipboard_string(pb: NSPasteboard):
    """Vrátí textový obsah schránky, nebo None (např. když je tam obrázek)."""
    return pb.stringForType_(NSPasteboardTypeString)


def set_clipboard_text(pb: NSPasteboard, text: str, transient: bool = True) -> int:
    """Zapíše text do schránky. Vrací changeCount po zápisu."""
    pb.clearContents()
    types = [NSPasteboardTypeString]
    if transient:
        types += [NSPASTEBOARD_TRANSIENT, NSPASTEBOARD_CONCEALED]
    pb.declareTypes_owner_(types, None)
    pb.setString_forType_(text, NSPasteboardTypeString)
    if transient:
        # Marker typy stačí deklarovat s prázdnou hodnotou.
        pb.setString_forType_("", NSPASTEBOARD_TRANSIENT)
    return pb.changeCount()


def send_cmd_v() -> None:
    """Simuluje stisk Cmd+V. Flags musí být i na key-up, jinak některé
    aplikace vidí "V" bez modifikátoru."""
    down = CGEventCreateKeyboardEvent(None, V_KEYCODE, True)
    CGEventSetFlags(down, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, down)

    up = CGEventCreateKeyboardEvent(None, V_KEYCODE, False)
    CGEventSetFlags(up, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, up)


def main() -> None:
    text = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEXT
    pb = NSPasteboard.generalPasteboard()

    original = get_clipboard_string(pb)
    print("── Spike A: paste ─────────────────────────────")
    print(f"Původní schránka: {original!r}")
    print(f"Vkládám text:     {text!r}")
    print(f"\n>>> Máš {FOCUS_COUNTDOWN_S:.0f} s — klikni do cílového textového pole…")
    for remaining in range(int(FOCUS_COUNTDOWN_S), 0, -1):
        print(f"    {remaining}…", end="", flush=True)
        time.sleep(1)
    print(" TEĎ")

    change_after_write = set_clipboard_text(pb, text, transient=True)
    send_cmd_v()
    time.sleep(PASTE_SETTLE_S)

    # Obnova: jen pokud schránku mezitím nepřepsal někdo jiný (clipboard manager).
    change_now = pb.changeCount()
    if change_now != change_after_write:
        print(f"\n⚠️  Schránku mezitím změnil jiný proces "
              f"(changeCount {change_after_write} → {change_now}) — "
              f"neobnovuji, ať nepřepíšu cizí zápis.")
    elif original is not None:
        set_clipboard_text(pb, original, transient=False)
        print("\n✅ Původní obsah schránky obnoven.")
    else:
        print("\nℹ️  Původní schránka nebyla text (nebo prázdná) — neobnovuji.")

    print("\nZkontroluj cílové pole: vložil se text správně a s diakritikou?")
    print("Zopakuj v každé z 6 cílových aplikací + password poli (očekáván fail).")


if __name__ == "__main__":
    main()
