# Spillway

Diktovací nástroj pro macOS — hold-to-talk → lokální přepis (mlx-whisper na Apple GPU) → úprava (Claude) → vložení do libovolné aplikace. Menu-bar app (`rumps`/PyObjC).

## Sjednocené standardy napříč projekty

Než začneš psát kód, přečti si v Obsidian vaultu OBOJÍ (ne jen první soubor):
- `/Users/ondrej/Documents/VaultHub/3. Areas/Programování/Standardy/Principy.md`
- `/Users/ondrej/Documents/VaultHub/3. Areas/Programování/Standardy/Bezpečnost.md`

Principy.md odkazuje dál na soubor pro tenhle konkrétní stack (macOS nativní
aplikace) a na UI komponenty — přečti si i ten, než děláš cokoli s UI
v nastavovacím okně (WKWebView). Bezpečnost.md čti vždycky celé, ne jen
proletět — platí bez výjimky.

Dokumentace projektu je v `_doc/` a je to živý obsah, ne jednorázově napsaný
při založení — aktualizuj příslušný soubor rovnou, když se mění zadání, plán
nebo přibude významné provozní poučení, ne "až bude čas".

Pravidla specifická pro tenhle projekt jsou níž — když jsou v konfliktu
s vault standardy, vyhrává tenhle soubor (je konkrétnější), ale konflikt
over, jestli není chyba tady, ne tam.

## Dokumentace

| Soubor | Co obsahuje | Role |
|---|---|---|
| [_doc/spillway-analyza.md](_doc/spillway-analyza.md) | co appka je, motivace, pipeline, náklady, známá omezení | business/produktová analýza |
| [_doc/spillway-plan-implementace.md](_doc/spillway-plan-implementace.md) | aktuální architektura a otevřená rozhodnutí | technický plán |
| [_doc/spillway-rozvoj-a-napady.md](_doc/spillway-rozvoj-a-napady.md) | roadmapa, nápady, monetizace | plán rozvoje |
| [_doc/spillway-log.md](_doc/spillway-log.md) | hotové věci, zamítnuté nápady, poznámky z provozu | log vývoje |
