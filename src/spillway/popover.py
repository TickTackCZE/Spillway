"""Popover v liště (Domovoy design) — WKWebView v NSPopoveru pod ikonou.

Levý klik na ikonu → tenhle popover: přehled na první pohled (statistiky, tempo
řeči, náklady za měsíc, 7denní aktivita), historie diktátů s kopírováním klikem,
přepínač modelu úpravy a tlačítka Nastavení… / Konec.

Data tečou přes JS↔Python most (stejný vzor jako `settings_window.py`). Popover
se sám přeměří po naplnění (JS pošle výšku), takže scrolluje jen seznam historie.
"""

from __future__ import annotations

import json
import os
import time as _time

import objc
from AppKit import (
    NSApp,
    NSMakeRect,
    NSMinYEdge,
    NSObject,
    NSPopover,
    NSPopoverBehaviorTransient,
    NSViewController,
)
from WebKit import WKWebView, WKWebViewConfiguration

from PyObjCTools import AppHelper

from . import config, design, stats
from .paste import copy_to_clipboard

_DBG_PATH = os.path.expanduser("~/Library/Logs/Spillway/popover-debug.log")


def _dbg(msg: str) -> None:
    try:
        os.makedirs(os.path.dirname(_DBG_PATH), exist_ok=True)
        with open(_DBG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{_time.strftime('%H:%M:%S')} [pop] {msg}\n")
    except Exception:  # noqa: BLE001
        pass

_LOGO = design.logo_svg(color="#818CF8", width=22, height=24, drops=False)

_HTML = r"""<!DOCTYPE html><html lang="cs"><head><meta charset="UTF-8"><style>
  *{margin:0;padding:0;box-sizing:border-box;}
  :root, :root[data-theme="dark"]{
    --bg:#0F1117;--surface:#1A1F2E;--surface2:#252D42;--text:#E2E8F0;--muted:#94A3B8;--faint:#3B4255;
    --accent:#818CF8;--accent-text:#A5B4FC;--onaccent:#0F1117;--border:rgba(129,140,248,0.20);
    --hair:rgba(129,140,248,0.12);--ok:#4ADE80;--shadow:rgba(0,0,0,0.55);}
  @media (prefers-color-scheme: light){ :root:not([data-theme]){
    --bg:#F8FAFC;--surface:#FFFFFF;--surface2:#EEF2F8;--text:#1E293B;--muted:#64748B;--faint:#CBD5E1;
    --accent:#3B82F6;--accent-text:#2563EB;--onaccent:#FFFFFF;--border:rgba(59,130,246,0.16);
    --hair:rgba(59,130,246,0.10);--ok:#16A34A;--shadow:rgba(30,41,59,0.18);} }
  :root[data-theme="light"]{
    --bg:#F8FAFC;--surface:#FFFFFF;--surface2:#EEF2F8;--text:#1E293B;--muted:#64748B;--faint:#CBD5E1;
    --accent:#3B82F6;--accent-text:#2563EB;--onaccent:#FFFFFF;--border:rgba(59,130,246,0.16);
    --hair:rgba(59,130,246,0.10);--ok:#16A34A;--shadow:rgba(30,41,59,0.18);}
  html,body{background:var(--surface);}
  body{font-family:-apple-system,'Raleway',sans-serif;color:var(--text);width:320px;padding:6px;overflow:hidden;}
  .row{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:9px;}
  .head{padding:11px 10px 9px;}
  .head .logo{flex-shrink:0;} .head .name{font-size:15px;font-weight:700;letter-spacing:.3px;}
  .grow{flex:1;}
  .pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;padding:4px 9px;border-radius:20px;background:var(--surface2);color:var(--text);}
  .pill .dot{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 3px color-mix(in srgb,var(--ok) 22%,transparent);}
  .pill.warn .dot{background:#F59E0B;box-shadow:0 0 0 3px color-mix(in srgb,#F59E0B 22%,transparent);}
  .hero{margin:2px 2px 8px;padding:14px;border-radius:11px;background:var(--surface2);border:0.5px solid var(--hair);text-align:center;}
  .hero .line{font-size:14px;display:flex;align-items:center;justify-content:center;gap:8px;flex-wrap:wrap;margin:2px 0;}
  .kbd{font:inherit;font-size:12px;font-weight:700;color:var(--text);padding:3px 9px;border-radius:7px;background:var(--surface);border:0.5px solid var(--border);box-shadow:0 1.5px 0 var(--faint);}
  .stats{display:flex;padding:4px 2px 8px;}
  .stat{flex:1;text-align:center;padding:4px;position:relative;}
  .stat + .stat::before{content:"";position:absolute;left:0;top:18%;height:64%;width:0.5px;background:var(--hair);}
  .stat b{font-size:19px;font-weight:700;color:var(--accent);font-variant-numeric:tabular-nums;letter-spacing:-.4px;}
  .stat span{display:block;font-size:11px;color:var(--muted);margin-top:1px;}
  .sep{height:0.5px;background:var(--hair);margin:6px 8px;}
  .lbl{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);font-weight:700;padding:6px 12px 3px;display:flex;align-items:center;gap:7px;}
  .panel{margin:4px 2px 8px;background:var(--surface2);border:0.5px solid var(--hair);border-radius:11px;padding:0 6px;}
  .kvrow{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:10px 6px;font-size:13px;}
  .kvrow + .kvrow{border-top:0.5px solid var(--hair);}
  .kvrow > span:first-child{color:var(--muted);white-space:nowrap;}
  .kvrow b{font-weight:600;color:var(--text);text-align:right;font-variant-numeric:tabular-nums;}
  .chart{padding:2px 10px 4px;}
  .barsWrap{position:relative;}
  .bartip{position:absolute;top:-4px;transform:translate(-50%,-100%);background:rgba(15,17,23,0.96);color:#F5F5F7;
    font-size:11px;font-weight:600;white-space:nowrap;padding:3px 8px;border-radius:6px;pointer-events:none;
    opacity:0;transition:opacity .1s;box-shadow:0 2px 8px rgba(0,0,0,.4);z-index:5;}
  .bartip.show{opacity:1;}
  .bars{display:flex;align-items:flex-end;gap:6px;height:42px;}
  .bars .b{cursor:default;}
  .bars .b{flex:1;background:color-mix(in srgb,var(--accent) 32%,transparent);border-radius:3px 3px 0 0;min-height:3px;}
  .bars .b.hi{background:var(--accent);}
  .days{display:flex;gap:6px;margin-top:5px;}
  .days span{flex:1;text-align:center;font-size:9px;color:var(--muted);font-variant-numeric:tabular-nums;}
  .scroll{max-height:150px;overflow-y:auto;margin:0 2px;}
  .scroll::-webkit-scrollbar{width:8px;}
  .scroll::-webkit-scrollbar-thumb{background:var(--surface2);border-radius:8px;border:2px solid var(--surface);}
  .scroll::-webkit-scrollbar-track{background:transparent;}
  .empty{font-size:12px;color:var(--muted);padding:6px 12px 10px;}
  .hrow{display:flex;align-items:center;gap:10px;padding:8px;border-radius:9px;cursor:pointer;}
  .hrow:hover{background:var(--surface2);}
  .hrow .av{width:19px;height:19px;border-radius:5px;flex-shrink:0;display:grid;place-items:center;font-size:10px;font-weight:700;color:var(--accent-text);background:color-mix(in srgb,var(--accent) 18%,transparent);}
  .hrow .txt{flex:1;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .hrow .age{font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums;flex-shrink:0;}
  .hrow .cpy{font-size:11px;font-weight:600;color:var(--accent-text);opacity:0;flex-shrink:0;}
  .hrow:hover .age{display:none;} .hrow:hover .cpy{opacity:1;}
  .seg{display:flex;background:var(--bg);border:0.5px solid var(--hair);border-radius:8px;padding:3px;gap:3px;margin:2px;}
  .seg button{flex:1;border:0.5px solid transparent;background:transparent;color:var(--muted);font:inherit;font-size:12px;font-weight:600;padding:6px;border-radius:6px;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:6px;}
  .seg button.on{background:var(--surface2);color:var(--text);border-color:var(--border);box-shadow:0 1px 3px var(--shadow);}
  .seg small{color:var(--muted);font-weight:500;}
  .metaline{font-size:11px;color:var(--muted);text-align:center;padding:6px 0 4px;display:flex;align-items:center;justify-content:center;gap:7px;}
  .metaline .gpu{color:var(--accent-text);font-weight:600;}
  .foot{display:flex;gap:6px;padding:4px 2px 2px;}
  .foot button{flex:1;border:0.5px solid var(--border);background:transparent;color:var(--text);font:inherit;font-size:13px;font-weight:600;padding:9px;border-radius:9px;cursor:pointer;}
  .foot button.primary{background:var(--accent);color:var(--onaccent);border-color:transparent;}
  #toast{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);background:var(--accent);color:var(--onaccent);
    font-size:12px;font-weight:600;padding:7px 14px;border-radius:20px;opacity:0;transition:opacity .18s;pointer-events:none;box-shadow:0 4px 14px var(--shadow);}
  #toast.show{opacity:1;}
</style></head><body>
  <div class="row head">
    __LOGO__<span class="name">Spillway</span><span class="grow"></span>
    <span class="pill" id="statusPill"><span class="dot"></span><span id="statusText">Připraveno</span></span>
  </div>

  <div class="hero"><div class="line">Podrž <span class="kbd" id="hotkeyKbd">F5</span> a mluv</div></div>

  <div class="stats">
    <div class="stat"><b id="stCount">—</b><span>diktátů</span></div>
    <div class="stat"><b id="stWords">—</b><span>slov</span></div>
    <div class="stat"><b id="stTime">—</b><span>namluveno</span></div>
  </div>

  <div class="panel">
    <div class="kvrow"><span>Náklady (tento měsíc)</span><b id="kvCost">—</b></div>
    <div class="kvrow"><span>Ø tempo řeči</span><b id="kvTempo">—</b></div>
    <div class="kvrow"><span>Nejčastější</span><b id="kvTop">—</b></div>
  </div>

  <div class="sep"></div>
  <div class="lbl">Aktivita · 7 dní</div>
  <div class="chart">
    <div class="barsWrap"><div class="bars" id="bars"></div><div class="bartip" id="bartip"></div></div>
    <div class="days" id="days"></div>
  </div>

  <div class="sep"></div>
  <div class="lbl">Historie</div>
  <div class="empty" id="histEmpty" style="display:none;">Zatím žádný diktát — jak budeš diktovat, objeví se tu.</div>
  <div class="scroll" id="hist"></div>

  <div class="sep"></div>
  <div class="lbl">Model úpravy</div>
  <div class="seg" id="modelSeg">
    <button data-model="claude-haiku-4-5" onclick="pickModel(this)">Haiku <small>rychlé</small></button>
    <button data-model="claude-sonnet-5" onclick="pickModel(this)">Sonnet <small>chytřejší</small></button>
  </div>
  <div class="metaline" id="gpuLine"><span class="gpu">⚡ GPU</span> · model načten</div>

  <div class="foot">
    <button class="primary" onclick="send({action:'open_settings'})">Nastavení…</button>
    <button onclick="send({action:'quit'})">Konec</button>
  </div>

  <div id="toast">Zkopírováno</div>

<script>
  function send(m){ try{ window.webkit.messageHandlers.spillway.postMessage(m); }catch(e){} }
  function esc(s){ var d=document.createElement('div'); d.textContent=s==null?'':String(s); return d.innerHTML; }
  var _toastT=null;
  function toast(msg){
    var t=document.getElementById('toast'); t.textContent=msg||'Zkopírováno'; t.classList.add('show');
    if(_toastT) clearTimeout(_toastT); _toastT=setTimeout(function(){ t.classList.remove('show'); }, 1300);
  }
  function pickModel(el){
    document.querySelectorAll('#modelSeg button').forEach(function(b){ b.classList.remove('on'); });
    el.classList.add('on'); send({action:'model', value:el.dataset.model});
  }
  function copyItem(i){ send({action:'copy', i:i}); }
  function applyTheme(t){
    if(t==='light'||t==='dark'){ document.documentElement.setAttribute('data-theme', t); }
    else { document.documentElement.removeAttribute('data-theme'); }
  }
  function pluralDiktat(n){ n=Math.abs(n); if(n===1) return 'diktát'; if(n>=2&&n<=4) return 'diktáty'; return 'diktátů'; }
  function renderBars(a){
    var max=1; a.forEach(function(x){ if(x.v>max) max=x.v; });
    var bars=document.getElementById('bars'), tip=document.getElementById('bartip');
    bars.innerHTML=a.map(function(x){
      var h=Math.max(4, Math.round(x.v/max*100)); var hi=(x.v===max&&max>0)?' hi':'';
      return '<div class="b'+hi+'" data-d="'+esc(x.d)+'" data-v="'+x.v+'" style="height:'+h+'%"></div>';
    }).join('');
    document.getElementById('days').innerHTML=a.map(function(x){ return '<span>'+esc(x.d)+'</span>'; }).join('');
    // Hover na sloupec → tooltip s hodnotou a metrikou (nad grafem, u daného dne).
    Array.prototype.forEach.call(bars.children, function(bar){
      bar.addEventListener('mouseenter', function(){
        var v=parseInt(bar.dataset.v,10)||0;
        tip.textContent=bar.dataset.d+' · '+v+' '+pluralDiktat(v);
        tip.style.left=(bar.offsetLeft+bar.offsetWidth/2)+'px';
        tip.classList.add('show');
      });
      bar.addEventListener('mouseleave', function(){ tip.classList.remove('show'); });
    });
  }
  function renderHist(items){
    var box=document.getElementById('hist'); var empty=document.getElementById('histEmpty');
    if(!items||!items.length){ box.innerHTML=''; box.style.display='none'; empty.style.display='block'; return; }
    empty.style.display='none'; box.style.display='block';
    box.innerHTML=items.map(function(it,i){
      return '<div class="hrow" onclick="copyItem('+i+')" title="Klik zkopíruje">'
        +'<span class="av">'+esc(it.avatar)+'</span>'
        +'<span class="txt">'+esc(it.snippet)+'</span>'
        +'<span class="age">'+esc(it.age)+'</span><span class="cpy">Kopírovat</span></div>';
    }).join('');
  }
  function applyState(s){
    applyTheme(s.theme||'system');
    document.getElementById('hotkeyKbd').textContent = s.hotkey_label || 'F5';
    var pill=document.getElementById('statusPill'), txt=document.getElementById('statusText');
    txt.textContent = s.status_text || 'Připraveno';
    pill.classList.toggle('warn', !!s.status_warn);
    var st=s.stats||{};
    document.getElementById('stCount').textContent = st.count!=null ? st.count : '—';
    document.getElementById('stWords').textContent = st.words_h || '—';
    document.getElementById('stTime').textContent = st.dictation_h || '—';
    document.getElementById('kvCost').textContent = st.cost_h || '$0,00';
    document.getElementById('kvTempo').textContent = st.tempo_h || '—';
    document.getElementById('kvTop').textContent = st.top_h || '—';
    renderBars(st.activity_7d||[]);
    renderHist(s.recent||[]);
    document.querySelectorAll('#modelSeg button').forEach(function(b){ b.classList.toggle('on', b.dataset.model===s.model); });
    var g=document.getElementById('gpuLine');
    g.innerHTML = s.gpu_loaded ? '<span class="gpu">⚡ GPU</span> · model načten · přepis ~1 s'
                               : '<span class="gpu">⚡ GPU</span> · model uvolněn · načte se při diktátu';
    // Popover se přizpůsobí obsahu (scrolluje jen historie).
    requestAnimationFrame(function(){ send({action:'resize', h: document.body.scrollHeight}); });
  }
  window.addEventListener('DOMContentLoaded', function(){ send({action:'ready'}); });
</script>
</body></html>""".replace("__LOGO__", _LOGO)


class _PopBridge(NSObject):
    def initWithController_popover_(self, controller, popover):  # noqa: N802
        self = objc.super(_PopBridge, self).init()
        if self is None:
            return None
        self.controller = controller
        self.popover = popover
        self.webview = None
        self._recent: list[dict] = []
        self.on_open_settings = None  # nastaví tray
        self.on_quit = None
        return self

    def userContentController_didReceiveScriptMessage_(self, ucc, message):  # noqa: N802
        try:
            raw = message.body()
            body = dict(raw) if hasattr(raw, "keys") else {}
            action = str(body.get("action", ""))
            if action == "ready":
                self.push_state()
            elif action == "resize":
                self._resize(body.get("h"))
            elif action == "model":
                mid = str(body.get("value", ""))
                if mid:
                    from . import settings

                    settings.set("model", mid)
                    self.controller.set_model(mid)
            elif action == "copy":
                self._copy(body.get("i"))
            elif action == "open_settings":
                self.popover.close()
                if self.on_open_settings is not None:
                    self.on_open_settings()
            elif action == "quit":
                self.popover.close()
                if self.on_quit is not None:
                    self.on_quit()
        except Exception as exc:  # noqa: BLE001 — popover most nesmí nikdy shodit appku
            print(f"[popover] bridge error: {exc}")

    @objc.python_method
    def _resize(self, h) -> None:
        try:
            height = int(float(h))
        except (TypeError, ValueError):
            return
        # Výška obsahu + drobná rezerva; strop, ať se popover vejde na obrazovku.
        height = max(320, min(height + 12, 760))
        self.popover.setContentSize_((320, height))

    @objc.python_method
    def _copy(self, i) -> None:
        try:
            idx = int(i)
        except (TypeError, ValueError):
            return
        if 0 <= idx < len(self._recent):
            text = self._recent[idx].get("text", "")
            if text:
                copy_to_clipboard(text)
                if self.webview is not None:
                    self.webview.evaluateJavaScript_completionHandler_("toast('Zkopírováno')", None)

    def push_state(self) -> None:
        if self.webview is None:
            return
        _kc, hotkey_label = config.get_hotkey()
        summary = stats.summary()
        self._recent = stats.recent(10)
        loaded = False
        try:
            loaded = bool(getattr(self.controller.transcriber, "is_loaded", False))
        except Exception:  # noqa: BLE001
            loaded = False
        has_key = bool(config.get_api_key())
        listener = getattr(self.controller, "hotkey_listener", None)
        tap_ok = getattr(listener, "tap_ok", None) if listener is not None else None
        if tap_ok is False:
            status_text, status_warn = "Klávesa nefunguje", True
        elif not has_key:
            status_text, status_warn = "Bez API klíče", True
        else:
            status_text, status_warn = "Připraveno", False
        # Krátký popisek klávesy do hero („F5 (diktování)" → „F5").
        short_key = (hotkey_label or "F5").split(" ")[0]
        top = summary["top_apps"]
        state = {
            "theme": config.get_theme(),
            "hotkey_label": short_key,
            "status_text": status_text,
            "status_warn": status_warn,
            "model": config.get_model(),
            "gpu_loaded": loaded,
            "stats": {
                "count": summary["count"],
                "words_h": _human_count(summary["words"]),
                "dictation_h": _human_short_duration(summary["dictation_s"]),
                "cost_h": stats.human_cost(summary["cost_month"]),
                "tempo_h": (f"{summary['tempo_wpm']} sl/min" if summary["tempo_wpm"] else "—"),
                "top_h": (" · ".join(a[0] for a in top[:3]) if top else "—"),
                "activity_7d": summary["activity_7d"],
            },
            # Do WKWebView jen náhledy (avatar/snippet/age) — plný text diktátu si
            # necháváme na Python straně (self._recent) pro kopírování přes most,
            # ať se celý obsah zbytečně nesype do JS.
            "recent": [
                {"avatar": r["avatar"], "snippet": r["snippet"], "age": r["age"]}
                for r in self._recent
            ],
        }
        js = "applyState(" + json.dumps(state, ensure_ascii=False) + ")"
        self.webview.evaluateJavaScript_completionHandler_(js, None)


def _human_count(n: int) -> str:
    """1234 → „1,2k" (do hero dlaždice, ať se vejde)."""
    n = int(n or 0)
    if n < 1000:
        return str(n)
    return (f"{n / 1000:.1f}").replace(".", ",").rstrip("0").rstrip(",") + "k"


def _human_short_duration(seconds: float) -> str:
    """Sekundy → krátce do dlaždice: „42 m", „3 h", „18 s"."""
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h} h"
    if m:
        return f"{m} m"
    return f"{sec} s"


class _ButtonHandler(NSObject):
    """Cíl akce tlačítka status itemu — přepíná popover."""

    def initWithPopoverController_(self, popctl):  # noqa: N802
        self = objc.super(_ButtonHandler, self).init()
        if self is None:
            return None
        self.popctl = popctl
        return self

    def togglePopover_(self, sender):  # noqa: N802
        self.popctl.toggle(sender)


class PopoverController:
    """Vlastní NSPopover s WKWebView, napojený na tlačítko status itemu."""

    def __init__(self, controller, *, on_open_settings=None, on_quit=None):  # noqa: ANN001
        cfg = WKWebViewConfiguration.alloc().init()
        self.popover = NSPopover.alloc().init()
        self.bridge = _PopBridge.alloc().initWithController_popover_(controller, self.popover)
        self.bridge.on_open_settings = on_open_settings
        self.bridge.on_quit = on_quit
        cfg.userContentController().addScriptMessageHandler_name_(self.bridge, "spillway")

        rect = NSMakeRect(0, 0, 320, 560)
        self.web = WKWebView.alloc().initWithFrame_configuration_(rect, cfg)
        self.bridge.webview = self.web
        self.web.loadHTMLString_baseURL_(_HTML, None)

        vc = NSViewController.alloc().init()
        vc.setView_(self.web)
        self.popover.setContentViewController_(vc)
        self.popover.setContentSize_((320, 560))
        self.popover.setBehavior_(NSPopoverBehaviorTransient)  # zavře se klikem mimo
        self.popover.setAnimates_(True)

        self._handler = _ButtonHandler.alloc().initWithPopoverController_(self)

    def attach_to_button(self, button) -> None:
        """Přesměruje klik na ikonu na tenhle popover (místo rumps menu)."""
        button.setTarget_(self._handler)
        button.setAction_("togglePopover:")
        self._button = button

    def toggle(self, button) -> None:
        try:
            button = button or getattr(self, "_button", None)
            if self.popover.isShown():
                self.popover.close()
                return
            # Data se přenačtou při každém otevření (JS `ready` se už podruhé
            # nespustí — HTML se nenačítá znovu), ať čísla nejsou zamrzlá.
            AppHelper.callAfter(self.bridge.push_state)
            self.popover.showRelativeToRect_ofView_preferredEdge_(
                button.bounds(), button, NSMinYEdge
            )
            NSApp.activateIgnoringOtherApps_(True)
        except Exception:  # noqa: BLE001
            import traceback

            _dbg("toggle ERROR\n" + traceback.format_exc())

    def is_shown(self) -> bool:
        try:
            return bool(self.popover.isShown())
        except Exception:  # noqa: BLE001
            return False
