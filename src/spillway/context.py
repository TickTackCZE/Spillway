"""Zjištění kontextu — do jaké aplikace se diktuje.

Používá NSWorkspace.frontmostApplication (název + bundle ID), bez oprávnění.
Titulek okna schválně neřešíme (vyžadoval by Screen Recording — viz plán O3).
"""

from __future__ import annotations

from AppKit import NSWorkspace

# Bundle ID → profil formátování.
_PROFILES = {
    "com.apple.mail": "email",
    "com.microsoft.Outlook": "email",
    "com.readdle.smartemail-Mac": "email",
    "com.tinyspeck.slackmacgap": "chat",
    "com.hnc.Discord": "chat",
    "com.apple.MobileSMS": "chat",  # Zprávy
    "net.whatsapp.WhatsApp": "chat",
    "com.microsoft.teams2": "chat",
    "com.microsoft.VSCode": "code",
    "com.apple.dt.Xcode": "code",
    "com.apple.Terminal": "code",
    "com.googlecode.iterm2": "code",
    "com.jetbrains.pycharm": "code",
    "com.anthropic.claudefordesktop": "ai",
    "com.openai.chat": "ai",
}
# Pořadí je důležité — "ai" před "chat", ať "gpt"/"claude" nespadne do obecného chatu.
_FALLBACK_KEYWORDS = {
    "ai": ("claude", "chatgpt", "gpt", "perplexity", "gemini"),
    "email": ("mail", "outlook"),
    "chat": ("slack", "discord", "zpráv", "message", "teams", "whatsapp"),
    "code": ("code", "xcode", "terminal", "iterm", "pycharm", "intellij", "antigravity"),
}


def frontmost_app() -> tuple[str | None, str | None]:
    """Vrátí (název aplikace, bundle ID) právě aktivní aplikace."""
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return (None, None)
    return (app.localizedName(), app.bundleIdentifier())


def app_profile(bundle_id: str | None, app_name: str | None = None) -> str:
    """Profil formátování pro cílovou aplikaci: email / chat / code / generic."""
    if bundle_id and bundle_id in _PROFILES:
        return _PROFILES[bundle_id]
    name = (app_name or "").lower()
    for profile, keywords in _FALLBACK_KEYWORDS.items():
        if any(k in name for k in keywords):
            return profile
    return "generic"


def focused_field() -> tuple[str | None, int | None]:
    """(existující text zaměřeného pole, pozice kurzoru) přes Accessibility.

    Vrátí (None, None), když pole nejde inspektovat (Electron/web, chybí
    oprávnění). Prázdné pole vrací ("", caret). Čtení je lokální — nic neodesílá.
    """
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
        return (None, None)
    try:
        from ApplicationServices import kAXValueCFRangeType as cfrange
    except Exception:  # noqa: BLE001
        try:
            from ApplicationServices import kAXValueTypeCFRange as cfrange
        except Exception:  # noqa: BLE001
            cfrange = 4

    try:
        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(
            system, kAXFocusedUIElementAttribute, None
        )
        if err or focused is None:
            return (None, None)
        err, text = AXUIElementCopyAttributeValue(focused, kAXValueAttribute, None)
        if err or not isinstance(text, str):
            return (None, None)

        caret: int | None = None
        err, rng_val = AXUIElementCopyAttributeValue(
            focused, kAXSelectedTextRangeAttribute, None
        )
        if not err and rng_val is not None:
            ok, rng = AXValueGetValue(rng_val, cfrange, None)
            if ok:
                caret = getattr(rng, "location", None)
                if caret is None:
                    try:
                        caret = rng[0]
                    except Exception:  # noqa: BLE001
                        caret = None
        return (text, caret)
    except Exception:  # noqa: BLE001
        return (None, None)


def caret_screen_rect() -> tuple[float, float, float, float] | None:
    """Obdélník textového kurzoru na obrazovce (x, y, w, h) v AX souřadnicích
    (počátek vlevo NAHOŘE, y roste dolů). None, když to appka nepodporuje.
    """
    try:
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            AXUIElementCopyParameterizedAttributeValue,
            AXUIElementCreateSystemWide,
            AXValueGetValue,
            kAXFocusedUIElementAttribute,
            kAXSelectedTextRangeAttribute,
        )
    except Exception:  # noqa: BLE001
        return None
    try:
        from ApplicationServices import (
            kAXBoundsForRangeParameterizedAttribute as bounds_attr,
        )
    except Exception:  # noqa: BLE001
        bounds_attr = "AXBoundsForRange"
    try:
        from ApplicationServices import kAXValueCGRectType as cgrect_type
    except Exception:  # noqa: BLE001
        try:
            from ApplicationServices import kAXValueTypeCGRect as cgrect_type
        except Exception:  # noqa: BLE001
            cgrect_type = 3

    try:
        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(
            system, kAXFocusedUIElementAttribute, None
        )
        if err or focused is None:
            return None
        err, rng_val = AXUIElementCopyAttributeValue(
            focused, kAXSelectedTextRangeAttribute, None
        )
        if err or rng_val is None:
            return None
        err, bounds_val = AXUIElementCopyParameterizedAttributeValue(
            focused, bounds_attr, rng_val, None
        )
        if err or bounds_val is None:
            return None
        ok, rect = AXValueGetValue(bounds_val, cgrect_type, None)
        if not ok:
            return None
        try:
            x, y = float(rect.origin.x), float(rect.origin.y)
            w, h = float(rect.size.width), float(rect.size.height)
        except Exception:  # noqa: BLE001
            (x, y), (w, h) = rect
            x, y, w, h = float(x), float(y), float(w), float(h)
        # Degenerovaný obdélník (typicky Electron/web vrací (0, výška, 0, 0)) →
        # neplatné; kurzor má vždy nenulovou výšku řádku.
        if h <= 1.0:
            return None
        return (x, y, w, h)
    except Exception:  # noqa: BLE001
        return None
