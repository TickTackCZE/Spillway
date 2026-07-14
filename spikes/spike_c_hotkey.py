"""
Spike C — globální hotkey (hold-to-talk) přes CGEventTap.

Cíl (dle plánu §5, rizika R4/R9/R11):
  - vytvořit CGEventTap, který vidí flagsChanged/keyDown/keyUp globálně,
  - implementovat hold-to-talk na modifier-only klávese (default: pravý ⌥),
  - ověřit chování při [R9] pokusu potlačit klávesu macOS diktování a
    [R11] při aktivním Secure Keyboard Entry (tap přestane dostávat eventy),
  - re-enable tapu po `kCGEventTapDisabledByTimeout` (R4).

PŘEDPOKLAD OPRÁVNĚNÍ (TCC):
  Vyžaduje System Settings → Privacy & Security → Input Monitoring pro aplikaci,
  která skript spouští (Terminal / iTerm / VS Code). Pro potlačení eventů
  (SUPPRESS=True) navíc Accessibility.

Použití:
    uv run python spikes/spike_c_hotkey.py

Drž a pusť pravý Option (⌥) → uvidíš START/STOP "nahrávání". Ctrl+C pro konec.

[R9] Test potlačení macOS diktování:
  1) Nech systémové diktování ZAPNUTÉ (System Settings → Keyboard → Dictation),
     zkus jeho klávesu → naskočí diktování i s běžícím spikem? (čekej ANO).
  2) Přepni SUPPRESS_HOTKEY=True níže a zkus znovu → potlačí to tap? (čekej spíš NE).
  3) Závěr: primární cesta = diktování v Nastavení VYPNOUT, ne spoléhat na tap.
"""

import ctypes
import time

from Quartz import (
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFMachPortCreateRunLoopSource,
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventTapCreate,
    CGEventTapEnable,
    CFRunLoopRun,
    kCFRunLoopCommonModes,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskSecondaryFn,
    kCGEventFlagsChanged,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventTapDisabledByTimeout,
    kCGEventTapDisabledByUserInput,
    kCGEventTapOptionDefault,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
)

# --- konfigurace spiku ---------------------------------------------------
RIGHT_OPTION_KEYCODE = 61   # pravý ⌥ (levý = 58)
SUPPRESS_HOTKEY = False     # True = zkusit "spolknout" hotkey event (R9 test)
# ------------------------------------------------------------------------

_recording = False


def is_secure_input_enabled() -> bool:
    """[R11] IsSecureEventInputEnabled() z Carbon/HIToolbox přes ctypes.
    Když je True, tap keyboard eventy vůbec nedostane."""
    try:
        carbon = ctypes.CDLL(
            "/System/Library/Frameworks/Carbon.framework/Carbon"
        )
        carbon.IsSecureEventInputEnabled.restype = ctypes.c_bool
        return bool(carbon.IsSecureEventInputEnabled())
    except Exception as exc:  # noqa: BLE001
        return False


def _tap_callback(proxy, type_, event, refcon):
    global _recording

    # [R4] macOS tap tiše zakáže při pomalém callbacku / user inputu — re-enable.
    if type_ in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
        print("⚠️  Tap zakázán systémem — re-enable.")
        CGEventTapEnable(_tap, True)
        return event

    if type_ == kCGEventFlagsChanged:
        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        flags = CGEventGetFlags(event)
        if keycode == RIGHT_OPTION_KEYCODE:
            pressed = bool(flags & kCGEventFlagMaskAlternate)
            if pressed and not _recording:
                _recording = True
                secure = " [⚠️ SECURE INPUT]" if is_secure_input_enabled() else ""
                print(f"🔴 START nahrávání (drží pravý ⌥){secure}")
            elif not pressed and _recording:
                _recording = False
                print("⬛ STOP nahrávání (puštěno)")
            if SUPPRESS_HOTKEY:
                return None  # [R9] pokus potlačit — u Fn/Globe spíš neúčinné

        # Diagnostika Fn/Globe (klávesa systémového diktování):
        if flags & kCGEventFlagMaskSecondaryFn:
            print("   (Fn/Globe stisknuto — sleduj, zda naskočí systémové diktování)")

    return event


def main() -> None:
    global _tap

    print("── Spike C: hotkey ────────────────────────────")
    print(f"Secure input právě aktivní? {is_secure_input_enabled()}")
    print(f"SUPPRESS_HOTKEY = {SUPPRESS_HOTKEY}")

    mask = (
        CGEventMaskBit(kCGEventKeyDown)
        | CGEventMaskBit(kCGEventKeyUp)
        | CGEventMaskBit(kCGEventFlagsChanged)
    )
    _tap = CGEventTapCreate(
        kCGSessionEventTap,
        kCGHeadInsertEventTap,
        kCGEventTapOptionDefault,
        mask,
        _tap_callback,
        None,
    )
    if _tap is None:
        print(
            "❌ Nepodařilo se vytvořit event tap.\n"
            "   Povol Input Monitoring (a pro SUPPRESS i Accessibility) pro\n"
            "   aplikaci, ze které skript spouštíš: System Settings →\n"
            "   Privacy & Security → Input Monitoring / Accessibility."
        )
        return

    source = CFMachPortCreateRunLoopSource(None, _tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
    CGEventTapEnable(_tap, True)

    print("\n✅ Tap běží. Drž a pusť pravý ⌥. Ctrl+C pro konec.\n")
    try:
        CFRunLoopRun()
    except KeyboardInterrupt:
        print("\nKonec.")


if __name__ == "__main__":
    main()
