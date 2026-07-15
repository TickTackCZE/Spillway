"""Ikona Spillway (waveform) pro menu bar — vykreslená jako template PNG.

Nakreslí zaoblené sloupce (stejné jako logo) do malého obrázku a uloží ho jako
template PNG; rumps ho pak v liště obarví dle systému (mono, jako ostatní ikony).
Vrací cestu k PNG, nebo None při chybě (tray pak použije emoji placeholder).
"""

from __future__ import annotations

import os

from . import design

_DIR = os.path.expanduser("~/Library/Application Support/Spillway")
_PATH = os.path.join(_DIR, "menubar.png")

# Zdrojová oblast waveform (viewBox 100), aby ikona seděla těsně.
_SX0, _SX1 = 17.0, 88.0
_SY0, _SY1 = 8.0, 88.0


def icon_path() -> str | None:
    try:
        from AppKit import (
            NSBezierPath,
            NSBitmapImageFileTypePNG,
            NSBitmapImageRep,
            NSColor,
            NSImage,
            NSMakeRect,
        )

        size = 20.0
        pad = size * 0.12
        avail = size - 2 * pad

        def mx(x: float) -> float:
            return pad + (x - _SX0) / (_SX1 - _SX0) * avail

        def my(x: float) -> float:  # SVG y (dolů) → NSImage y (nahoru)
            yy = pad + (x - _SY0) / (_SY1 - _SY0) * avail
            return size - yy

        img = NSImage.alloc().initWithSize_((size, size))
        img.lockFocus()
        NSColor.blackColor().set()
        bar_w = 6.0 / (_SX1 - _SX0) * avail
        for x, top, bot in design._WAVE_BARS:
            x0 = mx(x) - bar_w / 2
            y_bot = my(bot)
            y_top = my(top)
            rect = NSMakeRect(x0, y_bot, bar_w, y_top - y_bot)
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                rect, bar_w / 2, bar_w / 2
            )
            path.fill()
        img.unlockFocus()

        rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
        png = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
        os.makedirs(_DIR, exist_ok=True)
        png.writeToFile_atomically_(_PATH, True)
        return _PATH
    except Exception:  # noqa: BLE001
        return None
