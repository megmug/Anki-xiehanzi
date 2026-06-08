"""Shared xiehanzi matching-pipeline data helpers.

The pipeline still serializes report items as dictionaries, but pair identity
and bucket counting belong to the pipeline model rather than to an individual
matching or consumption rule module.
"""

from __future__ import annotations

from typing import Any


PairId = tuple[int, int]
PipelineItem = dict[str, Any]
PipelineResult = dict[str, Any]


def pair_source_form_id(item: PipelineItem) -> int:
    return int(item["context"]["source_form_id"])


def pair_candidate_index(item: PipelineItem) -> int:
    return int(item["context"]["candidate_index_for_source"])


def matching_pair_identity(item: PipelineItem) -> PairId | None:
    if "dictionary" not in item:
        return None
    return (pair_source_form_id(item), pair_candidate_index(item))


def bucket_source_form_ids(items: list[PipelineItem]) -> set[int]:
    return {pair_source_form_id(item) for item in items}


def bucket_matching_pair_count(items: list[PipelineItem]) -> int:
    return sum(1 for item in items if "dictionary" in item)


def group_pairs_by_source_form(working_pairs: list[PipelineItem]) -> dict[int, list[PipelineItem]]:
    pairs_by_source_form: dict[int, list[PipelineItem]] = {}
    for pair in working_pairs:
        pairs_by_source_form.setdefault(pair_source_form_id(pair), []).append(pair)
    return pairs_by_source_form


def empty_source_prelude_consumption(remaining_source_form_ids: set[int]) -> PipelineResult:
    return {
        "consumed_source_form_ids": set(),
        "consumed_source_form_count": 0,
        "consumed_matching_pair_count": 0,
        "remaining_source_form_count": len(remaining_source_form_ids),
    }


def empty_pair_consumption(remaining_items: list[PipelineItem]) -> PipelineResult:
    return {
        "consumed_source_form_ids": set(),
        "consumed_source_form_count": 0,
        "consumed_matching_pair_count": 0,
        "removed_from_remaining_matching_pair_count": 0,
        "remaining_items": remaining_items,
    }


def source_prelude_bucket_result(
    *,
    bucket: str,
    phase: str,
    input_source_form_count: int,
    selected_items: list[PipelineItem],
    consumption: PipelineResult,
) -> PipelineResult:
    return {
        "phase": phase,
        "bucket": bucket,
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


def pair_pipeline_bucket_result(
    *,
    bucket: str,
    phase: str,
    input_items: list[PipelineItem],
    selected_items: list[PipelineItem],
    consumption: PipelineResult,
    items_after_consumption: list[PipelineItem] | None = None,
) -> PipelineResult:
    remaining_items = consumption["remaining_items"]
    return {
        "phase": phase,
        "bucket": bucket,
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
        "items_after_consumption": [] if items_after_consumption is None else items_after_consumption,
    }
