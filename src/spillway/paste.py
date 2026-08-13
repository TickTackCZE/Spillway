"""Vložení textu do aktivní aplikace přes schránku + Cmd+V.

Ověřeno ve Spike A. Klíčové detaily:
  - Deklarujeme Transient/Concealed pasteboard typy → clipboard manageri
    (Maccy/Raycast) si vložený text neuloží do historie.
  - `changeCount` NEdetekuje dokončení vložení (Cmd+V schránku jen čte), proto
    fixní delay před obnovou původního obsahu.
  - Obnovu provedeme jen, pokud schránku mezitím nezměnil někdo jiný.
"""

from __future__ import annotations

import re
import time

from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventKeyboardSetUnicodeString,
    CGEventPost,
    CGEventSetFlags,
    CGEventSetIntegerValueField,
    kCGEventFlagMaskCommand,
    kCGEventSourceUserData,
    kCGHIDEventTap,
)

# Podpis vlastních syntetických kláves. Náš event tap odchytává i to, co Spillway
# sám pošle — bez téhle značky by si vlastní ⌘V spletl s tím, že uživatel vložil
# text ručně (a předčasně schoval lístek „Připraveno k vložení").
SPILLWAY_EVENT_MARK = 0x59A11

NSPASTEBOARD_TRANSIENT = "org.nspasteboard.TransientType"
NSPASTEBOARD_CONCEALED = "org.nspasteboard.ConcealedType"
V_KEYCODE = 9  # ANSI pozice "V"

DEFAULT_SETTLE_S = 0.25
# Vzdálená Windows plocha (RDP/AVD): text se „naťuká" po chunkech (viz _type_unicode).
_TYPE_CHUNK = 20
_TYPE_CHUNK_DELAY_S = 0.012
# Cokoli, co by v RDP session mohlo dorazit jako Enter/nový odstavec —
# i s okolními mezerami/odsazením — → JEDNA mezera. Nestačí holé „\n": první
# verze pouštěla beze změny samotné „\r" (bez „\n"), a stejně tak by prošlo
# U+2028/U+2029 (Unicode line/paragraph separator) a U+000B/U+000C (vertical/
# form feed) — znaky, které textové kontroly běžně čtou jako zalomení.
# Escapy schválně \uXXXX, ne literální znaky — ty se ve zdroji špatně
# rozeznají a editor/git je umí neviditelně poškodit.
_LINEBREAK_CHARS = "\r\n\x0b\x0c\u2028\u2029"
_NEWLINE_RE = re.compile(rf"[ \t]*[{_LINEBREAK_CHARS}]+[ \t]*")


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


def _paste_keystroke() -> None:
    """Pošle ⌘+V do aktivní nativní macOS aplikace."""
    for pressed in (True, False):
        ev = CGEventCreateKeyboardEvent(None, V_KEYCODE, pressed)
        CGEventSetFlags(ev, kCGEventFlagMaskCommand)
        CGEventSetIntegerValueField(ev, kCGEventSourceUserData, SPILLWAY_EVENT_MARK)
        CGEventPost(kCGHIDEventTap, ev)


def _type_unicode(text: str) -> None:
    """Vloží text „naťukáním" — jako sled znakových událostí, ne přes schránku.

    Pro vzdálenou Windows plochu (RDP/AVD): schránka + ⌘/Ctrl+V tam nefunguje
    (klient zahazuje modifikátory ze syntetických událostí). Vkládáme proto text
    přímo přes CGEventKeyboardSetUnicodeString — bez modifikátorů, bez schránky,
    nezávisle na rozložení. Řetězec nasazujeme na down i up (kanonický vzor).

    POZOR: funguje jen když má „Windows App" nastavený Keyboard Mode = **Unicode**
    (Connections → Keyboard Mode). Ve „Scancode" režimu klient unicode řetězec
    ignoruje a použije virtuální keycode události (0 = „a") → napsalo by se „aaa".

    [B-AVD1] Zalomení řádku uvnitř textu (`\\n` a příbuzné — viz `_NEWLINE_RE`)
    se nahrazují mezerou. Ze session není vidět, jaká appka je uvnitř zaměřená
    (proto se ani nedá rozhodnout podle appky) — a zalomení v ní typicky
    projede jako SKUTEČNÝ Enter, ne jako nový řádek. U chatovacích appek
    (Teams…) to zprávu rovnou odešle uprostřed ťukání. Dřív se to hlídalo jen
    u oddělovače PŘED textem (`context.leading_separator`, `allow_newline`),
    ale ne uvnitř samotného těla — a to AI úprava (`llm.py`) běžně formátuje
    do odstavců/odrážek se skutečnými zalomeními. Tohle je jediné místo, kudy
    text do AVD vůbec chodí, takže se hlídá tady, univerzálně.

    NEOVĚŘENO na živé RDP session, jestli je `\\n` opravdu příčinou odesílání —
    diagnóza vychází ze čtení kódu (žádná jiná cesta v appce neposílá klávesu
    Enter) a z jediného dochovaného záznamu v historii se zalomeními. Proto se
    do logu píše, KOLIK zalomení se odstranilo — bez toho není jak z historie
    poznat, že se do session naťukalo něco jiného, než co se opravdu řeklo.
    """
    flattened = _NEWLINE_RE.sub(" ", text)
    if flattened != text:
        n = len(_NEWLINE_RE.findall(text))
        print(f"⌨️  AVD: {n}× zalomení nahrazeno mezerou (Enter by odeslal/potvrdil)")
    text = flattened
    for i in range(0, len(text), _TYPE_CHUNK):
        part = text[i:i + _TYPE_CHUNK]
        for pressed in (True, False):
            ev = CGEventCreateKeyboardEvent(None, 0, pressed)
            CGEventKeyboardSetUnicodeString(ev, len(part), part)
            CGEventPost(kCGHIDEventTap, ev)
        time.sleep(_TYPE_CHUNK_DELAY_S)


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

    `windows_target=True` (vzdálená Windows plocha přes RDP/AVD) → text se do session
    „naťuká" znak po znaku (viz _type_unicode), protože schránka + ⌘/Ctrl+V tam
    nefunguje spolehlivě (klient přeposílá jen znaky, ne modifikátory). Nesahá na
    schránku, takže se neobnovuje.
    """
    if not text:
        return
    if windows_target:
        _type_unicode(text)
        return
    if settle_s is None:
        settle_s = DEFAULT_SETTLE_S
    pb = NSPasteboard.generalPasteboard()

    snapshot = _backup(pb) if restore else []
    change_after_write = _write(pb, text, transient=True)
    _paste_keystroke()
    time.sleep(settle_s)

    # Obnovit jen když schránku mezitím nepřepsal někdo jiný (clipboard manager).
    if restore and pb.changeCount() == change_after_write:
        try:
            _restore(pb, snapshot)
        except Exception:  # noqa: BLE001 — obnova je best-effort, neztroskotat na ní
            pass
