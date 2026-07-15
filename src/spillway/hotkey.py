"""Globální hold-to-talk hotkey přes CGEventTap.

Ověřeno ve Spike C/C2:
  - F5 (diktovací klávesa) chodí jako normální keyDown/keyUp, keycode 176,
  - `return None` z callbacku ji potlačí → nativní diktování nenaskočí (R9),
  - tap běží na VLASTNÍM vlákně s vlastním CFRunLoop (ne na main threadu),
    callback drží triviální (jen zavolá rychlé on_press/on_release),
  - po `kCGEventTapDisabledByTimeout` se tap znovu povolí (R4).

Vyžaduje oprávnění Input Monitoring; pro potlačení klávesy i Accessibility.
"""

from __future__ import annotations

import threading
from typing import Callable

from Quartz import (
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CFRunLoopStop,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventTapCreate,
    CGEventTapEnable,
    kCFRunLoopCommonModes,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventTapDisabledByTimeout,
    kCGEventTapDisabledByUserInput,
    kCGEventTapOptionDefault,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
)

F5_DICTATION_KEYCODE = 176


class HotkeyListener:
    def __init__(
        self,
        *,
        keycode: int = F5_DICTATION_KEYCODE,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        suppress: bool = True,
    ):
        self.keycode = keycode
        self.on_press = on_press
        self.on_release = on_release
        self.suppress = suppress
        self._pressed = False
        self._tap = None
        self._runloop = None
        self._thread: threading.Thread | None = None
        self._capturing = False
        self._capture_cb: Callable[[int], None] | None = None

    def start_capture(self, on_captured: Callable[[int], None]) -> None:
        """Zachytí příští stisknutou klávesu (kdekoliv v systému) a zavolá
        `on_captured(keycode)` — pro nastavení nové hotkey v UI. Jednorázové,
        volané z vlákna tapu; volající si musí přehodit výsledek na main thread."""
        self._capture_cb = on_captured
        self._capturing = True

    def _callback(self, proxy, type_, event, refcon):  # noqa: ANN001
        if type_ in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
            CGEventTapEnable(self._tap, True)
            return event

        if self._capturing:
            if type_ == kCGEventKeyDown:
                captured = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                self._capturing = False
                cb, self._capture_cb = self._capture_cb, None
                if cb is not None:
                    cb(captured)
                return None  # spolknout tenhle stisk, ať nic nenapíše/nespustí
            return event

        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        if keycode != self.keycode:
            return event

        if type_ == kCGEventKeyDown and not self._pressed:
            self._pressed = True
            self.on_press()
        elif type_ == kCGEventKeyUp and self._pressed:
            self._pressed = False
            self.on_release()

        return None if self.suppress else event

    def _run(self) -> None:
        mask = CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventKeyUp)
        self._tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            mask,
            self._callback,
            None,
        )
        if self._tap is None:
            raise RuntimeError(
                "Nepodařilo se vytvořit event tap — povol Input Monitoring "
                "(a pro potlačení klávesy Accessibility) pro tuto aplikaci."
            )
        source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
        self._runloop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(self._runloop, source, kCFRunLoopCommonModes)
        CGEventTapEnable(self._tap, True)
        CFRunLoopRun()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="spillway-hotkey")
        self._thread.start()

    def stop(self) -> None:
        if self._tap is not None:
            CGEventTapEnable(self._tap, False)
        if self._runloop is not None:
            CFRunLoopStop(self._runloop)
