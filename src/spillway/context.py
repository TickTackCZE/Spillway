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
}
_FALLBACK_KEYWORDS = {
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
