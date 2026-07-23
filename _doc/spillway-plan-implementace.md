# Spillway — Plán implementace

> Živý dokument: aktuální stav, otevřená rozhodnutí, co dál. **Hotové věci žijí v git historii (`dev` branch), ne tady.**
> Vychází z [spillway-analyza.md](spillway-analyza.md). Poslední úklid: 16. 7. 2026.

---

## Co je Spillway

Osobní diktovací nástroj pro macOS. Lokální přepis řeči (faster-whisper) → úprava textu přes Claude → univerzální vložení (Cmd+V) do libovolné aplikace. Hold-to-talk na konfigurovatelnou klávesu (výchozí F5), běží na pozadí jako menu-bar app.

**Funkční pilíře:** vícejazyčnost (CZ+EN code-switching), znalost cílové aplikace (per-app profily email/chat/code/ai/generic), uživatelský slovník termínů, zachování registru (nemění význam, necenzuruje, formátuje jen když se hodí).

---

## Současný stav — funkční, nasazeno ✅

- `.app` sestavená, **stabilně self-signed** (oprávnění přežijí rebuildy), nasazená v `/Applications/Spillway.app`.
- Pipeline běží end-to-end: F5 → nahrávání → přepis → úprava → vložení. HUD u pole, auto-unload modelu (~15 s), file-log.
- **Zrušení diktátu** klávesou (výchozí Escape, konfigurovatelná) — zahodí pipeline před placeným voláním Claude. Klávesa se spolkne JEN během zpracování, jinde funguje normálně.
- **Statistiky** v nastavení — **čas diktování** (celkem namluveno), počet diktátů, slova, nejčastější aplikace. („Ušetřený čas" odstraněn — dopočítával se z hádané rychlosti psaní 40 slov/min a nadhodnocoval pro rychlé pisatele.) Data v `history.jsonl` (rotace 5000 řádků) = i podklad pro pozdější export na RPi.
- Model: **`claude-sonnet-5`** (výchozí, `temperature=0`); Haiku volitelný v nastavení.
- Nastavení (téma / jazyk / model / klíč / slovník / klávesa) perzistentní; API klíč jen v Keychain.

---

## Architektura (podstata)

- **Python 3.12 + PyObjC** (AppKit / Quartz / WebKit / ApplicationServices). Menu-bar app (`LSUIElement`), bundle přes **PyInstaller**.
- **CGEventTap** na vlastním vlákně/CFRunLoop, callback triviální. F5 = keycode **176**, `return None` potlačí nativní diktování. Watchdog na ztracený key-up, re-enable po timeoutu.
- **Přepis:** dva backendy (`transcribe.py`, přepínač `SPILLWAY_WHISPER_BACKEND`). Výchozí **mlx-whisper na Apple GPU** (`large-v3-turbo`, RTF ~0,08–0,22, ~4,5× rychlejší než CPU při stejné kvalitě — změřeno) s **energetickou bránou proti tichu** (mlx nemá VAD → jinak halucinuje „Titulky vytvořil…"). Fallback **faster-whisper CPU** (má VAD; `beam_size=5`) — aktivuje se, když mlx health-check při startu selže (nezabalené shadery / jiný HW / budoucí Windows). V `.app` se balí mlx.metallib + dylibs (`collect_dynamic_libs`), torch se vylučuje (~490 MB, při přepisu se nenačítá). Bundle vzrostl na ~500 MB. **Slovník do Whisperu (`hotwords`) je VYPNUTÝ** (zapne `SPILLWAY_WHISPER_HOTWORDS=1`): bias sice pomáhá u vzácných termínů, ale na akusticky nejednoznačném místě termín **vloží, i když nezazněl** — porušení B1 rovnou v přepisu, kde už to nikdo nechytí. Zkomoleniny opravuje bezpečně až Claude přes slovník v promptu (ověřeno: „komitnul→commitnul", „pool request→pull request", a termín ze slovníku si nevymyslí).
- **Paste:** zápis do schránky (+ Transient/Concealed typy) → ⌘+V přes CGEvent → fixní delay ~250 ms → obnova schránky. **Vzdálená Windows plocha (RDP/AVD/VDI, `context.is_windows_target`) → Ctrl+V** místo ⌘+V (klienti syntetické ⌘ nepřeloží na Ctrl → do session dorazí holé „V"), čekání ~0,6 s na rdpclip a **schránka se u RDP záměrně NEobnovuje** — rdpclip si obsah stahuje opožděně, takže obnova by do Windows vložila starý text.
- **Moduly** `src/spillway/`: hotkey, audio, transcribe, context, llm, paste, tray, hud, settings(_window), config, lifecycle, autostart, baricon, keymap, design.
- **⚠️ Podpis je kritický:** TCC granty (Accessibility/Input Monitoring) i Keychain ACL se vážou na code signature. Ad-hoc podpis se mění každým buildem → resetoval by oprávnění. Řeší **stabilní self-signed cert „Spillway Self-Signed"** — DR = `identifier "com.spillway.app" and certificate root = H"…"` je konstantní napříč rebuildy. Privátní klíč v login keychainu + záloha `~/Library/Application Support/Spillway/codesign-identity.p12` (mimo git).

---

## Build & nasazení

```bash
bash build/make_codesign_cert.sh   # JEDNOU na stroji — vytvoří podpisový cert
bash build/build_app.sh            # PyInstaller + codesign → build/dist/Spillway.app
bash build/make_dmg.sh             # volitelně DMG instalátor
```

Nasazení do `/Applications` (stabilní cesta mimo Google Drive; re-sign po `cp`, protože kopie kvůli xattrs rozbije podpis):

```bash
rm -rf /Applications/Spillway.app && cp -R build/dist/Spillway.app /Applications/
xattr -cr /Applications/Spillway.app
codesign --force --deep --timestamp=none -s "Spillway Self-Signed" /Applications/Spillway.app
```

Log běhu: `~/Library/Logs/Spillway/spillway.log` (obsahuje `AXIsProcessTrusted` + stav event tapu). Testy: `uv run pytest`.

---

## Konfigurace

- **Nastavení:** `~/Library/Application Support/Spillway/settings.json` (model, jazyk, téma, slovník, hotkey, toggly). Pozn.: `settings.set()` ukládá celý slitý dict → změna defaultu v kódu se na existující soubor NEpropíše, přepsat ručně.
- **API klíč:** macOS Keychain (`keyring`, služba `spillway`), fallback env `ANTHROPIC_API_KEY`. **Nikdy** v repu.
- `.gitignore` blokuje `config.toml`, `.env`, `*.key`, `*.p12`, `*.crt`.

---

## Otevřená rozhodnutí (čekají na tebe)

- **O8 — celé e-mailové vlákno jako kontext?** ⚠️ **Pozor, částečně se to už děje:** profil `email` posílá Claudeovi `field_text[:3000]` — a protože AX vrací pole jako jeden plochý text, je v tom **i citovaná historie a podpis**. Rozhodnout: nechat, omezit (jen text nad citací), nebo vypnout. Vypínač už existuje (přepínač „Číst kontext pole").
- **O9 — sjednocení celého pole → ZAMÍTNUTO** (research 17. 7.). Obava uživatele potvrzena: AX vrací pole odpovědi jako jeden plochý text včetně citovaného vlákna a podpisu, a `paste.py` píše do schránky **jen plain text** → `Cmd+A` + vložení by nevratně smazalo historii konverzace i HTML podpis (logo, odkazy). Hranice „můj text / citace / podpis" nejde spolehlivě detekovat: markery citace jsou lokalizované a u Outlooku nekonzistentní, `-- ` podpis dle RFC 3676 dnes skoro nikdo nepoužívá a `<blockquote>` se v AX ztratí. Pokud někdy, tak jen nad **označeným výběrem** (`AXSelectedText`), nikdy `Cmd+A`, a až po implementaci undo.

---

## Next steps (zbývá dodělat)

- **Onboarding wizard oprávnění** — mikrofon / Accessibility / Input Monitoring, live detekce + deep-linky do Nastavení; první spuštění po instalaci.
- **Autostart pro `/Applications` verzi** — nahradit dřívější LaunchAgent (dev verzi, zneškodněnou) login-itemem podepsané `.app` (SMAppService).
- **Historie v menu** — `stats.py` už přepisy i metriky ukládá do `history.jsonl`; zbývá UI: posledních N diktátů v menu lišty (klik → zpět do schránky).
- **Statistiky — rozšíření:** úspora v **tokenech** (ne jen znacích) přes `client.messages.count_tokens`, útrata za Claude, rozpad za den/týden, tlačítko „vymazat historii" (teď jen rotace na 5000 řádků).
- **Editor per-app profilů v UI** — teď pevná mapa v `context.py`.
- **Zvuková odezva** start/stop nahrávání; **undo** posledního vložení; rychlý **raw-mode toggle** z menu.
- **Zabalit Raleway font** (jinak UI padá na systémový — funkčně OK).
- **Polish HUD:** multi-monitor pozice, první stav před doload WKWebView HTML.

---

## Backlog / budoucí featury

- **Komerční distribuce** — Developer ID + notarizace (odstraní Gatekeeper varování „nelze ověřit vývojáře"), licencování, onboarding cizích uživatelů. Architekturu držet čistou (žádné natvrdo zadrátované osobní cesty/klíče).
- **Export historie na RPi / DB + analytiky** — kolik/kde/jaké termíny diktuji, WER trendy. Proto historii od začátku ukládat strojově čitelně.
- **Rychlost:** `mlx-whisper` (Neural Engine/GPU místo CPU), streamovaná odpověď Claude, přeskočit LLM krok u velmi krátkých vět. Největší fixní náklad je síťová latence k API (~0,5–1,5 s).
- Vícejazyčný přepínatelný režim (per-app / hotkey), titulek okna do kontextu (za cenu Screen Recording), streaming přepis v reálném čase, vlastní hlasové příkazy („nový odstavec", „smazat větu").

---

## Profil `ai` — proč je agresivní

Diktování promptu do AI je jiná úloha než přepis zprávy: čte to model, ne člověk. Změřeno na reálné historii (9 diktátů, 2054 zn.): původní „šetrný" prompt zhušťoval jen o **13 %** a úsečné mluvené poznámky dokonce **rozepisoval do uhlazených vět** (+9 %). Po přeboostování profilu (výstup musí být kratší, odrážky od 2 zadání, pryč zdvořilosti a uvozovací vata) je zhuštění **29 %**, bez ztráty požadavků. Profil si výslovně přebíjí obecná pravidla FORMÁT. Obsah zůstává nedotknutelný — krátí se forma, ne informace.

---

## Vědomé výjimky z pravidla „nevymýšlet" (B1)

Základní pravidlo zní: nikdy nesmí vzniknout obsah, který uživatel nenadiktoval. Jedna výjimka je schválená:

- **E-mailová etiketa** (profil `email`): když oslovení/zakončení nezazní, doplní se výchozí „Dobrý den," a „S pozdravem". **Rozhodnutí uživatele 17. 7.** — chce nadiktovat jen obsah a dostat hotový e-mail. **Jméno do podpisu se nikdy nevymýšlí.** Ostatní profily (chat/ai/code/generic) nepřidávají nic.

---

## Známá omezení

- **Paste:** počítat s ~1 % selhání ve secure-input polích (hesla, Terminal secure entry). Při aktivním Secure Keyboard Entry event tap nedostává eventy → hotkey dočasně mrtvý.
- **Uvnitř RDP/AVD** nefunguje čtení kontextu pole ani pozice kurzoru (vzdálená plocha je pro Accessibility jen obrázek) → HUD u myši, žádný kontext pole, žádná chytrá mezera. Vkládání samo funguje (Ctrl+V).
- **HUD ve web/Electron appkách** sedí nad polem (ne přesně u kurzoru) — Chromium/Electron neposkytuje pozici kurzoru přes Accessibility.
- **`.app` je self-signed, ne notarizovaná** → první spuštění: pravý klik → Otevřít (nebo Nastavení → Soukromí → Otevřít i tak).
- **Náklady Claude:** Sonnet ~2–3× Haiku, typicky jednotky $/měsíc, hluboko pod komerčními nástroji (Wispr Flow $12–15).
