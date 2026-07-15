# Spillway

Lokální diktovací nástroj pro macOS: **Whisper** (lokální přepis) → **Claude** (úprava textu) → **univerzální vložení** do libovolné aplikace. Konfigurovatelná klávesa, běh na pozadí.

- 📄 Plán a stav implementace: [`_doc/spillway-plan-implementace.md`](_doc/spillway-plan-implementace.md)
- 📄 Původní analýza: [`_doc/spillway-analyza.md`](_doc/spillway-analyza.md)

Stav: **fáze F1 — MVP pipeline** (F0 spiky ověřeny; viz plán).

## Spuštění (F1 MVP)

```bash
uv run python run_spillway.py
```
Podrž **F5**, mluv česky, pusť → přepsaný text se vloží do aktivní aplikace.
Ctrl+C ukončí. **Oprávnění:** Microphone + Input Monitoring + Accessibility
(pro aplikaci, ze které spouštíš — Terminal / VS Code). Model se při prvním
běhu stáhne (~1,5 GB) do HuggingFace cache.

---

## Vývojové prostředí

Používá se [uv](https://docs.astral.sh/uv/). Python 3.12 si uv doinstaluje sám.

```bash
uv sync            # vytvoří .venv a nainstaluje závislosti
```

> ⚠️ **Google Drive:** repo je ve složce synchronizované Google Drivem. Pokud
> začne být sync `.venv` otravný (hlavně po přidání faster-whisper), založ
> virtualenv mimo Drive: `uv venv ~/.venvs/spillway` a nastav
> `export UV_PROJECT_ENVIRONMENT=~/.venvs/spillway`.

---

## Spiky (F0)

Před psaním zbytku ověřujeme 4 nejrizikovější věci. Každý spike vyžaduje udělení
macOS oprávnění aplikaci, ze které ho spouštíš (Terminal / iTerm / VS Code).

### Spike A — paste (největší riziko, R1)
```bash
uv run python spikes/spike_a_paste.py ["vlastní text"]
```
**Oprávnění:** System Settings → Privacy & Security → **Accessibility** (jinak
`CGEventPost` tiše nic neudělá). Skript odpočítá pár sekund — klikni do cílového
pole. Otestuj v 6 aplikacích (Safari, Chrome, VS Code, Terminal, Slack, Mail) +
password poli (očekáván fail). **Kritérium:** OK v ≥ 6/6 běžných polí, obnova
schránky bez ztráty i s běžícím clipboard managerem (Maccy/Raycast).

### Spike C — hotkey (R4/R9/R11)
```bash
uv run python spikes/spike_c_hotkey.py
```
**Oprávnění:** System Settings → Privacy & Security → **Input Monitoring**
(pro potlačení eventů i **Accessibility**). Drž a pusť pravý ⌥ → START/STOP
"nahrávání". Ověř [R9] (potlačení klávesy macOS diktování — spíš neúspěch → radši
diktování v Nastavení vypnout) a [R11] (chování při Secure Keyboard Entry).

### Spike B — Whisper benchmark (R2) · Spike D — bundle (F3)
Zatím nezahájeny — viz plán §5.

---

## Výsledky spiků

Zapisuj do bug trackeru / poznámek v plánu (`_doc/spillway-plan-implementace.md`,
§5 a §6). To je zdroj pravdy o stavu.
