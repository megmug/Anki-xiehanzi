"""Shared helpers for building the custom hanzi APKG."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

import genanki


DECK_ROOT = "汉字 (Hànzì)"
OUTPUT_APKG = Path("anki-hanzi.apkg")
DECK_INPUTS_DIR = Path("deck_inputs")
CARD_TEMPLATES_DIR = DECK_INPUTS_DIR / "card_templates"
EXTRA_AUDIO_DIR = DECK_INPUTS_DIR / "extra_audio"
HANZI_WRITER_PACKAGE_JSON = Path("node_modules/hanzi-writer/package.json")
HANZI_WRITER_BUNDLE = Path("node_modules/hanzi-writer/dist/hanzi-writer.min.js")
HANZI_WRITER_DATA_DIR = Path("node_modules/hanzi-writer-data")

LEVELS = ["1", "2", "3", "4", "5", "6", "7-9"]
CARD_TYPES = ["Meaning", "Pinyin", "Write"]

DEFAULT_CONFIG_PATH = DECK_INPUTS_DIR / "deck_config.json"
TAG_NAMESPACE = "hanzi"


class NoteEntry(Protocol):
    def fields(self, card_type: str, build_id: str) -> list[str]: ...

    @property
    def tags(self) -> tuple[str, ...]: ...


def stable_id(label: str) -> int:
    digest = hashlib.sha256(label.encode("utf-8")).digest()
    return (int.from_bytes(digest[:4], "big") % (1 << 30)) + (1 << 30)


def stable_hex_id(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def normalized_note_pinyin(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def note_pinyin_id_key(card_type: str, pinyin: str) -> str:
    if card_type == "Meaning":
        return str(pinyin or "").strip()
    return normalized_note_pinyin(pinyin)


def stable_note_id(card_type: str, simplified: str, pinyin: str) -> str:
    return stable_hex_id(f"{card_type}\0{str(simplified or '').strip()}\0{note_pinyin_id_key(card_type, pinyin)}")


def stable_note_guid(note_id: str) -> str:
    return genanki.guid_for(str(note_id or "").strip())


def anki_tag_name(tag: str) -> str:
    tag = tag.strip()
    if not tag:
        return ""
    if tag.casefold().startswith(f"{TAG_NAMESPACE}::"):
        return TAG_NAMESPACE + tag[len(TAG_NAMESPACE) :]
    if ":" in tag:
        return f"{TAG_NAMESPACE}::" + "::".join(part for part in tag.split(":") if part)
    return f"{TAG_NAMESPACE}::{tag}"


def anki_tag_names(tags: tuple[str, ...]) -> list[str]:
    return sorted({formatted for tag in tags if (formatted := anki_tag_name(tag))})


def create_deck(
    deck_name: str,
    card_type: str,
    model: genanki.Model,
    entries: list[NoteEntry],
    build_id: str,
) -> genanki.Deck:
    deck = genanki.Deck(stable_id(f"deck:{deck_name}"), deck_name)
    for entry in entries:
        fields = entry.fields(card_type, build_id)
        note_id = fields[-2]
        deck.add_note(
            genanki.Note(
                model=model,
                fields=fields,
                tags=anki_tag_names(entry.tags),
                guid=stable_note_guid(note_id),
            )
        )
    return deck


def remove_failed_audio_output(path: Path) -> None:
    if path.exists() and path.stat().st_size == 0:
        path.unlink()
