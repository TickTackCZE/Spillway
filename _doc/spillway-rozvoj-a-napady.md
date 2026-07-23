# Spillway — problémy a nápady na rozvoj

> Sběrný dokument: otevřené problémy, hypotézy a směry. **Nic tady není rozhodnuté ani hotové** — je to podklad k diskuzi, ne plán implementace (ten je v [spillway-plan-implementace.md](spillway-plan-implementace.md)).
> Založeno: 21. 7. 2026.

---

## 1. Známé problémy

### 1.1 Limit délky nahrávání = 120 s (2 min)
- **Kód:** `audio.py` → `MAX_SECONDS_DEFAULT = 120`. Po 120 s se audio přestane ukládat (callback ignoruje další vzorky), watchdog v `app.py` v **122 s** vynuceně přepne z RECORDING na PROCESSING — i když ještě držíš klávesu. Navenek to vypadá, že „nahrávání se samo vyplo".
- **Proč to tam je:** pojistka proti věčnému nahrávání při ztraceném key-up (spánek, lock). Není to technický strop — 120 s float32 audia = jen ~7,7 MB RAM.
- **Dopad:** delší souvislý diktát (dopis, poznámka) se uřízne.
- **Možnosti:** zvednout limit (např. 5 min); dělat průběžný přepis po segmentech (viz 3.3), takže délka nevadí; ukazovat v HUD zbývající čas / varování „blížíš se limitu".

### 1.2 Výpočet „ušetřeného času" je zavádějící
- **Jak se počítá teď** (`stats.py`): `ušetřeno = čas_psaní − (délka_audia + čas_zpracování)`, kde `čas_psaní = počet_slov / 40 * 60` (**pevných 40 slov/min**).
- **Problém:** celé číslo visí na jediné hádané konstantě — rychlosti psaní. Ta je nastavená nízko (40 slov/min je pomalý pisatel), takže úsporu **nadhodnocuje**. Ukázka na reálném vstupu (37 slov):
  | Předpoklad psaní | Vyjde „ušetřeno" |
  |---|---|
  | 40 slov/min (dnešní default) | ~28 s |
  | 65 slov/min (běžný pisatel) | ~8 s |
  | 80 slov/min (rychlopísař) | ~1 s |
- Tvůj postřeh sedí: kdo píše rychle, tomu reálná úspora skoro mizí — ale dnešní číslo mu pořád tvrdí, že ušetřil hodně.
- **Další slabiny:** proti diktování se počítá celý čas zpracování (čekání), ale psaní se bere jako „čisté" bez přemýšlení/oprav překlepů; rychlost mluvení kolísá; je to v jádru marnivá metrika (podobně jako smazané „zhuštění promptů").
- **Možnosti:** (a) rychlost psaní **nastavitelná** + jednorázová kalibrace („napiš tuhle větu") → číslo bude poctivé pro konkrétního člověka; (b) ukazovat jen **fakta** (počet diktátů, slova, čas mluvení) a úsporu buď škrtnout, nebo jasně označit „oproti psaní rychlostí X"; (c) default zvednout na realističtějších ~60 slov/min.

### 1.3 Vkládání po přepnutí okna
- Když během zpracování přepneš do jiné appky, text se nevloží do cizího pole — skončí ve schránce + upozornění. Bezpečné, ale musíš ho vložit sám. **Řešení viz 2.1.**

### 1.4 Kvalita vs. rychlost přepisu na CPU
- Whisper běží CPU-only (`large-v3-turbo`, RTF ~0,37 na iMacu M4). 17 s řeči = ~6,7 s přepis. To je dominantní část latence. **Viz 3.**

---

## 2. Nápad: odložené doručení přes popup („text je připraven")

Návrh uživatele (21. 7.): když opustím okno, popup se přesune **doprava dolů** a ukazuje stav `Zpracovávám → Zpracováno`. Kliknutím na něj se aktivuje původní aplikace a text se vloží do okna/pole, které jsem měl vybrané.

### 2.1 Jak by to fungovalo
1. Při diktování si Spillway zapamatuje **cíl** (viz 2.2).
2. Text se **automaticky nevloží**. Indikátor se z pozice u kurzoru (dobrá pro živý stav nahrávání) přesune na **pevné místo (vpravo dole)** a ukáže `Zpracovávám…` → `Zpracováno ✓`.
3. Doručení dvěma cestami:
   - **Klik na popup** → aktivuje cílovou appku + okno, vloží text (schránka + ⌘V/Ctrl+V).
   - **Návrat do pole sám** (klikneš tam) → vloží se automaticky.

### 2.2 Jak BEZPEČNĚ zapamatovat pole (ověřeno experimenty + research)
Tohle je nejchoulostivější část. Zjištění:
- **Nespoléhat na „podržený" odkaz na prvek** (`AXUIElement` / UIA element). V testech se stabilní odkaz na textové pole ani nepodařilo pokaždé zachytit, a u webu/Electronu ho re-render stránky/přepnutí záložky zneplatní (vytvoří nový uzel).
- **Naopak spolehlivé:** stačí zapamatovat **aplikaci + okno** a při doručení ji **aktivovat** — appka si sama obnoví fokus do pole, kde jsi naposled psal (ověřeno: aktivace appky + obyčejné ⌘V trefilo správné pole, i když odkaz na prvek selhal).
- **Bezpečnostní pojistka = otisk obsahu.** Při startu diktování si uložit krátký „otisk" pole (prefix textu, který v něm byl) + PID + číslo okna. **Před vložením revalidovat:** žije PID? existuje okno? odpovídá obsah pole otisku? Když cokoli nesedí → **nevkládat naslepo**, jen nechat ve schránce a říct „stiskni ⌘V". (Neplatnost cíle jde detekovat — mrtvý prvek vrací chybu / prázdný obsah.)

### 2.3 Odstupňované chování podle jistoty (ne „trefím/netrefím")
| Jistota | Chování |
|---|---|
| Vysoká (nativní appka, otisk sedí) | vloží automaticky |
| Střední (appka běží, pole nejde ověřit — typicky web) | aktivuje appku, ale **nevkládá naslepo**; text ve schránce + „⌘V" |
| Cíl zmizel (zavřené okno/appka) | nabídne jen zkopírování |

### 2.4 Mezní situace
- Víc čekajících textů → fronta s náhledem cíle.
- Nevyzvednutý text → timeout (~5–10 min) → přesun do historie, **nezahazovat**.
- Diktát „jinam" mezitím → nová položka fronty s vlastním cílem.
- Restart Spillway s čekajícím textem → cíl je vždy neplatný → nabídnout jen zkopírování; frontu perzistovat na disk **je nová bezpečnostní plocha** (citlivý obsah) — zvážit šifrování/kratší timeout.

### 2.5 Cross-platform (Windows do budoucna)
- Klik na popup **legitimně** splňuje windowsí podmínku pro `SetForegroundWindow` („proces přijal poslední vstupní událost") → aktivace projde **bez hacků**. Tohle je nejsilnější část návrhu — přenáší se čistě.
- Trefit konkrétní **pole** je slabší na obou OS (nativní ✅, Electron ⚠️, web ❌) — proto to odstupňování v 2.3.

### 2.6 Náročnost (odhad, jeden vývojář)
- macOS: ~1,5–2,5 týdne (na existující bázi). Windows od nuly: +3–5 týdnů (staví se celá platformní vrstva).
- **Doporučení: udělat po etapách.** Levné 80 % užitku: k dnešnímu „text ve schránce + upozornění" přidat jen **klik → aktivuj appku + vlož**. To je pár dní, bez fronty/perzistence/sledování fokusu. Plnou verzi (auto-vložení při návratu, fronta, historie) dostavět, až se ukáže, že jednoduchá varianta nestačí.

---

## 3. Zrychlení pipeline (cíl: standardní vstup do 3 s)

### 3.1 Kde se ztrácí čas (změřeno, iMac M4)
| Krok | Latence | Pozn. |
|---|---|---|
| Whisper přepis | **RTF ~0,37** → 10 s řeči ≈ 3,7 s | dominantní, CPU-only |
| Claude úprava | ~2,4–2,9 s | síť + inference, běží **až po** přepisu |
| Paste settle | 0,25 s | fixní |
| beam_size 5 vs 1 | rozdíl jen ~0,4 s | **nesahat**, přesnost za to nestojí |

Kroky jdou **sekvenčně** (Claude potřebuje hotový přepis). U 10s vstupu tedy dnes ~6 s, u 17s ~9,5 s. Do 3 s se to dnes nevejde.

### 3.2 Největší páka: `mlx-whisper` (Apple Silicon GPU/ANE) — výhra pro rychlost i kvalitu
- Na Neural Engine/GPU jde RTF stáhnout řádově na ~0,15–0,20 → 10 s řeči ≈ **1,5–2 s** místo 3,7 s.
- **Klíčové:** na GPU se vejde i **plný `large-v3`** (přesnější než dnešní turbo) při **rychlosti lepší než dnešní CPU turbo** → tvoje „zpřesnit a zároveň zrychlit" jde splnit **jedním krokem**.
- Cena: výměna backendu (jiný balíček, jiné bundlování), a **je to macOS-only** — Windows port by musel použít faster-whisper na CPU/CUDA. Backend už je v kódu za rozhraním, takže výměna je ohraničená.

### 3.3 Průběžný přepis během mluvení (streaming)
- Model se dnes už předehřívá při stisku klávesy (dobře). Další krok: **přepisovat po segmentech, už zatímco mluvíš** (VAD v pipeline je). Po puštění klávesy zbývá přepsat jen poslední kousek → **vnímaná latence Whisperu skoro zmizí**, zůstane hlavně Claude.
- Cena: větší architektonický zásah, koliduje s dnešním modelem „Escape zruší celý diktát před zaplacením". Vysoký přínos, vyšší riziko.

### 3.4 Claude — menší páky
- **Přeskočení u krátkých diktátů** (už hotové, <5 s) — u nich Claude nevolá vůbec.
- **Prompt caching** systémového promptu: ~100–300 ms na opakovaných voláních v krátkém sledu.
- **Haiku pro krátké/jednoduché** vstupy (nižší latence než Sonnet), Sonnet pro delší/složité — přepínat podle délky. Kompromis v kvalitě u Haiku.
- Streamovaná odpověď **nepomůže** — text se stejně vkládá až celý.

### 3.5 Realistický verdikt k „do 3 s"
- Pro **kratší** diktáty (do ~8 s řeči): dosažitelné kombinací mlx-whisper (~1,5 s) + Haiku/skip (~1 s) + paste (0,25 s) ≈ **pod 3 s**.
- Pro **dlouhé** diktáty (15 s+): pod 3 s reálně jen se streamingem (3.3), protože jinak sám přepis trvá víc.
- **Doporučené pořadí:** (1) mlx-whisper — jediná změna, co zrychlí i zpřesní; (2) prompt caching + auto-model; (3) streaming až jako velký krok, pokud první dva nestačí.

---

## 4. Další nápady (parkoviště)
- **Historie diktátů v menu** — data už se ukládají (`history.jsonl`), chybí UI. Klik → zpět do schránky. Zároveň záchrana, když se vložení nepovede.
- **Undo posledního vložení.**
- **Slovník jako páry „špatně → správně"** místo plochého seznamu.
- **Náklady v korunách/dolarech** místo znaků (přes `count_tokens` + ceník).
- **Zvuk při startu/konci nahrávání** (diktování „naslepo").
- **Editor per-app/per-doména profilů v UI** (teď natvrdo v `context.py`).
- **Windows port** — jádro (Whisper, Claude, statistiky) je přenositelné (~1/3 kódu), přepsat platformní vrstvu (klávesa, vkládání, kontext, UI). Princip vkládání držet jednotný: **schránka + zkratka, Accessibility jen na čtení**.

---

## 5. Architektonické pravidlo (z researche 21. 7.)
**Text se vkládá výhradně přes schránku + simulovanou zkratku (⌘V/Ctrl+V).** Accessibility/UI Automation se používá **jen ke čtení** kontextu, **nikdy k zápisu** — přímý zápis nefunguje v Electronu/webu/RDP a na Windows je ještě horší (ValuePattern přepíše celé pole). Výjimky musí být explicitní a předvídatelné (dnes: RDP → Ctrl+V).
