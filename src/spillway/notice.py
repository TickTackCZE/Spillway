"""Vedlejší okénko s upozorněním — visí VEDLE popoveru nebo okna nastavení.

Proč zvlášť a ne uvnitř: upozornění „bez modelu to nepojede" je jiná úroveň
sdělení než obsah okna. Když sedí nahoře v popoveru, splyne s ním a uživatel
ho přehlédne; jako samostatná kartička se šipkou na okno je vidět a nezabírá
místo v rozvržení, které pak skáče.

Stavba je stejná jako u `hud.py`: neaktivující borderless panel s WKWebView,
takže se okno pod ním nerozostří a nepřijde o fokus. Panel je na úrovni
status baru, tedy nad běžnými okny včetně Nastavení.
"""

from __future__ import annotations

import json

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSMakePoint,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSWindowAbove,
)
from WebKit import WKWebView, WKWebViewConfiguration

from . import design, models

_BORDERLESS = 0
_NONACTIVATING = 1 << 7
_STATUS_LEVEL = 25

_LOGO = design.logo_svg(color="#818CF8", width=15, height=15)

_HTML = r"""<!DOCTYPE html><html lang="cs"><head><meta charset="UTF-8"><style>
  *{margin:0;padding:0;box-sizing:border-box;}
  :root{--surface:#1A1F2E;--text:#E2E8F0;--muted:#94A3B8;--accent:#818CF8;
        --danger:#E11D48;--warn:#F59E0B;--border:rgba(129,140,248,0.22);}
  @media (prefers-color-scheme: light){ :root{
    --surface:#FFFFFF;--text:#1E293B;--muted:#64748B;--accent:#3B82F6;
    --border:rgba(59,130,246,0.18);} }
  html,body{background:transparent;}
  body{font-family:-apple-system,'Raleway',sans-serif;padding:8px;}
  .wrap{position:relative;}
  .card{background:var(--surface);border:0.5px solid var(--border);border-radius:12px;
    padding:12px 13px;box-shadow:0 8px 26px rgba(0,0,0,0.42);}
  /* Šipka míří doprava, na okno vedle. */
  .arrow{position:absolute;right:-6px;top:26px;width:12px;height:12px;
    background:var(--surface);border-right:0.5px solid var(--border);
    border-top:0.5px solid var(--border);transform:rotate(45deg);}
  .head{display:flex;align-items:center;gap:7px;margin-bottom:10px;}
  .head .t{font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;
    color:var(--muted);}
  /* Každé sdělení je blok: text + jeho VLASTNÍ tlačítka hned pod ním. */
  .item{padding:9px 0;}
  .item + .item{border-top:0.5px solid var(--border);}
  .item .msg{display:flex;gap:9px;}
  .item .dot{width:8px;height:8px;border-radius:50%;flex:none;margin-top:4px;}
  .item .txt{font-size:12px;color:var(--text);line-height:1.45;}
  .item .txt small{display:block;font-size:11px;color:var(--muted);margin-top:2px;}
  .acts{display:flex;gap:6px;margin-top:9px;}
  button{flex:1;border:0;border-radius:8px;font:inherit;font-size:12px;font-weight:600;
    padding:8px;cursor:pointer;background:var(--accent);color:#fff;}
  button.ghost{background:transparent;border:0.5px solid var(--border);color:var(--muted);}
  button:disabled{opacity:.6;cursor:default;}
  /* Drobný ukazatel TĚSNĚ nad tlačítkem, ne pod dělící čárou. */
  .prog{height:4px;background:rgba(148,163,184,0.22);border-radius:2px;overflow:hidden;margin-top:9px;}
  .prog>div{height:100%;width:0;background:var(--accent);border-radius:2px;transition:width .3s;}
  .pct{font-size:11px;color:var(--muted);margin-top:5px;}
</style></head><body>
  <div class="wrap">
    <div class="arrow"></div>
    <div class="card">
      <div class="head">__LOGO__<span class="t">Spillway</span></div>

      <div class="item" id="itModel" style="display:none;">
        <div class="msg"><span class="dot" style="background:var(--danger)"></span>
          <span class="txt"><b>Nefunguje, dokud nestáhneš model</b>
            <small id="modelSub">Přepis běží u tebe v počítači. Stáhne se jednou, 1,6 GB.</small></span></div>
        <div class="prog" id="prog" style="display:none;"><div id="bar"></div></div>
        <div class="acts"><button id="btnModel" onclick="modelBtn()">Stáhnout model</button></div>
      </div>

      <div class="item" id="itKey" style="display:none;">
        <div class="msg"><span class="dot" style="background:var(--warn)"></span>
          <span class="txt"><b>Nemáš zadaný API klíč pro AI zpracování</b>
            <small>Bez něj se řeč jen přepíše. S ním ji Claude ještě upraví.</small></span></div>
        <div class="acts">
          <button onclick="say('key_open')">Zadat</button>
          <button class="ghost" onclick="say('key_snooze')">Neupozorňovat</button>
        </div>
      </div>
    </div>
  </div>
<script>
  function say(a){ try{ window.webkit.messageHandlers.spillway.postMessage({action:a}); }catch(e){} }
  var _dl = false, _cancelling = false;
  function modelBtn(){
    var b = document.getElementById('btnModel');
    if(b.disabled) return;                 // opakovaný klik ignorovat
    // Během stahování se ze stejného tlačítka stane „Zrušit".
    if(_dl){ _cancelling = true; b.textContent = 'Ruším…'; }
    say(_dl ? 'cancel' : 'download');
    b.disabled = true;
  }
  function render(s){
    document.getElementById('itModel').style.display = s.model ? 'none' : 'block';
    document.getElementById('itKey').style.display = s.key ? 'none' : 'block';
    _dl = !!s.downloading;
    var b = document.getElementById('btnModel'), prog = document.getElementById('prog');
    // Po kliknutí na Zrušit zůstane tlačítko zamčené, dokud běh opravdu
    // neskončí — jinak ho každé hlášení průběhu zase povolí a dá se klikat
    // dokola, což jen zahltí most.
    if(_cancelling && s.downloading){
      prog.style.display = 'block';
      document.getElementById('bar').style.width = (s.percent||0) + '%';
      b.disabled = true; b.textContent = 'Ruším…';
      return;
    }
    _cancelling = false;
    b.disabled = false;
    if(s.downloading){
      prog.style.display = 'block';
      document.getElementById('bar').style.width = (s.percent||0) + '%';
      document.getElementById('modelSub').textContent = (s.progress_text || 'Stahuji…');
      b.textContent = 'Zrušit'; b.classList.add('ghost');
    } else {
      prog.style.display = 'none';
      document.getElementById('modelSub').textContent =
        'Přepis běží u tebe v počítači. Stáhne se jednou, 1,6 GB.';
      b.textContent = 'Stáhnout model'; b.classList.remove('ghost');
    }
  }
</script>
</body></html>""".replace("__LOGO__", _LOGO)


# Jméno musí být unikátní v CELÉ aplikaci — třídy Objective-C mají
# globální jmenný prostor a druhá stejnojmenná shodí import.
class _NoticeBridge(objc.lookUpClass("NSObject")):
    def initWithOwner_(self, owner):  # noqa: N802
        self = objc.super(_NoticeBridge, self).init()
        if self is None:
            return None
        self._owner = owner
        return self

    def userContentController_didReceiveScriptMessage_(self, ucc, message):  # noqa: N802
        try:
            body = dict(message.body()) if hasattr(message.body(), "keys") else {}
            action = str(body.get("action", ""))
            if action == "download":
                models.add_download_listener(self._owner.on_download_state)
                models.download_async()
            elif action == "cancel":
                models.cancel_download()
            elif action in ("key_open", "key_snooze"):
                self._owner.on_key_action(action)
        except Exception as exc:  # noqa: BLE001
            print(f"[notice] chyba: {exc}")


class NoticePanel:
    """Kartička s upozorněním vedle jiného okna."""

    W, H = 288, 300

    def __init__(self) -> None:
        rect = NSMakeRect(0, 0, self.W, self.H)
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, _BORDERLESS | _NONACTIVATING, NSBackingStoreBuffered, False
        )
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setLevel_(_STATUS_LEVEL)
        self.panel.setHasShadow_(False)      # stín dělá CSS
        self.panel.setFloatingPanel_(True)
        self.panel.setHidesOnDeactivate_(False)

        cfg = WKWebViewConfiguration.alloc().init()
        self._bridge = _NoticeBridge.alloc().initWithOwner_(self)
        cfg.userContentController().addScriptMessageHandler_name_(self._bridge, "spillway")
        self.web = WKWebView.alloc().initWithFrame_configuration_(rect, cfg)
        try:
            self.web.setValue_forKey_(False, "drawsBackground")
        except Exception:  # noqa: BLE001
            pass
        self.web.loadHTMLString_baseURL_(_HTML, None)
        self.panel.setContentView_(self.web)

        self._visible = False
        self._last: dict | None = None
        self.on_key = None       # doplní tray: 'key_open' | 'key_snooze'
        self._parent = None      # okno, ke kterému je kartička připnutá

    # --- vzhled ---------------------------------------------------------------

    @objc.python_method
    def _render(self, state: dict) -> None:
        from .settings_window import _run_js

        _run_js(self.web, "render(" + json.dumps(state, ensure_ascii=False) + ")", "notice")

    @objc.python_method
    def on_download_state(self, st: dict) -> None:
        """Postup stahování z `models` — musí zpátky na hlavní vlákno."""
        from Foundation import NSOperationQueue

        def apply() -> None:
            base = dict(self._last or {})
            base.update({"model": models.is_ready(),
                         "downloading": st.get("downloading", False),
                         "percent": st.get("percent", 0)})
            self._last = base
            self._render(base)
            if base["model"]:
                self.hide()

        NSOperationQueue.mainQueue().addOperationWithBlock_(apply)

    @objc.python_method
    def on_key_action(self, what: str) -> None:
        cb = self.on_key
        if cb is not None:
            try:
                cb(what)
            except Exception:  # noqa: BLE001 — klik nesmí nic shodit
                pass

    # --- poloha a viditelnost -------------------------------------------------

    @objc.python_method
    def show_beside(self, parent, *, model_ready: bool, has_key: bool) -> None:
        """Pověsí kartičku vlevo od okna `parent` (NSWindow).

        Kartička se připojí jako **potomek okna**, ne jen posadí na souřadnice.
        Díky tomu zmizí spolu s rodičem — když se popover zavře klikem jinam,
        odejde i ona. Dřív to hlídal jen časovač a kartička uměla zůstat viset.

        Nikdy rodiče nepřekrývá: kdyby vlevo nebylo místo, jde doprava od něj.
        Překryv byl nebezpečný — klik na její tlačítko vypadal jako klik do
        popoveru a otevíral Nastavení „samo od sebe".
        """
        if parent is None or (model_ready and has_key):
            self.hide()
            return

        state = {"model": model_ready, "key": has_key, **models.download_state()}
        self._last = state
        self._render(state)

        pf = parent.frame()
        gap = 8.0
        x = float(pf.origin.x) - self.W - gap
        y = float(pf.origin.y) + float(pf.size.height) - self.H

        screens = NSScreen.screens()
        if screens:
            vf = screens[0].visibleFrame()
            left, bottom = float(vf.origin.x), float(vf.origin.y)
            if x < left + 4.0:                      # vlevo se nevejde → doprava
                x = float(pf.origin.x) + float(pf.size.width) + gap
            y = max(bottom + 4.0, y)

        self.panel.setFrameOrigin_(NSMakePoint(x, y))

        if self._parent is not parent:
            self._detach()
            try:
                parent.addChildWindow_ordered_(self.panel, NSWindowAbove)
                self._parent = parent
            except Exception:  # noqa: BLE001 — bez vazby aspoň ukázat
                self.panel.orderFrontRegardless()
        elif not self._visible:
            self.panel.orderFrontRegardless()
        self._visible = True

    @objc.python_method
    def _detach(self) -> None:
        if self._parent is not None:
            try:
                self._parent.removeChildWindow_(self.panel)
            except Exception:  # noqa: BLE001
                pass
            self._parent = None

    @objc.python_method
    def hide(self) -> None:
        self._detach()
        if self._visible:
            self.panel.orderOut_(None)
            self._visible = False
