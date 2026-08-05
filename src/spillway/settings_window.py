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

_LOGO = design.logo_svg(color="#818CF8", width=30, height=30)

# Ikony stavů do nápovědy — kreslí se ze STEJNÉ geometrie jako skutečná ikona
# v liště (`design.scaled_bars` / `wave_bars`), takže se nemůžou rozejít.
# Pohyblivé stavy se ukazují jako SEKVENCE snímků: na statickém obrázku by
# jinak „nahrávám" a „zpracovávám" vypadaly skoro stejně jako klid.
_A = "#818CF8"


def _seq(bars_list, size=24):
    return "".join(design.bars_svg(b, _A, size, size) for b in bars_list)


_ICONS = {
    "idle": _seq([design.scaled_bars(1.0)], 26),
    "rec": _seq([design.scaled_bars(k) for k in (0.30, 0.95, 0.55)]),
    "proc": _seq([design.wave_bars(i, 8) for i in (0, 3, 6)]),
    "cancel": _seq([design.scaled_bars(0.18)], 26),
}

_LANGS = [
    ("cs", "Čeština"), ("en", "Angličtina"), ("sk", "Slovenština"),
    ("de", "Němčina"), ("es", "Španělština"), ("fr", "Francouzština"),
    ("pl", "Polština"), ("it", "Italština"), ("uk", "Ukrajinština"), ("ru", "Ruština"),
]
_LANG_OPTIONS = "".join(f'<option value="{c}">{n}</option>' for c, n in _LANGS)

_HTML = r"""<!DOCTYPE html><html lang="cs"><head><meta charset="UTF-8"><style>
  *{margin:0;padding:0;box-sizing:border-box;}
  :root{ /* DARK · Půlnoční (výchozí) */
    --bg:#0F1117;--surface:#1A1F2E;--surface2:#252D42;--text:#E2E8F0;--muted:#94A3B8;
    --accent:#818CF8;--border:rgba(129,140,248,0.2);--onaccent:#0F1117;--success:#4ADE80;--danger:#E11D48;--shadow:rgba(0,0,0,0.5);--chev:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8' fill='none'%3E%3Cpath d='M1 1.5L6 6.5L11 1.5' stroke='%2394A3B8' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");}
  @media (prefers-color-scheme: light){ :root:not([data-theme]){
    --bg:#F8FAFC;--surface:#FFFFFF;--surface2:#EEF2F8;--text:#1E293B;--muted:#64748B;
    --accent:#3B82F6;--border:rgba(59,130,246,0.15);--onaccent:#FFFFFF;--success:#16A34A;--danger:#E11D48;--shadow:rgba(30,41,59,0.18);--chev:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8' fill='none'%3E%3Cpath d='M1 1.5L6 6.5L11 1.5' stroke='%2364748B' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");} }
  :root[data-theme="light"]{
    --bg:#F8FAFC;--surface:#FFFFFF;--surface2:#EEF2F8;--text:#1E293B;--muted:#64748B;--shadow:rgba(30,41,59,0.18);
    --accent:#3B82F6;--border:rgba(59,130,246,0.15);--onaccent:#FFFFFF;--success:#16A34A;--danger:#E11D48;
    --chev:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8' fill='none'%3E%3Cpath d='M1 1.5L6 6.5L11 1.5' stroke='%2364748B' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");}
  html,body{background:var(--surface);}
  body{font-family:-apple-system,'Raleway',sans-serif;color:var(--text);padding:22px;}
  .head{display:flex;align-items:center;gap:12px;margin-bottom:4px;}
  .head svg{display:block;} .head .name{font-size:19px;font-weight:700;letter-spacing:4px;}
  .head .sub{font-size:9px;letter-spacing:3px;text-transform:uppercase;color:var(--muted);margin-top:2px;}
  .card{background:var(--surface2);border:0.5px solid var(--border);border-radius:12px;padding:16px;margin-top:14px;}
  .card h3{font-size:11px;font-weight:600;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:12px;}
  .seg{display:flex;background:var(--bg);border:0.5px solid var(--border);border-radius:9px;padding:3px;gap:3px;}
  .seg button{flex:1;border:0.5px solid transparent;background:transparent;color:var(--muted);font-family:inherit;font-size:12px;font-weight:600;padding:7px;border-radius:7px;cursor:pointer;}
  .seg button.active{background:var(--surface2);color:var(--text);border-color:var(--border);box-shadow:0 1px 3px var(--shadow);}
  .pills{display:flex;gap:8px;}
  .pill{flex:1;border:0.5px solid var(--border);border-radius:9px;padding:11px 12px;cursor:pointer;transition:.15s;background:transparent;}
  .pill.active{border-color:var(--accent);background:rgba(129,140,248,0.12);}
  .pill .t{font-size:13px;font-weight:600;} .pill .d{font-size:11px;color:var(--muted);margin-top:2px;}
  .field{display:flex;gap:8px;}
  input,textarea,select{width:100%;background:var(--bg);border:0.5px solid var(--border);border-radius:9px;color:var(--text);
    font-family:inherit;font-size:13px;padding:9px 11px;outline:none;}
  textarea{resize:vertical;min-height:84px;line-height:1.5;}
  select{appearance:none;-webkit-appearance:none;background-image:var(--chev);
    background-repeat:no-repeat;background-position:right 12px center;padding-right:34px;cursor:pointer;}
  select:hover{border-color:color-mix(in srgb,var(--accent) 55%,transparent);}
  input:focus,textarea:focus,select:focus{border-color:var(--accent);}
  /* Jedna velikost pro všechna tlačítka. Popisky se za běhu mění
     („Změnit" → „5 s" → „Potvrdit"), a bez pevné šířky by se řádek
     přeléval sem tam. */
  .btn{background:var(--accent);color:var(--onaccent);border:none;border-radius:9px;padding:9px 16px;
    font-weight:600;font-size:13px;cursor:pointer;font-family:inherit;white-space:nowrap;
    min-width:112px;text-align:center;}
  .btn:disabled{opacity:0.55;cursor:default;}
  .btn.danger{background:transparent;border:0.5px solid var(--danger);color:var(--danger);}
  .btn:disabled{opacity:.5;cursor:default;}
  .hint{font-size:11px;color:var(--muted);margin-top:8px;line-height:1.5;text-wrap:pretty;}
  .status{font-size:12px;margin-bottom:10px;display:flex;align-items:center;gap:7px;color:var(--text);}
  .status .dot{width:7px;height:7px;border-radius:50%;background:var(--success);}
  .rowt{display:flex;align-items:center;justify-content:space-between;padding:9px 0;gap:12px;}
  .rowt:not(:last-child){border-bottom:0.5px solid var(--border);}
  .rowt .l{font-size:13px;} .rowt .l small{display:block;font-size:11px;color:var(--muted);margin-top:1px;}
  .rowt.sub{margin-left:12px;padding-left:12px;border-left:2px solid var(--border);border-bottom:none;}
  .rowt.disabled{opacity:.45;}
  .sw.locked{cursor:default;}
  .sw{width:38px;height:22px;border-radius:11px;background:var(--surface2);position:relative;cursor:pointer;transition:.15s;flex-shrink:0;}
  .sw.on{background:var(--accent);}
  .sw::after{content:'';position:absolute;top:2px;left:2px;width:18px;height:18px;border-radius:50%;background:#fff;transition:.15s;}
  .sw.on::after{left:18px;}
  .foot{font-size:9px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);text-align:center;margin-top:18px;}
  /* Záložky pod logem — přepínání Nastavení / Nápověda. */
  .tabs{display:flex;gap:4px;background:var(--surface2);border:0.5px solid var(--border);border-radius:10px;padding:3px;margin-top:12px;}
  .tabs button{flex:1;border:0.5px solid transparent;background:transparent;color:var(--muted);font:inherit;font-size:12px;font-weight:600;padding:7px;border-radius:8px;cursor:pointer;}
  .tabs button.on{background:var(--surface);color:var(--text);border-color:var(--border);}
  .hidden{display:none;}
  /* --- Nápověda: schémata místo odstavců --- */
  .flow{display:flex;align-items:stretch;gap:6px;}
  .step{flex:1;background:var(--surface);border:0.5px solid var(--border);border-radius:10px;padding:10px 8px;text-align:center;}
  .step .big{font-size:20px;line-height:1.3;}
  .step .t{font-size:11px;font-weight:600;margin-top:3px;}
  .step .d{font-size:10px;color:var(--muted);margin-top:2px;line-height:1.4;text-wrap:balance;}
  .arrow{align-self:center;color:var(--muted);font-size:13px;}
  .kbd{display:inline-block;background:var(--surface2);border:0.5px solid var(--border);border-bottom-width:2px;border-radius:5px;padding:1px 6px;font-size:11px;font-weight:700;}
  .branch{display:flex;gap:8px;}
  .branch>div{flex:1;background:var(--surface);border:0.5px solid var(--border);border-radius:10px;padding:11px;}
  .branch .bt{font-size:12px;font-weight:600;display:flex;align-items:center;gap:6px;}
  .branch .bd{font-size:11px;color:var(--muted);margin-top:5px;line-height:1.5;text-wrap:pretty;}
  .dot{width:7px;height:7px;border-radius:50%;flex:none;}
  .states{display:flex;flex-direction:column;gap:2px;}
  .st{display:flex;align-items:center;gap:12px;padding:8px 0;}
  .st:not(:last-child){border-bottom:0.5px solid var(--border);}
  .st .ic{width:86px;display:flex;align-items:center;gap:3px;flex:none;}
  .st .ic svg{display:block;opacity:0.55;}
  .st .ic svg:last-child{opacity:1;}
  .st .ic.one svg{opacity:1;}
  .st .sl{font-size:12px;font-weight:600;} .st .sd{font-size:11px;color:var(--muted);margin-top:1px;}
  .privacy{display:flex;align-items:center;gap:8px;font-size:11px;}
  /* Stejná šířka i výška, ať schéma nevypadá jako váhy. */
  .privacy{align-items:stretch;}
  .privacy .box{flex:1 1 0;min-width:0;display:flex;flex-direction:column;justify-content:flex-start;
    background:var(--surface);border:0.5px solid var(--border);border-radius:9px;padding:9px;text-align:center;}
  .privacy .arrow{display:flex;align-items:center;}
  .privacy .box b{display:block;font-size:12px;margin-bottom:2px;}
  .privacy .box span{color:var(--muted);font-size:10px;line-height:1.45;display:block;text-wrap:balance;}
</style></head><body>
  <div class="head">__LOGO__<div><div class="name">SPILLWAY</div><div class="sub" id="sub">Nastavení</div></div></div>
  <div class="tabs">
    <button id="tabSet" class="on" onclick="showPage('settings')">Nastavení</button>
    <button id="tabHelp" onclick="showPage('help')">Nápověda</button>
  </div>

  <div id="pageSettings">

  <div class="card"><h3>Klávesy</h3>
    <div class="rowt">
      <div class="l">Diktování</div>
      <div class="field" style="width:auto;align-items:center;gap:8px;">
        <span class="l" id="hotkeyLabel" style="color:var(--accent);font-weight:600;">F5</span>
        <button class="btn" id="hotkeyBtn" onclick="recordHotkey()">Změnit</button>
      </div>
    </div>
    <div class="rowt">
      <div class="l">Zrušit zpracování</div>
      <div class="field" style="width:auto;align-items:center;gap:8px;">
        <span class="l" id="cancelLabel" style="color:var(--accent);font-weight:600;">Escape</span>
        <button class="btn" id="cancelBtn" onclick="recordCancel()">Změnit</button>
      </div>
    </div>
    <div class="hint">Klikni na Změnit a stiskni novou klávesu (funguje kdekoliv v systému). Rušicí klávesa se spolkne jen během zpracování — jinde funguje normálně.</div>
  </div>

  <div class="card"><h3>Primární jazyk (řeč)</h3>
    <select id="lang" onchange="send({action:'language',value:this.value})">__LANGS__</select>
  </div>

  <div class="card"><h3>Customizace</h3>
    <div class="rowt"><div class="l">Automatické spuštění po přihlášení<small>Spustí se s přihlášením do macOS</small></div><div class="sw" data-key="autostart" onclick="tog(this)"></div></div>
    <div class="rowt"><div class="l">Chytrá mezera<small>Mezera před textem, když jsi na konci slova</small></div><div class="sw" data-key="auto_space" onclick="tog(this)"></div></div>
    <div class="rowt"><div class="l">Odesílání do AI modelu<small>Úprava a formátování diktátu přes Claude</small></div><div class="sw" data-key="ai_edit" onclick="tog(this)"></div></div>
    <div class="rowt sub" id="fieldCtxRow"><div class="l">Číst kontext pole<small>Odesílání obsahu pole AI modelu</small></div><div class="sw" data-key="field_context" onclick="tog(this)"></div></div>
    <div class="rowt" style="border-top:0.5px solid var(--border);">
      <div class="l">Uvolnit model z paměti (10–600 s)<small>Po jaké nečinnosti (v sekundách), model zabírá ~2 GB RAM</small></div>
      <div class="field" style="width:auto;align-items:center;gap:8px;">
        <input id="unload" type="text" inputmode="numeric" style="width:74px;text-align:right;"
               onchange="saveUnload()" onblur="saveUnload()">
        <span class="l" style="color:var(--muted);">s</span>
      </div>
    </div>
    <div class="hint" id="unloadHint" style="display:none;"></div>
  </div>

  <div class="card"><h3>Slovník výrazů</h3>
    <textarea id="gloss" rows="4" placeholder="commit, pull request, repository, Trackio…" onchange="saveGloss()"></textarea>
    <div class="hint">Termíny oddělujte čárkou „,". Vstupuje až do AI modelu.</div>
  </div>

  <div class="card"><h3>Anthropic API klíč</h3>
    <div id="keyset" style="display:none">
      <div class="rowt" style="border-bottom:none;padding:0;">
        <div class="l"><span style="color:var(--success)">●</span> Klíč je nastavený<small>uložený v macOS Keychain</small></div>
        <button class="btn danger" onclick="send({action:'delkey'})">Smazat</button>
      </div>
    </div>
    <div id="keyunset" style="display:none">
      <div class="field"><input id="key" type="password" placeholder="sk-ant-…"><button class="btn" onclick="saveKey()">Uložit</button></div>
      <div class="hint">Klíč se uloží do macOS Keychain, ne do souboru.</div>
    </div>
  </div>

  <div class="card"><h3>Data a soukromí</h3>
    <div class="rowt">
      <div class="l">Reset statistik<small>Vynuluje počty, tempo, náklady i aktivitu</small></div>
      <button class="btn danger" data-label="Resetovat" onclick="armReset(this,'reset_stats')">Resetovat</button>
    </div>
    <div class="rowt">
      <div class="l">Reset historie nahrávek<small>Smaže uložené texty diktátů</small></div>
      <button class="btn danger" data-label="Vymazat" onclick="armReset(this,'reset_history')">Vymazat</button>
    </div>
  </div>

  <div class="card"><h3>Vzhled</h3>
    <div class="seg" id="seg">
      <button data-theme="system" onclick="setTheme('system')">Systém</button>
      <button data-theme="light" onclick="setTheme('light')">Light</button>
      <button data-theme="dark" onclick="setTheme('dark')">Dark</button>
    </div>
  </div>

  </div><!-- /pageSettings -->

  <div id="pageHelp" class="hidden">

  <div class="card"><h3>Jak to funguje</h3>
    <div class="flow">
      <div class="step"><div class="big"><span class="kbd hk">F5</span></div><div class="t">Podrž</div><div class="d">kdekoliv v systému</div></div>
      <div class="arrow">→</div>
      <div class="step"><div class="big">🎙️</div><div class="t">Mluv</div><div class="d">i s přeřeknutím</div></div>
      <div class="arrow">→</div>
      <div class="step"><div class="big">✋</div><div class="t">Pusť</div><div class="d">přepis a úprava</div></div>
      <div class="arrow">→</div>
      <div class="step"><div class="big">✨</div><div class="t">Hotovo</div><div class="d">text je na místě</div></div>
    </div>
    <div class="hint">Přeřeknutí se opraví samo: „sejdeme se ve 4, teda v 5“ → „sejdeme se v 5“.</div>
  </div>

  <div class="card"><h3>Kam text půjde</h3>
    <div class="branch">
      <div>
        <div class="bt"><span class="dot" style="background:var(--success)"></span>Kurzor je v poli</div>
        <div class="bd">Text se vloží rovnou tam, kde píšeš. Před něj se podle potřeby doplní mezera nebo nový řádek.</div>
      </div>
      <div>
        <div class="bt"><span class="dot" style="background:var(--accent)"></span>Pole není</div>
        <div class="bd">Nikam se nevkládá naslepo. Text čeká ve schránce a u ikony visí lístek&nbsp;— vložíš&nbsp;ho&nbsp;<span class="kbd">⌘V</span>.</div>
      </div>
    </div>
    <div class="hint">Totéž platí, když během zpracování odejdeš jinam&nbsp;— text se neztratí, jen počká.</div>
  </div>

  <div class="card"><h3>Ikona v liště</h3>
    <div class="states">
      <div class="st"><div class="ic one">__IC_IDLE__</div><div><div class="sl">Klid</div><div class="sd">Nic neběží</div></div></div>
      <div class="st"><div class="ic">__IC_REC__</div><div><div class="sl">Nahrávám</div><div class="sd">Sloupce skáčou podle tvého hlasu&nbsp;— poznáš, že tě mikrofon slyší</div></div></div>
      <div class="st"><div class="ic">__IC_PROC__</div><div><div class="sl">Zpracovávám</div><div class="sd">Vlna běží zleva doprava</div></div></div>
      <div class="st"><div class="ic one">__IC_CANCEL__</div><div><div class="sl">Ruším</div><div class="sd">Po stisku <span class="kbd ck">Escape</span></div></div></div>
    </div>
  </div>

  <div class="card"><h3>Klávesy</h3>
    <div class="rowt"><div class="l">Diktování<small>Drž po celou dobu mluvení</small></div><span class="kbd" id="helpHotkey">F5</span></div>
    <div class="rowt"><div class="l">Zrušit zpracování<small>Zahodí diktát, ušetří tokeny</small></div><span class="kbd" id="helpCancel">Escape</span></div>
    <div class="rowt"><div class="l">Vložit čekající text<small>Když text zůstal ve schránce</small></div><span class="kbd">⌘V</span></div>
  </div>

  <div class="card"><h3>Kudy tečou data</h3>
    <div class="privacy">
      <div class="box"><b>🎙️ Zvuk</b><span>Zůstává v Macu. Neodchází nikam.</span></div>
      <div class="arrow">→</div>
      <div class="box"><b>💻 Přepis</b><span>Běží lokálně na GPU tvého Macu.</span></div>
      <div class="arrow">→</div>
      <div class="box"><b>☁️ Úprava</b><span>Ven jde jen text, a to nepovinně.</span></div>
    </div>
    <div class="hint">API klíč leží v systémové Klíčence, ne v souboru. Do logu se obsah diktátů nezapisuje.</div>
  </div>

  <div class="card"><h3>Slovník a náklady</h3>
    <div class="rowt"><div class="l">Slovník výrazů<small>Vlastní jména a termíny, které se často komolí</small></div><button class="btn" onclick="showPage('settings')">Otevřít</button></div>
    <div class="rowt"><div class="l">Cena<small>Platí se jen za úpravu textu, přepis je zdarma</small></div><div class="l" style="color:var(--accent);font-weight:600;">~$2&nbsp;/&nbsp;měsíc</div></div>
    <div class="hint">Krátké diktáty se AI modelu neposílají vůbec&nbsp;— upraví se lokálně.</div>
  </div>

  </div><!-- /pageHelp -->

  <div class="foot">Spillway · v1.2</div>

<script>
  function send(m){ try{ window.webkit.messageHandlers.spillway.postMessage(m); }catch(e){} }
  function showPage(name){
    var help = name === 'help';
    document.getElementById('pageSettings').classList.toggle('hidden', help);
    document.getElementById('pageHelp').classList.toggle('hidden', !help);
    document.getElementById('tabSet').classList.toggle('on', !help);
    document.getElementById('tabHelp').classList.toggle('on', help);
    document.getElementById('sub').textContent = help ? 'Nápověda' : 'Nastavení';
    window.scrollTo(0, 0);
  }
  // Práh uvolnění modelu: pustíme dál jen celé sekundy v rozsahu. Nesmysl
  // (písmena, prázdno) se needituje na půl cesty — vrátíme poslední platnou
  // hodnotu, kterou pošle Python zpět v `applyUnload`.
  var lastUnload = 60;
  function saveUnload(){
    var el = document.getElementById('unload');
    var raw = (el.value || '').trim().replace(',', '.');
    var n = Number(raw);
    if(raw === '' || !isFinite(n)){ el.value = lastUnload; flashUnload('Zadej počet sekund (10–600).'); return; }
    n = Math.round(n);
    if(n < 10){ n = 10; flashUnload('Nejméně 10 s — jinak by se model uvolňoval mezi větami.'); }
    if(n > 600){ n = 600; flashUnload('Nejvíc 600 s (10 minut).'); }
    el.value = n; lastUnload = n;
    send({action:'auto_unload', value:n});
  }
  var unloadTimer = null;
  function flashUnload(msg){
    var h = document.getElementById('unloadHint');
    if(!h) return;
    h.textContent = msg; h.style.color = 'var(--danger)'; h.style.display = 'block';
    clearTimeout(unloadTimer);
    unloadTimer = setTimeout(function(){ h.style.display = 'none'; }, 3200);
  }
  function arm(which, action){
    document.getElementById(which+'Btn').disabled = true;   // popisek zůstává
    document.getElementById(which+'Label').textContent = 'Stiskni klávesu…';
    send({action:action});
  }
  function recordHotkey(){ arm('hotkey', 'record_hotkey'); }
  function recordCancel(){ arm('cancel', 'record_cancel'); }
  // `which` = 'hotkey' | 'cancel' — jeden pár funkcí pro obě klávesy.
  function applyHotkey(h){
    var which = h.which || 'hotkey';
    document.getElementById(which+'Btn').disabled = false;
    document.getElementById(which+'Label').textContent = h.label;
    var cls = which === 'cancel' ? '.kbd.ck' : '.kbd.hk';
    var id = which === 'cancel' ? 'helpCancel' : 'helpHotkey';
    var one = document.getElementById(id); if(one) one.textContent = h.label;
    document.querySelectorAll(cls).forEach(function(el){ el.textContent = h.label; });
  }
  function cancelHotkey(which){
    which = which || 'hotkey';
    document.getElementById(which+'Btn').disabled = false;
  }
  // [F3] Obě klávesy nesmí být stejné — vrátíme tlačítko a krátce to vysvětlíme.
  function rejectHotkey(which){
    var b = document.getElementById(which+'Btn');
    b.textContent = 'Už je použitá'; b.disabled = false;
    send({action:'state'});  // vrátit původní popisek klávesy
    setTimeout(function(){ b.textContent = 'Změnit'; }, 1600);
  }
  function applyTheme(t){
    if(t==='system'){ document.documentElement.removeAttribute('data-theme'); }
    else { document.documentElement.setAttribute('data-theme', t); }
    document.querySelectorAll('#seg button').forEach(b=>b.classList.toggle('active', b.dataset.theme===t));
  }
  function setTheme(t){ applyTheme(t); send({action:'theme',value:t}); }
  function saveKey(){ var v=document.getElementById('key').value; if(v.trim()){ send({action:'apikey',value:v.trim()}); document.getElementById('key').value=''; } }
  function saveGloss(){ send({action:'glossary',value:document.getElementById('gloss').value}); }
  // Destruktivní akce: první klik spustí 5s odpočet, po který JDE tlačítko zamčené
  // (ať omylem nedvojklikneš). Teprve pak jde potvrdit; bez potvrzení se za chvíli
  // vrátí do klidu.
  function resetBtn(btn){ clearInterval(btn._iv); clearTimeout(btn._to); btn.dataset.state=''; btn.disabled=false; btn.textContent=btn.dataset.label; }
  function armReset(btn, action){
    if(btn.dataset.state==='ready'){          // potvrzovací klik
      clearTimeout(btn._to); btn.dataset.state='';
      send({action:action});
      btn.textContent='Hotovo'; btn.disabled=true;
      setTimeout(function(){ resetBtn(btn); }, 1500);
      return;
    }
    if(btn.dataset.state) return;             // během odpočtu klik ignoruj
    btn.dataset.state='arming'; btn.disabled=true;
    var left=5; btn.textContent=left+' s';
    btn._iv=setInterval(function(){
      left--;
      if(left>0){ btn.textContent=left+' s'; return; }
      clearInterval(btn._iv);
      btn.disabled=false; btn.dataset.state='ready'; btn.textContent='Potvrdit';
      btn._to=setTimeout(function(){ resetBtn(btn); }, 5000);  // bez potvrzení → klid
    }, 1000);
  }
  // „Číst kontext pole" je podnastavení „Odesílání do AI modelu": vizuálně sleduje
  // rodiče (rodič vypnutý → dítě vypnuté a zašedlé/zamčené), master ho zapíná i vypíná.
  function syncAiEdit(){
    var master=document.querySelector('.sw[data-key="ai_edit"]');
    var on=master.classList.contains('on');
    var child=document.querySelector('.sw[data-key="field_context"]');
    document.getElementById('fieldCtxRow').classList.toggle('disabled', !on);
    child.classList.toggle('locked', !on);
    if(!on) child.classList.remove('on');  // vypnutý master → dítě i opticky vypnuté
  }
  function tog(el){
    if(el.classList.contains('locked')) return;  // zamčené dítě nereaguje
    var on=!el.classList.contains('on'); el.classList.toggle('on',on);
    send({action:'toggle',key:el.dataset.key,value:on});
    if(el.dataset.key==='ai_edit'){
      // Master přepíná i dítě: zapnout → zapne, vypnout → vypne (obojí uloží).
      var child=document.querySelector('.sw[data-key="field_context"]');
      if(on && !child.classList.contains('on')){
        child.classList.add('on'); send({action:'toggle',key:'field_context',value:true});
      } else if(!on && child.classList.contains('on')){
        child.classList.remove('on'); send({action:'toggle',key:'field_context',value:false});
      }
      syncAiEdit();
    }
  }
  function setKeyLabels(hotkey, cancel){
    // Klávesy se ukazují na dvou místech (Nastavení i Nápověda) — nastavují se
    // jedním voláním, ať se nemůžou rozejít.
    [['hotkeyLabel',hotkey],['helpHotkey',hotkey],['cancelLabel',cancel],['helpCancel',cancel]]
      .forEach(function(kv){ var el=document.getElementById(kv[0]); if(el && kv[1]) el.textContent = kv[1]; });
    // Klávesy ve schématech nápovědy (může jich být víc než jedna).
    document.querySelectorAll('.kbd.hk').forEach(function(el){ if(hotkey) el.textContent = hotkey; });
    document.querySelectorAll('.kbd.ck').forEach(function(el){ if(cancel) el.textContent = cancel; });
  }
  function applyState(s){
    setKeyLabels(s.hotkey_label || 'F5', s.cancel_label || 'Escape');
    if(typeof s.auto_unload_sec === 'number'){
      lastUnload = s.auto_unload_sec;
      document.getElementById('unload').value = s.auto_unload_sec;
    }
    applyTheme(s.theme||'system');
    document.getElementById('lang').value = s.language || 'cs';
    document.getElementById('keyset').style.display = s.has_key ? 'block' : 'none';
    document.getElementById('keyunset').style.display = s.has_key ? 'none' : 'block';
    document.getElementById('gloss').value = s.glossary || '';
    [['autostart',s.autostart],['ai_edit',s.ai_edit],['field_context',s.field_context],['auto_space',s.auto_space]].forEach(function(kv){
      var el=document.querySelector('.sw[data-key="'+kv[0]+'"]'); if(el) el.classList.toggle('on', !!kv[1]);
    });
    syncAiEdit();
  }
  window.addEventListener('DOMContentLoaded', function(){ send({action:'ready'}); });
</script>
</body></html>""".replace("__LOGO__", _LOGO).replace("__LANGS__", _LANG_OPTIONS)

# Ikony stavů do schémat v nápovědě.
for _key, _svg in _ICONS.items():
    _HTML = _HTML.replace(f"__IC_{_key.upper()}__", _svg)


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
            if action in ("ready", "state"):
                self._push_state()
            elif action == "language":
                lang = str(body.get("value", "")) or "cs"
                settings.set("language", lang)
                self.controller.set_language(lang)
            elif action == "theme":
                settings.set("theme", str(body.get("value", "system")))
            elif action == "reset_stats":
                stats.reset_stats()
            elif action == "reset_history":
                stats.clear_recordings()
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
            elif action == "auto_unload":
                # Validace i tady, ne jen v UI — z WKWebView může přijít cokoliv.
                sec = config.clamp_auto_unload(body.get("value"))
                if sec is not None:
                    settings.set("auto_unload_sec", sec)
                    print(f"⚙️  práh uvolnění modelu: {sec} s")
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
                elif key in ("field_context", "auto_space", "ai_edit"):
                    settings.set(key, val)
        except Exception as exc:  # noqa: BLE001
            print(f"[settings] bridge error: {exc}")

    def _on_hotkey_captured(self, keycode: int, which: str = "hotkey") -> None:
        # Voláno z vlákna event tapu → VŠE (i zápis settings [B16]) přehodit na main thread.
        label = keymap.label_for(keycode)

        # [F3] Obě klávesy nesmí být stejné — rušicí větev v tapu má přednost,
        # takže shodná klávesa by úplně umlčela hold-to-talk (a u F5 by navíc
        # přestala potlačovat nativní diktování).
        other = (
            config.get_hotkey()[0] if which == "cancel" else config.get_cancel_hotkey()[0]
        )
        if keycode == other:
            def _reject() -> None:
                if self.webview is not None:
                    self.webview.evaluateJavaScript_completionHandler_(
                        "rejectHotkey(" + json.dumps(which) + ")", None
                    )
            AppHelper.callAfter(_reject)
            return

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
        state = {
            "hotkey_label": hotkey_label,
            "cancel_label": cancel_label,
            "theme": config.get_theme(),
            "language": config.get_language(),
            "has_key": bool(config.get_api_key()),
            "glossary": ", ".join(config.glossary()),
            "autostart": autostart.is_enabled(),
            "ai_edit": bool(settings.get("ai_edit", True)),
            # Uložená hodnota (ne přes config.field_context, který ji při vypnuté
            # AI úpravě maskuje na False) — dítě má v UI ukazovat vlastní stav.
            "field_context": bool(settings.get("field_context", True)),
            "auto_space": config.auto_space(),
            "auto_unload_sec": config.get_auto_unload_seconds(),
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

        # Šířka kvůli schématům v nápovědě (kroky a větve vedle sebe),
        # výška kvůli delší stránce nastavení.
        rect = NSMakeRect(0, 0, 560, 820)
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

    def show(self, page: str = "settings") -> None:
        """Zobrazí okno; `page="help"` rovnou přepne na Nápovědu."""
        try:
            NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        except Exception:  # noqa: BLE001
            pass
        self.window.center()
        self.window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        self._show_page(page)
        # Okno se vytvoří jednou a pak recykluje — bez tohohle by karta
        # Statistiky ukazovala zamrzlá data z prvního otevření (`ready` už
        # podruhé nenastane, protože se HTML znovu nenačítá).
        self.refresh()

    def _show_page(self, page: str) -> None:
        """Přepne záložku. Volá se i při recyklaci okna, takže Nápověda z
        popoveru otevře Nápovědu i tehdy, když okno zůstalo na Nastavení."""
        try:
            name = "help" if page == "help" else "settings"
            self.web.evaluateJavaScript_completionHandler_(f"showPage('{name}')", None)
        except Exception:  # noqa: BLE001
            pass

    def refresh(self) -> None:
        """Přenačte stav do okna (hlavně Statistiky). Musí běžet na main threadu."""
        try:
            self.bridge._push_state()
        except Exception:  # noqa: BLE001 — refresh je kosmetika, nesmí nic shodit
            pass

    def is_visible(self) -> bool:
        try:
            return bool(self.window.isVisible())
        except Exception:  # noqa: BLE001
            return False
