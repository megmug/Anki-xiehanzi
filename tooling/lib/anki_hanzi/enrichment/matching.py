"""Report-only candidate matching between hanzi source entries and CC-CEDICT."""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Callable
from collections import Counter
from dataclasses import dataclass
from typing import Any

from dragonmapper import transcriptions

from anki_hanzi.lexicon import LexiconForm, LexiconState, LexiconWord


RuleHandler = Callable[..., dict[str, Any]]
ConsumptionRuleHandler = Callable[..., dict[str, Any]]

PINYIN_SEPARATOR_RE = re.compile(r"[\s'’·-]+")
LI_RE = re.compile(r"<li>(.*?)</li>", re.IGNORECASE | re.DOTALL)
WORD_RE = re.compile(r"[a-z0-9]+")

PINYIN_RANK = {
    "exact": 5,
    "format_variant": 4,
    "case_variant": 3,
    "toneless": 2,
    "mismatch": 1,
    "missing": 0,
}
DEFINITION_RANK = {
    "exact": 5,
    "subset": 4,
    "strong_overlap": 3,
    "weak_overlap": 2,
    "none": 1,
    "missing": 0,
}
BUCKET_DESCRIPTIONS = {
    "perfect_match": (
        "A source form has exactly one strict Pinyin-exact dictionary candidate. "
        "The source form is resolved and all of its candidate pairs are consumed."
    ),
    "missing_dictionary_word": (
        "No exact normalized Simplified word exists in CC-CEDICT. "
        "The source form is resolved by the future synthetic-form rule."
    ),
    "default_unresolved": (
        "No higher-priority bucket resolved the source form. All remaining candidate pairs are shown for rule design."
    ),
}


@dataclass(frozen=True)
class PinyinReading:
    strict: str
    compact_preserve_case: str
    compact_lower: str
    toneless_lower: str


@dataclass(frozen=True)
class BucketDefinition:
    name: str
    priority: int
    phase: str
    description: str
    report_items: bool
    matching_rules: tuple[str, ...] = ()
    consumption_rule: str | None = None


@dataclass(frozen=True)
class MatchingRuleDefinition:
    name: str
    scope: str
    requires: tuple[str, ...]
    handler: RuleHandler
    selected_pair: str | None = None


@dataclass(frozen=True)
class ConsumptionRuleDefinition:
    name: str
    report_only_effect: str
    future_merge_effect: str
    handler: ConsumptionRuleHandler


@dataclass(frozen=True)
class TargetFormRef:
    word: LexiconWord
    form: LexiconForm


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
    "default_unresolved": BucketDefinition(
        name="default_unresolved",
        priority=1000,
        phase="terminal",
        description=BUCKET_DESCRIPTIONS["default_unresolved"],
        report_items=True,
        matching_rules=("default_unresolved",),
        consumption_rule=None,
    ),
}


def normalize_pinyin_u_variants(value: str) -> str:
    return value.replace("ü", "v").replace("Ü", "V").replace("u:", "v").replace("U:", "V")


def strict_numbered_preserve_case(value: str) -> str:
    value = unicodedata.normalize("NFC", str(value or "").strip())
    value = re.sub(r"\s+", " ", value)
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


def pinyin_readings(value: str) -> list[PinyinReading]:
    readings: list[PinyinReading] = []
    for part in re.split(r"/", str(value or "")):
        strict = strict_numbered_preserve_case(part)
        if not strict:
            continue
        compact_preserve_case = PINYIN_SEPARATOR_RE.sub("", strict)
        compact_lower = compact_preserve_case.casefold()
        toneless_lower = re.sub(r"\d", "", compact_lower)
        readings.append(
            PinyinReading(
                strict=strict,
                compact_preserve_case=compact_preserve_case,
                compact_lower=compact_lower,
                toneless_lower=toneless_lower,
            )
        )
    return readings


def classify_pinyin(source_pinyin: str, dictionary_pinyin: str) -> str:
    source_readings = pinyin_readings(source_pinyin)
    dictionary_readings = pinyin_readings(dictionary_pinyin)
    if not source_readings or not dictionary_readings:
        return "missing"

    for source in source_readings:
        for dictionary in dictionary_readings:
            if source.strict == dictionary.strict:
                return "exact"

    for source in source_readings:
        for dictionary in dictionary_readings:
            if source.compact_preserve_case == dictionary.compact_preserve_case:
                return "format_variant"

    for source in source_readings:
        for dictionary in dictionary_readings:
            if source.compact_lower == dictionary.compact_lower:
                return "case_variant"

    for source in source_readings:
        for dictionary in dictionary_readings:
            if source.toneless_lower and source.toneless_lower == dictionary.toneless_lower:
                return "toneless"

    return "mismatch"


def pinyin_normalization_report(value: str) -> dict[str, Any]:
    readings = pinyin_readings(value)
    return {
        "raw": str(value or ""),
        "strict_numbered_preserve_case": [reading.strict for reading in readings],
        "compact_preserve_case": [reading.compact_preserve_case for reading in readings],
        "toneless_lower": [reading.toneless_lower for reading in readings],
    }


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


def normalize_definition(value: str) -> str:
    value = strip_html_text(value).casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def definition_tokens(values: list[str]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        tokens.update(WORD_RE.findall(normalize_definition(value)))
    return tokens


def preview_text(value: str, limit: int = 120) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def definition_preview(values: list[str], limit: int = 2) -> list[str]:
    return [preview_text(value) for value in values[:limit]]


def classify_definitions(source_definitions: list[str], dictionary_definitions: list[str]) -> tuple[str, float]:
    source_normalized = {normalize_definition(definition) for definition in source_definitions}
    dictionary_normalized = {normalize_definition(definition) for definition in dictionary_definitions}
    source_normalized.discard("")
    dictionary_normalized.discard("")
    if not source_normalized or not dictionary_normalized:
        return "missing", 0.0
    if source_normalized & dictionary_normalized:
        return "exact", 1.0

    for source in source_normalized:
        for dictionary in dictionary_normalized:
            if source in dictionary or dictionary in source:
                return "subset", 1.0

    source_tokens = definition_tokens(source_definitions)
    dictionary_tokens = definition_tokens(dictionary_definitions)
    if not source_tokens or not dictionary_tokens:
        return "missing", 0.0
    overlap = len(source_tokens & dictionary_tokens) / len(source_tokens | dictionary_tokens)
    if overlap >= 0.6:
        return "strong_overlap", overlap
    if overlap > 0:
        return "weak_overlap", overlap
    return "none", 0.0


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


def candidate_report(entry: dict[str, Any], word: LexiconWord, form: LexiconForm) -> dict[str, Any]:
    pinyin_kind = classify_pinyin(entry["pinyin"], form.pinyin)
    source_definitions = definitions_from_meaning_html(entry["meaning_html"])
    definition_kind, definition_overlap = classify_definitions(source_definitions, list(form.definitions))
    return {
        "dictionary": {
            "simplified": word.simplified,
            "pinyin": form.pinyin,
            "traditional_variants": list(form.traditional_variants),
            "tags": list(form.tags),
            "definitions_preview": definition_preview(list(form.definitions)),
        },
        "evidence": {
            "simplified": {"kind": "exact"},
            "pinyin": {
                "kind": pinyin_kind,
                "source": pinyin_normalization_report(entry["pinyin"]),
                "dictionary": pinyin_normalization_report(form.pinyin),
            },
            "definitions": {
                "kind": definition_kind,
                "token_overlap": round(definition_overlap, 3),
                "source_preview": definition_preview(source_definitions),
            },
        },
    }


def entry_evidence_summary(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    strict_pinyin_exact_count = sum(1 for candidate in candidates if candidate["evidence"]["pinyin"]["kind"] == "exact")
    if not candidates:
        return {
            "candidate_count": 0,
            "strict_pinyin_exact_candidate_count": 0,
            "top_candidate_pinyin_evidence": None,
            "top_candidate_definition_evidence": None,
        }

    return {
        "candidate_count": len(candidates),
        "strict_pinyin_exact_candidate_count": strict_pinyin_exact_count,
        "top_candidate_pinyin_evidence": candidates[0]["evidence"]["pinyin"]["kind"],
        "top_candidate_definition_evidence": candidates[0]["evidence"]["definitions"]["kind"],
    }


def candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, int, str]:
    pinyin_kind = candidate["evidence"]["pinyin"]["kind"]
    definition_kind = candidate["evidence"]["definitions"]["kind"]
    return (
        -PINYIN_RANK[pinyin_kind],
        -DEFINITION_RANK[definition_kind],
        candidate["dictionary"]["pinyin"],
    )


def normalize_entry_key(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = unicodedata.normalize("NFC", value)
    return re.sub(r"\s+", "", value).strip().lower()


def build_target_form_index(state: LexiconState) -> dict[str, list[TargetFormRef]]:
    target_form_index: dict[str, list[TargetFormRef]] = {}
    for word in state.sorted_words():
        key = normalize_entry_key(word.simplified)
        if not key:
            continue
        target_form_index.setdefault(key, []).extend(
            TargetFormRef(word=word, form=form) for form in word.sorted_forms()
        )
    return target_form_index


def empty_entry_evidence_summary() -> dict[str, Any]:
    return {
        "candidate_count": 0,
        "strict_pinyin_exact_candidate_count": 0,
        "top_candidate_pinyin_evidence": None,
        "top_candidate_definition_evidence": None,
    }


def source_matching_entry_report(entry: dict[str, Any], source_form_id: int) -> dict[str, Any]:
    return {
        "source_form_id": source_form_id,
        "source_key": normalize_entry_key(entry["simplified"]),
        "entry": entry,
        "source_entry": source_entry_report(entry),
        "evidence_summary": empty_entry_evidence_summary(),
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
    candidate_rank: int,
    matching_rule: str,
) -> dict[str, Any]:
    evidence_summary = entry_report["evidence_summary"]
    return {
        "source": entry_report["source_entry"],
        "dictionary": candidate["dictionary"],
        "context": {
            "source_form_id": entry_report["source_form_id"],
            "candidate_count_for_source": evidence_summary["candidate_count"],
            "candidate_rank_for_source": candidate_rank,
            "strict_pinyin_exact_candidate_count_for_source": evidence_summary["strict_pinyin_exact_candidate_count"],
        },
        "evidence": candidate["evidence"],
        "bucket": bucket,
        "matching_rule": matching_rule,
    }


def missing_dictionary_word_report(entry_report: dict[str, Any], *, bucket: str, matching_rule: str) -> dict[str, Any]:
    return {
        "source": entry_report["source_entry"],
        "context": {
            "source_form_id": entry_report["source_form_id"],
            "candidate_count_for_source": 0,
            "strict_pinyin_exact_candidate_count_for_source": 0,
        },
        "bucket": bucket,
        "matching_rule": matching_rule,
    }


def pair_source_form_id(item: dict[str, Any]) -> int:
    return int(item["context"]["source_form_id"])


def matching_pair_identity(item: dict[str, Any]) -> tuple[int, int] | None:
    if "dictionary" not in item:
        return None
    return (pair_source_form_id(item), int(item["context"]["candidate_rank_for_source"]))


def matching_pair_for_bucket(item: dict[str, Any], *, bucket: str, matching_rule: str) -> dict[str, Any]:
    return {
        **item,
        "bucket": bucket,
        "matching_rule": matching_rule,
    }


def bucket_source_form_ids(items: list[dict[str, Any]]) -> set[int]:
    return {pair_source_form_id(item) for item in items}


def bucket_matching_pair_count(items: list[dict[str, Any]]) -> int:
    return sum(1 for item in items if "dictionary" in item)


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


def drop_missing_dictionary_word_source_forms(
    selected_items: list[dict[str, Any]],
    remaining_source_form_ids: set[int],
) -> dict[str, Any]:
    consumed_source_form_ids = bucket_source_form_ids(selected_items) & remaining_source_form_ids
    remaining_source_form_ids.difference_update(consumed_source_form_ids)
    return {
        "consumed_source_form_ids": consumed_source_form_ids,
        "consumed_source_form_count": len(consumed_source_form_ids),
        "consumed_matching_pair_count": 0,
        "remaining_source_form_count": len(remaining_source_form_ids),
    }


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
        candidates = [candidate_report(entry, target.word, target.form) for target in target_refs]
        candidates.sort(key=candidate_sort_key)
        entry_report["candidates"] = candidates
        entry_report["evidence_summary"] = entry_evidence_summary(candidates)

        for candidate_rank, candidate in enumerate(candidates, start=1):
            working_pairs.append(
                matching_pair_report(
                    entry_report,
                    candidate,
                    bucket="simplified_match_working_set",
                    candidate_rank=candidate_rank,
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


def match_strict_pinyin_exact_unique_pairs(
    working_pairs: list[dict[str, Any]],
    bucket: str,
    matching_rule: str,
) -> dict[str, Any]:
    pairs_by_source_form: dict[int, list[dict[str, Any]]] = {}
    for pair in working_pairs:
        pairs_by_source_form.setdefault(pair_source_form_id(pair), []).append(pair)

    selected_pair_ids: set[tuple[int, int]] = set()
    for source_pairs in pairs_by_source_form.values():
        exact_pairs = [pair for pair in source_pairs if pair["evidence"]["pinyin"]["kind"] == "exact"]
        if len(exact_pairs) == 1:
            pair_id = matching_pair_identity(exact_pairs[0])
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


def drop_source_form_pairs(
    selected_items: list[dict[str, Any]],
    remaining_items: list[dict[str, Any]],
) -> dict[str, Any]:
    consumed_source_form_ids = bucket_source_form_ids(selected_items)
    remaining_after_consumption: list[dict[str, Any]] = []
    removed_from_remaining_items: list[dict[str, Any]] = []

    for item in remaining_items:
        if pair_source_form_id(item) in consumed_source_form_ids:
            removed_from_remaining_items.append(item)
        else:
            remaining_after_consumption.append(item)

    return {
        "consumed_source_form_ids": consumed_source_form_ids,
        "consumed_source_form_count": len(consumed_source_form_ids),
        "consumed_matching_pair_count": bucket_matching_pair_count(selected_items)
        + bucket_matching_pair_count(removed_from_remaining_items),
        "removed_from_remaining_matching_pair_count": bucket_matching_pair_count(removed_from_remaining_items),
        "remaining_items": remaining_after_consumption,
    }


def drop_perfect_match_source_form_pairs(
    selected_items: list[dict[str, Any]],
    remaining_items: list[dict[str, Any]],
) -> dict[str, Any]:
    return drop_source_form_pairs(selected_items, remaining_items)


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
        requires=("No exact normalized Simplified target word exists in CC-CEDICT",),
        handler=match_missing_dictionary_word_sources,
    ),
    "strict_pinyin_exact_unique": MatchingRuleDefinition(
        name="strict_pinyin_exact_unique",
        scope="pair_pipeline",
        requires=(
            "The working set already contains only normalized Simplified-compatible pairs",
            "Exactly one remaining pair for the source form has pinyin evidence exact",
        ),
        selected_pair="the unique strict Pinyin-exact pair",
        handler=match_strict_pinyin_exact_unique_pairs,
    ),
    "default_unresolved": MatchingRuleDefinition(
        name="default_unresolved",
        scope="terminal",
        requires=("No higher-priority pair-pipeline step consumed this source form",),
        handler=match_default_unresolved_pairs,
    ),
}


CONSUMPTION_RULES = {
    "drop_missing_dictionary_word_source_forms": ConsumptionRuleDefinition(
        name="drop_missing_dictionary_word_source_forms",
        report_only_effect="remove the source form from the pair pipeline before any pairs are materialized",
        future_merge_effect="no lexical mutation in the report-only scaffold",
        handler=drop_missing_dictionary_word_source_forms,
    ),
    "drop_perfect_match_source_form_pairs": ConsumptionRuleDefinition(
        name="drop_perfect_match_source_form_pairs",
        report_only_effect="remove all remaining matching pairs for the consumed source form",
        future_merge_effect="no lexical mutation",
        handler=drop_perfect_match_source_form_pairs,
    ),
}


def bucket_definitions_by_priority() -> list[BucketDefinition]:
    return sorted(BUCKET_DEFINITIONS.values(), key=lambda definition: definition.priority)


def bucket_definitions_by_phase(phase: str) -> list[BucketDefinition]:
    return [definition for definition in bucket_definitions_by_priority() if definition.phase == phase]


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
        rule_name = definition.matching_rules[0]
        rule = MATCHING_RULES[rule_name]
        result = rule.handler(remaining_items, definition.name, rule_name)
        selected_items = result["selected_items"]
        bucket_results[definition.name] = {
            "phase": definition.phase,
            "bucket": definition.name,
            "input_source_form_count": len(bucket_source_form_ids(remaining_items)),
            "input_matching_pair_count": bucket_matching_pair_count(remaining_items),
            "selected_items": selected_items,
            "selected_source_form_count": len(bucket_source_form_ids(selected_items)),
            "selected_matching_pair_count": bucket_matching_pair_count(selected_items),
            "consumed_source_form_count": 0,
            "consumed_matching_pair_count": 0,
            "removed_from_remaining_matching_pair_count": 0,
            "remaining_source_form_count_after_consumption": len(bucket_source_form_ids(selected_items)),
            "remaining_matching_pair_count_after_consumption": bucket_matching_pair_count(selected_items),
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


def pinyin_counts_for_items(items: list[dict[str, Any]]) -> Counter[str]:
    return Counter(item["evidence"]["pinyin"]["kind"] for item in items if "evidence" in item)


def top_candidate_pinyin_counts_for_source_forms(
    entry_reports_by_id: dict[int, dict[str, Any]],
    source_form_ids: set[int],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for source_form_id in source_form_ids:
        candidates = entry_reports_by_id[source_form_id]["candidates"]
        if candidates:
            counts[candidates[0]["evidence"]["pinyin"]["kind"]] += 1
    return counts


def candidate_count_buckets_for_source_forms(
    entry_reports_by_id: dict[int, dict[str, Any]],
    source_form_ids: set[int],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for source_form_id in source_form_ids:
        candidate_count = entry_reports_by_id[source_form_id]["evidence_summary"]["candidate_count"]
        counts[candidate_count_bucket(candidate_count)] += 1
    return counts


def build_matching_report(
    state: LexiconState,
    raw_entries: list[dict[str, Any]],
    deck_entries: list[dict[str, Any]],
    dropped_duplicates: list[dict[str, Any]],
    *,
    bucket_item_limit: int | None = None,
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
    default_items = bucket_results["default_unresolved"]["selected_items"]
    default_source_form_ids_after_consumption = bucket_source_form_ids(default_items)

    initial_candidate_count_buckets = Counter(
        candidate_count_bucket(entry_report["evidence_summary"]["candidate_count"])
        for entry_report in entry_reports_by_id.values()
    )
    initial_pinyin_counts = pinyin_counts_for_items(working_pairs)
    default_candidate_count_buckets = candidate_count_buckets_for_source_forms(
        entry_reports_by_id,
        default_source_form_ids_after_consumption,
    )
    default_pinyin_counts = pinyin_counts_for_items(default_items)
    default_top_candidate_pinyin_counts = top_candidate_pinyin_counts_for_source_forms(
        entry_reports_by_id,
        default_source_form_ids_after_consumption,
    )
    perfect_match_selected_pair_count = bucket_results["perfect_match"]["selected_matching_pair_count"]
    perfect_match_consumed_pair_count = bucket_results["perfect_match"]["consumed_matching_pair_count"]

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

    def report_bucket_items(bucket: str) -> list[dict[str, Any]]:
        if not BUCKET_DEFINITIONS[bucket].report_items:
            return []
        items = bucket_results[bucket]["selected_items"]
        return items if bucket_item_limit is None else items[:bucket_item_limit]

    def matching_rule_report(rule_name: str) -> dict[str, Any]:
        rule = MATCHING_RULES[rule_name]
        report: dict[str, Any] = {
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
            "future_merge_effect": rule.future_merge_effect,
        }

    def bucket_summary_item(definition: BucketDefinition) -> dict[str, Any]:
        bucket = definition.name
        result = bucket_result(definition)
        item: dict[str, Any] = {
            "priority": definition.priority,
            "phase": definition.phase,
            "bucket": bucket,
            "description": definition.description,
            "matching_rules": list(definition.matching_rules),
            "consumption_rule": definition.consumption_rule,
            "step_input_source_form_count": result["input_source_form_count"],
            "step_input_matching_pair_count": result["input_matching_pair_count"],
            "source_form_count_before_consumption": result["selected_source_form_count"],
            "source_form_count_after_consumption": selected_source_form_count_after_consumption(result, definition),
            "matching_pair_count_before_consumption": result["selected_matching_pair_count"],
            "matching_pair_count_after_consumption": selected_matching_pair_count_after_consumption(result, definition),
            "selected_matching_pair_count": result["selected_matching_pair_count"],
            "consumed_source_form_count": result["consumed_source_form_count"],
            "consumed_matching_pair_count": result["consumed_matching_pair_count"],
            "removed_from_remaining_matching_pair_count": result["removed_from_remaining_matching_pair_count"],
            "remaining_source_form_count_after_step": result["remaining_source_form_count_after_consumption"],
            "remaining_matching_pair_count_after_step": result["remaining_matching_pair_count_after_consumption"],
            "has_consumption_rule": definition.consumption_rule is not None,
            "reports_items": definition.report_items,
        }
        if bucket == "default_unresolved":
            item["remaining_matching_pair_count"] = sum(default_pinyin_counts.values())
        return item

    def priority_pipeline_item(definition: BucketDefinition) -> dict[str, Any]:
        bucket = definition.name
        result = bucket_result(definition)
        return {
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
        }

    def bucket_report_item(definition: BucketDefinition) -> dict[str, Any]:
        bucket = definition.name
        result = bucket_result(definition)
        return {
            "phase": definition.phase,
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
            "reports_items": definition.report_items,
            "items": report_bucket_items(bucket),
        }

    return {
        "schema": "hanzi-matching-report-v1",
        "bucket_summary": [bucket_summary_item(definition) for definition in bucket_definitions_by_priority()],
        "description": (
            "Report-only xiehanzi-to-CC-CEDICT candidate matching. "
            "Source prelude rules consume source forms before the pair pipeline starts. "
            "Pair rules then split a shrinking working set before consumption removes source-form redundancies. "
            "Only default_unresolved contains detailed remaining matching pairs."
        ),
        "summary": {
            "raw_source_entries": len(raw_entries),
            "deduped_source_entries": len(deck_entries),
            "dropped_duplicate_entries": len(dropped_duplicates),
            "dictionary_words": dictionary_word_count,
            "dictionary_forms": dictionary_form_count,
            "source_form_bucket_counts": dict(sorted(bucket_source_form_counts_after_consumption.items())),
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
            "perfect_match_selected_pair_count": perfect_match_selected_pair_count,
            "perfect_match_consumed_pair_count": perfect_match_consumed_pair_count,
            "default_unresolved_matching_pair_count": sum(default_pinyin_counts.values()),
            "initial_candidate_count_buckets": dict(sorted(initial_candidate_count_buckets.items())),
            "default_candidate_count_buckets": dict(sorted(default_candidate_count_buckets.items())),
            "initial_matching_pair_pinyin_evidence_counts": dict(sorted(initial_pinyin_counts.items())),
            "default_matching_pair_pinyin_evidence_counts": dict(sorted(default_pinyin_counts.items())),
            "default_top_candidate_pinyin_evidence_counts": dict(sorted(default_top_candidate_pinyin_counts.items())),
            "bucket_item_limit": bucket_item_limit,
        },
        "priority_pipeline": [priority_pipeline_item(definition) for definition in bucket_definitions_by_priority()],
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
                "description": "Materialized pairs whose normalized Simplified values match.",
                "matching_rule": "simplified_match",
                "source_form_count": materialization_result["source_form_count"],
                "target_form_count": materialization_result["target_form_count"],
                "virtual_input_matching_pair_count": materialization_result["virtual_pair_count"],
                "matching_pair_count": materialization_result["simplified_match_pair_count"],
                "materialized": True,
            },
            "simplified_mismatch": {
                "description": "Virtual rejected pairs whose normalized Simplified values do not match.",
                "matching_rule": "simplified_mismatch",
                "matching_pair_count": materialization_result["simplified_mismatch_pair_count"],
                "materialized": False,
            },
        },
        "candidate_generation": {
            "source_prelude": "missing_dictionary_word removes source forms with no normalized Simplified target key.",
            "pair_materialization": "simplified_match materializes only normalized Simplified-compatible pairs.",
            "virtual_rejection": "simplified_mismatch is counted as a virtual aggregate and is not stored as items.",
        },
        "evidence_model": {
            "pinyin": {
                "exact": "strict_numbered_preserve_case strings are identical.",
                "format_variant": "Compact preserve-case strings match, but strict strings differ.",
                "case_variant": "Compact casefolded strings match, but preserve-case strings differ.",
                "toneless": "Tone-stripped compact casefolded strings match.",
                "mismatch": "No pinyin normal form matches.",
                "missing": "Source or dictionary pinyin could not be normalized.",
            },
            "definitions": {
                "exact": "At least one normalized definition is identical.",
                "subset": "At least one normalized definition contains another.",
                "strong_overlap": "Definition token Jaccard overlap is at least 0.6.",
                "weak_overlap": "Definition token Jaccard overlap is non-zero.",
                "none": "No definition token overlap.",
                "missing": "Source or dictionary definitions are missing.",
            },
        },
        "pinyin_evidence_order": [
            "exact",
            "format_variant",
            "case_variant",
            "toneless",
            "mismatch",
            "missing",
        ],
        "buckets": {definition.name: bucket_report_item(definition) for definition in bucket_definitions_by_priority()},
    }
