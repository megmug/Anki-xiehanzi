"""Bucket specifications for BCT tag enrichment."""

from __future__ import annotations

from anki_hanzi.enrichment.bct.consumption import (
    apply_bct_level_tags,
    ignore_missing_dictionary_word,
    ignore_non_lexical_pattern,
)
from anki_hanzi.enrichment.bct.matching import (
    EXACT_WORD_SINGLE_FORM_RULE,
    EXACT_WORD_UNIQUE_LOWERCASE_FORM_RULE,
    MANUAL_SOURCE_FORM_TARGETS_RULE,
    MISSING_DICTIONARY_WORD_RULE,
    NON_LEXICAL_PATTERN_RULE,
    STRUCTURED_SOURCE_TERM_VARIANTS_RULE,
    UNIQUE_DICTIONARY_WORD_ALL_FORMS_RULE,
)
from anki_hanzi.enrichment.bct.model import BctBucketDefinition


BUCKET_DEFINITIONS = {
    "exact_word_single_form": BctBucketDefinition(
        name="exact_word_single_form",
        priority=10,
        description=(
            "Exact simplified BCT term match where the dictionary target has one "
            "form. The source term is consumed by adding the BCT level tags to "
            "the word and its form."
        ),
        report_items=False,
        matching_rule=EXACT_WORD_SINGLE_FORM_RULE,
        consumption_rule=apply_bct_level_tags,
    ),
    "exact_word_unique_lowercase_form": BctBucketDefinition(
        name="exact_word_unique_lowercase_form",
        priority=20,
        description=(
            "Exact simplified BCT term match where dictionary casing variants "
            "exist, and exactly one lowercase Pinyin form can be selected. The "
            "source term is consumed by adding BCT level tags only to that form."
        ),
        report_items=False,
        matching_rule=EXACT_WORD_UNIQUE_LOWERCASE_FORM_RULE,
        consumption_rule=apply_bct_level_tags,
    ),
    "structured_source_term_variants": BctBucketDefinition(
        name="structured_source_term_variants",
        priority=30,
        description=(
            "Explicit BCT source notation is expanded locally and each expanded "
            "target must resolve to exactly one safe dictionary form. The source "
            "term is consumed by adding BCT level tags to all resolved forms."
        ),
        report_items=True,
        matching_rule=STRUCTURED_SOURCE_TERM_VARIANTS_RULE,
        consumption_rule=apply_bct_level_tags,
    ),
    "manual_source_form_targets": BctBucketDefinition(
        name="manual_source_form_targets",
        priority=40,
        description=(
            "Curated BCT source notation whose exact dictionary forms are known. "
            "The source term is consumed by adding BCT level tags only to the "
            "configured simplified+Pinyin target forms."
        ),
        report_items=True,
        matching_rule=MANUAL_SOURCE_FORM_TARGETS_RULE,
        consumption_rule=apply_bct_level_tags,
    ),
    "unique_dictionary_word_all_forms": BctBucketDefinition(
        name="unique_dictionary_word_all_forms",
        priority=800,
        description=(
            "BCT source term points to exactly one dictionary word, but multiple "
            "dictionary forms remain after higher-priority form-specific rules. "
            "BCT is treated as word-level evidence here, so the source term is "
            "consumed by adding BCT level tags to the word and all forms."
        ),
        report_items=True,
        matching_rule=UNIQUE_DICTIONARY_WORD_ALL_FORMS_RULE,
        consumption_rule=apply_bct_level_tags,
    ),
    "missing_dictionary_word": BctBucketDefinition(
        name="missing_dictionary_word",
        priority=900,
        description=(
            "Plain Hanzi BCT source term has no exact dictionary word. The term "
            "is intentionally consumed without modifying the lexicon and is "
            "logged here instead of remaining unresolved."
        ),
        report_items=True,
        matching_rule=MISSING_DICTIONARY_WORD_RULE,
        consumption_rule=ignore_missing_dictionary_word,
    ),
    "non_lexical_pattern": BctBucketDefinition(
        name="non_lexical_pattern",
        priority=910,
        description=(
            "BCT source term contains the explicit ellipsis construction marker "
            "`……`, which denotes a grammar pattern rather than a lexical "
            "dictionary word. The term is intentionally consumed without "
            "modifying the lexicon and logged here."
        ),
        report_items=True,
        matching_rule=NON_LEXICAL_PATTERN_RULE,
        consumption_rule=ignore_non_lexical_pattern,
    ),
    "unresolved": BctBucketDefinition(
        name="unresolved",
        priority=1000,
        description=(
            "No higher-priority BCT bucket resolved the source term. These terms "
            "are reported for future matching-rule work and fail the build."
        ),
        report_items=True,
        consumption_rule=None,
    ),
}


def bucket_definitions_by_priority() -> list[BctBucketDefinition]:
    return sorted(BUCKET_DEFINITIONS.values(), key=lambda definition: definition.priority)
