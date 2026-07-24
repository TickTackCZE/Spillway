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

**Kvalita a skládání — sekání na TICHU kvalitu nezhoršuje, spíš zlepšuje.** Klíčové zjištění z researche: špatné je jen **fixní** sekání (uprostřed slova) — to zhoršuje přesnost. **VAD sekání na tichu** naopak dává čistší hranice, míň driftu a **míň halucinací** (WhisperX přesně tohle dělá: VAD segmenty → slepit na ~30 s okna s řezy v tichu). Takže:
- **Švy jsou v tichu → slova se nesekají**, spojení segmentů = prosté zřetězení textů (+ doporučený ~2–3 s překryv proti ztrátě slova na kraji). Nejchoulostivější část z minula (dedup slov na švu) je díky řezu v tichu skoro triviální.
- **Ztráta globálního kontextu** mezi vzdálenými segmenty je u dlouhého souvislého vyprávění reálná, ale u diktátu (krátké, samostatné věty) zanedbatelná — a **Claude v druhém kroku čte celý text**, takže případný šev dorovná.

**Pozn. k dnešnímu VAD:** dnes se audio **neseká** — výchozí mlx cesta má jen energetickou bránu proti tichu (`_is_silence`, boolean na celém klipu), faster-whisper má silero VAD, ale jako jedno volání po puštění. Takže „už se to rozděluje" zatím **neplatí** — streaming by tu segmentaci musel přidat (silero onnx je v bundlu, běží levně na CPU během nahrávání).

**Potřebný zásah (střední):** silero VAD během nahrávání → uzavřené segmenty přepisovat průběžně na mlx vlákně, po puštění dopřepsat poslední (otevřený) segment a zřetězit; přesun bodu zrušení „před Whisper" → „před Claude". **Verdikt:** kvalita **není bloker** (řez v tichu), hlavní práce je streamovací smyčka a VAD za běhu. Hezké zrychlení pro střední/dlouhé diktáty → dobrý kandidát na v2.

Zdroje: [ufal/whisper_streaming](https://github.com/ufal/whisper_streaming), [WhisperX (VAD cut&merge na 30 s)](https://ora.ox.ac.uk/objects/uuid:fece4192-95b7-4db8-a018-3cf728040194), [chunking strategie](https://www.saytowords.com/blogs/Whisper-Audio-Chunking/).

### 8.2 Odložené doručení — spolehlivost a scénáře

**Jak by to vypadalo — krok za krokem (jednoduše):**
1. Podržíš klávesu a normálně diktuješ.
2. Během nahrávání si Spillway **potichu poznamená cíl**: která **appka + okno** má fokus, a krátký **otisk** pole (kousek textu, co v něm byl / že bylo prázdné). *Nezapamatuje si samotné pole* — odkaz na textové pole je křehký (web/Electron ho re-renderem zneplatní).
3. Pustíš klávesu. Text se **hned nevloží** — vpravo dole naskočí malý chip: `Zpracovávám… → Připraveno ✓`.
4. Ty jsi mezitím odešel jinam (proto je to „odložené").
5. **Doručení, dvě cesty:**
   - **Vrátíš se do pole sám** (klikneš do něj) → Spillway pozná, že jsi zpět v zapamatované appce+okně, ověří otisk a **vloží**.
   - **Klikneš na chip** → Spillway požádá systém, ať tu appku+okno vytáhne dopředu; když to projde a pole sedí, **vloží**.
6. **Pojistka:** když cokoli nesedí (appka zavřená, jiné pole, nejde ověřit) → **nevkládá naslepo**, nechá text ve schránce a chip řekne „stiskni ⌘V". Text se nikdy neztratí — v nejhorším zmáčkneš ⌘V.

**Omezení jednoduše:** na novém macOS (Sonoma+) často nepůjde „klik na chip → appka sама dopředu" → dostaneš fallback ⌘V. Ve web/Electron polích Spillway pole neověří → taky ⌘V. Jen jeden čekající text (bez fronty). Po restartu Spillway s čekajícím textem → cíl neplatný → jen zkopírovat.

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

**Konkrétní otázky:**

- **Jak si pamatuje appku a okno?** Appku přes **bundle ID + PID** (`NSRunningApplication`), okno přes **CGWindowID** (`kCGWindowNumber`) — unikátní číslo okna, stabilní, dokud okno žije. *Pole* se nepamatuje (odkaz na prvek je křehký).
- **Víc polí v jednom okně (formulář).** Samotné appka+okno nestačí — po aktivaci appka vrátí fokus do *naposledy* zaměřeného pole, což *obvykle* je to tvoje, ale ne vždy. Proto **otisk obsahu**: při doručení přečteme aktuálně zaměřené pole přes AX a porovnáme s uloženým otiskem. Sedí → vlož; jiné pole (jiný obsah) → **nevkládat**, fallback ⌘V. *Limit:* dvě prázdná pole mají stejný (prázdný) otisk → nerozlišíš → radši ⌘V.
- **Víc oken Chrome.** Každé okno = jiné CGWindowID; zapamatujeme to konkrétní. Vytáhnout dopředu *správné* okno jde přes AX (`AXWindow` s odpovídajícím CGWindowID → `AXRaise`). ALE pole uvnitř je **web** → AX ho neověří ani netrefí přesnou záložku → pro prohlížeč reálně: vytáhnout okno, zbytek **⌘V** (text ve schránce). Přepnutá záložka = cíl pryč.
- **Když začnu diktovat a zůstanu v poli (dnešní chování).** Žádná změna — odložené doručení se **zapne jen když se fokus mezitím přesune**. Když jsi po dokončení pořád ve stejném poli (otisk sedí), **vloží se hned jako dnes**. Logika je jednotná: „jsem si jistý cílem → vlož hned; fokus se přesunul → chip a odlož". Takže to není nová cesta navíc, ale fallback k té dnešní.

Zdroje: [activateWithOptions na Sonoma](https://developer.apple.com/forums/thread/739524), [bring another app to foreground](https://developer.apple.com/forums/thread/793253).

### 8.3 Automatický slovník — přehodnoceno (původní návrh byl slabý)

**Kritika sedí:** stavět slovník jen z historie `raw`→`final` (Whisper→Claude) je **málo užitečné**. Ten diff totiž zachytí jen to, co **Claude už sám opravuje** — takže přidání do slovníku je z velké části **redundantní** (Claude to trefí příště tak jako tak). Jediný přínos: konzistence + hotwords pro Whisper (ty jsou ale vypnuté, protože halucinují). Málo muziky.

**Kde je ta cenná informace:** termíny, které **Whisper i Claude minou zároveň** — vzácné slovo, které ani jeden nezná (název produktu „Domovoy", jméno člověka, niche knihovna). Whisper ho přeslechne, Claude ho nezná → nechá zkomoleninu nebo hádá špatně. **Tohle se v `raw`→`final` NIKDY neobjeví jako oprava** (Claude to neopravil). Objeví se to jen tam, kde to **ty ručně opravíš ve vloženém textu** — a to je přesně signál, který dnes Spillway nevidí (vloží a zapomene).

**Proč „vidět jen výstup Whisperu a Claude" nestačí** (tvůj postřeh): ten pár ukazuje jen Claudovy jistoty. Neznámé termíny (ty do slovníku patří) v něm chybí, protože se nikde neopravily — jen se vložily špatně a ty jsi je pak přepsal rukou.

**Možné zdroje signálu (od nejlepšího k nejhoršímu na realizaci):**

| Zdroj | Co zachytí | Realizace |
|---|---|---|
| **Ruční oprava vloženého textu** (ideál) | přesně to, co Whisper+Claude minuli | **těžké:** po vložení znovu číst pole přes AX a diffovat — kdy vzorkovat? uživatel dál píše, pole se mění z mnoha důvodů → **šumné přiřazení**; navíc **soukromí** (čtení toho, co jsi napsal) a jen v AX-čitelných polích. „Bez vnímání uživatele" = přesně ta invazivní část. |
| **Claude označí vlastní nejistotu** (realistické) | jména/vzácné termíny, u kterých si Claude nebyl jistý | Claude ve výstupu vrátí navíc malý seznam `uncertain_terms`. Automatické, bez čtení polí, pár tokenů navíc. Zachytí část případu „oba minuli" (Claude přizná nejistotu). |
| **Re-diktát krátce po sobě** | „řekl jsem to špatně" | signál „něco bylo blbě", ale **nedá správný tvar** → k slovníku k ničemu. |
| **⭐ Vlastní psaní uživatele (korpus)** | termíny, které uživatel reálně používá, **napsané správně** | Spillway UŽ čte obsah cílového pole (kontext pro Claude). Z něj (a z vloženého výsledku) posbírat opakující se **vlastní jména / camelCase / žargon** → to jsou přesně vzácné termíny, které chceš, ve správném tvaru. |

**Nejlepší úhel — učit se z toho, co uživatel sám píše správně (korpusově).** Standardní přístup ke „custom vocabulary" je **korpus** (slovník z doménových textů), ne diff oprav. A Spillway má korpus zadarmo: **obsah polí, který už čte jako kontext**. Když se v tvých e-mailech / editoru opakovaně objeví `Kubernetes`, `TrackIO`, `Domovoy` napsané správně, Spillway je vidí a může je vzít jako **známé termíny** → přidat do slovníku (do promptu pro Claude). Výhody: automatické, neinvazivní (žádné dodatečné čtení polí „po ruční opravě"), používá data, co už máme, a chytá **přesně tvůj slovník ve tvém pravopise**. Filtr: opakující se tokeny, které vypadají jako termín (velké písmeno uprostřed, ne-české slovo, žargon), ne běžná slova.

**Poctivý verdikt:** původní `raw`→`final` je slabé (souhlas). Použitelné a užitečné jsou **dva automatické zdroje**: (1) ⭐ **korpus z vlastního psaní** (kontext pole) — hlavní; (2) **`uncertain_terms` od Claude** — doplněk na jména, co Claude přizná, že nezná. Obojí bez invazivního čtení polí po opravě, bez zásahu uživatele. Slovník se aplikuje jen do **promptu pro Claude** (bezpečné), ne jako Whisper hotwords (ty halucinují). Ruční „ideál" (číst opravy z pole) nechat být — šum + soukromí to nevyváží.

Zdroje: [word boosting / custom vocabulary](https://www.mindstudio.ai/blog/word-boosting-ai-transcription-custom-vocabulary), [korpusové custom vocabulary](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-to-text), [Gladia custom vocabulary](https://www.gladia.io/blog/custom-vocabulary-stt-accuracy).
