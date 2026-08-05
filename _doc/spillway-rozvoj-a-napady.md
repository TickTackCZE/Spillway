# Spillway — rozvoj a nápady

> Kam dál. **Nic tady není hotové ani slíbené** — je to podklad k rozhodování, ne plán práce
> (ten je v [spillway-plan-implementace.md](spillway-plan-implementace.md)).
> Stav aplikace: **v1.2** · Aktualizováno: 5. 8. 2026
> **Sekce 7 = odmítnuto / neaktuální. Ty nápady se do návrhů nevracejí.**

---

## Co Spillway dnes umí

**Diktování**
- Podržíš klávesu (výchozí **F5**), mluvíš, pustíš → text se vloží tam, kde píšeš.
- Přepis běží **lokálně na GPU** (mlx-whisper, model `large-v3-turbo`); záloha na CPU.
- **Streaming**: přepisuje se už během mluvení (řeže se v tichu), takže po puštění klávesy čekáš jen na poslední kousek.
- **Escape** zruší diktát dřív, než se zaplatí AI úprava.
- Limit jednoho diktátu: 5 minut.

**Úprava textu (Claude)**
- Opraví interpunkci, pády, zkomolené anglické termíny; vycpávky („ehm", „prostě") vyhodí.
- **Pozná přeřeknutí**: „sejdeme se ve 4 nebo teda v 5" → „sejdeme se v 5".
- **Nevymýšlí si** — věrohodnost je nadřazená všemu; nesrozumitelné zkomoleniny maže místo hádání, termíny ze slovníku jsou chráněné.
- **Formátuje podle cílové aplikace** — jiný tón pro e-mail, chat, editor, prompt do AI.
- **Angličtina zůstává anglicky** (nepřekládá „meeting" na „schůzka").
- **Uživatelský slovník** — termíny, které má psát přesně.
- AI úpravu jde úplně vypnout (pak nic neodchází ven).

**Vkládání**
- Kamkoliv přes schránku + `⌘V`; do **vzdálené Windows plochy** (RDP/AVD) naťukáním znaků.
- **Chytrý oddělovač** — nic / mezera / nový řádek: uprostřed věty mezera, za dokončenou větou ve víceřádkovém poli nový řádek (další záznam pod sebe).
- Když **odejdeš z pole nebo z aplikace**, text se nevloží jinam — zůstane ve schránce.
- Když **není kam vložit** (nemáš zaklikané žádné pole), text se rovnou nechá ve schránce s lístkem — nevkládá se naslepo.

**Ikona v liště**
- V klidu základní vlnovka; při **nahrávání se hýbe podle hlasitosti** mikrofonu (poznáš, že tě slyší), při **zpracování** jí běží vlna zleva doprava.
- Kreslí se procedurálně jako „šablona", takže si ji macOS sám obarví podle světlého/tmavého motivu.

**Okénko u kurzoru (HUD)**
- Ukazuje `Nahrávám` / `Zpracovávám` / `Ruším` přímo u textu, kam píšeš.
- Má jen **dvě polohy**: u kurzoru, nebo pod ikonou v liště (se špičkou na ikonu) — když pozice kurzoru není k dispozici nebo odejdeš z cílové aplikace. U myši se neukazuje nikdy.
- Po dokončení tam zůstane lístek **„Připraveno k vložení ⌘V"** — zmizí klikem, po `⌘V`, nebo novým diktátem.

**Menu v liště (popover)**
- Statistiky (počet diktátů, slova, čas mluvení), průměrné tempo řeči, náklady za měsíc.
- Graf aktivity za 7 dní, **historie diktátů** (klik = zkopírovat).
- Přepínač modelu (Haiku / Sonnet), stav GPU.

**Nastavení a nápověda**
- Okno má dvě záložky: **Nastavení** a **Nápověda** (schémata: jak to funguje, kam text půjde, co znamenají stavy ikony, kudy tečou data).
- Klávesy, jazyk, autostart, chytrá mezera, slovník, API klíč (v Keychain), vzhled (Systém/Light/Dark).
- **Práh uvolnění modelu** v sekundách (0 = držet stále, jinak 10–600 s).
- **Diagnostika** — standardně vypnutá. Zapíná se klíčem `diagnostics` v `settings.json` nebo proměnnou `SPILLWAY_DIAG` (`all`, nebo výčet `focus,hud,audio,text`). Teprve pak se do logu píšou podrobnosti o fokusu, poloze okénka a mikrofonu. Pozor: oblast `text` zapisuje do logu **přepsaný text**, ne jen jeho délku.
- Reset statistik a historie.

---

## 1. Otevřený problém: text uvázne ve schránce

**Co se děje:** když během zpracování odejdeš z pole nebo přepneš aplikaci, Spillway text
**nevloží** (aby nespadl do cizího pole) — nechá ho ve schránce a u ikony ukáže lístek
„Připraveno k vložení". Musíš si ho vložit sám přes `⌘V`.

**Co by šlo zlepšit:** aby stačilo **kliknout na lístek** a Spillway text doručil sám tam,
kam jsi původně diktoval.

### Jak by to fungovalo (krok za krokem)
1. Při diktování si Spillway zapamatuje **aplikaci a okno** + krátký „otisk" pole
   (typ prvku a jeho pozice). *Nepamatuje si samotné pole* — odkaz na textové pole je křehký
   a u webu/Electronu ho překreslení stránky zneplatní.
2. Po dokončení visí lístek u ikony.
3. **Klikneš na lístek** → Spillway zkusí vytáhnout to původní okno dopředu, ověří otisk pole
   a vloží.
4. **Nebo se do pole vrátíš sám** → Spillway to pozná a vloží.
5. **Když cokoli nesedí** (jiné pole, zavřené okno, nejde ověřit) → nevkládá naslepo,
   nechá text ve schránce s hláškou „stiskni ⌘V".

### Kde je háček
- **Apple od macOS Sonoma omezil, aby aplikace vytahovaly jiné aplikace dopředu.** Takže
  krok 3 často **neprojde** a spadne to na `⌘V`. Hodnota featury tím klesá — reálně zbývá
  hlavně „vloží se to samo, když se vrátíš" (krok 4).
- **Webová pole** (Gmail, Slack v prohlížeči) se ověřit nedají → tam vždycky jen `⌘V`.
- **Dvě prázdná pole vedle sebe** se od sebe poznají jen podle pozice.

**Bez fronty.** Čeká vždy nanejvýš jeden text; nový diktát ten starý nahradí.

**Verdikt:** střední přínos, protože nejhezčí část (klik → doruč) macOS blokuje.
Levná varianta = jen krok 4 (vloží se, když se vrátíš do pole).

---

## 2. Rychlost a chování modelu

### 2.2 Automatické rozpoznání jazyka pro každý diktát

**Jak to je dnes:** jazyk je natvrdo nastavený (čeština). Když nadiktuješ něco anglicky,
Whisper to stejně zkusí psát česky.

**Proč to není jen „zapnout"**: Whisper hádá jazyk z prvních vteřin nahrávky. U nás je běžné,
že česká věta začne anglickým termínem („commitnul jsem to…") — a to ho může přepnout do
angličtiny a **rozsypat celý diktát**. Proto je dnes jazyk pevně daný.

**Tři možnosti**

| Varianta | Jak funguje | Riziko |
|---|---|---|
| **A. Plné rozpoznání** | Whisper si jazyk určí sám | ❌ Vysoké — česko-anglický mix překlopí do angličtiny |
| **B. S prahem jistoty** ⭐ | Základ je čeština; přepne jen když si je Whisper **hodně jistý**, že je to jiný jazyk | Nízké |
| **C. Krátký seznam** | Rozpoznává jen mezi 2–3 jazyky, které si nastavíš (např. CZ/EN) | Nejnižší |

**Dopad na rychlost:** rozpoznání jazyka potřebuje průchod „enkodérem", což je stejně
většina práce, kterou přepis dělá tak jako tak → přirážka je **malá (řádově desetiny
sekundy)**. U streamingu by se jazyk určil **jednou z prvního úseku** a dál se držel — jinak
by se mohl mezi větami přepínat a text by byl nesourodý.

**Dopad na přesnost:**
- Čistě anglický diktát: **výrazné zlepšení** (dnes se komolí do češtiny).
- Česko-anglický mix: **riziko zhoršení** u varianty A; u B/C prakticky beze změny.
- Krátké diktáty (1–2 s) jsou na rozpoznání nejhorší → tam raději zůstat u výchozího jazyka.

**Navazuje na to i AI úprava** — Claude by měl vědět, v jakém jazyce text je, aby ho
nepřeložil.

**Verdikt:** jít cestou **B** (nebo C). Plné automatické rozpoznání by hlavní scénář zhoršilo.

---

## 3. Ovládání hlasem

### 3.1 Hlasové editační příkazy

**Nápad:** říct „nový odstavec", „odrážka", „velké písmeno" a Spillway to promítne do
**formátování**, místo aby ta slova napsal.

**Dobrá zpráva:** máme na to už hotový mechanismus. Oprava přeřeknutí („teda v 5") funguje
úplně stejně — Claude rozliší, co je **obsah** a co je **pokyn**. Takže je to hlavně otázka
rozšíření zadání pro Claude, ne nová technika.

**Kde je háček — rozeznat pokyn od obsahu.** Když nadiktuješ větu *„napiš mu, ať smaže tu
větu o cenách"*, nesmí to Spillway pochopit jako povel a text smazat.

**Proto navrhuji dělit příkazy na dvě skupiny:**

| Skupina | Příklady | Riziko | Doporučení |
|---|---|---|---|
| **Formátovací** (jen přidávají) | „nový odstavec", „nový řádek", „odrážka", „číslovaný seznam" | Nízké — když se splete, jen jinak zalomí text | ✅ začít tady |
| **Ničivé** (mažou obsah) | „smazat větu", „smazat poslední slovo", „začni znovu" | Vysoké — chyba znamená **ztracený text** | ⚠️ až později, opatrně |

**Návrh postupu:** nejdřív jen formátovací příkazy, pevně daný seznam, sepsaný v nastavení,
ať víš, co Spillway poslouchá. Ničivé příkazy až potom — a jen v jasně rozeznatelné podobě.

**Náročnost:** malá (zadání pro Claude + testy). **Riziko:** nízké u formátovacích.

---

## 4. Uživatelské rozhraní

### 4.1 Průvodce oprávněními při prvním spuštění
Spillway potřebuje tři povolení (mikrofon, sledování klávesnice, zpřístupnění). Dnes si je
musíš najít sám a když jedno chybí, projeví se to jen tím, že „to nefunguje".

**Návrh:** při prvním spuštění okno, které u každého oprávnění ukáže **živě zelenou/červenou**,
tlačítkem otevře přesné místo v Nastavení systému, a na konci nabídne **zkušební diktát**
s potvrzením „funguje".

### 4.2 Úprava zadání pro AI (promptu) s resetem
**Návrh:** v nastavení textové pole s tím, co se posílá Claudovi, plus tlačítko
**„Vrátit na výchozí"**. Kdo chce, doladí si tón; kdo ne, nesahá na to.

**Pozor:** prompt je nejchoulostivější část celé aplikace — drží pravidla jako „nic si
nevymýšlej" nebo „angličtinu nepřekládej". Když si ho někdo přepíše, kvalita se může tiše
zhoršit.

**Proto navrhuji dvouúrovňově:**
- **Běžná úroveň:** jen pár přepínačů a **vlastní doplněk** („piš mi vždycky neformálně",
  „nepoužívej pomlčky") — připojí se k našemu promptu, nepřepíše ho.
- **Expertní úroveň:** celý prompt k přepsání, schované za varováním, s resetem na výchozí.

### 4.3 Úprava profilů aplikací
Dnes je pevně dané, že Mail = formální e-mail, Slack = neformální chat, editor = kód atd.
**Návrh:** v nastavení tabulka „aplikace → profil", kde si to přepíšeš (třeba že Slack u tebe
má být formální), a možnost přidat vlastní aplikaci nebo webovou doménu.

### 4.4 Drobnosti
- **Zabalit font Raleway** do aplikace (dnes padá na systémový, když ho nemáš).
- **Doladit okénko u kurzoru** na více monitorech.
- **Notarizace u Apple** (Developer ID, ~$99/rok) — odstraní varování „nelze ověřit vývojáře"
  při prvním spuštění. Nutné, jestli to má používat někdo další.
- **Světlý motiv** okna a nápovědy zatím nikdo neprošel okem — tmavý ano.

---

## 5. Data a další platformy

### 5.1 Export historie a statistik
Historie se od začátku ukládá strojově čitelně (`history.jsonl`), takže jde poslat jinam —
na Raspberry Pi nebo do databáze — a dělat nad tím přehledy: kolik toho denně nadiktuji,
kde nejvíc, jaké termíny se opakují, jestli se přepis v čase zlepšuje.

### 5.2 Windows
Jádro (přepis, AI úprava, statistiky) je přenositelné — asi **třetina kódu**. Přepsat by se
musela „platformní vrstva": odchytávání klávesy, vkládání textu, zjištění aktivní aplikace a UI.
Princip držet stejný: **schránka + zkratka**, čtení kontextu jen pro informaci.

### 5.3 iPhone
Tady je to jinak — iOS **nedovolí** aplikaci běžet na pozadí a vkládat text do cizích aplikací.
Existuje ale jedna dobrá cesta:

| Cesta | Jak by to fungovalo | Reálnost |
|---|---|---|
| **Vlastní klávesnice** ⭐ | Spillway se přidá jako klávesnice; kdekoliv píšeš, přepneš na ni, podržíš mikrofon, mluvíš → text se **vloží rovnou do pole** | Funkční cesta. Jediná, která umí psát do cizích aplikací. |
| Samostatná aplikace | Nadiktuješ → text do schránky → ručně vložíš | Jednoduché, ale nepohodlné |
| Sdílení (share sheet) | Diktuješ nad označeným textem | Okrajové použití |

**Zásadní omezení klávesnice:** klávesnicové rozšíření na iOS má **velmi přísný limit paměti
(desítky MB)**. Náš model (~1,6 GB) se tam **nevejde**. Možnosti:
1. **Malý model přímo v telefonu** (horší přesnost, hlavně u češtiny),
2. **poslat zvuk k sobě na Mac / server** (potřebuje síť a řeší se soukromí),
3. **použít diktování od Applu** a nechat si od Spillway dělat jen tu **AI úpravu** — to je
   nejrealističtější: Apple přepíše, Claude vyčistí a naformátuje podle aplikace.

Varianta 3 je zajímavá i proto, že hodnota Spillway není jen v přepisu, ale právě v té úpravě.

### 5.4 Android
Android je vstřícnější: aplikace může být **plnohodnotná klávesnice**, smí běžet na pozadí
a nemá tak tvrdé limity paměti. Šel by tam i model přímo v telefonu (na slabších přístrojích
menší varianta), nebo stejné rozdělení jako u iPhonu (systémový přepis + naše úprava).

### 5.5 Sdílení nastavení mezi zařízeními
Kdyby vznikla mobilní verze, dávalo by smysl sdílet aspoň **slovník výrazů** a nastavení stylu,
aby se termíny psaly všude stejně.

---

## 6. Poznámky z provozu (ať se to neopakuje)

- **Ikony si macOS cachuje podle cesty A NÁZVU souboru.** Po překreslení ikony nestačí
  přeinstalovat ani vyčistit systémové cache — nejjistější je změnit název `.icns`.
  Vlastní cache mají navíc nástroje třetích stran, které ikony zobrazují
  (alternativní taskbary, launchery); ty je potřeba restartovat zvlášť.
- **Accessibility nejde osahat zvenku.** Z odděleného procesu vrací `-25204`, takže
  chování fokusu se dá ověřit jen v běžící aplikaci — na to je diagnostický režim.
- **Podle role prvku se pole nepozná.** Plocha Finderu, rám okna i webový editor se
  hlásí stejně (`AXGroup`/`AXScrollArea`). Chromium navíc hlásí `AXSelectedTextRange`
  i pro stránku bez zaměřeného pole a jako kurzor vrací začátek dokumentu.
  Rozhoduje **editovatelnost** (`AXValue` je settable).
- **Stejné rozhodnutí na více místech se dřív nebo později rozejde.** Poloha okénka
  a volba vložit/schránka se počítaly zvlášť — a okénko pak viselo jinde, než kam
  text šel. Odvozovat vše z jednoho snímku.

---

## 7. ⛔ ODMÍTNUTO / NEAKTUÁLNÍ — už nenavrhovat

**Tohle se nesmí vracet do návrhů.** Každý řádek je uzavřené rozhodnutí; když se objeví znovu, musí k tomu být nový důvod (nová data, změněné zadání), ne opakování.

| Nápad | Stav | Proč |
|---|---|---|
| **Prompt caching** | ⛔ odmítnuto 29. 7. | **Změřeno na reálném provozu:** stabilní část 1 560 tok., trefa 49 % (5 min) / 76 % (1 h) → úspora jen **$0,32–0,45/měsíc** (z $1,95). Nestojí to za změnu tvaru API volání. |
| **Adaptivní uvolňování modelu z paměti** | ⛔ odmítnuto 30. 7. | **Změřeno:** rozestupy mezi diktáty jsou dvouvrcholové — 32 % do 1 min, 35 % nad 10 min, střed (1–10 min) jen ~34 %. Pevný práh tedy sebere skoro celý přínos a adaptivní logika by přidala nejvýš ~10 p. b. za cenu stavové logiky a stropu proti zaseknutí. Navíc padl původní argument „topí to" — teplo způsobovala opravená chyba dvojího načítání; 7 načtení denně = ~11 s GPU práce, bez měřitelného vlivu na baterku. Rozhodnutí: práh zůstává na **1 minutě**. |
| **Fronta diktátů** (stisk klávesy během zpracování) | ⛔ odmítnuto | Je správné počkat, než předchozí doběhne. Fronta by jen zvýšila riziko, že text spadne do špatného pole. |
| **Automatický výběr modelu** (Haiku na krátké, Sonnet na dlouhé) | ⛔ odmítnuto | Ztratila by se kontrola nad tím, co text upravuje. Sonnet je dost rychlý. |
| **Průběžné zobrazování odpovědi Claude** | ⛔ odmítnuto | K ničemu — text se stejně vkládá až celý. |
| **Vrácení posledního vložení (undo)** | ⛔ odmítnuto | Ve většině aplikací funguje běžné `⌘Z`. |
| **Náhled a potvrzení před vložením** | ⛔ odmítnuto | Další okno navíc, které zdržuje; smysl diktování je, že text prostě naskočí. |
| **„Kopírovat místo vložit" zvláštní zkratkou** | 🕓 nahrazeno | Nahrazeno diktováním bez zaklikaného pole — hotovo. |
| **Vždy přepsat schránku posledním diktátem** (nevracet původní obsah) | ⛔ odmítnuto 4. 8. | **Změřeno na 154 diktátech:** 91 % se normálně vloží, jen 6 % skončí ve schránce — a ty už fallback řeší sám. Přeplácnutí by tedy poškodilo schránku v 91 % případů kvůli riziku v 6 %, které je navíc pojištěné dvakrát (lístek „Připraveno k vložení" + Historie, do které se zapisuje **každý** diktát bez ohledu na výsledek). Navíc by rozbilo běžný postup „zkopíruj odkaz → nadiktuj komentář → vlož odkaz" a vynutilo výjimku pro RDP. Rozhodnutí: schránka se po vložení **vrací** jako dosud. |
| **„Přemluvit" (nahradit poslední vložení)** | ⛔ odmítnuto | Jednodušší je smazat a nadiktovat znovu. |
| **Tichý režim / pauza** | ⛔ odmítnuto | Řeší se sám — bez řeči se nic nepřepisuje (je tam filtr ticha). |
| **Slovník jako páry „špatně → správně"** | ⛔ odmítnuto | Ruční slovník stačí; automatické učení je slepá ulička (viz 8). |
| **Restart GPU vlákna při zaseknutí** | 🕓 neaktuální | Zaseknutí se po opravách neděje. Otevřít až kdyby nastalo. |

### ✅ Hotovo — už to není nápad, ale funkce
Streaming přepisu · oprava přeřeknutí („teda v 5") · prompt proti vymýšlení (věrohodnost nad cílem, mazání zkomolenin, chráněný slovník) · chytrý oddělovač (mezera vs. nový řádek) · HUD u ikony + lístek „Připraveno k vložení" · schránka při odchodu z pole · vkládání do RDP/AVD · statistiky, náklady, historie s kopírováním · **diktování bez zaklikaného pole** (není-li kam vložit, text jde do schránky s lístkem) · **animovaná ikona v liště** (živý ukazatel hlasitosti při nahrávání, běžící vlna při zpracování) · **nápověda v aplikaci** (schémata místo odstavců) · **nastavitelný práh uvolnění modelu** · **diagnostický režim** (vypnutý, zapíná se v nastavení) · potvrzení u všech nevratných akcí · sjednocené zjišťování fokusu (jedno místo pro polohu okénka i volbu vložit/schránka).

---

## 8. Proč nebude automatický slovník (analýza)

**Nápad byl:** ať se Spillway sám učí termíny, které špatně slyší, a přidává si je do slovníku.

**První pokus:** porovnávat, co napsal Whisper, s tím, co z toho udělal Claude, a rozdíly brát
jako kandidáty do slovníku.

**Proč to nefunguje:** takhle se zachytí jen to, co **Claude už sám opravuje** — takže přidat
to do slovníku je zbytečné, opravilo by se to i tak. Skutečně cenné jsou termíny, které
**minou oba** (vlastní název, jméno člověka, neznámá knihovna). Ty se v tom porovnání
**nikdy neobjeví**, protože je nikdo neopravil — jen se vložily špatně a **ty jsi je pak
přepsal rukou**.

**Ostatní zdroje a proč taky ne:**

| Zdroj | Co by zachytil | Proč to nejde |
|---|---|---|
| Tvoje ruční opravy vloženého textu | přesně ty správné termíny | Muselo by se po vložení sledovat, co v poli měníš — nespolehlivé (píšeš dál, text se mění z mnoha důvodů) a je to zásah do soukromí. |
| Claude přizná nejistotu | část neznámých jmen | Použitelné jako doplněk, ale zachytí jen zlomek. |
| Opakovaný diktát po sobě | „řekl jsem to blbě" | Neřekne správný tvar → k slovníku nepoužitelné. |

**Závěr:** slovník **zůstane ruční**. Je to pár termínů, které si zadáš jednou, a funguje to
spolehlivě. Automatika by buď nepřinesla nic navíc, nebo by musela slídit v tom, co píšeš.
