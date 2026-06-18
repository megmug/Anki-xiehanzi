"""Shared paths and deck assembly helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import genanki

from anki_hanzi.deck import identity


DECK_ROOT = "汉字 (Hànzì)"
OUTPUT_APKG = Path("anki-hanzi.apkg")
DECK_INPUTS_DIR = Path("deck_inputs")
TEMPLATE_RESOURCES_DIR = Path("tooling/lib/anki_hanzi/deck/template_resources")
EXTRA_AUDIO_DIR = DECK_INPUTS_DIR / "extra_audio"
HANZI_WRITER_PACKAGE_JSON = Path("node_modules/hanzi-writer/package.json")
HANZI_WRITER_BUNDLE = Path("node_modules/hanzi-writer/dist/hanzi-writer.min.js")
HANZI_WRITER_DATA_DIR = Path("node_modules/hanzi-writer-data")

LEVELS = ["1", "2", "3", "4", "5", "6", "7-9"]
CARD_TYPES = ["Meaning", "Pinyin", "Write"]

DEFAULT_CONFIG_PATH = DECK_INPUTS_DIR / "deck_config.json"


class NoteEntry(Protocol):
    def fields(self, card_type: str, build_id: str) -> list[str]: ...

    @property
    def tags(self) -> tuple[str, ...]: ...


def create_deck(
    deck_name: str,
    card_type: str,
    model: genanki.Model,
    entries: list[NoteEntry],
    build_id: str,
) -> genanki.Deck:
    deck = genanki.Deck(identity.stable_id(f"deck:{deck_name}"), deck_name)
    for entry in entries:
        fields = entry.fields(card_type, build_id)
        note_id = fields[-2]
        deck.add_note(
            genanki.Note(
                model=model,
                fields=fields,
                tags=identity.anki_tag_names(entry.tags),
                guid=identity.stable_note_guid(note_id),
            )
        )
    return deck


def remove_failed_audio_output(path: Path) -> None:
    if path.exists() and path.stat().st_size == 0:
        path.unlink()
