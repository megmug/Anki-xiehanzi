"""
Enrich the CC-CEDICT lexicon state with xiehanzi deck-source data.

This module is part of the in-memory APKG build pipeline:

    CC-CEDICT source + hanzi TSV files -> enriched LexiconState -> APKG

The optional enriched JSON and report are diagnostic build artifacts.
"""

from __future__ import annotations

import json
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
from anki_hanzi.enrichment.erhua import apply_erhua_definition_enrichment_to_state
from anki_hanzi.enrichment.xiehanzi.buckets import (
    bucket_definitions_by_phase,
    bucket_definitions_by_priority,
)
from anki_hanzi.enrichment.xiehanzi.consumption import (
    apply_pipeline_enrichment_to_state,
)
from anki_hanzi.enrichment.xiehanzi.model import (
    BucketResult,
    PairConsumption,
    PairPipelineResult,
    PipelineItem,
    SourcePreludeConsumption,
    SourcePreludePipelineResult,
    empty_pair_consumption,
    empty_source_prelude_consumption,
    pair_pipeline_bucket_result,
    source_prelude_bucket_result,
)
from anki_hanzi.enrichment.xiehanzi.source import (
    HANZI_DEDUPE_KEY,
    HANZI_FIELDS,
    dedupe_entries,
    load_hanzi_entries,
)
from anki_hanzi.enrichment.xiehanzi.matching import (
    TargetFormRef,
    build_source_entry_reports,
    build_target_form_index,
    materialize_simplified_match_pairs,
)
from anki_hanzi.enrichment.xiehanzi.reports import (
    build_enrichment_report,
    build_enrichment_summary,
    build_matching_report,
)
from anki_hanzi.json_io import write_json


DEFAULT_DECK_INPUTS_DIR = Path("deck_inputs")
DEFAULT_HSK_DATA_DIR = DEFAULT_DECK_INPUTS_DIR / "hsk-3.0-words-list/New HSK (2025)/Anki xiehanzi"


@dataclass(frozen=True)
class XiehanziEnrichmentResult:
    enriched: dict[str, Any]
    enrichment_report: dict[str, Any]
    matching_report: dict[str, Any]


def apply_source_prelude_rules(
    entry_reports_by_id: dict[int, dict[str, Any]],
    target_form_index: dict[str, list[TargetFormRef]],
) -> SourcePreludePipelineResult:
    remaining_source_form_ids = set(entry_reports_by_id)
    bucket_results: dict[str, BucketResult] = {}
    consumed_by_source_form: dict[int, str] = {}

    for definition in bucket_definitions_by_phase("source_prelude"):
        selected_items: list[PipelineItem] = []
        input_source_form_count = len(remaining_source_form_ids)

        for rule in definition.matching_rules:
            result = rule.match_source_prelude(
                entry_reports_by_id,
                target_form_index,
                remaining_source_form_ids,
                definition.name,
            )
            selected_items.extend(result["selected_items"])

        consumption_rule = definition.consumption_rule
        consumption: SourcePreludeConsumption = (
            consumption_rule.consume_source_prelude(selected_items, remaining_source_form_ids)
            if consumption_rule is not None
            else empty_source_prelude_consumption(remaining_source_form_ids)
        )
        for source_form_id in consumption["consumed_source_form_ids"]:
            consumed_by_source_form[source_form_id] = definition.name

        bucket_results[definition.name] = source_prelude_bucket_result(
            bucket=definition.name,
            phase=definition.phase,
            input_source_form_count=input_source_form_count,
            selected_items=selected_items,
            consumption=consumption,
        )

    return {
        "remaining_source_form_ids": remaining_source_form_ids,
        "bucket_results": bucket_results,
        "consumed_by_source_form": consumed_by_source_form,
    }


def apply_pair_pipeline_rules(working_pairs: list[PipelineItem]) -> PairPipelineResult:
    remaining_items = list(working_pairs)
    bucket_results: dict[str, BucketResult] = {}
    consumed_by_source_form: dict[int, str] = {}

    for definition in bucket_definitions_by_phase("pair_pipeline"):
        input_items = remaining_items
        selected_items: list[PipelineItem] = []

        for rule in definition.matching_rules:
            result = rule.match_pairs(input_items, definition.name)
            selected_items.extend(result["selected_items"])
            remaining_items = result["remaining_items"]

        consumption_rule = definition.consumption_rule
        consumption: PairConsumption = (
            consumption_rule.consume_pairs(selected_items, remaining_items)
            if consumption_rule is not None
            else empty_pair_consumption(remaining_items)
        )
        remaining_items = consumption["remaining_items"]
        for source_form_id in consumption["consumed_source_form_ids"]:
            consumed_by_source_form[source_form_id] = definition.name

        bucket_results[definition.name] = pair_pipeline_bucket_result(
            bucket=definition.name,
            phase=definition.phase,
            input_items=input_items,
            selected_items=selected_items,
            consumption=consumption,
        )

    for definition in bucket_definitions_by_phase("terminal"):
        input_items = remaining_items
        rule = definition.matching_rules[0]
        result = rule.match_pairs(input_items, definition.name)
        selected_items = result["selected_items"]
        consumption_rule = definition.consumption_rule
        consumption: PairConsumption = (
            consumption_rule.consume_pairs(selected_items, result["remaining_items"])
            if consumption_rule is not None
            else empty_pair_consumption(result["remaining_items"])
        )
        remaining_items = consumption["remaining_items"]
        for source_form_id in consumption["consumed_source_form_ids"]:
            consumed_by_source_form[source_form_id] = definition.name

        bucket_results[definition.name] = pair_pipeline_bucket_result(
            bucket=definition.name,
            phase=definition.phase,
            input_items=input_items,
            selected_items=selected_items,
            consumption=consumption,
            items_after_consumption=selected_items,
        )

    return {
        "bucket_results": bucket_results,
        "consumed_by_source_form": consumed_by_source_form,
        "remaining_items": remaining_items,
    }


def validate_pair_pipeline(
    initial_matching_pair_count: int,
    bucket_results: dict[str, BucketResult],
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


def enrich_state(
    master_state: LexiconState,
    input_label: str,
    output_path: Path | None,
    hsk_data_dir: Path,
    frequency_list_path: Path,
) -> XiehanziEnrichmentResult:
    base_snapshot = LexiconBaseSnapshot.from_state(master_state)
    base_words = list(master_state.sorted_words())
    base_word_index = {word.simplified: word for word in master_state.sorted_words()}

    raw_entries = load_hanzi_entries(hsk_data_dir=hsk_data_dir)
    deck_entries, dropped_duplicates = dedupe_entries(raw_entries)
    matching_pipeline = build_matching_pipeline(master_state, deck_entries)
    matching_report = build_matching_report(
        raw_entries=raw_entries,
        deck_entries=deck_entries,
        dropped_duplicates=dropped_duplicates,
        pipeline=matching_pipeline,
    )

    missing_raw_entries = [entry for entry in raw_entries if entry["simplified"] not in base_word_index]
    state_consumption_rules = tuple(
        definition.state_consumption_rule
        for definition in bucket_definitions_by_priority()
        if definition.state_consumption_rule is not None
    )
    pipeline_enrichment = apply_pipeline_enrichment_to_state(
        master_state,
        deck_entries,
        matching_pipeline,
        state_consumption_rules,
    )
    missing_deck_entries = pipeline_enrichment["missing_deck_entries"]
    synthetic_words = pipeline_enrichment["synthetic_words"]
    form_stats = pipeline_enrichment["form_stats"]
    frequency_enrichment = apply_frequency_enrichment_to_state(master_state, frequency_list_path)
    erhua_definition_enrichment = apply_erhua_definition_enrichment_to_state(master_state)
    master_state.hanzi_dropped_duplicates = dropped_duplicates

    enrichment_metadata = LexiconEnrichmentMetadata(
        name="hanzi New HSK (2025)",
        fields=tuple(HANZI_FIELDS),
        hsk_data_dir=hsk_data_dir,
        frequency_list=frequency_list_path,
        frequency_tags=tuple(f"freq:top{threshold}" for threshold in TOP_FREQUENCY_THRESHOLDS),
        dedupe_key=HANZI_DEDUPE_KEY,
    )
    summary = build_enrichment_summary(
        base_words=base_words,
        total_words=len(master_state.words),
        synthetic_words=synthetic_words,
        raw_entries=raw_entries,
        deck_entries=deck_entries,
        dropped_duplicates=dropped_duplicates,
        missing_raw_entries=missing_raw_entries,
        missing_deck_entries=missing_deck_entries,
        form_stats=form_stats,
        frequency_enrichment=frequency_enrichment,
        erhua_definition_enrichment=erhua_definition_enrichment,
    )
    enriched = master_state.to_enriched_json(
        base=base_snapshot,
        enrichment=enrichment_metadata,
        summary=summary,
    )

    report = build_enrichment_report(
        input_label=input_label,
        output_path=output_path,
        enriched=enriched,
        matching_report=matching_report,
        pipeline_enrichment=pipeline_enrichment,
        frequency_enrichment=frequency_enrichment,
        erhua_definition_enrichment=erhua_definition_enrichment,
        missing_raw_entries=missing_raw_entries,
        missing_deck_entries=missing_deck_entries,
        synthetic_words=synthetic_words,
        form_stats=form_stats,
        dropped_duplicates=dropped_duplicates,
    )

    if output_path is not None:
        write_json(output_path, enriched)
    return XiehanziEnrichmentResult(
        enriched=enriched,
        enrichment_report=report,
        matching_report=matching_report,
    )


def load_master_state(master_db_path: Path) -> LexiconState:
    return LexiconState.from_master_json(json.loads(master_db_path.read_text(encoding="utf-8")))


def enrich_database(
    master_db_path: Path,
    output_path: Path,
    hsk_data_dir: Path,
    frequency_list_path: Path,
) -> XiehanziEnrichmentResult:
    return enrich_state(
        master_state=load_master_state(master_db_path),
        input_label=str(master_db_path),
        output_path=output_path,
        hsk_data_dir=hsk_data_dir,
        frequency_list_path=frequency_list_path,
    )
