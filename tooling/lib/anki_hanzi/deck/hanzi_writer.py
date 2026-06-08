"""Hanzi-writer data helpers for the Write deck."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from anki_hanzi.deck import common
from anki_hanzi.deck.entries import EnrichedWordEntry


def _is_hanzi_char(char: str) -> bool:
    code = ord(char)
    return (0x4E00 <= code <= 0x9FFF) or (0x3400 <= code <= 0x4DBF) or (0x20000 <= code <= 0x2EBEF)


def has_hanzi_writer_data(char: str) -> bool:
    if not _is_hanzi_char(char):
        return False
    data_file = common.HANZI_WRITER_DATA_DIR / f"{char}.json"
    return data_file.exists()


def is_writable_hanzi(text: str) -> bool:
    if not text:
        return False
    return all(has_hanzi_writer_data(char) for char in text)


def build_hanzi_writer_bundle(
    write_entries: list[EnrichedWordEntry],
    output_path: Path,
) -> str:
    """Build a single JS file with all hanzi-writer data needed by the Write deck."""

    unique_chars: set[str] = set()
    for entry in write_entries:
        for char in entry.simplified:
            if has_hanzi_writer_data(char):
                unique_chars.add(char)

    data: dict[str, Any] = {}
    for char in sorted(unique_chars):
        data_file = common.HANZI_WRITER_DATA_DIR / f"{char}.json"
        if data_file.exists():
            data[char] = json.loads(data_file.read_text(encoding="utf-8"))

    bundle_js = "window.hanziWriterData = " + json.dumps(data, ensure_ascii=False) + ";\n"
    output_path.write_text(bundle_js, encoding="utf-8")
    return str(output_path)
