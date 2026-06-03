"""
Enrich the CC-CEDICT lexicon state with hanzi deck-source data.

This module is part of the in-memory APKG build pipeline:

    CC-CEDICT source + hanzi TSV files -> enriched LexiconState -> APKG

The optional enriched JSON and report are diagnostic build artifacts.
"""

from __future__ import annotations

import csv
import html
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dragonmapper import transcriptions

from anki_hanzi.lexicon import (
    LexiconBaseSnapshot,
    LexiconEnrichmentMetadata,
    LexiconForm,
    LexiconState,
    LexiconWord,
)


DEFAULT_MASTER_DB = Path("master_db_output/cc_cedict_master.json")
DEFAULT_OUTPUT = Path("master_db_output/cc_cedict_hanzi_enriched.json")
DEFAULT_REPORT = Path("master_db_output/hanzi_enrichment_report.json")
DEFAULT_DECK_INPUTS_DIR = Path("deck_inputs")
DEFAULT_HSK_DATA_DIR = DEFAULT_DECK_INPUTS_DIR / "hsk-3.0-words-list/New HSK (2025)/Anki xiehanzi"
DEFAULT_FREQUENCY_LIST = (
    DEFAULT_DECK_INPUTS_DIR
    / "hsk-3.0-words-list/Scripts and data/blog_lit_news_tech_weibo_freq.release_sorted.txt"
)
TOP_FREQUENCY_THRESHOLDS = (500, 2500, 10000)
HANZI_DEDUPE_KEY = "Simplified + normalized Pinyin"

# Corrections for known pinyin defects in the xiehanzi TSV column. These keep
# the read-only source files unchanged while allowing the matcher to target the
# intended CC-CEDICT form.
HANZI_PINYIN_OVERRIDES = {
    ("标致", "7-9"): "biao1zhi5",
    ("疼爱", "7-9"): "teng2ai4",
    ("脚踏实地", "7-9"): "jiao3ta4shi2di4",
    ("蹊跷", "7-9"): "qi1qiao1",
}

LEVELS = ["1", "2", "3", "4", "5", "6", "7-9"]
HANZI_FIELDS = [
    "Simplified",
    "Traditional",
    "Pinyin",
    "Zhuyin",
    "Level",
    "PoS",
    "Frequency",
    "Meaning HTML",
]


def normalize_field(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = unicodedata.normalize("NFC", value)
    return re.sub(r"\s+", "", value).strip().lower()


def dedupe_key(entry: dict[str, Any]) -> tuple[str, str]:
    return normalize_field(entry["simplified"]), normalize_field(entry["pinyin"])


def printable_key(key: tuple[str, str]) -> str:
    return "::".join(key)


PINYIN_SEPARATOR_RE = re.compile(r"[\s'’\-·]+")


@dataclass(frozen=True)
class PinyinReading:
    spaced: str
    compact: str
    lower_compact: str


def normalize_pinyin_u_variants(value: str) -> str:
    return (
        value.replace("ü", "v")
        .replace("Ü", "V")
        .replace("u:", "v")
        .replace("U:", "V")
    )


def numbered_pinyin_part(value: str) -> str:
    value = unicodedata.normalize("NFC", value.strip())
    if not value:
        return ""
    if re.search(r"\d", value):
        numbered = value
    else:
        try:
            numbered = transcriptions.accented_to_numbered(value)
        except ValueError:
            numbered = value
    return normalize_pinyin_u_variants(numbered)


def canonical_pinyin_readings(value: str) -> list[PinyinReading]:
    readings: list[PinyinReading] = []
    for part in re.split(r"/", value or ""):
        numbered = numbered_pinyin_part(part)
        if not numbered:
            continue

        spaced = PINYIN_SEPARATOR_RE.sub(" ", numbered).strip()
        spaced = re.sub(r"\s+", " ", spaced)
        compact = spaced.replace(" ", "")
        if compact:
            readings.append(PinyinReading(
                spaced=spaced,
                compact=compact,
                lower_compact=compact.lower(),
            ))
    return readings


def normalize_pinyin_lookup_key(value: str) -> str:
    readings = canonical_pinyin_readings(value)
    return readings[0].lower_compact if readings else ""


def pinyin_lookup_keys(value: str) -> list[str]:
    keys: list[str] = []
    for reading in canonical_pinyin_readings(value):
        key = reading.lower_compact
        if key not in keys:
            keys.append(key)
    return keys


def pinyin_lookup_key(value: str) -> str:
    keys = pinyin_lookup_keys(value)
    return keys[0] if keys else ""


def toneless_pinyin_lookup_key(value: str) -> str:
    return re.sub(r"\d", "", pinyin_lookup_key(value))


def toneless_pinyin_lookup_keys(value: str) -> list[str]:
    keys: list[str] = []
    for key in pinyin_lookup_keys(value):
        toneless_key = re.sub(r"\d", "", key)
        if toneless_key and toneless_key not in keys:
            keys.append(toneless_key)
    return keys


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


def entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "simplified": entry["simplified"],
        "traditional": entry["traditional"],
        "pinyin": entry["pinyin"],
        "zhuyin": entry["zhuyin"],
        "deck_level": entry["deck_level"],
        "raw_level": entry["raw_level"],
        "source": entry["source"],
    }
    if entry.get("raw_pinyin") and entry["raw_pinyin"] != entry["pinyin"]:
        summary["raw_pinyin"] = entry["raw_pinyin"]
    return summary


def make_entry(
    row: list[str],
    source: str,
    source_file: Path,
    row_number: int,
    deck_level: str,
) -> dict[str, Any]:
    if len(row) < len(HANZI_FIELDS):
        raise ValueError(f"Expected at least 8 TSV columns in {source_file}:{row_number}, got {len(row)}: {row!r}")

    simplified = row[0]
    traditional = row[1]
    raw_pinyin = row[2]
    pinyin = HANZI_PINYIN_OVERRIDES.get((simplified, deck_level), raw_pinyin)
    zhuyin = row[3]
    raw_level = row[4]
    pos = row[5]
    frequency_text = row[6]
    meaning_html = row[7]

    tags = ["source:xiehanzi", *level_tags(deck_level, raw_level)]
    return {
        "simplified": simplified,
        "traditional": traditional,
        "pinyin": pinyin,
        "raw_pinyin": raw_pinyin,
        "zhuyin": zhuyin,
        "deck_level": deck_level,
        "raw_level": raw_level,
        "pos": pos,
        "frequency": parse_frequency(frequency_text),
        "meaning_html": meaning_html,
        "audio_filename": f"cmn-{simplified}.mp3",
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


def build_state_word_index(state: LexiconState) -> dict[str, LexiconWord]:
    index: dict[str, LexiconWord] = {}
    for word in state.sorted_words():
        key = normalize_field(word.simplified)
        if key:
            index[key] = word
    return index


LI_RE = re.compile(r"<li>(.*?)</li>", re.IGNORECASE | re.DOTALL)


def strip_html_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def definitions_from_meaning_html(value: str) -> list[str]:
    parts = LI_RE.findall(value or "") or [value]
    definitions: list[str] = []
    seen: set[str] = set()

    for part in parts:
        definition = strip_html_text(part)
        if not definition or definition in seen:
            continue
        definitions.append(definition)
        seen.add(definition)

    return definitions


def build_synthetic_words(missing_entries: list[dict[str, Any]]) -> list[LexiconWord]:
    by_simplified: dict[str, LexiconWord] = {}

    for entry in missing_entries:
        simplified = entry["simplified"]
        word = by_simplified.get(simplified)
        if word is None:
            word = LexiconWord(simplified=simplified, tags=["source:xiehanzi"])
            by_simplified[simplified] = word

        traditional = entry["traditional"]
        if traditional and traditional not in word.traditional_variants:
            word.traditional_variants.append(traditional)

        form_key = entry["pinyin"]
        form = word.forms.get(form_key)
        if form is None:
            form = LexiconForm(pinyin=entry["pinyin"], tags=[])
            word.forms[form_key] = form

        if traditional and traditional not in form.traditional_variants:
            form.traditional_variants.append(traditional)

        form.append_definitions(definitions_from_meaning_html(entry["meaning_html"]))
        form.add_tags(entry["tags"])

    for word in by_simplified.values():
        word.sort_forms_by_pinyin()

    return sorted(by_simplified.values(), key=lambda word: word.simplified)


def prefer_first(values: list[str], value: str) -> None:
    if not value:
        return
    if value in values:
        values.remove(value)
    values.insert(0, value)


def pinyin_pair_match_type(form_pinyin: str, entry_pinyin: str) -> str | None:
    best_score = -1
    best_match_type: str | None = None
    for form_reading in canonical_pinyin_readings(form_pinyin):
        for entry_reading in canonical_pinyin_readings(entry_pinyin):
            if form_reading.lower_compact != entry_reading.lower_compact:
                continue
            if form_reading.spaced == entry_reading.spaced:
                match_type = "exact"
            elif form_reading.compact == entry_reading.compact:
                match_type = "format_variant"
            else:
                match_type = "case_variant"

            score = match_type_score(match_type)
            if score > best_score:
                best_match_type = match_type
                best_score = score
    return best_match_type


def match_type_score(match_type: str | None) -> int:
    return {
        "exact": 100,
        "format_variant": 90,
        "case_variant": 80,
        "reading_variant": 70,
        "toneless": 60,
        "created": 0,
        None: -1,
    }[match_type]


def classify_pinyin_match(form_pinyin: str, entry_pinyin: str) -> str | None:
    match_type = pinyin_pair_match_type(form_pinyin, entry_pinyin)
    if not match_type:
        return None
    if pinyin_lookup_keys(form_pinyin) != pinyin_lookup_keys(entry_pinyin):
        return "reading_variant"
    return match_type


def record_form_match(form_stats: dict[str, Any], match_type: str) -> None:
    form_stats["match_types"][match_type] += 1
    if match_type == "reading_variant":
        form_stats["matched_pinyin_variant"] += 1


def find_or_create_hanzi_form(
    word: LexiconWord,
    entry: dict[str, Any],
    form_stats: dict[str, Any],
) -> tuple[LexiconForm, str]:
    forms = word.sorted_forms()
    entry_keys = pinyin_lookup_keys(entry["pinyin"])

    matching_forms: list[tuple[LexiconForm, str]] = []
    for form in forms:
        match_type = classify_pinyin_match(form.pinyin, entry["pinyin"])
        if match_type:
            matching_forms.append((form, match_type))

    if len(matching_forms) > 1:
        best_match = None
        best_match_type = None
        best_score = -1

        for form, match_type in matching_forms:
            score = match_type_score(match_type)
            if score > best_score:
                best_match = form
                best_match_type = match_type
                best_score = score

        if best_match and best_match_type:
            form_stats["matched"] += 1
            record_form_match(form_stats, best_match_type)
            return best_match, best_match_type

    for form, match_type in matching_forms:
        form_stats["matched"] += 1
        record_form_match(form_stats, match_type)
        return form, match_type

    entry_toneless_keys = toneless_pinyin_lookup_keys(entry["pinyin"])
    toneless_matches = [
        form
        for form in forms
        if set(toneless_pinyin_lookup_keys(form.pinyin)).intersection(entry_toneless_keys)
    ]
    if len(toneless_matches) == 1:
        form_stats["matched"] += 1
        form_stats["matched_toneless"] += 1
        record_form_match(form_stats, "toneless")
        return toneless_matches[0], "toneless"

    form = LexiconForm(
        pinyin=entry["pinyin"],
        definitions=definitions_from_meaning_html(entry["meaning_html"]),
        tags=["source:xiehanzi"],
    )
    word.add_form(form)
    word.sort_forms_by_pinyin()
    form_stats["created"] += 1
    record_form_match(form_stats, "created")
    form_stats["created_entries"].append({
        "entry": entry_summary(entry),
        "lookup_key": entry_keys[0] if entry_keys else "",
        "lookup_keys": entry_keys,
        "available_form_pinyins": [
            existing_form.pinyin
            for existing_form in forms
        ],
    })
    return form, "created"


def pinyin_formatting_key(value: str) -> str:
    return "/".join(reading.compact for reading in canonical_pinyin_readings(value))


def apply_reference_pinyin_case(source_pinyin: str, reference_pinyin: str) -> str:
    reference_by_key = {
        reading.lower_compact: reading.compact
        for reading in canonical_pinyin_readings(reference_pinyin)
    }
    cased_tokens: list[str] = []

    for source_part in re.split(r"(/)", source_pinyin or ""):
        if source_part == "/":
            cased_tokens.append(source_part)
            continue

        leading_space = re.match(r"\s*", source_part).group(0)
        trailing_space = re.search(r"\s*$", source_part).group(0)
        stripped_source = source_part.strip()
        if not stripped_source:
            cased_tokens.append(source_part)
            continue

        numbered_source = numbered_pinyin_part(stripped_source)
        source_readings = canonical_pinyin_readings(numbered_source)
        if not source_readings:
            cased_tokens.append(source_part)
            continue

        reference_compact = reference_by_key.get(source_readings[0].lower_compact)
        if not reference_compact:
            cased_tokens.append(f"{leading_space}{numbered_source}{trailing_space}")
            continue

        chars = list(numbered_source)
        reference_index = 0
        for index, char in enumerate(chars):
            if PINYIN_SEPARATOR_RE.fullmatch(char):
                continue
            if reference_index >= len(reference_compact):
                break

            reference_char = reference_compact[reference_index]
            if char.isalpha() and reference_char.isalpha() and char.lower() == reference_char.lower():
                chars[index] = char.upper() if reference_char.isupper() else char.lower()
            reference_index += 1

        cased_tokens.append(f"{leading_space}{''.join(chars)}{trailing_space}")

    return "".join(cased_tokens)


def numbered_pinyin(value: str) -> str:
    if re.search(r"\d", value):
        return normalize_pinyin_u_variants(value)
    try:
        return transcriptions.accented_to_numbered(value)
    except ValueError:
        return value


def non_exact_match_record(
    entry: dict[str, Any],
    match_type: str,
    cc_cedict_pinyin: str | None,
    cc_cedict_definitions: list[str],
    xiehanzi_pinyin: str,
) -> dict[str, Any]:
    return {
        "simplified": entry["simplified"],
        "match_type": match_type,
        "cc_cedict_pinyin": cc_cedict_pinyin,
        "xiehanzi_pinyin": xiehanzi_pinyin,
        "xiehanzi_raw_pinyin": entry.get("raw_pinyin", entry["pinyin"]),
        "cc_cedict_definitions": cc_cedict_definitions,
        "xiehanzi_definitions": definitions_from_meaning_html(entry["meaning_html"]),
    }


def normalized_definition_set(definitions: list[str]) -> set[str]:
    return {re.sub(r"\s+", " ", definition).strip() for definition in definitions if definition.strip()}


def definitions_differ(left: list[str], right: list[str]) -> bool:
    return normalized_definition_set(left) != normalized_definition_set(right)


def attach_deck_entries_to_state(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    word_index = build_state_word_index(state)
    unmatched: list[dict[str, Any]] = []
    form_stats = {
        "matched": 0,
        "matched_pinyin_variant": 0,
        "matched_toneless": 0,
        "created": 0,
        "match_types": {
            "exact": 0,
            "format_variant": 0,
            "case_variant": 0,
            "reading_variant": 0,
            "toneless": 0,
            "created": 0,
        },
        "created_entries": [],
        "non_exact_matches": [],
        "non_exact_definition_mismatches": [],
        "pinyin_case_preserved": [],
        "pinyin_whitespace_only": [],
        "pinyin_substantive": [],
    }

    for entry in deck_entries:
        word = word_index.get(normalize_field(entry["simplified"]))
        if word is None:
            unmatched.append(entry_summary(entry))
            continue

        word.add_tags(entry["tags"])
        word.set_hanzi_frequency_once(entry["frequency"])

        form, match_type = find_or_create_hanzi_form(word, entry, form_stats)
        cc_cedict_pinyin = None if match_type == "created" else form.pinyin
        cc_cedict_definitions = [] if match_type == "created" else list(form.definitions)
        xiehanzi_pinyin = numbered_pinyin(entry["pinyin"])
        if match_type != "exact":
            match_record = non_exact_match_record(
                entry=entry,
                match_type=match_type,
                cc_cedict_pinyin=cc_cedict_pinyin,
                cc_cedict_definitions=cc_cedict_definitions,
                xiehanzi_pinyin=xiehanzi_pinyin,
            )
            form_stats["non_exact_matches"].append(match_record)
            if (
                match_type != "created"
                and definitions_differ(match_record["cc_cedict_definitions"], match_record["xiehanzi_definitions"])
            ):
                form_stats["non_exact_definition_mismatches"].append(match_record)

        prefer_first(form.traditional_variants, entry["traditional"])
        form.add_tags(entry["tags"])

        if entry.get("pinyin"):
            new_pinyin = xiehanzi_pinyin
            old_pinyin = form.pinyin
            if old_pinyin and match_type != "created":
                cased_pinyin = apply_reference_pinyin_case(new_pinyin, str(old_pinyin))
                if cased_pinyin != new_pinyin:
                    form_stats["pinyin_case_preserved"].append({
                        "simplified": entry["simplified"],
                        "cc_cedict_pinyin": old_pinyin,
                        "xiehanzi_pinyin": new_pinyin,
                        "merged_pinyin": cased_pinyin,
                        "match_type": match_type,
                    })
                    new_pinyin = cased_pinyin
            if old_pinyin and old_pinyin != new_pinyin and match_type != "created":
                override_record = {
                    "simplified": entry["simplified"],
                    "cc_cedict_pinyin": old_pinyin,
                    "xiehanzi_pinyin": new_pinyin,
                    "match_type": match_type,
                    "cc_cedict_definitions": form.definitions,
                    "xiehanzi_definitions": definitions_from_meaning_html(entry["meaning_html"]),
                }
                if pinyin_formatting_key(str(old_pinyin)) == pinyin_formatting_key(new_pinyin):
                    form_stats["pinyin_whitespace_only"].append(override_record)
                else:
                    form_stats["pinyin_substantive"].append(override_record)
            form.pinyin = new_pinyin

    return unmatched, form_stats


def load_frequency_ranks(frequency_list_path: Path) -> dict[str, int]:
    ranks: dict[str, int] = {}
    with frequency_list_path.open(encoding="utf-8") as handle:
        for rank, line in enumerate(handle, start=1):
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            key = normalize_field(parts[0])
            if key and key not in ranks:
                ranks[key] = rank
    return ranks


def top_frequency_tags(rank: int | None) -> list[str]:
    if rank is None:
        return []
    return [f"freq:top{threshold}" for threshold in TOP_FREQUENCY_THRESHOLDS if rank <= threshold]


def apply_frequency_tags_to_state(state: LexiconState, frequency_list_path: Path) -> dict[str, Any]:
    ranks = load_frequency_ranks(frequency_list_path)
    tagged_words_by_threshold = {f"top{threshold}": 0 for threshold in TOP_FREQUENCY_THRESHOLDS}
    tagged_forms_by_threshold = {f"top{threshold}": 0 for threshold in TOP_FREQUENCY_THRESHOLDS}
    matched_words = 0

    for word in state.sorted_words():
        rank = ranks.get(normalize_field(word.simplified))
        tags = top_frequency_tags(rank)
        if not tags:
            continue

        matched_words += 1
        word.frequency_rank = rank
        word.add_tags(tags)

        for tag in tags:
            tagged_words_by_threshold[tag.removeprefix("freq:")] += 1

        for form in word.forms.values():
            form.add_tags(tags)
            for tag in tags:
                tagged_forms_by_threshold[tag.removeprefix("freq:")] += 1

    return {
        "source": str(frequency_list_path),
        "thresholds": list(TOP_FREQUENCY_THRESHOLDS),
        "source_entries": len(ranks),
        "matched_words": matched_words,
        "tagged_words_by_threshold": tagged_words_by_threshold,
        "tagged_forms_by_threshold": tagged_forms_by_threshold,
    }


def summarize_by_level(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = {level: 0 for level in LEVELS}
    for entry in entries:
        counts[entry["deck_level"]] = counts.get(entry["deck_level"], 0) + 1
    return counts


def group_non_exact_matches(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups = {
        "format_variant": [],
        "case_variant": [],
        "reading_variant": [],
        "toneless": [],
        "created": [],
    }
    for record in records:
        groups.setdefault(record["match_type"], []).append(record)
    return groups


def enrich_state(
    master_state: LexiconState,
    input_label: str,
    output_path: Path,
    report_path: Path,
    hsk_data_dir: Path,
    frequency_list_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_snapshot = LexiconBaseSnapshot.from_state(master_state)
    base_words = list(master_state.sorted_words())
    base_word_index = build_state_word_index(master_state)

    raw_entries = load_hanzi_entries(hsk_data_dir=hsk_data_dir)
    deck_entries, dropped_duplicates = dedupe_entries(raw_entries)

    missing_raw_before_stubs = [
        entry_summary(entry)
        for entry in raw_entries
        if normalize_field(entry["simplified"]) not in base_word_index
    ]
    missing_deck_entries_before_stubs = [
        entry
        for entry in deck_entries
        if normalize_field(entry["simplified"]) not in base_word_index
    ]
    synthetic_words = build_synthetic_words(missing_deck_entries_before_stubs)
    for word in synthetic_words:
        key = word.simplified
        if key in master_state.words:
            raise ValueError(f"Synthetic word collides with existing lexicon word: {key}")
        master_state.words[key] = word

    missing_deck_after_stubs, form_stats = attach_deck_entries_to_state(master_state, deck_entries)
    frequency_tag_stats = apply_frequency_tags_to_state(master_state, frequency_list_path)
    master_state.hanzi_dropped_duplicates = dropped_duplicates

    enrichment_metadata = LexiconEnrichmentMetadata(
        name="hanzi New HSK (2025)",
        fields=tuple(HANZI_FIELDS),
        hsk_data_dir=hsk_data_dir,
        frequency_list=frequency_list_path,
        frequency_tags=tuple(f"freq:top{threshold}" for threshold in TOP_FREQUENCY_THRESHOLDS),
        dedupe_key=HANZI_DEDUPE_KEY,
    )
    summary = {
        "base_words": len(base_words),
        "synthetic_hanzi_words": len(synthetic_words),
        "total_words": len(master_state.words),
        "raw_hanzi_entries": len(raw_entries),
        "deck_entries_after_dedupe": len(deck_entries),
        "dropped_duplicate_entries": len(dropped_duplicates),
        "raw_entries_missing_base_word": len(missing_raw_before_stubs),
        "deck_entries_missing_base_word": len(missing_deck_entries_before_stubs),
        "deck_entries_missing_enriched_word": len(missing_deck_after_stubs),
        "deck_entries_by_level": summarize_by_level(deck_entries),
        "hanzi_form_targets": form_stats["matched"] + form_stats["created"],
        "hanzi_form_matches": form_stats["matched"],
        "hanzi_form_exact_matches": form_stats["match_types"]["exact"],
        "hanzi_form_format_variant_matches": form_stats["match_types"]["format_variant"],
        "hanzi_form_case_variant_matches": form_stats["match_types"]["case_variant"],
        "hanzi_form_reading_variant_matches": form_stats["match_types"]["reading_variant"],
        "hanzi_form_pinyin_variant_matches": form_stats["matched_pinyin_variant"],
        "hanzi_form_toneless_matches": form_stats["matched_toneless"],
        "hanzi_form_stubs_created": form_stats["created"],
        "hanzi_non_exact_matches": len(form_stats["non_exact_matches"]),
        "hanzi_non_exact_definition_mismatches": len(form_stats["non_exact_definition_mismatches"]),
        "hanzi_pinyin_case_preserved": len(form_stats["pinyin_case_preserved"]),
        "hanzi_pinyin_whitespace_only": len(form_stats["pinyin_whitespace_only"]),
        "hanzi_pinyin_substantive": len(form_stats["pinyin_substantive"]),
        "frequency_tags_by_word": frequency_tag_stats["tagged_words_by_threshold"],
        "frequency_tags_by_form": frequency_tag_stats["tagged_forms_by_threshold"],
    }
    enriched = master_state.to_enriched_json(
        base=base_snapshot,
        enrichment=enrichment_metadata,
        summary=summary,
    )

    report = {
        "schema": "hanzi-enrichment-report-v1",
        "input": input_label,
        "output": str(output_path),
        "report": str(report_path),
        "summary": enriched["summary"],
        "frequency_tags": frequency_tag_stats,
        "samples": {
            "missing_raw_entries": missing_raw_before_stubs[:25],
            "missing_deck_entries": [
                entry_summary(entry)
                for entry in missing_deck_entries_before_stubs[:25]
            ],
            "synthetic_words": [
                word.to_enriched_json()
                for word in synthetic_words[:25]
            ],
            "missing_deck_entries_after_stubs": missing_deck_after_stubs[:25],
            "hanzi_form_stubs": form_stats["created_entries"],
            "hanzi_non_exact_definition_mismatches": form_stats["non_exact_definition_mismatches"],
            "hanzi_non_exact_definition_mismatches_by_type": group_non_exact_matches(
                form_stats["non_exact_definition_mismatches"]
            ),
            "dropped_duplicates": dropped_duplicates[:25],
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return enriched, report


def load_master_state(master_db_path: Path) -> LexiconState:
    return LexiconState.from_master_json(json.loads(master_db_path.read_text(encoding="utf-8")))


def enrich_database(
    master_db_path: Path,
    output_path: Path,
    report_path: Path,
    hsk_data_dir: Path,
    frequency_list_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return enrich_state(
        master_state=load_master_state(master_db_path),
        input_label=str(master_db_path),
        output_path=output_path,
        report_path=report_path,
        hsk_data_dir=hsk_data_dir,
        frequency_list_path=frequency_list_path,
    )
