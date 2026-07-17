"""Plovoucí status okénko u textového kurzoru — Domovoy design přes WKWebView.

Vzhled je HTML/CSS (přesně dle Domovoy: ghost logo, tmavá karta, accent lem,
pulzující tečka), takže ho lze ladit a náhledovat v prohlížeči. Okno je
borderless, průhledné, neaktivní panel; obsah renderuje WKWebView.

Poloha: nad textovým kurzorem (AX `kAXBoundsForRangeParameterizedAttribute`),
fallback k myši. `SPILLWAY_DEBUG_HUD=1` vypisuje zjištěné souřadnice.

Vše běží na hlavním vlákně (voláno z rumps.Timer). Když se HUD nepodaří
vytvořit, tray ho tiše přeskočí.
"""

from __future__ import annotations

import os

from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSEvent,
    NSMakePoint,
    NSMakeRect,
    NSPanel,
    NSScreen,
)
from WebKit import WKWebView, WKWebViewConfiguration

from . import context, design

_DEBUG = os.environ.get("SPILLWAY_DEBUG_HUD", "0").lower() not in ("0", "false", "no")

_BORDERLESS = 0
_NONACTIVATING = 1 << 7
_STATUS_LEVEL = 25
_ALL_SPACES = 1 << 0
_STATIONARY = 1 << 4
_FS_AUX = 1 << 8

# Spillway logo (roztékající waveform) — světlé sloupce, bez kapek (malá velikost).
_LOGO = design.logo_svg(color="#C7CCF7", width=17, height=17, drops=False)

_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  * { margin:0; padding:0; box-sizing:border-box; }
  html,body { background:transparent; }
  body { font-family:-apple-system,'Raleway',sans-serif; padding:8px; }
  .card {
    display:none; align-items:center; gap:10px;
    background:rgba(38,38,40,0.96); border:0.5px solid rgba(255,255,255,0.15);
    border-radius:12px; padding:9px 15px 9px 12px;
    box-shadow:0 8px 22px rgba(0,0,0,0.4); width:fit-content;
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
  <div id="card" class="card">
    <span class="logo">__LOGO__</span>
    <span id="dot" class="dot"></span>
    <span id="label" class="label"></span>
  </div>
  <script>
    function setState(s){
      var c=document.getElementById('card'),d=document.getElementById('dot'),l=document.getElementById('label');
      if(s==='rec'){c.style.display='inline-flex';d.className='dot rec';l.textContent='Nahrávám';}
      else if(s==='proc'){c.style.display='inline-flex';d.className='dot proc';l.textContent='Zpracovávám';}
      else if(s==='cancel'){c.style.display='inline-flex';d.className='dot cancel';l.textContent='Ruším';}
      else {c.style.display='none';}
    }
  </script>
</body></html>""".replace("__LOGO__", _LOGO)


class StatusHUD:
    W, H = 210, 48

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
        self.panel.setContentView_(self.web)

        self._state = None
        self._visible = False

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            try:
                self.web.evaluateJavaScript_completionHandler_(
                    f"setState('{state}')", None
                )
            except Exception:  # noqa: BLE001
                pass

    def _reposition(self) -> None:
        gap = 10.0
        rect = context.caret_screen_rect()
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
            if _DEBUG:
                print(f"[hud] caret AX=({cx:.0f},{cy:.0f},{cw:.0f},{ch:.0f}) → panel=({x:.0f},{y:.0f})")
            self.panel.setFrameOrigin_(NSMakePoint(x, y))
        else:
            loc = NSEvent.mouseLocation()
            if _DEBUG:
                print(f"[hud] bez kurzoru (fallback myš) → ({loc.x:.0f},{loc.y:.0f})")
            self.panel.setFrameOrigin_(NSMakePoint(loc.x - self.W / 2, loc.y + 24))

    def show(self, state: str) -> None:
        self._set_state(state)
        self._reposition()
        if not self._visible:
            self.panel.orderFrontRegardless()
            self._visible = True

    def hide(self) -> None:
        self._set_state("hide")
        if self._visible:
            self.panel.orderOut_(None)
            self._visible = False
