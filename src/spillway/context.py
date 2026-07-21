"""Zjištění kontextu — do jaké aplikace se diktuje.

Používá NSWorkspace.frontmostApplication (název + bundle ID), bez oprávnění.
Titulek okna schválně neřešíme (vyžadoval by Screen Recording — viz plán O3).
"""

from __future__ import annotations

from AppKit import NSWorkspace

# Bundle ID → profil formátování.
_PROFILES = {
    # E-mail
    "com.apple.mail": "email",
    "com.microsoft.Outlook": "email",
    "com.readdle.smartemail-Mac": "email",       # Spark
    "com.superhuman.mail": "email",
    "org.mozilla.thunderbird": "email",
    "com.CanaryMail.CanaryMail": "email",
    "com.mimestream.Mimestream": "email",
    # Chat / zprávy
    "com.tinyspeck.slackmacgap": "chat",
    "com.hnc.Discord": "chat",
    "com.apple.MobileSMS": "chat",               # Zprávy
    "net.whatsapp.WhatsApp": "chat",
    "com.microsoft.teams2": "chat",
    "com.microsoft.teams": "chat",
    "ru.keepcoder.Telegram": "chat",
    "org.whispersystems.signal-desktop": "chat",
    "com.facebook.archon.developerID": "chat",   # Messenger
    "us.zoom.xos": "chat",
    # Editory / terminály
    "com.microsoft.VSCode": "code",
    "com.todesktop.230313mzl4w4u92": "code",     # Cursor
    "dev.zed.Zed": "code",
    "com.exafunction.windsurf": "code",
    "com.apple.dt.Xcode": "code",
    "com.apple.Terminal": "code",
    "com.googlecode.iterm2": "code",
    "dev.warp.Warp-Stable": "code",
    "com.mitchellh.ghostty": "code",
    "com.jetbrains.pycharm": "code",
    "com.jetbrains.intellij": "code",
    "com.jetbrains.WebStorm": "code",
    "com.sublimetext.4": "code",
    # AI asistenti
    "com.anthropic.claudefordesktop": "ai",
    "com.openai.chat": "ai",
    "ai.perplexity.mac": "ai",
    # Poznámky a psaní → obecná próza
    "com.apple.Notes": "generic",
    "md.obsidian": "generic",
    "notion.id": "generic",
    "net.shinyfrog.bear": "generic",
    "com.apple.TextEdit": "generic",
    "com.apple.iWork.Pages": "generic",
    "com.linear": "generic",
}
# Pořadí je důležité — "ai" před "chat", ať "gpt"/"claude" nespadne do obecného chatu.
_FALLBACK_KEYWORDS = {
    "ai": ("claude", "chatgpt", "gpt", "perplexity", "gemini"),
    "email": ("mail", "outlook"),
    "chat": ("slack", "discord", "zpráv", "message", "teams", "whatsapp"),
    "code": ("code", "xcode", "terminal", "iterm", "pycharm", "intellij", "antigravity"),
}

# Aplikace, ve kterých je cílem vzdálená/virtuální WINDOWS plocha (RDP/VDI/VM).
# Vkládání v nich musí použít Ctrl+V, ne ⌘+V — klient nepřeloží ⌘ na Ctrl a do
# session dorazí holé „V" (napíše se „v" místo vložení). Viz `paste.paste_text`.
_WINDOWS_TARGET_BUNDLES = {
    "com.microsoft.rdc.macos",       # Windows App (dřív Microsoft Remote Desktop) / AVD
    "com.microsoft.rdc.osx",         # starší Microsoft Remote Desktop
    "com.microsoft.rdc.osx.beta",    # beta kanál
    "com.citrix.receiver.icaviewer.mac",  # Citrix Workspace
    "com.vmware.horizon",            # VMware Horizon Client
    "com.parallels.client",          # Parallels Client (RAS)
    "com.parallels.desktop.console",  # Parallels Desktop (Windows VM)
    "com.vmware.fusion",             # VMware Fusion (Windows VM)
    "org.virtualbox.app.VirtualBoxVM",  # VirtualBox (Windows VM)
    "com.realvnc.vncviewer",         # VNC na Windows
    "com.teamviewer.TeamViewer",     # TeamViewer
    "com.nulana.remotixmac",         # Remotix
}
_WINDOWS_TARGET_KEYWORDS = ("windows app", "remote desktop", "citrix", "horizon", "anydesk")


def is_windows_target(bundle_id: str | None, app_name: str | None = None) -> bool:
    """True, když se diktuje do vzdálené/virtuální WINDOWS plochy (RDP/VDI/VM).

    Spillway běží na macOS, ale cílové pole je na Windows — a tam platí jiná
    klávesová zkratka pro vložení (Ctrl+V). Ověřeno na uživatelově stroji:
    „Windows App" = `com.microsoft.rdc.macos`.
    """
    if bundle_id and bundle_id in _WINDOWS_TARGET_BUNDLES:
        return True
    name = (app_name or "").lower()
    return any(k in name for k in _WINDOWS_TARGET_KEYWORDS)


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


def focused_element():
    """Reference na právě zaměřený AX prvek — schová se při diktování, aby šlo
    text později vložit přesně do NĚJ, i když uživatel mezitím přepnul jinam."""
    try:
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            AXUIElementCreateSystemWide,
            kAXFocusedUIElementAttribute,
        )
    except Exception:  # noqa: BLE001
        return None
    try:
        err, focused = AXUIElementCopyAttributeValue(
            AXUIElementCreateSystemWide(), kAXFocusedUIElementAttribute, None
        )
        return None if err else focused
    except Exception:  # noqa: BLE001
        return None


def insert_text_ax(element, text: str) -> bool:  # noqa: ANN001
    """Zapíše text přímo do prvku přes Accessibility — BEZ fokusu a BEZ schránky.

    Díky tomu může uživatel po nadiktování rovnou dělat něco jiného a text mu
    doputuje tam, kam diktoval. Ověřeno naživo: zápis do TextEditu proběhl,
    zatímco vepředu byl Finder.

    Vrací False, když to pole nepodporuje (typicky web/Electron, kde je AX
    read-only) nebo prvek už neexistuje — volající pak sáhne po schránce.
    """
    if element is None or not text:
        return False
    try:
        from ApplicationServices import (
            AXUIElementSetAttributeValue,
            kAXSelectedTextAttribute,
        )
    except Exception:  # noqa: BLE001
        return False
    try:
        # AXSelectedText vloží na pozici kurzoru (nebo nahradí výběr) — stejná
        # sémantika jako ⌘V, jen bez nutnosti mít pole aktivní.
        return AXUIElementSetAttributeValue(element, kAXSelectedTextAttribute, text) == 0
    except Exception:  # noqa: BLE001
        return False


def needs_leading_space(field_text: str | None, caret: int | None) -> bool:
    """Má se před vkládaný text doplnit mezera, ať slova nesplynou?

    Pravidlo: ano jen tehdy, když kurzor stojí těsně za nemezerovým znakem.
    Konec řádku (i s odsazením) mezeru NEchce — po Enteru začínáme nový řádek.
    """
    if not field_text or caret is None:
        return False
    if caret <= 0 or caret > len(field_text):
        return False
    before = field_text[:caret]
    # Odsazení na novém řádku („\n   ") pořád znamená začátek řádku.
    if before.rstrip(" \t").endswith(("\n", "\r", " ", " ")):
        return False
    return not before[-1].isspace()


def caret_at_line_start() -> bool | None:
    """Stojí kurzor na začátku řádku? True/False, None = nezjistitelné.

    Nutné proto, že rich-text editory (Mail, Outlook) vracejí v AXValue text
    BEZ koncového konce řádku — po „Dobrý den" + Enter tedy z textu vypadá, že
    kurzor stojí za písmenem „n", a `needs_leading_space` by chybně přidala
    mezeru. Číslo řádku + rozsah řádku to poznají správně i tam.
    """
    try:
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            AXUIElementCopyParameterizedAttributeValue,
            AXUIElementCreateSystemWide,
            AXValueGetValue,
            kAXFocusedUIElementAttribute,
            kAXInsertionPointLineNumberAttribute,
            kAXRangeForLineParameterizedAttribute,
            kAXSelectedTextRangeAttribute,
        )
    except Exception:  # noqa: BLE001
        return None
    try:
        from ApplicationServices import kAXValueCFRangeType as cfrange
    except Exception:  # noqa: BLE001
        try:
            from ApplicationServices import kAXValueTypeCFRange as cfrange
        except Exception:  # noqa: BLE001
            cfrange = 4

    def _location(rng_val):
        ok, rng = AXValueGetValue(rng_val, cfrange, None)
        if not ok:
            return None
        loc = getattr(rng, "location", None)
        if loc is None:
            try:
                loc = rng[0]
            except Exception:  # noqa: BLE001
                return None
        return int(loc)

    try:
        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(
            system, kAXFocusedUIElementAttribute, None
        )
        if err or focused is None:
            return None
        err, line = AXUIElementCopyAttributeValue(
            focused, kAXInsertionPointLineNumberAttribute, None
        )
        if err or line is None:
            return None
        err, line_rng = AXUIElementCopyParameterizedAttributeValue(
            focused, kAXRangeForLineParameterizedAttribute, line, None
        )
        if err or line_rng is None:
            return None
        line_start = _location(line_rng)
        err, sel = AXUIElementCopyAttributeValue(
            focused, kAXSelectedTextRangeAttribute, None
        )
        if err or sel is None:
            return None
        caret = _location(sel)
        if line_start is None or caret is None:
            return None
        return caret <= line_start
    except Exception:  # noqa: BLE001
        return None


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
