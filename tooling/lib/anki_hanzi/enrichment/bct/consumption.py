"""Consumption rules for matched BCT source terms."""

from __future__ import annotations

from anki_hanzi.enrichment.bct.model import BctBucketMatch, BctConsumptionResult


def apply_bct_level_tags(match: BctBucketMatch) -> BctConsumptionResult:
    tags = match.source.tags()
    target_word_count = 0
    target_form_count = 0

    for target in match.targets:
        if target.tag_word:
            target.word.add_tags(tags)
            target_word_count += 1
        for form in target.forms:
            form.add_tags(tags)
            target_form_count += 1

    return BctConsumptionResult(
        tags_applied=True,
        target_word_count=target_word_count,
        target_form_count=target_form_count,
    )


def ignore_missing_dictionary_word(_match: BctBucketMatch) -> BctConsumptionResult:
    return BctConsumptionResult(tags_applied=False)


def ignore_non_lexical_pattern(_match: BctBucketMatch) -> BctConsumptionResult:
    return BctConsumptionResult(tags_applied=False)
