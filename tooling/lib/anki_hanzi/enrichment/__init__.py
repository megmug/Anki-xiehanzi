"""Top-level lexicon enrichment orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anki_hanzi.enrichment.frequency import (
    DEFAULT_FREQUENCY_LIST,
    TOP_FREQUENCY_THRESHOLDS,
    apply_frequency_enrichment_to_state,
)
from anki_hanzi.enrichment.hsk import (
    DEFAULT_HSK_DATA_DIR,
    HANZI_DEDUPE_KEY,
    apply_hsk_enrichment_to_state,
)
from anki_hanzi.enrichment.yct import (
    DEFAULT_YCT_DATA_DIR,
    YCT_LEVELS,
    apply_yct_enrichment_to_state,
)
from anki_hanzi.json_io import write_json
from anki_hanzi.lexicon import (
    LexiconBaseSnapshot,
    LexiconEnrichmentMetadata,
    LexiconState,
)
from anki_hanzi.enrichment.erhua import apply_erhua_definition_enrichment_to_state


@dataclass(frozen=True)
class LexiconEnrichmentResult:
    enriched: dict[str, Any]
    enrichment_report: dict[str, Any]
    matching_report: dict[str, Any]


def build_lexicon_enrichment_summary(
    *,
    hsk_summary: dict[str, Any],
    frequency_enrichment: dict[str, Any],
    yct_enrichment: dict[str, Any],
    erhua_definition_enrichment: dict[str, Any],
) -> dict[str, Any]:
    return {
        **hsk_summary,
        "frequency_tags_by_word": frequency_enrichment["tagged_words_by_threshold"],
        "frequency_tags_by_form": frequency_enrichment["tagged_forms_by_threshold"],
        "yct_source_terms": yct_enrichment["source_terms"],
        "yct_matched_terms": yct_enrichment["matched_terms"],
        "yct_unmatched_terms": yct_enrichment["unmatched_terms"],
        "yct_tags_by_word": yct_enrichment["tagged_words_by_level"],
        "yct_tags_by_form": yct_enrichment["tagged_forms_by_level"],
        "erhua_variant_definitions": erhua_definition_enrichment["scanned_erhua_definitions"],
        "erhua_variant_definitions_resolved": erhua_definition_enrichment["resolved_erhua_definitions"],
        "erhua_variant_definitions_duplicate_only": erhua_definition_enrichment[
            "duplicate_only_erhua_definitions"
        ],
        "erhua_variant_definitions_unresolved": erhua_definition_enrichment["unresolved_erhua_definitions"],
    }


def build_lexicon_enrichment_report(
    *,
    input_label: str,
    output_path: Path | None,
    enriched: dict[str, Any],
    hsk_enrichment: dict[str, Any],
    frequency_enrichment: dict[str, Any],
    yct_enrichment: dict[str, Any],
    erhua_definition_enrichment: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "hanzi-enrichment-report-v1",
        "input": input_label,
        "output": str(output_path) if output_path is not None else None,
        "summary": enriched["summary"],
        "hsk_enrichment": hsk_enrichment,
        "frequency_enrichment": frequency_enrichment,
        "yct_enrichment": yct_enrichment,
        "erhua_definition_enrichment": erhua_definition_enrichment,
        "samples": hsk_enrichment["samples"],
    }


def enrich_state(
    master_state: LexiconState,
    input_label: str,
    output_path: Path | None,
    hsk_data_dir: Path,
    frequency_list_path: Path,
    yct_data_dir: Path,
) -> LexiconEnrichmentResult:
    base_snapshot = LexiconBaseSnapshot.from_state(master_state)

    hsk_result = apply_hsk_enrichment_to_state(
        master_state,
        input_label=input_label,
        hsk_data_dir=hsk_data_dir,
    )
    frequency_enrichment = apply_frequency_enrichment_to_state(master_state, frequency_list_path)
    yct_enrichment = apply_yct_enrichment_to_state(master_state, yct_data_dir)
    erhua_definition_enrichment = apply_erhua_definition_enrichment_to_state(master_state)

    summary = build_lexicon_enrichment_summary(
        hsk_summary=hsk_result.summary,
        frequency_enrichment=frequency_enrichment,
        yct_enrichment=yct_enrichment,
        erhua_definition_enrichment=erhua_definition_enrichment,
    )
    enrichment_metadata = LexiconEnrichmentMetadata(
        name="hanzi lexicon enrichment",
        fields=("hsk", "frequency", "yct", "erhua"),
        hsk_data_dir=hsk_data_dir,
        frequency_list=frequency_list_path,
        frequency_tags=tuple(f"freq:top{threshold}" for threshold in TOP_FREQUENCY_THRESHOLDS),
        yct_data_dir=yct_data_dir,
        yct_tags=tuple(f"yct:{level}" for level in YCT_LEVELS),
        dedupe_key=HANZI_DEDUPE_KEY,
    )
    enriched = master_state.to_enriched_json(
        base=base_snapshot,
        enrichment=enrichment_metadata,
        summary=summary,
    )
    report = build_lexicon_enrichment_report(
        input_label=input_label,
        output_path=output_path,
        enriched=enriched,
        hsk_enrichment=hsk_result.enrichment_report,
        frequency_enrichment=frequency_enrichment,
        yct_enrichment=yct_enrichment,
        erhua_definition_enrichment=erhua_definition_enrichment,
    )

    if output_path is not None:
        write_json(output_path, enriched)
    return LexiconEnrichmentResult(
        enriched=enriched,
        enrichment_report=report,
        matching_report=hsk_result.matching_report,
    )


def load_master_state(master_db_path: Path) -> LexiconState:
    return LexiconState.from_master_json(json.loads(master_db_path.read_text(encoding="utf-8")))


def enrich_database(
    master_db_path: Path,
    output_path: Path,
    hsk_data_dir: Path = DEFAULT_HSK_DATA_DIR,
    frequency_list_path: Path = DEFAULT_FREQUENCY_LIST,
    yct_data_dir: Path = DEFAULT_YCT_DATA_DIR,
) -> LexiconEnrichmentResult:
    return enrich_state(
        master_state=load_master_state(master_db_path),
        input_label=str(master_db_path),
        output_path=output_path,
        hsk_data_dir=hsk_data_dir,
        frequency_list_path=frequency_list_path,
        yct_data_dir=yct_data_dir,
    )


__all__ = [
    "DEFAULT_FREQUENCY_LIST",
    "DEFAULT_HSK_DATA_DIR",
    "DEFAULT_YCT_DATA_DIR",
    "HANZI_DEDUPE_KEY",
    "LexiconEnrichmentResult",
    "enrich_database",
    "enrich_state",
]
