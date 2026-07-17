"""Okno nastavení Spillway (Domovoy design) — WKWebView + JS↔Python most.

Klik na ikonu v liště → toto okno. Vše se nastavuje a ukládá tady (settings.json
+ Keychain pro klíč). Podporuje světlý/tmavý režim (Systém/Light/Dark, Domovoy
palety Ledová/Půlnoční), výběr primárního jazyka, model, slovník a přepínače.
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

from PyObjCTools import AppHelper

from . import autostart, config, design, keymap, settings, stats
from .config import KEYRING_ACCOUNT, KEYRING_SERVICE

_LOGO = design.logo_svg(color="#818CF8", width=30, height=30, drops=False)

_LANGS = [
    ("cs", "Čeština"), ("en", "Angličtina"), ("sk", "Slovenština"),
    ("de", "Němčina"), ("es", "Španělština"), ("fr", "Francouzština"),
    ("pl", "Polština"), ("it", "Italština"), ("uk", "Ukrajinština"), ("ru", "Ruština"),
]
_LANG_OPTIONS = "".join(f'<option value="{c}">{n}</option>' for c, n in _LANGS)

_HTML = r"""<!DOCTYPE html><html lang="cs"><head><meta charset="UTF-8"><style>
  *{margin:0;padding:0;box-sizing:border-box;}
  :root{ /* DARK · Půlnoční (výchozí) */
    --bg:#0F1117;--surface:#1A1F2E;--surface2:#252D42;--text:#E2E8F0;--muted:#64748B;
    --accent:#818CF8;--border:rgba(129,140,248,0.2);--onaccent:#0F1117;--success:#4ADE80;--danger:#E11D48;}
  @media (prefers-color-scheme: light){ :root:not([data-theme]){
    --bg:#F8FAFC;--surface:#FFFFFF;--surface2:#E9EEF5;--text:#1E293B;--muted:#64748B;
    --accent:#3B82F6;--border:rgba(59,130,246,0.15);--onaccent:#FFFFFF;--success:#16A34A;--danger:#E11D48;} }
  :root[data-theme="light"]{
    --bg:#F8FAFC;--surface:#FFFFFF;--surface2:#E9EEF5;--text:#1E293B;--muted:#64748B;
    --accent:#3B82F6;--border:rgba(59,130,246,0.15);--onaccent:#FFFFFF;--success:#16A34A;--danger:#E11D48;}
  html,body{background:var(--bg);}
  body{font-family:-apple-system,'Raleway',sans-serif;color:var(--text);padding:22px;}
  .head{display:flex;align-items:center;gap:12px;margin-bottom:4px;}
  .head svg{display:block;} .head .name{font-size:19px;font-weight:700;letter-spacing:4px;}
  .head .sub{font-size:9px;letter-spacing:3px;text-transform:uppercase;color:var(--muted);margin-top:2px;}
  .card{background:var(--surface);border:0.5px solid var(--border);border-radius:12px;padding:16px;margin-top:14px;}
  .card h3{font-size:11px;font-weight:600;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:12px;}
  .seg{display:flex;background:var(--surface2);border-radius:9px;padding:3px;gap:3px;}
  .seg button{flex:1;border:none;background:transparent;color:var(--muted);font-family:inherit;font-size:12px;font-weight:600;padding:7px;border-radius:7px;cursor:pointer;}
  .seg button.active{background:var(--surface);color:var(--text);}
  .pills{display:flex;gap:8px;}
  .pill{flex:1;border:0.5px solid var(--border);border-radius:9px;padding:11px 12px;cursor:pointer;transition:.15s;background:transparent;}
  .pill.active{border-color:var(--accent);background:rgba(129,140,248,0.12);}
  .pill .t{font-size:13px;font-weight:600;} .pill .d{font-size:11px;color:var(--muted);margin-top:2px;}
  .field{display:flex;gap:8px;}
  input,textarea,select{width:100%;background:var(--bg);border:0.5px solid var(--border);border-radius:9px;color:var(--text);
    font-family:inherit;font-size:13px;padding:9px 11px;outline:none;}
  textarea{resize:vertical;min-height:84px;line-height:1.5;}
  input:focus,textarea:focus,select:focus{border-color:var(--accent);}
  .btn{background:var(--accent);color:var(--onaccent);border:none;border-radius:9px;padding:9px 16px;font-weight:600;font-size:13px;cursor:pointer;font-family:inherit;white-space:nowrap;}
  .btn.danger{background:transparent;border:0.5px solid var(--danger);color:var(--danger);}
  .hint{font-size:11px;color:var(--muted);margin-top:8px;line-height:1.5;}
  .status{font-size:12px;margin-bottom:10px;display:flex;align-items:center;gap:7px;color:var(--text);}
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

  <div class="card"><h3>Klávesy</h3>
    <div class="rowt">
      <div class="l">Diktování<small>Podrž, mluv, pusť → text se vloží</small></div>
      <div class="field" style="width:auto;align-items:center;gap:8px;">
        <span class="l" id="hotkeyLabel" style="color:var(--accent);font-weight:600;">F5</span>
        <button class="btn" id="hotkeyBtn" onclick="recordHotkey()">Změnit</button>
      </div>
    </div>
    <div class="rowt">
      <div class="l">Zrušit zpracování<small>Zahodí diktát dřív, než se zaplatí AI úprava</small></div>
      <div class="field" style="width:auto;align-items:center;gap:8px;">
        <span class="l" id="cancelLabel" style="color:var(--accent);font-weight:600;">Escape</span>
        <button class="btn" id="cancelBtn" onclick="recordCancel()">Změnit</button>
      </div>
    </div>
    <div class="hint">Klikni na Změnit a stiskni novou klávesu (funguje kdekoliv v systému). Rušicí klávesa se spolkne jen během zpracování — jinde funguje normálně.</div>
  </div>

  <div class="card"><h3>Statistiky</h3>
    <div id="statsEmpty" class="hint" style="margin:0;">Zatím žádný diktát — až budeš diktovat, uvidíš tu, kolik času jsi ušetřil.</div>
    <div id="statsBody" style="display:none;">
      <div class="rowt">
        <div class="l">Ušetřený čas<small id="statsSavedSub">oproti psaní na klávesnici</small></div>
        <div class="l" id="statsSaved" style="color:var(--accent);font-weight:600;">—</div>
      </div>
      <div class="rowt">
        <div class="l">Diktátů<small id="statsWords">—</small></div>
        <div class="l" id="statsCount" style="font-weight:600;">—</div>
      </div>
      <div class="rowt" id="statsPromptRow">
        <div class="l">Zhuštění promptů<small>O kolik se diktát zkrátil do AI (profil „ai“)</small></div>
        <div class="l" id="statsPrompt" style="color:var(--accent);font-weight:600;">—</div>
      </div>
      <div class="rowt" id="statsAppsRow" style="border:none;">
        <div class="l">Nejčastěji<small id="statsApps">—</small></div>
      </div>
    </div>
  </div>

  <div class="card"><h3>Model úpravy</h3>
    <div class="pills">
      <div class="pill" data-model="claude-haiku-4-5" onclick="pickModel(this)"><div class="t">Haiku</div><div class="d">rychlé · levné</div></div>
      <div class="pill" data-model="claude-sonnet-5" onclick="pickModel(this)"><div class="t">Sonnet</div><div class="d">chytřejší · dražší</div></div>
    </div>
  </div>

  <div class="card"><h3>Primární jazyk (řeč)</h3>
    <select id="lang" onchange="send({action:'language',value:this.value})">__LANGS__</select>
  </div>

  <div class="card"><h3>Anthropic API klíč</h3>
    <div id="keyset" style="display:none">
      <div class="status"><span class="dot"></span>Klíč je nastavený (uložený v Keychain)</div>
      <button class="btn danger" onclick="send({action:'delkey'})">Smazat klíč</button>
    </div>
    <div id="keyunset" style="display:none">
      <div class="field"><input id="key" type="password" placeholder="sk-ant-…"><button class="btn" onclick="saveKey()">Uložit</button></div>
      <div class="hint">Klíč se uloží do macOS Keychain, ne do souboru.</div>
    </div>
  </div>

  <div class="card"><h3>Slovník výrazů</h3>
    <textarea id="gloss" rows="4" placeholder="commit, pull request, repository, Trackio…" onchange="saveGloss()"></textarea>
    <div class="hint">Termíny oddělené čárkou — zůstanou beze změny a přeslechy se opraví k nim.</div>
  </div>

  <div class="card"><h3>Chování</h3>
    <div class="rowt"><div class="l">Spouštět po přihlášení<small>Běží na pozadí po startu Macu</small></div><div class="sw" data-key="autostart" onclick="tog(this)"></div></div>
    <div class="rowt"><div class="l">Číst kontext pole<small>Formátování dle obsahu (e-mail) — text jde k Anthropic</small></div><div class="sw" data-key="field_context" onclick="tog(this)"></div></div>
    <div class="rowt"><div class="l">Chytrá mezera<small>Mezera před textem, když jsi na konci slova</small></div><div class="sw" data-key="auto_space" onclick="tog(this)"></div></div>
  </div>

  <div class="card"><h3>Vzhled</h3>
    <div class="seg" id="seg">
      <button data-theme="system" onclick="setTheme('system')">Systém</button>
      <button data-theme="light" onclick="setTheme('light')">Světlý</button>
      <button data-theme="dark" onclick="setTheme('dark')">Tmavý</button>
    </div>
  </div>

  <div class="foot">Spillway · v0.1</div>

<script>
  function send(m){ try{ window.webkit.messageHandlers.spillway.postMessage(m); }catch(e){} }
  function recordHotkey(){
    document.getElementById('hotkeyBtn').textContent = 'Stiskni klávesu…';
    document.getElementById('hotkeyBtn').disabled = true;
    document.getElementById('hotkeyLabel').textContent = '…';
    send({action:'record_hotkey'});
  }
  function recordCancel(){
    document.getElementById('cancelBtn').textContent = 'Stiskni klávesu…';
    document.getElementById('cancelBtn').disabled = true;
    document.getElementById('cancelLabel').textContent = '…';
    send({action:'record_cancel'});
  }
  // `which` = 'hotkey' | 'cancel' — jeden pár funkcí pro obě klávesy.
  function applyHotkey(h){
    var which = h.which || 'hotkey';
    document.getElementById(which+'Btn').textContent = 'Změnit';
    document.getElementById(which+'Btn').disabled = false;
    document.getElementById(which+'Label').textContent = h.label;
  }
  function cancelHotkey(which){
    which = which || 'hotkey';
    document.getElementById(which+'Btn').textContent = 'Změnit';
    document.getElementById(which+'Btn').disabled = false;
  }
  function applyStats(st){
    var has = st && st.count > 0;
    document.getElementById('statsEmpty').style.display = has ? 'none' : 'block';
    document.getElementById('statsBody').style.display = has ? 'block' : 'none';
    if(!has) return;
    document.getElementById('statsSaved').textContent = st.saved_h;
    document.getElementById('statsSavedSub').textContent = 'napsal bys to za ' + st.typing_h + ', nadiktoval za ' + st.spoken_h;
    document.getElementById('statsCount').textContent = st.count;
    document.getElementById('statsWords').textContent = st.words + ' slov celkem';
    var pr = document.getElementById('statsPromptRow');
    if(st.prompt_saving_pct === null){ pr.style.display='none'; }
    else { pr.style.display='flex'; document.getElementById('statsPrompt').textContent = '−' + st.prompt_saving_pct + ' %'; }
    var ar = document.getElementById('statsAppsRow');
    if(!st.top_apps || !st.top_apps.length){ ar.style.display='none'; }
    else { ar.style.display='flex'; document.getElementById('statsApps').textContent = st.top_apps.map(function(a){return a[0]+' ('+a[1]+')';}).join(' · '); }
  }
  function applyTheme(t){
    if(t==='system'){ document.documentElement.removeAttribute('data-theme'); }
    else { document.documentElement.setAttribute('data-theme', t); }
    document.querySelectorAll('#seg button').forEach(b=>b.classList.toggle('active', b.dataset.theme===t));
  }
  function setTheme(t){ applyTheme(t); send({action:'theme',value:t}); }
  function pickModel(el){ document.querySelectorAll('.pill').forEach(p=>p.classList.remove('active')); el.classList.add('active'); send({action:'model',value:el.dataset.model}); }
  function saveKey(){ var v=document.getElementById('key').value; if(v.trim()){ send({action:'apikey',value:v.trim()}); document.getElementById('key').value=''; } }
  function saveGloss(){ send({action:'glossary',value:document.getElementById('gloss').value}); }
  function tog(el){ var on=!el.classList.contains('on'); el.classList.toggle('on',on); send({action:'toggle',key:el.dataset.key,value:on}); }
  function applyState(s){
    document.getElementById('hotkeyLabel').textContent = s.hotkey_label || 'F5';
    document.getElementById('cancelLabel').textContent = s.cancel_label || 'Escape';
    if(s.stats) applyStats(s.stats);
    applyTheme(s.theme||'system');
    document.querySelectorAll('.pill').forEach(p=>p.classList.toggle('active', p.dataset.model===s.model));
    document.getElementById('lang').value = s.language || 'cs';
    document.getElementById('keyset').style.display = s.has_key ? 'block' : 'none';
    document.getElementById('keyunset').style.display = s.has_key ? 'none' : 'block';
    document.getElementById('gloss').value = s.glossary || '';
    [['autostart',s.autostart],['field_context',s.field_context],['auto_space',s.auto_space]].forEach(function(kv){
      var el=document.querySelector('.sw[data-key="'+kv[0]+'"]'); if(el) el.classList.toggle('on', !!kv[1]);
    });
  }
  window.addEventListener('DOMContentLoaded', function(){ send({action:'ready'}); });
</script>
</body></html>""".replace("__LOGO__", _LOGO).replace("__LANGS__", _LANG_OPTIONS)


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
            elif action == "language":
                lang = str(body.get("value", "")) or "cs"
                settings.set("language", lang)
                self.controller.set_language(lang)
            elif action == "theme":
                settings.set("theme", str(body.get("value", "system")))
            elif action == "apikey":
                key = str(body.get("value", "")).strip()
                if key:
                    keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, key)
                    config.set_api_key_cache(key)  # ať se hned neptá Keychain znovu
                    self.controller.set_api_key(key)
                    self._push_state()
            elif action == "delkey":
                try:
                    keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
                except Exception:  # noqa: BLE001
                    pass
                config.set_api_key_cache(None)
                self.controller.set_api_key(None)
                self._push_state()
            elif action == "glossary":
                text = str(body.get("value", "")).replace("\n", ",")
                terms = [t.strip() for t in text.split(",") if t.strip()]
                settings.set("glossary", terms)
                self.controller.set_glossary(terms)
            elif action in ("record_hotkey", "record_cancel"):
                which = "hotkey" if action == "record_hotkey" else "cancel"
                listener = getattr(self.controller, "hotkey_listener", None)
                started = False
                if listener is not None and getattr(self.controller, "state", "IDLE") == "IDLE":
                    started = listener.start_capture(
                        lambda kc, w=which: self._on_hotkey_captured(kc, w),
                        lambda w=which: self._on_hotkey_cancelled(w),
                    )
                if not started:  # [B6] nahrává se / capture už běží → reset UI
                    self._on_hotkey_cancelled(which)
            elif action == "toggle":
                key = str(body.get("key", ""))
                val = bool(body.get("value"))
                if key == "autostart":
                    (autostart.enable if val else autostart.disable)()
                elif key in ("field_context", "auto_space"):
                    settings.set(key, val)
        except Exception as exc:  # noqa: BLE001
            print(f"[settings] bridge error: {exc}")

    def _on_hotkey_captured(self, keycode: int, which: str = "hotkey") -> None:
        # Voláno z vlákna event tapu → VŠE (i zápis settings [B16]) přehodit na main thread.
        label = keymap.label_for(keycode)

        def _apply() -> None:
            listener = getattr(self.controller, "hotkey_listener", None)
            if which == "cancel":
                settings.set("cancel_keycode", keycode)
                settings.set("cancel_label", label)
                if listener is not None:
                    listener.cancel_keycode = keycode
            else:
                settings.set("hotkey_keycode", keycode)
                settings.set("hotkey_label", label)
                if listener is not None:
                    listener.keycode = keycode
            if self.webview is not None:
                payload = {"keycode": keycode, "label": label, "which": which}
                js = "applyHotkey(" + json.dumps(payload, ensure_ascii=False) + ")"
                self.webview.evaluateJavaScript_completionHandler_(js, None)

        AppHelper.callAfter(_apply)

    def _on_hotkey_cancelled(self, which: str = "hotkey") -> None:
        # [B4] Timeout / zrušené zachytávání → jen resetuj tlačítko v UI.
        def _apply() -> None:
            if self.webview is not None:
                js = "cancelHotkey(" + json.dumps(which) + ")"
                self.webview.evaluateJavaScript_completionHandler_(js, None)

        AppHelper.callAfter(_apply)

    def _push_state(self) -> None:
        if self.webview is None:
            return
        _keycode, hotkey_label = config.get_hotkey()
        _cancel_kc, cancel_label = config.get_cancel_hotkey()
        summary = stats.summary()
        state = {
            "hotkey_label": hotkey_label,
            "cancel_label": cancel_label,
            "stats": {
                "count": summary["count"],
                "words": summary["words"],
                "saved_h": stats.human_duration(summary["saved_s"]),
                "typing_h": stats.human_duration(summary["typing_s"]),
                "spoken_h": stats.human_duration(summary["spoken_s"]),
                "prompt_saving_pct": summary["prompt_saving_pct"],
                "top_apps": summary["top_apps"],
            },
            "theme": config.get_theme(),
            "model": config.get_model(),
            "language": config.get_language(),
            "has_key": bool(config.get_api_key()),
            "glossary": ", ".join(config.glossary()),
            "autostart": autostart.is_enabled(),
            "field_context": config.field_context(),
            "auto_space": config.auto_space(),
        }
        js = "applyState(" + json.dumps(state, ensure_ascii=False) + ")"
        self.webview.evaluateJavaScript_completionHandler_(js, None)


class _WinDelegate(NSObject):
    def initWithController_(self, controller):  # noqa: N802
        self = objc.super(_WinDelegate, self).init()
        if self is None:
            return None
        self.controller = controller
        return self

    def windowWillClose_(self, notification):  # noqa: N802
        # [B4] Zruš probíhající zachytávání klávesy, ať nezůstane „ozbrojené".
        try:
            listener = getattr(self.controller, "hotkey_listener", None)
            if listener is not None:
                listener.cancel_capture()
        except Exception:  # noqa: BLE001
            pass
        try:
            NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        except Exception:  # noqa: BLE001
            pass


class SettingsWindow:
    def __init__(self, controller):  # noqa: ANN001
        self.bridge = _Bridge.alloc().initWithController_(controller)
        cfg = WKWebViewConfiguration.alloc().init()
        cfg.userContentController().addScriptMessageHandler_name_(self.bridge, "spillway")

        rect = NSMakeRect(0, 0, 480, 760)
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
        self._delegate = _WinDelegate.alloc().initWithController_(controller)
        self.window.setDelegate_(self._delegate)

    def show(self) -> None:
        try:
            NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        except Exception:  # noqa: BLE001
            pass
        self.window.center()
        self.window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
