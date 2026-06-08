"""Shared predicates used by xiehanzi matching and consumption rules."""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass

from anki_hanzi.pinyin import PINYIN_SEPARATOR_RE, strict_numbered_preserve_case


LI_RE = re.compile(r"<li>(.*?)</li>", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class RulePinyinReading:
    strict: str
    compact_preserve_case: str
    compact_lower: str
    toneless_lower: str


def pinyin_rule_readings(value: str) -> list[RulePinyinReading]:
    readings: list[RulePinyinReading] = []
    for part in re.split(r"/", str(value or "")):
        strict = strict_numbered_preserve_case(part)
        if not strict:
            continue
        compact_preserve_case = PINYIN_SEPARATOR_RE.sub("", strict)
        compact_lower = compact_preserve_case.casefold()
        toneless_lower = re.sub(r"\d", "", compact_lower)
        readings.append(
            RulePinyinReading(
                strict=strict,
                compact_preserve_case=compact_preserve_case,
                compact_lower=compact_lower,
                toneless_lower=toneless_lower,
            )
        )
    return readings


def pinyin_rule_values(readings: list[RulePinyinReading], attribute: str) -> list[str]:
    return [getattr(reading, attribute) for reading in readings]


def pinyin_rule_values_overlap(source_values: list[str], dictionary_values: list[str]) -> bool:
    return bool(set(source_values) & set(dictionary_values))


def pinyin_rule_kind(source_pinyin: str, dictionary_pinyin: str) -> str:
    source_readings = pinyin_rule_readings(source_pinyin)
    dictionary_readings = pinyin_rule_readings(dictionary_pinyin)
    if not source_readings or not dictionary_readings:
        return "missing"

    source_strict = pinyin_rule_values(source_readings, "strict")
    dictionary_strict = pinyin_rule_values(dictionary_readings, "strict")
    if source_strict == dictionary_strict:
        return "exact"

    source_compact_preserve_case = pinyin_rule_values(source_readings, "compact_preserve_case")
    dictionary_compact_preserve_case = pinyin_rule_values(dictionary_readings, "compact_preserve_case")
    if source_compact_preserve_case == dictionary_compact_preserve_case:
        return "format_variant"

    source_compact_lower = pinyin_rule_values(source_readings, "compact_lower")
    dictionary_compact_lower = pinyin_rule_values(dictionary_readings, "compact_lower")
    if source_compact_lower == dictionary_compact_lower:
        return "case_variant"

    source_toneless_lower = pinyin_rule_values(source_readings, "toneless_lower")
    dictionary_toneless_lower = pinyin_rule_values(dictionary_readings, "toneless_lower")
    if source_toneless_lower == dictionary_toneless_lower:
        return "toneless"

    if (
        pinyin_rule_values_overlap(source_strict, dictionary_strict)
        or pinyin_rule_values_overlap(source_compact_preserve_case, dictionary_compact_preserve_case)
        or pinyin_rule_values_overlap(source_compact_lower, dictionary_compact_lower)
        or pinyin_rule_values_overlap(source_toneless_lower, dictionary_toneless_lower)
    ):
        return "reading_overlap"

    return "mismatch"


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


def normalize_matching_definition(value: str) -> str:
    value = unicodedata.normalize("NFC", strip_html_text(value)).casefold()
    return re.sub(r"\s+", " ", value).strip()


def normalized_matching_definition_set(definitions: list[str]) -> set[str]:
    values = {normalize_matching_definition(definition) for definition in definitions}
    values.discard("")
    return values


def definition_sets_exact(left: list[str], right: list[str]) -> bool:
    left_set = normalized_matching_definition_set(left)
    right_set = normalized_matching_definition_set(right)
    return bool(left_set) and left_set == right_set
