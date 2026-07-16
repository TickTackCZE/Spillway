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

# Prohlížeče, u kterých umíme AppleScriptem zjistit URL aktivní karty
# (Automation oprávnění, NE Screen Recording — jednorázový systémový dialog).
_BROWSER_SCRIPTS = {
    "com.apple.Safari": 'tell application "Safari" to get URL of front document',
    "com.google.Chrome": 'tell application "Google Chrome" to get URL of active tab of front window',
    "com.brave.Browser": 'tell application "Brave Browser" to get URL of active tab of front window',
    "com.microsoft.edgemac": 'tell application "Microsoft Edge" to get URL of active tab of front window',
    "company.thebrowser.Browser": 'tell application "Arc" to get URL of active tab of front window',
}
# Doména → profil formátování (jen doména, ne obsah stránky).
_DOMAIN_PROFILES = {
    "mail.google.com": "email", "outlook.office.com": "email",
    "outlook.live.com": "email", "outlook.office365.com": "email",
    "chat.openai.com": "ai", "chatgpt.com": "ai", "claude.ai": "ai",
    "gemini.google.com": "ai", "perplexity.ai": "ai",
    "web.whatsapp.com": "chat", "web.telegram.org": "chat",
    "discord.com": "chat", "slack.com": "chat", "x.com": "chat", "twitter.com": "chat",
}


def frontmost_app() -> tuple[str | None, str | None]:
    """Vrátí (název aplikace, bundle ID) právě aktivní aplikace."""
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return (None, None)
    return (app.localizedName(), app.bundleIdentifier())


def browser_context(bundle_id: str | None) -> tuple[str | None, str | None]:
    """(profil dle domény, doména) aktivní karty podporovaného prohlížeče.

    Přes AppleScript/Automation (NE Screen Recording) — přesnější než titulek
    okna, čte jen URL, ne obsah stránky. Vyžaduje jednorázové schválení
    systémového dialogu „Spillway chce ovládat <prohlížeč>"; bez povolení,
    mimo podporovaný prohlížeč, nebo když appka neběží, vrací (None, None).
    """
    script_src = _BROWSER_SCRIPTS.get(bundle_id or "")
    if not script_src:
        return (None, None)
    # [B10] `osascript` v subprocessu (ne NSAppleScript, který je main-thread-only) —
    # tohle běží na worker vlákně. Timeout, ať se nezasekne na TCC dialogu.
    try:
        import subprocess

        proc = subprocess.run(
            ["osascript", "-e", script_src],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        url = proc.stdout.strip()
        if proc.returncode != 0 or not url:
            return (None, None)
    except Exception:  # noqa: BLE001 (vč. TimeoutExpired)
        return (None, None)

    from urllib.parse import urlparse

    host = (urlparse(url).netloc or "").removeprefix("www.")
    return (_DOMAIN_PROFILES.get(host), host or None)


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

    Ladění: `SPILLWAY_DEBUG_HUD=1` vypíše, na kterém kroku AX selhal (appka
    prostě nemusí `kAXBoundsForRangeParameterizedAttribute` implementovat —
    i u „nativních" appek to není univerzální)."""
    import os

    debug = os.environ.get("SPILLWAY_DEBUG_HUD", "0").lower() not in ("0", "false", "no")

    def _dbg(msg: str) -> None:
        if debug:
            print(f"[caret] {msg}")

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

    def _focused_frame(focused) -> tuple[float, float, float, float] | None:  # noqa: ANN001
        """Fallback: rám (pozice+velikost) fokusovaného pole. Když appka neumí
        přesnou pozici kurzoru (Electron/web), je HUD u pole pořád mnohem lepší
        než u myši. Vracíme jen horní pruh pole (výška omezená), ať HUD sedí
        nahoře nad polem, ne uprostřed velké textarey."""
        try:
            from ApplicationServices import (
                kAXPositionAttribute,
                kAXSizeAttribute,
                kAXValueCGPointType,
                kAXValueCGSizeType,
            )
        except Exception:  # noqa: BLE001
            return None
        try:
            err1, pos_val = AXUIElementCopyAttributeValue(focused, kAXPositionAttribute, None)
            err2, size_val = AXUIElementCopyAttributeValue(focused, kAXSizeAttribute, None)
            if err1 or err2 or pos_val is None or size_val is None:
                _dbg("fallback: pole nevrací pozici/velikost")
                return None
            okp, pt = AXValueGetValue(pos_val, kAXValueCGPointType, None)
            oks, sz = AXValueGetValue(size_val, kAXValueCGSizeType, None)
            if not (okp and oks):
                return None
            fx, fy = float(pt.x), float(pt.y)
            fh = float(sz.height)
            if fh <= 1.0:
                return None
            _dbg(f"fallback rám pole=({fx:.0f},{fy:.0f}, h={fh:.0f}) → HUD nad pole")
            # Předstíráme „kurzor" s malou výškou na horní hraně pole.
            return (fx, fy, 1.0, min(fh, 22.0))
        except Exception as exc:  # noqa: BLE001
            _dbg(f"fallback výjimka: {type(exc).__name__}: {exc}")
            return None

    try:
        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(
            system, kAXFocusedUIElementAttribute, None
        )
        if err or focused is None:
            _dbg(f"žádný focused element (err={err})")
            return None
        err, rng_val = AXUIElementCopyAttributeValue(
            focused, kAXSelectedTextRangeAttribute, None
        )
        if err or rng_val is None:
            _dbg(f"appka nevrací kAXSelectedTextRangeAttribute (err={err}) → zkouším rám pole")
            return _focused_frame(focused)
        err, bounds_val = AXUIElementCopyParameterizedAttributeValue(
            focused, bounds_attr, rng_val, None
        )
        if err or bounds_val is None:
            _dbg(f"appka nepodporuje {bounds_attr} (err={err}) → zkouším rám pole")
            return _focused_frame(focused)
        ok, rect = AXValueGetValue(bounds_val, cgrect_type, None)
        if not ok:
            _dbg("AXValueGetValue selhalo → zkouším rám pole")
            return _focused_frame(focused)
        try:
            x, y = float(rect.origin.x), float(rect.origin.y)
            w, h = float(rect.size.width), float(rect.size.height)
        except Exception:  # noqa: BLE001
            (x, y), (w, h) = rect
            x, y, w, h = float(x), float(y), float(w), float(h)
        # Degenerovaný obdélník (typicky Electron/web vrací (0, výška, 0, 0)) →
        # neplatné; kurzor má vždy nenulovou výšku řádku.
        if h <= 1.0:
            _dbg(f"degenerovaný rect (0,{y},0,0) — appka to jen předstírá → zkouším rám pole")
            return _focused_frame(focused)
        _dbg(f"OK rect=({x:.0f},{y:.0f},{w:.0f},{h:.0f})")
        return (x, y, w, h)
    except Exception as exc:  # noqa: BLE001
        _dbg(f"výjimka: {type(exc).__name__}: {exc}")
        return None
