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
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventTapCreate,
    CGEventTapEnable,
    kCFRunLoopCommonModes,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskShift,
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
_CAPTURE_TIMEOUT_S = 6.0
_MODIFIER_MASK = (
    kCGEventFlagMaskCommand
    | kCGEventFlagMaskAlternate
    | kCGEventFlagMaskControl
    | kCGEventFlagMaskShift
)


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
        self._cancel_cb: Callable[[], None] | None = None
        self._capture_lock = threading.Lock()
        self._capture_timer: threading.Timer | None = None

    def start_capture(
        self,
        on_captured: Callable[[int], None],
        on_cancel: Callable[[], None] | None = None,
    ) -> bool:
        """Zachytí příští „čistý" stisk (bez modifikátorů) a zavolá
        `on_captured(keycode)`. [B4] Po `_CAPTURE_TIMEOUT_S` bez stisku se zruší
        a zavolá `on_cancel`. [B6] Odmítne se, když se právě nahrává (vrátí False).
        Callbacky běží z vlákna tapu/časovače — volající je přehodí na main thread."""
        with self._capture_lock:
            if self._pressed or self._capturing:
                return False
            self._capturing = True
            self._capture_cb = on_captured
            self._cancel_cb = on_cancel
            self._capture_timer = threading.Timer(_CAPTURE_TIMEOUT_S, self._capture_timeout)
            self._capture_timer.daemon = True
            self._capture_timer.start()
        return True

    def cancel_capture(self) -> None:
        """Zruší probíhající zachytávání (např. při zavření okna nastavení)."""
        with self._capture_lock:
            if not self._capturing:
                return
            self._capturing = False
            self._capture_cb = None
            cancel, self._cancel_cb = self._cancel_cb, None
            if self._capture_timer is not None:
                self._capture_timer.cancel()
                self._capture_timer = None
        if cancel is not None:
            cancel()

    def _capture_timeout(self) -> None:
        self.cancel_capture()

    def _callback(self, proxy, type_, event, refcon):  # noqa: ANN001
        if type_ in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
            CGEventTapEnable(self._tap, True)
            return event

        if self._capturing:
            if type_ != kCGEventKeyDown:
                return event
            # [B4] Ignoruj klávesu se stisknutým modifikátorem (⌘C by jinak
            # zachytilo jen „C" a potlačilo všechno psaní C). Čekej dál na čistý stisk.
            if CGEventGetFlags(event) & _MODIFIER_MASK:
                return event
            with self._capture_lock:
                if not self._capturing:
                    return event
                captured = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                self._capturing = False
                cb, self._capture_cb = self._capture_cb, None
                self._cancel_cb = None
                if self._capture_timer is not None:
                    self._capture_timer.cancel()
                    self._capture_timer = None
            if cb is not None:
                cb(captured)
            return None  # spolknout tenhle stisk, ať nic nenapíše/nespustí

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
