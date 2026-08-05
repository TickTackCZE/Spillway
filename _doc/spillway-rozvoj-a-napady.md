# Spillway — rozvoj a nápady

> **Jen aktivní věci a další kroky.** Hotové funkce, odmítnuté nápady a poučení z provozu
> jsou v [logu rozhodnutí](spillway-log.md) — do návrhů se nevracejí.
> Co aplikace **dnes umí**, je v [plánu implementace](spillway-plan-implementace.md)
> a v [README](../README.md) — tady se to nezdvojuje.
> Stav aplikace: **v1.2** · Aktualizováno: 5. 8. 2026

**Rozhodnuto:** aplikace se bude prodávat jako **roční licence (~1 000 Kč) s vlastním API
klíčem uživatele**. Nulový variabilní náklad, žádný server v cestě diktátu.

Dokument má tři oblasti:

| Oblast | O čem je | Kdy |
|---|---|---|
| **[1. Prodej](#1-prodej)** | co postavit, aby to šlo prodat cizímu člověku | teď |
| **[2. Nové funkcionality](#2-nové-funkcionality)** | co přidat, aby si to koupilo víc lidí | po prvním prodeji |
| **[3. Monetizace](#3-monetizace)** | obchodní kroky, ne kód | souběžně s 1 |

---

## 1. Prodej

Technická práce, bez které se aplikace nedá dát cizímu člověku. **Žádná z položek není
funkce** — je to infrastruktura kolem produktu, které je dnes nula.

Pořadí je záměrné: bez prvních tří se nedá prodat vůbec.

| # | Krok | Proč | Odhad |
|---|---|---|---|
| 1.1 | **Notarizace u Apple** ($99/rok) | Dnes je podpis self-signed a Gatekeeper hlásí „nelze ověřit vývojáře". Cizí člověk aplikaci nenainstaluje. | 1 den |
| 1.2 | **Ověřování licence** | Podepsaný klíč (Ed25519), ověření **offline**, tolerance výpadku sítě. Detail v [3.2](#32-licencování-a-uzavření-kódu). | 3–5 dní |
| 1.3 | **Automatické aktualizace** (Sparkle) | Bez nich zůstanou zákazníci navždy na rozbité verzi. Potřebuje notarizované buildy. | 2–3 dny |
| 1.4 | **Export diagnostiky** | Tlačítko, které složí do ZIPu log, nastavení (bez klíče) a údaje o systému. Rozdíl mezi „pošlete mi log" a „klikněte sem". Bez toho je podpora neúnosná. | ½ dne |
| 1.5 | **Průvodce oprávněními** | Tři povolení (mikrofon, sledování klávesnice, zpřístupnění). Když jedno chybí, projeví se to jen tím, že „to nefunguje" → okamžitý refund. Návrh: živě zelená/červená u každého, tlačítko otevře přesné místo v Nastavení, na konci zkušební diktát. | 3–4 dny |
| 1.6 | **Průvodce zadáním API klíče** | U modelu s vlastním klíčem je to **první překážka**, kterou uživatel potká — musí si založit účet u Anthropic a nabít kredit. Provést ho tím krok za krokem. | 1–2 dny |
| 1.7 | **Anglické UI** | Celé rozhraní i nápověda jsou česky. Bez angličtiny je trh jen ČR + SK. | 3–5 dní |

**Dohromady ~3–4 týdny k první prodejné verzi.**

### Menší věci, které se hodí přibalit
- **Zabalit font Raleway** do aplikace (dnes padá na systémový, když ho uživatel nemá).
- **Projít světlý motiv** okna a nápovědy — kontrolovaný byl jen tmavý.
- **Doladit okénko u kurzoru** na více monitorech.
- **Otestovat na cizím Macu** — všechno je ověřené na jednom stroji, jedné verzi macOS
  a jedné sadě aplikací. Intel Macy, starší systém, jiné mikrofony, jiný jazyk systému.

---

## 2. Nové funkcionality

### 2.1 Režim schůzka — dlouhý lokální přepis bez AI

**Největší nová funkce v plánu.** Spustí se nahrávání schůzky, zvuk se přepíše **výhradně
na tomhle Macu**, do žádného cloudu ani modelu nic neodejde a text se nijak neupravuje —
uživatel dostane surový přepis a naloží si s ním sám.

**Proč to prodává:** Otter, Fireflies, Granola i Zoom posílají nahrávku na server. Spillway
přepisuje lokálně, takže v tomhle režimu neodejde ven **nic**. To je argument, který
konkurence technicky nemůže mít — a tam, kde se řeší mlčenlivost (právo, zdravotnictví,
HR, interní porady), to není detail.

**Provoz je zadarmo** — žádné volání API. Sedne to do modelu s vlastním klíčem přesně.

#### Dva scénáře, každý s jinou obtížností

**A) Mac leží na stole a poslouchá místnost.** Mikrofon zachytí všechny. **Žádné zachytávání
zvuku systému, žádné čtvrté oprávnění, žádný ovladač.** Technicky je to „dlouhé nahrávání
+ přepis po částech". **Tohle je ta snadná půlka a dělá se první.**

**B) Online hovor (Teams, Meet, Zoom).** Mikrofon slyší jen tebe, protistrana jde do
sluchátek — musí se zachytit zvuk systému. macOS **od 14.4** to umí bez instalace ovladače
(Core Audio process taps); na starším systému by uživatel musel doinstalovat virtuální
zvukové zařízení (BlackHole, Loopback), o což většina lidí zakopne. Nejspíš přibude
čtvrté oprávnění.

#### Co se musí vyřešit

| Věc | Dnes | Co je potřeba |
|---|---|---|
| **Paměť** | audio v RAM, strop 5 minut (19 MB) | Hodina schůzky = **230 MB**, tři hodiny 690 MB. Nutné streamovat na disk. |
| **Doba zpracování** | diktát pár sekund | Hodinový záznam přepisovat **po částech s průběžným výsledkem**, ne až na konci. |
| **Uložení** | audio se nikdy neukládá | Schůzka nutně vzniká jako soubor → nová rozvaha o soukromí, kde leží a kdo to maže. |
| **Výstup** | text do schránky | Delší text chce vlastní okno, časové značky, export. |
| **Právo** | — | Nahrávání hovoru vyžaduje souhlas účastníků. Aplikace na to musí upozornit. |

**Náročnost:** scénář A **2–3 týdny**, scénář B navrch ~1 týden.

### 2.2 Rozlišení mluvčích (diarizace) — hypotéza

Navazuje na 2.1. Odlišit v přepisu, kdo co řekl — „Mluvčí 1 / 2 / 3", pojmenovaní ručně.

**Lokálně to jde, ale ne přes standardní `pyannote`** — ten stojí na PyTorch a nafoukl by
aplikaci o stovky MB až jednotky GB (Spillway dnes PyTorch nepoužívá vůbec). Reálná cesta
jsou **ONNX modely** (segmentace + hlasové otisky), dohromady **desítky MB** a bez nové
těžké závislosti. Slib „všechno lokálně" tím zůstane.

**Jak to funguje:** zvuk se rozseká na úseky, ke každému se spočítá otisk hlasu, otisky se
shlukují a shluk = mluvčí. Whisper zvlášť dodá text s časy, obojí se spojí přes časovou osu.

**Kde to bude drhnout — čekat to předem:**
- **Jeden mikrofon uprostřed stolu je nejhorší možný vstup.** Vzdálenost, odrazy a různá
  hlasitost mluvčích přesnost citelně srážejí.
- **Překrývající se řeč** se rozdělit v podstatě nedá.
- **Podobné hlasy** splynou do jednoho mluvčího.
- **Chyba na hranici střídání** — poslední slova se připíšou předchozímu mluvčímu.
- Výsledek jsou **anonymní čísla, ne jména**.

**Jak to prodat, aby to nezklamalo:** jako **pomůcku pro orientaci** v přepisu („kdo asi
mluvil"), ne jako spolehlivý zápis. Uživatel si jména doplní a chyby opraví.

**Náročnost:** 1–2 týdny nad hotovým 2.1. **Až jako druhý krok.**

### 2.3 Export nahrávek a přepisu — navazuje na 2.1

Dnes nedává smysl (audio se neukládá, není co exportovat). S režimem schůzka nahrávka
nutně vznikne jako soubor → export zvuku i přepisu, ideálně s časovými značkami a s
rozlišením mluvčích, když bude 2.2 hotová.

### 2.4 Vlastní klíč k jinému poskytovateli (OpenAI, Gemini)

Uživatel si zadá klíč nejen k Anthropic a vybere, kdo má text upravovat. **Snižuje to
bariéru vstupu** — kdo už platí OpenAI, klíč má.

**Kód je malá práce.** Všichni tři mají stejný tvar volání (systémový pokyn + zpráva →
text). Stačí tenká vrstva nad HTTP a tabulka cen; **nové SDK přidávat netřeba**.

**Riziko je jinde: zadání je vyladěné NA Clauda.** Vzniklo měřením na reálné historii
a přepisovalo se kvůli vymýšlení. Jiný model má jiné sklony — typicky víc přeformulovává,
což je přesně to, čemu jsme se bránili. „Podporuje víc poskytovatelů" ≠ „funguje stejně dobře".

**Postup:** rozhraní + HTTP klient (~2 dny) → **profiltrovat historických 152 diktátů**
přes každý model a porovnat výstupy → doladit odchylky u těch, co projdou.
**Riziko: střední** — u neověřeného modelu hrozí návrat vymýšlení, tedy chyba, kterou
uživatel nemusí poznat.

### 2.5 Automatické rozpoznání jazyka

Dnes je jazyk pevně nastavený (čeština); anglický diktát se komolí do češtiny.

Whisper hádá jazyk z prvních vteřin. U nás je běžné, že česká věta začne anglickým
termínem („commitnul jsem to…") — plné rozpoznání by ji překlopilo do angličtiny
a **rozsypalo celý diktát**.

**Řešení: přepnout jen při vysoké jistotě**, jinak zůstat u výchozího jazyka. U streamingu
určit jazyk **jednou z prvního úseku** a dál ho držet. Krátké diktáty (1–2 s) nerozpoznávat
vůbec. Přirážka na rychlosti je malá (desetiny sekundy).

**Navazuje:** Claude by měl vědět, v jakém jazyce text je, aby ho nepřekládal.

### 2.6 Doručení textu z lístku

Když během zpracování odejdeš z pole, text čeká ve schránce s lístkem. **Návrh:** klik na
lístek text doručí sám tam, kam jsi diktoval.

**Háček:** Apple od Sonomy omezil, aby aplikace vytahovaly jiné aplikace dopředu — klik
často neprojde a spadne to na `⌘V`. Webová pole se ověřit nedají.

**Verdikt:** levná varianta je jen „vloží se to samo, když se do pole vrátíš". To zbytek
hodnoty pokrývá a nenaráží na omezení systému.

### 2.7 Úprava zadání pro AI (promptu)

Prompt je nejchoulostivější část aplikace — drží pravidla jako „nic si nevymýšlej".
Kdyby si ho někdo přepsal, kvalita se může tiše zhoršit.

**Proto dvouúrovňově:** běžná úroveň = pár přepínačů a **vlastní doplněk** („piš neformálně")
připojený k našemu promptu; expertní úroveň = celý prompt k přepsání, za varováním, s resetem.

### 2.8 Úprava profilů aplikací

Dnes je pevně dané, že Mail = formální e-mail, Slack = neformální chat. **Návrh:** tabulka
„aplikace → profil" k přepsání, plus možnost přidat vlastní aplikaci nebo doménu.

### 2.9 Export historie a statistik

`history.jsonl` je strojově čitelný, takže data jdou poslat jinam a dělat nad nimi přehledy:
kolik toho denně nadiktuji, kde nejvíc, jaké termíny se opakují.

---

## 3. Monetizace

Obchodní kroky. Kód je v [oblasti 1](#1-prodej).

### 3.1 Kolik to reálně stojí (změřeno)

Za 19 dní provozu: **185 diktátů (9,8 denně), náklad $0,77** → **$1,22/měsíc ≈ 29 Kč**.
Podstatné: **44 % diktátů se AI vůbec neposílá** (krátké se upraví lokálně) a přepis na
GPU nestojí nic.

**Proto vlastní klíč uživatele:** náklad roste se spotřebou, ale příjem z licence je fixní.
Kdyby se platily tokeny za uživatele, aktivní zákazník by byl ztrátový — a právě ten má
nejsilnější důvod platit.

| Uživatel | Náklad na API | Marže při 50 Kč/měs, kdyby se platily tokeny |
|---|---|---|
| jako dnes (10 diktátů/den) | 29 Kč | +21 Kč |
| 3× aktivnější | 86 Kč | **−36 Kč** |
| profesionál (100/den) | 288 Kč | **−238 Kč** |

**Cena pro zákazníka:** ~1 000 Kč licence + ~350 Kč ročně za tokeny = **~1 350 Kč/rok**.
Konkurence (Wispr Flow, superwhisper, Aqua Voice) bere **3 000–4 300 Kč/rok**.

### 3.2 Licencování a uzavření kódu

**Ověřování — offline, s podpisem.** Licenční klíč je podepsaný údaj (Ed25519): komu patří,
do kdy platí, kolik zařízení. Aplikace nese jen **veřejný** klíč a ověří podpis **bez
internetu**; privátní klíč zůstává u autora.
- Musí fungovat ve vlaku i bez sítě — je to nástroj na každodenní psaní.
- Občasná kontrola u serveru jen kvůli odvolání ukradených klíčů. **Selhání sítě nikdy
  nesmí zablokovat práci** (tolerance např. 30 dní).
- **Server na začátku není potřeba vůbec** — Lemon Squeezy / Gumroad generují i ověřují
  klíče samy a jsou *merchant of record* (vyřeší DPH). Vlastní server až při větších počtech.

**Uzavření kódu — realisticky.** Dnešní bundle obsahuje Python bytecode, který jde poměrně
snadno převést zpátky na čitelný kód; kdo chce, najde i ověřování licence a obejde ho.
- **Nuitka** (překlad do C) je nejúčinnější dostupná cesta. Riziko: kombinace s PyObjC
  a mlx není samozřejmá — **ověřit malým pokusem dřív, než se na to spolehne**.
- **Obfuskace kupuje čas, ne bezpečí.** U nástroje za tisícovku ročně, mířeného na lidi,
  kteří řeší práci a ne crackování, je rozumné počítat s únikem a soustředit se na to,
  aby **zaplatit bylo snazší než hledat crack**.
- **Repozitář musí přestat být veřejný** dřív, než se začne prodávat.

### 3.3 Kroky

| # | Krok | Poznámka |
|---|---|---|
| 3.a | **Zavřít repozitář** | Dnes je veřejný celý kód včetně promptu. Udělat jako první. |
| 3.b | **Zvolit prodejnu** | Lemon Squeezy nebo Gumroad — licenční klíče i DPH out of the box. Poplatek 5–10 %. |
| 3.c | **Ověřit Nuitku pokusem** | Malý test s PyObjC a mlx, než se na kompilaci spolehne. |
| 3.d | **Právní subjekt a fakturace** | Živnost nebo s.r.o., účetnictví, DPH. |
| 3.e | **Obchodní podmínky a zásady soukromí** | Musí uvést **Anthropic jako zpracovatele**. Že zvuk neopouští stroj je nejsilnější argument — formulovat přesně, ne jako „vaše data jsou v bezpečí". |
| 3.f | **Stanovit cenu a délku licence** | Výchozí návrh 1 000 Kč / rok. |
| 3.g | **Web a ukázka** | Krátké video s reálným diktátem řekne víc než popis. |
| 3.h | **Spustit prodej** | Ověřit zájem **dřív**, než se postaví režim schůzka. |

### 3.4 Co se snadno přehlédne

- **Pasivní příjem není pasivní.** macOS každý rok něco rozbije (oprávnění, Accessibility),
  API mění modely a ceny, zákazníci píšou. Model s vlastním klíčem je tomu nejblíž —
  žádný server, žádné měření spotřeby.
- **Bariéra vlastního klíče je reálná.** Uživatel si musí založit účet a nabít kredit.
  Zmírňuje ji [2.4](#24-vlastní-klíč-k-jinému-poskytovateli-openai-gemini) a průvodce [1.6](#1-prodej).
- **Kdyby někdy vznikla varianta „s naším klíčem", limit nesmí být na počet diktátů.**
  Změřeno na 126 diktátech: medián řeči **5,7 s**, nejdelší **140 s** — 25× rozdíl.
  Desetina nejdelších spotřebuje **polovinu všech minut**. Férová metrika jsou **minuty
  řeči** (korelace s cenou **0,93**) a aplikace je už dnes měří (`speech_s`).
- **Windows by rozšířil trh řádově, ale je to největší položka ze všech** — platformní
  vrstva k přepsání beze zbytku a `mlx-whisper` běží jen na Apple GPU, takže hlavní
  přednost („přepis hotový dřív, než pustíš klávesu") tam odpadá. 2–3 měsíce a trvale
  dvojnásobná údržba. Až když se macOS verze prodává natolik, že to zaplatí.
- **Mobil:** iOS nedovolí vkládat text do cizích aplikací jinak než přes vlastní klávesnici,
  a ta má limit paměti v desítkách MB — náš model se tam nevejde. Nejreálnější varianta je
  nechat přepis na Applu a dělat jen **AI úpravu**. Android je vstřícnější (plnohodnotná
  klávesnice, model by se tam vešel).
