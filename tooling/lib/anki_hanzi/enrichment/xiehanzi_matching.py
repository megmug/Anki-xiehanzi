"""Matching rules and evidence helpers for xiehanzi-to-CC-CEDICT alignment."""

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
from anki_hanzi.enrichment.xiehanzi_consumption import bucket_source_form_ids, pair_source_form_id


RuleHandler = Callable[..., dict[str, Any]]

PINYIN_SEPARATOR_RE = re.compile(r"[\s'’·-]+")
LI_RE = re.compile(r"<li>(.*?)</li>", re.IGNORECASE | re.DOTALL)
WORD_RE = re.compile(r"[a-z0-9]+")

PINYIN_RANK = {
    "exact": 6,
    "format_variant": 5,
    "case_variant": 4,
    "toneless": 3,
    "reading_overlap": 2,
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
class PinyinReading:
    strict: str
    compact_preserve_case: str
    compact_lower: str
    toneless_lower: str


@dataclass(frozen=True)
class MatchingRuleDefinition:
    name: str
    scope: str
    requires: tuple[str, ...]
    handler: RuleHandler
    selected_pair: str | None = None


@dataclass(frozen=True)
class TargetFormRef:
    word: LexiconWord
    form: LexiconForm


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


def reading_values(readings: list[PinyinReading], attribute: str) -> list[str]:
    return [getattr(reading, attribute) for reading in readings]


def readings_overlap(source_values: list[str], dictionary_values: list[str]) -> bool:
    return bool(set(source_values) & set(dictionary_values))


def classify_pinyin(source_pinyin: str, dictionary_pinyin: str) -> str:
    source_readings = pinyin_readings(source_pinyin)
    dictionary_readings = pinyin_readings(dictionary_pinyin)
    if not source_readings or not dictionary_readings:
        return "missing"

    source_strict = reading_values(source_readings, "strict")
    dictionary_strict = reading_values(dictionary_readings, "strict")
    if source_strict == dictionary_strict:
        return "exact"

    source_compact_preserve_case = reading_values(source_readings, "compact_preserve_case")
    dictionary_compact_preserve_case = reading_values(dictionary_readings, "compact_preserve_case")
    if source_compact_preserve_case == dictionary_compact_preserve_case:
        return "format_variant"

    source_compact_lower = reading_values(source_readings, "compact_lower")
    dictionary_compact_lower = reading_values(dictionary_readings, "compact_lower")
    if source_compact_lower == dictionary_compact_lower:
        return "case_variant"

    source_toneless_lower = reading_values(source_readings, "toneless_lower")
    dictionary_toneless_lower = reading_values(dictionary_readings, "toneless_lower")
    if source_toneless_lower == dictionary_toneless_lower:
        return "toneless"

    if (
        readings_overlap(source_strict, dictionary_strict)
        or readings_overlap(source_compact_preserve_case, dictionary_compact_preserve_case)
        or readings_overlap(source_compact_lower, dictionary_compact_lower)
        or readings_overlap(source_toneless_lower, dictionary_toneless_lower)
    ):
        return "reading_overlap"

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
    pair["evidence"] = {
        **pair["evidence"],
        "manual_pinyin_override": {
            "kind": "configured",
            "reason": override["reason"],
            "raw_source": pinyin_normalization_report(override["raw_pinyin"]),
            "corrected_source": pinyin_normalization_report(override["override_pinyin"]),
            "dictionary": pinyin_normalization_report(pair["dictionary"]["pinyin"]),
            "corrected_source_to_dictionary": classify_pinyin(
                override["override_pinyin"],
                pair["dictionary"]["pinyin"],
            ),
        },
    }
    return pair


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
    "default_unresolved": MatchingRuleDefinition(
        name="default_unresolved",
        scope="terminal",
        requires=("No higher-priority pair-pipeline step consumed this source form",),
        handler=match_default_unresolved_pairs,
    ),
}


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
