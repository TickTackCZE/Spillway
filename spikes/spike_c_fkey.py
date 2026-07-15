"""
Spike C2 — zachycení nativní klávesy F5 (diktování/Siri) pro použití jako hotkey.

Cíl (dle plánu, riziko R9): uživatel chce přebít nativní macOS klávesu F5
(diktování/Siri) a použít ji pro Spillway. Funkční/mediální klávesy ale NEchodí
jako normální keyDown — jdou jako "system-defined" události (NSSystemDefined,
type 14, subtype 8 = aux control buttons). Tenhle spike je zachytí a vypíše,
ať víme:
  1) jaká událost F5 vůbec pošle (a jestli ji tap vidí dřív než systém),
  2) jestli ji lze potlačit (return None), aby nenaskočilo diktování/Siri.

DŮLEŽITÉ: I když F5 zachytíme, macOS může diktování spustit paralelně na nižší
vrstvě. Primární cesta (viz R9) je diktování/Siri na té klávese v Nastavení
VYPNOUT; tento spike ověří, jestli je to nutné, nebo jestli stačí tap.

Oprávnění: Input Monitoring (+ Accessibility pro potlačení). Ctrl+C = konec.

Použití:
    uv run python spikes/spike_c_fkey.py
Pak stiskni F5 (klávesu s mikrofonem / diktováním) a sleduj výpis.
"""

import ctypes

from AppKit import NSEvent
from Quartz import (
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventTapCreate,
    CGEventTapEnable,
    kCFRunLoopCommonModes,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventTapDisabledByTimeout,
    kCGEventTapDisabledByUserInput,
    kCGEventTapOptionDefault,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
)

# --- konfigurace ---------------------------------------------------------
SUPPRESS_F5 = True    # True = spolknout F5 (return None) → test: nenaskočí diktování?
# ------------------------------------------------------------------------

NSSYSTEMDEFINED = 14                 # CGEventType pro NSSystemDefined
NX_SUBTYPE_AUX_CONTROL = 8           # subtype speciálních (mediálních) kláves
F5_STANDARD_KEYCODE = 96             # F5 jako "standardní funkční klávesa" (Fn+F5)
F5_DICTATION_KEYCODE = 176          # F5 diktovací klávesa (zjištěno empiricky na tomto Macu)

_recording = False                   # stav hold-to-talk

# Mapa známých aux keycodů (horní byte data1) pro orientaci ve výpisu.
AUX_KEYS = {
    4: "NX_KEYTYPE_DICTATION?",  # orientační — potvrdí až reálný výpis
    7: "MUTE",
    1: "SOUND_UP",
    2: "SOUND_DOWN",
    3: "BRIGHTNESS_UP",
}


def _callback(proxy, type_, event, refcon):
    if type_ in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
        print("⚠️  Tap zakázán systémem — re-enable.")
        CGEventTapEnable(_tap, True)
        return event

    if type_ in (kCGEventKeyDown, kCGEventKeyUp):
        global _recording
        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        kind = "keyDown" if type_ == kCGEventKeyDown else "keyUp"

        if keycode == F5_DICTATION_KEYCODE:
            # Hold-to-talk na F5: keyDown = START, keyUp = STOP.
            if type_ == kCGEventKeyDown and not _recording:
                _recording = True
                print("🔴 START nahrávání (F5 stisknuta)")
            elif type_ == kCGEventKeyUp and _recording:
                _recording = False
                print("⬛ STOP nahrávání (F5 puštěna)")
            if SUPPRESS_F5:
                # Spolknout F5 → test, jestli tím zabráníme nativnímu diktování/Siri.
                return None
            return event

        note = " ← F5 standardní fn klávesa" if keycode == F5_STANDARD_KEYCODE else ""
        print(f"   · {kind}, keycode={keycode}{note}")
        return event

    if type_ == NSSYSTEMDEFINED:
        try:
            ns = NSEvent.eventWithCGEvent_(event)
            if ns is not None and ns.subtype() == NX_SUBTYPE_AUX_CONTROL:
                data1 = ns.data1()
                aux_keycode = (data1 & 0xFFFF0000) >> 16
                key_state = (data1 & 0x0000FF00) >> 8
                pressed = key_state == 0x0A
                label = AUX_KEYS.get(aux_keycode, "?")
                print(
                    f"   ★ SYSTEM-DEFINED aux klávesa: aux_keycode={aux_keycode} "
                    f"({label}), {'stisk' if pressed else 'puštění'}"
                )
                if SUPPRESS_F5:
                    print("     (SUPPRESS_F5=True → vracím None, sleduj zda naskočí diktování)")
                    return None
        except Exception as exc:  # noqa: BLE001
            print(f"   ! chyba při čtení system-defined události: {exc}")

    return event


def main() -> None:
    global _tap
    print("── Spike C2: F5 / diktovací klávesa ───────────")
    print(f"SUPPRESS_F5 = {SUPPRESS_F5}")

    mask = (
        CGEventMaskBit(kCGEventKeyDown)
        | CGEventMaskBit(kCGEventKeyUp)
        | CGEventMaskBit(NSSYSTEMDEFINED)
    )
    _tap = CGEventTapCreate(
        kCGSessionEventTap,
        kCGHeadInsertEventTap,
        kCGEventTapOptionDefault,
        mask,
        _callback,
        None,
    )
    if _tap is None:
        print("❌ Tap se nevytvořil — povol Input Monitoring (+ Accessibility).")
        return

    source = CFMachPortCreateRunLoopSource(None, _tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
    CGEventTapEnable(_tap, True)

    print("\n✅ Tap běží. Stiskni F5 (klávesu s mikrofonem/diktováním).")
    print("   Vyzkoušej i hlasitost/jas pro srovnání. Ctrl+C = konec.\n")
    try:
        CFRunLoopRun()
    except KeyboardInterrupt:
        print("\nKonec.")


if __name__ == "__main__":
    main()
