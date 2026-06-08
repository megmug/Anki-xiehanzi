"""Source parsing for the xiehanzi New HSK TSV files."""

from __future__ import annotations

import csv
import html
import re
from pathlib import Path
from typing import Any


HANZI_DEDUPE_KEY = "Simplified + raw Pinyin"
LEVELS = ["1", "2", "3", "4", "5", "6", "7-9"]
HANZI_FIELDS = [
    "Simplified",
    "Pinyin",
    "Level",
    "PoS",
    "Frequency",
    "Meaning HTML",
]

XIEHANZI_TSV_MIN_COLUMNS = 8
XIEHANZI_SIMPLIFIED_COLUMN = 0
XIEHANZI_PINYIN_COLUMN = 2
XIEHANZI_LEVEL_COLUMN = 4
XIEHANZI_POS_COLUMN = 5
XIEHANZI_FREQUENCY_COLUMN = 6
XIEHANZI_MEANING_HTML_COLUMN = 7


def strip_html_field(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", "", value)
    return value.strip()


def entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "simplified": entry["simplified"],
        "pinyin": entry["pinyin"],
        "deck_level": entry["deck_level"],
        "raw_level": entry["raw_level"],
        "source": entry["source"],
    }
    if entry.get("raw_pinyin") and entry["raw_pinyin"] != entry["pinyin"]:
        summary["raw_pinyin"] = entry["raw_pinyin"]
    if entry.get("manual_pinyin_override"):
        summary["manual_pinyin_override"] = entry["manual_pinyin_override"]
    return summary


def dedupe_key(entry: dict[str, Any]) -> tuple[str, str]:
    return entry["simplified"], entry["pinyin"]


def printable_key(key: tuple[str, str]) -> str:
    return "::".join(key)


def parse_frequency(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def normalize_hsk_level(value: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if value in {"7", "8", "9", "7-9"}:
        return "7-9"
    if value in {"1", "2", "3", "4", "5", "6"}:
        return value
    return None


def level_tags(source_level: str, raw_level: str) -> list[str]:
    levels: list[str] = []
    for value in [source_level, *re.findall(r"7-9|[1-9]", raw_level or "")]:
        normalized = normalize_hsk_level(value)
        if normalized and normalized not in levels:
            levels.append(normalized)
    return [f"hsk:{level}" for level in levels]


def make_entry(
    row: list[str],
    source: str,
    source_file: Path,
    row_number: int,
    deck_level: str,
) -> dict[str, Any]:
    if len(row) < XIEHANZI_TSV_MIN_COLUMNS:
        raise ValueError(f"Expected at least 8 TSV columns in {source_file}:{row_number}, got {len(row)}: {row!r}")

    simplified = strip_html_field(row[XIEHANZI_SIMPLIFIED_COLUMN])
    raw_pinyin = row[XIEHANZI_PINYIN_COLUMN]
    raw_level = row[XIEHANZI_LEVEL_COLUMN]
    pos = row[XIEHANZI_POS_COLUMN]
    frequency_text = row[XIEHANZI_FREQUENCY_COLUMN]
    meaning_html = row[XIEHANZI_MEANING_HTML_COLUMN]

    tags = level_tags(deck_level, raw_level)
    return {
        "simplified": simplified,
        "pinyin": raw_pinyin,
        "raw_pinyin": raw_pinyin,
        "deck_level": deck_level,
        "raw_level": raw_level,
        "pos": pos,
        "frequency": parse_frequency(frequency_text),
        "meaning_html": meaning_html,
        "source": source,
        "tags": sorted(set(tags)),
    }


def read_word_file(path: Path, source: str, deck_level: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row_number, row in enumerate(csv.reader(handle, delimiter="\t"), start=1):
            if not row:
                continue
            if row[0].startswith("#"):
                continue
            entries.append(
                make_entry(
                    row,
                    source=source,
                    source_file=path,
                    row_number=row_number,
                    deck_level=deck_level,
                )
            )
    return entries


def load_hanzi_entries(hsk_data_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for level in LEVELS:
        path = hsk_data_dir / f"HSK_Level_{level}.txt"
        entries.extend(read_word_file(path, source=f"HSK {level}", deck_level=level))

    return entries


def dedupe_entries(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    kept_entries: list[dict[str, Any]] = []
    dropped_duplicates: list[dict[str, Any]] = []
    next_deck_order = {level: 0 for level in LEVELS}

    for entry in entries:
        key = dedupe_key(entry)
        existing = kept_by_key.get(key)
        if existing is None:
            entry["deck_order"] = next_deck_order[entry["deck_level"]]
            next_deck_order[entry["deck_level"]] += 1
            kept_by_key[key] = entry
            kept_entries.append(entry)
            continue

        duplicate_record = {
            "key": printable_key(key),
            "kept": entry_summary(existing),
            "dropped": entry_summary(entry),
            "reason": "duplicate hanzi entry",
        }
        dropped_duplicates.append(duplicate_record)

    return kept_entries, dropped_duplicates
