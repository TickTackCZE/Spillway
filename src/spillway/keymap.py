"""Čitelné názvy macOS virtuálních keycodů — jen pro zobrazení v UI.

Zachycení klávesy funguje pro libovolný keycode (viz `hotkey.start_capture`);
tahle mapa je jen kosmetika, aby uživatel viděl název místo čísla.
"""

from __future__ import annotations

_NAMES: dict[int, str] = {
    0: "A", 1: "S", 2: "D", 3: "F", 4: "H", 5: "G", 6: "Z", 7: "X", 8: "C", 9: "V",
    11: "B", 12: "Q", 13: "W", 14: "E", 15: "R", 16: "Y", 17: "T",
    18: "1", 19: "2", 20: "3", 21: "4", 22: "6", 23: "5", 24: "=", 25: "9",
    26: "7", 27: "-", 28: "8", 29: "0", 30: "]", 31: "O", 32: "U", 33: "[",
    34: "I", 35: "P", 36: "Return", 37: "L", 38: "J", 39: "'", 40: "K",
    41: ";", 42: "\\", 43: ",", 44: "/", 45: "N", 46: "M", 47: ".",
    48: "Tab", 49: "Mezerník", 50: "`", 51: "Delete", 53: "Escape",
    82: "Keypad 0", 83: "Keypad 1", 84: "Keypad 2", 85: "Keypad 3", 86: "Keypad 4",
    87: "Keypad 5", 88: "Keypad 6", 89: "Keypad 7", 91: "Keypad 8", 92: "Keypad 9",
    96: "F5", 97: "F6", 98: "F7", 99: "F3", 100: "F8", 101: "F9", 103: "F11",
    105: "F13", 107: "F14", 109: "F10", 111: "F12", 113: "F15", 118: "F4",
    120: "F2", 122: "F1",
    114: "Help", 115: "Home", 116: "PageUp", 117: "ForwardDelete",
    119: "End", 121: "PageDown", 123: "Šipka vlevo", 124: "Šipka vpravo",
    125: "Šipka dolů", 126: "Šipka nahoru",
    54: "Pravý ⌘", 55: "⌘", 56: "⇧", 57: "Caps Lock", 58: "Levý ⌥",
    59: "Levý ⌃", 60: "Pravý ⇧", 61: "Pravý ⌥", 62: "Pravý ⌃", 63: "Fn / Globe",
    176: "F5 (diktování)",  # nativní diktovací klávesa, viz plán R9/Spike C2
}


def label_for(keycode: int) -> str:
    return _NAMES.get(keycode, f"Klávesa #{keycode}")
