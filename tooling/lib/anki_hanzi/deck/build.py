"""Build the customized hanzi APKG from the typed lexicon pipeline."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import genanki

from anki_hanzi.audio.generation import AudioGenerator
from anki_hanzi.deck import DeckConfig
from anki_hanzi.deck import common
from anki_hanzi.deck.entries import (
    EnrichedWordEntry,
    build_entries_from_state,
    flatten_entries_by_card_type,
    unique_audio_entries,
)
from anki_hanzi.deck.hanzi_writer import build_hanzi_writer_bundle, is_writable_hanzi
from anki_hanzi.enrichment import xiehanzi as xiehanzi_enrichment
from anki_hanzi.lexicon import ENRICHED_LEXICON_SCHEMA, LexiconState
from anki_hanzi.lexicon.cc_cedict import load_cedict_state, load_snapshot_manifest, resolve_source_file


DEFAULT_FREQUENCY_LIST = xiehanzi_enrichment.DEFAULT_FREQUENCY_LIST
DEFAULT_HSK_DATA_DIR = xiehanzi_enrichment.DEFAULT_HSK_DATA_DIR
DEFAULT_MASTER_DB = xiehanzi_enrichment.DEFAULT_MASTER_DB
DEFAULT_MATCHING_REPORT = xiehanzi_enrichment.DEFAULT_MATCHING_REPORT
DEFAULT_ENRICHED_DB_OUTPUT = xiehanzi_enrichment.DEFAULT_OUTPUT
DEFAULT_ENRICHMENT_REPORT = xiehanzi_enrichment.DEFAULT_REPORT
HANZI_DEDUPE_KEY = xiehanzi_enrichment.HANZI_DEDUPE_KEY
enrich_state = xiehanzi_enrichment.enrich_state

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
            card_entries = [entry for entry in card_entries if is_writable_hanzi(entry.simplified)]
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
    matching_report_path: Path | None,
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
        matching_report_path=matching_report_path,
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
    matching_report_path: Path | None,
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
    if not config.selection.config_found:
        raise ValueError("deck config file is required but not found")
    audio_generator = AudioGenerator(
        config.audio.engine,
        exceptions_path=DEFAULT_AUDIO_EXCEPTIONS,
    )
    state = build_enriched_state(
        snapshot_manifest=snapshot_manifest,
        source_file=source_file,
        master_db_output=master_db_output,
        enriched_db_output=enriched_db_output,
        enrichment_report_path=enrichment_report_path,
        matching_report_path=matching_report_path,
        hsk_data_dir=hsk_data_dir,
        frequency_list=frequency_list,
    )
    entries_by_card_type, selection_report = build_entries_from_state(
        state,
        config.selection,
        audio_generator,
    )
    all_deck_entries = flatten_entries_by_card_type(entries_by_card_type)
    audio_deck_entries = unique_audio_entries(all_deck_entries)
    audio_jobs = audio_generator.jobs_for_texts(entry.simplified for entry in audio_deck_entries)
    build_id = resolve_build_id()

    static_media = config.static_media()
    audio_result = audio_generator.generate(audio_jobs)

    # Build hanzi-writer JS bundle for offline Write deck usage
    write_entries = [entry for entry in entries_by_card_type.get("Write", []) if is_writable_hanzi(entry.simplified)]
    hw_bundle_path = Path(common.EXTRA_AUDIO_DIR) / "hanzi-writer-data.js"
    hw_bundle_path.parent.mkdir(parents=True, exist_ok=True)
    build_hanzi_writer_bundle(write_entries, hw_bundle_path)

    models = common.create_models(config, hw_bundle_path if hw_bundle_path.exists() else None)
    decks = build_decks(config, models, entries_by_card_type, build_id)

    media_files, missing_audio = collect_media(audio_deck_entries, static_media)

    package = genanki.Package(decks, media_files=media_files)
    write_package(
        package=package,
        output_apkg=output_apkg,
        timestamp=timestamp,
        deterministic_zip=deterministic_zip,
        zip_generated_datetime=zip_generated_datetime,
    )

    total_cards = sum(len(d.notes) for d in decks)
    unique_words = {entry.simplified.strip() for entry in all_deck_entries if entry.simplified.strip()}
    report = {
        "output": str(output_apkg),
        "report": str(report_path),
        "master_db": str(master_db_output),
        "enriched_db": str(enriched_db_output),
        "enrichment_report": str(enrichment_report_path),
        "matching_report": str(matching_report_path) if matching_report_path is not None else None,
        "deck_config": selection_report,
        "source_schema": ENRICHED_LEXICON_SCHEMA,
        "deck_root": common.DECK_ROOT,
        "build_id": build_id,
        "card_types": list(config.card_types),
        "card_settings": config.card_settings,
        "dedupe_key": HANZI_DEDUPE_KEY,
        "total_words": len(unique_words),
        "entries_by_card_type": {card_type: len(entries) for card_type, entries in entries_by_card_type.items()},
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
    write_json(report_path, report)
    return report
