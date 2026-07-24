# Spillway — analýza

> Osobní diktovací nástroj pro macOS: lokální přepis (Whisper na Apple GPU) + AI úprava (Claude API) + univerzální vložení do libovolné aplikace.
> Stav: **v1.0 — funkční, nasazeno.** · Aktualizováno: 24. 7. 2026

---

## 1. Název

**Spillway** — přeliv hráze. Řízené místo, kudy se přebytek pustí ven, aniž by to protrhlo hráz. Myšlenek je víc, než klávesnice stíhá, tak jim otevřeš průchod.

Kategorie diktovacích nástrojů je zaplavená názvy popisujícími mluvení (Wispr, Whisper, Murmur, Hush…). Spillway jako jediný *nepopisuje mluvení* — je zapamatovatelný a volný.

## 2. Motivace

Wispr Flow stojí 12–15 $/měsíc, posílá snímky obrazovky na cizí servery kvůli kontextu a **stylové/tónové úpravy nabízí jen pro angličtinu**. Pro česko-anglický code-switching (běžný v IT: „commitnul jsem to do repository") je jeho hlavní přidaná hodnota nedostupná.

Spillway: **jednotky $/měsíc**, data neopouštějí stroj kromě jednoho textového API volání, plná kontrola nad promptem pro češtinu.

## 3. Jak to funguje (as-built)

| # | Krok | Technologie |
|---|------|-------------|
| 1 | Globální hotkey (hold-to-talk, výchozí F5) | `CGEventTap` na vlastním run-loopu |
| 2 | Nahrávání mikrofonu (jen v RAM, nikdy na disk) | `sounddevice`, 16 kHz mono |
| 3 | Přepis řeči → text | **mlx-whisper na Apple GPU** (`large-v3-turbo`), CPU fallback `faster-whisper` |
| 4 | Kontext (aktivní aplikace, profil, obsah pole) | `NSWorkspace` + Accessibility |
| 5 | Úprava textu | **Claude API** (výchozí `claude-sonnet-5`, `temperature=0`) |
| 6 | Vložení do pole | schránka + `⌘V` (nativně) / naťukání znaků (RDP/AVD) |

**Klíčový insight:** vkládání nevyžaduje integraci per-aplikace. Funguje v nativních (Notes), Electron (Claude desktop) i webových (Gmail) polích, protože jde přes schránku + systémovou zkratku, ne přes API konkrétní appky.

**Dvoustupňová pipeline** (Whisper + Claude) má pro češtinu ještě větší smysl než pro angličtinu: krok 5 je druhá gramatická korektura — z kontextu věty opraví i špatný pád/koncovku, které Whisper foneticky netrefil, a formátuje podle cílové aplikace.

## 4. Čeština — kde to bolí a jak to obcházíme

- Bohatá morfologie (7 pádů) → vyšší chybovost než angličtina; nutný `large-v3(-turbo)`, menší modely se na češtině rozsypou.
- **`language="cs"` je napevno** — auto-detekce hádá z prvních sekund a při začátku anglickým termínem překlopí celou větu do angličtiny.
- Code-switching (CZ + anglické termíny) zvládá slušně, ale termíny občas foneticky počeští → opraví je Claude přes uživatelský slovník v promptu (ověřeno: „komitnul→commitnul", „pool request→pull request").
- **Slovník do Whisperu (`hotwords`) je vypnutý** — bias vkládá termíny, i když nezazněly (porušení „nevymýšlet" rovnou v přepisu). Zkomoleniny řeší bezpečně až Claude.

## 5. Náklady

| Položka | Náklad |
|---------|--------|
| Whisper (lokálně, Apple GPU) | 0 $ |
| Claude (Sonnet 5, ~$3/$15 za M tokenů in/out) | jednotky $/měsíc při běžném používání |
| *Wispr Flow Pro pro srovnání* | *12–15 $/měsíc* |

Haiku je volitelný (levnější/rychlejší). Náklady na AI úpravu se počítají z tokenů a zobrazují v popoveru („Náklady tento měsíc"). Textový kontext (název appky, obsah pole) stačí — screenshoty jako kontext (jak dělá Wispr Flow) by cenu zvedly řádově.

## 6. Známá omezení

- **Secure-input pole** (hesla, Terminal secure entry): event tap nedostává eventy → hotkey je tam dočasně mrtvý, vložení může selhat (~1 %).
- **RDP/AVD (vzdálená Windows plocha):** Accessibility vidí vzdálenou plochu jen jako obrázek → žádný kontext pole, žádná chytrá mezera, HUD u myši. Vkládání funguje (naťukání znaků; vyžaduje v „Windows App" nastavit **Keyboard Mode = Unicode**).
- **HUD ve web/Electron appkách** sedí nad polem, ne přesně u kurzoru (Chromium neposkytuje pozici kurzoru přes AX).
- **`.app` je self-signed, ne notarizovaná** → první spuštění: pravý klik → Otevřít.

## 7. Pozice

Postaveno jako osobní nástroj. Existují alternativy (Murmure – AGPL lokální STT+LLM, Uttr, Dictato…), ale žádná neřeší česko-anglický code-switching s plnou kontrolou nad promptem a s daty na stroji. Architektura je držena čistá (žádné natvrdo zadrátované osobní cesty/klíče), takže případná komerční distribuce (Developer ID + notarizace, licencování, onboarding) je otevřená cesta.
