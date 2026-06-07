"""
Enrich the CC-CEDICT lexicon state with xiehanzi deck-source data.

This module is part of the in-memory APKG build pipeline:

    CC-CEDICT source + hanzi TSV files -> enriched LexiconState -> APKG

The optional enriched JSON and report are diagnostic build artifacts.
"""

from __future__ import annotations

import csv
import html
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anki_hanzi.lexicon import (
    LexiconBaseSnapshot,
    LexiconEnrichmentMetadata,
    LexiconState,
)
from anki_hanzi.enrichment.frequency import (
    DEFAULT_FREQUENCY_LIST as DEFAULT_FREQUENCY_LIST,
    TOP_FREQUENCY_THRESHOLDS,
    apply_frequency_enrichment_to_state,
)
from anki_hanzi.enrichment.xiehanzi_consumption import (
    CONSUMPTION_RULES,
    apply_pipeline_enrichment_to_state,
    bucket_matching_pair_count,
    bucket_source_form_ids,
    entry_summary,
)
from anki_hanzi.enrichment.xiehanzi_matching import (
    MATCHING_RULES,
    TargetFormRef,
    build_source_entry_reports,
    build_target_form_index,
    candidate_count_bucket,
    candidate_count_buckets_for_source_forms,
    materialize_simplified_match_pairs,
)


DEFAULT_MASTER_DB = Path("master_db_output/cc_cedict_master.json")
DEFAULT_OUTPUT = Path("master_db_output/cc_cedict_hanzi_enriched.json")
DEFAULT_REPORT = Path("master_db_output/hanzi_enrichment_report.json")
DEFAULT_MATCHING_REPORT = Path("master_db_output/hanzi_matching_report.json")
DEFAULT_DECK_INPUTS_DIR = Path("deck_inputs")
DEFAULT_HSK_DATA_DIR = DEFAULT_DECK_INPUTS_DIR / "hsk-3.0-words-list/New HSK (2025)/Anki xiehanzi"
HANZI_DEDUPE_KEY = "Simplified + raw Pinyin"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


BUCKET_DESCRIPTIONS = {
    "perfect_match": (
        "A source form has exactly one remaining dictionary candidate with the same complete strict numbered "
        "preserve-case Pinyin reading list. The source form is resolved and all of its candidate pairs are consumed."
    ),
    "manual_pinyin_override": (
        "A configured manual Pinyin correction has exactly one remaining strict or format-variant dictionary "
        "candidate. The source form is resolved with the corrected Pinyin value."
    ),
    "format_variant_unique": (
        "A source form has exactly one remaining dictionary candidate whose complete compact preserve-case Pinyin "
        "reading list matches after spacing and separator differences. The source form is resolved without changing "
        "dictionary Pinyin or definitions."
    ),
    "spoken_tone_variant": (
        "A source form has exactly one remaining dictionary candidate whose toneless Pinyin matches. Every tone "
        "difference between source and dictionary Pinyin is fully explained by recognized spoken variants: 一 "
        "sandhi, 不 sandhi, or neutral-tone differences with matching reading and syllable structure. The source "
        "form is consumed by adding the source tones in dictionary Pinyin format as an accepted reading on the "
        "selected dictionary form."
    ),
    "case_variant_exact_definition": (
        "A source form has exactly one remaining dictionary candidate whose Pinyin differs by case after spacing "
        "and separator normalization, and whose complete normalized definition set matches exactly. The source form "
        "is resolved by applying tags and metadata to the selected dictionary form without changing dictionary "
        "Pinyin or definitions."
    ),
    "exact_definition_also_pr": (
        "A source form has exactly one remaining dictionary candidate whose complete normalized definition set "
        "matches exactly. Every source Pinyin reading is either already on the dictionary form or explicitly listed "
        "in the dictionary definitions as also pr., and at least one source reading is such an extra also-pr reading. "
        "The source form is resolved by applying tags and metadata directly and adding the explicitly attested "
        "also-pr readings to the selected dictionary form."
    ),
    "exact_definition": (
        "A source form has exactly one remaining dictionary candidate whose complete normalized definition set "
        "matches exactly. The source form is resolved by applying tags and metadata directly to the selected "
        "dictionary form without changing dictionary Pinyin or definitions."
    ),
    "semicolon_split_exact_definition_also_pr": (
        "A source form has exactly one remaining dictionary candidate whose complete normalized definition set "
        "matches after rule-local semicolon splitting. Every source Pinyin reading is either already on the "
        "dictionary form or explicitly listed in the dictionary definitions as also pr., and at least one source "
        "reading is such an extra also-pr reading. The source form is resolved by applying tags and metadata "
        "directly and adding the explicitly attested also-pr readings to the selected dictionary form."
    ),
    "html_subform_definition_cover": (
        "A remaining source form is internally split by xiehanzi HTML Pinyin/definition blocks. Each HTML subform "
        "has exactly one strict numbered preserve-case Pinyin dictionary candidate whose normalized definition set "
        "matches after rule-local semicolon splitting, and the matched subforms cover all remaining dictionary "
        "candidates exactly once. The source form is resolved by applying tags and metadata directly to every "
        "covered dictionary form without changing dictionary Pinyin or definitions."
    ),
    "missing_dictionary_word": (
        "No exact Simplified target key exists in CC-CEDICT. The source form is resolved by creating synthetic "
        "words/forms from the xiehanzi source entry."
    ),
    "default_unresolved": (
        "No higher-priority bucket resolved the source form. This bucket must stay empty; the build aborts if any "
        "matching pairs reach it."
    ),
}

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


@dataclass(frozen=True)
class BucketDefinition:
    name: str
    priority: int
    phase: str
    description: str
    report_items: bool
    matching_rules: tuple[str, ...] = ()
    consumption_rule: str | None = None


BUCKET_DEFINITIONS = {
    "missing_dictionary_word": BucketDefinition(
        name="missing_dictionary_word",
        priority=10,
        phase="source_prelude",
        description=BUCKET_DESCRIPTIONS["missing_dictionary_word"],
        report_items=False,
        matching_rules=("missing_dictionary_word",),
        consumption_rule="drop_missing_dictionary_word_source_forms",
    ),
    "perfect_match": BucketDefinition(
        name="perfect_match",
        priority=20,
        phase="pair_pipeline",
        description=BUCKET_DESCRIPTIONS["perfect_match"],
        report_items=False,
        matching_rules=("strict_pinyin_exact_unique",),
        consumption_rule="drop_perfect_match_source_form_pairs",
    ),
    "manual_pinyin_override": BucketDefinition(
        name="manual_pinyin_override",
        priority=30,
        phase="pair_pipeline",
        description=BUCKET_DESCRIPTIONS["manual_pinyin_override"],
        report_items=False,
        matching_rules=("manual_pinyin_override_unique",),
        consumption_rule="drop_manual_pinyin_override_source_form_pairs",
    ),
    "format_variant_unique": BucketDefinition(
        name="format_variant_unique",
        priority=40,
        phase="pair_pipeline",
        description=BUCKET_DESCRIPTIONS["format_variant_unique"],
        report_items=False,
        matching_rules=("format_variant_unique",),
        consumption_rule="drop_format_variant_source_form_pairs",
    ),
    "spoken_tone_variant": BucketDefinition(
        name="spoken_tone_variant",
        priority=50,
        phase="pair_pipeline",
        description=BUCKET_DESCRIPTIONS["spoken_tone_variant"],
        report_items=False,
        matching_rules=("spoken_tone_variant_unique",),
        consumption_rule="consume_spoken_tone_variant_source_form_pairs",
    ),
    "case_variant_exact_definition": BucketDefinition(
        name="case_variant_exact_definition",
        priority=60,
        phase="pair_pipeline",
        description=BUCKET_DESCRIPTIONS["case_variant_exact_definition"],
        report_items=False,
        matching_rules=("case_variant_exact_definition_unique",),
        consumption_rule="drop_case_variant_exact_definition_source_form_pairs",
    ),
    "exact_definition_also_pr": BucketDefinition(
        name="exact_definition_also_pr",
        priority=65,
        phase="pair_pipeline",
        description=BUCKET_DESCRIPTIONS["exact_definition_also_pr"],
        report_items=False,
        matching_rules=("exact_definition_also_pr_unique",),
        consumption_rule="drop_exact_definition_also_pr_source_form_pairs",
    ),
    "exact_definition": BucketDefinition(
        name="exact_definition",
        priority=70,
        phase="pair_pipeline",
        description=BUCKET_DESCRIPTIONS["exact_definition"],
        report_items=False,
        matching_rules=("exact_definition_unique",),
        consumption_rule="drop_exact_definition_source_form_pairs",
    ),
    "semicolon_split_exact_definition_also_pr": BucketDefinition(
        name="semicolon_split_exact_definition_also_pr",
        priority=75,
        phase="pair_pipeline",
        description=BUCKET_DESCRIPTIONS["semicolon_split_exact_definition_also_pr"],
        report_items=False,
        matching_rules=("semicolon_split_exact_definition_also_pr_unique",),
        consumption_rule="drop_semicolon_split_exact_definition_also_pr_source_form_pairs",
    ),
    "html_subform_definition_cover": BucketDefinition(
        name="html_subform_definition_cover",
        priority=80,
        phase="pair_pipeline",
        description=BUCKET_DESCRIPTIONS["html_subform_definition_cover"],
        report_items=False,
        matching_rules=("html_subform_definition_cover_unique",),
        consumption_rule="drop_html_subform_definition_cover_source_form_pairs",
    ),
    "default_unresolved": BucketDefinition(
        name="default_unresolved",
        priority=1000,
        phase="terminal",
        description=BUCKET_DESCRIPTIONS["default_unresolved"],
        report_items=True,
        matching_rules=("default_unresolved",),
        consumption_rule="assert_default_unresolved_empty",
    ),
}


def strip_html_field(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", "", value)
    return value.strip()


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


def bucket_definitions_by_priority() -> list[BucketDefinition]:
    return sorted(BUCKET_DEFINITIONS.values(), key=lambda definition: definition.priority)


def bucket_definitions_by_phase(phase: str) -> list[BucketDefinition]:
    return [definition for definition in bucket_definitions_by_priority() if definition.phase == phase]


def apply_source_prelude_rules(
    entry_reports_by_id: dict[int, dict[str, Any]],
    target_form_index: dict[str, list[TargetFormRef]],
) -> dict[str, Any]:
    remaining_source_form_ids = set(entry_reports_by_id)
    bucket_results: dict[str, dict[str, Any]] = {}
    consumed_by_source_form: dict[int, str] = {}

    for definition in bucket_definitions_by_phase("source_prelude"):
        selected_items: list[dict[str, Any]] = []
        input_source_form_count = len(remaining_source_form_ids)

        for rule_name in definition.matching_rules:
            rule = MATCHING_RULES[rule_name]
            result = rule.handler(
                entry_reports_by_id,
                target_form_index,
                remaining_source_form_ids,
                definition.name,
                rule_name,
            )
            selected_items.extend(result["selected_items"])

        consumption_rule = CONSUMPTION_RULES[definition.consumption_rule] if definition.consumption_rule else None
        consumption = (
            consumption_rule.handler(selected_items, remaining_source_form_ids)
            if consumption_rule is not None
            else {
                "consumed_source_form_ids": set(),
                "consumed_source_form_count": 0,
                "consumed_matching_pair_count": 0,
                "remaining_source_form_count": len(remaining_source_form_ids),
            }
        )
        for source_form_id in consumption["consumed_source_form_ids"]:
            consumed_by_source_form[source_form_id] = definition.name

        bucket_results[definition.name] = {
            "phase": definition.phase,
            "bucket": definition.name,
            "input_source_form_count": input_source_form_count,
            "input_matching_pair_count": 0,
            "selected_items": selected_items,
            "selected_source_form_count": len(bucket_source_form_ids(selected_items)),
            "selected_matching_pair_count": 0,
            "consumed_source_form_count": consumption["consumed_source_form_count"],
            "consumed_matching_pair_count": consumption["consumed_matching_pair_count"],
            "removed_from_remaining_matching_pair_count": 0,
            "remaining_source_form_count_after_consumption": consumption["remaining_source_form_count"],
            "remaining_matching_pair_count_after_consumption": 0,
            "items_after_consumption": [],
        }

    return {
        "remaining_source_form_ids": remaining_source_form_ids,
        "bucket_results": bucket_results,
        "consumed_by_source_form": consumed_by_source_form,
    }


def apply_pair_pipeline_rules(working_pairs: list[dict[str, Any]]) -> dict[str, Any]:
    remaining_items = list(working_pairs)
    bucket_results: dict[str, dict[str, Any]] = {}
    consumed_by_source_form: dict[int, str] = {}

    for definition in bucket_definitions_by_phase("pair_pipeline"):
        input_items = remaining_items
        selected_items: list[dict[str, Any]] = []

        for rule_name in definition.matching_rules:
            rule = MATCHING_RULES[rule_name]
            result = rule.handler(input_items, definition.name, rule_name)
            selected_items.extend(result["selected_items"])
            remaining_items = result["remaining_items"]

        consumption_rule = CONSUMPTION_RULES[definition.consumption_rule] if definition.consumption_rule else None
        consumption = (
            consumption_rule.handler(selected_items, remaining_items)
            if consumption_rule is not None
            else {
                "consumed_source_form_ids": set(),
                "consumed_source_form_count": 0,
                "consumed_matching_pair_count": 0,
                "removed_from_remaining_matching_pair_count": 0,
                "remaining_items": remaining_items,
            }
        )
        remaining_items = consumption["remaining_items"]
        for source_form_id in consumption["consumed_source_form_ids"]:
            consumed_by_source_form[source_form_id] = definition.name

        bucket_results[definition.name] = {
            "phase": definition.phase,
            "bucket": definition.name,
            "input_source_form_count": len(bucket_source_form_ids(input_items)),
            "input_matching_pair_count": bucket_matching_pair_count(input_items),
            "selected_items": selected_items,
            "selected_source_form_count": len(bucket_source_form_ids(selected_items)),
            "selected_matching_pair_count": bucket_matching_pair_count(selected_items),
            "consumed_source_form_count": consumption["consumed_source_form_count"],
            "consumed_matching_pair_count": consumption["consumed_matching_pair_count"],
            "removed_from_remaining_matching_pair_count": consumption["removed_from_remaining_matching_pair_count"],
            "remaining_source_form_count_after_consumption": len(bucket_source_form_ids(remaining_items)),
            "remaining_matching_pair_count_after_consumption": bucket_matching_pair_count(remaining_items),
            "items_after_consumption": [],
        }

    for definition in bucket_definitions_by_phase("terminal"):
        input_items = remaining_items
        rule_name = definition.matching_rules[0]
        rule = MATCHING_RULES[rule_name]
        result = rule.handler(input_items, definition.name, rule_name)
        selected_items = result["selected_items"]
        consumption_rule = CONSUMPTION_RULES[definition.consumption_rule] if definition.consumption_rule else None
        consumption = (
            consumption_rule.handler(selected_items, result["remaining_items"])
            if consumption_rule is not None
            else {
                "consumed_source_form_ids": set(),
                "consumed_source_form_count": 0,
                "consumed_matching_pair_count": 0,
                "removed_from_remaining_matching_pair_count": 0,
                "remaining_items": result["remaining_items"],
            }
        )
        remaining_items = consumption["remaining_items"]
        for source_form_id in consumption["consumed_source_form_ids"]:
            consumed_by_source_form[source_form_id] = definition.name

        bucket_results[definition.name] = {
            "phase": definition.phase,
            "bucket": definition.name,
            "input_source_form_count": len(bucket_source_form_ids(input_items)),
            "input_matching_pair_count": bucket_matching_pair_count(input_items),
            "selected_items": selected_items,
            "selected_source_form_count": len(bucket_source_form_ids(selected_items)),
            "selected_matching_pair_count": bucket_matching_pair_count(selected_items),
            "consumed_source_form_count": consumption["consumed_source_form_count"],
            "consumed_matching_pair_count": consumption["consumed_matching_pair_count"],
            "removed_from_remaining_matching_pair_count": consumption["removed_from_remaining_matching_pair_count"],
            "remaining_source_form_count_after_consumption": len(bucket_source_form_ids(remaining_items)),
            "remaining_matching_pair_count_after_consumption": bucket_matching_pair_count(remaining_items),
            "items_after_consumption": selected_items,
        }

    return {
        "bucket_results": bucket_results,
        "consumed_by_source_form": consumed_by_source_form,
        "remaining_items": remaining_items,
    }


def validate_pair_pipeline(
    initial_matching_pair_count: int,
    bucket_results: dict[str, dict[str, Any]],
) -> None:
    consumed_matching_pair_count = sum(
        result["consumed_matching_pair_count"]
        for result in bucket_results.values()
        if result["phase"] == "pair_pipeline"
    )
    terminal_matching_pair_count = sum(
        result["selected_matching_pair_count"] for result in bucket_results.values() if result["phase"] == "terminal"
    )
    if consumed_matching_pair_count + terminal_matching_pair_count != initial_matching_pair_count:
        raise ValueError(
            "Pair pipeline did not account for every materialized matching pair: "
            f"{consumed_matching_pair_count=} {terminal_matching_pair_count=} {initial_matching_pair_count=}"
        )


def build_matching_pipeline(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    target_form_index = build_target_form_index(state)
    dictionary_word_count = len(state.sorted_words())
    dictionary_form_count = sum(len(target_refs) for target_refs in target_form_index.values())
    entry_reports_by_id = build_source_entry_reports(deck_entries)

    source_prelude_result = apply_source_prelude_rules(entry_reports_by_id, target_form_index)
    materialization_result = materialize_simplified_match_pairs(
        entry_reports_by_id,
        target_form_index,
        source_prelude_result["remaining_source_form_ids"],
    )
    working_pairs = materialization_result["working_pairs"]
    pair_pipeline_result = apply_pair_pipeline_rules(working_pairs)

    bucket_results = {
        **source_prelude_result["bucket_results"],
        **pair_pipeline_result["bucket_results"],
    }
    validate_pair_pipeline(len(working_pairs), pair_pipeline_result["bucket_results"])

    consumed_by_source_form = {
        **source_prelude_result["consumed_by_source_form"],
        **pair_pipeline_result["consumed_by_source_form"],
    }

    return {
        "target_form_index": target_form_index,
        "dictionary_word_count": dictionary_word_count,
        "dictionary_form_count": dictionary_form_count,
        "entry_reports_by_id": entry_reports_by_id,
        "source_prelude_result": source_prelude_result,
        "materialization_result": materialization_result,
        "working_pairs": working_pairs,
        "pair_pipeline_result": pair_pipeline_result,
        "bucket_results": bucket_results,
        "consumed_by_source_form": consumed_by_source_form,
    }


def build_matching_report(
    state: LexiconState,
    raw_entries: list[dict[str, Any]],
    deck_entries: list[dict[str, Any]],
    dropped_duplicates: list[dict[str, Any]],
    *,
    bucket_item_limit: int | None = None,
    pipeline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pipeline = pipeline or build_matching_pipeline(state, deck_entries)
    dictionary_word_count = pipeline["dictionary_word_count"]
    dictionary_form_count = pipeline["dictionary_form_count"]
    entry_reports_by_id = pipeline["entry_reports_by_id"]
    materialization_result = pipeline["materialization_result"]
    working_pairs = pipeline["working_pairs"]
    bucket_results = pipeline["bucket_results"]
    consumed_by_source_form = pipeline["consumed_by_source_form"]
    default_items = bucket_results["default_unresolved"]["selected_items"]
    default_source_form_ids_after_consumption = bucket_source_form_ids(default_items)

    initial_candidate_count_buckets = Counter(
        candidate_count_bucket(entry_report["candidate_summary"]["candidate_count"])
        for entry_report in entry_reports_by_id.values()
    )
    default_candidate_count_buckets = candidate_count_buckets_for_source_forms(
        entry_reports_by_id,
        default_source_form_ids_after_consumption,
    )

    def bucket_result(definition: BucketDefinition) -> dict[str, Any]:
        return bucket_results[definition.name]

    def selected_source_form_count_after_consumption(result: dict[str, Any], definition: BucketDefinition) -> int:
        if definition.consumption_rule is None:
            return result["selected_source_form_count"]
        return 0

    def selected_matching_pair_count_after_consumption(result: dict[str, Any], definition: BucketDefinition) -> int:
        if definition.consumption_rule is None:
            return result["selected_matching_pair_count"]
        return 0

    def source_form_bucket_counts_before_consumption() -> dict[str, int]:
        return {
            definition.name: bucket_result(definition)["selected_source_form_count"]
            for definition in bucket_definitions_by_priority()
        }

    def source_form_bucket_counts_after_consumption() -> dict[str, int]:
        return {
            definition.name: selected_source_form_count_after_consumption(bucket_result(definition), definition)
            for definition in bucket_definitions_by_priority()
        }

    def matching_pair_bucket_counts_before_consumption() -> dict[str, int]:
        return {
            definition.name: bucket_result(definition)["selected_matching_pair_count"]
            for definition in bucket_definitions_by_priority()
        }

    def matching_pair_bucket_counts_after_consumption() -> dict[str, int]:
        return {
            definition.name: selected_matching_pair_count_after_consumption(bucket_result(definition), definition)
            for definition in bucket_definitions_by_priority()
        }

    bucket_source_form_counts_before_consumption = source_form_bucket_counts_before_consumption()
    bucket_source_form_counts_after_consumption = source_form_bucket_counts_after_consumption()
    bucket_matching_pair_counts_before_consumption = matching_pair_bucket_counts_before_consumption()
    bucket_matching_pair_counts_after_consumption = matching_pair_bucket_counts_after_consumption()

    def compact_report_item(item: dict[str, Any]) -> dict[str, Any]:
        source = item["source"]
        context = item.get("context", {})
        source_label = f"{source['simplified']} {source['pinyin']} [{source['deck_level']}]"
        if source.get("raw_pinyin") and source["raw_pinyin"] != source["pinyin"]:
            source_label = f"{source_label} raw:{source['raw_pinyin']}"
        report: dict[str, Any] = {
            "source_form_id": context.get("source_form_id"),
            "source": source_label,
        }

        dictionary = item.get("dictionary")
        if dictionary is not None:
            report["target"] = dictionary["pinyin"]
            report["definitions"] = {
                "source": item.get("source_definitions", []),
                "dictionary": dictionary.get("definitions", []),
            }

        if context.get("candidate_count_for_source") is not None:
            report["candidate"] = f"{context.get('candidate_index_for_source')}/{context['candidate_count_for_source']}"

        for extra_key in (
            "manual_pinyin_override",
            "spoken_tone_variant",
            "exact_definition_also_pr",
            "semicolon_split_exact_definition_also_pr",
            "html_subform_definition_cover",
        ):
            if extra_key in context:
                report[extra_key] = context[extra_key]

        return report

    def report_bucket_items(bucket: str) -> list[dict[str, Any]]:
        if not BUCKET_DEFINITIONS[bucket].report_items:
            return []
        items = bucket_results[bucket]["selected_items"]
        if bucket_item_limit is not None:
            items = items[:bucket_item_limit]
        return [compact_report_item(item) for item in items]

    def matching_rule_report(rule_name: str) -> dict[str, Any]:
        rule = MATCHING_RULES[rule_name]
        report = {
            "name": rule.name,
            "scope": rule.scope,
            "requires": list(rule.requires),
        }
        if rule.selected_pair is not None:
            report["selected_pair"] = rule.selected_pair
        return report

    def consumption_rule_report(rule_name: str | None) -> dict[str, Any] | None:
        if rule_name is None:
            return None
        rule = CONSUMPTION_RULES[rule_name]
        return {
            "name": rule.name,
            "report_only_effect": rule.report_only_effect,
            "enrichment_effect": rule.enrichment_effect,
        }

    def bucket_summary_item(definition: BucketDefinition) -> dict[str, Any]:
        bucket = definition.name
        result = bucket_result(definition)
        item: dict[str, Any] = {
            "priority": definition.priority,
            "phase": definition.phase,
            "bucket": bucket,
            "description": definition.description,
            "matching_rules": [matching_rule_report(rule_name) for rule_name in definition.matching_rules],
            "consumption_rule": consumption_rule_report(definition.consumption_rule),
            "step_input_source_form_count": result["input_source_form_count"],
            "step_input_matching_pair_count": result["input_matching_pair_count"],
            "source_form_count_before_consumption": result["selected_source_form_count"],
            "source_form_count_after_consumption": selected_source_form_count_after_consumption(result, definition),
            "matching_pair_count_before_consumption": result["selected_matching_pair_count"],
            "matching_pair_count_after_consumption": selected_matching_pair_count_after_consumption(result, definition),
            "consumed_source_form_count": result["consumed_source_form_count"],
            "consumed_matching_pair_count": result["consumed_matching_pair_count"],
            "removed_from_remaining_matching_pair_count": result["removed_from_remaining_matching_pair_count"],
            "remaining_source_form_count_after_step": result["remaining_source_form_count_after_consumption"],
            "remaining_matching_pair_count_after_step": result["remaining_matching_pair_count_after_consumption"],
            "has_consumption_rule": definition.consumption_rule is not None,
            "report_items": definition.report_items,
        }
        return item

    def bucket_report_item(definition: BucketDefinition) -> dict[str, Any]:
        bucket = definition.name
        result = bucket_result(definition)
        return {
            "description": definition.description,
            "matching_rules": [matching_rule_report(rule_name) for rule_name in definition.matching_rules],
            "item_count": result["selected_matching_pair_count"],
            "items": report_bucket_items(bucket),
        }

    return {
        "schema": "hanzi-matching-report-v1",
        "bucket_summary": [bucket_summary_item(definition) for definition in bucket_definitions_by_priority()],
        "description": (
            "Diagnostic xiehanzi-to-CC-CEDICT matching pipeline. "
            "Source prelude rules consume source forms before the pair pipeline starts. "
            "Pair rules then split a shrinking working set before consumption removes source-form redundancies. "
            "All buckets include overview counts; buckets configured with report_items contain detailed matching "
            "pairs for rule design."
        ),
        "summary": {
            "raw_source_entries": len(raw_entries),
            "deduped_source_entries": len(deck_entries),
            "dropped_duplicate_entries": len(dropped_duplicates),
            "dictionary_words": dictionary_word_count,
            "dictionary_forms": dictionary_form_count,
            "source_form_bucket_counts_before_consumption": dict(
                sorted(bucket_source_form_counts_before_consumption.items())
            ),
            "source_form_bucket_counts_after_consumption": dict(
                sorted(bucket_source_form_counts_after_consumption.items())
            ),
            "matching_pair_bucket_counts_before_consumption": dict(
                sorted(bucket_matching_pair_counts_before_consumption.items())
            ),
            "matching_pair_bucket_counts_after_consumption": dict(
                sorted(bucket_matching_pair_counts_after_consumption.items())
            ),
            "resolved_source_forms": len(consumed_by_source_form),
            "unresolved_source_forms": bucket_results["default_unresolved"]["selected_source_form_count"],
            "virtual_start_matching_pair_count": len(deck_entries) * dictionary_form_count,
            "virtual_pair_pipeline_start_matching_pair_count": materialization_result["virtual_pair_count"],
            "virtual_simplified_mismatch_pair_count": materialization_result["simplified_mismatch_pair_count"],
            "initial_matching_pair_count": len(working_pairs),
            "default_unresolved_matching_pair_count": bucket_matching_pair_count(default_items),
            "initial_candidate_count_buckets": dict(sorted(initial_candidate_count_buckets.items())),
            "default_candidate_count_buckets": dict(sorted(default_candidate_count_buckets.items())),
            "bucket_item_limit": bucket_item_limit,
        },
        "pair_materialization": {
            "virtual_start_bucket": {
                "description": "Logical source-form x dictionary-form universe; never materialized.",
                "source_form_count": len(deck_entries),
                "target_form_count": dictionary_form_count,
                "virtual_matching_pair_count": len(deck_entries) * dictionary_form_count,
                "materialized": False,
            },
            "source_prelude_remaining_sources": {
                "description": "Source forms that survived source-level prelude rules.",
                "source_form_count": materialization_result["source_form_count"],
            },
            "simplified_match_working_set": {
                "description": "Materialized pairs whose exact Simplified values match.",
                "matching_rule": "simplified_match",
                "source_form_count": materialization_result["source_form_count"],
                "target_form_count": materialization_result["target_form_count"],
                "virtual_input_matching_pair_count": materialization_result["virtual_pair_count"],
                "matching_pair_count": materialization_result["simplified_match_pair_count"],
                "materialized": True,
            },
            "simplified_mismatch": {
                "description": "Virtual rejected pairs whose exact Simplified values do not match.",
                "matching_rule": "simplified_mismatch",
                "matching_pair_count": materialization_result["simplified_mismatch_pair_count"],
                "materialized": False,
            },
        },
        "candidate_generation": {
            "source_prelude": "missing_dictionary_word removes source forms with no exact Simplified target key.",
            "pair_materialization": "simplified_match materializes only exact Simplified-compatible pairs.",
            "virtual_rejection": "simplified_mismatch is counted as a virtual aggregate and is not stored as items.",
        },
        "buckets": {
            definition.name: bucket_report_item(definition)
            for definition in bucket_definitions_by_priority()
            if definition.report_items
        },
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
    }
    for record in records:
        groups.setdefault(record["match_type"], []).append(record)
    return groups


def pipeline_report_item(result: dict[str, Any]) -> dict[str, Any]:
    omitted_keys = {"added_readings", "entries", "form_stats", "matched_targets"}
    return {key: value for key, value in result.items() if key not in omitted_keys}


def enrich_state(
    master_state: LexiconState,
    input_label: str,
    output_path: Path,
    report_path: Path,
    matching_report_path: Path | None,
    hsk_data_dir: Path,
    frequency_list_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_snapshot = LexiconBaseSnapshot.from_state(master_state)
    base_words = list(master_state.sorted_words())
    base_word_index = {word.simplified: word for word in master_state.sorted_words()}

    raw_entries = load_hanzi_entries(hsk_data_dir=hsk_data_dir)
    deck_entries, dropped_duplicates = dedupe_entries(raw_entries)
    matching_pipeline = build_matching_pipeline(master_state, deck_entries)
    matching_report = build_matching_report(
        state=master_state,
        raw_entries=raw_entries,
        deck_entries=deck_entries,
        dropped_duplicates=dropped_duplicates,
        pipeline=matching_pipeline,
    )

    missing_raw_entries = [entry_summary(entry) for entry in raw_entries if entry["simplified"] not in base_word_index]
    pipeline_enrichment = apply_pipeline_enrichment_to_state(master_state, deck_entries, matching_pipeline)
    missing_deck_entries = pipeline_enrichment["missing_deck_entries"]
    synthetic_words = pipeline_enrichment["synthetic_words"]
    form_stats = pipeline_enrichment["form_stats"]
    frequency_enrichment = apply_frequency_enrichment_to_state(master_state, frequency_list_path)
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
        "raw_entries_missing_base_word": len(missing_raw_entries),
        "deck_entries_missing_base_word": len(missing_deck_entries),
        "deck_entries_by_level": summarize_by_level(deck_entries),
        "hanzi_form_targets": form_stats["matched"],
        "hanzi_form_matches": form_stats["matched"],
        "hanzi_form_exact_matches": form_stats["match_types"]["exact"],
        "hanzi_form_format_variant_matches": form_stats["match_types"]["format_variant"],
        "hanzi_form_case_variant_matches": form_stats["match_types"]["case_variant"],
        "hanzi_form_spoken_tone_variant_matches": form_stats["match_types"]["spoken_tone_variant"],
        "hanzi_form_exact_definition_matches": form_stats["match_types"]["exact_definition"],
        "hanzi_form_exact_definition_also_pr_matches": form_stats["match_types"]["exact_definition_also_pr"],
        "hanzi_form_semicolon_split_exact_definition_also_pr_matches": form_stats["match_types"][
            "semicolon_split_exact_definition_also_pr"
        ],
        "hanzi_form_html_subform_definition_cover_matches": form_stats["match_types"]["html_subform_definition_cover"],
        "hanzi_non_exact_matches": len(form_stats["non_exact_matches"]),
        "hanzi_non_exact_definition_mismatches": len(form_stats["non_exact_definition_mismatches"]),
        "hanzi_pinyin_case_preserved": len(form_stats["pinyin_case_preserved"]),
        "hanzi_pinyin_whitespace_only": len(form_stats["pinyin_whitespace_only"]),
        "hanzi_pinyin_substantive": len(form_stats["pinyin_substantive"]),
        "frequency_tags_by_word": frequency_enrichment["tagged_words_by_threshold"],
        "frequency_tags_by_form": frequency_enrichment["tagged_forms_by_threshold"],
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
        "matching_report": str(matching_report_path) if matching_report_path is not None else None,
        "summary": enriched["summary"],
        "matching_summary": matching_report["summary"],
        "pipeline_enrichment": {
            definition.name: pipeline_report_item(pipeline_enrichment[definition.name])
            for definition in bucket_definitions_by_priority()
            if definition.name in pipeline_enrichment
        },
        "frequency_enrichment": frequency_enrichment,
        "samples": {
            "missing_raw_entries": missing_raw_entries[:25],
            "missing_deck_entries": [entry_summary(entry) for entry in missing_deck_entries[:25]],
            "synthetic_words": [word.to_enriched_json() for word in synthetic_words[:25]],
            "perfect_match_entries": pipeline_enrichment["perfect_match"]["entries"][:25],
            "manual_pinyin_override_entries": pipeline_enrichment["manual_pinyin_override"]["entries"][:25],
            "format_variant_unique_entries": pipeline_enrichment["format_variant_unique"]["entries"][:25],
            "exact_definition_also_pr_added_readings": pipeline_enrichment["exact_definition_also_pr"][
                "added_readings"
            ][:25],
            "exact_definition_also_pr_entries": pipeline_enrichment["exact_definition_also_pr"]["entries"][:25],
            "exact_definition_entries": pipeline_enrichment["exact_definition"]["entries"][:25],
            "semicolon_split_exact_definition_also_pr_added_readings": pipeline_enrichment[
                "semicolon_split_exact_definition_also_pr"
            ]["added_readings"][:25],
            "semicolon_split_exact_definition_also_pr_entries": pipeline_enrichment[
                "semicolon_split_exact_definition_also_pr"
            ]["entries"][:25],
            "html_subform_definition_cover_entries": pipeline_enrichment["html_subform_definition_cover"]["entries"][
                :25
            ],
            "html_subform_definition_cover_targets": pipeline_enrichment["html_subform_definition_cover"][
                "matched_targets"
            ][:25],
            "hanzi_non_exact_definition_mismatches": form_stats["non_exact_definition_mismatches"],
            "hanzi_non_exact_definition_mismatches_by_type": group_non_exact_matches(
                form_stats["non_exact_definition_mismatches"]
            ),
            "dropped_duplicates": dropped_duplicates[:25],
        },
    }

    if matching_report_path is not None:
        write_json(matching_report_path, matching_report)
    write_json(output_path, enriched)
    write_json(report_path, report)
    return enriched, report


def load_master_state(master_db_path: Path) -> LexiconState:
    return LexiconState.from_master_json(json.loads(master_db_path.read_text(encoding="utf-8")))


def enrich_database(
    master_db_path: Path,
    output_path: Path,
    report_path: Path,
    matching_report_path: Path | None,
    hsk_data_dir: Path,
    frequency_list_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return enrich_state(
        master_state=load_master_state(master_db_path),
        input_label=str(master_db_path),
        output_path=output_path,
        report_path=report_path,
        matching_report_path=matching_report_path,
        hsk_data_dir=hsk_data_dir,
        frequency_list_path=frequency_list_path,
    )
