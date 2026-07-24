# Spillway

Osobní diktovací nástroj pro macOS. Podrž klávesu, mluv, pusť → text se přepíše
lokálně, upraví přes AI a vloží do libovolné aplikace.

**Pipeline:** hold-to-talk (výchozí F5) → **mlx-whisper na Apple GPU** (lokální
přepis) → **Claude** (úprava/formátování) → **univerzální vložení** (`⌘V`, nebo
naťukání do RDP/AVD). Běží na pozadí jako **menu-bar app**.

> Stav: **v1.0** — funkční, nasazeno. Data neopouštějí stroj kromě jednoho
> textového API volání do Claude. API klíč jen v macOS Keychain.

- 📄 [Analýza](_doc/spillway-analyza.md) · [Plán implementace](_doc/spillway-plan-implementace.md) · [Rozvoj a nápady](_doc/spillway-rozvoj-a-napady.md)

## Co umí

- **Vícejazyčnost** — čeština i anglické termíny (code-switching), `language="cs"` napevno.
- **Znalost cílové aplikace** — profily formátování (e-mail / chat / kód / prompt pro AI / obecné).
- **Popover v liště** — statistiky, ⌀ tempo řeči, náklady za měsíc, 7denní graf, historie diktátů (klik = zpět do schránky), přepínač modelu.
- **Nastavení** — klávesy, jazyk, chování (autostart, chytrá mezera, odesílání do AI + čtení kontextu pole), uživatelský slovník, API klíč, vzhled (Systém / Light / Dark), reset statistik a historie.
- **Zrušení diktátu** klávesou (Escape) před placeným voláním AI.
- **Uživatelský slovník** — termíny, které má Claude psát přesně (opraví k nim i přeslechy).

## Instalace (.app)

```bash
bash build/make_codesign_cert.sh   # JEDNOU na stroji — stabilní podpisový cert
bash build/build_app.sh            # PyInstaller + codesign → build/dist/Spillway.app
rm -rf /Applications/Spillway.app && ditto build/dist/Spillway.app /Applications/Spillway.app
open /Applications/Spillway.app
bash build/make_dmg.sh             # volitelně DMG instalátor
```

Podpis stabilním self-signed certem znamená, že **udělená oprávnění přežijí
rebuildy** (jinak by je macOS při každém buildu resetoval). `.app` není
notarizovaná → první spuštění: pravý klik → **Otevřít**.

**Oprávnění (jednorázově):** Microphone · Input Monitoring · Accessibility.
API klíč (Anthropic): nastavíš v okně Nastavení; uloží se do Keychain.

## Spuštění ze zdrojáků (vývoj)

```bash
uv sync                                # .venv + závislosti (Python 3.12 doinstaluje uv)
uv run python run_spillway.py          # s AI úpravou (když je klíč v Keychain)
uv run python run_spillway.py --raw    # jen syrový přepis, bez Claude
uv run python set_api_key.py           # uloží API klíč do Keychain (getpass)
```

Podrž **F5**, mluv, pusť → text se vloží do aktivní aplikace. Model se při prvním
běhu stáhne (~1,5 GB) do HuggingFace cache.

> ⚠️ **Google Drive:** repo je v synchronizované složce. Když sync `.venv` zlobí,
> založ virtualenv mimo Drive: `uv venv ~/.venvs/spillway` +
> `export UV_PROJECT_ENVIRONMENT=~/.venvs/spillway`.

## Model a náklady

Výchozí **`claude-sonnet-5`** (`temperature=0`), Haiku volitelný v Nastavení.
Přepis běží lokálně (0 $). AI úprava = jednotky $/měsíc (počítá se z tokenů,
vidíš ji v popoveru). Bez API klíče běží raw režim (jen přepis).

Přepis: výchozí **mlx-whisper na Apple GPU** (`large-v3-turbo`), fallback
**faster-whisper na CPU** (přepínač `SPILLWAY_WHISPER_BACKEND=mlx|faster`).

## Vzdálená Windows plocha (RDP / AVD)

Vkládání do „Windows App" funguje **naťukáním znaků** — vyžaduje v klientu
**Connections → Keyboard Mode → Unicode** (ve Scancode režimu se modifikátory
i unicode zahazují).

## Konfigurace a data

- Nastavení: `~/Library/Application Support/Spillway/settings.json`
- Historie/statistiky: `~/Library/Application Support/Spillway/history.jsonl`
- Log: `~/Library/Logs/Spillway/spillway.log`
- API klíč: macOS Keychain (služba `spillway`), **nikdy v repu**.

## Testy

```bash
uv run pytest      # testy čisté logiky (bez GUI/API)
```
