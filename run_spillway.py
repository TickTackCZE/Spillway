"""Spouštěč Spillway (F1). Přidá src/ na path a spustí app.

    uv run python run_spillway.py

Ve fázi F3 nahradí instalovatelný balíček + menu bar .app.

POZOR na pořadí v `__main__` — přepis běží v podprocesu (`spillway.gpuworker`),
který se startuje přes „spawn", takže tenhle soubor se v něm spustí ZNOVU:

  1. `sys.path.insert` musí zůstat na úrovni modulu. Projekt není instalovatelný
     balíček (`package = false` v pyproject), takže bez něj by podproces
     `spillway.gpuworker` vůbec nenašel.
  2. `multiprocessing.freeze_support()` musí být PRVNÍ věc v `__main__` — a těžký
     import `spillway.app` až ZA ním. V zabalené .app se totiž podproces spustí
     s `__name__ == "__main__"`, takže samotná podmínka nestačí: `freeze_support()`
     v podprocesu odbočí do workeru a už se nevrátí, takže se import appky
     (a s ním rumps, AppKit, sounddevice → `Pa_Initialize()`) v podprocesu vůbec
     neprovede. Kdyby byl import nad ním, každý worker by si zbytečně otevřel
     klienta CoreAudia a držel ho až do svého zabití.
"""

import multiprocessing
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

if __name__ == "__main__":
    multiprocessing.freeze_support()

    from spillway.app import main

    main()
