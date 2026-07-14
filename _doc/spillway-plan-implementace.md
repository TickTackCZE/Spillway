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
| **Aktuální fáze** | F0 — Spiky (🟨 rozjeto: repo + Spike A/C nakódované) |
| **Milník** | Rozhodnutý Whisper backend + paste strategie |
| **Blokery** | Spike A/C čekají na spuštění na Macu (TCC oprávnění + GUI — musí spustit uživatel) |
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
- [x] **Spike A — paste** 🟨 *Kód hotový* (`spikes/spike_a_paste.py`), čeká na spuštění uživatelem (Accessibility + GUI). Zapsat do schránky (+ Transient/Concealed typy) → Cmd+V přes CGEvent → fixní delay → obnovit schránku. Test v 6 appkách (Safari, Chrome, VS Code, Terminal, Slack/Electron, Mail) + password pole + běžící clipboard manager. *Největší riziko celé aplikace.* **Kritérium úspěchu:** paste OK v ≥ 6/6 běžných polí; obnova schránky bez ztráty i s běžícím Maccy; do password pole očekáván fail → změřit, jak vypadá.
- [ ] **Spike B — Whisper benchmark** ⬜ 10s + 60s CZ nahrávky: faster-whisper int8 vs. mlx-whisper vs. whisper.cpp na M5. Měřit latenci, WER na CZ+IT termínech, RAM. Test slovníku (`hotwords` u faster-whisper vs. `initial_prompt` u mlx — nepřenese se 1:1) a zda prompt neprosakuje do výstupu. **Kritérium:** latence 60s nahrávky < ~10 s, přijatelný WER na CZ.
- [x] **Spike C — hotkey** 🟨 *Kód hotový* (`spikes/spike_c_hotkey.py`), čeká na spuštění uživatelem (Input Monitoring + GUI). CGEventTap, modifier-only (pravý ⌥ / Fn), hold-to-talk, chování při přepnutí okna během držení, re-enable po timeoutu. **[R9]** ověřit potlačení klávesy macOS diktování (spíš čekat neúspěch → primární cesta je vypnout diktování v Nastavení). **[R11]** ověřit chování při Secure Keyboard Entry (tap nedostává eventy).
- [ ] **Spike D — bundle** ⬜ PyInstaller balíček s PyObjC+ctranslate2, ad-hoc podpis, ověřit že TCC oprávnění přežijí restart. **[Model]** ověřit stahování Whisper modelu (~1,5 GB) při first-run z HuggingFace do cache (`~/.cache/huggingface` nebo vlastní Application Support) — model **NEsmí** do bundlu; first-run UX s progress barem.

**Milník F0:** ✅ backend vybraný, paste strategie ověřená → jde se stavět.

### F1 — MVP pipeline (bez LLM, bez UI) ⬜
- [ ] hotkey → audio → transcribe → paste
- [ ] config v TOML, spouštění z terminálu
- [ ] **Milník:** diktuju do libovolné appky, raw text se vloží.

### F2 — LLM + kontext ⬜
- [ ] Claude cleanup s fallbackem na raw text
- [ ] NSWorkspace kontext (název appky) → **[F-b]** předání do promptu
- [ ] Keychain pro API klíč, raw-mode toggle
- [ ] **[F-c]** slovník výrazů → Whisper hint + Claude prompt
- [ ] **[F-d]** chráněné výrazy (preserve verbatim) v promptu
- [ ] **[F-a]** ověřit CZ+EN code-switching výstup
- [ ] **Milník:** CZ+EN diktát vychází čistý, slovník a chráněné výrazy respektovány, změřená cena.

### F3 — Aplikace ⬜
- [ ] NSStatusItem + stavy ikony
- [ ] Settings okno / menu
- [ ] PyInstaller .app + podpis + SMAppService autostart + single-instance
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
| — | — | *Zatím žádné bugy — přidávej během implementace* | — | — |

---

## 7. Nedostatky a rizika (tech debt / watchlist)

> Známá rizika z review. Sleduj a mitiguj během příslušné fáze.

| # | Sev | Riziko | Mitigace | Fáze |
|---|-----|--------|----------|------|
| R1 | 🔴 | **Paste spolehlivost** — secure input pole (hesla, Terminal secure entry), Electron/Java vlastní handling; obnova schránky je race-prone (clipboard manageri Raycast/Maccy); počítat s ~1 % selhání | Fixní delay ~150–300 ms (changeCount **nedetekuje** vložení); deklarovat Transient/Concealed pasteboard typy; 3-úrovňový fallback; blacklist appek | Spike A / F1 |
| R2 | 🟠 | **faster-whisper běží na M5 jen na CPU** (CTranslate2 nemá Metal) — mlx-whisper/whisper.cpp výrazně rychlejší a šetrnější k baterii; large-v3-**turbo** má u CZ mírně horší přesnost | Backend abstrahovat, rozhodnout dle benchmarku (Spike B) | Spike B / F1 |
| R3 | 🟠 | **TCC vs. rebuildy** — bez stabilního podpisu se povolení resetují po každém buildu | Stabilní ad-hoc podpis + stabilní Bundle ID; dev wrapper | Spike D / F3 |
| R4 | 🟠 | **Hotkey race conditions** — ztracený key-up (přepnutí Space, spánek, lock) → věčné nahrávání; event tap se tiše zakáže při pomalém callbacku | Max-duration watchdog; reset stavu při sleep/lock; naslouchat `kCGEventTapDisabledByTimeout` a re-enablovat | Spike C / F1 |
| R5 | 🟡 | **Paměť** — model rezidentně ~1,5–2 GB RAM | Na 16GB Airu OK; auto-unload po nečinnosti | F4 |
| R6 | 🟡 | **Privacy** — přepis + titulek okna odchází k Anthropic; titulky umí obsahovat citlivé věci | Titulek okna opt-in; audio nikdy neopouští stroj (komunikovat v UI); Keychain pro klíč | F2 |
| R7 | ⚪ | **Konflikt hotkey** s Raycast/Alfred (drží vlastní event tapy) | Konfigurovatelnost = nutnost | F1 |
| R8 | ⚪ | **Náklady** — potvrdit odhad ~$1–3/měs při reálném používání | Krátký cache-ovatelný systémový prompt; měřit v F2 | F2 |
| R9 | 🟠 | **[O2] Převzetí klávesy macOS diktování** — Fn/Globe a dvojí Control jsou obsluhované nízko v systému; `return None` z tapu je spolehlivě nepotlačí. Navíc Fn se běžně používá (Fn+šipky, fkeys) → kolize s hold-to-talk | **Primární cesta: uživatel v Nastavení macOS nastaví Globe/diktování na „Do Nothing"/Off** a Spillway klávesu převezme; potlačení tapem jen bonus. Doporučený default hotkey = **pravý ⌥**, Fn jako opt-in | Spike C / F1 |
| R10 | 🟡 | **Whisper halucinace na tichu** — na tichém/krátkém audiu vrací fantomové věty (typicky „Titulky vytvořil…") | `vad_filter=True` + post-filtr v `transcribe` (zahodit známé fráze, min. délku); detekce ticha už v `audio` | F1 |
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
| O7 | [F-a] Jazykový režim | **`fixed cs`** — jen slova (anglické termíny uvnitř CZ řeší Whisper, celé EN věty se zatím neřeší). |

**Otevřené (rozhodne se během spiků):**

| # | Otázka | Řešení |
|---|--------|--------|
| O1 | Whisper backend: faster-whisper vs. mlx-whisper/whisper.cpp | Rozhodne benchmark (**Spike B**) |

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

- **14. 7. 2026** — Založen plán. Architektura rozhodnuta (Python + PyObjC menu bar .app, PyInstaller, SMAppService; Docker zamítnut). Definováno 9 modulů, 5 fází (F0–F4), 8 rizik, 6 otevřených otázek. Návrh ověřen agentem Fable 5.
- **14. 7. 2026** — Doplněny 4 funkční požadavky uživatele: **F-a** vícejazyčnost (CZ+EN), **F-b** znalost aplikace + per-app profily, **F-c** slovník výrazů (Whisper hint + Claude prompt), **F-d** chráněné výrazy (preserve verbatim). Rozšířeny moduly `transcribe`/`context`/`llm`, konfigurace (glossary, protected_terms, app_profile, language.mode), fáze F2/F4 a přidána otázka O7 (jazykový režim).
- **14. 7. 2026** — **Start implementace (F0).** Založeno repo (uv, Python 3.12.13, PyObjC Cocoa+Quartz), `.gitignore`, README, scaffold `src/spillway/`. Nakódovány **Spike A** (`spikes/spike_a_paste.py` — paste s Transient/Concealed typy + fixní delay) a **Spike C** (`spikes/spike_c_hotkey.py` — CGEventTap hold-to-talk na pravý ⌥, detekce secure input přes Carbon/ctypes, re-enable po timeoutu). Smoke-test: syntaxe + všechny PyObjC symboly + Carbon ctypes OK. Git inicializován (necommitnuto). **Další krok: uživatel spustí spiky na Macu s TCC oprávněními a zapíše výsledky.**
- **14. 7. 2026** — **Review plánu agentem Fable 5 (zelená pro start)** → korekce: (1) event tap na vlastním vlákně, ne na main threadu (§2); (2) paste — `changeCount` nedetekuje vložení, použít fixní delay + Transient/Concealed pasteboard typy (modul `paste`, R1); (3) potlačení Fn/Globe tapem je nespolehlivé → primární cesta je vypnout diktování v Nastavení, default hotkey pravý ⌥ (R9). Přidána rizika R10 (Whisper halucinace na tichu), R11 (Secure input blokuje i hotkey). Doplněna distribuce Whisper modelu (Spike D), číselná kritéria spiků, poznámka o vědomém nestavění Murmure (§1).
- **14. 7. 2026** — Rozhodnuty otázky O2–O7 (zbývá jen O1 na benchmark). O2 = konfigurovatelný hotkey s cílem převzít klávesu macOS diktování (+ riziko R9, modul `hotkey`, Spike C). O5 = ukládat historii lokálně (JSONL, modul `history`). O6 = viditelná chyba + přesto vložit raw text. O4 = teď ad-hoc, prodej do budoucna. Založena §9 Budoucí featury (RPi/DB/analytiky, komerční distribuce).
