# Spillway — plán implementace

> Živý dokument: aktuální stav a otevřená rozhodnutí. **Hotové věci žijí v git historii, ne tady.**
> Vychází z [spillway-analyza.md](spillway-analyza.md). Aktualizováno: 24. 7. 2026 (v1.0).

---

## Co je Spillway

Osobní diktovací nástroj pro macOS. Lokální přepis řeči (mlx-whisper na Apple GPU) → úprava přes Claude → univerzální vložení do libovolné aplikace. Hold-to-talk na konfigurovatelnou klávesu (výchozí F5), běží na pozadí jako menu-bar app.

**Funkční pilíře:** vícejazyčnost (CZ+EN code-switching), znalost cílové aplikace (profily email/chat/code/ai/generic), uživatelský slovník, zachování registru (nemění význam, necenzuruje, formátuje jen když se hodí).

---

## Současný stav — v1.0, nasazeno ✅

- `.app` sestavená, **stabilně self-signed** (oprávnění přežijí rebuildy), v `/Applications/Spillway.app`. Autostart přes LaunchAgent spouští binárku v bundlu.
- Pipeline end-to-end: F5 → nahrávání → přepis (GPU) → úprava (Claude) → vložení. HUD u kurzoru, auto-unload modelu po **1 min** nečinnosti (→ 0 MB GPU), file-log s jednořádkovým souhrnem každého diktátu.
- **Popover v liště** (levý klik na ikonu): statistiky (počet / slova / čas mluvení), přehled (náklady tento měsíc, ⌀ tempo řeči bez ticha, nejčastější aplikace), 7denní graf aktivity (hover = hodnota), **historie diktátů s kopírováním klikem**, přepínač modelu, stav GPU, Nastavení / Konec.
- **Nastavení** (WKWebView okno): klávesy (diktování + zrušení), primární jazyk, Customizace (autostart, chytrá mezera, „Odesílání do AI modelu" s vnořeným „Číst kontext pole"), slovník, API klíč, vzhled (Systém / Light / Dark), **Data a soukromí** (reset statistik / reset historie — potvrzení po 5s zámku).
- **Zrušení diktátu** klávesou (výchozí Escape) — zahodí pipeline před placeným voláním Claude; klávesa se spolkne jen během zpracování.
- **Náklady** za AI úpravu se počítají z tokenů (ceník per model) a sčítají za měsíc. **Tempo řeči** se počítá z délky bez ticha (`voiced_seconds`). **Reset statistik** (baseline) a **reset historie** (smaže texty) jsou nezávislé.
- Model: **`claude-sonnet-5`** (`temperature=0`, timeout 30 s), Haiku volitelný. Nastavení perzistentní; API klíč jen v Keychain.

---

## Architektura (podstata)

- **Python 3.12 + PyObjC** (AppKit / Quartz / WebKit / ApplicationServices). Menu-bar app (`LSUIElement`), bundle přes **PyInstaller**.
- **CGEventTap** na vlastním run-loopu, callback triviální. F5 = keycode **176**, `return None` potlačí nativní diktování. Watchdog na ztracený key-up, re-enable po timeoutu.
- **Přepis** (`transcribe.py`): dva backendy (přepínač `SPILLWAY_WHISPER_BACKEND`). Výchozí **mlx-whisper na Apple GPU** (`large-v3-turbo`, float16) s **energetickou bránou proti tichu** (mlx nemá VAD). Fallback **faster-whisper CPU** (má VAD, `beam_size=5`) při selhání mlx health-checku. ⚠️ **Všechny mlx GPU operace (načtení / přepis / uvolnění) běží na JEDNOM vyhrazeném vlákně** (`_MlxWorker`) — mlx drží GPU stream per-vlákno, jinak „There is no Stream(gpu, N) in current thread" a spadlý (ztracený) diktát. Model se drží v `ModelHolder`, načte se jednou, přepis ho převezme.
- **Kontext** (`context.py`): AX čtení pole/kurzoru má **messaging timeout 1 s** — nereagující cílová appka jinak zablokuje hlavní vlákno (freeze). Kontext pole se posílá Claudovi vždy (pomoc s tónem/navázáním), ale prompt přísně zakazuje zkopírovat ho do výstupu.
- **Paste** (`paste.py`): nativně schránka (+ Transient/Concealed typy) → `⌘V` → ~250 ms → obnova schránky. **RDP/AVD** (`context.is_windows_target`): text se **naťuká** znak po znaku přes `CGEventKeyboardSetUnicodeString` (klient zahazuje modifikátory ze syntetických událostí → `⌘/Ctrl+V` selhává; vyžaduje Keyboard Mode = Unicode).
- **Odseknutí zásеku:** watchdog v tray sleduje délku PROCESSING — po 90 s soft-cancel (jako Escape), po 120 s tvrdý reset do IDLE + notifikace. Claude volání má timeout 30 s.
- **Cmd+C/V/A** v oknech aplikace zajišťuje vložené **Edit menu** (bez něj neměla zkratka kam poslat akci).
- **Moduly** `src/spillway/`: hotkey, audio, transcribe, context, llm, paste, tray, hud, popover, settings(_window), stats, config, settings, lifecycle, autostart, baricon, keymap, design.
- **⚠️ Podpis je kritický:** TCC granty (Accessibility/Input Monitoring) i Keychain ACL se vážou na code signature. Řeší **stabilní self-signed cert „Spillway Self-Signed"** — designated requirement je konstantní napříč rebuildy. Privátní klíč v login keychainu + záloha `codesign-identity.p12` (mimo git).

---

## Build & nasazení

```bash
bash build/make_codesign_cert.sh   # JEDNOU na stroji — vytvoří podpisový cert
bash build/build_app.sh            # PyInstaller + codesign → build/dist/Spillway.app
bash build/make_dmg.sh             # volitelně DMG instalátor
```

Přeinstalace do `/Applications` (stabilní cesta mimo Google Drive):

```bash
rm -rf /Applications/Spillway.app && ditto build/dist/Spillway.app /Applications/Spillway.app
```

Log: `~/Library/Logs/Spillway/spillway.log` (obsahuje `AXIsProcessTrusted`, stav event tapu a `🏁 diktát: …` souhrn). Testy: `uv run pytest`.

---

## Konfigurace

- **Nastavení:** `~/Library/Application Support/Spillway/settings.json` (model, jazyk, téma, slovník, hotkey, toggly, `auto_unload_min`, `stats_reset_ts`). Pozn.: `settings.set()` ukládá celý slitý dict → změna defaultu v kódu se na existující soubor NEpropíše.
- **API klíč:** macOS Keychain (`keyring`, služba `spillway`), fallback env `ANTHROPIC_API_KEY`. **Nikdy** v repu.
- `.gitignore` blokuje `config.toml`, `.env`, `*.key`, `*.p12`, `*.crt`, `build/dist`, `build/work`.

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
