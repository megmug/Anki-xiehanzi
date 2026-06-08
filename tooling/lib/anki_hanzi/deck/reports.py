"""Build report assembly for the customized hanzi APKG."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anki_hanzi.audio.api import AudioGenerationResult
from anki_hanzi.deck import common
from anki_hanzi.deck.entries import EnrichedWordEntry
from anki_hanzi.deck.templates import read_hanzi_writer_package_version


@dataclass(frozen=True)
class DeckBuildReportInput:
    output_apkg: Path
    report_path: Path
    master_db_output: Path
    enriched_db_output: Path
    enrichment_report_path: Path
    matching_report_path: Path | None
    selection_report: dict[str, Any]
    source_schema: str
    build_id: str
    card_types: tuple[str, ...]
    card_settings: dict[str, dict[str, dict[str, Any]]]
    dedupe_key: str
    entries_by_card_type: Mapping[str, Sequence[EnrichedWordEntry]]
    all_entries: Sequence[EnrichedWordEntry]
    total_cards: int
    decks_count: int
    media_files: Sequence[str]
    static_media: Sequence[str]
    audio_engine: str
    audio_voices: dict[str, dict[str, str]]
    audio_result: AudioGenerationResult
    timestamp: float | None
    deterministic_zip: bool
    default_zip_datetime: tuple[int, int, int, int, int, int]
    zip_generated_datetime: tuple[int, int, int, int, int, int] | None
    dropped_duplicates: Sequence[dict[str, Any]]
    missing_audio_files: Sequence[str]


def _unique_word_count(entries: Sequence[EnrichedWordEntry]) -> int:
    return len({entry.simplified.strip() for entry in entries if entry.simplified.strip()})


def build_deck_report(data: DeckBuildReportInput) -> dict[str, Any]:
    return {
        "output": str(data.output_apkg),
        "report": str(data.report_path),
        "master_db": str(data.master_db_output),
        "enriched_db": str(data.enriched_db_output),
        "enrichment_report": str(data.enrichment_report_path),
        "matching_report": str(data.matching_report_path) if data.matching_report_path is not None else None,
        "deck_config": data.selection_report,
        "source_schema": data.source_schema,
        "deck_root": common.DECK_ROOT,
        "build_id": data.build_id,
        "card_types": list(data.card_types),
        "card_settings": data.card_settings,
        "dedupe_key": data.dedupe_key,
        "total_words": _unique_word_count(data.all_entries),
        "entries_by_card_type": {card_type: len(entries) for card_type, entries in data.entries_by_card_type.items()},
        "total_cards": data.total_cards,
        "decks": data.decks_count,
        "audio_files_packaged": len(data.media_files) - len(data.static_media),
        "audio_engine": data.audio_engine,
        "audio_voices": data.audio_voices,
        "hanzi_writer_version": read_hanzi_writer_package_version(),
        "hanzi_writer_bundle": str(common.HANZI_WRITER_BUNDLE),
        "timestamp": data.timestamp,
        "deterministic_zip": data.deterministic_zip,
        "zip_datetime": data.default_zip_datetime
        if data.deterministic_zip and data.zip_generated_datetime is None
        else None,
        "zip_generated_datetime": data.zip_generated_datetime,
        "generated_audio_files_count": len(data.audio_result.generated),
        "failed_audio_generation": data.audio_result.report_failed(),
        "skipped_audio_generation": data.audio_result.report_skipped(),
        "removed_zero_length_audio_files": data.audio_result.removed_zero_length,
        "dropped_duplicate_occurrences": len(data.dropped_duplicates),
        "dropped_duplicates": list(data.dropped_duplicates),
        "missing_audio_files": list(data.missing_audio_files),
    }
