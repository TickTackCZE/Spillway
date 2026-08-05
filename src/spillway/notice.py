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
  /* Šipka míří doprava, na okno vedle. */
  .wrap{position:relative;}
  .card{background:var(--surface);border:0.5px solid var(--border);border-radius:12px;
    padding:12px 13px;box-shadow:0 8px 26px rgba(0,0,0,0.42);}
  .arrow{position:absolute;right:-6px;top:26px;width:12px;height:12px;
    background:var(--surface);border-right:0.5px solid var(--border);
    border-top:0.5px solid var(--border);transform:rotate(45deg);}
  .head{display:flex;align-items:center;gap:7px;margin-bottom:9px;}
  .head .t{font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;
    color:var(--muted);}
  .item{display:flex;gap:9px;padding:8px 0;}
  .item + .item{border-top:0.5px solid var(--border);}
  .item .dot{width:8px;height:8px;border-radius:50%;flex:none;margin-top:4px;}
  .item .msg{font-size:12px;color:var(--text);line-height:1.45;}
  .item .msg small{display:block;font-size:11px;color:var(--muted);margin-top:2px;}
  button{width:100%;border:0;border-radius:9px;background:var(--danger);color:#fff;
    font:inherit;font-size:12px;font-weight:600;padding:9px;cursor:pointer;margin-top:10px;}
  button:disabled{opacity:.6;cursor:default;}
  .prog{height:5px;background:rgba(148,163,184,0.22);border-radius:3px;overflow:hidden;margin-top:9px;}
  .prog>div{height:100%;width:0;background:var(--danger);border-radius:3px;transition:width .3s;}
</style></head><body>
  <div class="wrap">
    <div class="arrow"></div>
    <div class="card">
      <div class="head">__LOGO__<span class="t">Spillway</span></div>
      <div id="items"></div>
      <div class="prog" id="prog" style="display:none;"><div id="bar"></div></div>
      <button id="btn" style="display:none;" onclick="grab()">Stáhnout model</button>
    </div>
  </div>
<script>
  function grab(){
    var b=document.getElementById('btn');
    b.disabled=true; b.textContent='Stahuji…';
    try{ window.webkit.messageHandlers.spillway.postMessage({action:'download'}); }catch(e){}
  }
  function render(s){
    var box=document.getElementById('items'), html='';
    if(!s.model){
      html += '<div class="item"><span class="dot" style="background:var(--danger)"></span>'
           + '<span class="msg"><b>Nefunguje, dokud nestáhneš model</b>'
           + '<small>Přepis běží u tebe v počítači. Stáhne se jednou, 1,6 GB.</small></span></div>';
    }
    if(!s.key){
      html += '<div class="item"><span class="dot" style="background:var(--warn)"></span>'
           + '<span class="msg"><b>Nemáš zadaný API klíč pro AI zpracování</b>'
           + '<small>Bez něj se řeč jen přepíše. S ním ji Claude ještě upraví.</small></span></div>';
    }
    box.innerHTML = html;
    var btn=document.getElementById('btn'), prog=document.getElementById('prog');
    btn.style.display = s.model ? 'none' : 'block';
    if(s.downloading){
      prog.style.display='block';
      document.getElementById('bar').style.width=(s.percent||0)+'%';
      btn.disabled=true; btn.textContent='Stahuji '+(s.percent||0)+' %';
    } else {
      prog.style.display='none';
      btn.disabled=false; btn.textContent='Stáhnout model';
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
            if str(body.get("action", "")) == "download":
                models.add_download_listener(self._owner.on_download_state)
                models.download_async()
        except Exception as exc:  # noqa: BLE001
            print(f"[notice] chyba: {exc}")


class NoticePanel:
    """Kartička s upozorněním vedle jiného okna."""

    W, H = 276, 268

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

    # --- poloha a viditelnost -------------------------------------------------

    @objc.python_method
    def show_beside(self, frame, *, model_ready: bool, has_key: bool) -> None:
        """Ukáže kartičku vlevo od `frame` (rám okna, u kterého má viset).

        Když je vše v pořádku, schová se — ať nevisí zbytečně.
        """
        if model_ready and has_key:
            self.hide()
            return
        state = {"model": model_ready, "key": has_key,
                 **models.download_state()}
        self._last = state
        self._render(state)

        x = float(frame.origin.x) - self.W + 4.0
        y = float(frame.origin.y) + float(frame.size.height) - self.H - 6.0
        screens = NSScreen.screens()
        if screens:
            left = float(screens[0].frame().origin.x)
            if x < left + 4.0:                       # vlevo není místo → doprava
                x = float(frame.origin.x) + float(frame.size.width) - 4.0
        self.panel.setFrameOrigin_(NSMakePoint(x, y))
        if not self._visible:
            self.panel.orderFrontRegardless()
            self._visible = True

    @objc.python_method
    def hide(self) -> None:
        if self._visible:
            self.panel.orderOut_(None)
            self._visible = False
