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

from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskControl,
    kCGHIDEventTap,
)

NSPASTEBOARD_TRANSIENT = "org.nspasteboard.TransientType"
NSPASTEBOARD_CONCEALED = "org.nspasteboard.ConcealedType"
V_KEYCODE = 9  # ANSI pozice "V"

DEFAULT_SETTLE_S = 0.25
# Vzdálená Windows plocha (RDP/VDI): schránka se do session přenáší po síti přes
# rdpclip — potřebuje víc času než lokální vložení, jinak by Ctrl+V vložil ještě
# starý obsah vzdálené schránky.
REMOTE_SETTLE_S = 0.6


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


def _paste_keystroke(windows_target: bool = False) -> None:
    """Pošle ⌘+V (macOS), nebo Ctrl+V při diktování do vzdálené Windows plochy.

    RDP klienti (Windows App / AVD) syntetické ⌘+V NEpřeloží na Ctrl — do session
    dorazí holé „V" a místo vložení se napíše „v". Ctrl+V projde správně.
    """
    flags = kCGEventFlagMaskControl if windows_target else kCGEventFlagMaskCommand
    for pressed in (True, False):
        ev = CGEventCreateKeyboardEvent(None, V_KEYCODE, pressed)
        CGEventSetFlags(ev, flags)
        CGEventPost(kCGHIDEventTap, ev)


def _backup(pb: NSPasteboard):
    """[B13] Záloha VŠECH typů schránky (text, obrázek, soubory) → seznam
    {typ: data}, ať se po vložení dá obnovit i ne-textový obsah."""
    items = pb.pasteboardItems()
    if not items:
        return []
    snapshot = []
    for item in items:
        data = {}
        for t in item.types():
            d = item.dataForType_(t)
            if d is not None:
                data[t] = d
        if data:
            snapshot.append(data)
    return snapshot


def _restore(pb: NSPasteboard, snapshot) -> None:
    pb.clearContents()
    if not snapshot:
        return
    new_items = []
    for data in snapshot:
        item = NSPasteboardItem.alloc().init()
        for t, d in data.items():
            item.setData_forType_(d, t)
        new_items.append(item)
    if new_items:
        pb.writeObjects_(new_items)


def copy_to_clipboard(text: str) -> None:
    """Jen zapsat do schránky, nevkládat. Používá se, když uživatel mezitím
    přepnul do jiné aplikace — text by jinak spadl do cizího pole."""
    if not text:
        return
    _write(NSPasteboard.generalPasteboard(), text, transient=False)


def paste_text(
    text: str,
    *,
    settle_s: float | None = None,
    restore: bool = True,
    windows_target: bool = False,
) -> None:
    """Vloží `text` do právě zaměřeného pole a (volitelně) obnoví schránku
    (vč. ne-textového obsahu). Vyžaduje Accessibility (jinak CGEventPost tiše selže).

    `windows_target=True` (vzdálená Windows plocha přes RDP/VDI) → Ctrl+V místo
    ⌘+V a delší čekání na síťovou synchronizaci schránky.
    """
    if not text:
        return
    if settle_s is None:
        settle_s = DEFAULT_SETTLE_S
    pb = NSPasteboard.generalPasteboard()

    # [F9] U vzdálené plochy schránku NEOBNOVUJEME. rdpclip si obsah stahuje
    # opožděně (delayed rendering) — kdybychom lokální schránku vrátili zpátky
    # dřív, než si ho vzdálená strana vyzvedne, vložil by se do Windows STARÝ
    # text. Tiché a matoucí selhání; ztráta transient obsahu schránky je menší zlo.
    restore = restore and not windows_target
    snapshot = _backup(pb) if restore else []

    change_after_write = _write(pb, text, transient=True)
    if windows_target:
        # Dát rdpclip čas přenést schránku do session, teprve pak Ctrl+V.
        time.sleep(REMOTE_SETTLE_S)
    _paste_keystroke(windows_target=windows_target)
    time.sleep(settle_s)

    # Obnovit jen když schránku mezitím nepřepsal někdo jiný (clipboard manager).
    if restore and pb.changeCount() == change_after_write:
        try:
            _restore(pb, snapshot)
        except Exception:  # noqa: BLE001 — obnova je best-effort, neztroskotat na ní
            pass
