# Spillway — log rozhodnutí

> Archiv. **Co je tady, se nevrací do návrhů.** Hotové funkce, uzavřená rozhodnutí
> a poučení z provozu. Aktivní věci žijí v [rozvoj a nápady](spillway-rozvoj-a-napady.md).
> Aktualizováno: 6. 8. 2026

---

## ✅ Hotovo — už to není nápad, ale funkce

**Diktování a přepis**
- Streaming přepisu (segmentuje se v tichu, přepisuje už během mluvení)
- Zrušení diktátu klávesou před placeným voláním AI
- Uvolnění modelu z paměti po nastavitelné nečinnosti (10–600 s)

**Kvalita textu**
- Prompt proti vymýšlení — věrohodnost nadřazená všemu, zkomoleniny se mažou místo hádání, termíny ze slovníku chráněné
- Oprava přeřeknutí („ve 4 nebo teda v 5" → „v 5")
- Chytrý oddělovač — nic / mezera / nový řádek podle kontextu pole
- Profily podle cílové aplikace, uživatelský slovník

**Vkládání**
- Vkládání do RDP/AVD naťukáním znaků
- Schránka + lístek při odchodu z pole nebo z aplikace
- Diktování bez zaklikaného pole — není-li kam vložit, text jde do schránky, nevkládá se naslepo
- Sjednocené zjišťování fokusu — jedno místo pro polohu okénka i volbu vložit/schránka

**Rozhraní**
- Animovaná ikona v liště (živý ukazatel hlasitosti, běžící vlna při zpracování)
- Okénko jen ve dvou polohách: u kurzoru, nebo pod ikonou se šipkou
- Nápověda přímo v aplikaci (schémata místo odstavců)
- Statistiky, náklady, historie s kopírováním
- Potvrzení u všech nevratných akcí
- Diagnostický režim, standardně vypnutý

---

## ⛔ Odmítnuto / neaktuální

**Každý řádek je uzavřené rozhodnutí.** Když se má vrátit, musí k tomu být nový důvod —
nová data nebo změněné zadání, ne opakování téhož nápadu.

| Nápad | Stav | Proč |
|---|---|---|
| **Hlasové editační a formátovací příkazy** | ⛔ 5. 8. | **Měřeno na 152 diktátech (9 112 slov):** editační fráze („přepiš", „odstraň") se 4× objevily jako běžný OBSAH — např. „jenom přepiš tu dvojku prosím". Rozpoznávání by ukusovalo kusy zadání a otevřelo čtvrtá vrátka v pravidle NEZTRÁCEJ OBSAH, které stálo nejvíc práce. Formátovací příkazy jsou měřením bezpečné (1 výskyt), ale nemají use case. |
| **Vždy přepsat schránku posledním diktátem** | ⛔ 4. 8. | **Změřeno na 154 diktátech:** 91 % se normálně vloží, jen 6 % skončí ve schránce — a ty už fallback řeší sám. Přeplácnutí by poškodilo schránku v 91 % případů kvůli riziku v 6 %, které je pojištěné dvakrát (lístek + Historie, kam se zapisuje **každý** diktát). Navíc by rozbilo postup „zkopíruj odkaz → nadiktuj komentář → vlož odkaz". |
| **Adaptivní uvolňování modelu z paměti** | ⛔ 30. 7. | **Změřeno:** rozestupy mezi diktáty jsou dvouvrcholové — 32 % do 1 min, 35 % nad 10 min, střed jen ~34 %. Pevný práh sebere skoro celý přínos. Padl i argument „topí to" — teplo způsobovala opravená chyba dvojího načítání; 7 načtení denně ≈ 11 s GPU práce. **Nahrazeno nastavitelným prahem v UI.** |
| **Prompt caching** | ⛔ 29. 7. | **Změřeno:** stabilní část 1 560 tok., trefa 49 % (5 min) / 76 % (1 h) → úspora jen $0,32–0,45/měsíc. Nestojí to za změnu tvaru API volání. |
| **Fronta diktátů** (stisk během zpracování) | ⛔ | Je správné počkat. Fronta by zvýšila riziko, že text spadne do špatného pole. |
| **Automatický výběr modelu** | ⛔ | Ztratila by se kontrola nad tím, co text upravuje. Sonnet je dost rychlý. |
| **Průběžné zobrazování odpovědi Claude** | ⛔ | K ničemu — text se stejně vkládá až celý. |
| **Vrácení posledního vložení (undo)** | ⛔ | Ve většině aplikací funguje běžné `⌘Z`. |
| **Náhled a potvrzení před vložením** | ⛔ | Okno navíc, které zdržuje; smysl diktování je, že text prostě naskočí. |
| **„Přemluvit" (nahradit poslední vložení)** | ⛔ | Jednodušší je smazat a nadiktovat znovu. |
| **Tichý režim / pauza** | ⛔ | Řeší se sám — bez řeči se nic nepřepisuje. |
| **Slovník jako páry „špatně → správně"** | ⛔ | Ruční slovník stačí; automatické učení je slepá ulička (viz níž). |
| **„Kopírovat místo vložit" zvláštní zkratkou** | 🕓 nahrazeno | Nahrazeno diktováním bez zaklikaného pole. |
| **Restart GPU vlákna při zaseknutí** | 🕓 neaktuální | Po opravách se to neděje. Otevřít, až kdyby nastalo. |

---

## Poznámky z provozu (ať se to neopakuje)

- **Ikony si macOS cachuje podle cesty A NÁZVU souboru.** Po překreslení ikony nestačí
  přeinstalovat ani vyčistit systémové cache — nejjistější je změnit název `.icns`.
  Vlastní cache mají navíc nástroje třetích stran, které ikony zobrazují (alternativní
  taskbary, launchery); ty je potřeba restartovat zvlášť.
- **Accessibility nejde osahat zvenku.** Z odděleného procesu vrací `-25204`, takže
  chování fokusu se dá ověřit jen v běžící aplikaci — na to je diagnostický režim.
- **Podle role prvku se pole nepozná.** Plocha Finderu, rám okna i webový editor se hlásí
  stejně (`AXGroup`/`AXScrollArea`). Chromium navíc hlásí `AXSelectedTextRange` i pro
  stránku bez zaměřeného pole a jako kurzor vrací začátek dokumentu. Rozhoduje
  **editovatelnost** (`AXValue` je settable).
- **Stejné rozhodnutí na více místech se dřív nebo později rozejde.** Poloha okénka
  a volba vložit/schránka se počítaly zvlášť — a okénko pak viselo jinde, než kam text
  šel. Odvozovat vše z jednoho snímku.
- **Příznak plněný na jiném vlákně se čte zastaralý.** „Chybí model" se zjišťovalo na
  vlákně, které předtím čeká na Accessibility (strop 1 s). Krátké ťuknutí do klávesy ho
  předběhlo → jednou zahozený platný diktát, podruhé „Chyba při vkládání" místo nabídky
  ke stažení. Levný dotaz (`os.path.exists`) je lepší se prostě zeptat znovu.
- **Hlavní vlákno nesmí sáhnout na Klíčenku.** `SecItemCopyMatching` čeká libovolně
  dlouho — po přeinstalování `.app` ukáže macOS dialog. Četlo se to v `Controller.__init__`,
  tedy dřív, než vznikne ikona v liště: aplikace pak neměla ŽÁDNÉ UI a vypadala, že se
  nespustila. Totéž platí pro časovač lišty.
- **„Bezpečná" pojistka umí být ta nejdražší operace.** Zrušení stahování mazalo celou
  složku i kopii v cache HuggingFace, takže každé Zrušit stálo při dalším pokusu znovu
  1,6 GB — a komentář nad tím tvrdil pravý opak.
- **Test, který grepuje zdroják, přežije i rozbitou funkci.** Uvítání po instalaci mělo
  zelený test na existenci HTML, zatímco příznak, který ho zobrazuje, byl vždy `False`.
  Testovat chování, ne přítomnost řetězce.

---

## Proč nebude automatický slovník

**Nápad byl:** ať se Spillway sám učí termíny, které špatně slyší, a přidává si je do slovníku.

**První pokus:** porovnávat, co napsal Whisper, s tím, co z toho udělal Claude, a rozdíly
brát jako kandidáty do slovníku.

**Proč to nefunguje:** takhle se zachytí jen to, co **Claude už sám opravuje** — přidat to
do slovníku je zbytečné, opravilo by se to i tak. Skutečně cenné jsou termíny, které
**minou oba** (vlastní název, jméno člověka, neznámá knihovna). Ty se v porovnání
**nikdy neobjeví**, protože je nikdo neopravil — jen se vložily špatně a přepsal jsi je rukou.

| Zdroj | Co by zachytil | Proč to nejde |
|---|---|---|
| Ruční opravy vloženého textu | přesně ty správné termíny | Muselo by se sledovat, co v poli měníš — nespolehlivé a je to zásah do soukromí. |
| Claude přizná nejistotu | část neznámých jmen | Použitelné jako doplněk, zachytí jen zlomek. |
| Opakovaný diktát po sobě | „řekl jsem to blbě" | Neřekne správný tvar → k slovníku nepoužitelné. |

**Závěr:** slovník **zůstane ruční**. Je to pár termínů, které zadáš jednou. Automatika by
buď nepřinesla nic navíc, nebo by musela slídit v tom, co píšeš.
