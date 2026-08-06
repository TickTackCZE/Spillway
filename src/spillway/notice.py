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
)
from WebKit import WKWebView, WKWebViewConfiguration

from . import design, models, screens
from .webview import measure, run_js

_BORDERLESS = 0
_NONACTIVATING = 1 << 7
_STATUS_LEVEL = 25
# Průhledné odsazení kolem karty uvnitř okna (musí sedět s `body{padding}`
# v CSS). Počítá se s ním při umisťování, aby se zarovnávala viditelná karta,
# ne okno kolem ní.
_PAD = 8.0
_ALL_SPACES = 1 << 0
_STATIONARY = 1 << 4
_FS_AUX = 1 << 8

_LOGO = design.logo_svg(color="#818CF8", width=15, height=15)

_HTML = r"""<!DOCTYPE html><html lang="cs"><head><meta charset="UTF-8"><style>
  *{margin:0;padding:0;box-sizing:border-box;}
  :root{--surface:#1A1F2E;--text:#E2E8F0;--muted:#94A3B8;--accent:#818CF8;
        --danger:#E11D48;--warn:#F59E0B;--border:rgba(129,140,248,0.22);}
  @media (prefers-color-scheme: light){ :root{
    --surface:#FFFFFF;--text:#1E293B;--muted:#64748B;--accent:#3B82F6;
    --border:rgba(59,130,246,0.18);} }
  /* Šipka kartičky vyčnívá 6 px za pravý okraj (`.arrow{right:-6px}`), takže
     obsah přetéká a WKWebView pod ním vykreslí vodorovný posuvník — ta šedá
     tlustá čára pod kartičkou. Okno je plovoucí panel bez rolování, posuvník
     tu nemá co dělat. */
  html,body{background:transparent;overflow:hidden;}
  ::-webkit-scrollbar{width:0;height:0;display:none;}
  body{font-family:-apple-system,'Raleway',sans-serif;padding:8px;}
  .wrap{position:relative;}
  /* Stín kreslí macOS (`setHasShadow_`), ne CSS. CSS stín se ořezával na
     hraně okna a dělal kolem kartičky šedý obdélník s ostrými rohy; nativní
     se kreslí VEN z okna a tvaruje se podle viditelného obsahu, takže sedí
     přesně na zaoblený tvar. */
  .card{background:var(--surface);border:0.5px solid var(--border);border-radius:12px;
    padding:12px 13px;}
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
    document.getElementById('itModel').style.display = s.ready ? 'none' : 'block';
    document.getElementById('itKey').style.display = s.key_ok ? 'none' : 'block';
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
                # Odběr postupu tu NEREGISTRUJEME. Stav stahování má jediný
                # zdroj (`status.snapshot()`) a do oken ho rozesílá jedno místo
                # v `tray`; odsud se jen spouští.
                models.download_async()
            elif action == "cancel":
                models.cancel_download()
            elif action in ("key_open", "key_snooze"):
                self._owner.on_key_action(action)
        except Exception as exc:  # noqa: BLE001
            print(f"[notice] chyba: {exc}")


class NoticePanel:
    """Kartička s upozorněním vedle jiného okna."""

    # Výška je jen VÝCHOZÍ — `_fit_to_content` ji po každém vykreslení srovná
    # s obsahem (jedno sdělení, nebo dvě).
    W, H = 288, 300

    def __init__(self) -> None:
        rect = NSMakeRect(0, 0, self.W, self.H)
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, _BORDERLESS | _NONACTIVATING, NSBackingStoreBuffered, False
        )
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setLevel_(_STATUS_LEVEL)
        self.panel.setHasShadow_(True)       # tvarovaný stín kreslí macOS
        self.panel.setFloatingPanel_(True)
        self.panel.setHidesOnDeactivate_(False)
        try:
            # Stejně jako okénko u kurzoru: popover jde z lišty otevřít i nad
            # aplikací na celé obrazovce a kartička tam musí být vidět taky.
            self.panel.setCollectionBehavior_(_ALL_SPACES | _STATIONARY | _FS_AUX)
        except Exception:  # noqa: BLE001
            pass

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
        self._pos = None         # poslední poloha, ať se nepřesazuje zbytečně

    # --- vzhled ---------------------------------------------------------------

    def _render(self, state: dict) -> bool:
        """Překreslí kartičku a srovná výšku okna s obsahem.

        O nenačtenou stránku se stará `run_js` — volání odloží, dokud se
        stránka nedonačte, místo aby ho zahodil.

        Výška se dopočítává, protože obsah je jednou o jednom sdělení a jindy
        o dvou. Pevná výška by pod kartičkou nechala průhledný pruh, který
        polyká kliknutí, aniž by na něm cokoliv bylo.
        """
        run_js(self.web, "render(" + json.dumps(state, ensure_ascii=False) + ")", "notice")
        self._fit_to_content()
        return True

    def _refresh_shadow(self) -> None:
        """Nativní stín se počítá z průhlednosti okna — po změně obsahu nebo
        velikosti se musí přepočítat, jinak zůstane viset podle staré podoby."""
        try:
            self.panel.invalidateShadow()
        except Exception:  # noqa: BLE001
            pass

    def _fit_to_content(self) -> None:
        """Srovná výšku okna s obsahem.

        Měření jde přes `webview.measure`, aby počkalo na načtenou stránku.
        Dřív šlo přímo do `evaluateJavaScript` — a protože tray kartičku vytvoří
        a v témže tiku ukáže, stránka se ještě načítala, `querySelector` vrátil
        `null` a okno zůstalo na výchozí výšce. Pod kartičkou pak visel
        průhledný pruh, který polykal kliknutí.
        """
        def apply(value) -> None:
            h = float(value) + 2 * _PAD    # + odsazení těla nahoře i dole
            frame = self.panel.frame()
            if abs(h - float(frame.size.height)) < 1.0:
                return
            # Panel roste dolů: horní hrana musí zůstat u okna vedle.
            top = float(frame.origin.y) + float(frame.size.height)
            self.panel.setFrame_display_(
                NSMakeRect(float(frame.origin.x), top - h, self.W, h), True)
            self.web.setFrame_(NSMakeRect(0, 0, self.W, h))
            self._pos = None               # ať `show_beside` polohu přepočítá
            self._refresh_shadow()

        measure(self.web,
                "document.querySelector('.wrap').getBoundingClientRect().height",
                apply, "notice")

    def _apply(self, state: dict) -> None:
        """Překreslí, JEN když se stav změnil.

        Volá se z časovače 6,7×/s a každé `evaluateJavaScript` je práce navíc
        na hlavním vlákně — bez téhle podmínky se UI během stahování znatelně
        seká. O nenačtenou stránku se stará `run_js` uvnitř `_render`: volání
        odloží, dokud se stránka nedonačte, místo aby ho zahodil.
        """
        if state != self._last and self._render(state):
            self._last = state

    def on_key_action(self, what: str) -> None:
        cb = self.on_key
        if cb is not None:
            try:
                cb(what)
            except Exception:  # noqa: BLE001 — klik nesmí nic shodit
                pass

    # --- poloha a viditelnost -------------------------------------------------

    def show_beside(self, parent, anchor, snap: dict) -> None:
        """Posadí kartičku vlevo od okna `parent`, zarovnanou k jeho obsahu.

        `anchor` je VIDITELNÝ obdélník rodiče na obrazovce (u popoveru bez
        šipky a bez místa na stín) — podle něj se zarovnává, ne podle rámu okna.

        Nikdy rodiče nepřekrývá: kdyby vlevo nebylo místo, jde doprava od něj.
        Překryv byl nebezpečný — klik na její tlačítko vypadal jako klik do
        popoveru a otevíral Nastavení „samo od sebe".

        Viditelnost NEŘEŠÍ tahle metoda — o tom, kdy se kartička ukazuje a kdy
        mizí, rozhoduje výhradně `tray._update_notice`. Dokud tu byla kopie té
        podmínky, byla to tatáž past, na kterou projekt už dvakrát naletěl.
        """
        self._apply(snap)

        # Poloha se počítá z VIDITELNÉ karty a z VIDITELNÉHO obsahu okna vedle,
        # ne z rámů oken. Obojí má kolem sebe průhledný okraj (u nás `_PAD`
        # z CSS, u popoveru navíc šipka a místo na stín), takže zarovnání podle
        # rámů posadilo kartičku výš a dál, než vypadalo správně.
        gap = 8.0
        ax, ay = float(anchor.origin.x), float(anchor.origin.y)
        aw, ah = float(anchor.size.width), float(anchor.size.height)
        # Skutečná výška panelu, ne `self.H` — `_fit_to_content` ji mění podle
        # toho, jestli se hlásí jedno sdělení nebo dvě.
        h = float(self.panel.frame().size.height)
        x = ax - gap - self.W + _PAD            # pravá hrana KARTY `gap` od obsahu
        y = ay + ah - h + _PAD                  # horní hrany karet zarovnané

        # Obrazovka, na které je okno vedle — ne primární. Na sestavě s víc
        # monitory by se kartička jinak přehazovala podle špatného displeje.
        vf = screens.visible_frame_at(ax, ay)
        if vf is not None:
            left, bottom = float(vf.origin.x), float(vf.origin.y)
            if x + _PAD < left + 4.0:               # vlevo se nevejde → doprava
                x = ax + aw + gap - _PAD
            y = max(bottom + 4.0 - _PAD, y)

        if (x, y) != self._pos:
            self._pos = (x, y)
            self.panel.setFrameOrigin_(NSMakePoint(x, y))

        # Kartička NENÍ potomek rodičovského okna (`addChildWindow_`). Vypadá
        # to lákavě — zmizela by s ním sama — ale u popoveru to rozbíjí jeho
        # `Transient` chování: s připnutým potomkem se popover přestane zavírat
        # klikem mimo. O to, kdy kartička zmizí, se proto stará JEDNO místo:
        # `tray._update_notice`, které se ptá, jestli rodič vůbec svítí.
        if self._parent is not parent:
            self._parent = parent
            # Nad rodičem musí být i bez vazby — popover má vyšší hladinu než
            # běžné okno, takže se hladina bere z něj, ne natvrdo.
            try:
                self.panel.setLevel_(int(parent.level()) + 1)
            except Exception:  # noqa: BLE001
                self.panel.setLevel_(_STATUS_LEVEL)
        if not self._visible:
            self.panel.orderFrontRegardless()
        self._visible = True

    def is_visible(self) -> bool:
        return self._visible

    def hide(self) -> None:
        """Kartičku pryč. Řídí se skutečným stavem okna, ne jen příznakem —
        kdyby se `_visible` s realitou rozešel, zůstala by viset na obrazovce
        bez rodiče a nešla by zavřít ničím."""
        self._parent = None
        self._pos = None
        try:
            showing = bool(self.panel.isVisible())
        except Exception:  # noqa: BLE001
            showing = self._visible
        if self._visible or showing:
            self.panel.orderOut_(None)
        self._visible = False
