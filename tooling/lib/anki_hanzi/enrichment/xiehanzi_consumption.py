"""Consumption rules for xiehanzi matching and LexiconState enrichment.

The first rule layer mutates only pipeline working sets. The second layer
applies the selected buckets to the LexiconState.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dragonmapper import transcriptions

from anki_hanzi.lexicon import LexiconForm, LexiconState, LexiconWord
from anki_hanzi.enrichment.xiehanzi_rule_helpers import (
    definition_sets_exact,
    definitions_from_meaning_html,
    normalize_pinyin_u_variants,
    pinyin_rule_kind,
)


ConsumptionRuleHandler = Callable[..., dict[str, Any]]
StateConsumptionRuleHandler = Callable[..., dict[str, Any]]

PINYIN_SEPARATOR_RE = re.compile(r"[\s'’\-·]+")
PINYIN_NUMBERED_TOKEN_RE = re.compile(r"[A-Za-züÜv:]+[1-5]?")
PINYIN_PAIR_MATCH_PREFERENCE = ("exact", "format_variant", "case_variant")
FORM_MATCH_PREFERENCE = ("exact", "format_variant", "case_variant", "reading_variant")


@dataclass(frozen=True)
class ConsumptionRuleDefinition:
    name: str
    report_only_effect: str
    enrichment_effect: str
    handler: ConsumptionRuleHandler


@dataclass(frozen=True)
class StateConsumptionRuleDefinition:
    name: str
    bucket: str
    state_effect: str
    handler: StateConsumptionRuleHandler


@dataclass(frozen=True)
class PinyinReading:
    spaced: str
    compact: str
    lower_compact: str


def normalize_field(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = unicodedata.normalize("NFC", value)
    return re.sub(r"\s+", "", value).strip().lower()


def numbered_pinyin_part(value: str) -> str:
    value = unicodedata.normalize("NFC", value.strip())
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


def canonical_pinyin_readings(value: str) -> list[PinyinReading]:
    readings: list[PinyinReading] = []
    for part in re.split(r"/", value or ""):
        numbered = numbered_pinyin_part(part)
        if not numbered:
            continue

        spaced = PINYIN_SEPARATOR_RE.sub(" ", numbered).strip()
        spaced = re.sub(r"\s+", " ", spaced)
        compact = spaced.replace(" ", "")
        if compact:
            readings.append(
                PinyinReading(
                    spaced=spaced,
                    compact=compact,
                    lower_compact=compact.lower(),
                )
            )
    return readings


def numbered_pinyin_tokens(value: str) -> list[str]:
    return PINYIN_NUMBERED_TOKEN_RE.findall(numbered_pinyin_part(value))


def split_numbered_pinyin_token(value: str) -> tuple[str, str]:
    match = re.fullmatch(r"([A-Za-züÜv:]+)([1-5]?)", value)
    if match is None:
        raise ValueError(f"Invalid numbered Pinyin token: {value!r}")
    return match.group(1), match.group(2)


def pinyin_base_key(value: str) -> str:
    return normalize_pinyin_u_variants(value).casefold()


def source_tone_on_reference_base(source_token: str, reference_token: str) -> str:
    source_base, source_tone = split_numbered_pinyin_token(source_token)
    reference_base, _ = split_numbered_pinyin_token(reference_token)
    if pinyin_base_key(source_base) != pinyin_base_key(reference_base):
        raise ValueError(
            f"Cannot align spoken-tone Pinyin token {source_token!r} with dictionary token {reference_token!r}"
        )
    return f"{reference_base}{source_tone}"


def source_pinyin_in_dictionary_format(source_pinyin: str, dictionary_pinyin: str) -> str:
    source_parts = [part for part in re.split(r"/", str(source_pinyin or "")) if part.strip()]
    dictionary_parts = [part for part in re.split(r"/", str(dictionary_pinyin or "")) if part.strip()]
    if len(source_parts) != len(dictionary_parts):
        raise ValueError(
            f"Cannot align spoken-tone Pinyin readings {source_pinyin!r} with dictionary readings {dictionary_pinyin!r}"
        )

    formatted_readings: list[str] = []
    for source_part, dictionary_part in zip(source_parts, dictionary_parts):
        source_tokens = numbered_pinyin_tokens(source_part)
        dictionary_tokens = numbered_pinyin_tokens(dictionary_part)
        if len(source_tokens) != len(dictionary_tokens):
            raise ValueError(
                f"Cannot align spoken-tone Pinyin syllables {source_part!r} with dictionary syllables "
                f"{dictionary_part!r}"
            )
        formatted_readings.append(
            " ".join(
                source_tone_on_reference_base(source_token, dictionary_token)
                for source_token, dictionary_token in zip(source_tokens, dictionary_tokens)
            )
        )

    return " / ".join(formatted_readings)


def pinyin_lookup_keys(value: str) -> list[str]:
    keys: list[str] = []
    for reading in canonical_pinyin_readings(value):
        key = reading.lower_compact
        if key not in keys:
            keys.append(key)
    return keys


def pinyin_lookup_key(value: str) -> str:
    keys = pinyin_lookup_keys(value)
    return keys[0] if keys else ""


def toneless_pinyin_lookup_keys(value: str) -> list[str]:
    keys: list[str] = []
    for key in pinyin_lookup_keys(value):
        toneless_key = re.sub(r"\d", "", key)
        if toneless_key and toneless_key not in keys:
            keys.append(toneless_key)
    return keys


def entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "simplified": entry["simplified"],
        "traditional": entry["traditional"],
        "pinyin": entry["pinyin"],
        "zhuyin": entry["zhuyin"],
        "deck_level": entry["deck_level"],
        "raw_level": entry["raw_level"],
        "source": entry["source"],
    }
    if entry.get("raw_pinyin") and entry["raw_pinyin"] != entry["pinyin"]:
        summary["raw_pinyin"] = entry["raw_pinyin"]
    if entry.get("manual_pinyin_override"):
        summary["manual_pinyin_override"] = entry["manual_pinyin_override"]
    return summary


def form_pinyin_reading_string(form: LexiconForm) -> str:
    return " / ".join(form.pinyin_readings or [form.pinyin])


def build_state_word_index(state: LexiconState) -> dict[str, LexiconWord]:
    index: dict[str, LexiconWord] = {}
    for word in state.sorted_words():
        key = normalize_field(word.simplified)
        if key:
            index[key] = word
    return index


def build_synthetic_words(missing_entries: list[dict[str, Any]]) -> list[LexiconWord]:
    by_simplified: dict[str, LexiconWord] = {}

    for entry in missing_entries:
        simplified = entry["simplified"]
        word = by_simplified.get(simplified)
        if word is None:
            word = LexiconWord(simplified=simplified, tags=["source:xiehanzi"])
            by_simplified[simplified] = word

        word.add_tags(entry["tags"])
        word.set_hanzi_frequency_once(entry["frequency"])

        traditional = entry["traditional"]
        if traditional and traditional not in word.traditional_variants:
            word.traditional_variants.append(traditional)

        form_key = numbered_pinyin(entry["pinyin"])
        form = word.forms.get(form_key)
        if form is None:
            form = LexiconForm(pinyin=form_key, tags=[])
            word.forms[form_key] = form

        if traditional and traditional not in form.traditional_variants:
            form.traditional_variants.append(traditional)

        form.append_definitions(definitions_from_meaning_html(entry["meaning_html"]))
        form.add_tags(entry["tags"])

    for word in by_simplified.values():
        word.sort_forms_by_pinyin()

    return sorted(by_simplified.values(), key=lambda word: word.simplified)


def prefer_first(values: list[str], value: str) -> None:
    if not value:
        return
    if value in values:
        values.remove(value)
    values.insert(0, value)


def pinyin_pair_match_type(form_pinyin: str, entry_pinyin: str) -> str | None:
    observed_match_types: set[str] = set()
    for form_reading in canonical_pinyin_readings(form_pinyin):
        for entry_reading in canonical_pinyin_readings(entry_pinyin):
            if form_reading.lower_compact != entry_reading.lower_compact:
                continue
            if form_reading.spaced == entry_reading.spaced:
                match_type = "exact"
            elif form_reading.compact == entry_reading.compact:
                match_type = "format_variant"
            else:
                match_type = "case_variant"

            observed_match_types.add(match_type)

    for match_type in PINYIN_PAIR_MATCH_PREFERENCE:
        if match_type in observed_match_types:
            return match_type
    return None


def choose_preferred_form_match(
    matching_forms: list[tuple[LexiconForm, str]],
) -> tuple[LexiconForm, str] | None:
    for preferred_match_type in FORM_MATCH_PREFERENCE:
        for form, match_type in matching_forms:
            if match_type == preferred_match_type:
                return form, match_type
    return None


def classify_pinyin_match(form_pinyin: str, entry_pinyin: str) -> str | None:
    match_type = pinyin_pair_match_type(form_pinyin, entry_pinyin)
    if not match_type:
        return None
    if pinyin_lookup_keys(form_pinyin) != pinyin_lookup_keys(entry_pinyin):
        return "reading_variant"
    return match_type


def record_form_match(form_stats: dict[str, Any], match_type: str) -> None:
    form_stats["match_types"][match_type] += 1
    if match_type == "reading_variant":
        form_stats["matched_pinyin_variant"] += 1


def find_or_create_hanzi_form(
    word: LexiconWord,
    entry: dict[str, Any],
    form_stats: dict[str, Any],
) -> tuple[LexiconForm, str]:
    forms = word.sorted_forms()
    entry_keys = pinyin_lookup_keys(entry["pinyin"])

    matching_forms: list[tuple[LexiconForm, str]] = []
    for form in forms:
        match_type = classify_pinyin_match(form.pinyin, entry["pinyin"])
        if match_type:
            matching_forms.append((form, match_type))

    if len(matching_forms) > 1:
        preferred_match = choose_preferred_form_match(matching_forms)
        if preferred_match:
            best_match, best_match_type = preferred_match
            form_stats["matched"] += 1
            record_form_match(form_stats, best_match_type)
            return best_match, best_match_type

    for form, match_type in matching_forms:
        form_stats["matched"] += 1
        record_form_match(form_stats, match_type)
        return form, match_type

    entry_toneless_keys = toneless_pinyin_lookup_keys(entry["pinyin"])
    toneless_matches = [
        form for form in forms if set(toneless_pinyin_lookup_keys(form.pinyin)).intersection(entry_toneless_keys)
    ]
    if len(toneless_matches) == 1:
        form_stats["matched"] += 1
        form_stats["matched_toneless"] += 1
        record_form_match(form_stats, "toneless")
        return toneless_matches[0], "toneless"

    form = LexiconForm(
        pinyin=entry["pinyin"],
        definitions=definitions_from_meaning_html(entry["meaning_html"]),
        tags=["source:xiehanzi"],
    )
    word.add_form(form)
    word.sort_forms_by_pinyin()
    form_stats["created"] += 1
    record_form_match(form_stats, "created")
    form_stats["created_entries"].append(
        {
            "entry": entry_summary(entry),
            "lookup_key": entry_keys[0] if entry_keys else "",
            "lookup_keys": entry_keys,
            "available_form_pinyins": [existing_form.pinyin for existing_form in forms],
        }
    )
    return form, "created"


def pinyin_formatting_key(value: str) -> str:
    return "/".join(reading.compact for reading in canonical_pinyin_readings(value))


def apply_reference_pinyin_case(source_pinyin: str, reference_pinyin: str) -> str:
    reference_by_key = {
        reading.lower_compact: reading.compact for reading in canonical_pinyin_readings(reference_pinyin)
    }
    cased_tokens: list[str] = []

    for source_part in re.split(r"(/)", source_pinyin or ""):
        if source_part == "/":
            cased_tokens.append(source_part)
            continue

        leading_space = re.match(r"\s*", source_part).group(0)
        trailing_space = re.search(r"\s*$", source_part).group(0)
        stripped_source = source_part.strip()
        if not stripped_source:
            cased_tokens.append(source_part)
            continue

        numbered_source = numbered_pinyin_part(stripped_source)
        source_readings = canonical_pinyin_readings(numbered_source)
        if not source_readings:
            cased_tokens.append(source_part)
            continue

        reference_compact = reference_by_key.get(source_readings[0].lower_compact)
        if not reference_compact:
            cased_tokens.append(f"{leading_space}{numbered_source}{trailing_space}")
            continue

        chars = list(numbered_source)
        reference_index = 0
        for index, char in enumerate(chars):
            if PINYIN_SEPARATOR_RE.fullmatch(char):
                continue
            if reference_index >= len(reference_compact):
                break

            reference_char = reference_compact[reference_index]
            if char.isalpha() and reference_char.isalpha() and char.lower() == reference_char.lower():
                chars[index] = char.upper() if reference_char.isupper() else char.lower()
            reference_index += 1

        cased_tokens.append(f"{leading_space}{''.join(chars)}{trailing_space}")

    return "".join(cased_tokens)


def numbered_pinyin(value: str) -> str:
    if re.search(r"\d", value):
        return normalize_pinyin_u_variants(value)
    try:
        return transcriptions.accented_to_numbered(value)
    except ValueError:
        return value


def non_exact_match_record(
    entry: dict[str, Any],
    match_type: str,
    cc_cedict_pinyin: str | None,
    cc_cedict_definitions: list[str],
    xiehanzi_pinyin: str,
) -> dict[str, Any]:
    return {
        "simplified": entry["simplified"],
        "match_type": match_type,
        "cc_cedict_pinyin": cc_cedict_pinyin,
        "xiehanzi_pinyin": xiehanzi_pinyin,
        "xiehanzi_raw_pinyin": entry.get("raw_pinyin", entry["pinyin"]),
        "cc_cedict_definitions": cc_cedict_definitions,
        "xiehanzi_definitions": definitions_from_meaning_html(entry["meaning_html"]),
    }


def normalized_definition_set(definitions: list[str]) -> set[str]:
    return {re.sub(r"\s+", " ", definition).strip() for definition in definitions if definition.strip()}


def definitions_differ(left: list[str], right: list[str]) -> bool:
    return normalized_definition_set(left) != normalized_definition_set(right)


def new_form_stats() -> dict[str, Any]:
    return {
        "matched": 0,
        "matched_pinyin_variant": 0,
        "matched_toneless": 0,
        "created": 0,
        "match_types": {
            "exact": 0,
            "format_variant": 0,
            "case_variant": 0,
            "reading_variant": 0,
            "spoken_tone_variant": 0,
            "exact_definition": 0,
            "exact_definition_also_pr": 0,
            "toneless": 0,
            "created": 0,
        },
        "created_entries": [],
        "non_exact_matches": [],
        "non_exact_definition_mismatches": [],
        "pinyin_case_preserved": [],
        "pinyin_whitespace_only": [],
        "pinyin_substantive": [],
    }


def pair_source_form_id(item: dict[str, Any]) -> int:
    return int(item["context"]["source_form_id"])


def bucket_source_form_ids(items: list[dict[str, Any]]) -> set[int]:
    return {pair_source_form_id(item) for item in items}


def bucket_matching_pair_count(items: list[dict[str, Any]]) -> int:
    return sum(1 for item in items if "dictionary" in item)


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


def drop_manual_pinyin_override_source_form_pairs(
    selected_items: list[dict[str, Any]],
    remaining_items: list[dict[str, Any]],
) -> dict[str, Any]:
    return drop_source_form_pairs(selected_items, remaining_items)


def drop_format_variant_source_form_pairs(
    selected_items: list[dict[str, Any]],
    remaining_items: list[dict[str, Any]],
) -> dict[str, Any]:
    return drop_source_form_pairs(selected_items, remaining_items)


def consume_spoken_tone_variant_source_form_pairs(
    selected_items: list[dict[str, Any]],
    remaining_items: list[dict[str, Any]],
) -> dict[str, Any]:
    return drop_source_form_pairs(selected_items, remaining_items)


def drop_case_variant_exact_definition_source_form_pairs(
    selected_items: list[dict[str, Any]],
    remaining_items: list[dict[str, Any]],
) -> dict[str, Any]:
    return drop_source_form_pairs(selected_items, remaining_items)


def drop_exact_definition_also_pr_source_form_pairs(
    selected_items: list[dict[str, Any]],
    remaining_items: list[dict[str, Any]],
) -> dict[str, Any]:
    return drop_source_form_pairs(selected_items, remaining_items)


def drop_exact_definition_source_form_pairs(
    selected_items: list[dict[str, Any]],
    remaining_items: list[dict[str, Any]],
) -> dict[str, Any]:
    return drop_source_form_pairs(selected_items, remaining_items)


def apply_legacy_enrichment_fallback_pairs(
    selected_items: list[dict[str, Any]],
    remaining_items: list[dict[str, Any]],
) -> dict[str, Any]:
    _ = remaining_items
    consumed_source_form_ids = bucket_source_form_ids(selected_items)
    return {
        "consumed_source_form_ids": consumed_source_form_ids,
        "consumed_source_form_count": len(consumed_source_form_ids),
        "consumed_matching_pair_count": bucket_matching_pair_count(selected_items),
        "removed_from_remaining_matching_pair_count": 0,
        "remaining_items": [],
    }


CONSUMPTION_RULES = {
    "drop_missing_dictionary_word_source_forms": ConsumptionRuleDefinition(
        name="drop_missing_dictionary_word_source_forms",
        report_only_effect="remove the source form from the pair pipeline before any pairs are materialized",
        enrichment_effect="create synthetic words/forms from xiehanzi source entries",
        handler=drop_missing_dictionary_word_source_forms,
    ),
    "drop_perfect_match_source_form_pairs": ConsumptionRuleDefinition(
        name="drop_perfect_match_source_form_pairs",
        report_only_effect="remove all remaining matching pairs for the consumed source form",
        enrichment_effect="apply exact-pair tags and metadata directly to the selected dictionary form",
        handler=drop_perfect_match_source_form_pairs,
    ),
    "drop_manual_pinyin_override_source_form_pairs": ConsumptionRuleDefinition(
        name="drop_manual_pinyin_override_source_form_pairs",
        report_only_effect="remove all remaining matching pairs for the manually corrected source form",
        enrichment_effect="apply the configured Pinyin override directly to the selected dictionary form",
        handler=drop_manual_pinyin_override_source_form_pairs,
    ),
    "drop_format_variant_source_form_pairs": ConsumptionRuleDefinition(
        name="drop_format_variant_source_form_pairs",
        report_only_effect="remove all remaining matching pairs for the format-variant source form",
        enrichment_effect="apply tags and metadata directly to the selected dictionary form without changing Pinyin",
        handler=drop_format_variant_source_form_pairs,
    ),
    "consume_spoken_tone_variant_source_form_pairs": ConsumptionRuleDefinition(
        name="consume_spoken_tone_variant_source_form_pairs",
        report_only_effect="remove all remaining matching pairs for the spoken-tone-variant source form",
        enrichment_effect="add the source Pinyin as an accepted reading on the selected dictionary form",
        handler=consume_spoken_tone_variant_source_form_pairs,
    ),
    "drop_case_variant_exact_definition_source_form_pairs": ConsumptionRuleDefinition(
        name="drop_case_variant_exact_definition_source_form_pairs",
        report_only_effect="remove all remaining matching pairs for the exact-definition case-variant source form",
        enrichment_effect="apply tags and metadata directly to the selected dictionary form without changing Pinyin",
        handler=drop_case_variant_exact_definition_source_form_pairs,
    ),
    "drop_exact_definition_also_pr_source_form_pairs": ConsumptionRuleDefinition(
        name="drop_exact_definition_also_pr_source_form_pairs",
        report_only_effect="remove all remaining matching pairs for the exact-definition also-pr source form",
        enrichment_effect="apply tags and metadata directly and add explicitly attested also-pr readings",
        handler=drop_exact_definition_also_pr_source_form_pairs,
    ),
    "drop_exact_definition_source_form_pairs": ConsumptionRuleDefinition(
        name="drop_exact_definition_source_form_pairs",
        report_only_effect="remove all remaining matching pairs for the exact-definition source form",
        enrichment_effect="apply tags and metadata directly to the selected dictionary form without changing Pinyin",
        handler=drop_exact_definition_source_form_pairs,
    ),
    "apply_legacy_enrichment_fallback": ConsumptionRuleDefinition(
        name="apply_legacy_enrichment_fallback",
        report_only_effect="consume the terminal default_unresolved rest bucket",
        enrichment_effect="apply the previous hanzi enrichment merge to the remaining source forms",
        handler=apply_legacy_enrichment_fallback_pairs,
    ),
}


def attach_deck_entries_to_state(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    form_stats: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    word_index = build_state_word_index(state)
    unmatched: list[dict[str, Any]] = []
    if form_stats is None:
        form_stats = new_form_stats()

    for entry in deck_entries:
        word = word_index.get(normalize_field(entry["simplified"]))
        if word is None:
            unmatched.append(entry_summary(entry))
            continue

        word.add_tags(entry["tags"])
        word.set_hanzi_frequency_once(entry["frequency"])

        form, match_type = find_or_create_hanzi_form(word, entry, form_stats)
        cc_cedict_pinyin = None if match_type == "created" else form.pinyin
        cc_cedict_definitions = [] if match_type == "created" else list(form.definitions)
        xiehanzi_pinyin = numbered_pinyin(entry["pinyin"])
        if match_type != "exact":
            match_record = non_exact_match_record(
                entry=entry,
                match_type=match_type,
                cc_cedict_pinyin=cc_cedict_pinyin,
                cc_cedict_definitions=cc_cedict_definitions,
                xiehanzi_pinyin=xiehanzi_pinyin,
            )
            form_stats["non_exact_matches"].append(match_record)
            if match_type != "created" and definitions_differ(
                match_record["cc_cedict_definitions"], match_record["xiehanzi_definitions"]
            ):
                form_stats["non_exact_definition_mismatches"].append(match_record)

        prefer_first(form.traditional_variants, entry["traditional"])
        form.add_tags(entry["tags"])

        if entry.get("pinyin"):
            new_pinyin = xiehanzi_pinyin
            old_pinyin = form.pinyin
            if old_pinyin and match_type != "created":
                cased_pinyin = apply_reference_pinyin_case(new_pinyin, str(old_pinyin))
                if cased_pinyin != new_pinyin:
                    form_stats["pinyin_case_preserved"].append(
                        {
                            "simplified": entry["simplified"],
                            "cc_cedict_pinyin": old_pinyin,
                            "xiehanzi_pinyin": new_pinyin,
                            "merged_pinyin": cased_pinyin,
                            "match_type": match_type,
                        }
                    )
                    new_pinyin = cased_pinyin
            if old_pinyin and old_pinyin != new_pinyin and match_type != "created":
                override_record = {
                    "simplified": entry["simplified"],
                    "cc_cedict_pinyin": old_pinyin,
                    "xiehanzi_pinyin": new_pinyin,
                    "match_type": match_type,
                    "cc_cedict_definitions": form.definitions,
                    "xiehanzi_definitions": definitions_from_meaning_html(entry["meaning_html"]),
                }
                if pinyin_formatting_key(str(old_pinyin)) == pinyin_formatting_key(new_pinyin):
                    form_stats["pinyin_whitespace_only"].append(override_record)
                else:
                    form_stats["pinyin_substantive"].append(override_record)
            form.replace_pinyin(new_pinyin)

    return unmatched, form_stats


def deck_entries_for_source_form_ids(
    deck_entries: list[dict[str, Any]], source_form_ids: set[int]
) -> list[dict[str, Any]]:
    return [deck_entries[source_form_id] for source_form_id in sorted(source_form_ids)]


def deck_entry_for_pair(deck_entries: list[dict[str, Any]], item: dict[str, Any]) -> dict[str, Any]:
    return deck_entries[pair_source_form_id(item)]


def deck_entry_with_manual_pinyin_override(deck_entries: list[dict[str, Any]], item: dict[str, Any]) -> dict[str, Any]:
    override = item["context"].get("manual_pinyin_override")
    if override is None:
        raise ValueError(f"Manual Pinyin override bucket item lacks override context: {item!r}")

    entry = dict(deck_entry_for_pair(deck_entries, item))
    entry["raw_pinyin"] = override["raw_pinyin"]
    entry["pinyin"] = override["override_pinyin"]
    entry["manual_pinyin_override"] = override
    return entry


def target_word_and_form_from_pair(
    state: LexiconState,
    item: dict[str, Any],
) -> tuple[LexiconWord, LexiconForm, str, str]:
    target = item.get("target")
    if not isinstance(target, dict):
        raise ValueError(f"Matching pair lacks target identity: {item!r}")

    word_key = str(target.get("word_key") or "")
    form_key = str(target.get("form_key") or "")
    word = state.words.get(word_key)
    if word is None:
        raise ValueError(f"Target word no longer exists in state: {target!r}")

    form = word.forms.get(form_key)
    if form is None:
        raise ValueError(f"Target form no longer exists in state: {target!r}")

    return word, form, word_key, form_key


def apply_entry_metadata_to_selected_form(word: LexiconWord, form: LexiconForm, entry: dict[str, Any]) -> None:
    word.add_tags(entry["tags"])
    word.set_hanzi_frequency_once(entry["frequency"])
    prefer_first(form.traditional_variants, entry["traditional"])
    form.add_tags(entry["tags"])


def unique_form_key(word: LexiconWord, desired_key: str, current_key: str) -> str:
    key = desired_key
    index = 1
    while key in word.forms and key != current_key:
        key = f"{desired_key}#{index}"
        index += 1
    return key


def rekey_form(
    word: LexiconWord,
    current_key: str,
    form: LexiconForm,
    new_pinyin: str,
) -> str:
    new_key = unique_form_key(word, new_pinyin, current_key)
    form.replace_pinyin(new_pinyin)
    if new_key == current_key:
        return current_key

    rebuilt_forms: dict[str, LexiconForm] = {}
    replaced = False
    for key, value in word.forms.items():
        if key == current_key:
            if value is not form:
                raise ValueError(f"Target form key points at a different form: {current_key!r}")
            rebuilt_forms[new_key] = form
            replaced = True
        else:
            rebuilt_forms[key] = value

    if not replaced:
        raise ValueError(f"Target form key disappeared before rekey: {current_key!r}")
    word.forms = rebuilt_forms
    return new_key


def add_synthetic_words_to_state(state: LexiconState, missing_entries: list[dict[str, Any]]) -> list[LexiconWord]:
    synthetic_words = build_synthetic_words(missing_entries)
    for word in synthetic_words:
        key = word.simplified
        if key in state.words:
            raise ValueError(f"Synthetic word collides with existing lexicon word: {key}")
        state.words[key] = word
    return synthetic_words


def consume_perfect_match_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    selected_items = pipeline["bucket_results"]["perfect_match"]["selected_items"]
    consumed_entries: list[dict[str, Any]] = []

    for item in sorted(selected_items, key=pair_source_form_id):
        word, form, _, _ = target_word_and_form_from_pair(state, item)
        entry = deck_entry_for_pair(deck_entries, item)
        if pinyin_rule_kind(entry["pinyin"], form_pinyin_reading_string(form)) != "exact":
            raise ValueError(f"Perfect-match bucket selected a non-exact pair: {item!r}")
        apply_entry_metadata_to_selected_form(word, form, entry)
        form_stats["matched"] += 1
        record_form_match(form_stats, "exact")
        consumed_entries.append(entry)

    return {
        "entries": [entry_summary(entry) for entry in consumed_entries],
        "entry_count": len(consumed_entries),
        "state_effect": "applied exact-pair tags and metadata directly to the selected dictionary forms",
    }


def consume_manual_pinyin_override_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    selected_items = pipeline["bucket_results"]["manual_pinyin_override"]["selected_items"]
    consumed_entries: list[dict[str, Any]] = []

    for item in sorted(selected_items, key=pair_source_form_id):
        word, form, _, form_key = target_word_and_form_from_pair(state, item)
        entry = deck_entry_with_manual_pinyin_override(deck_entries, item)
        old_pinyin = form.pinyin
        match_type = pinyin_rule_kind(entry["pinyin"], form_pinyin_reading_string(form))
        if match_type not in {"exact", "format_variant"}:
            raise ValueError(f"Manual Pinyin override no longer matches the selected target form: {item!r}")

        word.add_tags(entry["tags"])
        word.set_hanzi_frequency_once(entry["frequency"])
        form_stats["matched"] += 1
        record_form_match(form_stats, match_type)

        xiehanzi_pinyin = numbered_pinyin(entry["pinyin"])
        if match_type != "exact":
            match_record = non_exact_match_record(
                entry=entry,
                match_type=match_type,
                cc_cedict_pinyin=old_pinyin,
                cc_cedict_definitions=list(form.definitions),
                xiehanzi_pinyin=xiehanzi_pinyin,
            )
            form_stats["non_exact_matches"].append(match_record)
            if definitions_differ(match_record["cc_cedict_definitions"], match_record["xiehanzi_definitions"]):
                form_stats["non_exact_definition_mismatches"].append(match_record)

        prefer_first(form.traditional_variants, entry["traditional"])
        form.add_tags(entry["tags"])

        new_pinyin = xiehanzi_pinyin
        cased_pinyin = apply_reference_pinyin_case(new_pinyin, str(old_pinyin))
        if cased_pinyin != new_pinyin:
            form_stats["pinyin_case_preserved"].append(
                {
                    "simplified": entry["simplified"],
                    "cc_cedict_pinyin": old_pinyin,
                    "xiehanzi_pinyin": new_pinyin,
                    "merged_pinyin": cased_pinyin,
                    "match_type": match_type,
                }
            )
            new_pinyin = cased_pinyin

        if old_pinyin and old_pinyin != new_pinyin:
            override_record = {
                "simplified": entry["simplified"],
                "cc_cedict_pinyin": old_pinyin,
                "xiehanzi_pinyin": new_pinyin,
                "match_type": match_type,
                "cc_cedict_definitions": form.definitions,
                "xiehanzi_definitions": definitions_from_meaning_html(entry["meaning_html"]),
            }
            if pinyin_formatting_key(str(old_pinyin)) == pinyin_formatting_key(new_pinyin):
                form_stats["pinyin_whitespace_only"].append(override_record)
            else:
                form_stats["pinyin_substantive"].append(override_record)

        new_form_key = rekey_form(word, form_key, form, new_pinyin)
        item["target"] = {**item["target"], "form_key": new_form_key}
        consumed_entries.append(entry)

    return {
        "entries": [entry_summary(entry) for entry in consumed_entries],
        "entry_count": len(consumed_entries),
        "form_stats": form_stats,
        "state_effect": "applied configured Pinyin overrides directly to the selected dictionary forms",
    }


def consume_format_variant_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    selected_items = pipeline["bucket_results"]["format_variant_unique"]["selected_items"]
    consumed_entries: list[dict[str, Any]] = []

    for item in sorted(selected_items, key=pair_source_form_id):
        word, form, _, _ = target_word_and_form_from_pair(state, item)
        entry = deck_entry_for_pair(deck_entries, item)
        if pinyin_rule_kind(entry["pinyin"], form_pinyin_reading_string(form)) != "format_variant":
            raise ValueError(f"Format-variant bucket selected a non-format-variant pair: {item!r}")
        apply_entry_metadata_to_selected_form(word, form, entry)
        form_stats["matched"] += 1
        record_form_match(form_stats, "format_variant")
        consumed_entries.append(entry)

    return {
        "entries": [entry_summary(entry) for entry in consumed_entries],
        "entry_count": len(consumed_entries),
        "form_stats": form_stats,
        "state_effect": "applied format-variant tags and metadata directly without changing dictionary Pinyin",
    }


def consume_spoken_tone_variant_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    selected_items = pipeline["bucket_results"]["spoken_tone_variant"]["selected_items"]
    consumed_entries: list[dict[str, Any]] = []
    added_readings: list[dict[str, Any]] = []

    for item in sorted(selected_items, key=pair_source_form_id):
        spoken_tone_variant = item["context"].get("spoken_tone_variant")
        if not spoken_tone_variant or not spoken_tone_variant.get("kinds"):
            raise ValueError(f"Spoken-tone-variant bucket lacks recognized variant context: {item!r}")

        word, form, _, _ = target_word_and_form_from_pair(state, item)
        entry = deck_entry_for_pair(deck_entries, item)
        dictionary_pinyin = form_pinyin_reading_string(form)
        if pinyin_rule_kind(entry["pinyin"], dictionary_pinyin) != "toneless":
            raise ValueError(f"Spoken-tone-variant bucket selected a non-toneless pair: {item!r}")
        apply_entry_metadata_to_selected_form(word, form, entry)

        source_pinyin = source_pinyin_in_dictionary_format(entry["pinyin"], item["dictionary"]["pinyin"])
        old_readings = list(form.pinyin_readings)
        added = form.add_pinyin_readings(source_pinyin)
        form_stats["matched"] += 1
        record_form_match(form_stats, "spoken_tone_variant")

        added_readings.append(
            {
                "entry": entry_summary(entry),
                "target": item["target"],
                "spoken_tone_variant_kinds": list(spoken_tone_variant["kinds"]),
                "dictionary_primary_pinyin": form.pinyin,
                "source_pinyin": source_pinyin,
                "old_pinyin_readings": old_readings,
                "added_pinyin_readings": added,
                "new_pinyin_readings": list(form.pinyin_readings),
            }
        )
        consumed_entries.append(entry)

    return {
        "entries": [entry_summary(entry) for entry in consumed_entries],
        "entry_count": len(consumed_entries),
        "added_readings": added_readings,
        "form_stats": form_stats,
        "state_effect": "added source Pinyin as accepted readings on the selected dictionary forms",
    }


def consume_case_variant_exact_definition_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    selected_items = pipeline["bucket_results"]["case_variant_exact_definition"]["selected_items"]
    consumed_entries: list[dict[str, Any]] = []

    for item in sorted(selected_items, key=pair_source_form_id):
        word, form, _, _ = target_word_and_form_from_pair(state, item)
        entry = deck_entry_for_pair(deck_entries, item)
        if pinyin_rule_kind(entry["pinyin"], form_pinyin_reading_string(form)) != "case_variant":
            raise ValueError(f"Case-variant bucket selected a non-case-variant pair: {item!r}")
        if not definition_sets_exact(definitions_from_meaning_html(entry["meaning_html"]), list(form.definitions)):
            raise ValueError(f"Case-variant bucket selected a non-exact-definition pair: {item!r}")
        apply_entry_metadata_to_selected_form(word, form, entry)
        form_stats["matched"] += 1
        record_form_match(form_stats, "case_variant")
        consumed_entries.append(entry)

    return {
        "entries": [entry_summary(entry) for entry in consumed_entries],
        "entry_count": len(consumed_entries),
        "form_stats": form_stats,
        "state_effect": "applied case-variant tags and metadata directly without changing dictionary Pinyin",
    }


def consume_exact_definition_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    selected_items = pipeline["bucket_results"]["exact_definition"]["selected_items"]
    consumed_entries: list[dict[str, Any]] = []

    for item in sorted(selected_items, key=pair_source_form_id):
        word, form, _, _ = target_word_and_form_from_pair(state, item)
        entry = deck_entry_for_pair(deck_entries, item)
        if not definition_sets_exact(definitions_from_meaning_html(entry["meaning_html"]), list(form.definitions)):
            raise ValueError(f"Exact-definition bucket selected a non-exact-definition pair: {item!r}")
        apply_entry_metadata_to_selected_form(word, form, entry)
        form_stats["matched"] += 1
        record_form_match(form_stats, "exact_definition")
        consumed_entries.append(entry)

    return {
        "entries": [entry_summary(entry) for entry in consumed_entries],
        "entry_count": len(consumed_entries),
        "missing_deck_after_pipeline": [],
        "form_stats": form_stats,
        "state_effect": "applied exact-definition tags and metadata directly without changing dictionary Pinyin",
    }


def compact_lower_pinyin_key_from_record(record: dict[str, Any]) -> str:
    return str(record.get("compact_lower") or "")


def matching_also_pr_reading_values(item: dict[str, Any]) -> list[str]:
    exact_definition_also_pr = item["context"].get("exact_definition_also_pr")
    if not exact_definition_also_pr:
        raise ValueError(f"Exact-definition also-pr bucket lacks also-pr context: {item!r}")

    extra_keys = {
        compact_lower_pinyin_key_from_record(record)
        for record in exact_definition_also_pr.get("extra_source_readings", [])
    }
    also_pr_by_key = {
        compact_lower_pinyin_key_from_record(record): str(record.get("strict") or "")
        for record in exact_definition_also_pr.get("also_pr_readings", [])
    }

    readings: list[str] = []
    for key in sorted(extra_keys):
        reading = also_pr_by_key.get(key)
        if reading and reading not in readings:
            readings.append(reading)
    if not readings:
        raise ValueError(f"Exact-definition also-pr bucket has no addable extra readings: {item!r}")
    return readings


def pinyin_reading_in_reference_spacing(reading: str, reference_pinyin: str) -> str:
    source_tokens = numbered_pinyin_tokens(reading)
    if not source_tokens:
        return numbered_pinyin_part(reading)

    for reference_part in re.split(r"/", str(reference_pinyin or "")):
        reference_tokens = numbered_pinyin_tokens(reference_part)
        if len(reference_tokens) != len(source_tokens):
            continue
        try:
            return " ".join(
                source_tone_on_reference_base(source_token, reference_token)
                for source_token, reference_token in zip(source_tokens, reference_tokens)
            )
        except ValueError:
            return " ".join(source_tokens)

    return " ".join(source_tokens)


def consume_exact_definition_also_pr_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    selected_items = pipeline["bucket_results"]["exact_definition_also_pr"]["selected_items"]
    consumed_entries: list[dict[str, Any]] = []
    added_readings: list[dict[str, Any]] = []

    for item in sorted(selected_items, key=pair_source_form_id):
        word, form, _, _ = target_word_and_form_from_pair(state, item)
        entry = deck_entry_for_pair(deck_entries, item)
        if not definition_sets_exact(definitions_from_meaning_html(entry["meaning_html"]), list(form.definitions)):
            raise ValueError(f"Exact-definition also-pr bucket selected a non-exact-definition pair: {item!r}")

        apply_entry_metadata_to_selected_form(word, form, entry)
        old_readings = list(form.pinyin_readings)
        requested_readings = [
            pinyin_reading_in_reference_spacing(reading, item["dictionary"]["pinyin"])
            for reading in matching_also_pr_reading_values(item)
        ]
        added = form.add_pinyin_readings(" / ".join(requested_readings))
        word.sort_forms_by_pinyin()
        form_stats["matched"] += 1
        record_form_match(form_stats, "exact_definition_also_pr")

        added_readings.append(
            {
                "entry": entry_summary(entry),
                "target": item["target"],
                "dictionary_primary_pinyin": form.pinyin,
                "requested_pinyin_readings": requested_readings,
                "old_pinyin_readings": old_readings,
                "added_pinyin_readings": added,
                "new_pinyin_readings": list(form.pinyin_readings),
            }
        )
        consumed_entries.append(entry)

    return {
        "entries": [entry_summary(entry) for entry in consumed_entries],
        "entry_count": len(consumed_entries),
        "added_readings": added_readings,
        "missing_deck_after_pipeline": [],
        "form_stats": form_stats,
        "state_effect": "applied exact-definition tags and metadata and added explicitly attested also-pr readings",
    }


def consume_missing_dictionary_word_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
) -> dict[str, Any]:
    missing_source_form_ids = bucket_source_form_ids(
        pipeline["bucket_results"]["missing_dictionary_word"]["selected_items"]
    )
    missing_entries = deck_entries_for_source_form_ids(deck_entries, missing_source_form_ids)
    synthetic_words = add_synthetic_words_to_state(state, missing_entries)
    return {
        "entries": missing_entries,
        "entry_count": len(missing_entries),
        "synthetic_words": synthetic_words,
        "state_effect": "created synthetic words/forms from xiehanzi source entries",
    }


def consume_default_unresolved_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    default_source_form_ids = bucket_source_form_ids(pipeline["bucket_results"]["default_unresolved"]["selected_items"])
    default_entries = deck_entries_for_source_form_ids(deck_entries, default_source_form_ids)
    missing_deck_after_pipeline, form_stats = attach_deck_entries_to_state(
        state,
        default_entries,
        form_stats=form_stats,
    )
    return {
        "entries": default_entries,
        "entry_count": len(default_entries),
        "default_unresolved_entry_count": len(default_source_form_ids),
        "missing_deck_after_pipeline": missing_deck_after_pipeline,
        "form_stats": form_stats,
        "state_effect": "applied the previous hanzi enrichment merge as fallback",
    }


STATE_CONSUMPTION_RULES = {
    "missing_dictionary_word": StateConsumptionRuleDefinition(
        name="consume_missing_dictionary_word_bucket",
        bucket="missing_dictionary_word",
        state_effect="create synthetic words/forms from xiehanzi source entries",
        handler=consume_missing_dictionary_word_bucket,
    ),
    "perfect_match": StateConsumptionRuleDefinition(
        name="consume_perfect_match_bucket",
        bucket="perfect_match",
        state_effect="apply exact-pair tags and metadata directly to selected dictionary forms",
        handler=consume_perfect_match_bucket,
    ),
    "manual_pinyin_override": StateConsumptionRuleDefinition(
        name="consume_manual_pinyin_override_bucket",
        bucket="manual_pinyin_override",
        state_effect="apply configured Pinyin overrides directly to selected dictionary forms",
        handler=consume_manual_pinyin_override_bucket,
    ),
    "format_variant_unique": StateConsumptionRuleDefinition(
        name="consume_format_variant_bucket",
        bucket="format_variant_unique",
        state_effect="apply format-variant tags and metadata directly without changing dictionary Pinyin",
        handler=consume_format_variant_bucket,
    ),
    "spoken_tone_variant": StateConsumptionRuleDefinition(
        name="consume_spoken_tone_variant_bucket",
        bucket="spoken_tone_variant",
        state_effect="add source Pinyin as accepted readings on selected dictionary forms",
        handler=consume_spoken_tone_variant_bucket,
    ),
    "case_variant_exact_definition": StateConsumptionRuleDefinition(
        name="consume_case_variant_exact_definition_bucket",
        bucket="case_variant_exact_definition",
        state_effect="apply case-variant tags and metadata directly without changing dictionary Pinyin",
        handler=consume_case_variant_exact_definition_bucket,
    ),
    "exact_definition_also_pr": StateConsumptionRuleDefinition(
        name="consume_exact_definition_also_pr_bucket",
        bucket="exact_definition_also_pr",
        state_effect="apply exact-definition tags and metadata and add explicitly attested also-pr readings",
        handler=consume_exact_definition_also_pr_bucket,
    ),
    "exact_definition": StateConsumptionRuleDefinition(
        name="consume_exact_definition_bucket",
        bucket="exact_definition",
        state_effect="apply exact-definition tags and metadata directly without changing dictionary Pinyin",
        handler=consume_exact_definition_bucket,
    ),
    "default_unresolved": StateConsumptionRuleDefinition(
        name="consume_default_unresolved_bucket",
        bucket="default_unresolved",
        state_effect="apply the previous hanzi enrichment merge as fallback",
        handler=consume_default_unresolved_bucket,
    ),
}


def apply_pipeline_enrichment_to_state(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
) -> dict[str, Any]:
    missing_dictionary_word = STATE_CONSUMPTION_RULES["missing_dictionary_word"].handler(
        state,
        deck_entries,
        pipeline,
    )

    form_stats = new_form_stats()
    perfect_match_stats = STATE_CONSUMPTION_RULES["perfect_match"].handler(
        state=state,
        deck_entries=deck_entries,
        pipeline=pipeline,
        form_stats=form_stats,
    )

    manual_pinyin_override_stats = STATE_CONSUMPTION_RULES["manual_pinyin_override"].handler(
        state=state,
        deck_entries=deck_entries,
        pipeline=pipeline,
        form_stats=form_stats,
    )
    form_stats = manual_pinyin_override_stats["form_stats"]

    format_variant_stats = STATE_CONSUMPTION_RULES["format_variant_unique"].handler(
        state=state,
        deck_entries=deck_entries,
        pipeline=pipeline,
        form_stats=form_stats,
    )
    form_stats = format_variant_stats["form_stats"]

    spoken_tone_variant = STATE_CONSUMPTION_RULES["spoken_tone_variant"].handler(
        state=state,
        deck_entries=deck_entries,
        pipeline=pipeline,
        form_stats=form_stats,
    )
    form_stats = spoken_tone_variant["form_stats"]

    case_variant_exact_definition = STATE_CONSUMPTION_RULES["case_variant_exact_definition"].handler(
        state=state,
        deck_entries=deck_entries,
        pipeline=pipeline,
        form_stats=form_stats,
    )
    form_stats = case_variant_exact_definition["form_stats"]

    exact_definition_also_pr = STATE_CONSUMPTION_RULES["exact_definition_also_pr"].handler(
        state=state,
        deck_entries=deck_entries,
        pipeline=pipeline,
        form_stats=form_stats,
    )
    form_stats = exact_definition_also_pr["form_stats"]

    exact_definition = STATE_CONSUMPTION_RULES["exact_definition"].handler(
        state=state,
        deck_entries=deck_entries,
        pipeline=pipeline,
        form_stats=form_stats,
    )
    form_stats = exact_definition["form_stats"]

    default_unresolved = STATE_CONSUMPTION_RULES["default_unresolved"].handler(
        state,
        deck_entries,
        pipeline,
        form_stats=form_stats,
    )
    form_stats = default_unresolved["form_stats"]

    return {
        "synthetic_words": missing_dictionary_word["synthetic_words"],
        "missing_dictionary_word": {
            key: value for key, value in missing_dictionary_word.items() if key != "synthetic_words"
        },
        "missing_deck_entries_before_stubs": missing_dictionary_word["entries"],
        "perfect_match": perfect_match_stats,
        "manual_pinyin_override": manual_pinyin_override_stats,
        "format_variant_unique": format_variant_stats,
        "spoken_tone_variant": spoken_tone_variant,
        "case_variant_exact_definition": case_variant_exact_definition,
        "exact_definition_also_pr": exact_definition_also_pr,
        "exact_definition": exact_definition,
        "default_unresolved": {
            key: value for key, value in default_unresolved.items() if key not in {"entries", "form_stats"}
        },
        "default_fallback_entries": [entry_summary(entry) for entry in default_unresolved["entries"]],
        "default_fallback_entry_count": default_unresolved["entry_count"],
        "missing_deck_after_pipeline": default_unresolved["missing_deck_after_pipeline"],
        "form_stats": form_stats,
    }
