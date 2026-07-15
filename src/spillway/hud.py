"""Plovoucí status okénko u kurzoru (Domovoy design).

Malý borderless panel u myši, který ukazuje stav: 🔴 Nahrávám / ⏳ Zpracovávám.
Styl dle Domovoy (Půlnoční surface, accent border, Raleway, radius 10).

Vše musí běžet na hlavním vlákně (volá se z rumps.Timer). Konstrukce i update
jsou proto v tray na main threadu. Když se HUD nepodaří vytvořit, tray ho tiše
přeskočí (aplikace běží dál).
"""

from __future__ import annotations

from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSEvent,
    NSFont,
    NSMakePoint,
    NSMakeRect,
    NSPanel,
    NSTextField,
    NSView,
)

from . import design

_BORDERLESS = 0
_NONACTIVATING = 1 << 7
_STATUS_LEVEL = 25  # NSStatusWindowLevel — nad běžnými okny
_ALL_SPACES = 1 << 0
_STATIONARY = 1 << 4
_FS_AUX = 1 << 8


def _color(rgb, alpha: float = 1.0):
    r, g, b = rgb
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r / 255, g / 255, b / 255, alpha)


class StatusHUD:
    W, H = 172, 42

    def __init__(self) -> None:
        rect = NSMakeRect(0, 0, self.W, self.H)
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, _BORDERLESS | _NONACTIVATING, NSBackingStoreBuffered, False
        )
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setLevel_(_STATUS_LEVEL)
        self.panel.setIgnoresMouseEvents_(True)
        self.panel.setHasShadow_(True)
        self.panel.setFloatingPanel_(True)
        self.panel.setHidesOnDeactivate_(False)
        try:
            self.panel.setCollectionBehavior_(_ALL_SPACES | _STATIONARY | _FS_AUX)
        except Exception:  # noqa: BLE001
            pass

        content = NSView.alloc().initWithFrame_(rect)
        content.setWantsLayer_(True)
        layer = content.layer()
        layer.setBackgroundColor_(_color(design.SURFACE).CGColor())
        layer.setCornerRadius_(design.RADIUS)
        layer.setBorderWidth_(1.0)
        layer.setBorderColor_(_color(design.ACCENT, 0.45).CGColor())
        self.panel.setContentView_(content)

        # Stavová tečka.
        self.dot = NSView.alloc().initWithFrame_(NSMakeRect(16, self.H / 2 - 4, 8, 8))
        self.dot.setWantsLayer_(True)
        self.dot.layer().setCornerRadius_(4)
        content.addSubview_(self.dot)

        # Popisek.
        self.label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(34, 0, self.W - 44, self.H)
        )
        self.label.setBezeled_(False)
        self.label.setDrawsBackground_(False)
        self.label.setEditable_(False)
        self.label.setSelectable_(False)
        self.label.setTextColor_(_color(design.TEXT))
        font = NSFont.fontWithName_size_(design.FONT, 13.0) or NSFont.systemFontOfSize_(13.0)
        self.label.setFont_(font)
        content.addSubview_(self.label)

        self._visible = False

    def _reposition(self) -> None:
        loc = NSEvent.mouseLocation()  # screen coords, bottom-left origin
        self.panel.setFrameOrigin_(NSMakePoint(loc.x + 14, loc.y + 18))

    def show(self, text: str, dot_rgb) -> None:  # noqa: ANN001
        self.dot.layer().setBackgroundColor_(_color(dot_rgb).CGColor())
        self.label.setStringValue_(text)
        self._reposition()
        if not self._visible:
            self.panel.orderFrontRegardless()
            self._visible = True

    def hide(self) -> None:
        if self._visible:
            self.panel.orderOut_(None)
            self._visible = False
