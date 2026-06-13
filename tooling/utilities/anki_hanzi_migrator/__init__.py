"""Anki Hanzi Migrator add-on entry point."""

from __future__ import annotations

try:
    from .ui import register_menu_action
except ModuleNotFoundError as exc:
    if exc.name != "aqt":
        raise
else:
    register_menu_action()
