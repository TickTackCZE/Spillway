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
- Model: **`claude-sonnet-5`** (výchozí, `temperature=0`); Haiku volitelný v nastavení.
- Nastavení (téma / jazyk / model / klíč / slovník / klávesa) perzistentní; API klíč jen v Keychain.

---

## Architektura (podstata)

- **Python 3.12 + PyObjC** (AppKit / Quartz / WebKit / ApplicationServices). Menu-bar app (`LSUIElement`), bundle přes **PyInstaller**.
- **CGEventTap** na vlastním vlákně/CFRunLoop, callback triviální. F5 = keycode **176**, `return None` potlačí nativní diktování. Watchdog na ztracený key-up, re-enable po timeoutu.
- **Přepis:** faster-whisper `large-v3-turbo` int8, CPU (RTF ~0,30 na M-čipu, reload ~1,6 s). `vad_filter=True` (Silero VAD asset se balí přes `collect_data_files`).
- **Paste:** zápis do schránky (+ Transient/Concealed typy) → Cmd+V přes CGEvent → fixní delay ~250 ms → obnova schránky.
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

- **O8 — celé e-mailové vlákno jako kontext?** Teď se čte jen doména aktivní karty (→ profil), ne obsah. Číst celé vlákno by zlepšilo odpovědi, ale pošle víc textu k Anthropic (privacy dopad). Chceš? Jen Mail.app, nebo i webmail (Gmail/Outlook v prohlížeči)?
- **O9 — sjednocení celého pole při doplnění.** Místo navázání na existující text přeformulovat celé pole + nový diktát do jednoho celku (Cmd+A → přepsat). Doporučení: **volitelný** režim spouštěný explicitně (tlačítko / hlasový pokyn), ne výchozí (jinak hrozí „vylepšení" už hotových částí + ztráta rich-text formátování). Chceš to?

---

## Next steps (zbývá dodělat)

- **Onboarding wizard oprávnění** — mikrofon / Accessibility / Input Monitoring, live detekce + deep-linky do Nastavení; první spuštění po instalaci.
- **Autostart pro `/Applications` verzi** — nahradit dřívější LaunchAgent (dev verzi, zneškodněnou) login-itemem podepsané `.app` (SMAppService).
- **Modul `history`** — ukládání přepisů (JSONL: čas, appka, raw, upravený text, jazyk) + historie posledních N v menu (klik → zpět do schránky).
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

## Známá omezení

- **Paste:** počítat s ~1 % selhání ve secure-input polích (hesla, Terminal secure entry). Při aktivním Secure Keyboard Entry event tap nedostává eventy → hotkey dočasně mrtvý.
- **HUD ve web/Electron appkách** sedí nad polem (ne přesně u kurzoru) — Chromium/Electron neposkytuje pozici kurzoru přes Accessibility.
- **`.app` je self-signed, ne notarizovaná** → první spuštění: pravý klik → Otevřít (nebo Nastavení → Soukromí → Otevřít i tak).
- **Náklady Claude:** Sonnet ~2–3× Haiku, typicky jednotky $/měsíc, hluboko pod komerčními nástroji (Wispr Flow $12–15).
