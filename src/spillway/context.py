"""Zjištění kontextu — do jaké aplikace se diktuje.

Používá NSWorkspace.frontmostApplication (název + bundle ID), bez oprávnění.
Titulek okna schválně neřešíme (vyžadoval by Screen Recording — viz plán O3).
"""

from __future__ import annotations

from typing import NamedTuple

from AppKit import NSWorkspace

from . import diag

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


def same_field(before: tuple | None, now: tuple | None, tol: int = 8) -> bool | None:
    """Je zaměřené pole pořád to samé jako při diktování?

    Porovnává „otisky" z `focus_snapshot(want_sig=True).sig`, tedy
    (role, x, y, šířka, výška). Obsah pole k tomu schválně nepoužíváme — ten
    se legitimně mění tím, jak uživatel píše.

    True = ano, False = jiné pole, None = nelze rozhodnout (otisk chybí — typicky
    web/Electron). `tol` je tolerance v bodech na drobné posuny (scroll o pár pixelů,
    rozrůstající se textarea), ať se nehlásí změna, když se jen posunul layout.
    """
    if before is None or now is None:
        return None
    if before[0] != now[0]:      # jiná role prvku (textové pole vs. tlačítko…)
        return False
    # Pozice rozliší i dvě prázdná pole; velikost schválně neporovnáváme přísně,
    # protože textarea se při psaní legitimně roztahuje.
    return abs(before[1] - now[1]) <= tol and abs(before[2] - now[2]) <= tol


# Role, které JSOU textový vstup. `AXComboBox`/`AXSearchField` taky — dá se do
# nich psát, takže vložení dává smysl.
_TEXT_ROLES = frozenset(
    {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField"}
)
def is_text_input(value_settable: bool, role: str | None) -> bool:
    """Jádro rozhodnutí „dá se do toho psát?".

    **Rozhoduje editovatelnost** — jde prvku nastavit `AXValue`. Ani role, ani
    přítomnost výběru textu na to nestačí:

    - podle *role* to nejde, protože plocha Finderu, rám okna i webový editor
      se běžně hlásí stejně (`AXGroup`, `AXScrollArea`);
    - podle *výběru textu* to nejde, protože Chromium hlásí `AXSelectedTextRange`
      i pro celou stránku, na které žádné pole zaměřené není — a `AXBoundsForRange`
      pak vrátí začátek dokumentu, tedy levý horní roh okna.

    Role zůstává jako doplněk pro vstupy, které editovatelnost nehlásí
    (typicky `AXComboBox`).

    Oddělené od AX volání, aby šlo pravidlo otestovat bez GUI.
    """
    return bool(value_settable) or role in _TEXT_ROLES


def _ax():
    """Zkratka na ApplicationServices; None, když modul není (test/CI bez GUI)."""
    try:
        import ApplicationServices as _mod

        return _mod
    except Exception:  # noqa: BLE001
        return None


def _cfrange_type(ax) -> int:  # noqa: ANN001
    """Konstanta typu CFRange — jméno se mezi verzemi PyObjC liší."""
    return getattr(ax, "kAXValueCFRangeType", None) or getattr(
        ax, "kAXValueTypeCFRange", None
    ) or 4


def _range_location(ax, rng_val) -> int | None:  # noqa: ANN001
    """Začátek rozsahu (`CFRange.location`) z AX hodnoty."""
    if rng_val is None:
        return None
    try:
        ok, rng = ax.AXValueGetValue(rng_val, _cfrange_type(ax), None)
        if not ok:
            return None
        loc = getattr(rng, "location", None)
        if loc is None:
            loc = rng[0]
        return int(loc)
    except Exception:  # noqa: BLE001
        return None


def _focused_element(ax):  # noqa: ANN001
    """Zaměřený prvek s nastaveným timeoutem, nebo None.

    Jediné místo v modulu, které sahá na `AXFocusedUIElement`. Všechno ostatní
    z něj jen odvozuje — dřív si ho tahaly čtyři funkce zvlášť, takže se mohly
    ptát na různé prvky a rozejít se v závěrech.
    """
    try:
        system = ax.AXUIElementCreateSystemWide()
        # AX volání nemají default timeout — na hlavním vlákně (HUD) by
        # nereagující cílová appka zmrazila celou aplikaci. Strop 1 s.
        ax.AXUIElementSetMessagingTimeout(system, 1.0)
        err, focused = ax.AXUIElementCopyAttributeValue(
            system, ax.kAXFocusedUIElementAttribute, None
        )
        if err or focused is None:
            return None
        ax.AXUIElementSetMessagingTimeout(focused, 1.0)
        return focused
    except Exception:  # noqa: BLE001
        return None


def _read_role(ax, el) -> str | None:  # noqa: ANN001
    try:
        err, role = ax.AXUIElementCopyAttributeValue(el, ax.kAXRoleAttribute, None)
        return role if (not err and isinstance(role, str)) else None
    except Exception:  # noqa: BLE001
        return None


def _read_settable(ax, el) -> bool:  # noqa: ANN001
    try:
        err, val = ax.AXUIElementIsAttributeSettable(el, ax.kAXValueAttribute, None)
        return bool(val) if not err else False
    except Exception:  # noqa: BLE001
        return False


def _read_sig(ax, el, role) -> tuple | None:  # noqa: ANN001
    """Otisk pole (role, x, y, šířka, výška) — k ověření, že vkládáme tam,
    kam se diktovalo."""
    try:
        err1, pos_val = ax.AXUIElementCopyAttributeValue(el, ax.kAXPositionAttribute, None)
        err2, size_val = ax.AXUIElementCopyAttributeValue(el, ax.kAXSizeAttribute, None)
        if err1 or err2 or pos_val is None or size_val is None:
            return None
        okp, pt = ax.AXValueGetValue(pos_val, ax.kAXValueCGPointType, None)
        oks, sz = ax.AXValueGetValue(size_val, ax.kAXValueCGSizeType, None)
        if not (okp and oks):
            return None
        # Zaokrouhlení na celé body — subpixelové rozdíly nejsou změna pole.
        return (role, round(float(pt.x)), round(float(pt.y)),
                round(float(sz.width)), round(float(sz.height)))
    except Exception:  # noqa: BLE001
        return None


def _read_text_caret(ax, el) -> tuple[str | None, int | None]:  # noqa: ANN001
    """(obsah pole, pozice kurzoru). Prázdné pole vrací ("", caret)."""
    try:
        err, text = ax.AXUIElementCopyAttributeValue(el, ax.kAXValueAttribute, None)
        if err or not isinstance(text, str):
            return (None, None)
        err, rng_val = ax.AXUIElementCopyAttributeValue(
            el, ax.kAXSelectedTextRangeAttribute, None
        )
        caret = _range_location(ax, rng_val) if not err else None
        return (text, caret)
    except Exception:  # noqa: BLE001
        return (None, None)


def _read_at_line_start(ax, el) -> bool | None:  # noqa: ANN001
    """Stojí kurzor na začátku řádku? None = nezjistitelné.

    Nutné proto, že rich-text editory (Mail, Outlook) vracejí v AXValue text
    BEZ koncového konce řádku — po „Dobrý den" + Enter tedy z textu vypadá, že
    kurzor stojí za písmenem „n", a `needs_leading_space` by chybně přidala
    mezeru. Číslo řádku + rozsah řádku to poznají správně i tam.
    """
    try:
        err, line = ax.AXUIElementCopyAttributeValue(
            el, ax.kAXInsertionPointLineNumberAttribute, None
        )
        if err or line is None:
            return None
        err, line_rng = ax.AXUIElementCopyParameterizedAttributeValue(
            el, ax.kAXRangeForLineParameterizedAttribute, line, None
        )
        if err or line_rng is None:
            return None
        err, sel = ax.AXUIElementCopyAttributeValue(
            el, ax.kAXSelectedTextRangeAttribute, None
        )
        if err or sel is None:
            return None
        line_start = _range_location(ax, line_rng)
        caret = _range_location(ax, sel)
        if line_start is None or caret is None:
            return None
        return caret <= line_start
    except Exception:  # noqa: BLE001
        return None


class Focus(NamedTuple):
    """Jeden snímek zaměřeného prvku — vše z JEDNOHO dotazu na fokus.

    Existuje proto, aby se rozhodnutí, která spolu souvisejí (kam ukotvit
    okénko, jestli vložit nebo nechat ve schránce, jaký dát oddělovač),
    nedělala každé z jiného okamžiku. Když se dřív ptala každá funkce zvlášť,
    mohl se mezi dotazy fokus změnit a závěry se rozešly.
    """

    ok: bool                    # podařilo se fokus vůbec zjistit?
    is_input: bool              # dá se do toho psát?
    role: str | None
    sig: tuple | None           # otisk pole (role, x, y, w, h)
    text: str | None            # obsah pole
    caret: int | None
    at_line_start: bool | None

    @property
    def description(self) -> str:
        """Krátký popis do logu, ať jde zpětně ověřit chování diktátu."""
        if not self.ok:
            return "fokus neznámý (AX neodpověděl)"
        return f"role={self.role or '?'} pole={'ano' if self.is_input else 'ne'}"


_NO_FOCUS = Focus(False, False, None, None, None, None, None)


def focus_snapshot(*, want_text: bool = False, want_line: bool = False,
                   want_sig: bool = False) -> Focus:
    """Snímek zaměřeného prvku jedním dotazem na fokus.

    Volitelné části se čtou jen na vyžádání — každý AX atribut je round-trip
    do cizí aplikace s vlastním sekundovým stropem, takže je zbytečné tahat
    obsah pole tam, kde volajícího zajímá jen „je to pole?".
    """
    ax = _ax()
    if ax is None:
        return _NO_FOCUS
    el = _focused_element(ax)
    if el is None:
        return _NO_FOCUS

    role = _read_role(ax, el)
    is_input = is_text_input(_read_settable(ax, el), role)
    text = caret = at_line_start = sig = None
    if is_input:
        # U prvku, do kterého se psát nedá, nemá smysl číst obsah ani kurzor.
        if want_text:
            text, caret = _read_text_caret(ax, el)
        if want_line:
            at_line_start = _read_at_line_start(ax, el)
    if want_sig:
        sig = _read_sig(ax, el, role)
    return Focus(True, is_input, role, sig, text, caret, at_line_start)


def has_focused_text_field() -> bool | None:
    """Je teď zaměřené něco, do čeho se dá psát?

    True = ano, False = ne, None = nelze zjistit vůbec (chybí Accessibility
    nebo appka nehlásí žádný fokus).

    Accessibility je kooperativní — appka nemusí odpovědět nebo může lhát —
    takže absolutní jistota z principu neexistuje. Když se prvek za textový
    vstup neoznačí, chováme se, jako by pole nebylo: text zůstane ve schránce
    s lístkem „Připraveno k vložení". Nejhorší případ je tedy `⌘V` navíc, ne
    ztracený diktát.
    """
    snap = focus_snapshot()
    return snap.is_input if snap.ok else None


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


# Konce vět, po kterých má nový záznam začít na vlastním řádku.
_SENTENCE_END = (".", "!", "?", ":", "…")


def leading_separator(
    field_text: str | None,
    caret: int | None,
    *,
    role: str | None = None,
    allow_newline: bool = True,
) -> str:
    """Co vložit PŘED diktovaný text: "" | " " | "\\n".

    Navazuje na `needs_leading_space` — dokud ta říká, že mezera netřeba (začátek
    řádku, prázdné pole), nevkládá se nic. Když navazujeme za textem, rozhodne se
    mezi mezerou a novým řádkem:

    - **nový řádek** jen když je pole víceřádkové A předchozí text končí větou.
      To je případ „ukládám pod sebe další záznam" — jinak by dva záznamy splynuly
      do jednoho dlouhého řádku oddělené mezerou.
    - **mezera** ve všech ostatních případech (pokračuji uprostřed věty, po čárce,
      nebo pole jednořádkové).

    `role` je AX role prvku (`AXTextArea` = víceřádkové). Když ji nemáme (web,
    Electron), poznáme víceřádkové pole podle toho, že už odřádkování obsahuje.
    `allow_newline=False` novou řádku zakáže úplně — nutné u vzdálené Windows
    plochy, kde se text „ťuká" znak po znaku a `\\n` by zafungoval jako Enter
    (tj. odeslal by rozepsanou zprávu).
    """
    if not needs_leading_space(field_text, caret):
        return ""
    if not allow_newline:
        return " "
    multiline = role == "AXTextArea" or "\n" in (field_text or "")
    if multiline and field_text[:caret].rstrip().endswith(_SENTENCE_END):
        return "\n"
    return " "


def caret_screen_rect() -> tuple[float, float, float, float] | None:
    """Obdélník textového kurzoru na obrazovce (x, y, w, h) v AX souřadnicích
    (počátek vlevo NAHOŘE, y roste dolů). None, když to appka nepodporuje.

    Ladění: diagnostická oblast `hud` vypíše, na kterém kroku AX selhal (appka
    prostě nemusí `kAXBoundsForRangeParameterizedAttribute` implementovat —
    i u „nativních" appek to není univerzální)."""
    def _dbg(msg: str) -> None:
        diag.log("hud", f"caret: {msg}")

    try:
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            AXUIElementCopyParameterizedAttributeValue,
            AXValueGetValue,
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
        """Fallback: rám (pozice+velikost) fokusovaného POLE. Když appka neumí
        přesnou pozici kurzoru (Electron/web), je HUD u pole pořád mnohem lepší
        než nikde. Vracíme jen horní pruh pole (výška omezená), ať HUD sedí
        nahoře nad polem, ne uprostřed velké textarey.

        Volá se jen pro prvky, které už prošly bránou „je to textový vstup" —
        tedy je to prokazatelně pole a jen neumí spočítat pozici kurzoru. Na
        cokoliv jiného se rám nepoužívá, jinak by okénko přistálo v rohu okna
        nebo na ploše místo pod ikonou.
        """
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
        # Stejná brána jako u rozhodnutí „vložit vs. do schránky": co není
        # textový vstup, u toho polohu kurzoru vůbec nehledáme. Jinak by okénko
        # skončilo v levém horním rohu okna (Chromium tam hlásí začátek
        # dokumentu jako „kurzor", i když žádné pole zaměřené není).
        ax = _ax()
        if ax is None:
            return None
        focused = _focused_element(ax)
        if focused is None:
            _dbg("žádný focused element")
            return None
        role = _read_role(ax, focused)
        if not is_text_input(_read_settable(ax, focused), role):
            _dbg(f"fokus není textový vstup (role={role}) → HUD patří k ikoně")
            return None
        err, rng_val = AXUIElementCopyAttributeValue(
            focused, kAXSelectedTextRangeAttribute, None
        )
        if err or rng_val is None:
            _dbg(f"pole nehlásí výběr textu (err={err}) → zkouším rám pole")
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


def decide_delivery(*, target_bundle: str | None, field_sig: tuple | None,
                    win_target: bool) -> tuple[bool, str]:
    """Vložit text rovnou, nebo ho nechat ve schránce? → (vložit?, důvod)

    Tři situace, kdy se NEVKLÁDÁ, protože by text spadl někam, kam nepatří.
    Jsou pohromadě schválně: dřív to byly tři samostatné bloky v pipeline
    a bylo snadné jeden z nich přehlédnout nebo upravit jinak než ostatní.

    Rozhoduje se konzervativně — při pochybnosti se vkládá, protože text ve
    schránce s lístkem je drobná otrava, kdežto nevložení bez varování vypadá
    jako by se diktát ztratil.
    """
    # 1) Přepnul uživatel do jiné aplikace? Text by spadl do cizího pole.
    _name, now_bundle = frontmost_app()
    if target_bundle and now_bundle and now_bundle != target_bundle:
        return (False, f"fokus je jinde ({now_bundle})")

    # 2) Stejná aplikace, ale jiné pole (klik jinam, zavřené okno).
    #    `same_field` vrací None, když otisk nejde získat (web/Electron) —
    #    tam se vkládá jako dřív, jinak by to hlásilo pořád.
    if same_field(field_sig, focus_snapshot(want_sig=True).sig) is False:
        return (False, "jsi v jiném poli")

    # 3) Není kam vložit vůbec (fokus na okně, seznamu, tlačítku).
    #    U RDP/AVD se neptáme: pole je uvnitř vzdálené plochy a macOS do ní
    #    nevidí, takže by odpověď stejně nic neznamenala.
    if not win_target and has_focused_text_field() is False:
        return (False, "není zaměřené textové pole")

    return (True, "")
