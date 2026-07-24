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

- **Streaming přepis během mluvení** — přepisovat po segmentech, už zatímco mluvíš (VAD je v pipeline). Po puštění klávesy zbývá poslední kousek → vnímaná latence Whisperu skoro zmizí. Velký přínos, ale koliduje s modelem „Escape zruší celý diktát před zaplacením" → vyšší riziko.
- **Auto-výběr modelu** — Haiku pro krátké/jednoduché (nižší latence), Sonnet pro delší/složité; přepínat podle délky.
- **Prompt caching** systémového promptu — ~100–300 ms na opakovaných voláních v krátkém sledu.
- Streamovaná odpověď Claude **nepomůže** — text se vkládá až celý.

---

## 4. Kvalita a chování

- **Adaptivní unload** — místo fixní 1 min držet model, dokud „aktivně diktuješ" (hodně diktátů v poslední době → delší práh), a uvolnit až po delší pauze. Míň churnu při souvislé práci.
- **Auto-detekce jazyka per diktát** s prahem jistoty — default primární jazyk, přepnout jen když je detekovaný jazyk jiný A jistota vysoká (plná auto-detekce by česko-anglický mix zhoršila).
- **Undo posledního vložení.**
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
