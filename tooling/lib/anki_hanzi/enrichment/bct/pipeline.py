"""Apply BCT matching buckets and tag consumption."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any

from anki_hanzi.enrichment.bct.buckets import bucket_definitions_by_priority
from anki_hanzi.enrichment.bct.matching import diagnose_unresolved_term
from anki_hanzi.enrichment.bct.model import (
    BctBucketDefinition,
    BctBucketMatch,
    BctSourceTerm,
    BctUnresolvedTerm,
)
from anki_hanzi.enrichment.bct.source import (
    BCT_LEVELS,
    duplicate_source_terms,
    group_bct_source_terms,
    load_bct_entries,
)
from anki_hanzi.lexicon import LexiconState


def consume_bct_match(match: BctBucketMatch) -> dict[str, Any]:
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

    return {
        "source_word": match.source.word,
        "levels": list(match.source.levels),
        "target_word_count": target_word_count,
        "target_form_count": target_form_count,
    }


def apply_matching_bucket(
    state: LexiconState,
    bucket: BctBucketDefinition,
    remaining_terms: list[BctSourceTerm],
) -> tuple[list[BctBucketMatch], list[BctSourceTerm]]:
    if bucket.matching_rule is None:
        return [], remaining_terms

    selected_matches: list[BctBucketMatch] = []
    unresolved_terms: list[BctSourceTerm] = []

    for source_term in remaining_terms:
        match = bucket.matching_rule.match(state, source_term)
        if match is None:
            unresolved_terms.append(source_term)
        else:
            selected_matches.append(match)

    return selected_matches, unresolved_terms


def matching_bucket_report(
    bucket: BctBucketDefinition,
    input_term_count: int,
    matches: list[BctBucketMatch],
    remaining_term_count: int,
) -> dict[str, Any]:
    rule = bucket.matching_rule
    report = {
        "bucket": bucket.name,
        "priority": bucket.priority,
        "description": bucket.description,
        "matching_rule": rule.name if rule is not None else None,
        "matching_rule_description": rule.description if rule is not None else None,
        "consumption_rule": bucket.consumption_rule if rule is not None else None,
        "input_terms": input_term_count,
        "matched_terms": len(matches),
        "remaining_terms_after_consumption": remaining_term_count,
        "report_items": bucket.report_items,
    }
    if bucket.report_items:
        report["items"] = [match.to_report() for match in matches]
    return report


def unresolved_bucket_report(
    bucket: BctBucketDefinition,
    unresolved_terms: list[BctUnresolvedTerm],
) -> dict[str, Any]:
    return {
        "bucket": bucket.name,
        "priority": bucket.priority,
        "description": bucket.description,
        "matching_rule": None,
        "matching_rule_description": None,
        "consumption_rule": bucket.consumption_rule,
        "input_terms": len(unresolved_terms),
        "matched_terms": 0,
        "unresolved_terms": len(unresolved_terms),
        "remaining_terms_after_consumption": len(unresolved_terms),
        "report_items": bucket.report_items,
        "items": [term.to_report() for term in unresolved_terms] if bucket.report_items else [],
    }


def apply_bct_enrichment_to_state(state: LexiconState, bct_data_dir: Path) -> dict[str, Any]:
    entries = load_bct_entries(bct_data_dir)
    source_terms = group_bct_source_terms(entries)
    remaining_terms = list(source_terms)

    tagged_words_by_level = {level: 0 for level in BCT_LEVELS}
    tagged_forms_by_level = {level: 0 for level in BCT_LEVELS}
    match_methods = Counter()
    ignored_methods = Counter()
    ignored_by_reason = Counter()
    unmatched_by_reason = Counter()
    matched_terms: list[str] = []
    ignored_terms: list[dict[str, Any]] = []
    unmatched_terms: list[dict[str, Any]] = []
    case_disambiguated_matches: list[dict[str, Any]] = []
    bucket_reports: dict[str, dict[str, Any]] = {}

    for bucket in bucket_definitions_by_priority():
        if bucket.name == "unresolved":
            unresolved = [diagnose_unresolved_term(state, term) for term in remaining_terms]
            unmatched_terms = [term.to_report() for term in unresolved]
            for term in unresolved:
                unmatched_by_reason[term.reason] += 1
            bucket_reports[bucket.name] = unresolved_bucket_report(bucket, unresolved)
            if unresolved:
                raise ValueError(
                    "BCT enrichment left unresolved source terms:\n"
                    + json.dumps(unmatched_terms, ensure_ascii=False, indent=2)
                )
            continue

        input_term_count = len(remaining_terms)
        matches, remaining_terms = apply_matching_bucket(state, bucket, remaining_terms)
        bucket_reports[bucket.name] = matching_bucket_report(
            bucket=bucket,
            input_term_count=input_term_count,
            matches=matches,
            remaining_term_count=len(remaining_terms),
        )

        for match in matches:
            if bucket.consumption_rule == "apply_bct_level_tags":
                consume_bct_match(match)
                matched_terms.append(match.source.word)
                match_methods[match.method] += 1
            else:
                ignored_terms.append(match.to_report())
                ignored_methods[match.method] += 1
                ignored_by_reason[match.report.get("reason", match.method)] += 1

            if match.method == "exact_word_unique_lowercase_form":
                case_disambiguated_matches.append(
                    {
                        "word": match.source.word,
                        "levels": list(match.source.levels),
                        "selected_pinyin": match.report["selected_pinyin"],
                        "ignored_pinyin": match.report["ignored_pinyin"],
                    }
                )

            target_form_count = sum(len(target.forms) for target in match.targets)
            for level in match.source.levels:
                if bucket.consumption_rule == "apply_bct_level_tags":
                    tagged_words_by_level[level] += 1
                    tagged_forms_by_level[level] += target_form_count

    duplicate_terms = duplicate_source_terms(source_terms)

    return {
        "stage": "bct_enrichment",
        "source": str(bct_data_dir),
        "levels": list(BCT_LEVELS),
        "matching_policy": (
            "Ordered BCT matching buckets consume source terms by priority. "
            "Consumed terms only add BCT level tags; unresolved terms fail "
            "the build so new source notation cannot be missed silently."
        ),
        "source_entries": len(entries),
        "source_terms": len(source_terms),
        "duplicate_source_terms": len(duplicate_terms),
        "matched_terms": len(matched_terms),
        "ignored_terms": len(ignored_terms),
        "unmatched_terms": len(unmatched_terms),
        "match_methods": dict(sorted(match_methods.items())),
        "ignored_methods": dict(sorted(ignored_methods.items())),
        "ignored_by_reason": dict(sorted(ignored_by_reason.items())),
        "unmatched_by_reason": dict(sorted(unmatched_by_reason.items())),
        "buckets": bucket_reports,
        "case_disambiguated_matches": case_disambiguated_matches,
        "tagged_words_by_level": tagged_words_by_level,
        "tagged_forms_by_level": tagged_forms_by_level,
        "ignored_terms_detail": ignored_terms,
        "ignored_term_samples": ignored_terms[:50],
        "unmatched_terms_detail": unmatched_terms,
        "unmatched_term_samples": unmatched_terms[:50],
    }
