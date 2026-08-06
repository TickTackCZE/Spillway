"""Na které obrazovce okno je.

Plovoucí okna (okénko u kurzoru, kartička s upozorněním) se musí vejít na tu
obrazovku, kde se právě ukazují — ne na primární. Obě se dřív ptaly
`NSScreen.screens()[0]`, takže na sestavě s víc monitory ořezávaly polohu podle
špatného displeje: okénko u kurzoru na pravém monitoru se srazilo na šířku
primárního a kartička se mohla přehodit na druhou stranu, i když tam místo bylo.

Je to jedna funkce ve vlastním modulu schválně — kdyby žila v jednom z těch
dvou panelů, druhý by si ji dřív nebo později zkopíroval. Přesně na tom už
tenhle projekt několikrát sedl.
"""

from __future__ import annotations

from AppKit import NSScreen


def visible_frame_at(x: float, y: float):  # noqa: ANN201
    """Použitelná plocha obrazovky, na které leží bod (x, y) — bez lišty a Docku.

    Když bod neleží na žádné (okno je mimo viditelnou plochu, monitor se právě
    odpojil), vrátí hlavní obrazovku. `None` jen tehdy, když nejsou žádné.
    """
    screens = NSScreen.screens()
    if not screens:
        return None
    for scr in screens:
        f = scr.frame()
        if (float(f.origin.x) <= x < float(f.origin.x) + float(f.size.width)
                and float(f.origin.y) <= y < float(f.origin.y) + float(f.size.height)):
            return scr.visibleFrame()
    main = NSScreen.mainScreen() or screens[0]
    return main.visibleFrame()


def primary_height() -> float:
    """Výška PRIMÁRNÍ obrazovky — převodní konstanta mezi souřadnicemi.

    Accessibility měří odshora a od primární obrazovky, Cocoa odspoda. Tenhle
    údaj se proto bere vždy z primární, i když okno leží na jiné; zaměnit ho za
    výšku aktuální obrazovky je snadná chyba s ošklivým projevem (okénko skočí
    na jiný monitor).
    """
    screens = NSScreen.screens()
    return float(screens[0].frame().size.height) if screens else 0.0
