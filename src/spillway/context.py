"""Zjištění kontextu — do jaké aplikace se diktuje.

Používá NSWorkspace.frontmostApplication (název + bundle ID), bez oprávnění.
Titulek okna schválně neřešíme (vyžadoval by Screen Recording — viz plán O3).
"""

from __future__ import annotations

from AppKit import NSWorkspace


def frontmost_app() -> tuple[str | None, str | None]:
    """Vrátí (název aplikace, bundle ID) právě aktivní aplikace."""
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return (None, None)
    return (app.localizedName(), app.bundleIdentifier())
