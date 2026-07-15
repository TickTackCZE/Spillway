"""Okno nastavení Spillway (Domovoy design) — WKWebView + JS↔Python most.

Klik na ikonu v liště → toto okno. Vše se nastavuje tady (ne v menu). HTML je
v Domovoy stylu (Půlnoční paleta, accent #818CF8), ovládání posílá zprávy do
Pythonu přes `window.webkit.messageHandlers.spillway`.
"""

from __future__ import annotations

import json

import keyring
import objc
from AppKit import (
    NSApp,
    NSApplicationActivationPolicyAccessory,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSColor,
    NSMakeRect,
    NSObject,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskTitled,
)
from WebKit import WKWebView, WKWebViewConfiguration

from . import autostart, config, design, settings
from .config import KEYRING_ACCOUNT, KEYRING_SERVICE

_LOGO = design.logo_svg(color="#818CF8", width=30, height=30, drops=False)

_HTML = r"""<!DOCTYPE html><html lang="cs"><head><meta charset="UTF-8"><style>
  *{margin:0;padding:0;box-sizing:border-box;}
  :root{--bg:#0F1117;--surface:#1A1F2E;--surface2:#252D42;--text:#E2E8F0;--muted:#64748B;
    --accent:#818CF8;--border:rgba(129,140,248,0.2);--success:#4ADE80;}
  html,body{background:var(--bg);}
  body{font-family:-apple-system,'Raleway',sans-serif;color:var(--text);padding:22px;}
  .head{display:flex;align-items:center;gap:12px;margin-bottom:4px;}
  .head svg{display:block;} .head .name{font-size:19px;font-weight:700;letter-spacing:4px;}
  .head .sub{font-size:9px;letter-spacing:3px;text-transform:uppercase;color:var(--muted);margin-top:2px;}
  .card{background:var(--surface);border:0.5px solid var(--border);border-radius:12px;padding:16px;margin-top:14px;}
  .card h3{font-size:11px;font-weight:600;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:12px;}
  .pills{display:flex;gap:8px;}
  .pill{flex:1;border:0.5px solid var(--border);border-radius:9px;padding:11px 12px;cursor:pointer;transition:.15s;background:transparent;}
  .pill.active{border-color:var(--accent);background:rgba(129,140,248,0.12);}
  .pill .t{font-size:13px;font-weight:600;} .pill .d{font-size:11px;color:var(--muted);margin-top:2px;}
  .field{display:flex;gap:8px;}
  input,textarea{flex:1;background:var(--bg);border:0.5px solid var(--border);border-radius:9px;color:var(--text);
    font-family:inherit;font-size:13px;padding:9px 11px;outline:none;resize:vertical;}
  input:focus,textarea:focus{border-color:var(--accent);}
  .btn{background:var(--accent);color:#0F1117;border:none;border-radius:9px;padding:9px 16px;font-weight:600;font-size:13px;cursor:pointer;font-family:inherit;}
  .hint{font-size:11px;color:var(--muted);margin-top:8px;line-height:1.5;}
  .status{font-size:11px;margin-top:8px;display:flex;align-items:center;gap:6px;color:var(--muted);}
  .status .dot{width:7px;height:7px;border-radius:50%;background:var(--success);}
  .rowt{display:flex;align-items:center;justify-content:space-between;padding:9px 0;gap:12px;}
  .rowt:not(:last-child){border-bottom:0.5px solid var(--border);}
  .rowt .l{font-size:13px;} .rowt .l small{display:block;font-size:11px;color:var(--muted);margin-top:1px;}
  .sw{width:38px;height:22px;border-radius:11px;background:var(--surface2);position:relative;cursor:pointer;transition:.15s;flex-shrink:0;}
  .sw.on{background:var(--accent);}
  .sw::after{content:'';position:absolute;top:2px;left:2px;width:18px;height:18px;border-radius:50%;background:#fff;transition:.15s;}
  .sw.on::after{left:18px;}
  .foot{font-size:9px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);text-align:center;margin-top:18px;}
</style></head><body>
  <div class="head">__LOGO__<div><div class="name">SPILLWAY</div><div class="sub">Nastavení</div></div></div>

  <div class="card"><h3>Model úpravy</h3>
    <div class="pills">
      <div class="pill" data-model="claude-haiku-4-5" onclick="pickModel(this)"><div class="t">Haiku</div><div class="d">rychlé · levné</div></div>
      <div class="pill" data-model="claude-sonnet-5" onclick="pickModel(this)"><div class="t">Sonnet</div><div class="d">chytřejší · dražší</div></div>
    </div>
  </div>

  <div class="card"><h3>Anthropic API klíč</h3>
    <div class="field"><input id="key" type="password" placeholder="sk-ant-…"><button class="btn" onclick="saveKey()">Uložit</button></div>
    <div class="status" id="keystatus"></div>
  </div>

  <div class="card"><h3>Slovník výrazů</h3>
    <textarea id="gloss" rows="3" placeholder="commit, pull request, repository…" onchange="saveGloss()"></textarea>
    <div class="hint">Termíny oddělené čárkou — zůstanou beze změny a přeslechy se opraví k nim.</div>
  </div>

  <div class="card"><h3>Chování</h3>
    <div class="rowt"><div class="l">Spouštět po přihlášení<small>Běží na pozadí po startu Macu</small></div><div class="sw" data-key="autostart" onclick="tog(this)"></div></div>
    <div class="rowt"><div class="l">Číst kontext pole<small>Formátování dle obsahu (e-mail) — text jde k Anthropic</small></div><div class="sw" data-key="field_context" onclick="tog(this)"></div></div>
    <div class="rowt"><div class="l">Chytrá mezera<small>Mezera před textem, když jsi na konci slova</small></div><div class="sw" data-key="auto_space" onclick="tog(this)"></div></div>
  </div>

  <div class="foot">Spillway · v0.1 · klávesa F5</div>

<script>
  function send(m){ try{ window.webkit.messageHandlers.spillway.postMessage(m); }catch(e){} }
  function pickModel(el){ document.querySelectorAll('.pill').forEach(p=>p.classList.remove('active')); el.classList.add('active'); send({action:'model',value:el.dataset.model}); }
  function saveKey(){ var v=document.getElementById('key').value; if(v.trim()){ send({action:'apikey',value:v.trim()}); document.getElementById('key').value=''; } }
  function saveGloss(){ send({action:'glossary',value:document.getElementById('gloss').value}); }
  function tog(el){ var on=!el.classList.contains('on'); el.classList.toggle('on',on); send({action:'toggle',key:el.dataset.key,value:on}); }
  function applyState(s){
    document.querySelectorAll('.pill').forEach(p=>p.classList.toggle('active', p.dataset.model===s.model));
    document.getElementById('keystatus').innerHTML = s.has_key
      ? '<span class="dot"></span>Klíč je nastavený (Keychain)'
      : '<span class="dot" style="background:#E11D48"></span>Klíč není nastavený';
    document.getElementById('gloss').value = s.glossary || '';
    [['autostart',s.autostart],['field_context',s.field_context],['auto_space',s.auto_space]].forEach(function(kv){
      var el=document.querySelector('.sw[data-key="'+kv[0]+'"]'); if(el) el.classList.toggle('on', !!kv[1]);
    });
  }
  window.addEventListener('DOMContentLoaded', function(){ send({action:'ready'}); });
</script>
</body></html>""".replace("__LOGO__", _LOGO)


class _Bridge(NSObject):
    def initWithController_(self, controller):  # noqa: N802
        self = objc.super(_Bridge, self).init()
        if self is None:
            return None
        self.controller = controller
        self.webview = None
        return self

    def userContentController_didReceiveScriptMessage_(self, ucc, message):  # noqa: N802
        try:
            raw = message.body()
            body = dict(raw) if hasattr(raw, "keys") else {}
            action = str(body.get("action", ""))
            if action == "ready":
                self._push_state()
            elif action == "model":
                mid = str(body.get("value", ""))
                if mid:
                    settings.set("model", mid)
                    self.controller.set_model(mid)
            elif action == "apikey":
                key = str(body.get("value", "")).strip()
                if key:
                    keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, key)
                    self.controller.set_api_key(key)
                    self._push_state()
            elif action == "glossary":
                text = str(body.get("value", "")).replace("\n", ",")
                terms = [t.strip() for t in text.split(",") if t.strip()]
                settings.set("glossary", terms)
                self.controller.set_glossary(terms)
            elif action == "toggle":
                key = str(body.get("key", ""))
                val = bool(body.get("value"))
                if key == "autostart":
                    (autostart.enable if val else autostart.disable)()
                elif key in ("field_context", "auto_space"):
                    settings.set(key, val)
        except Exception as exc:  # noqa: BLE001
            print(f"[settings] bridge error: {exc}")

    def _push_state(self) -> None:
        if self.webview is None:
            return
        state = {
            "model": config.get_model(),
            "has_key": bool(config.get_api_key()),
            "glossary": ", ".join(config.glossary()),
            "autostart": autostart.is_enabled(),
            "field_context": config.field_context(),
            "auto_space": config.auto_space(),
        }
        js = "applyState(" + json.dumps(state, ensure_ascii=False) + ")"
        self.webview.evaluateJavaScript_completionHandler_(js, None)


class _WinDelegate(NSObject):
    def windowWillClose_(self, notification):  # noqa: N802
        # Po zavření okna zpět na menu bar app (bez ikony v Docku).
        try:
            NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        except Exception:  # noqa: BLE001
            pass


class SettingsWindow:
    def __init__(self, controller):  # noqa: ANN001
        self.bridge = _Bridge.alloc().initWithController_(controller)
        cfg = WKWebViewConfiguration.alloc().init()
        cfg.userContentController().addScriptMessageHandler_name_(self.bridge, "spillway")

        rect = NSMakeRect(0, 0, 480, 700)
        self.web = WKWebView.alloc().initWithFrame_configuration_(rect, cfg)
        self.bridge.webview = self.web
        self.web.loadHTMLString_baseURL_(_HTML, None)

        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
        )
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False
        )
        self.window.setTitle_("Spillway")
        self.window.setContentView_(self.web)
        self.window.setReleasedWhenClosed_(False)
        self._delegate = _WinDelegate.alloc().init()
        self.window.setDelegate_(self._delegate)
        try:
            self.window.setBackgroundColor_(NSColor.colorWithSRGBRed_green_blue_alpha_(
                0x0F / 255, 0x11 / 255, 0x17 / 255, 1.0
            ))
        except Exception:  # noqa: BLE001
            pass

    def show(self) -> None:
        # Menu bar app běží jako accessory → dočasně regular, ať okno dostane fokus.
        try:
            NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        except Exception:  # noqa: BLE001
            pass
        self.window.center()
        self.window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
