# Spillway

> Vlastní diktovací nástroj pro macOS: lokální přepis (Whisper) + AI úprava (Claude API) + univerzální vkládání do libovolné aplikace.
> Stav: koncept / pre-MVP · Datum: 14. 7. 2026

---

## 1. Název

**Spillway** — přeliv hráze. Řízené místo, kudy se přebytek pustí ven, aniž by to protrhlo hráz. Myšlenek je víc, než klávesnice stíhá, tak jim otevřeš průchod.

**Proč zrovna tenhle:** kategorie diktovacích nástrojů je zaplavená názvy, které popisují mluvení — Wispr, Whisper, Murmur, Hush, Sotto, Uttr, Utterly, Blurt, Babble. Každé slovo pro tiché mluvení už někdo zabral, protože všichni přišli na stejný nápad. Spillway je jediný název, který *nepopisuje mluvení* — a proto je zapamatovatelný a volný.

**Známé kolize (žádná fatální):**
- `AdRoll/spillway` — Erlang OTP knihovna na load shedding (jiná kategorie)
- SpillwayPro — hydraulický software US Bureau of Reclamation
- SEO bude vždycky zaplavené hydraulikou přehrad — relevantní jen pro komerční produkt, ne pro osobní nástroj

**Zvažované alternativy ze stejné rodiny (volné):** Sluice, Weir, Penstock, Siphon, Retort, Bellows

---

## 2. Motivace

Wispr Flow stojí 12–15 $/měsíc, posílá snímky obrazovky na cizí servery kvůli kontextu a **stylové/tónové úpravy nabízí jen pro angličtinu**. Pro česko-anglický code-switching (běžný v IT: „commitnul jsem to do repository") je jeho hlavní přidaná hodnota nedostupná.

Spillway: **~1–3 $/měsíc**, data neopouštějí stroj kromě jednoho textového API volání, plná kontrola nad promptem pro češtinu.

---

## 3. ⚠️ Nejdřív si přečti tohle: konkurence

Během rešerše názvu vyplavalo padesát existujících produktů v přesně téhle kategorii. Několik z nich **dělá přesně to, co Spillway zamýšlí** — a jsou zdarma a open-source.

| Nástroj | Co umí | Proč je relevantní |
|---------|--------|--------------------|
| **Murmure** (`Kieirra/murmure`, AGPL) | Lokální STT + LLM post-processing, global hotkey, vloží text kamkoliv, **podporuje češtinu**, připojíš vlastní LLM server | Celá naše pipeline, hotová, zdarma |
| **Hush** (`khawkins98/Hush`) | Lokální whisper.cpp, push-to-talk, audio jen v RAM (nikdy na disk), cross-platform | Funguje i na Windows PC |
| **Uttr** (`uttr.pro`) | STT pro macOS s **editovatelným cleanup promptem** | Doslova náš návrh, komerčně |
| **Dictato** (`dicta.to`) | Offline diktování, per-app profily (jiný tón pro Slack/Gmail/editor), 19,99 € jednorázově | Per-app tón bez subscription |
| **Sotto** (`sotto.to`) | Lokální, wake-word, transform mode, $49 jednorázově | |

**Doporučení: než napíšeš první řádek kódu, stáhni si Murmure a dva týdny ho používej.**

Pokud ti sedne, ušetřil sis víkend. Pokud ti bude chybět jen prompt pro česko-anglický code-switching, je to open-source — forkneš a doladíš, což je pořád levnější než stavět od nuly. Spillway má smysl stavět jen tehdy, když ti ani jeden z nich nesedne, nebo když to chceš postavit **kvůli tomu stavění samotnému** (což je legitimní důvod, ale je dobré si ho přiznat).

---

## 4. Architektura

| # | Krok | Technologie | AI? | Obtížnost |
|---|------|-------------|-----|-----------|
| 1 | Globální hotkey | `NSEvent` monitor (pyobjc) | ne | ★☆☆☆☆ |
| 2 | Nahrávání mikrofonu | `sounddevice` / `pyaudio` | ne | ★☆☆☆☆ |
| 3 | Přepis řeči → text | `faster-whisper`, model `large-v3-turbo`, `language="cs"` | ASR model | ★★★☆☆ |
| 4 | Zjištění kontextu | `NSWorkspace.frontmostApplication` + název okna | ne | ★★☆☆☆ |
| 5 | Úprava textu | Claude API (Haiku 4.5) | **LLM** | ★★☆☆☆ |
| 6 | Vložení do pole | schránka + simulace `Cmd+V` přes `CGEvent` | ne | ★★★★☆ |

**Klíčový insight:** vkládání textu nevyžaduje integraci per-aplikace. Paste podporuje každé textové pole — nativní (Notes), Electron (Claude desktop), webové (Gmail). To je důvod, proč to funguje „všude".

**Nejtěžší část:** krok 6 — spolehlivost napříč aplikacemi. Alternativa přes Accessibility API (`AXUIElementSetAttributeValue`) je čistší, ale funguje jen tam, kde appka accessibility pořádně implementuje. Paste je robustnější default.

---

## 5. Čeština — kde to bolí a jak to obejít

**Whisper na češtině:**
- Bohatá morfologie (7 pádů, skloňování) → vyšší chybovost než angličtina; u srovnatelně komplexních jazyků (finština) se WER pohybuje kolem 10–15 %
- Nutno použít `large-v3` / `large-v3-turbo` — menší modely (tiny/base/small) jsou trénované hlavně na angličtinu a na češtině se rozsypou
- **Vždy nastavit `language="cs"` napevno** — auto-detekce hádá z prvních sekund audia a při začátku anglickým termínem přepne celou větu na angličtinu
- Slabší interpunkce a kapitalizace než u angličtiny
- Code-switching (CZ + anglické technické termíny) zvládá slušně, ale termíny občas foneticky počeští

**Proč dvoustupňová pipeline dává pro češtinu ještě větší smysl než pro angličtinu:**
Krok 5 (Claude) není jen kosmetika — funguje jako **druhá gramatická korektura**. Z kontextu věty dokáže opravit i špatný pád nebo koncovku, kterou Whisper fonicky netrefil. U angličtiny tahle oprava tolik nenaskočí, protože tam Whisper chybuje málo.

**Náčrt system promptu pro krok 5:**
```
Toto je syrový přepis mluveného textu určený pro aplikaci: {app_name}.
- Odstraň výplňová slova (ehm, jako, prostě) a nedokončené začátky vět
- Doplň interpunkci a kapitalizaci
- Oprav gramatické a pádové chyby vzniklé při přepisu řeči
- Anglické technické termíny ponech beze změny, neopravuj je na české ekvivalenty
- Zachovej autorův styl a tón; nepřidávej vlastní obsah
- Přizpůsob formálnost cílové aplikaci (Slack = neformální, e-mail = formálnější)
Vrať POUZE upravený text, bez komentáře.
```

---

## 6. Náklady

| Položka | Náklad |
|---------|--------|
| Whisper (lokálně, MacBook Air M5) | 0 $ |
| Claude Haiku 4.5 (1 $/5 $ za M tokenů in/out) | ~2 $/měsíc při 10 000 slov denně |
| **Celkem** | **~1–3 $/měsíc** |
| *Wispr Flow Pro pro srovnání* | *12–15 $/měsíc* |

Čeština s diakritikou se tokenizuje o něco méně efektivně než angličtina → rozdíl v haléřích.
Screenshoty jako kontext (jak dělá Wispr Flow) by cenu zvedly řádově — textový kontext (název appky/okna) stačí.

---

## 7. Rizika

| Riziko | Dopad | Mitigace |
|--------|-------|----------|
| **Existující nástroj to už umí líp** | **Vysoký** | **Nejdřív vyzkoušet Murmure (viz §3)** |
| Scope creep → další nedokončený side-project | Vysoký | Tvrdý MVP scope (níže), timebox 1 víkend |
| Aplikace ignoruje simulovaný `Cmd+V` | Střední | Fallback na Accessibility API; blacklist problémových appek |
| Latence Whisperu na CPU/ANE | Střední | `large-v3-turbo` (~6× rychlejší); benchmark na M5 před rozhodnutím |
| Paste přepíše obsah schránky | Nízký | Uložit předchozí obsah, po vložení obnovit |
| Latence Claude API v pipeline | Nízký | Haiku je rychlá; volitelně raw mode (přeskočit AI krok) |
| macOS permissions (mikrofon, Accessibility, Input Monitoring) | Nízký | Jednorázové udělení, ošetřit onboarding |

---

## 8. MVP scope (timebox: 1 víkend)

**In scope:**
- [ ] Globální hotkey (hold-to-talk)
- [ ] Nahrávání → `faster-whisper` `large-v3-turbo`, `language="cs"`
- [ ] Claude Haiku cleanup s promptem výše
- [ ] Vložení přes schránku + `Cmd+V`
- [ ] Kontext = jen název aktivní aplikace
- [ ] Funguje spolehlivě ve 4 appkách: **Claude, Chrome/Gmail, Slack, VS Code**

**Out of scope (v1):**
- Multiplatformnost (Windows PC neřešíme)
- GUI / menu bar ikona (stačí běžící skript)
- Screenshoty jako kontext
- Vlastní slovník / custom vocabulary
- Streaming přepis v reálném čase (stačí batch po dokončení nahrávky)

**Definition of done:** nadiktuju v češtině odstavec do Gmailu, vyjde gramaticky správný text s interpunkcí, anglické termíny zachované, bez ručního zásahu.

---

## 9. Postup

1. **Vyzkoušej Murmure** (2 týdny). Nejlevnější způsob, jak zjistit, jestli ti diktování vůbec sedí do workflow — a možná zjistíš, že Spillway nepotřebuješ.
2. **Ověř nejtěžší část.** Pokud jdeš stavět: napiš 30řádkový skript, který jen zkopíruje text na schránku a simuluje `Cmd+V`. Otestuj ve všech 4 cílových appkách. Když tohle nefunguje spolehlivě, zbytek nemá smysl stavět — a zjistíš to za půl hodiny místo za víkend.
3. Teprve pak stav zbytek pipeline.

---

```
spillway start     # spustí daemon
spillway config    # nastavení hotkey, modelu, promptu
spillway --raw     # přeskočí AI cleanup
```
