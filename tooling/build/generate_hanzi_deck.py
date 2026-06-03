#!/usr/bin/env python

"""
Build the customized hanzi APKG from the typed lexicon pipeline.

The generator builds the CC-CEDICT state, enriches it with hanzi deck-source
data in memory, and uses the shared deck build helpers in
`tooling/lib/anki_hanzi/deck/common.py` for templates, media, and stable Anki
ids.

`deck_inputs/deck_config.json` controls which tagged hanzi forms are emitted
as notes, which card types are generated, and optional per-card display
settings that are baked into the templates.

Run from the repository root inside the Nix shell:

    nix-shell --run "python tooling/build/generate_hanzi_deck.py"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import genanki

from anki_hanzi.audio.generation import AudioGenerator
from anki_hanzi.deck import DeckConfig
from anki_hanzi.deck import common
from anki_hanzi.enrichment.hanzi import (
    DEFAULT_FREQUENCY_LIST,
    DEFAULT_HSK_DATA_DIR,
    DEFAULT_MASTER_DB,
    DEFAULT_OUTPUT as DEFAULT_ENRICHED_DB_OUTPUT,
    DEFAULT_REPORT as DEFAULT_ENRICHMENT_REPORT,
    HANZI_DEDUPE_KEY,
    enrich_state,
)
from anki_hanzi.lexicon import ENRICHED_LEXICON_SCHEMA, LexiconForm, LexiconState, LexiconWord
from anki_hanzi.lexicon.cc_cedict import load_cedict_state, load_snapshot_manifest, resolve_source_file
from anki_hanzi.rendering.meaning_html import numbered_to_display, render_meaning_group, render_meaning_html


DEFAULT_SNAPSHOT_MANIFEST = Path("deck_inputs/cc-cedict/snapshot.json")
DEFAULT_DECK_CONFIG = Path("deck_inputs/deck_config.json")
DEFAULT_AUDIO_EXCEPTIONS = Path("deck_inputs/audio_generation_exceptions.json")
DEFAULT_REPORT_PATH = Path("build_reports/generate_hanzi_report.json")
DEFAULT_GENANKI_TIMESTAMP = 1779251987.6
DEFAULT_GENERATED_ZIP_DATETIME = (2026, 5, 20, 6, 39, 48)
DEFAULT_ZIP_DATETIME = (1980, 1, 1, 0, 0, 0)
GENERATED_ZIP_MEMBERS = {"collection.anki2", "media"}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True)
class EnrichedWordEntry:
    simplified: str
    pinyin: str
    definition_html: str
    meaning_definition_html: str
    audio_filename_primary: str
    audio_filename_secondary: str
    note_pinyin: str | None = None
    tags: tuple[str, ...] = ()

    @property
    def audio_ref(self) -> str:
        if not self.audio_filename_primary and not self.audio_filename_secondary:
            return ""
        return (
            f"[sound:{self.audio_filename_primary}]"
            f"[sound:{self.audio_filename_secondary}]"
        )

    @property
    def audio_filenames(self) -> tuple[str, str]:
        return (self.audio_filename_primary, self.audio_filename_secondary)

    def fields(self, card_type: str, build_id: str) -> list[str]:
        note_pinyin = self.pinyin if self.note_pinyin is None else self.note_pinyin
        note_id = common.stable_note_id(card_type, self.simplified, note_pinyin)
        meaning_html = self.meaning_definition_html if card_type == "Meaning" else self.definition_html
        return [
            self.simplified,
            self.pinyin,
            meaning_html,
            self.audio_ref,
            note_id,
            build_id,
        ]


@dataclass(frozen=True)
class DeckSelection:
    mode: str
    tags: tuple[str, ...]
    individual_simplified: frozenset[str]
    config_path: str | None
    config_found: bool

    def report(self) -> dict[str, Any]:
        return {
            "config_path": self.config_path,
            "config_found": self.config_found,
            "mode": self.mode,
            "tags": list(self.tags),
            "individual_simplified": sorted(self.individual_simplified),
        }


@dataclass(frozen=True)
class ReadingGroup:
    display_pinyin: str
    forms: tuple[LexiconForm, ...]
    tags: frozenset[str]


def normalize_simplified(value: Any) -> str:
    return str(value or "").strip()


def parse_simplified_list(value: Any, field_name: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if not isinstance(value, list):
        raise ValueError(f"deck config selection.{field_name} must be a list")
    return frozenset(
        simplified
        for simplified in (normalize_simplified(item) for item in value)
        if simplified
    )


def load_deck_selection(config_path: Path | None) -> DeckSelection:
    if config_path is None or not config_path.exists():
        raise ValueError("deck config file is required but not found")

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    selection = raw.get("selection")
    if selection is None:
        raise ValueError("deck config must define a 'selection' object")
    if not isinstance(selection, dict):
        raise ValueError("deck config selection must be an object")

    tags_raw = selection.get("tags", [])
    if isinstance(tags_raw, str):
        tags = (tags_raw,)
    elif isinstance(tags_raw, list):
        tags = tuple(str(t) for t in tags_raw)
    else:
        tags = ()

    return DeckSelection(
        mode=str(selection.get("mode", "")),
        tags=tags,
        individual_simplified=parse_simplified_list(
            selection.get("individual_simplified", []),
            "individual_simplified",
        ),
        config_path=str(config_path),
        config_found=True,
    )


def _is_hanzi_char(char: str) -> bool:
    code = ord(char)
    return (
        (0x4E00 <= code <= 0x9FFF)
        or (0x3400 <= code <= 0x4DBF)
        or (0x20000 <= code <= 0x2EBEF)
    )


def _has_hanzi_writer_data(char: str) -> bool:
    if not _is_hanzi_char(char):
        return False
    data_file = common.HANZI_WRITER_DATA_DIR / f"{char}.json"
    return data_file.exists()


def _is_writable_hanzi(text: str) -> bool:
    if not text:
        return False
    return all(_has_hanzi_writer_data(c) for c in text)


def build_decks(
    config: DeckConfig,
    models: dict[str, genanki.Model],
    entries_by_card_type: dict[str, list[EnrichedWordEntry]],
    build_id: str,
) -> list[genanki.Deck]:
    decks: list[genanki.Deck] = []

    for card_type in config.card_types:
        card_entries = entries_by_card_type.get(card_type, [])
        if card_type == "Write":
            card_entries = [e for e in card_entries if _is_writable_hanzi(e.simplified)]
        decks.append(
            common.create_deck(
                deck_name=f"{common.DECK_ROOT}::{card_type}",
                card_type=card_type,
                model=models[card_type],
                entries=card_entries,
                build_id=build_id,
            )
        )

    return decks


def resolve_build_id() -> str:
    env_build_id = os.environ.get("ANKI_HANZI_BUILD_ID", "").strip()
    if env_build_id:
        return env_build_id
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=7", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def build_hanzi_writer_bundle(
    write_entries: list[EnrichedWordEntry],
    output_path: Path,
) -> str:
    """Build a single JS file with all hanzi-writer data needed by the Write deck.

    Returns the path to the generated file.
    """
    unique_chars: set[str] = set()
    for entry in write_entries:
        for char in entry.simplified:
            if _has_hanzi_writer_data(char):
                unique_chars.add(char)

    data: dict[str, Any] = {}
    for char in sorted(unique_chars):
        data_file = common.HANZI_WRITER_DATA_DIR / f"{char}.json"
        if data_file.exists():
            data[char] = json.loads(data_file.read_text(encoding="utf-8"))

    bundle_js = "window.hanziWriterData = " + json.dumps(data, ensure_ascii=False) + ";\n"
    output_path.write_text(bundle_js, encoding="utf-8")
    return str(output_path)


def _resolve_display_pinyin(form: LexiconForm) -> str:
    return numbered_to_display(form.pinyin)


def _effective_form_tags(word: LexiconWord, form: LexiconForm) -> set[str]:
    form_tags = set(form.tags)
    fallback_tags = set(word.tags)
    return form_tags or fallback_tags


def _is_form_selected(
    effective_tags: set[str],
    mode: str,
    selection_tags: set[str],
    is_individual: bool,
) -> bool:
    if is_individual:
        return True
    if mode == "all":
        return True
    if mode == "tagged":
        return bool(effective_tags & selection_tags)
    return False


def _selected_reading_groups(
    word: LexiconWord,
    forms: list[LexiconForm],
    mode: str,
    selection_tags: set[str],
    is_individual: bool,
) -> list[ReadingGroup]:
    groups: dict[str, list[LexiconForm]] = {}
    display_by_key: dict[str, str] = {}
    selected_display_by_key: dict[str, str] = {}

    for form in forms:
        display_pinyin = _resolve_display_pinyin(form)
        normalized_pinyin = common.normalized_note_pinyin(display_pinyin)
        if not normalized_pinyin:
            continue

        groups.setdefault(normalized_pinyin, []).append(form)
        display_by_key.setdefault(normalized_pinyin, display_pinyin)

        effective_tags = _effective_form_tags(word, form)
        if _is_form_selected(effective_tags, mode, selection_tags, is_individual):
            selected_display_by_key.setdefault(normalized_pinyin, display_pinyin)

    reading_groups: list[ReadingGroup] = []
    for normalized_pinyin, group_forms in groups.items():
        if normalized_pinyin not in selected_display_by_key:
            continue

        group_tags: set[str] = set()
        for form in group_forms:
            group_tags.update(_effective_form_tags(word, form))

        reading_groups.append(ReadingGroup(
            display_pinyin=selected_display_by_key.get(normalized_pinyin)
            or display_by_key[normalized_pinyin],
            forms=tuple(group_forms),
            tags=frozenset(group_tags),
        ))
    return reading_groups


def _word_tags(word: LexiconWord, forms: list[LexiconForm]) -> set[str]:
    tags = set(word.tags)
    for form in forms:
        tags.update(form.tags)
    return tags


def _selected_word_forms(
    word: LexiconWord,
    forms: list[LexiconForm],
    mode: str,
    selection_tags: set[str],
    is_individual: bool,
) -> list[LexiconForm]:
    if is_individual or mode == "all":
        return forms

    if mode != "tagged":
        return []

    word_tags = set(word.tags)
    for form in forms:
        if (word_tags | set(form.tags)) & selection_tags:
            return forms
    return []


def _display_pinyin_readings(forms: list[LexiconForm]) -> str:
    readings: list[str] = []
    seen: set[str] = set()
    for form in forms:
        display_pinyin = _resolve_display_pinyin(form)
        normalized_pinyin = common.normalized_note_pinyin(display_pinyin)
        if not normalized_pinyin or normalized_pinyin in seen:
            continue
        seen.add(normalized_pinyin)
        readings.append(display_pinyin)
    return " / ".join(readings)


def _all_entries(entries_by_card_type: dict[str, list[EnrichedWordEntry]]) -> list[EnrichedWordEntry]:
    entries: list[EnrichedWordEntry] = []
    for card_type_entries in entries_by_card_type.values():
        entries.extend(card_type_entries)
    return entries


def _audio_entries(entries: list[EnrichedWordEntry]) -> list[EnrichedWordEntry]:
    deduped: list[EnrichedWordEntry] = []
    seen: set[str] = set()
    for entry in entries:
        word = entry.simplified.strip()
        if not word or word in seen:
            continue
        seen.add(word)
        deduped.append(entry)
    return deduped


def build_entries_from_state(
    state: LexiconState,
    selection: DeckSelection,
    audio_generator: AudioGenerator,
) -> tuple[dict[str, list[EnrichedWordEntry]], dict[str, Any]]:
    meaning_entries: list[EnrichedWordEntry] = []
    pinyin_entries: list[EnrichedWordEntry] = []
    write_entries: list[EnrichedWordEntry] = []
    matched_individual_simplified: set[str] = set()
    rendered_meaning_html_used = 0
    seen_entry_keys: set[tuple[str, str]] = set()
    seen_word_level_words: set[str] = set()
    selection_tags = set(selection.tags)

    for word in state.sorted_words():
        simplified = normalize_simplified(word.simplified)

        is_individual = simplified in selection.individual_simplified
        mode = selection.mode

        rendered_definition_html = render_meaning_html(word)

        forms = word.forms_in_order()

        selected_word_forms = _selected_word_forms(
            word=word,
            forms=forms,
            mode=mode,
            selection_tags=selection_tags,
            is_individual=is_individual,
        )
        display_readings = _display_pinyin_readings(selected_word_forms)
        if display_readings and simplified not in seen_word_level_words:
            seen_word_level_words.add(simplified)
            audio_filename_primary, audio_filename_secondary = audio_generator.filenames_for_text(simplified)
            word_level_entry = EnrichedWordEntry(
                simplified=simplified,
                pinyin=display_readings,
                definition_html=rendered_definition_html,
                meaning_definition_html=rendered_definition_html,
                audio_filename_primary=audio_filename_primary,
                audio_filename_secondary=audio_filename_secondary,
                note_pinyin="",
                tags=tuple(sorted(_word_tags(word, forms) | {"source:xiehanzi"})),
            )
            pinyin_entries.append(word_level_entry)
            write_entries.append(word_level_entry)

        word_entry_count = 0
        for reading_group in _selected_reading_groups(
            word=word,
            forms=forms,
            mode=mode,
            selection_tags=selection_tags,
            is_individual=is_individual,
        ):
            display_pinyin = reading_group.display_pinyin
            entry_key = (simplified, common.normalized_note_pinyin(display_pinyin))
            if not entry_key[1] or entry_key in seen_entry_keys:
                continue
            seen_entry_keys.add(entry_key)

            if is_individual:
                matched_individual_simplified.add(simplified)

            audio_filename_primary, audio_filename_secondary = audio_generator.filenames_for_text(simplified)
            entry = EnrichedWordEntry(
                simplified=simplified,
                pinyin=display_pinyin,
                definition_html=rendered_definition_html,
                meaning_definition_html=render_meaning_group(word, list(reading_group.forms)),
                audio_filename_primary=audio_filename_primary,
                audio_filename_secondary=audio_filename_secondary,
                tags=tuple(sorted(set(reading_group.tags) | {"source:xiehanzi"})),
            )
            meaning_entries.append(entry)
            word_entry_count += 1

        if word_entry_count:
            rendered_meaning_html_used += 1

    entries_by_card_type = {
        "Meaning": sorted(meaning_entries, key=lambda entry: entry.simplified),
        "Pinyin": sorted(pinyin_entries, key=lambda entry: entry.simplified),
        "Write": sorted(write_entries, key=lambda entry: entry.simplified),
    }

    selection_report = {
        **selection.report(),
        "entries_by_card_type": {
            card_type: len(entries)
            for card_type, entries in entries_by_card_type.items()
        },
        "matched_individual_simplified": sorted(matched_individual_simplified),
        "unmatched_individual_simplified": sorted(
            selection.individual_simplified - matched_individual_simplified
        ),
        "meaning_html": {
            "rendered_from_data": rendered_meaning_html_used,
        },
    }

    return entries_by_card_type, selection_report


def collect_media(entries: list[EnrichedWordEntry], static_media: list[str]) -> tuple[list[str], list[str]]:
    media = list(static_media)
    missing_audio: list[str] = []
    seen_media_names = {Path(path).name for path in media}

    for entry in entries:
        for filename in entry.audio_filenames:
            if not filename:
                continue
            path = common.EXTRA_AUDIO_DIR / filename
            if path.exists():
                if filename not in seen_media_names:
                    seen_media_names.add(filename)
                    media.append(str(path))
            else:
                missing_audio.append(filename)

    return media, sorted(set(missing_audio))


def copy_zip_info(reference_info: zipfile.ZipInfo, filename: str | None = None) -> zipfile.ZipInfo:
    output_info = zipfile.ZipInfo(filename or reference_info.filename, reference_info.date_time)
    output_info.compress_type = reference_info.compress_type
    output_info.external_attr = reference_info.external_attr
    output_info.internal_attr = reference_info.internal_attr
    output_info.comment = reference_info.comment
    output_info.extra = reference_info.extra
    output_info.create_system = reference_info.create_system
    return output_info


def normalize_zip_file(source: Path, output: Path, zip_datetime: tuple[int, int, int, int, int, int]) -> None:
    with zipfile.ZipFile(source) as source_zip, zipfile.ZipFile(output, "w") as output_zip:
        for info in source_zip.infolist():
            data = source_zip.read(info.filename)
            output_info = copy_zip_info(info)
            output_info.date_time = zip_datetime
            output_info.extra = b""
            output_zip.writestr(output_info, data)


def rewrite_generated_zip_datetimes(
    source: Path,
    output: Path,
    generated_datetime: tuple[int, int, int, int, int, int],
) -> None:
    with zipfile.ZipFile(source) as source_zip, zipfile.ZipFile(output, "w") as output_zip:
        for info in source_zip.infolist():
            data = source_zip.read(info.filename)
            output_info = copy_zip_info(info)
            if info.filename in GENERATED_ZIP_MEMBERS:
                output_info.date_time = generated_datetime
            output_zip.writestr(output_info, data)


def parse_zip_datetime(value: str) -> tuple[int, int, int, int, int, int]:
    try:
        date_part, time_part = value.replace("T", " ").split()
        year, month, day = (int(part) for part in date_part.split("-"))
        hour, minute, second = (int(part) for part in time_part.split(":"))
    except Exception as exc:
        raise argparse.ArgumentTypeError(
            "Expected datetime in YYYY-MM-DDTHH:MM:SS format"
        ) from exc
    return year, month, day, hour, minute, second


def write_package(
    package: genanki.Package,
    output_apkg: Path,
    timestamp: float | None,
    deterministic_zip: bool,
    zip_generated_datetime: tuple[int, int, int, int, int, int] | None,
) -> None:
    if zip_generated_datetime is None and not deterministic_zip:
        if timestamp is None:
            package.write_to_file(str(output_apkg))
        else:
            package.write_to_file(str(output_apkg), timestamp=timestamp)
        return

    with tempfile.NamedTemporaryFile(suffix=".apkg", delete=False) as handle:
        temporary_path = Path(handle.name)

    try:
        if timestamp is None:
            package.write_to_file(str(temporary_path))
        else:
            package.write_to_file(str(temporary_path), timestamp=timestamp)

        if zip_generated_datetime is not None:
            rewrite_generated_zip_datetimes(
                source=temporary_path,
                output=output_apkg,
                generated_datetime=zip_generated_datetime,
            )
        else:
            normalize_zip_file(temporary_path, output_apkg, DEFAULT_ZIP_DATETIME)
    finally:
        temporary_path.unlink(missing_ok=True)


def build_enriched_state(
    snapshot_manifest: Path,
    source_file: Path | None,
    master_db_output: Path,
    enriched_db_output: Path,
    enrichment_report_path: Path,
    hsk_data_dir: Path,
    frequency_list: Path,
) -> LexiconState:
    manifest = load_snapshot_manifest(snapshot_manifest)
    resolved_source_file = resolve_source_file(snapshot_manifest, manifest, source_file)
    if not resolved_source_file.exists():
        raise FileNotFoundError(f"missing CC-CEDICT source file: {resolved_source_file}")

    state = load_cedict_state(
        source_file=resolved_source_file,
        url=manifest["source_url"],
        expected_sha256=manifest["sha256"],
    )
    state.sort_forms_by_pinyin()
    write_json(master_db_output, state.to_master_json())

    enrich_state(
        master_state=state,
        input_label=str(master_db_output),
        output_path=enriched_db_output,
        report_path=enrichment_report_path,
        hsk_data_dir=hsk_data_dir,
        frequency_list_path=frequency_list,
    )
    return state


def build_package(
    snapshot_manifest: Path,
    source_file: Path | None,
    master_db_output: Path,
    enriched_db_output: Path,
    enrichment_report_path: Path,
    hsk_data_dir: Path,
    frequency_list: Path,
    deck_config_path: Path | None,
    output_apkg: Path,
    report_path: Path,
    timestamp: float | None,
    deterministic_zip: bool,
    zip_generated_datetime: tuple[int, int, int, int, int, int] | None,
) -> dict[str, Any]:
    config = common.load_deck_config(deck_config_path)
    audio_generator = AudioGenerator(
        config.audio.engine,
        exceptions_path=DEFAULT_AUDIO_EXCEPTIONS,
    )
    selection = load_deck_selection(deck_config_path)
    state = build_enriched_state(
        snapshot_manifest=snapshot_manifest,
        source_file=source_file,
        master_db_output=master_db_output,
        enriched_db_output=enriched_db_output,
        enrichment_report_path=enrichment_report_path,
        hsk_data_dir=hsk_data_dir,
        frequency_list=frequency_list,
    )
    entries_by_card_type, selection_report = build_entries_from_state(
        state,
        selection,
        audio_generator,
    )
    all_entries = _all_entries(entries_by_card_type)
    audio_entries = _audio_entries(all_entries)
    audio_jobs = audio_generator.jobs_for_texts(entry.simplified for entry in audio_entries)
    build_id = resolve_build_id()

    static_media = config.static_media()
    audio_result = audio_generator.generate(audio_jobs)

    # Build hanzi-writer JS bundle for offline Write deck usage
    write_entries = [
        e for e in entries_by_card_type.get("Write", [])
        if _is_writable_hanzi(e.simplified)
    ]
    hw_bundle_path = Path(common.EXTRA_AUDIO_DIR) / "hanzi-writer-data.js"
    hw_bundle_path.parent.mkdir(parents=True, exist_ok=True)
    build_hanzi_writer_bundle(write_entries, hw_bundle_path)

    models = common.create_models(config, hw_bundle_path if hw_bundle_path.exists() else None)
    decks = build_decks(config, models, entries_by_card_type, build_id)

    media_files, missing_audio = collect_media(audio_entries, static_media)

    package = genanki.Package(decks, media_files=media_files)
    write_package(
        package=package,
        output_apkg=output_apkg,
        timestamp=timestamp,
        deterministic_zip=deterministic_zip,
        zip_generated_datetime=zip_generated_datetime,
    )

    total_cards = sum(len(d.notes) for d in decks)
    unique_words = {
        entry.simplified.strip()
        for entry in all_entries
        if entry.simplified.strip()
    }
    report = {
        "output": str(output_apkg),
        "report": str(report_path),
        "master_db": str(master_db_output),
        "enriched_db": str(enriched_db_output),
        "enrichment_report": str(enrichment_report_path),
        "deck_config": selection_report,
        "source_schema": ENRICHED_LEXICON_SCHEMA,
        "deck_root": common.DECK_ROOT,
        "build_id": build_id,
        "card_types": list(config.card_types),
        "card_settings": config.card_settings,
        "dedupe_key": HANZI_DEDUPE_KEY,
        "total_words": len(unique_words),
        "entries_by_card_type": {
            card_type: len(entries)
            for card_type, entries in entries_by_card_type.items()
        },
        "total_cards": total_cards,
        "decks": len(decks),
        "audio_files_packaged": len(media_files) - len(static_media),
        "audio_engine": config.audio.engine,
        "audio_voices": audio_generator.voice_report(),
        "hanzi_writer_version": common.read_hanzi_writer_package_version(),
        "hanzi_writer_bundle": str(common.HANZI_WRITER_BUNDLE),
        "timestamp": timestamp,
        "deterministic_zip": deterministic_zip,
        "zip_datetime": DEFAULT_ZIP_DATETIME if deterministic_zip and zip_generated_datetime is None else None,
        "zip_generated_datetime": zip_generated_datetime,
        "generated_audio_files_count": len(audio_result.generated),
        "failed_audio_generation": audio_result.report_failed(),
        "skipped_audio_generation": audio_result.report_skipped(),
        "removed_zero_length_audio_files": audio_result.removed_zero_length,
        "dropped_duplicate_occurrences": len(state.hanzi_dropped_duplicates),
        "dropped_duplicates": list(state.hanzi_dropped_duplicates),
        "missing_audio_files": missing_audio,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot-manifest",
        type=Path,
        default=DEFAULT_SNAPSHOT_MANIFEST,
        help="Snapshot manifest with the pinned CC-CEDICT source filename, SHA256, and source URL.",
    )
    parser.add_argument("--source-file", type=Path, default=None, help="Optional pinned CC-CEDICT text file override.")
    parser.add_argument("--master-db-output", type=Path, default=DEFAULT_MASTER_DB, help="Diagnostic master JSON output.")
    parser.add_argument(
        "--enriched-db-output",
        type=Path,
        default=DEFAULT_ENRICHED_DB_OUTPUT,
        help="Diagnostic enriched JSON output.",
    )
    parser.add_argument(
        "--enrichment-report",
        type=Path,
        default=DEFAULT_ENRICHMENT_REPORT,
        help="Diagnostic enrichment report JSON output.",
    )
    parser.add_argument("--hsk-data-dir", type=Path, default=DEFAULT_HSK_DATA_DIR, help="Prepared hanzi HSK TSV directory.")
    parser.add_argument("--frequency-list", type=Path, default=DEFAULT_FREQUENCY_LIST, help="Simplified word frequency list sorted by usage.")
    parser.add_argument("--config", type=Path, default=DEFAULT_DECK_CONFIG, help="Deck selection JSON config.")
    parser.add_argument("--output", type=Path, default=None, help="Output APKG path.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH, help="Output report JSON path.")
    parser.add_argument(
        "--timestamp",
        type=float,
        default=DEFAULT_GENANKI_TIMESTAMP,
        help="Fixed genanki timestamp for hermetic builds.",
    )
    parser.add_argument(
        "--deterministic-zip",
        action="store_true",
        help="Rewrite the APKG zip with fixed member timestamps for byte-reproducible output.",
    )
    parser.add_argument(
        "--zip-generated-datetime",
        type=parse_zip_datetime,
        default=DEFAULT_GENERATED_ZIP_DATETIME,
        help="Set ZIP timestamps for generated members collection.anki2 and media. Format: YYYY-MM-DDTHH:MM:SS.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.snapshot_manifest.exists():
        print(f"missing snapshot manifest: {args.snapshot_manifest}")
        return 2
    if not args.hsk_data_dir.exists():
        print(f"missing hanzi HSK data dir: {args.hsk_data_dir}")
        return 2
    if not args.frequency_list.exists():
        print(f"missing frequency list: {args.frequency_list}")
        return 2

    output_apkg = args.output
    if output_apkg is None:
        output_apkg = common.OUTPUT_APKG

    report = build_package(
        snapshot_manifest=args.snapshot_manifest,
        source_file=args.source_file,
        master_db_output=args.master_db_output,
        enriched_db_output=args.enriched_db_output,
        enrichment_report_path=args.enrichment_report,
        hsk_data_dir=args.hsk_data_dir,
        frequency_list=args.frequency_list,
        deck_config_path=args.config,
        output_apkg=output_apkg,
        report_path=args.report,
        timestamp=args.timestamp,
        deterministic_zip=args.deterministic_zip,
        zip_generated_datetime=args.zip_generated_datetime,
    )
    console_report = {
        key: value
        for key, value in report.items()
        if key != "dropped_duplicates"
    }
    print(json.dumps(console_report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
