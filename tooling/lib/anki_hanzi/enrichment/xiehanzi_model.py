"""Shared xiehanzi matching-pipeline data helpers.

The pipeline still serializes report items as dictionaries, but pair identity
and bucket counting belong to the pipeline model rather than to an individual
matching or consumption rule module.
"""

from __future__ import annotations

from typing import Any


PairId = tuple[int, int]
PipelineItem = dict[str, Any]


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
