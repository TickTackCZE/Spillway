# Spillway — Plán implementace

> **Živý dokument.** Sem zapisujeme bugy, trackujeme nedostatky a udržujeme aktuální stav implementace.
> Aktualizuj při každé změně stavu. Zdroj pravdy pro „kde jsme".
>
> Návrh vychází z [spillway-analyza.md](spillway-analyza.md) + architektonického review (Fable 5).
> Založeno: 14. 7. 2026 · Poslední aktualizace: 14. 7. 2026

---

## 0. Stav projektu (dashboard)

| Ukazatel | Hodnota |
|---|---|
| **Aktuální fáze** | **F3 — Aplikace** (🟨 menu bar + settings okno + logo + perzistence hotové; zbývá `.app`) |
| **Milník** | Instaluju .app, běží na pozadí, přežije restart |
| **Blokery** | Zabalení do `.app` (hlavní krok); GUI test opraveného zachytávání klávesy + settings okna. Bugy: 15/18 opraveno, zbývá B18/B20 (F4). |
| **Testovací stroj** | iMac M4, 16 GB RAM, 10 jader (Mac16,12, 2024) — **ne** M5 Air; Apple Silicon, faster-whisper poběží CPU-only stejně |
| **Otevřené otázky k rozhodnutí** | 1 — O1 Whisper backend (rozhodne Spike B); O2–O7 rozhodnuty (viz §8) |

**Legenda stavů:** ⬜ TODO · 🟨 rozpracováno · ✅ hotovo · ⛔ blokováno · ❌ zamítnuto

---

## 1. Cíl a rozsah

**Spillway** = osobní diktovací nástroj pro macOS (MacBook Air M5). Lokální přepis řeči (Whisper) → AI úprava textu (Claude Haiku) → univerzální vložení do libovolné aplikace. Konfigurovatelná klávesa (hold-to-talk). Běží na pozadí jako menu bar aplikace.

**Klíčové vlastnosti (dle požadavků uživatele):**
- **F-a) Vícejazyčnost** — podpora více jazyků, primárně čeština + angličtina (code-switching v jedné promluvě i celé věty v druhém jazyce). Viz [modul `transcribe`](#3-moduly) a otázka O7.
- **F-b) Znalost aplikace** — nástroj ví, do jaké aplikace se diktuje (název + bundle ID), a přizpůsobí tomu úpravu (formálnost, styl → per-app profily). Viz modul `context`.
- **F-c) Slovník výrazů** — uživatelský slovník termínů (IT žargon, názvy, zkratky), který zlepší jak přepis (Whisper hint), tak úpravu (Claude je nepočeští ani nepřepíše).
- **F-d) Selektivní oprava** — ne všechna slova se opravují; některé výrazy jsou **chráněné** (preserve verbatim) — specifický pravopis, názvy, značky, které Claude nesmí měnit.

**Rozhodnutí:** Analýza doporučovala nejdřív 2 týdny zkoušet hotový open-source **Murmure**. Vědomě stavíme vlastní nástroj (plná kontrola nad CZ+EN promptem, slovníkem a budoucím směrem — viz §9) i za cenu, že Murmure by možná stačil.

**Non-goals (v1):** Windows/Linux, streaming přepis v reálném čase, screenshoty jako kontext, cloud sync.

**Definition of done (MVP):** Nadiktuju v češtině odstavec do Gmailu → vyjde gramaticky správný text s interpunkcí, anglické termíny zachované, bez ručního zásahu.

---

## 2. Architektura (rozhodnuto)

- **Jazyk:** Python 3.12 (vynucuje faster-whisper / CTranslate2). macOS integrace přes **PyObjC** (AppKit, Quartz, AVFoundation).
- **Forma:** jedna **.app bundle**, menu bar app (`LSUIElement=true`, bez ikony v Docku), build **PyInstaller**.
- **Autostart:** `SMAppService.mainApp.register()` (moderní Login Item, viditelné v System Settings). LaunchAgent `KeepAlive` jen jako fallback restart po pádu.
- **Procesní model:** AppKit main thread jen pro UI (NSStatusItem). **CGEventTap běží na vlastním dedikovaném vlákně s vlastním CFRunLoop** (ne na main threadu — zaneprázdněné UI by způsobilo `kCGEventTapDisabledByTimeout`). Callback tapu drží triviální (jen zápis do fronty). Worker vlákna (audio / Whisper / LLM), komunikace přes `queue.Queue`. Explicitní stavový automat: `IDLE → RECORDING → TRANSCRIBING → LLM → PASTING → IDLE`.

### ❌ Docker — zamítnuto
Kontejner na macOS běží v linuxové VM → nemá přístup k CoreAudio (mikrofon), WindowServeru (CGEvent, NSWorkspace), TCC oprávněním (Accessibility, Input Monitoring) ani globálním hotkeys. Fungoval by v něm jen samotný Whisper. „Kontejner" z požadavku = **samostatně zabalená .app běžící na pozadí** (řeší .app bundle + launchd/SMAppService).

### ⚠️ Podpis kódu je kritický
TCC oprávnění se vážou na code signature. Bez **stabilního podpisu + stabilního Bundle ID** každý rebuild resetuje povolení Microphone/Accessibility/Input Monitoring. Minimum: ad-hoc podpis (`codesign --force --deep -s -`). Ideál: Developer ID ($99/rok) — viz otázka O4.

---

## 3. Moduly

| Modul | Odpovědnost | Stav |
|---|---|---|
| `hotkey` | CGEventTap (Quartz) na vlastním CFRunLoop vlákně; push-to-talk automat; modifier-only klávesy přes `flagsChanged`; watchdog na ztracený key-up; ignorování key-repeat; re-enable po `kCGEventTapDisabledByTimeout`. **[O2] Plně konfigurovatelný + cíl převzít klávesu macOS diktování** (Fn/Globe): onboarding navede vypnout/přemapovat diktování v Nastavení; event tap klávesu zachytí a případně potlačí (`return None` z callbacku). Viz R9 | ⬜ |
| `audio` | `sounddevice` → 16 kHz mono float32 ring buffer v RAM; start/stop zvuk; limit délky (~120 s); detekce ticha (zahodit prázdné) | ⬜ |
| `transcribe` | faster-whisper singleton držený v paměti; `vad_filter=True`, `beam_size=1`; **abstrakce backendu** (možná výměna za mlx-whisper). **[F-a] Vícejazyčnost:** výchozí `language="cs"` zvládá CZ+EN code-switching (anglické termíny uvnitř české věty); pro čistě jiný jazyk režim přepínatelný jazyk (per-app / hotkey / config — viz O7). **[F-c] Slovník:** termíny předat jako `initial_prompt`/hotwords → biasuje přepis ke správnému znění | ⬜ |
| `context` | `NSWorkspace.frontmostApplication` (název + bundle ID, bez oprávnění); titulek okna přes `CGWindowListCopyWindowInfo` vyžaduje Screen Recording → v MVP jen název appky. **[F-b] Per-app profily:** mapa bundle ID → profil (formálnost/styl/jazyk), předá se do `llm` promptu | ⬜ |
| `llm` | Anthropic SDK, `claude-haiku-4-5`, timeout ~10 s; **[O6] při chybě vloží raw přepis A ZÁROVEŇ ukáže viditelnou chybu** (notifikace/badge — nikdy neztratit text); prompt šablona CZ+EN + kontext appky. **[F-c] Slovník** vložen do promptu (termíny zachovat přesně). **[F-d] Chráněné výrazy:** seznam „preserve verbatim" v promptu — Claude tato slova nesmí opravit/změnit | ⬜ |
| `history` | **[O5]** ukládání přepisů lokálně, minimální formát (JSONL: časová značka, aplikace, raw text, upravený text, jazyk); nešifrovaně; rotace/limit; zdroj pro menu History i budoucí export na RPi (§10) | ⬜ |
| `paste` | uložit obsah NSPasteboard → zapsat text **+ deklarovat typy `org.nspasteboard.TransientType`/`ConcealedType`** (clipboard manageri Maccy/Raycast pak záznam ignorují) → CGEvent Cmd+V (flags na keydown i keyup) → **fixní delay ~150–300 ms** (Cmd+V schránku jen čte, `changeCount` se nemění → nelze pollovat dokončení) → obnovit původní obsah (jen pokud `changeCount` mezitím nezměnil někdo jiný). fallback 1: AXUIElement setValue; fallback 2: `CGEventKeyboardSetUnicodeString` (pomalé, univerzální) | ⬜ |
| `config` | TOML, hot-reload z UI, validace (pydantic) | ⬜ |
| `tray` | NSStatusItem (raw PyObjC — rumps si uzurpuje main loop); stavy ikony; menu: Raw mode, History, Settings, Quit | ⬜ |
| `lifecycle` | single-instance lock (pid soubor); graceful shutdown (odregistrovat tap, uvolnit audio); crash-restart | ⬜ |

---

## 4. Konfigurace

- **Umístění:** `~/Library/Application Support/Spillway/config.toml`
- **API klíč:** macOS **Keychain** přes `keyring`, fallback `ANTHROPIC_API_KEY`. **Nikdy** v config.toml ani v repu.
- **Logy:** `~/Library/Logs/Spillway/` — **bez obsahu přepisů** (opt-in debug flag).
- **Klíče:** `hotkey` (keycode+modifikátory), `raw_mode`, `language` (výchozí `cs`), `language.mode` (v1 pevně `fixed` — `per_app`/`hotkey_switch` **rezervováno** pro backlog §9), `language.secondary` (rezervováno), `model`, `llm.enabled`, `llm.model`, `paste.strategy` (`cmd_v`/`type`/`auto`), `paste.restore_clipboard`, `audio.max_seconds`, `context.include_window_title`.
- **[F-c] Slovník výrazů** (`[[glossary]]`): seznam položek `{ term, note? }` — termíny, které se biasují do Whisperu a v Claude promptu se drží beze změny. Např. `commit`, `repository`, `pull request`, vlastní názvy projektů.
- **[F-d] Chráněné výrazy** (`protected_terms`): seznam slov/frází, které Claude **nesmí opravovat** (specifický pravopis, značky, přezdívky). Podmnožina slovníku s tvrdým „preserve verbatim".
- **[F-b] Per-app profily** (`[[app_profile]]`): `{ bundle_id, formality, style?, language? }` — např. Slack = neformální/CZ, Mail = formální, VS Code = technický/EN.
- **[O5] Historie** (`history.enabled=true`, `history.path`, `history.max_entries`): ukládání do `~/Library/Application Support/Spillway/history.jsonl`, nešifrovaně, minimální formát. (Debug logy v `~/Library/Logs/Spillway/` zůstávají bez obsahu přepisů — historie je oddělené úložiště.)

---

## 5. Fáze implementace

### F0 — Spiky (ověření neznámých) ⬜
Cíl: rozhodnout Whisper backend a paste strategii, než se napíše zbytek.
- [x] **Spike A — paste** ✅ **OVĚŘENO 14. 7.** — text se vložil správně vč. diakritiky (ř/ž/ů) i emoji 🐎 (Terminal běžel s Accessibility). Pozn.: schránka byla prázdná (`None`), takže obnova s neprázdným obsahem + clipboard managerem se ještě neotestovala; test napříč 6 appkami dokončit ve F1. Zapsat do schránky (+ Transient/Concealed typy) → Cmd+V přes CGEvent → fixní delay → obnovit schránku. Test v 6 appkách (Safari, Chrome, VS Code, Terminal, Slack/Electron, Mail) + password pole + běžící clipboard manager. *Největší riziko celé aplikace.* **Kritérium úspěchu:** paste OK v ≥ 6/6 běžných polí; obnova schránky bez ztráty i s běžícím Maccy; do password pole očekáván fail → změřit, jak vypadá.
- [x] **Spike B — Whisper benchmark** ✅ **OVĚŘENO 15. 7.** (`spikes/spike_b_whisper.py`, na iMac M4). faster-whisper `large-v3-turbo` int8, CPU: **RTF ~0,30** (19,7 s CZ audia → 6,0 s přepis; 10s diktát ≈ 3 s), teplé načtení modelu **1,6 s**, RAM **~1,6–1,9 GB**. Kvalita CZ výborná; jediná chyba `commitnul→sommitnul` (foneticky anglické „commit") — přesně to opraví Claude v F2. **Závěr: faster-whisper na M4 vyhovuje** (kritérium splněno). Pozn.: WER měřeno na syntetickém (say) audiu → pro ostré WER dodělat reálnou nahrávku. mlx-whisper porovnání = volitelné (nižší latence/baterie na Air), neblokuje. **Porovnání s plným `large-v3`** (int8): pomalejší (RTF 0,51), víc RAM (2,6 GB) a na tomto vzorku i víc chyb v angl. termínech (`comitnul/fiaturé/pool request`) → **turbo zůstává výchozí**, plný model nepřináší jasný zisk.
- [x] **Spike C — hotkey** ✅ **OVĚŘENO 14. 7.** — CGEventTap + Input Monitoring fungují; hold-to-talk na pravý ⌥ (`keycode=61`) spouští START/STOP spolehlivě. Mechanismus globálního hotkey odrizikován. CGEventTap, modifier-only.
- [x] **Spike C2 — F5 / diktovací klávesa** ✅ **OVĚŘENO 14. 7.** — F5 chodí jako **normální `keyDown`/`keyUp`, keycode=176** (ne system-defined). Hold-to-talk funguje a se `SUPPRESS_F5=True` (`return None`) **nativní diktování NEnaskočí** → F5 lze přebít čistě softwarově, uživatel nemusí nic vypínat v Nastavení. **R9 vyřešeno.** Výchozí klávesa = **F5 (176)**., hold-to-talk, chování při přepnutí okna během držení, re-enable po timeoutu. **[R9]** ověřit potlačení klávesy macOS diktování (spíš čekat neúspěch → primární cesta je vypnout diktování v Nastavení). **[R11]** ověřit chování při Secure Keyboard Entry (tap nedostává eventy).
- [ ] **Spike D — bundle** ⬜ PyInstaller balíček s PyObjC+ctranslate2, ad-hoc podpis, ověřit že TCC oprávnění přežijí restart. **[Model]** ověřit stahování Whisper modelu (~1,5 GB) při first-run z HuggingFace do cache (`~/.cache/huggingface` nebo vlastní Application Support) — model **NEsmí** do bundlu; first-run UX s progress barem.

**Milník F0:** ✅ backend vybraný, paste strategie ověřená → jde se stavět.

### F1 — MVP pipeline (bez LLM, bez UI) ✅
- [x] **Moduly nakódovány** (`src/spillway/`): `hotkey` (F5 tap na vlastním vlákně), `audio` (sounddevice, RAM-only), `transcribe` (faster-whisper singleton + filtr halucinací R10), `paste` (ze Spike A), `app` (stavový automat IDLE→RECORDING→PROCESSING). Spouštěč `run_spillway.py`.
- [x] Smoke-test: importy + konstrukce + přepisová cesta přes moduly OK.
- [x] **End-to-end test ✅ 15. 7.** — nadiktováno česky, text vložen do aktivní aplikace (RTF ~0,39 na reálné řeči, VAD správně odfiltroval krátký stisk).
- [ ] config v TOML (zatím natvrdo výchozí hodnoty) → dodělat ve F3.
- [x] **Milník ✅ splněn:** diktuju do libovolné appky, raw text se vloží.

### F2 — LLM + kontext 🟨
- [x] **Moduly nakódovány:** `llm` (Claude Haiku cleanup, prompt pro CZ+EN), `context` (NSWorkspace frontmost app — **ověřeno**), `config` (API klíč z Keychain/env), `set_api_key.py` (getpass → Keychain). Wiring v `app.py`.
- [x] **[F-b]** kontext (název appky) předán do promptu.
- [x] Keychain pro API klíč, **[O6]** fallback: při chybě AI se vloží syrový přepis + viditelná chyba, raw-mode toggle (`--raw`).
- [ ] **End-to-end test uživatelem** — nastavit API klíč (`set_api_key.py`) a ověřit, že Claude opraví `sommitnul→commitnul` apod. Změřit cenu.
- [ ] **[F-c]** slovník výrazů + **[F-d]** chráněné výrazy → odloženo do F3 (potřebují TOML config s uživatelským vstupem).
- [ ] **Milník:** CZ+EN diktát vychází čistý (angl. termíny opraveny), změřená cena.

### F3 — Aplikace 🟨
> **Design:** uživatel dodal brand manuál **Domovoy** (Půlnoční paleta, Raleway, ploché, tenké 0,5px hrany, accent #818CF8). Vlastní UI Spillway to má napodobit. Tokeny: `src/spillway/design.py`. Viz paměť `domovoy-design-system`.
- [x] **Spillway logo** = roztékající waveform (`design.logo_svg`) — dle reference uživatele, v accentu. App ikona / HUD / wordmark.
- [x] **Menu bar** (`tray.py`): statická ikona, klik → menu „Nastavení…" (otevře okno) + „Konec". Vše nastavení přesunuto do okna.
- [x] **Plovoucí HUD u kurzoru** (`hud.py`, WKWebView) — neutrální graphite karta + logo + pulzující tečka. Caret nad textem (nativní pole) / u myši (Electron/web). Ověřeno v náhledu.
- [x] **Settings okno v Domovoy designu** (`settings_window.py`, WKWebView + JS↔Python most): **téma Systém/Světlý/Tmavý** (Ledová/Půlnoční, „systém" dle OS), **výběr primárního jazyka** (Whisper), model (Haiku/Sonnet), **API klíč (vložit→uložit→smazat→vložit)**, slovník (celá šířka), přepínače. Ověřeno v náhledu obou témat. **Čeká na GUI test.**
- [x] **Ikona v liště = Spillway logo** (`baricon.py` — template PNG z waveform). Fallback emoji.
- [x] **Konfigurovatelná klávesa v UI** — karta „Klávesa" v nastavení, tlačítko Změnit zachytí příští stisk kdekoliv v systému (`hotkey.start_capture`, `keymap.py` pro čitelný název), uloží se a hned se použije (bez restartu appky). Čeká na GUI test.
- [x] **[F-b] Profil „ai"** — diktování do Claude/ChatGPT/Perplexity/Gemini teď cíleně formátuje jako prompt (strukturovaná instrukce), ne jen obecná korektura.
- [x] Karta Vzhled přesunuta na konec nastavení (dle uživatele).
- [x] **[F-b] Detekce webu v prohlížeči přes AppleScript/Automation** (`context.browser_context`) — NE Screen Recording. Čte jen URL aktivní karty (Safari/Chrome/Brave/Edge/Arc), doména → profil (gmail.com→email, chat.openai.com→ai atd.). Jednorázové schválení systémového dialogu. Nečte obsah stránky (žádná historie e-mailu) — vědomé rozhodnutí, viz O8.
- [x] **Hlasový metapokyn o formátu** — „toto je e-mail", „piš to formálně" v promptu Claude rozpozná a použije, samotný pokyn do výstupu nezahrne. Bez nutnosti oprávnění.
- [x] **Perzistence všeho** — settings.json (model, jazyk, téma, slovník, toggly) + Keychain (klíč) + LaunchAgent (autostart); Controller vše načte při startu.
- [ ] Raleway font zabalit (jinak UI padá na systémový font — funkčně OK).
- [ ] **Zabalení do `.app`** (PyInstaller, LSUIElement, ikony) + single-instance — aby šlo nainstalovat a spouštět bez terminálu. **Hlavní zbývající krok.**
- [x] **[F-b] Kontextové formátování** — per-app profil (email/chat/code/generic) + čtení obsahu pole (email = celé pole 3000 zn.) jako kontext pro Claude. Pojistka B1 zachována. Čeká na test.
- [x] **[F-c/F-d] Slovník výrazů** — editovatelný v menu, uložen v `settings.json`, předán do promptu (termíny beze změny + oprava přeslechů k nim).
- [x] **Přepínání modelu** za běhu z menu (Haiku ↔ Sonnet), perzistováno.
- [x] **Autostart po přihlášení** (`autostart.py`, LaunchAgent) — zap/vyp z menu. *(Ve fázi zabalení nahradí SMAppService.)*
- [x] **Perzistentní nastavení** (`settings.json` v Application Support) — model, slovník, toggly. *(Nahrazuje plánovaný TOML.)*
- [x] **API klíč z menu** — dialog uloží do Keychain (+ `set_api_key.py` zůstává).
- [ ] PyInstaller .app (LSUIElement — jen ikona v liště, bez Docku) + podpis + single-instance
- [ ] **Milník:** instaluju .app, přežije restart.

### F4 — Polish ⬜
- [ ] Onboarding wizard oprávnění (mikrofon / Accessibility / Input Monitoring, live detekce + deep-linky) + **[O2]** krok pro vypnutí/přemapování macOS diktování
- [ ] **[O5]** modul `history` — ukládání do JSONL + historie posledních N přepisů v menu
- [ ] Zvuky start/stop, floating HUD (waveform)
- [ ] **[F-c]** editor slovníku a **[F-d]** chráněných výrazů v Settings UI
- [ ] **[F-b]** editor per-app profilů v Settings UI
- [ ] **[F-a]** UI pro přepínání jazyka (dle zvoleného režimu O7)
- [ ] Auto-unload modelu po nečinnosti

---

## 6. Bug tracker

> Formát: `#ID · [severita] · popis · stav · poznámka`. Severita: 🔴 kritická / 🟠 vysoká / 🟡 střední / ⚪ nízká.

| # | Sev | Popis | Stav | Poznámka |
|---|-----|-------|------|----------|
| B1 | 🟠 | **AI úprava přepisovala nejasný obsah** — Haiku halucinoval náhrady slov, kterým nerozuměl (`„ten klot s tím mapíčkem"` → `„tu mapu"`), měnil význam | ✅ vyřešeno | Prompt přepsán na striktně minimální úpravy; model konfigurovatelný přes `SPILLWAY_LLM_MODEL`. Uživatel potvrdil, že Haiku teď vypadá dobře. |
| B2 | ✅ | **Mikrofon se neuvolní** — oranžový indikátor mikrofonu v liště svítí i po nahrávání | **Vyřešeno** | Fix v3 (gc.collect + restart PortAudia) zabral — potvrzeno uživatelem. |
| B3 | 🟡 | **Souběh: co při nahrání během zpracování / překlik pole** — otázka uživatele | ✅ ošetřeno / ⚠️ známé | Nová nahrávka během zpracování se **ignoruje** (žádná fronta — ať se nevloží do špatného pole), s výpisem „zaneprázdněno". Kontext (appka/profil/pole) se snímá při puštění F5; paste jde tam, kam je fokus v okamžiku vložení — **překlik pole během zpracování → vloží se do nového pole, ale formátování dle starého kontextu** (přijatelné; latence ~1–3 s). |
| B4 | 🔴 | **Zachytávání klávesy (`hotkey.py:62-82`) nemá timeout ani zrušení** — po kliku na „Změnit" zůstane `_capturing=True` navždy, pokud uživatel okno jen zavře/odklikne jinam. Příští stisk KDEKOLIV v systému (klidně o hodinu později) se potlačí a stane se novou hotkey bez potvrzení. Modifikátorové kombinace (⌘C) chodí přes `flagsChanged`, který tap nesleduje → zachytí se jen „C", takže se nečekaně potlačí každé psaní písmene C | ⬜ | Oprava: timeout (~5s) na capture, zrušení při zavření okna, ignorovat keyDown se stisknutými modifikátory, potvrzení v UI před uložením. **Ověřeno čtením kódu.** |
| B5 | 🔴 | **`autostart.enable()` (`autostart.py:56-58`) spustí druhou instanci appky okamžitě** — zapíše plist s `RunAtLoad=true` a hned `launchctl load`, zatímco původní instance (ze které se kliklo na toggle) běží dál. Dva event tapy na hotkey, dva `Recorder` o mikrofon, 2× Whisper model v paměti (~4 GB), možné dvojité vložení textu. Chybí single-instance lock (byl v plánu jako modul `lifecycle`, neimplementován) | ⬜ | Oprava: buď plist zapsat bez okamžitého `launchctl load` (naběhne až po přihlášení), nebo pid-file lock, co druhou instanci hned ukončí. **Ověřeno čtením kódu.** |
| B6 | 🟠 | **Capture spuštěný během nahrávání rozbije stavový automat** (`hotkey.py:74-82`) — pustíš F5 zrovna když běží capture (klik myší na „Změnit"): keyUp jen propustí (`return event`), `on_release` se nezavolá → stav zůstane `RECORDING` navěky (mikrofon běží, HUD trčí na „Nahrávám"), a keyUp F5 navíc unikne nepotlačený do systému | ⬜ | `start_capture` odmítnout/odložit, když `_pressed` nebo `Controller.state != IDLE`; v capture větvi keyUp aktuální hotkey propustit do normální větve, ne jen `return event`. |
| B7 | 🟠 | **Chybí watchdog na ztracený key-up** (R4 splněno jen napůl — re-enable po timeoutu je, watchdog na spánek/lock chybí) — Mac usne/zamkne se staženým F5 → keyUp nikdy nedorazí → `RECORDING` navěky | ⬜ | Timer v Controlleru: po `audio.max_seconds` od `on_press` vynutit `on_release`; posluchač `NSWorkspaceWillSleepNotification` → reset stavu. Viz R4/R11. |
| B8 | 🟠 | **Filtr halucinací zahazuje legitimní text** (`transcribe.py:45-48`) — `startswith("překlad ")` je běžné české slovo; diktát „Překlad toho dokumentu pošlu zítra" se **celý zahodí** jako „prázdný přepis", tichá ztráta 10 s řeči, proti duchu O6 | ⬜ | Aplikovat filtr jen na krátké výstupy (< ~40 znaků) nebo když celý text ≈ marker; „překlad " vyřadit ze seznamu. |
| B9 | 🟠 | **Těžká práce (gc.collect + restart PortAudia) běží přímo ve vlákně tapu** (`app.py:86` → `audio.stop()`) — `on_release` volá `recorder.stop()` synchronně na vlákně event tapu; stovky ms práce riskují `kCGEventTapDisabledByTimeout` právě v okamžiku, kdy je tap potřeba (eventy během výpadku projdou nepotlačené → možný návrat nativního diktování, R9). Porušuje vlastní pravidlo z §2 „callback tapu drž triviální" | ⬜ | `on_release` jen přehodí stav, `recorder.stop()` (těžké volání) přesunout do worker vlákna. **Ověřeno čtením kódu.** |
| B10 | 🟠 | **`NSAppleScript` (`context.py:76-87`) se spouští mimo main thread** — `browser_context()` volaný z worker vlákna `_process`; Apple dokumentuje NSAppleScript jako main-thread-only. První spuštění navíc vyvolá synchronní TCC dialog, na kterém worker vlákno visí — appka se tváří „zaneprázdněná" bez vysvětlení, dokud uživatel dialog neodklikne | ⬜ | Spustit přes `AppHelper.callAfter`/main-thread dispatch, nebo `subprocess.run(["osascript",…], timeout=2)` místo `NSAppleScript`. |
| B11 | 🟡 | **`settings.json` zápis není atomický ani mezi-procesově chráněný** (`settings.py:42-48`) — pád uprostřed zápisu poškodí JSON → `_load()` tiše vrátí defaulty (ztráta slovníku/hotkey/modelu bez hlášky); dva souběžné procesy (viz B5) se navzájem přepíšou | ⬜ | Zápis do `.tmp` + `os.replace()` (atomické); zvážit `fcntl.flock` pro mezi-procesovou ochranu. |
| B12 | 🟡 | **O6 „viditelná chyba" v praxi neexistuje** (`app.py`) — jen `print()`; pod LaunchAgentem (bez terminálu) je appka nediagnostikovatelná — vypršelý API klíč = týdny nevysvětleného raw textu. Vnější `except` navíc chytá i selhání `paste_text` → text se ztratí úplně, jen do /dev/null | ⬜ | `rumps.notification(...)` v except větvích; do plistu `StandardOutPath/StandardErrorPath` → `~/Library/Logs/Spillway/`. |
| B13 | 🟡 | **Ne-textový obsah schránky se nenávratně zničí** (`paste.py:57-65`) — `stringForType_` na screenshot/soubory vrátí `None` → obnova se přeskočí → diktát přepíše cokoliv bylo ve schránce (např. právě zkopírovaný screenshot) | ⬜ | Zálohovat všechny typy schránky (`pasteboardItems()`), nebo při `original is None` schránku po vložení vyčistit místo ponechání transkriptu. |
| B14 | 🟡 | **Pojistka B1 obejitelná prompt-injection přes obsah pole** (`llm.py:90-95`) — `before_text` (cizí text, u e-mailu až 3000 zn.) jde do system promptu ohraničený jen `"""`; sekvence `"""` v datech (citovaný kód, cizí zpráva) rozbije ohraničení a může přebít PŘÍSNÉ ZÁKAZY | ⬜ | `before_text` posílat jako samostatnou user zprávu / content blok, ne do system promptu; nebo escapovat `"""` z dat. |
| B15 | 🟡 | **Nekontroluje se `stop_reason` → tiché vložení uříznutého textu** (`llm.py:102-113`) — `max_tokens` počítá znaky, ne tokeny; při `stop_reason=="max_tokens"` se uřezaná věta vloží bez varování | ⬜ | Po odpovědi zkontrolovat `resp.stop_reason`; při `max_tokens` spadnout na raw přepis (stejná větev jako O6). |
| B16 | 🟡 | **`_on_hotkey_captured` zapisuje settings.json přímo ve vlákně tapu** (`settings_window.py:239-243`) — 2 oddělené `settings.set()` volání PŘED `AppHelper.callAfter` (komentář v kódu říká opak); pomalý disk → tap timeout (stejný mechanismus jako B9); navíc neatomické (pád mezi zápisy nechá keycode nový, label starý) | ⬜ | Přesunout oba `settings.set()` dovnitř `_apply()` (main thread), ideálně jeden zápis. |
| B17 | 🟡 | **Poškozený typ v settings.json shodí appku při startu** (`config.py:43-46`) — validní JSON se špatným typem (`"hotkey_keycode": "F5"`) → `int("F5")` → `ValueError` při startu, pod LaunchAgentem neviditelně (viz B12) | ⬜ | try/except s fallbackem v `get_hotkey()`; obecná validace typů v `settings._load()`. |
| B18 | ⚪ | **HUD počítá jen s primárním monitorem** (`hud.py:120-131`) — kurzor na druhém monitoru → špatná pozice HUD | ⬜ | Najít screen obsahující caret rect, použít jeho frame místo `screens[0]`. |
| B19 | ⚪ | **Cleanup ve `finally` se nespustí při Quit z menu** (`app.py:180,187-189`) — `rumps.quit_application()` ukončí proces uvnitř `run()`, `finally` (uvolnění tapu/mikrofonu) se nevykoná; OS to uklidí, ale rozpracovaný přepis za běhu se tiše zahodí | ⬜ | Vlastní Quit callback: `listener.stop()` + `recorder.stop()` před `rumps.quit_application()`. |
| B20 | ⚪ | **HUD `setState` volaný před dokončením `loadHTMLString`** (`hud.py:104,110-118`) se ztratí — první `show()` těsně po startu může doběhnout dřív než JS load → HUD okno viditelné, ale prázdné po celé první nahrávání | ⬜ | `navigationDelegate` + bufferovat stav do `didFinishNavigation`, nebo necachovat stav při chybě JS volání. |
| B21 | ⚪ | **Toggle „Číst kontext pole" mimochodem vypíná i detekci prohlížeče** (`app.py:98-101`) — `browser_context` (jen doména) je gatovaná stejným přepínačem jako obsah pole, i když UI popisek slibuje jen odesílání textu pole; návrhová nekonzistence, ne pád | ⬜ | Samostatný toggle pro detekci domény prohlížeče, nebo přeznačit popisek v UI. |

**Zdroj B4–B21:** code review agentem **Fable 5** (15. 7. 2026) — dostal celý plán + všech 19 zdrojových souborů, hledal race conditions, resource leaky a porušení invariantů B1/O6/R4.

**✅ Opraveno 16. 7. 2026 (commit `6fcbe4f`): B4–B17 + B19** (15 bugů). B4 (timeout+cancel+ignore modifikátorů), B5 (autostart bez okamžitého loadu + `lifecycle.py` flock), B6 (guard při nahrávání), B7 (watchdog), B8 (filtr jen na krátký text), B9 (stop na workeru), B10 (osascript subprocess), B11 (atomický zápis), B12 (rumps notifikace), B13 (záloha všech typů schránky), B14 (obsah pole jako user zpráva), B15 (stop_reason→raw), B16 (zápis na main threadu), B17 (odolné get_hotkey/glossary), B19 (úklid při Quit). Smoke-testy prošly; GUI část (B4/B6/B16 přes okno) čeká na test uživatelem.

**⬜ Zbývá:** **B18** (HUD multi-monitor), **B20** (HUD stav před doload HTML) — do F4/polish. **B21** (detekce prohlížeče gatovaná přepínačem „kontext pole") — ponecháno záměrně jako konzervativní privacy default (vypnutí kontextu vypne i automation prohlížeče).

---

## 7. Nedostatky a rizika (tech debt / watchlist)

> Známá rizika z review. Sleduj a mitiguj během příslušné fáze.

| # | Sev | Riziko | Mitigace | Fáze |
|---|-----|--------|----------|------|
| R1 | 🔴 | **Paste spolehlivost** — secure input pole (hesla, Terminal secure entry), Electron/Java vlastní handling; obnova schránky je race-prone (clipboard manageri Raycast/Maccy); počítat s ~1 % selhání | Fixní delay ~150–300 ms (changeCount **nedetekuje** vložení); deklarovat Transient/Concealed pasteboard typy; 3-úrovňový fallback; blacklist appek | Spike A / F1 |
| R2 | 🟢 | **faster-whisper CPU-only** — na M4 ale **RTF ~0,30** (dost rychlé), RAM ~1,9 GB. mlx-whisper by byl rychlejší/šetrnější k baterii, ale neblokuje | **Sníženo (Spike B):** faster-whisper `large-v3-turbo` int8 je pro v1 dostačující. Backend zůstává abstrahovaný pro pozdější mlx | vyřešeno pro v1 |
| R3 | 🟠 | **TCC vs. rebuildy** — bez stabilního podpisu se povolení resetují po každém buildu | Stabilní ad-hoc podpis + stabilní Bundle ID; dev wrapper | Spike D / F3 |
| R4 | 🟠 | **Hotkey race conditions** — ztracený key-up (přepnutí Space, spánek, lock) → věčné nahrávání; event tap se tiše zakáže při pomalém callbacku | Max-duration watchdog; reset stavu při sleep/lock; naslouchat `kCGEventTapDisabledByTimeout` a re-enablovat | Spike C / F1 |
| R5 | 🟡 | **Paměť** — model rezidentně ~1,5–2 GB RAM | Na 16GB Airu OK; auto-unload po nečinnosti | F4 |
| R6 | 🟡 | **Privacy** — přepis + titulek okna odchází k Anthropic; titulky umí obsahovat citlivé věci | Titulek okna opt-in; audio nikdy neopouští stroj (komunikovat v UI); Keychain pro klíč | F2 |
| R7 | ⚪ | **Konflikt hotkey** s Raycast/Alfred (drží vlastní event tapy) | Konfigurovatelnost = nutnost | F1 |
| R8 | 🟢 | **Náklady** — potvrzeno odhadem (`spikes/spend_estimate.py`): Haiku ~$0,8–4/měs typicky, s e-mail kontextem ~2×, Sonnet ~2–3×. Vše pod Wispr Flow ($12–15) | Systémový prompt (~600 tok) je pod minimem cache (Haiku 4096) → caching nepomůže; kontext pole je vypínatelný | vyřešeno |
| R9 | ✅ | **[O2] Převzetí nativní klávesy F5 (diktování/Siri)** — ~~mediální klávesy nechodí jako keyDown~~ | **VYŘEŠENO (Spike C2):** F5 chodí jako normální keyDown/keyUp (keycode 176) a `return None` ji spolehlivě potlačí → diktování nenaskočí, **bez zásahu do Nastavení**. Použít keycode 176 jako výchozí hotkey; tap musí být aktivní (ne listen-only) + Accessibility | ✅ hotovo |
| R10 | 🟡 | **Whisper halucinace na tichu** — na tichém/krátkém audiu vrací fantomové věty (typicky „Titulky vytvořil…") | `vad_filter=True` + post-filtr v `transcribe` (zahodit známé fráze, min. délku); detekce ticha už v `audio` | F1 |
| R12 | 🟠 | **[O2] Volba klávesy na CZ layoutu** — na české klávesnici se **oba** Alty používají k psaní (pravý Alt/AltGr = `@ & # …`, levý Alt = další znaky) → hold-to-talk na Option koliduje s psaním. Fn koliduje s fkeys/diktováním (R9). *Zjištěno ve Spike C: uživatel přirozeně stiskl levý ⌥ (58).* | Kandidáti: pravý ⌘ (méně používaný k psaní), dvojí poklep modifikátoru (jako Wispr Flow), nebo Caps Lock remap. Rozhodnout po dotestování Spike C; hotkey je stejně plně konfigurovatelný | Spike C / F1 |
| R11 | 🟠 | **Secure input blokuje i hotkey** — při aktivním Secure Keyboard Entry (Terminal, password pole) event tap **nedostává keyboard eventy vůbec** → hotkey mrtvý, uživatel neví proč | Detekce `IsSecureEventInputEnabled()` + indikace v tray („diktování nedostupné v zabezpečeném poli") | Spike C / F1 |

---

## 8. Rozhodnuté otázky + otevřené

**Rozhodnuto (14. 7. 2026):**

| # | Otázka | ✅ Rozhodnutí |
|---|--------|--------------|
| O2 | Výchozí hotkey | **Plně konfigurovatelný.** Cíl: **převzít klávesu macOS diktování** (Fn/Globe). Uživatel v Nastavení macOS diktování vypne/přemapuje, Spillway klávesu převezme; případně event tap událost potlačí. Viz modul `hotkey` + riziko R9 + onboarding. |
| O3 | Titulek okna do kontextu | **Zatím jen název aplikace** (bez Screen Recording). |
| O4 | Podpis aplikace | **Teď ad-hoc** (osobní nástroj). **Do budoucna Developer ID + notarizace** kvůli plánovanému prodeji → nearchitektovat se do kouta (viz §10 Budoucí featury). |
| O5 | Historie přepisů | **Ukládat**, minimální formát, **nešifrovaně lokálně** na PC. Budoucí odesílání na RPi/DB + analytiky → §10. |
| O6 | Výpadek API | **Viditelná chyba** (notifikace/badge) — a **raw přepis se přesto vloží**, aby se text neztratil. |
| O7 | [F-a] Jazykový režim | **Aktualizováno:** primární jazyk je nyní **volitelný v nastavení** (cs/en/sk/de/…), uložený a živě měnitelný. CZ+EN code-switching uvnitř věty řeší Whisper + Claude. |
| O8 | **Celá historie e-mailového vlákna jako kontext?** Teď se čte jen URL domény (gmail.com → profil), ne obsah stránky. Číst celé vlákno (předchozí zprávy) by šlo přes AppleScript pro Mail.app, nebo procházením celého accessibility stromu webmailu — ale to je výrazně větší privacy dopad (celé vlákno by šlo k Anthropic). Vědomě neimplementováno bez tvého rozhodnutí. | Chceš to? Pokud ano, upřesnit: jen Mail.app, nebo i webmail (Gmail/Outlook v prohlížeči)? |

**Otevřené (rozhodne se během spiků):**

| # | Otázka | Řešení |
|---|--------|--------|
| O1 | Whisper backend | ✅ **Rozhodnuto (Spike B): faster-whisper `large-v3-turbo` int8** (RTF ~0,30 na M4). mlx-whisper zvážit později pro Air/baterii. |

---

## 9. Budoucí featury (mimo v1, backlog)

> Nápady mimo současný plán. Nezávazné, sem si odkládáme směr, kam to může růst.

- **Export historie na RPi / do databáze + analytiky** — Spillway lokálně ukládá přepisy (JSONL, viz O5); do budoucna je odesílat na Raspberry Pi do databáze a stavět nad nimi analýzy (kolik diktuji, v jakých appkách, jaké termíny, WER trendy). Vyžaduje: sync mechanismus (push/pull), schéma DB, dashboard. **Historii proto od začátku ukládat ve strojově čitelném formátu, ať je pozdější export snadný.**
- **Komerční distribuce / prodej** (souvisí s O4) — Developer ID certifikát + notarizace, instalátor (.dmg), licencování, onboarding pro cizí uživatele, případně web. Architekturu držet čistou (žádné natvrdo zadrátované osobní cesty/klíče), ať přechod na produkt není přepis od nuly.
- **Vícejazyčný přepínatelný režim** (rozšíření O7) — `per_app` / `hotkey_switch` pro diktování celých vět v druhém jazyce, pokud se ukáže potřeba.
- **Titulek okna do kontextu** (rozšíření O3) — přesnější úpravy za cenu Screen Recording oprávnění.
- **Streaming / real-time přepis**, **floating HUD s waveform**, **vlastní hlasové příkazy** (např. „nový odstavec", „smazat větu").

---

## 10. Changelog

- **16. 7. 2026** — **Opraveno 15/18 bugů z review + testy + ukázky + predikce spendu.** Opravy B4–B17, B19 (commit `6fcbe4f`; nový modul `lifecycle.py` — single-instance flock). **Testy:** `tests/test_logic.py` (pytest, 19 testů čisté logiky — B8 filtr, B14/B15 prompt, B17 odolnost, profily, perzistence, keymap) — všechny procházejí, `uv run pytest`. **Ukázky formátování:** `spikes/demo_formatting.py` — vzorové diktáty × profily (email/SMS/ai/code + hlasový metapokyn), pustí se s API klíčem. **Predikce spendu:** `spikes/spend_estimate.py` — Haiku ~$0,80–4/měs (typicky), Sonnet ~2–3×, s e-mail kontextem ~2× víc; vše hluboko pod Wispr Flow ($12–15). Whisper lokálně = 0 $. Řeší otevřenou položku R8 (náklady).
- **15. 7. 2026** — **Code review agentem Fable 5 → 18 nových bugů (B4–B21) v §6.** Dostal celý plán + zdrojáky, hledal race conditions/resource leaky/porušení invariantů. Dva kritické: **B4** (zachytávání klávesy nemá timeout/zrušení — může tiše převzít libovolnou klávesu jako hotkey), **B5** (`autostart.enable()` spustí druhou instanci appky souběžně s první). Tři nálezy ověřeny přímo čtením kódu (B4, B5, B9) — sedí přesně. Doporučená priorita: B4/B5 před `.app`, B6/B7/B9/B10 (hotkey/tap stabilita) hned potom, zbytek do F4.
- **15. 7. 2026** — **B2 vyřešen** (mikrofon, potvrzeno uživatelem). **Detekce prohlížeče přes AppleScript/Automation** (`context.browser_context`) — alternativa ke Screen Recording, čte jen URL aktivní karty (Safari/Chrome/Brave/Edge/Arc) → doména vybírá profil. **Hlasový metapokyn** — „toto je e-mail"/„piš to formálně" v promptu, Claude ho použije a nezahrne do výstupu, bez nutnosti oprávnění. Nová otázka **O8**: číst celé e-mailové vlákno jako kontext? (vědomě neimplementováno, čeká na rozhodnutí uživatele — vyšší privacy dopad).
- **15. 7. 2026** — **Konfigurovatelná klávesa + profil pro AI chaty.** Nová karta „Klávesa" v nastavení — tlačítko Změnit spustí `HotkeyListener.start_capture()`, zachytí příští stisk kdekoliv v systému, uloží (settings.json) a hned použije (jen se přepíše `listener.keycode`, tap se nerestartuje). `keymap.py` mapuje keycode → čitelný název pro UI. Vzhled přesunut na konec nastavení. Nový profil formátování **„ai"** (Claude/ChatGPT/Perplexity/Gemini) — diktát se teď formátuje jako srozumitelný prompt, ne jen obecná próza. Odpověď na otázku o prohlížeči: bez detekce webu/URL (rozhodnuto v O3 kvůli Screen Recording), formátuje se jako generic próza; SMS (Zprávy) už má profil „chat".
- **15. 7. 2026** — **Nastavení rozšířeno + logo do lišty.** Settings okno: téma Systém/Světlý/Tmavý (Domovoy palety, „systém" dle OS), výběr primárního jazyka (napojen na Whisper), API klíč vložit→smazat→vložit, slovník na celou šířku. Vše se ukládá (settings.json + Keychain + LaunchAgent) a načítá při startu. Menu bar ikona = Spillway waveform (`baricon.py` template PNG). Obě témata ověřena v náhledu. O7 aktualizováno (jazyk volitelný).

- **14. 7. 2026** — Založen plán. Architektura rozhodnuta (Python + PyObjC menu bar .app, PyInstaller, SMAppService; Docker zamítnut). Definováno 9 modulů, 5 fází (F0–F4), 8 rizik, 6 otevřených otázek. Návrh ověřen agentem Fable 5.
- **14. 7. 2026** — Doplněny 4 funkční požadavky uživatele: **F-a** vícejazyčnost (CZ+EN), **F-b** znalost aplikace + per-app profily, **F-c** slovník výrazů (Whisper hint + Claude prompt), **F-d** chráněné výrazy (preserve verbatim). Rozšířeny moduly `transcribe`/`context`/`llm`, konfigurace (glossary, protected_terms, app_profile, language.mode), fáze F2/F4 a přidána otázka O7 (jazykový režim).
- **15. 7. 2026** — **Domovoy design + HUD.** Uživatel dodal Domovoy brand manuál → uloženo do paměti + `src/spillway/design.py` (Půlnoční paleta, Raleway). Nový `hud.py`: plovoucí status okénko u kurzoru (🔴 Nahrávám / ⏳ Zpracovávám) v Domovoy stylu, poloha u myši. Menu bar ikona teď statická, dynamický status přesunut do HUD. Další: vlastní settings popup okno v Domovoy stylu + Domovoy logo jako ikona v liště.
- **15. 7. 2026** — **F3 menu naplněno.** `tray.py`: červený mikrofon při nahrávání (HUD zrušen dle uživatele), menu s přepnutím modelu (Haiku↔Sonnet), slovníkem, API klíčem, autostartem, kontextem pole. Nové moduly `settings.py` (perzistence, nahrazuje TOML) a `autostart.py` (LaunchAgent). Slovník (F-c/F-d) zapojen do promptu. E-mail vidí celý obsah pole. Souběh ošetřen (B3). B2 mikrofon: v1+v2 selhaly → v3 (gc + diagnostika), jinak AVFoundation. Domovoy = uživatelův projekt → design se použije až na vlastní okno (menu je nativní).
- **15. 7. 2026** — **Kontextové formátování (F-b).** `llm.py` přepsán z pouhé korektury na **formátování dle profilu aplikace** (email/chat/code/generic) + volitelný **kontext z obsahu pole** (`context.focused_field` přes AX → Claude naváže na rozepsaný e-mail, tón). Zachována pojistka B1. `smart_spacing.py` sloučen do `context.focused_field` (jedno AX čtení pro mezeru i kontext). Nový toggle `SPILLWAY_FIELD_CONTEXT`. Uživatel navíc chce menu bar jen jako ikonu appky a status do plovoucího HUD u kurzoru → zapsáno do F3.
- **15. 7. 2026** — **F2 potvrzena + start F3.** F2 kvalita OK (Haiku). B2 mikrofon fix v2 (restart PortAudia po nahrávce). Chytrá mezera: potvrzeno ošetření prázdného pole / pozice 0. **F3 zahájen:** menu bar ikona se stavem (`tray.py`, rumps + Timer), `app.py` běží pod rumps s fallbackem na terminál. Dep `rumps`.
- **15. 7. 2026** — **Ladění F2 dle testů uživatele.** B1 vyřešen (konzervativní prompt — Haiku teď OK). B2 (mikrofon se neuvolňoval) — zpřísněn `audio.stop()` + uvolnění při shutdown. Nová featura: **chytrá mezera** (`smart_spacing.py`) — přes Accessibility zjistí znak před kurzorem a vloží mezeru, když slova hrozí splynout (best-effort, vypínatelné `SPILLWAY_AUTO_SPACE=0`). Přidán dep `pyobjc-framework-ApplicationServices`.
- **15. 7. 2026** — **F1 milník ✅ splněn** (diktát naživo funguje) + **F2 nakódována.** Moduly `context` (NSWorkspace frontmost app, ověřeno), `llm` (Claude `claude-haiku-4-5` cleanup, prompt pro CZ+EN code-switching), `config` (Keychain/env), `set_api_key.py` (getpass). Wiring v `app.py`: kontext → přepis → **[O6]** Claude úprava s fallbackem na raw + viditelná chyba; `--raw` toggle. Deps `anthropic`, `keyring`. Ověřen správný model ID přes claude-api skill. Čeká na test uživatelem (API klíč).
- **15. 7. 2026** — **F1 pipeline nakódována.** Moduly `src/spillway/{hotkey,audio,transcribe,paste,app}.py` + `run_spillway.py`. Přidány deps `sounddevice`, `faster-whisper`, `numpy` do pyproject. Smoke-test OK (importy, konstrukce, přepis přes moduly). Čeká na end-to-end test uživatelem (mikrofon). Halucinace R10 řešeny filtrem v `transcribe`.
- **15. 7. 2026** — **Spike B ✅ / O1 rozhodnuto / F0 milník splněn.** faster-whisper `large-v3-turbo` int8 na M4: RTF ~0,30, teplé načtení 1,6 s, RAM ~1,9 GB, CZ kvalita výborná (jediná code-switching chyba půjde opravit v F2). Backend = faster-whisper. R2 sníženo na 🟢, R5 potvrzeno (auto-unload reálný). **F0 odrizikováno (paste + hotkey + backend) → připraveno na F1.** Přidán `spikes/spike_b_whisper.py`. faster-whisper nainstalován jen do venv (ne do pyproject).
- **14. 7. 2026** — **Spike C2 ✅ / R9 vyřešeno.** F5 (diktovací klávesa) chodí jako normální keyDown/keyUp **keycode 176** a `return None` ji potlačí → **nativní diktování nenaskočí bez jakéhokoli zásahu do Nastavení**. Výchozí hotkey = F5 (176). Pozn.: keycode 176 může být specifický pro tuto klávesnici → hotkey zůstává plně konfigurovatelný (O2). **Hotkey část F0 kompletní** (paste ✅ + hotkey ✅). Další: Spike B (benchmark Whisperu na M4).
- **14. 7. 2026** — **Spike C ✅ dokončen** (pravý ⌥ / keycode 61 → hold-to-talk START/STOP funguje). Uživatel zvolil **F5 jako výchozí klávesu** (obchází R12) → přidán `spikes/spike_c_fkey.py` (Spike C2) na ověření, zda lze přebít nativní diktování/Siri na F5 (R9 aktualizováno na F5).
- **14. 7. 2026** — **Spiky spuštěny na Macu.** Spike A **✅ ověřen** (paste vč. diakritiky a emoji). Spike C **mechanismus ověřen** (tap + Input Monitoring OK, události chodí); přidána do něj diagnostika (`VERBOSE`). Zjištěno: testovací stroj je **iMac M4 / 16 GB** (ne M5 Air) → zapsáno do dashboardu. Nové riziko **R12**: na CZ layoutu kolidují oba Alty s psaním → volbu výchozí klávesy je třeba přehodnotit (pravý ⌘ / dvojí poklep / Caps Lock).
- **14. 7. 2026** — **Start implementace (F0).** Založeno repo (uv, Python 3.12.13, PyObjC Cocoa+Quartz), `.gitignore`, README, scaffold `src/spillway/`. Nakódovány **Spike A** (`spikes/spike_a_paste.py` — paste s Transient/Concealed typy + fixní delay) a **Spike C** (`spikes/spike_c_hotkey.py` — CGEventTap hold-to-talk na pravý ⌥, detekce secure input přes Carbon/ctypes, re-enable po timeoutu). Smoke-test: syntaxe + všechny PyObjC symboly + Carbon ctypes OK. Git inicializován (necommitnuto). **Další krok: uživatel spustí spiky na Macu s TCC oprávněními a zapíše výsledky.**
- **14. 7. 2026** — **Review plánu agentem Fable 5 (zelená pro start)** → korekce: (1) event tap na vlastním vlákně, ne na main threadu (§2); (2) paste — `changeCount` nedetekuje vložení, použít fixní delay + Transient/Concealed pasteboard typy (modul `paste`, R1); (3) potlačení Fn/Globe tapem je nespolehlivé → primární cesta je vypnout diktování v Nastavení, default hotkey pravý ⌥ (R9). Přidána rizika R10 (Whisper halucinace na tichu), R11 (Secure input blokuje i hotkey). Doplněna distribuce Whisper modelu (Spike D), číselná kritéria spiků, poznámka o vědomém nestavění Murmure (§1).
- **14. 7. 2026** — Rozhodnuty otázky O2–O7 (zbývá jen O1 na benchmark). O2 = konfigurovatelný hotkey s cílem převzít klávesu macOS diktování (+ riziko R9, modul `hotkey`, Spike C). O5 = ukládat historii lokálně (JSONL, modul `history`). O6 = viditelná chyba + přesto vložit raw text. O4 = teď ad-hoc, prodej do budoucna. Založena §9 Budoucí featury (RPi/DB/analytiky, komerční distribuce).
