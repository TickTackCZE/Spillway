# Spillway — plán implementace

> Živý dokument: aktuální stav a otevřená rozhodnutí. **Hotové věci žijí v git historii, ne tady.**
> Vychází z [spillway-analyza.md](spillway-analyza.md). Aktualizováno: 5. 8. 2026 (v1.2).

---

## Co je Spillway

Osobní diktovací nástroj pro macOS. Lokální přepis řeči (mlx-whisper na Apple GPU) → úprava přes Claude → univerzální vložení do libovolné aplikace. Hold-to-talk na konfigurovatelnou klávesu (výchozí F5), běží na pozadí jako menu-bar app.

**Funkční pilíře:** vícejazyčnost (CZ+EN code-switching), znalost cílové aplikace (profily email/chat/code/ai/generic), uživatelský slovník, zachování registru (nemění význam, necenzuruje, formátuje jen když se hodí).

---

## Současný stav — v1.2, nasazeno ✅

- `.app` sestavená, **stabilně self-signed** (oprávnění přežijí rebuildy), v `/Applications/Spillway.app`. Autostart přes LaunchAgent spouští binárku v bundlu. DMG instalátor volitelně.
- Pipeline end-to-end: klávesa → nahrávání → přepis (GPU) → úprava (Claude) → vložení. **Streaming**: segmentuje se v tichu a přepisuje už během mluvení, po puštění klávesy dobíhá jen poslední úsek.
- **Rozhoduje, kam text patří.** Zjištění fokusu je na JEDNOM místě (`context.focus_snapshot`) a rozhoduje **editovatelnost prvku** (`AXValue` je settable), ne role ani přítomnost výběru textu. Podle toho se řídí poloha okénka i volba vložit / nechat ve schránce, takže se nemůžou rozejít. Když pole není nebo z něj odejdeš, text zůstane ve schránce s lístkem „Připraveno k vložení".
- **Okénko (HUD)** má jen dvě polohy: u kurzoru, nebo pod ikonou v liště se špičkou na ni. U myši nikdy.
- **Ikona v liště odráží stav** — v klidu logo, při nahrávání živý ukazatel hlasitosti z mikrofonu, při zpracování vlna běžící zleva doprava, při rušení sražené sloupce. Snímky se kreslí procedurálně ze sdílené geometrie (`design.scaled_bars` / `wave_bars`), žádné externí assety.
- **Popover v liště**: statistiky, náklady za měsíc, ⌀ tempo řeči bez ticha, nejčastější aplikace, 7denní graf, historie diktátů s kopírováním klikem, přepínač modelu, stav GPU, Nastavení / Nápověda / Konec.
- **Okno se dvěma záložkami**: Nastavení (klávesy, jazyk, Customizace vč. prahu uvolnění modelu 10–600 s, slovník, API klíč, vzhled, Data a soukromí) a **Nápověda** — schémata funkcí přímo v aplikaci, kreslená ze stejné geometrie jako ikona.
- **Každá nevratná akce má pětisekundové potvrzení** — reset statistik, reset historie i smazání API klíče.
- **Diagnostika** (`diag.py`) je standardně vypnutá; zapíná se klíčem `diagnostics` nebo `SPILLWAY_DIAG`. Bez ní se do logu píše jen jednořádkový souhrn diktátu.
- **Zrušení diktátu** klávesou (výchozí Escape) před placeným voláním Claude; klávesa se spolkne jen během zpracování.
- Model: **`claude-sonnet-5`** (`temperature=0`, timeout 30 s), Haiku volitelný. Nastavení perzistentní; API klíč jen v Keychain.

---

## Architektura (podstata)

- **Python 3.12 + PyObjC** (AppKit / Quartz / WebKit / ApplicationServices). Menu-bar app (`LSUIElement`), bundle přes **PyInstaller**.
- **CGEventTap** na vlastním run-loopu, callback triviální. F5 = keycode **176**, `return None` potlačí nativní diktování. Watchdog na ztracený key-up, re-enable po timeoutu.
- **Přepis** (`transcribe.py`): dva backendy (přepínač `SPILLWAY_WHISPER_BACKEND`). Výchozí **mlx-whisper na Apple GPU** (`large-v3-turbo`, float16) s **energetickou bránou proti tichu** (mlx nemá VAD). Fallback **faster-whisper CPU** (má VAD, `beam_size=5`) při selhání mlx health-checku. ⚠️ **Všechny mlx GPU operace (načtení / přepis / uvolnění) běží na JEDNOM vyhrazeném vlákně** (`_MlxWorker`) — mlx drží GPU stream per-vlákno, jinak „There is no Stream(gpu, N) in current thread" a spadlý (ztracený) diktát. Model se drží v `ModelHolder`, načte se jednou, přepis ho převezme.
- **Kontext** (`context.py`): na `AXFocusedUIElement` sahá **jediná funkce** (`_focused_element`), všechno ostatní z ní odvozuje přes `focus_snapshot()`, který čte jen to, co si volající vyžádá. Dřív se ptaly čtyři funkce nezávisle a mohly se rozejít — okénko pak viselo jinde, než kam text šel. AX čtení má **messaging timeout 1 s** — nereagující cílová appka jinak zablokuje hlavní vlákno (freeze). Kontext pole se posílá Claudovi vždy (pomoc s tónem/navázáním), ale prompt přísně zakazuje zkopírovat ho do výstupu.
- **Paste** (`paste.py`): nativně schránka (+ Transient/Concealed typy) → `⌘V` → ~250 ms → obnova schránky. **RDP/AVD** (`context.is_windows_target`): text se **naťuká** znak po znaku přes `CGEventKeyboardSetUnicodeString` (klient zahazuje modifikátory ze syntetických událostí → `⌘/Ctrl+V` selhává; vyžaduje Keyboard Mode = Unicode).
- **Odseknutí zásеku:** watchdog v tray sleduje délku PROCESSING — po 90 s soft-cancel (jako Escape), po 120 s tvrdý reset do IDLE + notifikace. Claude volání má timeout 30 s.
- **Cmd+C/V/A** v oknech aplikace zajišťuje vložené **Edit menu** (bez něj neměla zkratka kam poslat akci).
- **Ikona** (`baricon.py`): snímky se generují líně a cachují; animaci řídí existující `rumps.Timer` v trayi, takže v klidu nestojí nic. Ikona je *template* — macOS ji obarví podle motivu.
- **Moduly** `src/spillway/`: hotkey, audio, transcribe, context, llm, paste, tray, hud, popover, settings(_window), stats, config, settings, diag, lifecycle, autostart, baricon, keymap, design.
- **⚠️ Podpis je kritický:** TCC granty (Accessibility/Input Monitoring) i Keychain ACL se vážou na code signature. Řeší **stabilní self-signed cert „Spillway Self-Signed"** — designated requirement je konstantní napříč rebuildy. Privátní klíč v login keychainu + záloha `codesign-identity.p12` (mimo git).

---

## Build & nasazení

```bash
bash build/make_codesign_cert.sh   # JEDNOU na stroji — vytvoří podpisový cert
bash build/build_app.sh            # PyInstaller + codesign → build/dist/Spillway.app
bash build/make_dmg.sh             # volitelně DMG instalátor
```

Přeinstalace do `/Applications` (stabilní cesta mimo synchronizované složky —
TCC granty se vážou na cestu i podpis):

```bash
rm -rf /Applications/Spillway.app && ditto build/dist/Spillway.app /Applications/Spillway.app
```

> ⚠️ macOS si ikony cachuje podle cesty **a názvu souboru**. Po překreslení ikony
> proto nestačí přeinstalovat — je potřeba buď změnit název `.icns`, nebo
> aplikaci odregistrovat (`lsregister -u`), smazat, restartovat Dock a teprve
> pak nainstalovat. Vlastní cache mají i nástroje třetích stran, které ikony
> zobrazují (alternativní taskbary, launchery).

Log: `~/Library/Logs/Spillway/spillway.log` (obsahuje `AXIsProcessTrusted`, stav event tapu a `🏁 diktát: …` souhrn). Testy: `uv run pytest`.

---

## Konfigurace

- **Nastavení:** `~/Library/Application Support/Spillway/settings.json` (model, jazyk, téma, slovník, hotkey, toggly, `auto_unload_sec`, `diagnostics`, `stats_reset_ts`).
  Pozn.: `settings.set()` ukládá celý slitý dict → změna defaultu v kódu se na existující soubor NEpropíše. Pro změny formátu slouží `settings._migrate()` (tam se řešil i přechod `auto_unload_min` → `auto_unload_sec`).
- **API klíč:** macOS Keychain (`keyring`, služba `spillway`), fallback env `ANTHROPIC_API_KEY`. **Nikdy** v repu.
- `.gitignore` blokuje `config.toml`, `.env`, `*.key`, `*.p12`, `*.crt`, `build/dist`, `build/work`.

---

## Směr produktu (v1.3+)

Rozhodnuto: aplikace se bude **monetizovat** (viz [rozvoj a nápady, sekce 6](spillway-rozvoj-a-napady.md)).
Model: **roční licence (~1 000 Kč) + vlastní API klíč uživatele.** Nulový variabilní
náklad, žádný proxy v cestě diktátu. Licence je podepsaný klíč ověřovaný **offline**
(Ed25519), prodejna typu Lemon Squeezy generuje klíče i řeší DPH — vlastní server zatím
netřeba. Před prodejem: **notarizace**, ověřování licence, automatické aktualizace,
export diagnostiky, průvodce oprávněními, anglické UI. Repozitář musí přestat být veřejný.

Největší nová funkce v plánu je **režim schůzka** — dlouhý přepis čistě lokálně, bez AI
a bez sítě. Dělí se na dva scénáře: **Mac na stole** (mikrofon slyší všechny — žádné zachytávání
zvuku systému, snadná půlka) a **online hovor** (nutné zachytit zvuk systému; macOS 14.4+
to umí bez ovladače). Otevřené: běh přes hodinové nahrávky (dnešní strop je 5 minut v RAM)
a rozlišení mluvčích přes ONNX modely, bez tažení PyTorch do bundlu.

---

## Otevřená rozhodnutí

- **Kontext pole u e-mailu:** profil `email` posílá `field_text[:3000]`, tj. i citovanou historii a podpis. Prompt zakazuje echo, ale je to velký blok tokenů. Zvážit omezení jen na text nad citací. (Vypínač „Číst kontext pole" existuje.)
- **Sjednocení celého pole (`Cmd+A` + přepis) → ZAMÍTNUTO:** AX vrací pole jako plochý text vč. citace a podpisu, `paste.py` píše plain text → přepis by nevratně smazal HTML podpis i historii. Případně jen nad `AXSelectedText`, nikdy `Cmd+A`, a až po undo.

---

## Vědomé výjimky z pravidla „nevymýšlet"

Základ: nikdy nevzniká obsah, který uživatel nenadiktoval. Jediná schválená výjimka — **e-mailová etiketa** (profil `email`): když oslovení/zakončení nezazní, doplní se „Dobrý den," / „S pozdravem". **Jméno do podpisu se nikdy nevymýšlí.** Ostatní profily nepřidávají nic.

---

## Profil `ai` — proč je agresivní

Diktování promptu do AI čte model, ne člověk. Změřeno na reálné historii: „šetrný" prompt zhušťoval jen o ~13 % a úsečné poznámky rozepisoval do vět. Přeboostovaný profil (výstup kratší, odrážky od 2 zadání, pryč zdvořilosti a vata) zhušťuje ~29 % bez ztráty požadavků. Obsah nedotknutelný — krátí se forma, ne informace.

---

## Architektonické pravidlo

**Text se vkládá výhradně přes schránku + zkratku (`⌘V`), nebo naťukáním znaků (RDP).** Accessibility se používá **jen ke čtení** kontextu, **nikdy k zápisu** — přímý zápis nefunguje v Electronu/webu/RDP. Výjimky musí být explicitní a předvídatelné.
