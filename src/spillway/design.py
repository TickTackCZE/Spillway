"""Design tokeny Domovoy (Půlnoční / dark) — z brand manuálu Domovoy.

Používá HUD a (budoucí) vlastní okno nastavení, ať Spillway vypadá jako Domovoy.
Barvy jako (R, G, B) 0–255.
"""

FONT = "Raleway"  # fallback na systémový font, pokud není nainstalovaný

BG = (0x0F, 0x11, 0x17)        # background (Půlnoční)
SURFACE = (0x1A, 0x1F, 0x2E)   # surface
SURFACE_2 = (0x25, 0x2D, 0x42)
TEXT = (0xE2, 0xE8, 0xF0)      # text primary
MUTED = (0x64, 0x74, 0x8B)     # text muted
ACCENT = (0x81, 0x8C, 0xF8)    # accent

SUCCESS = (0x4A, 0xDE, 0x80)
WARNING = (0xF5, 0x9E, 0x0B)
ERROR = (0xE1, 0x1D, 0x48)
IDLE = (0x94, 0xA3, 0xB8)

RADIUS = 10


# Sloupce roztékající waveform (viewBox 100×100): x, top, bottom.
_WAVE_BARS = (
    (23, 40, 58), (31, 30, 66), (39, 20, 74), (47, 12, 82),
    (55, 22, 72), (63, 16, 84), (71, 34, 64), (79, 44, 60),
)


def scaled_bars(k: float) -> tuple[tuple[float, float, float], ...]:
    """Sloupce loga zmenšené na `k` původní výšky, každý kolem svého středu.

    Geometrie vlnovky žije tady, ne u volajících — kreslí ji ikona v liště
    (animace stavů) i nápověda (schémata), a musí vypadat stejně.
    """
    out = []
    for x, top, bot in _WAVE_BARS:
        center = (top + bot) / 2.0
        half = (bot - top) / 2.0 * k
        out.append((x, center - half, center + half))
    return tuple(out)


def wave_bars(index: int, frames: int, lo: float = 0.28, hi: float = 0.78
              ) -> tuple[tuple[float, float, float], ...]:
    """Vlna běžící zleva doprava — snímek `index` z `frames`.

    Výšku určuje POUZE vlna, ne původní tvar loga: ten má sloupce hodně různě
    vysoké a putující hřeben by se v něm ztratil.
    """
    import math

    n = len(_WAVE_BARS)
    center = sum((t + b) / 2.0 for _, t, b in _WAVE_BARS) / n
    ref_half = max((b - t) / 2.0 for _, t, b in _WAVE_BARS)
    out = []
    for j in range(n):
        phase = 2 * math.pi * (j / n - (index % frames) / frames)
        half = ref_half * (lo + (hi - lo) * (0.5 + 0.5 * math.sin(phase)))
        out.append((_WAVE_BARS[j][0], center - half, center + half))
    return tuple(out)


def bars_svg(bars, color: str = "#818CF8", width: int = 18, height: int = 18) -> str:
    """Libovolná sada sloupců jako SVG (viewBox 100×100)."""
    rects = "".join(
        f'<rect x="{x - 3:.1f}" y="{t:.1f}" width="6" height="{b - t:.1f}" rx="3" fill="{color}"/>'
        for x, t, b in bars
    )
    return (
        f'<svg viewBox="0 0 100 100" width="{width}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg">{rects}</svg>'
    )


def logo_svg(color: str = "#818CF8", width: int = 18, height: int = 18) -> str:
    """Logo Spillway: zvuková vlna (řeč, která přetéká — „spillway").

    Svislé zaoblené sloupce (waveform). Nic pod nimi — kapky se ukázaly jako
    šum, který se v malých velikostech slil a do loga nepatřil.
    """
    return bars_svg(_WAVE_BARS, color, width, height)
