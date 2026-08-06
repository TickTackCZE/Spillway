"""Geometrie plovoucích oken PROTI SKUTEČNÉMU WebKitu.

Zbytek testů běží bez AppKitu, a to je správně — jsou rychlé. Tenhle soubor je
výjimka, protože jedna třída chyb se jinak chytit nedá: okno se nastavuje podle
toho, co naměří DOM, a měření na **ještě nenačtené stránce** vrátí nesmysl.
Přesně to se v projektu už třikrát stalo (naposledy u `_fit_to_card`
a `_fit_to_content`) a všechny testy u toho zůstaly zelené, protože jen hledaly
řetězce ve zdrojáku.

Run loop se pumpuje ručně (`runUntilDate_`), ne přes `AppHelper` — ten by
v pytestu zůstal viset, kdyby podmínka nikdy nenastala.
"""

from __future__ import annotations

import pytest

pytest.importorskip("WebKit")
pytest.importorskip("AppKit")


def _pump(until, timeout: float = 8.0) -> bool:
    """Nechá běžet smyčku, dokud `until()` neplatí (nebo nevyprší čas)."""
    import time

    from AppKit import NSDate, NSRunLoop

    loop = NSRunLoop.currentRunLoop()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if until():
            return True
        loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
    return until()


@pytest.fixture(scope="module")
def _app():
    from AppKit import NSApplication

    return NSApplication.sharedApplication()


def test_hud_window_shrinks_to_the_card_it_shows(_app):
    from spillway.hud import StatusHUD

    # Okno se musí srovnat s kartou, ne zůstat na výchozí velikosti. Průhledný
    # okraj kolem karty totiž POLYKÁ kliknutí (okno si je vezme, i když je
    # klikací vrstva menší), a okénko visí přesně pod lištou — vznikla tam
    # mrtvá zóna přes 300 px a druhý klik z dvojkliku na ikonu do ní padal.
    hud = StatusHUD()
    hud.show("nomodel")

    ok = _pump(lambda: hud.panel.frame().size.width < StatusHUD.W - 1)
    w = float(hud.panel.frame().size.width)
    assert ok, f"okno zůstalo na výchozí šířce {w:.0f} px — měření DOM neproběhlo"

    # Karta „Chybí model pro přepis" je změřeně ~221 px; okno = karta + 2×PAD.
    assert 200 < w < 260, f"okno {w:.0f} px neodpovídá kartě"
    assert abs(float(hud._click.frame().size.width) - w) < 1.0, (
        "klikací vrstva má krýt celé (zmenšené) okno"
    )

    # Změna stavu velikost přepočítá — jinak by se delší text uřízl.
    hud.show("ready")
    assert _pump(lambda: float(hud.panel.frame().size.width) > w + 10), (
        "delší stav Připraveno k vložení musí okno roztáhnout"
    )
    hud.hide()


def test_notice_window_fits_its_content_on_the_very_first_show(_app):
    from spillway.notice import _PAD, NoticePanel

    # REGRESE: tray kartičku vytvoří a v TÉMŽE tiku ukáže, takže se stránka
    # ještě načítá. Přímé `evaluateJavaScript` tam spadlo na `null` a okno
    # zůstalo na výchozích 300 px — pod kartičkou pak visel průhledný pruh,
    # který polykal kliknutí.
    class Rect:
        def __init__(self, x, y, w, h):
            self.origin = type("P", (), {"x": x, "y": y})()
            self.size = type("S", (), {"width": w, "height": h})()

    panel = NoticePanel()
    panel.show_beside(object(), Rect(1200, 400, 320, 560),
                      {"ready": False, "key_ok": True,
                       "downloading": False, "percent": 0})

    ok = _pump(lambda: float(panel.panel.frame().size.height) < NoticePanel.H - 1)
    h = float(panel.panel.frame().size.height)
    assert ok, f"okno zůstalo na výchozích {h:.0f} px — měření DOM neproběhlo"
    # Jedno sdělení je změřeně ~157 px obsahu.
    assert 150 < h < 200, f"okno {h:.0f} px neodpovídá jednomu sdělení"

    # Dvě sdělení musí okno zase natáhnout.
    panel.show_beside(object(), Rect(1200, 400, 320, 560),
                      {"ready": False, "key_ok": False,
                       "downloading": False, "percent": 0})
    assert _pump(lambda: float(panel.panel.frame().size.height) > h + 40), (
        "druhé sdělení (chybí i klíč) musí okno natáhnout"
    )
    assert float(panel.panel.frame().size.width) == NoticePanel.W
    assert _PAD > 0
    panel.hide()


def test_hud_card_never_gets_clipped(_app):
    from spillway.hud import StatusHUD

    # Karta má `width:fit-content`; kdyby okno bylo užší, text se uřízne.
    # Tohle se už jednou stalo („Připraveno k vložení" mělo 243 px v okně 240).
    hud = StatusHUD()
    for state in ("rec", "proc", "cancel", "ready", "nomodel"):
        hud.show(state)
        got = {}

        def grab(value, err, _got=got):
            _got["v"] = value

        _pump(lambda: False, 0.35)   # nech doběhnout setState i přepočet okna
        hud.web.evaluateJavaScript_completionHandler_(
            "document.getElementById('card').getBoundingClientRect().width", grab)
        _pump(lambda g=got: "v" in g, 3.0)
        card = float(got.get("v") or 0)
        win = float(hud.panel.frame().size.width)
        assert card > 0, f"stav {state}: kartu se nepodařilo změřit"
        assert win >= card, f"stav {state}: okno {win:.0f} px uřízne kartu {card:.0f} px"
    hud.hide()
