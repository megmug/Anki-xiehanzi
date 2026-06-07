"""Matching rules and pair helpers for xiehanzi-to-CC-CEDICT alignment."""

from __future__ import annotations

import re
from collections.abc import Callable
from collections import Counter
from dataclasses import dataclass
from typing import Any

from anki_hanzi.lexicon import LexiconForm, LexiconState, LexiconWord
from anki_hanzi.enrichment.xiehanzi_rule_helpers import (
    definition_sets_exact,
    definitions_from_meaning_html,
    normalize_matching_definition,
    normalize_pinyin_u_variants,
    pinyin_rule_kind as classify_pinyin,
    pinyin_rule_readings as pinyin_readings,
    strip_html_text,
)
from anki_hanzi.enrichment.xiehanzi_consumption import bucket_source_form_ids, pair_source_form_id


RuleHandler = Callable[..., dict[str, Any]]

PINYIN_NUMBERED_TOKEN_RE = re.compile(r"[A-Za-züÜv:]+[1-5]?")
ALSO_PR_RE = re.compile(r"also\s+pr\.\s*\[([^\]]+)\]", re.IGNORECASE)
PINYIN_BLOCK_RE = re.compile(
    r'<span\s+class="pinYinWrapper"[^>]*>(?P<pinyin>.*?)</span>\s*<ul>(?P<definitions>.*?)</ul>',
    re.IGNORECASE | re.DOTALL,
)
SEMICOLON_SPLIT_RE = re.compile(r"\s*;\s*")
MANUAL_PINYIN_OVERRIDES = {
    ("标致", "7-9"): {
        "pinyin": "biao1zhi5",
        "reason": "known xiehanzi TSV pinyin defect",
    },
    ("疼爱", "7-9"): {
        "pinyin": "teng2ai4",
        "reason": "known xiehanzi TSV pinyin defect",
    },
    ("脚踏实地", "7-9"): {
        "pinyin": "jiao3ta4shi2di4",
        "reason": "known xiehanzi TSV pinyin defect",
    },
    ("蹊跷", "7-9"): {
        "pinyin": "qi1qiao1",
        "reason": "known xiehanzi TSV pinyin defect",
    },
}


@dataclass(frozen=True)
class MatchingRuleDefinition:
    name: str
    scope: str
    requires: tuple[str, ...]
    handler: RuleHandler
    selected_pair: str | None = None


@dataclass(frozen=True)
class TargetFormRef:
    word_key: str
    form_key: str
    word: LexiconWord
    form: LexiconForm


def form_pinyin_reading_string(form: LexiconForm) -> str:
    return " / ".join(form.pinyin_readings or [form.pinyin])


def source_entry_report(entry: dict[str, Any]) -> dict[str, Any]:
    report = {
        "simplified": entry["simplified"],
        "traditional": entry["traditional"],
        "pinyin": entry["pinyin"],
        "zhuyin": entry["zhuyin"],
        "deck_level": entry["deck_level"],
        "raw_level": entry["raw_level"],
        "source": entry["source"],
        "tags": list(entry["tags"]),
    }
    if entry.get("raw_pinyin") and entry["raw_pinyin"] != entry["pinyin"]:
        report["raw_pinyin"] = entry["raw_pinyin"]
    return report


def candidate_report(entry: dict[str, Any], target: TargetFormRef) -> dict[str, Any]:
    word = target.word
    form = target.form
    dictionary_pinyin = form_pinyin_reading_string(form)
    source_definitions = definitions_from_meaning_html(entry["meaning_html"])
    return {
        "target": {
            "word_key": target.word_key,
            "form_key": target.form_key,
        },
        "dictionary": {
            "simplified": word.simplified,
            "pinyin": dictionary_pinyin,
            "primary_pinyin": form.pinyin,
            "pinyin_readings": list(form.pinyin_readings),
            "traditional_variants": list(form.traditional_variants),
            "tags": list(form.tags),
            "definitions": list(form.definitions),
        },
        "source_definitions": source_definitions,
    }


def entry_candidate_summary(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "candidate_count": len(candidates),
    }


def simplified_matching_key(value: str) -> str:
    return str(value or "")


def build_target_form_index(state: LexiconState) -> dict[str, list[TargetFormRef]]:
    target_form_index: dict[str, list[TargetFormRef]] = {}
    for word_key in sorted(state.words):
        word = state.words[word_key]
        key = simplified_matching_key(word.simplified)
        if not key:
            continue
        target_form_index.setdefault(key, []).extend(
            TargetFormRef(word_key=word_key, form_key=form_key, word=word, form=form)
            for form_key, form in word.forms.items()
        )
    return target_form_index


def empty_entry_candidate_summary() -> dict[str, Any]:
    return {
        "candidate_count": 0,
    }


def source_matching_entry_report(entry: dict[str, Any], source_form_id: int) -> dict[str, Any]:
    return {
        "source_form_id": source_form_id,
        "source_key": simplified_matching_key(entry["simplified"]),
        "entry": entry,
        "source_entry": source_entry_report(entry),
        "candidate_summary": empty_entry_candidate_summary(),
        "candidates": [],
    }


def build_source_entry_reports(deck_entries: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {
        source_form_id: source_matching_entry_report(entry, source_form_id)
        for source_form_id, entry in enumerate(deck_entries)
    }


def candidate_count_bucket(count: int) -> str:
    if count >= 4:
        return "4+"
    return str(count)


def matching_pair_report(
    entry_report: dict[str, Any],
    candidate: dict[str, Any],
    *,
    bucket: str,
    candidate_index: int,
    matching_rule: str,
) -> dict[str, Any]:
    candidate_summary = entry_report["candidate_summary"]
    return {
        "source": entry_report["source_entry"],
        "target": candidate["target"],
        "dictionary": candidate["dictionary"],
        "source_definitions": candidate["source_definitions"],
        "source_meaning_html": entry_report["entry"]["meaning_html"],
        "context": {
            "source_form_id": entry_report["source_form_id"],
            "candidate_count_for_source": candidate_summary["candidate_count"],
            "candidate_index_for_source": candidate_index,
        },
        "bucket": bucket,
        "matching_rule": matching_rule,
    }


def missing_dictionary_word_report(entry_report: dict[str, Any], *, bucket: str, matching_rule: str) -> dict[str, Any]:
    return {
        "source": entry_report["source_entry"],
        "context": {
            "source_form_id": entry_report["source_form_id"],
            "candidate_count_for_source": 0,
        },
        "bucket": bucket,
        "matching_rule": matching_rule,
    }


def matching_pair_identity(item: dict[str, Any]) -> tuple[int, int] | None:
    if "dictionary" not in item:
        return None
    return (pair_source_form_id(item), int(item["context"]["candidate_index_for_source"]))


def matching_pair_for_bucket(item: dict[str, Any], *, bucket: str, matching_rule: str) -> dict[str, Any]:
    return {
        **item,
        "bucket": bucket,
        "matching_rule": matching_rule,
    }


def manual_pinyin_override_for_source(source: dict[str, Any]) -> dict[str, str] | None:
    override = MANUAL_PINYIN_OVERRIDES.get((source["simplified"], source["deck_level"]))
    if override is None:
        return None
    return {
        "raw_pinyin": source["pinyin"],
        "override_pinyin": override["pinyin"],
        "reason": override["reason"],
    }


def matching_pair_with_manual_pinyin_override(
    item: dict[str, Any],
    override: dict[str, str],
    *,
    bucket: str,
    matching_rule: str,
) -> dict[str, Any]:
    pair = matching_pair_for_bucket(item, bucket=bucket, matching_rule=matching_rule)
    pair["context"] = {
        **pair["context"],
        "manual_pinyin_override": override,
    }
    return pair


def numbered_pinyin_tokens(value: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    for token in PINYIN_NUMBERED_TOKEN_RE.findall(value or ""):
        match = re.match(r"(.+?)([1-5])?$", token)
        if match is None:
            continue
        base = normalize_pinyin_u_variants(match.group(1)).casefold()
        tone = match.group(2) or ""
        tokens.append((base, tone))
    return tokens


def spoken_tone_variant_kinds(source_pinyin: str, dictionary_pinyin: str) -> tuple[str, ...]:
    kinds: set[str] = set()
    source_readings = pinyin_readings(source_pinyin)
    dictionary_readings = pinyin_readings(dictionary_pinyin)
    if len(source_readings) != len(dictionary_readings):
        return ()

    for source_reading, dictionary_reading in zip(source_readings, dictionary_readings):
        source_tokens = numbered_pinyin_tokens(source_reading.strict)
        dictionary_tokens = numbered_pinyin_tokens(dictionary_reading.strict)
        if len(source_tokens) != len(dictionary_tokens):
            return ()

        for (source_base, source_tone), (dictionary_base, dictionary_tone) in zip(
            source_tokens,
            dictionary_tokens,
        ):
            if source_base != dictionary_base:
                return ()
            if source_tone == dictionary_tone:
                continue
            if source_base == "yi" and source_tone in {"2", "4"} and dictionary_tone == "1":
                kinds.add("yi_sandhi")
                continue
            if source_base == "bu" and source_tone == "2" and dictionary_tone == "4":
                kinds.add("bu_sandhi")
                continue
            if {source_tone, dictionary_tone} & {"5"} and source_tone != dictionary_tone:
                kinds.add("neutral_tone_diff")
                continue
            return ()

    return tuple(sorted(kinds))


def matching_pair_with_spoken_tone_variant(
    item: dict[str, Any],
    kinds: tuple[str, ...],
    *,
    bucket: str,
    matching_rule: str,
) -> dict[str, Any]:
    pair = matching_pair_for_bucket(item, bucket=bucket, matching_rule=matching_rule)
    pair["context"] = {
        **pair["context"],
        "spoken_tone_variant": {
            "kinds": list(kinds),
        },
    }
    return pair


def unique_pinyin_reading_records(value: str) -> list[dict[str, str]]:
    readings: list[dict[str, str]] = []
    seen: set[str] = set()
    for reading in pinyin_readings(value):
        if reading.compact_lower in seen:
            continue
        readings.append(
            {
                "strict": reading.strict,
                "compact_lower": reading.compact_lower,
            }
        )
        seen.add(reading.compact_lower)
    return readings


def also_pr_definition_readings(definitions: list[str]) -> list[dict[str, str]]:
    readings: list[dict[str, str]] = []
    seen: set[str] = set()
    for definition in definitions:
        for value in ALSO_PR_RE.findall(definition or ""):
            for reading in unique_pinyin_reading_records(value):
                key = reading["compact_lower"]
                if key in seen:
                    continue
                readings.append(reading)
                seen.add(key)
    return readings


def also_pr_pinyin_context(pair: dict[str, Any]) -> dict[str, Any] | None:
    source_readings = unique_pinyin_reading_records(pair["source"]["pinyin"])
    dictionary_readings = unique_pinyin_reading_records(pair["dictionary"]["pinyin"])
    also_pr_readings = also_pr_definition_readings(list(pair["dictionary"].get("definitions", [])))
    source_keys = {reading["compact_lower"] for reading in source_readings}
    dictionary_keys = {reading["compact_lower"] for reading in dictionary_readings}
    also_pr_keys = {reading["compact_lower"] for reading in also_pr_readings}
    extra_source_readings = [
        reading
        for reading in source_readings
        if reading["compact_lower"] in also_pr_keys and reading["compact_lower"] not in dictionary_keys
    ]

    if not source_keys or not extra_source_readings:
        return None
    if not source_keys <= dictionary_keys | also_pr_keys:
        return None

    return {
        "source_readings": source_readings,
        "dictionary_readings": dictionary_readings,
        "also_pr_readings": also_pr_readings,
        "extra_source_readings": extra_source_readings,
    }


def exact_definition_also_pr_context(pair: dict[str, Any]) -> dict[str, Any] | None:
    if not pair_definition_sets_exact(pair):
        return None
    return also_pr_pinyin_context(pair)


def matching_pair_with_exact_definition_also_pr(
    item: dict[str, Any],
    also_pr_context: dict[str, Any],
    *,
    bucket: str,
    matching_rule: str,
) -> dict[str, Any]:
    pair = matching_pair_for_bucket(item, bucket=bucket, matching_rule=matching_rule)
    pair["context"] = {
        **pair["context"],
        "exact_definition_also_pr": also_pr_context,
    }
    return pair


def split_semicolon_definitions(definitions: list[str]) -> list[str]:
    split_definitions: list[str] = []
    seen: set[str] = set()
    for definition in definitions:
        for part in SEMICOLON_SPLIT_RE.split(definition):
            value = part.strip()
            if not value or value in seen:
                continue
            split_definitions.append(value)
            seen.add(value)
    return split_definitions


def semicolon_split_definition_set(definitions: list[str]) -> set[str]:
    values = {normalize_matching_definition(definition) for definition in split_semicolon_definitions(definitions)}
    values.discard("")
    return values


def semicolon_split_definition_sets_exact(left: list[str], right: list[str]) -> bool:
    left_set = semicolon_split_definition_set(left)
    right_set = semicolon_split_definition_set(right)
    return bool(left_set) and left_set == right_set


def semicolon_split_exact_definition_also_pr_context(pair: dict[str, Any]) -> dict[str, Any] | None:
    source_definitions = list(pair.get("source_definitions", []))
    dictionary_definitions = list(pair["dictionary"].get("definitions", []))
    if not semicolon_split_definition_sets_exact(source_definitions, dictionary_definitions):
        return None

    also_pr_context = also_pr_pinyin_context(pair)
    if also_pr_context is None:
        return None

    return {
        **also_pr_context,
        "source_expanded_definitions": split_semicolon_definitions(source_definitions),
        "dictionary_expanded_definitions": split_semicolon_definitions(dictionary_definitions),
    }


def matching_pair_with_semicolon_split_exact_definition_also_pr(
    item: dict[str, Any],
    context: dict[str, Any],
    *,
    bucket: str,
    matching_rule: str,
) -> dict[str, Any]:
    pair = matching_pair_for_bucket(item, bucket=bucket, matching_rule=matching_rule)
    pair["context"] = {
        **pair["context"],
        "semicolon_split_exact_definition_also_pr": context,
    }
    return pair


def source_html_subentries(meaning_html: str) -> list[dict[str, Any]]:
    subentries: list[dict[str, Any]] = []
    for index, match in enumerate(PINYIN_BLOCK_RE.finditer(meaning_html or ""), start=1):
        pinyin = strip_html_text(match.group("pinyin"))
        definitions = definitions_from_meaning_html(match.group("definitions"))
        if not pinyin or not definitions:
            continue
        subentries.append(
            {
                "index": index,
                "pinyin": pinyin,
                "definitions": definitions,
                "expanded_definitions": split_semicolon_definitions(definitions),
            }
        )
    return subentries


def html_subform_match_context(source_pairs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not source_pairs:
        return None

    source_meaning_html = str(source_pairs[0].get("source_meaning_html") or "")
    subentries = source_html_subentries(source_meaning_html)
    if not subentries:
        return None

    matches: list[dict[str, Any]] = []
    matched_pair_ids: set[tuple[int, int]] = set()
    for subentry in subentries:
        matching_pairs: list[dict[str, Any]] = []
        for pair in source_pairs:
            if classify_pinyin(subentry["pinyin"], pair["dictionary"]["pinyin"]) != "exact":
                continue
            if not semicolon_split_definition_sets_exact(
                list(subentry["definitions"]),
                list(pair["dictionary"].get("definitions", [])),
            ):
                continue
            matching_pairs.append(pair)

        if len(matching_pairs) != 1:
            return None

        pair = matching_pairs[0]
        pair_id = matching_pair_identity(pair)
        if pair_id is None or pair_id in matched_pair_ids:
            return None
        matched_pair_ids.add(pair_id)

        dictionary_definitions = list(pair["dictionary"].get("definitions", []))
        row_pinyin_match = classify_pinyin(pair["source"]["pinyin"], pair["dictionary"]["pinyin"])
        matches.append(
            {
                "subentry_index": subentry["index"],
                "subentry_pinyin": subentry["pinyin"],
                "subentry_definitions": list(subentry["definitions"]),
                "subentry_expanded_definitions": list(subentry["expanded_definitions"]),
                "target": pair["target"],
                "target_pinyin": pair["dictionary"]["pinyin"],
                "target_definitions": dictionary_definitions,
                "target_expanded_definitions": split_semicolon_definitions(dictionary_definitions),
                "row_pinyin_match": row_pinyin_match,
            }
        )

    source_pair_ids = {matching_pair_identity(pair) for pair in source_pairs}
    if matched_pair_ids != {pair_id for pair_id in source_pair_ids if pair_id is not None}:
        return None

    return {
        "source_subentry_count": len(subentries),
        "matched_target_count": len(matches),
        "row_pinyin": source_pairs[0]["source"]["pinyin"],
        "row_pinyin_matched_target_count": sum(
            1 for match in matches if match["row_pinyin_match"] in {"exact", "format_variant", "case_variant"}
        ),
        "matches": matches,
    }


def matching_pair_with_html_subform_definition_cover(
    item: dict[str, Any],
    context: dict[str, Any],
    *,
    bucket: str,
    matching_rule: str,
) -> dict[str, Any]:
    pair = matching_pair_for_bucket(item, bucket=bucket, matching_rule=matching_rule)
    pair["context"] = {
        **pair["context"],
        "html_subform_definition_cover": context,
    }
    return pair


def pair_pinyin_kind(pair: dict[str, Any]) -> str:
    return classify_pinyin(pair["source"]["pinyin"], pair["dictionary"]["pinyin"])


def pair_definition_sets_exact(pair: dict[str, Any]) -> bool:
    return definition_sets_exact(
        list(pair.get("source_definitions", [])),
        list(pair.get("dictionary", {}).get("definitions", [])),
    )


def match_missing_dictionary_word_sources(
    entry_reports_by_id: dict[int, dict[str, Any]],
    target_form_index: dict[str, list[TargetFormRef]],
    remaining_source_form_ids: set[int],
    bucket: str,
    matching_rule: str,
) -> dict[str, Any]:
    selected_items = [
        missing_dictionary_word_report(entry_reports_by_id[source_form_id], bucket=bucket, matching_rule=matching_rule)
        for source_form_id in sorted(remaining_source_form_ids)
        if entry_reports_by_id[source_form_id]["source_key"] not in target_form_index
    ]
    return {
        "selected_items": selected_items,
        "selected_source_form_ids": bucket_source_form_ids(selected_items),
    }


def materialize_simplified_match_pairs(
    entry_reports_by_id: dict[int, dict[str, Any]],
    target_form_index: dict[str, list[TargetFormRef]],
    source_form_ids: set[int],
) -> dict[str, Any]:
    working_pairs: list[dict[str, Any]] = []

    for source_form_id in sorted(source_form_ids):
        entry_report = entry_reports_by_id[source_form_id]
        entry = entry_report["entry"]
        target_refs = target_form_index.get(entry_report["source_key"], [])
        candidates = [candidate_report(entry, target) for target in target_refs]
        entry_report["candidates"] = candidates
        entry_report["candidate_summary"] = entry_candidate_summary(candidates)

        for candidate_index, candidate in enumerate(candidates, start=1):
            working_pairs.append(
                matching_pair_report(
                    entry_report,
                    candidate,
                    bucket="simplified_match_working_set",
                    candidate_index=candidate_index,
                    matching_rule="simplified_match",
                )
            )

    target_form_count = sum(len(target_refs) for target_refs in target_form_index.values())
    virtual_pair_count = len(source_form_ids) * target_form_count
    return {
        "working_pairs": working_pairs,
        "source_form_count": len(source_form_ids),
        "target_form_count": target_form_count,
        "virtual_pair_count": virtual_pair_count,
        "simplified_match_pair_count": len(working_pairs),
        "simplified_mismatch_pair_count": virtual_pair_count - len(working_pairs),
    }


def match_manual_pinyin_override_pairs(
    working_pairs: list[dict[str, Any]],
    bucket: str,
    matching_rule: str,
) -> dict[str, Any]:
    pairs_by_source_form: dict[int, list[dict[str, Any]]] = {}
    for pair in working_pairs:
        pairs_by_source_form.setdefault(pair_source_form_id(pair), []).append(pair)

    selected_pair_ids: set[tuple[int, int]] = set()
    overrides_by_pair_id: dict[tuple[int, int], dict[str, str]] = {}

    for source_pairs in pairs_by_source_form.values():
        override = manual_pinyin_override_for_source(source_pairs[0]["source"])
        if override is None:
            continue

        corrected_matching_pairs = [
            pair
            for pair in source_pairs
            if classify_pinyin(override["override_pinyin"], pair["dictionary"]["pinyin"]) in {"exact", "format_variant"}
        ]
        if len(corrected_matching_pairs) != 1:
            continue

        pair_id = matching_pair_identity(corrected_matching_pairs[0])
        if pair_id is not None:
            selected_pair_ids.add(pair_id)
            overrides_by_pair_id[pair_id] = override

    selected_items: list[dict[str, Any]] = []
    remaining_items: list[dict[str, Any]] = []
    for pair in working_pairs:
        pair_id = matching_pair_identity(pair)
        if pair_id in selected_pair_ids:
            selected_items.append(
                matching_pair_with_manual_pinyin_override(
                    pair,
                    overrides_by_pair_id[pair_id],
                    bucket=bucket,
                    matching_rule=matching_rule,
                )
            )
        else:
            remaining_items.append(pair)

    return {
        "selected_items": selected_items,
        "remaining_items": remaining_items,
        "selected_source_form_ids": bucket_source_form_ids(selected_items),
    }


def match_strict_pinyin_exact_unique_pairs(
    working_pairs: list[dict[str, Any]],
    bucket: str,
    matching_rule: str,
) -> dict[str, Any]:
    return match_unique_pinyin_kind_pairs(
        working_pairs,
        bucket=bucket,
        matching_rule=matching_rule,
        pinyin_kind="exact",
    )


def match_format_variant_unique_pairs(
    working_pairs: list[dict[str, Any]],
    bucket: str,
    matching_rule: str,
) -> dict[str, Any]:
    return match_unique_pinyin_kind_pairs(
        working_pairs,
        bucket=bucket,
        matching_rule=matching_rule,
        pinyin_kind="format_variant",
    )


def match_spoken_tone_variant_pairs(
    working_pairs: list[dict[str, Any]],
    bucket: str,
    matching_rule: str,
) -> dict[str, Any]:
    pairs_by_source_form: dict[int, list[dict[str, Any]]] = {}
    for pair in working_pairs:
        pairs_by_source_form.setdefault(pair_source_form_id(pair), []).append(pair)

    selected_pair_ids: set[tuple[int, int]] = set()
    kinds_by_pair_id: dict[tuple[int, int], tuple[str, ...]] = {}
    for source_pairs in pairs_by_source_form.values():
        matching_pairs: list[tuple[dict[str, Any], tuple[str, ...]]] = []
        for pair in source_pairs:
            if pair_pinyin_kind(pair) != "toneless":
                continue
            kinds = spoken_tone_variant_kinds(pair["source"]["pinyin"], pair["dictionary"]["pinyin"])
            if kinds:
                matching_pairs.append((pair, kinds))

        if len(matching_pairs) != 1:
            continue

        pair, kinds = matching_pairs[0]
        pair_id = matching_pair_identity(pair)
        if pair_id is not None:
            selected_pair_ids.add(pair_id)
            kinds_by_pair_id[pair_id] = kinds

    selected_items: list[dict[str, Any]] = []
    remaining_items: list[dict[str, Any]] = []
    for pair in working_pairs:
        pair_id = matching_pair_identity(pair)
        if pair_id in selected_pair_ids:
            selected_items.append(
                matching_pair_with_spoken_tone_variant(
                    pair,
                    kinds_by_pair_id[pair_id],
                    bucket=bucket,
                    matching_rule=matching_rule,
                )
            )
        else:
            remaining_items.append(pair)

    return {
        "selected_items": selected_items,
        "remaining_items": remaining_items,
        "selected_source_form_ids": bucket_source_form_ids(selected_items),
    }


def match_case_variant_exact_definition_pairs(
    working_pairs: list[dict[str, Any]],
    bucket: str,
    matching_rule: str,
) -> dict[str, Any]:
    pairs_by_source_form: dict[int, list[dict[str, Any]]] = {}
    for pair in working_pairs:
        pairs_by_source_form.setdefault(pair_source_form_id(pair), []).append(pair)

    selected_pair_ids: set[tuple[int, int]] = set()
    for source_pairs in pairs_by_source_form.values():
        matching_pairs = [
            pair
            for pair in source_pairs
            if pair_pinyin_kind(pair) == "case_variant" and pair_definition_sets_exact(pair)
        ]
        if len(matching_pairs) != 1:
            continue
        pair_id = matching_pair_identity(matching_pairs[0])
        if pair_id is not None:
            selected_pair_ids.add(pair_id)

    selected_items: list[dict[str, Any]] = []
    remaining_items: list[dict[str, Any]] = []
    for pair in working_pairs:
        pair_id = matching_pair_identity(pair)
        if pair_id in selected_pair_ids:
            selected_items.append(matching_pair_for_bucket(pair, bucket=bucket, matching_rule=matching_rule))
        else:
            remaining_items.append(pair)

    return {
        "selected_items": selected_items,
        "remaining_items": remaining_items,
        "selected_source_form_ids": bucket_source_form_ids(selected_items),
    }


def match_exact_definition_also_pr_pairs(
    working_pairs: list[dict[str, Any]],
    bucket: str,
    matching_rule: str,
) -> dict[str, Any]:
    pairs_by_source_form: dict[int, list[dict[str, Any]]] = {}
    for pair in working_pairs:
        pairs_by_source_form.setdefault(pair_source_form_id(pair), []).append(pair)

    selected_pair_ids: set[tuple[int, int]] = set()
    context_by_pair_id: dict[tuple[int, int], dict[str, Any]] = {}
    for source_pairs in pairs_by_source_form.values():
        matching_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for pair in source_pairs:
            also_pr_context = exact_definition_also_pr_context(pair)
            if also_pr_context is not None:
                matching_pairs.append((pair, also_pr_context))

        if len(matching_pairs) != 1:
            continue

        pair, also_pr_context = matching_pairs[0]
        pair_id = matching_pair_identity(pair)
        if pair_id is not None:
            selected_pair_ids.add(pair_id)
            context_by_pair_id[pair_id] = also_pr_context

    selected_items: list[dict[str, Any]] = []
    remaining_items: list[dict[str, Any]] = []
    for pair in working_pairs:
        pair_id = matching_pair_identity(pair)
        if pair_id in selected_pair_ids:
            selected_items.append(
                matching_pair_with_exact_definition_also_pr(
                    pair,
                    context_by_pair_id[pair_id],
                    bucket=bucket,
                    matching_rule=matching_rule,
                )
            )
        else:
            remaining_items.append(pair)

    return {
        "selected_items": selected_items,
        "remaining_items": remaining_items,
        "selected_source_form_ids": bucket_source_form_ids(selected_items),
    }


def match_exact_definition_pairs(
    working_pairs: list[dict[str, Any]],
    bucket: str,
    matching_rule: str,
) -> dict[str, Any]:
    pairs_by_source_form: dict[int, list[dict[str, Any]]] = {}
    for pair in working_pairs:
        pairs_by_source_form.setdefault(pair_source_form_id(pair), []).append(pair)

    selected_pair_ids: set[tuple[int, int]] = set()
    for source_pairs in pairs_by_source_form.values():
        matching_pairs = [pair for pair in source_pairs if pair_definition_sets_exact(pair)]
        if len(matching_pairs) != 1:
            continue
        pair_id = matching_pair_identity(matching_pairs[0])
        if pair_id is not None:
            selected_pair_ids.add(pair_id)

    selected_items: list[dict[str, Any]] = []
    remaining_items: list[dict[str, Any]] = []
    for pair in working_pairs:
        pair_id = matching_pair_identity(pair)
        if pair_id in selected_pair_ids:
            selected_items.append(matching_pair_for_bucket(pair, bucket=bucket, matching_rule=matching_rule))
        else:
            remaining_items.append(pair)

    return {
        "selected_items": selected_items,
        "remaining_items": remaining_items,
        "selected_source_form_ids": bucket_source_form_ids(selected_items),
    }


def match_semicolon_split_exact_definition_also_pr_pairs(
    working_pairs: list[dict[str, Any]],
    bucket: str,
    matching_rule: str,
) -> dict[str, Any]:
    pairs_by_source_form: dict[int, list[dict[str, Any]]] = {}
    for pair in working_pairs:
        pairs_by_source_form.setdefault(pair_source_form_id(pair), []).append(pair)

    selected_pair_ids: set[tuple[int, int]] = set()
    context_by_pair_id: dict[tuple[int, int], dict[str, Any]] = {}
    for source_pairs in pairs_by_source_form.values():
        matching_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for pair in source_pairs:
            context = semicolon_split_exact_definition_also_pr_context(pair)
            if context is not None:
                matching_pairs.append((pair, context))

        if len(matching_pairs) != 1:
            continue

        pair, context = matching_pairs[0]
        pair_id = matching_pair_identity(pair)
        if pair_id is not None:
            selected_pair_ids.add(pair_id)
            context_by_pair_id[pair_id] = context

    selected_items: list[dict[str, Any]] = []
    remaining_items: list[dict[str, Any]] = []
    for pair in working_pairs:
        pair_id = matching_pair_identity(pair)
        if pair_id in selected_pair_ids:
            selected_items.append(
                matching_pair_with_semicolon_split_exact_definition_also_pr(
                    pair,
                    context_by_pair_id[pair_id],
                    bucket=bucket,
                    matching_rule=matching_rule,
                )
            )
        else:
            remaining_items.append(pair)

    return {
        "selected_items": selected_items,
        "remaining_items": remaining_items,
        "selected_source_form_ids": bucket_source_form_ids(selected_items),
    }


def match_html_subform_definition_cover_pairs(
    working_pairs: list[dict[str, Any]],
    bucket: str,
    matching_rule: str,
) -> dict[str, Any]:
    pairs_by_source_form: dict[int, list[dict[str, Any]]] = {}
    for pair in working_pairs:
        pairs_by_source_form.setdefault(pair_source_form_id(pair), []).append(pair)

    selected_pair_ids: set[tuple[int, int]] = set()
    context_by_pair_id: dict[tuple[int, int], dict[str, Any]] = {}
    for source_pairs in pairs_by_source_form.values():
        context = html_subform_match_context(source_pairs)
        if context is None:
            continue

        for pair in source_pairs:
            pair_id = matching_pair_identity(pair)
            if pair_id is None:
                continue
            selected_pair_ids.add(pair_id)
            context_by_pair_id[pair_id] = context

    selected_items: list[dict[str, Any]] = []
    remaining_items: list[dict[str, Any]] = []
    for pair in working_pairs:
        pair_id = matching_pair_identity(pair)
        if pair_id in selected_pair_ids:
            selected_items.append(
                matching_pair_with_html_subform_definition_cover(
                    pair,
                    context_by_pair_id[pair_id],
                    bucket=bucket,
                    matching_rule=matching_rule,
                )
            )
        else:
            remaining_items.append(pair)

    return {
        "selected_items": selected_items,
        "remaining_items": remaining_items,
        "selected_source_form_ids": bucket_source_form_ids(selected_items),
    }


def match_unique_pinyin_kind_pairs(
    working_pairs: list[dict[str, Any]],
    *,
    bucket: str,
    matching_rule: str,
    pinyin_kind: str,
) -> dict[str, Any]:
    pairs_by_source_form: dict[int, list[dict[str, Any]]] = {}
    for pair in working_pairs:
        pairs_by_source_form.setdefault(pair_source_form_id(pair), []).append(pair)

    selected_pair_ids: set[tuple[int, int]] = set()
    for source_pairs in pairs_by_source_form.values():
        matching_pairs = [pair for pair in source_pairs if pair_pinyin_kind(pair) == pinyin_kind]
        if len(matching_pairs) == 1:
            pair_id = matching_pair_identity(matching_pairs[0])
            if pair_id is not None:
                selected_pair_ids.add(pair_id)

    selected_items: list[dict[str, Any]] = []
    remaining_items: list[dict[str, Any]] = []
    for pair in working_pairs:
        pair_id = matching_pair_identity(pair)
        if pair_id in selected_pair_ids:
            selected_items.append(matching_pair_for_bucket(pair, bucket=bucket, matching_rule=matching_rule))
        else:
            remaining_items.append(pair)

    return {
        "selected_items": selected_items,
        "remaining_items": remaining_items,
        "selected_source_form_ids": bucket_source_form_ids(selected_items),
    }


def match_default_unresolved_pairs(
    working_pairs: list[dict[str, Any]], bucket: str, matching_rule: str
) -> dict[str, Any]:
    selected_items = [
        matching_pair_for_bucket(pair, bucket=bucket, matching_rule=matching_rule) for pair in working_pairs
    ]
    return {
        "selected_items": selected_items,
        "remaining_items": [],
        "selected_source_form_ids": bucket_source_form_ids(selected_items),
    }


MATCHING_RULES = {
    "missing_dictionary_word": MatchingRuleDefinition(
        name="missing_dictionary_word",
        scope="source_prelude",
        requires=("No exact Simplified target word exists in CC-CEDICT",),
        handler=match_missing_dictionary_word_sources,
    ),
    "strict_pinyin_exact_unique": MatchingRuleDefinition(
        name="strict_pinyin_exact_unique",
        scope="pair_pipeline",
        requires=(
            "The working set already contains only exact Simplified-compatible pairs",
            "Exactly one remaining pair for the source form has complete strict Pinyin-list equality",
        ),
        selected_pair="the unique complete strict Pinyin-list exact pair",
        handler=match_strict_pinyin_exact_unique_pairs,
    ),
    "manual_pinyin_override_unique": MatchingRuleDefinition(
        name="manual_pinyin_override_unique",
        scope="pair_pipeline",
        requires=(
            "The source form has a configured manual Pinyin correction",
            "Exactly one remaining pair matches the corrected Pinyin with complete strict or compact preserve-case Pinyin-list equality",
        ),
        selected_pair="the unique pair targeted by the configured corrected Pinyin value",
        handler=match_manual_pinyin_override_pairs,
    ),
    "format_variant_unique": MatchingRuleDefinition(
        name="format_variant_unique",
        scope="pair_pipeline",
        requires=(
            "The working set already contains only exact Simplified-compatible pairs",
            "Exactly one remaining pair for the source form has complete compact preserve-case Pinyin-list equality",
            "The strict Pinyin reading lists differ only by spacing or accent/number formatting",
        ),
        selected_pair="the unique complete compact preserve-case Pinyin-list format-variant pair",
        handler=match_format_variant_unique_pairs,
    ),
    "spoken_tone_variant_unique": MatchingRuleDefinition(
        name="spoken_tone_variant_unique",
        scope="pair_pipeline",
        requires=(
            "The working set already contains only exact Simplified-compatible pairs",
            "Exactly one remaining pair for the source form has toneless Pinyin equality",
            "The source and dictionary Pinyin have the same reading count, syllable count, and syllable bases",
            "Every tone difference is explained by recognized spoken variants: 一 sandhi, 不 sandhi, or neutral tone differences",
        ),
        selected_pair="the unique recognized spoken-tone-variant pair",
        handler=match_spoken_tone_variant_pairs,
    ),
    "case_variant_exact_definition_unique": MatchingRuleDefinition(
        name="case_variant_exact_definition_unique",
        scope="pair_pipeline",
        requires=(
            "The working set already contains only exact Simplified-compatible pairs",
            "Exactly one remaining pair for the source form has complete compact lower-case Pinyin-list equality",
            "The strict Pinyin reading lists differ only by case after spacing and accent/number normalization",
            "The complete non-empty normalized source and dictionary definition sets are identical",
        ),
        selected_pair="the unique exact-definition case-variant pair",
        handler=match_case_variant_exact_definition_pairs,
    ),
    "exact_definition_also_pr_unique": MatchingRuleDefinition(
        name="exact_definition_also_pr_unique",
        scope="pair_pipeline",
        requires=(
            "The working set already contains only exact Simplified-compatible pairs",
            "No higher-priority pair-pipeline step consumed this source form",
            "Exactly one remaining pair for the source form has complete normalized definition-set equality",
            "Every source Pinyin reading is either already on the dictionary form or explicitly listed in the "
            "dictionary definitions as also pr.",
            "At least one source Pinyin reading is an extra also-pr reading not already on the dictionary form",
        ),
        selected_pair="the unique exact-definition pair whose source Pinyin is fully explained by also-pr readings",
        handler=match_exact_definition_also_pr_pairs,
    ),
    "exact_definition_unique": MatchingRuleDefinition(
        name="exact_definition_unique",
        scope="pair_pipeline",
        requires=(
            "The working set already contains only exact Simplified-compatible pairs",
            "No higher-priority pair-pipeline step consumed this source form",
            "Exactly one remaining pair for the source form has complete normalized definition-set equality",
        ),
        selected_pair="the unique exact-definition pair",
        handler=match_exact_definition_pairs,
    ),
    "semicolon_split_exact_definition_also_pr_unique": MatchingRuleDefinition(
        name="semicolon_split_exact_definition_also_pr_unique",
        scope="pair_pipeline",
        requires=(
            "The working set already contains only exact Simplified-compatible pairs",
            "No higher-priority pair-pipeline step consumed this source form",
            "Exactly one remaining pair for the source form has complete definition-set equality after "
            "rule-local semicolon splitting",
            "Every source Pinyin reading is either already on the dictionary form or explicitly listed in the "
            "dictionary definitions as also pr.",
            "At least one source Pinyin reading is an extra also-pr reading not already on the dictionary form",
        ),
        selected_pair=(
            "the unique semicolon-split exact-definition pair whose source Pinyin is fully explained by also-pr "
            "readings"
        ),
        handler=match_semicolon_split_exact_definition_also_pr_pairs,
    ),
    "html_subform_definition_cover_unique": MatchingRuleDefinition(
        name="html_subform_definition_cover_unique",
        scope="pair_pipeline",
        requires=(
            "No higher-priority pair-pipeline step consumed this source form",
            "The xiehanzi HTML contains one or more Pinyin/definition subentries",
            "Each HTML subentry has exactly one strict-Pinyin dictionary candidate whose definition set matches "
            "after rule-local semicolon splitting",
            "The matched subentries cover every remaining dictionary candidate for the source form exactly once",
        ),
        selected_pair="all pairs in the source form whose dictionary forms are covered by xiehanzi HTML subentries",
        handler=match_html_subform_definition_cover_pairs,
    ),
    "default_unresolved": MatchingRuleDefinition(
        name="default_unresolved",
        scope="terminal",
        requires=("No higher-priority pair-pipeline step consumed this source form",),
        handler=match_default_unresolved_pairs,
    ),
}


def candidate_count_buckets_for_source_forms(
    entry_reports_by_id: dict[int, dict[str, Any]],
    source_form_ids: set[int],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for source_form_id in source_form_ids:
        candidate_count = entry_reports_by_id[source_form_id]["candidate_summary"]["candidate_count"]
        counts[candidate_count_bucket(candidate_count)] += 1
    return counts
