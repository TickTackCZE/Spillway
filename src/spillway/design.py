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
