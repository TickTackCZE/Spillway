"""Plovoucí status okénko u textového kurzoru — Domovoy design přes WKWebView.

Vzhled je HTML/CSS (přesně dle Domovoy: ghost logo, tmavá karta, accent lem,
pulzující tečka), takže ho lze ladit a náhledovat v prohlížeči. Okno je
borderless, průhledné, neaktivní panel; obsah renderuje WKWebView.

Poloha má jen DVĚ možnosti, ať je chování jednotné: nad textovým kurzorem
(AX `kAXBoundsForRangeParameterizedAttribute`), a když ten není k dispozici
(web/Electron, odchod z cílové appky, čekající lístek), pod ikonou v liště se
šipkou na ni. U myši se okénko neukazuje nikdy.
Souřadnice okénka vypíše diagnostická oblast `hud` (viz `diag.py`).

Vše běží na hlavním vlákně (voláno z rumps.Timer). Když se HUD nepodaří
vytvořit, tray ho tiše přeskočí.
"""

from __future__ import annotations

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSMakePoint,
    NSMakeRect,
    NSPanel,
    NSPointInRect,
    NSScreen,
    NSView,
)
from WebKit import WKWebView, WKWebViewConfiguration

from . import context, design, diag
from .webview import run_js

_BORDERLESS = 0
_NONACTIVATING = 1 << 7
_STATUS_LEVEL = 25
_ALL_SPACES = 1 << 0
_STATIONARY = 1 << 4
_FS_AUX = 1 << 8

# Spillway logo (roztékající waveform) — světlé sloupce, bez kapek (malá velikost).
_LOGO = design.logo_svg(color="#C7CCF7", width=17, height=17)

_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  * { margin:0; padding:0; box-sizing:border-box; }
  html,body { background:transparent; }
  body { font-family:-apple-system,'Raleway',sans-serif; padding:8px;
         display:flex; justify-content:center; }
  .card {
    display:none; align-items:center; gap:10px;
    background:rgba(38,38,40,0.96); border:0.5px solid rgba(255,255,255,0.15);
    border-radius:12px; padding:9px 15px 9px 12px;
    box-shadow:0 8px 22px rgba(0,0,0,0.4); width:fit-content;
  }
  /* Ukotvení pod ikonu v liště: špička míří nahoru na ikonu (jako u menu). */
  .card.anchored { margin-top:6px; }
  #arrow {
    display:none; position:absolute; top:5px; width:12px; height:12px;
    background:rgba(38,38,40,0.96);
    border-left:0.5px solid rgba(255,255,255,0.15);
    border-top:0.5px solid rgba(255,255,255,0.15);
    transform:translateX(-50%) rotate(45deg);
  }
  .dot.ready { background:#4ADE80; }
  .dot.nomodel { background:#E11D48; animation:pulse 1.5s infinite; }
  .kbd {
    font-size:11px; font-weight:600; color:#F5F5F7; padding:2px 6px; border-radius:5px;
    background:rgba(255,255,255,0.14); border:0.5px solid rgba(255,255,255,0.18);
    white-space:nowrap;
  }
  .logo { display:flex; align-items:center; width:17px; height:19px; flex-shrink:0; }
  .logo svg { display:block; }
  .dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
  .dot.rec { background:#FF453A; animation:pulse 1.5s infinite; }
  .dot.proc { background:#FF9F0A; animation:blink 1s infinite; }
  /* Ruším — šedá, bliká stejně jako „Zpracovávám" (rušení taky chvíli běží). */
  .dot.cancel { background:#8E8E93; animation:blink 1s infinite; }
  @keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(255,69,58,0.5);} 70%{box-shadow:0 0 0 6px rgba(255,69,58,0);} 100%{box-shadow:0 0 0 0 rgba(255,69,58,0);} }
  @keyframes blink { 0%,100%{opacity:1;} 50%{opacity:0.4;} }
  .label { color:#F5F5F7; font-size:13px; font-weight:500; letter-spacing:0.2px; white-space:nowrap; line-height:1; }
</style></head><body>
  <div id="arrow"></div>
  <div id="card" class="card">
    <span class="logo">__LOGO__</span>
    <span id="dot" class="dot"></span>
    <span id="label" class="label"></span>
    <span id="kbd" class="kbd" style="display:none">⌘V</span>
  </div>
  <script>
    function setState(s){
      var c=document.getElementById('card'),d=document.getElementById('dot'),
          l=document.getElementById('label'),k=document.getElementById('kbd');
      k.style.display='none';
      if(s==='rec'){c.style.display='inline-flex';d.className='dot rec';l.textContent='Nahrávám';}
      else if(s==='proc'){c.style.display='inline-flex';d.className='dot proc';l.textContent='Zpracovávám';}
      else if(s==='cancel'){c.style.display='inline-flex';d.className='dot cancel';l.textContent='Ruším';}
      else if(s==='ready'){c.style.display='inline-flex';d.className='dot ready';
        l.textContent='Připraveno k vložení';
        k.textContent='⌘V';k.style.display='inline-block';}
      else if(s==='nomodel'){c.style.display='inline-flex';d.className='dot nomodel';
        l.textContent='Chybí model — klikni a stáhni';
        k.textContent='esc';k.style.display='inline-block';}
      else {c.style.display='none';}
    }
    // `off` = vzdálenost středu ikony od levého okraje okénka (v px), nebo null
    // pro režim „u kurzoru" (bez šipky). Šipku držíme uvnitř karty.
    function setAnchor(off){
      var c=document.getElementById('card'), a=document.getElementById('arrow');
      if(off===null||off===undefined){ c.classList.remove('anchored'); a.style.display='none'; return; }
      c.classList.add('anchored'); a.style.display='block';
      var r=c.getBoundingClientRect();
      a.style.left=Math.max(r.left+14, Math.min(off, r.right-14))+'px';
    }
  </script>
</body></html>""".replace("__LOGO__", _LOGO)


class _ClickCatcher(NSView):
    """Neviditelná vrstva nad WKWebView, která spolehlivě chytne kliknutí.

    Na klik uvnitř nekey okna se u WKWebView spolehnout nedá, tak si ho bereme
    nativně: `hitTest_` vrátí vždy sebe, takže web-view myš nikdy nedostane.
    """

    @objc.python_method
    def set_callback(self, cb) -> None:
        self._cb = cb

    def hitTest_(self, point):  # noqa: N802
        # `point` je v souřadnicích nadřazeného view.
        return self if NSPointInRect(point, self.frame()) else None

    def mouseDown_(self, event):  # noqa: N802, ARG002
        cb = getattr(self, "_cb", None)
        if cb is not None:
            try:
                cb()
            except Exception:  # noqa: BLE001 — klik nesmí nic shodit
                pass


class StatusHUD:
    # Šířka musí pojmout NEJDELŠÍ stav („Chybí model — klikni a stáhni"),
    # jinak se text uřízne: karta uvnitř má `width:fit-content`, ale okno ji
    # ořízne na svoji šířku. Karta se v okně centruje, takže u kratších stavů
    # nadbytečná šířka není vidět (okno je průhledné).
    W, H = 330, 56

    def __init__(self) -> None:
        rect = NSMakeRect(0, 0, self.W, self.H)
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, _BORDERLESS | _NONACTIVATING, NSBackingStoreBuffered, False
        )
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setLevel_(_STATUS_LEVEL)
        self.panel.setIgnoresMouseEvents_(True)
        self.panel.setHasShadow_(False)  # stín dělá CSS
        self.panel.setFloatingPanel_(True)
        self.panel.setHidesOnDeactivate_(False)
        try:
            self.panel.setCollectionBehavior_(_ALL_SPACES | _STATIONARY | _FS_AUX)
        except Exception:  # noqa: BLE001
            pass

        config = WKWebViewConfiguration.alloc().init()
        self.web = WKWebView.alloc().initWithFrame_configuration_(rect, config)
        try:
            self.web.setValue_forKey_(False, "drawsBackground")  # průhledné pozadí
        except Exception:  # noqa: BLE001
            pass
        self.web.loadHTMLString_baseURL_(_HTML, None)

        # Kontejner: web-view (vzhled) + neviditelná klikací vrstva nad ním.
        container = NSView.alloc().initWithFrame_(rect)
        container.addSubview_(self.web)
        self._click = _ClickCatcher.alloc().initWithFrame_(rect)
        self._click.set_callback(self._on_click)
        container.addSubview_(self._click)
        self.panel.setContentView_(container)

        self._state = None
        self._visible = False
        self._anchor_offset = None   # px od levého okraje okna (šipka), None = u kurzoru
        # Tlumení dotazů na polohu kurzoru — viz `_caret_rect`.
        self._rect_cache: tuple | None = None
        self._rect_at = 0.0
        self.status_button = None    # tlačítko ikony v liště (doplní tray)
        self.on_dismiss = None       # zavolá se, když uživatel klikne na lístek

    @objc.python_method
    def _on_click(self) -> None:
        # Klik má smysl jen u lístku „Připraveno k vložení" — jinak je vrstva
        # vypnutá (panel ignoruje myš), takže se sem stejně nedostaneme.
        cb = self.on_dismiss
        if cb is not None:
            cb()

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            try:
                run_js(self.web, f"setState('{state}')", "hud")
            except Exception:  # noqa: BLE001
                pass

    def _caret_rect(self) -> tuple | None:
        """Poloha kurzoru, přepočítaná nejvýš 3×/s.

        `caret_screen_rect()` je 5–7 kol Accessibility do CIZÍ aplikace a každé
        má strop 1 s. Volalo se to z časovače lišty 6,7×/s, takže stačilo, aby
        cílová appka chvíli neodpovídala (Electron při GC, Xcode při indexaci) a
        zamrzlo celé UI Spillway: ikona přestala animovat, okénko se
        nepřekreslilo, popover nešel otevřít.

        Kurzor se mezi dvěma tiky nikam neposune tak, aby to šlo vidět, takže
        se tím nic neztrácí — jen se přestane ptát zbytečně často.
        """
        import time as _t

        now = _t.monotonic()
        if now - self._rect_at < 0.3:
            return self._rect_cache
        self._rect_at = now
        self._rect_cache = context.caret_screen_rect()
        return self._rect_cache

    def _reposition(self) -> None:
        gap = 10.0
        rect = self._caret_rect()
        screens = NSScreen.screens()
        primary_h = float(screens[0].frame().size.height) if screens else 0.0
        screen_w = float(screens[0].frame().size.width) if screens else 99999.0

        if rect is not None:
            cx, cy, cw, ch = rect  # AX: počátek vlevo NAHOŘE
            # karta má 8px odsazení uvnitř okna → posun, aby seděla nad kurzorem
            x = cx + cw / 2.0 - self.W / 2.0
            x = max(4.0, min(x, screen_w - self.W - 4.0))
            caret_top = primary_h - cy
            caret_bottom = primary_h - (cy + ch)
            y = caret_top + gap - 8.0
            if y + self.H > primary_h - 4.0:
                y = caret_bottom - self.H - gap
            diag.log("hud", f"caret AX=({cx:.0f},{cy:.0f},{cw:.0f},{ch:.0f}) → panel=({x:.0f},{y:.0f})")
            self.panel.setFrameOrigin_(NSMakePoint(x, y))
        else:
            # Kurzor neznáme (odešel jsi z pole, web/Electron) — místo lítání za
            # myší se okénko ukotví pod ikonu v liště a špičkou míří na ni.
            self._anchor_to_status_item()
            return
        self._set_anchor(None)  # u kurzoru → bez šipky

    def _anchor_to_status_item(self) -> None:
        """Posadí okénko pod ikonu Spillway v liště (šipka míří na ikonu).
        Když polohu ikony nejde zjistit (schovaná v Bartenderu, výřez), spadne
        to na pravý horní roh obrazovky."""
        icon_center_x = None
        top_y = None
        button = self.status_button
        try:
            if button is not None:
                win = button.window()
                if win is not None:
                    f = win.frame()
                    icon_center_x = float(f.origin.x) + float(f.size.width) / 2.0
                    top_y = float(f.origin.y)  # spodní hrana lišty
        except Exception:  # noqa: BLE001
            icon_center_x = top_y = None

        screen = NSScreen.mainScreen() or (NSScreen.screens()[0] if NSScreen.screens() else None)
        if screen is None:
            return
        vf = screen.frame()
        if icon_center_x is None or top_y is None:
            icon_center_x = float(vf.origin.x) + float(vf.size.width) - 40.0
            top_y = float(vf.origin.y) + float(vf.size.height) - 24.0
            diag.log("hud", "ikona v liště neznámá → pravý horní roh")

        x = icon_center_x - self.W / 2.0
        x = max(float(vf.origin.x) + 4.0,
                min(x, float(vf.origin.x) + float(vf.size.width) - self.W - 4.0))
        y = top_y - self.H
        diag.log("hud", f"ukotveno k ikoně: icon_x={icon_center_x:.0f} → panel=({x:.0f},{y:.0f})")
        self.panel.setFrameOrigin_(NSMakePoint(x, y))
        self._set_anchor(icon_center_x - x)  # kam v okénku patří špička

    def _set_anchor(self, offset) -> None:
        if offset == self._anchor_offset:
            return
        self._anchor_offset = offset
        js = "setAnchor(%s)" % ("null" if offset is None else f"{float(offset):.1f}")
        try:
            run_js(self.web, js, "hud")
        except Exception:  # noqa: BLE001
            pass

    def show(self, state: str, at_icon: bool = False) -> None:
        """`at_icon=True` posadí okénko k ikoně v liště i během nahrávání/zpracování
        — používá se, když uživatel odejde z cílové aplikace (jinak by okénko
        zůstalo viset u kurzoru v cizí appce, kam se nic vkládat nebude)."""
        self._set_state(state)
        if state in ("ready", "nomodel") or at_icon:
            # Lístek „Připraveno k vložení" visí u ikony a dá se na něj kliknout.
            # Panel je neaktivační, takže klik NEPŘEPNE aplikaci a tvoje pole
            # nepřijde o kurzor (jinak by následné ⌘V vložilo text jinam).
            self._anchor_to_status_item()
        else:
            self._reposition()
        self.panel.setIgnoresMouseEvents_(state not in ("ready", "nomodel"))  # jinde ať myš propadává
        if not self._visible:
            self.panel.orderFrontRegardless()
            self._visible = True

    def hide(self) -> None:
        self._set_state("hide")
        # Zahodit polohu kurzoru, ať se příští diktát neukotví podle pole, ve
        # kterém se diktovalo minule.
        self._rect_cache, self._rect_at = None, 0.0
        if self._visible:
            self.panel.setIgnoresMouseEvents_(True)
            self.panel.orderOut_(None)
            self._visible = False
