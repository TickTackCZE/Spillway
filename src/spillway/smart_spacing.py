"""Chytrá mezera před vkládaným textem (best-effort přes Accessibility API).

Pokud je textový kurzor hned za nemezerovým znakem, vrátí True → před vkládaný
text se přidá mezera, aby slova nesplynula. Když zaměřené pole nejde inspektovat
(Electron/webová pole, chybí Accessibility oprávnění, apod.), vrátí False a
chování zůstane beze změny.

Vyžaduje Accessibility oprávnění (stejné jako paste).
"""

from __future__ import annotations

# kAXValueCFRangeType má v enumu AXValueType hodnotu 4 (fallback, kdyby konstanta
# nešla naimportovat pod žádným ze známých jmen).
_CFRANGE_TYPE_FALLBACK = 4


def leading_space_needed() -> bool:
    try:
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            AXUIElementCreateSystemWide,
            AXValueGetValue,
            kAXFocusedUIElementAttribute,
            kAXSelectedTextRangeAttribute,
            kAXValueAttribute,
        )
    except Exception:  # noqa: BLE001
        return False

    try:
        from ApplicationServices import kAXValueCFRangeType as cfrange_type
    except Exception:  # noqa: BLE001
        try:
            from ApplicationServices import kAXValueTypeCFRange as cfrange_type
        except Exception:  # noqa: BLE001
            cfrange_type = _CFRANGE_TYPE_FALLBACK

    try:
        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(
            system, kAXFocusedUIElementAttribute, None
        )
        if err or focused is None:
            return False

        err, text = AXUIElementCopyAttributeValue(focused, kAXValueAttribute, None)
        if err or not isinstance(text, str) or not text:
            return False

        err, rng_val = AXUIElementCopyAttributeValue(
            focused, kAXSelectedTextRangeAttribute, None
        )
        if err or rng_val is None:
            return False

        ok, rng = AXValueGetValue(rng_val, cfrange_type, None)
        if not ok:
            return False

        loc = getattr(rng, "location", None)
        if loc is None:
            loc = rng[0]  # CFRange jako tuple (location, length)
        if loc <= 0 or loc > len(text):
            return False

        return not text[loc - 1].isspace()
    except Exception:  # noqa: BLE001
        return False
