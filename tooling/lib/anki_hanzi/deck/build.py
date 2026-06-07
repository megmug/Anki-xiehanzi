"""Build the customized hanzi APKG from the typed lexicon pipeline."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import genanki

from anki_hanzi.audio.generation import AudioGenerator
from anki_hanzi.deck import DeckConfig, DeckSelection
from anki_hanzi.deck import common
from anki_hanzi.enrichment import xiehanzi as xiehanzi_enrichment
from anki_hanzi.lexicon import ENRICHED_LEXICON_SCHEMA, LexiconForm, LexiconState, LexiconWord
from anki_hanzi.lexicon.cc_cedict import load_cedict_state, load_snapshot_manifest, resolve_source_file
from anki_hanzi.rendering.meaning_html import numbered_to_display, render_meaning_group, render_meaning_html


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
        return f"[sound:{self.audio_filename_primary}][sound:{self.audio_filename_secondary}]"

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
class MeaningFormEntry:
    display_pinyin: str
    form: LexiconForm
    tags: frozenset[str]


def normalize_simplified(value: Any) -> str:
    return str(value or "").strip()


def _is_hanzi_char(char: str) -> bool:
    code = ord(char)
    return (0x4E00 <= code <= 0x9FFF) or (0x3400 <= code <= 0x4DBF) or (0x20000 <= code <= 0x2EBEF)


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
    return " / ".join(_resolve_display_pinyin_readings(form))


def _resolve_display_pinyin_readings(form: LexiconForm) -> list[str]:
    readings: list[str] = []
    for reading in form.pinyin_readings or [form.pinyin]:
        display_pinyin = numbered_to_display(reading).strip()
        if display_pinyin:
            readings.append(display_pinyin)
    return readings


def _form_selection_tags(form: LexiconForm) -> set[str]:
    return set(form.tags)


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


def _note_tags(tags: set[str]) -> tuple[str, ...]:
    return tuple(sorted(tags))


def _assert_unique_form_display_pinyin(word: LexiconWord, forms: list[LexiconForm]) -> None:
    seen: dict[str, LexiconForm] = {}
    for form in forms:
        for display_pinyin in _resolve_display_pinyin_readings(form):
            existing = seen.get(display_pinyin)
            if existing is not None and existing is not form:
                raise ValueError(
                    f"Word {word.simplified!r} has multiple forms with overlapping display Pinyin "
                    f"{display_pinyin!r}: {existing.pinyin_readings!r} and {form.pinyin_readings!r}"
                )
            seen[display_pinyin] = form


def _selected_meaning_forms(
    word: LexiconWord,
    forms: list[LexiconForm],
    mode: str,
    selection_tags: set[str],
    is_individual: bool,
) -> list[MeaningFormEntry]:
    selected_forms: list[MeaningFormEntry] = []
    for form in forms:
        display_pinyin = _resolve_display_pinyin(form)
        if not display_pinyin.strip():
            continue

        effective_tags = _form_selection_tags(form)
        if _is_form_selected(effective_tags, mode, selection_tags, is_individual):
            selected_forms.append(
                MeaningFormEntry(
                    display_pinyin=display_pinyin,
                    form=form,
                    tags=frozenset(effective_tags),
                )
            )
    return selected_forms


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
        for display_pinyin in _resolve_display_pinyin_readings(form):
            display_key = display_pinyin.strip()
            if not display_key or display_key in seen:
                continue
            seen.add(display_key)
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
    seen_meaning_entry_keys: set[tuple[str, str]] = set()
    seen_word_level_words: set[str] = set()
    selection_tags = set(selection.tags)

    for word in state.sorted_words():
        simplified = normalize_simplified(word.simplified)

        is_individual = simplified in selection.individual_simplified
        mode = selection.mode

        rendered_definition_html = render_meaning_html(word)

        forms = word.forms_in_order()
        _assert_unique_form_display_pinyin(word, forms)

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
                tags=_note_tags(_word_tags(word, forms)),
            )
            pinyin_entries.append(word_level_entry)
            write_entries.append(word_level_entry)

        word_entry_count = 0
        for meaning_form in _selected_meaning_forms(
            word=word,
            forms=forms,
            mode=mode,
            selection_tags=selection_tags,
            is_individual=is_individual,
        ):
            display_pinyin = meaning_form.display_pinyin
            entry_key = (simplified, display_pinyin)
            if entry_key in seen_meaning_entry_keys:
                continue
            seen_meaning_entry_keys.add(entry_key)

            if is_individual:
                matched_individual_simplified.add(simplified)

            audio_filename_primary, audio_filename_secondary = audio_generator.filenames_for_text(simplified)
            entry = EnrichedWordEntry(
                simplified=simplified,
                pinyin=display_pinyin,
                definition_html=rendered_definition_html,
                meaning_definition_html=render_meaning_group(word, [meaning_form.form]),
                audio_filename_primary=audio_filename_primary,
                audio_filename_secondary=audio_filename_secondary,
                tags=_note_tags(set(meaning_form.tags)),
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
        "entries_by_card_type": {card_type: len(entries) for card_type, entries in entries_by_card_type.items()},
        "matched_individual_simplified": sorted(matched_individual_simplified),
        "unmatched_individual_simplified": sorted(selection.individual_simplified - matched_individual_simplified),
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
    all_entries = _all_entries(entries_by_card_type)
    audio_entries = _audio_entries(all_entries)
    audio_jobs = audio_generator.jobs_for_texts(entry.simplified for entry in audio_entries)
    build_id = resolve_build_id()

    static_media = config.static_media()
    audio_result = audio_generator.generate(audio_jobs)

    # Build hanzi-writer JS bundle for offline Write deck usage
    write_entries = [e for e in entries_by_card_type.get("Write", []) if _is_writable_hanzi(e.simplified)]
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
    unique_words = {entry.simplified.strip() for entry in all_entries if entry.simplified.strip()}
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
