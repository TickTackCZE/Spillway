# Spillway — rozvoj a nápady

> Otevřené problémy a směry rozvoje. **Nic tady není hotové ani rozhodnuté** — podklad k diskuzi, ne plán (ten je v [spillway-plan-implementace.md](spillway-plan-implementace.md)).
> Aktualizováno: 24. 7. 2026 (po v1.0). Hotové věci vyškrtnuty.

---

## 1. Otevřené problémy

### 1.1 Rychlé druhé stisknutí F5 = zahozený diktát
- Když stiskneš F5 znovu dřív, než doběhne zpracování předchozího diktátu (`PROCESSING`), nový se **zahodí** („zaneprázdněno") — schválně žádná fronta, aby text nespadl do špatného pole.
- **Dopad:** při rychlém tempu se občas diktát „ztratí".
- **Možnosti:** krátká fronta s revalidací cíle (viz 2 — odložené doručení), nebo aspoň zvukový/vizuální signál „zaneprázdněno", ať je jasné, že se nenahrává.

### 1.2 Vkládání po přepnutí okna
- Když během zpracování přepneš do jiné appky, text se nevloží do cizího pole — skončí ve schránce + upozornění. Bezpečné, ale musíš ho vložit sám. **Řešení viz 2.**

### 1.3 Tvrdý zásek mlx přepisu blokuje GPU vlákno
- Všechny GPU operace jdou přes jedno vlákno. Kdyby mlx přepis někdy tvrdě zamrzl (ne jen zpomalil), další diktáty by se do něj řadily až do restartu (UI ale díky watchdogu nezmrzne).
- **Možnost:** detekovat zaseklý submit a **restartovat GPU vlákno** (znovu vytvořit `_MlxWorker`), místo čekání na restart appky.

---

## 2. Odložené doručení přes popup („text je připraven")

Když opustím okno, popup se přesune **doprava dolů** a ukazuje `Zpracovávám → Zpracováno`. Kliknutím se aktivuje původní aplikace a text se vloží do pole, které jsem měl vybrané. Řeší 1.1 i 1.2.

### 2.1 Jak by to fungovalo
1. Při diktování si Spillway zapamatuje **cíl** (viz 2.2).
2. Text se **automaticky nevloží**. Indikátor se přesune na pevné místo (vpravo dole): `Zpracovávám…` → `Zpracováno ✓`.
3. Doručení: **klik na popup** → aktivuje appku + okno, vloží; nebo **návrat do pole sám** → vloží se.

### 2.2 Jak BEZPEČNĚ zapamatovat pole (ověřeno experimenty)
- **Nespoléhat na „podržený" odkaz na prvek** (`AXUIElement`) — u webu/Electronu ho re-render zneplatní.
- **Spolehlivé:** zapamatovat **aplikaci + okno** a při doručení ji **aktivovat** — appka si sama obnoví fokus do pole (ověřeno: aktivace + `⌘V` trefilo správné pole, i když odkaz na prvek selhal).
- **Pojistka = otisk obsahu:** uložit prefix textu v poli + PID + číslo okna. Před vložením revalidovat (žije PID? sedí otisk?). Když nesedí → nevkládat naslepo, jen schránka + „stiskni ⌘V".

### 2.3 Odstupňované chování podle jistoty
| Jistota | Chování |
|---|---|
| Vysoká (nativní appka, otisk sedí) | vloží automaticky |
| Střední (appka běží, pole nejde ověřit — web) | aktivuje appku, nevkládá naslepo; schránka + „⌘V" |
| Cíl zmizel | nabídne jen zkopírování |

### 2.4 Mezní situace
- Víc čekajících textů → fronta s náhledem cíle. Nevyzvednutý text → timeout (~5–10 min) → do historie, nezahazovat. Restart Spillway s čekajícím textem → cíl neplatný → jen zkopírování. Perzistence fronty je nová bezpečnostní plocha (citlivý obsah) → zvážit šifrování/kratší timeout.

### 2.5 Náročnost a doporučení
- macOS ~1,5–2,5 týdne na existující bázi. **Levné 80 % užitku:** k dnešnímu „text ve schránce + upozornění" přidat jen **klik → aktivuj appku + vlož** (pár dní, bez fronty/perzistence). Plnou verzi dostavět, až se ukáže, že jednoduchá nestačí.
- Klik na popup navíc **legitimně** splňuje windowsí podmínku pro `SetForegroundWindow` → přenáší se čistě na budoucí Windows port.

---

## 3. Zrychlení pipeline

Kroky jdou sekvenčně (Claude potřebuje hotový přepis). Přepis je díky mlx GPU rychlý (~1,5–2 s na 10 s řeči); dominantní zbývá Claude (~2–3 s síť + inference).

- **Streaming přepis během mluvení.** Dnes je to **dávkově**: dokud držíš klávesu, NIC se nepřepisuje — celé audio se pošle Whisperu až po puštění, takže na přepis čekáš teprve tehdy. Streaming = přepisovat průběžně **po segmentech, už zatímco mluvíš**; po puštění klávesy zbývá jen poslední kousek → čekání po puštění skoro zmizí. Velký přínos, ale koliduje s modelem „Escape zruší celý diktát před zaplacením" a je to větší architektonický zásah → vyšší riziko.
- **Auto-výběr modelu** — Haiku pro krátké/jednoduché (nižší latence), Sonnet pro delší/složité; přepínat podle délky.
- **Prompt caching** systémového promptu — ~100–300 ms na opakovaných voláních v krátkém sledu.
- Streamovaná odpověď Claude **nepomůže** — text se vkládá až celý.

---

## 4. Kvalita a chování

- **Adaptivní unload** — místo fixní 1 min držet model, dokud „aktivně diktuješ" (hodně diktátů v poslední době → delší práh), a uvolnit až po delší pauze. Míň churnu při souvislé práci.
- **Auto-detekce jazyka per diktát** s prahem jistoty — default primární jazyk, přepnout jen když je detekovaný jazyk jiný A jistota vysoká (plná auto-detekce by česko-anglický mix zhoršila).
- **Undo posledního vložení** — „oops" klávesa, která smaže právě vložený text.
  Nejjednodušší spolehlivě: poslat cílové appce `⌘Z` (paste je ve většině appek
  jeden undo krok). Alternativa: pamatovat vložený text a smazat N znaků
  Backspacem — křehké, když se mezitím pohnul kurzor. K čemu: rychlá náprava po
  špatném přepisu / vložení do jiného pole, bez ručního mazání. (Nižší priorita —
  Escape už ruší před vložením a `⌘Z` zvládneš i sám.)
- **Slovník jako páry „špatně → správně"** místo plochého seznamu.
- **Zvuk při startu/konci nahrávání** (diktování „naslepo").

---

## 5. UI a distribuce

- **Onboarding wizard oprávnění** — mikrofon / Accessibility / Input Monitoring, živá detekce + deep-linky do Nastavení; první spuštění po instalaci.
- **Editor per-app / per-doména profilů v UI** — teď pevná mapa v `context.py`.
- **Zabalit Raleway font** (jinak UI padá na systémový — funkčně OK).
- **Polish HUD:** multi-monitor pozice, první stav před doload WKWebView HTML.
- **Notarizace** (Developer ID) — odstraní Gatekeeper varování; předpoklad komerční distribuce (licencování, onboarding cizích uživatelů).

---

## 6. Data a platformy

- **Export historie na RPi / DB + analytiky** — kolik/kde/jaké termíny diktuji, WER trendy. Historie se od začátku ukládá strojově čitelně (`history.jsonl`).
- **Windows port** — jádro (Whisper, Claude, statistiky) je přenositelné (~1/3 kódu), přepsat platformní vrstvu (klávesa, vkládání, kontext, UI). Princip držet jednotný: **schránka + zkratka / naťukání, Accessibility jen na čtení.**

---

## 7. Další nápady (nové, k rozmyšlení)

- **Náhled / potvrzení před vložením (volitelně).** Režim, kdy se upravený text ukáže v malém okně, můžeš ho doupravit a teprve `Enter` ho vloží. Pro důležitá pole (e-mail zákazníkovi) — jistota před nevratným vložením. Vypnuté by default (přidává klik).
- **Vynucení profilu klávesou.** Druhá zkratka, která diktuje rovnou v režimu `email` / `ai` bez ohledu na aktivní appku (např. psát prompt do AI, i když nejsi zrovna v AI okně).
- **Kopírovat místo vložit.** Modifikátor při puštění klávesy (podržet ⇧) → výsledek jen do schránky, nevkládat. Užitečné, když chceš text jinam, než kde zrovna jsi.
- **„Přemluvit" — nahradit poslední vložení.** Podržet poslední audio; zkratka = přepsat/znovu upravit poslední diktát a nahradit vložený text (undo + nové vložení). Řeší „řekl jsem to blbě".
- **Hlasové editační příkazy** — „nový odstavec", „odrážka", „smazat větu", „velké písmeno". Rozpoznat je v přepisu a promítnout do formátování, ne je vložit jako text.
- **Automatický slovník.** Sledovat, které termíny Claude opakovaně opravuje (raw → final), a nabídnout je k přidání do uživatelského slovníku. Statistiky „co se nejčastěji opravuje" jako podklad.
- **Ikona v liště odráží stav** (nahrávám / zpracovávám), nejen plovoucí HUD — přehled i bez pohledu ke kurzoru.
- **Rychlá pauza / tichý režim** — dočasně vypnout hotkey (např. při hovoru), bez ukončení appky.

---

## 8. Research (24. 7. 2026)

### 8.1 Streaming přepis — zrychlení a zásah

**Dnešní stav (dávkově):** dokud držíš klávesu, Whisper NIC nepřepisuje — celé audio jde do modelu až po puštění. Metrika, na které záleží, je **čekání PO puštění** = RTF × délka. Na Apple GPU (mlx `large-v3-turbo`, RTF ~0,08–0,22): 10 s řeči ≈ **1–2 s** čekání, 20 s ≈ **2–4 s**.

**Se streamingem** se přepisuje průběžně během mluvení; po puštění zbývá jen poslední kousek → čekání spadne na **~0,3–0,6 s** bez ohledu na délku.

| Délka diktátu | Čekání dnes | Se streamingem | Úspora |
|---|---|---|---|
| krátký (3–5 s) | ~0,5–1 s | ~0,4 s | malá (nemá cenu) |
| střední (10 s) | ~1–2 s | ~0,5 s | **~50–70 %** |
| dlouhý (20 s+) | ~2–4 s | ~0,5 s | **~75 %** |

**Dvě cesty implementace:**
- **LocalAgreement-n** (ufal `whisper_streaming`) — potvrzuje tokeny, když se N po sobě jdoucích oken shodne na prefixu. Dělané pro živé titulky (latence ~3,3 s u souvislé řeči). Pro nás **overkill** — my živý text nezobrazujeme.
- **Segmentově (sedí nám líp)** — VAD rozseká audio na pauzách; hotové segmenty se přepisují už během mluvení, po puštění se přepíše jen poslední (otevřený) segment a spojí se. Bez živého zobrazení. Přínos roste s tím, jak moc mezi větami pauzuješ; u souvislé řeči bez pauz benefit zmizí (spadne to na dávku).

**Kompatibilní s tvým požadavkem na zrušení:** Whisper běží lokálně a zdarma i během mluvení; **po puštění pořád zbývá okamžik (poslední segment + volání Claude), kdy Escape stihne zrušit, než se text pošle do Claude** (placený/nevratný krok). Bod zrušení se jen posune z „před Whisperem" na „před Claude" — to je pro nás OK.

**Potřebný zásah (střední–vyšší):** inkrementální snapshoty audia z Recorderu; smyčka na mlx vlákně (přepis rostoucího audia / hotových segmentů); **spojování segmentů** (hranice slov, dedup překryvu — nejchoulostivější část); přesun bodu zrušení. **Riziko:** kvalita na hranicích segmentů (Whisper je nejpřesnější s plným 30s kontextem — sekání může zhoršit přesnost na švech). **Verdikt:** hezké zrychlení pro střední/dlouhé diktáty, ale netriviální a s rizikem kvality → spíš v2, ne teď.

Zdroje: [ufal/whisper_streaming](https://github.com/ufal/whisper_streaming), [whisper_streaming_web](https://github.com/codesdancing/whisper_streaming_web).

### 8.2 Odložené doručení — spolehlivost a scénáře

**Klíčové zjištění (Apple forums):** od **macOS Sonoma (14+) Apple omezil cross-app aktivaci** — `NSRunningApplication.activateWithOptions` / `activate(ignoringOtherApps:)` je nespolehlivé/deprecated; appka už nemůže volně vytáhnout jinou appku do popředí. Existuje kooperativní `activate(from:)` (14+) pro předání aktivace po uživatelově gestu, ale je křehké napříč verzemi.

**Dopad:** krok „klik na popup → Spillway sám aktivuje cílovou appku → vloží" je na nové macOS **nespolehlivý**. Řešení: nespoléhat na auto-aktivaci, ale na **návrat uživatele do pole** (klik do pole = přirozený fokus) a/nebo kooperativní `activate(from:)` po kliku na popup, s **tvrdým fallbackem „text ve schránce + ⌘V"**.

| Scénář | Chování | Odhad spolehlivosti |
|---|---|---|
| Nativní appka, otisk sedí, aktivace projde | auto-vloží | vysoká (macOS ≤ Ventura), nižší na Sonoma+ |
| Cross-app aktivace selže (Sonoma+) | fallback: schránka + „⌘V", nebo počkat na klik do pole | ~100 % (bezpečné) |
| Web/Electron pole nejde ověřit | neaktivovat naslepo → schránka + „⌘V" | ~100 % (bezpečné) |
| Uživatel klikl jinam než do původního pole | otisk nesedí → nevkládat | pojistka drží |
| Cíl zavřený / Spillway restart | jen zkopírování | ~100 % |

**Chybovost:** „plně automatické" doručení vyjde spolehlivě hlavně u nativních appek na starším macOS nebo když se uživatel do pole vrátí sám; na Sonoma+ čekej, že auto-aktivace často selže → spadne na **bezpečný fallback ⌘V** (v nejhorším zmáčkneš ⌘V). Web/Electron nikdy nevkládej naslepo. **Hodnota** tedy není v garantované auto-aktivaci, ale v **zapamatovaném cíli + doručení na jeden klik / při návratu + bezpečném fallbacku**. Takhle je featura užitečná i s Apple omezeními.

Zdroje: [activateWithOptions na Sonoma](https://developer.apple.com/forums/thread/739524), [bring another app to foreground](https://developer.apple.com/forums/thread/793253).

### 8.3 Automatický slovník — mining oprav z historie

**Koncept je zavedený** (učení z post-editace / custom vocabulary), ale máme **výhodu zdarma**: v `history.jsonl` už držíme `raw` (Whisper) i `final` (Claude) u každého diktátu → opravy jde vytěžit bez extra nákladů.

**Jak by to fungovalo:**
1. **Diff `raw` → `final`** na úrovni slov (`difflib.SequenceMatcher`) → seznam nahrazení (co Claude změnil).
2. **Filtr na „slovníkový materiál"** — jen záměny, kde vznikl anglický/technický termín v kanonickém tvaru (`pool request→pull request`, `komitnul→commitnul`, `hagging fejs→Hugging Face`). Zahodit běžnou gramatiku/interpunkci (to není do slovníku). Heuristika: malá fonetická vzdálenost + cílový tvar je ne-české slovo / camelCase / známý žargon.
3. **Agregace + práh** — počítat (špatně→správně) napříč historií; když se stejná oprava opakuje ≥N×, je to kandidát.
4. **Návrh uživateli** v nastavení: „Přidat *Hugging Face* do slovníku? (Claude opravoval 5×)" → klik přidá kanonický termín. Díky tomu ho příště Whisper/Claude trefí konzistentně a je potvrzený (ne odhad Claude).

**Náročnost: nízká–střední** (diff + počítání je triviální; ladění filtru je hlavní práce). **Vše lokálně** (žádná nová data ven). **Riziko: nízké** — je to jen návrh, nic se nepřidá bez potvrzení. **Verdikt:** z těch tří **nejsnadnější a nejpraktičtější** — staví na už existujících datech a řeší dnes ruční slovník.

Zdroje: [post-editing STT korekce](https://aws.amazon.com/blogs/machine-learning/build-a-custom-vocabulary-to-enhance-speech-to-text-transcription-accuracy-with-amazon-transcribe/), [Gladia custom vocabulary](https://www.gladia.io/blog/custom-vocabulary-stt-accuracy).
