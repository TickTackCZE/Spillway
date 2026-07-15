"""Vygeneruje app ikonu (.icns) z waveform loga — zaoblený čtverec v accentu
(#818CF8) na tmavém pozadí (Domovoy Půlnoční), bílá vlna uprostřed + kapky.

Spuštění:  uv run python build/make_icon.py
Výstup:    build/icon.icns
"""

from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from AppKit import (  # noqa: E402
    NSBezierPath,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSColor,
    NSImage,
    NSMakeRect,
)

from spillway import design  # noqa: E402

_HERE = os.path.dirname(__file__)
_ICONSET = os.path.join(_HERE, "icon.iconset")
_ICNS = os.path.join(_HERE, "icon.icns")

_BG = tuple(c / 255 for c in design.BG)          # #0F1117
_ACCENT = tuple(c / 255 for c in design.ACCENT)  # #818CF8
_WHITE = (0.95, 0.96, 0.98)


def _color(rgb, alpha=1.0):
    r, g, b = rgb
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, alpha)


def render(size: int) -> NSImage:
    img = NSImage.alloc().initWithSize_((size, size))
    img.lockFocus()

    # Zaoblené pozadí (~22% radius, macOS „squircle" styl).
    pad = size * 0.04
    rect = NSMakeRect(pad, pad, size - 2 * pad, size - 2 * pad)
    bg = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        rect, size * 0.22, size * 0.22
    )
    _color(_BG).set()
    bg.fill()

    # Waveform sloupce (souřadnice ze design._WAVE_BARS, viewBox 100x100).
    scale = (size - 2 * pad) / 100.0

    def mx(x: float) -> float:
        return pad + x * scale

    def my(y: float) -> float:  # SVG y dolů → AppKit y nahoru
        return size - (pad + y * scale)

    bar_w = 6.0 * scale
    for x, top, bot in design._WAVE_BARS:
        x0 = mx(x) - bar_w / 2
        y_bot = my(bot)
        y_top = my(top)
        r = NSMakeRect(x0, y_bot, bar_w, y_top - y_bot)
        p = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(r, bar_w / 2, bar_w / 2)
        _color(_ACCENT).set()
        p.fill()

    # Kapky pod vlnou.
    for cx, cy, r in ((50, 90, 3.4), (63, 93, 2.4), (40, 92, 2.0)):
        rect = NSMakeRect(mx(cx) - r * scale, my(cy) - r * scale, 2 * r * scale, 2 * r * scale)
        dot = NSBezierPath.bezierPathWithOvalInRect_(rect)
        _color(_ACCENT).set()
        dot.fill()

    img.unlockFocus()
    return img


def save_png(img: NSImage, path: str) -> None:
    rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
    png = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    png.writeToFile_atomically_(path, True)


def main() -> None:
    os.makedirs(_ICONSET, exist_ok=True)
    # macOS .iconset konvence: base + @2x pro každou deklarovanou velikost.
    sizes = [16, 32, 128, 256, 512]
    for s in sizes:
        save_png(render(s), os.path.join(_ICONSET, f"icon_{s}x{s}.png"))
        save_png(render(s * 2), os.path.join(_ICONSET, f"icon_{s}x{s}@2x.png"))

    subprocess.run(["iconutil", "-c", "icns", _ICONSET, "-o", _ICNS], check=True)
    print(f"✅ {_ICNS}")


if __name__ == "__main__":
    main()
