"""Ikona Spillway (waveform) pro menu bar — vykreslená jako template PNG.

Nakreslí zaoblené sloupce (stejné jako logo) do malého obrázku a uloží ho jako
template PNG; rumps ho pak v liště obarví dle systému (mono, jako ostatní ikony).

Ikona je animovaná: kreslí se procedurálně z `design._WAVE_BARS`, takže „snímek"
je jen jiná sada výšek sloupců — žádné externí assety. Animace = tray přepíná
cesty k PNG na svém časovači (`frame_path`).

Snímky:
  idle   — základní logo (klid, „připraveno k vložení")
  rec    — živý ukazatel hlasitosti, `LEVEL_STEPS` stupňů podle mikrofonu
  proc   — vlna běžící zleva doprava (zpracovávám)
  cancel — sražené sloupce (ruším)

Vrací cestu k PNG, nebo None při chybě (tray pak použije emoji placeholder).
"""

from __future__ import annotations

import math
import os

from . import design

_DIR = os.path.expanduser("~/Library/Application Support/Spillway")
_PATH = os.path.join(_DIR, "menubar.png")

# Zdrojová oblast waveform (viewBox 100), aby ikona seděla těsně.
_SX0, _SX1 = 17.0, 88.0
_SY0, _SY1 = 8.0, 88.0

# Kolik stupňů má živý ukazatel. Víc než 8 se ve 20 bodech stejně nerozliší
# a jen by to rozblikalo ikonu.
LEVEL_STEPS = 8
# Délka pulzu při zpracování ve snímcích; tray tiká 0,15 s → cyklus ~1,2 s.
PULSE_FRAMES = 8

# Nejnižší poloha sloupců (podíl původní výšky) — v tichu z vlnovky zbyde
# řádka teček, ne prázdno, ať ikona nezmizí.
_K_MIN = 0.18
_K_MAX = 1.0

_cache: dict[tuple[str, int], str | None] = {}


def level_step(level: float) -> int:
    """Hlasitost 0..1 → index snímku 0..LEVEL_STEPS-1."""
    if level != level:  # NaN
        return 0
    return max(0, min(LEVEL_STEPS - 1, int(level * LEVEL_STEPS)))


# Rozsah běžící vlny při zpracování (podíl původní výšky).
_WAVE_LO, _WAVE_HI = 0.28, 0.78


def _scale_for(kind: str, index: int) -> float:
    """Jak vysoké mají být sloupce pro daný snímek (1.0 = původní logo).

    Platí pro stavy, kde jsou všechny sloupce stejně vysoké; „proc" má výšku
    pro každý sloupec jinou (běžící vlna) a řeší ho `_bars_for`.
    """
    if kind == "rec":
        i = max(0, min(LEVEL_STEPS - 1, index))
        return _K_MIN + (_K_MAX - _K_MIN) * (i / (LEVEL_STEPS - 1))
    if kind == "cancel":
        return _K_MIN
    return _K_MAX  # idle


def _bars_scaled(k: float) -> tuple[tuple[float, float, float], ...]:
    """Sloupce loga zmenšené na `k` výšky, každý kolem svého středu."""
    out = []
    for x, top, bot in design._WAVE_BARS:
        center = (top + bot) / 2.0
        half = (bot - top) / 2.0 * k
        out.append((x, center - half, center + half))
    return tuple(out)


def _bars_wave(index: int) -> tuple[tuple[float, float, float], ...]:
    """Vlna běžící zleva doprava — stav „zpracovávám".

    Každý sloupec má vlastní fázi podle své pozice, takže hřeben putuje po
    vlnovce; za `PULSE_FRAMES` snímků projde celou ikonu a plynule naváže.
    Pohyb má směr — tím se odliší od ukazatele hlasitosti, který jen skáče.

    Výšku tady určuje POUZE vlna, ne původní tvar loga: to má sloupce hodně
    různě vysoké (uprostřed skoro čtyřnásobek krajních), takže by se v něm
    putující hřeben ztratil a vypadalo by to jako blikání na místě.
    """
    bars = design._WAVE_BARS
    n = len(bars)
    center = sum((t + b) / 2.0 for _, t, b in bars) / n
    ref_half = max((b - t) / 2.0 for _, t, b in bars)
    out = []
    for j, (x, _t, _b) in enumerate(bars):
        phase = 2 * math.pi * (j / n - (index % PULSE_FRAMES) / PULSE_FRAMES)
        k = _WAVE_LO + (_WAVE_HI - _WAVE_LO) * (0.5 + 0.5 * math.sin(phase))
        half = ref_half * k
        out.append((x, center - half, center + half))
    return tuple(out)


def _bars_for(kind: str, index: int) -> tuple[tuple[float, float, float], ...]:
    """Sloupce pro daný snímek."""
    return _bars_wave(index) if kind == "proc" else _bars_scaled(_scale_for(kind, index))


def _render(bars, path: str) -> str | None:
    """Vykreslí sloupce do template PNG na `path`."""
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
    for x, top, bot in bars:
        x0 = mx(x) - bar_w / 2
        y_bot, y_top = my(bot), my(top)
        h = y_top - y_bot
        # Kratší než široký sloupec by se zaoblením zdegeneroval — necháme z něj
        # aspoň tečku, ať je vlnovka pořád čitelná jako logo.
        if h < bar_w:
            mid = (y_bot + y_top) / 2.0
            y_bot, h = mid - bar_w / 2, bar_w
        rect = NSMakeRect(x0, y_bot, bar_w, h)
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            rect, bar_w / 2, bar_w / 2
        ).fill()
    img.unlockFocus()

    rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
    png = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    os.makedirs(_DIR, exist_ok=True)
    png.writeToFile_atomically_(path, True)
    return path


def frame_path(kind: str = "idle", index: int = 0) -> str | None:
    """Cesta k PNG daného snímku; generuje se líně a drží se v cache.

    Líně schválně — snímků je 18 a naráz by je nikdo nepotřeboval. Každý stojí
    pár milisekund a vygeneruje se nejvýš jednou za běh.
    """
    key = (kind, index if kind in ("rec", "proc") else 0)
    if key in _cache:
        return _cache[key]
    try:
        name = _PATH if kind == "idle" else os.path.join(_DIR, f"menubar-{key[0]}-{key[1]}.png")
        result = _render(_bars_for(*key), name)
    except Exception:  # noqa: BLE001
        result = None
    _cache[key] = result
    return result


def icon_path() -> str | None:
    """Statická ikona (klid) — použije ji tray při startu."""
    return frame_path("idle")
