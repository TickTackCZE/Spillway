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


def logo_svg(fg: str = "#E2E8F0", grille: str = "#1A1F2E", width: int = 18, height: int = 20) -> str:
    """Logo Spillway (koncept A): kapka = mikrofon (mřížka = vlnky vody).

    `fg` = barva kapky, `grille` = barva mřížky (obvykle barva pozadí, aby
    linky „prořízly" kapku). Dvojí čtení jako Domovoy (mic ↔ voda).
    """
    return (
        f'<svg viewBox="0 0 64 72" width="{width}" height="{height}" '
        'xmlns="http://www.w3.org/2000/svg">'
        f'<path d="M32 5 C45 27 51 35 51 45 A19 19 0 0 1 13 45 C13 35 19 27 32 5 Z" fill="{fg}"/>'
        f'<line x1="20" y1="42" x2="44" y2="42" stroke="{grille}" stroke-width="3" stroke-linecap="round"/>'
        f'<line x1="18" y1="50" x2="46" y2="50" stroke="{grille}" stroke-width="3" stroke-linecap="round"/>'
        f'<line x1="21" y1="58" x2="43" y2="58" stroke="{grille}" stroke-width="3" stroke-linecap="round"/>'
        "</svg>"
    )
