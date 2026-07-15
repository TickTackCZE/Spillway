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


def logo_svg(color: str = "#818CF8", width: int = 18, height: int = 18, drops: bool = True) -> str:
    """Logo Spillway: roztékající se zvuková vlna (řeč, která přetéká — „spillway").

    Svislé zaoblené sloupce (waveform) + drobné kapky pod nimi. `drops=False`
    pro malé velikosti (lišta/HUD), kde by kapky splynuly.
    """
    bars = "".join(
        f'<rect x="{x - 3}" y="{t}" width="6" height="{b - t}" rx="3" fill="{color}"/>'
        for x, t, b in _WAVE_BARS
    )
    d = (
        f'<circle cx="50" cy="90" r="3.4" fill="{color}"/>'
        f'<circle cx="63" cy="93" r="2.4" fill="{color}" opacity="0.7"/>'
        f'<circle cx="40" cy="92" r="2" fill="{color}" opacity="0.6"/>'
    ) if drops else ""
    return (
        f'<svg viewBox="0 0 100 100" width="{width}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg">{bars}{d}</svg>'
    )
