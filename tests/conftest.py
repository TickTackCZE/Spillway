"""Sdílené nastavení testů — přidá src/ na path."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
