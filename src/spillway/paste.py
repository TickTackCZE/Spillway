"""Vložení textu do aktivní aplikace přes schránku + Cmd+V.

Ověřeno ve Spike A. Klíčové detaily:
  - Deklarujeme Transient/Concealed pasteboard typy → clipboard manageri
    (Maccy/Raycast) si vložený text neuloží do historie.
  - `changeCount` NEdetekuje dokončení vložení (Cmd+V schránku jen čte), proto
    fixní delay před obnovou původního obsahu.
  - Obnovu provedeme jen, pokud schránku mezitím nezměnil někdo jiný.
"""

from __future__ import annotations

import time

from AppKit import NSPasteboard, NSPasteboardTypeString
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)

NSPASTEBOARD_TRANSIENT = "org.nspasteboard.TransientType"
NSPASTEBOARD_CONCEALED = "org.nspasteboard.ConcealedType"
V_KEYCODE = 9  # ANSI pozice "V"

DEFAULT_SETTLE_S = 0.25


def _write(pb: NSPasteboard, text: str, transient: bool) -> int:
    pb.clearContents()
    types = [NSPasteboardTypeString]
    if transient:
        types += [NSPASTEBOARD_TRANSIENT, NSPASTEBOARD_CONCEALED]
    pb.declareTypes_owner_(types, None)
    pb.setString_forType_(text, NSPasteboardTypeString)
    if transient:
        pb.setString_forType_("", NSPASTEBOARD_TRANSIENT)
    return pb.changeCount()


def _cmd_v() -> None:
    for pressed in (True, False):
        ev = CGEventCreateKeyboardEvent(None, V_KEYCODE, pressed)
        CGEventSetFlags(ev, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, ev)


def paste_text(text: str, *, settle_s: float = DEFAULT_SETTLE_S, restore: bool = True) -> None:
    """Vloží `text` do právě zaměřeného pole a (volitelně) obnoví schránku.

    Vyžaduje Accessibility oprávnění pro proces (jinak CGEventPost tiše selže).
    """
    if not text:
        return
    pb = NSPasteboard.generalPasteboard()
    original = pb.stringForType_(NSPasteboardTypeString)

    change_after_write = _write(pb, text, transient=True)
    _cmd_v()
    time.sleep(settle_s)

    if restore and original is not None and pb.changeCount() == change_after_write:
        _write(pb, original, transient=False)
