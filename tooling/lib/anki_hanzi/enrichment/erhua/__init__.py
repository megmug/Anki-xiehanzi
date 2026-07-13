"""Resolve CC-CEDICT erhua variant definition references."""

from __future__ import annotations

from typing import Any

from anki_hanzi.enrichment.model import EnrichmentStageResult
from anki_hanzi.lexicon import LexiconForm, LexiconState, LexiconWord
from anki_hanzi.lexicon.definitions import (
    ErhuaVariantDefinition,
    PlainDefinition,
    definition_display_texts,
)
from anki_hanzi.pinyin import normalize_single_pinyin


def _form_label(word: LexiconWord, form: LexiconForm) -> dict[str, Any]:
    return {
        "simplified": word.simplified,
        "pinyin": form.pinyin,
        "definitions": list(form.definitions),
    }


def _matching_target_forms(
    state: LexiconState,
    simplified: str,
    pinyin: str,
) -> list[LexiconForm]:
    word = state.words.get(simplified)
    if word is None:
        return []

    normalized_pinyin = normalize_single_pinyin(pinyin)
    return [
        form
        for form in word.forms_in_order()
        if normalized_pinyin and normalized_pinyin in (form.pinyin_readings or [form.pinyin])
    ]


def _has_erhua_variant_only(form: LexiconForm) -> bool:
    items = form.definition_items
    return bool(items) and all(isinstance(item, ErhuaVariantDefinition) for item in items)


def _resolved_definition_texts(source_form: LexiconForm, target_form: LexiconForm) -> list[str]:
    source_texts = set(definition_display_texts(source_form.definition_items))
    resolved_texts: list[str] = []
    seen = set(source_texts)
    for text in definition_display_texts(target_form.definition_items):
        if text in seen:
            continue
        resolved_texts.append(text)
        seen.add(text)
    return resolved_texts


def apply_erhua_definition_enrichment_to_state(state: LexiconState) -> EnrichmentStageResult:
    report: dict[str, Any] = {
        "stage": "erhua_definition_enrichment",
        "description": "Resolve CC-CEDICT erhua variant references into nested derived definition lines.",
        "scanned_erhua_definitions": 0,
        "resolved_erhua_definitions": 0,
        "duplicate_only_erhua_definitions": 0,
        "unresolved_erhua_definitions": 0,
        "unresolved_by_reason": {},
        "samples": {
            "resolved": [],
            "duplicate_only": [],
            "unresolved": [],
        },
    }

    def add_unresolved(reason: str, word: LexiconWord, form: LexiconForm, item: ErhuaVariantDefinition) -> None:
        report["unresolved_erhua_definitions"] += 1
        unresolved_by_reason = report["unresolved_by_reason"]
        unresolved_by_reason[reason] = unresolved_by_reason.get(reason, 0) + 1
        if len(report["samples"]["unresolved"]) < 25:
            report["samples"]["unresolved"].append(
                {
                    **_form_label(word, form),
                    "definition": item.text,
                    "target_simplified": item.target_simplified,
                    "target_pinyin": item.target_pinyin,
                    "reason": reason,
                }
            )

    for word in state.sorted_words():
        for form in word.forms_in_order():
            for item in form.definition_items:
                if not isinstance(item, ErhuaVariantDefinition):
                    continue

                report["scanned_erhua_definitions"] += 1
                target_word = state.words.get(item.target_simplified)
                if target_word is None:
                    add_unresolved("missing_target_word", word, form, item)
                    continue

                target_forms = _matching_target_forms(state, item.target_simplified, item.target_pinyin)
                if not target_forms:
                    add_unresolved("missing_target_form", word, form, item)
                    continue
                if len(target_forms) > 1:
                    add_unresolved("ambiguous_target_form", word, form, item)
                    continue

                target_form = target_forms[0]
                if _has_erhua_variant_only(target_form):
                    add_unresolved("recursive_target", word, form, item)
                    continue

                resolved_texts = _resolved_definition_texts(form, target_form)
                if not resolved_texts:
                    report["duplicate_only_erhua_definitions"] += 1
                    if len(report["samples"]["duplicate_only"]) < 25:
                        report["samples"]["duplicate_only"].append(
                            {
                                **_form_label(word, form),
                                "definition": item.text,
                                "target": _form_label(target_word, target_form),
                            }
                        )
                    continue

                item.resolved_definitions = [PlainDefinition(text=text) for text in resolved_texts]
                report["resolved_erhua_definitions"] += 1
                if len(report["samples"]["resolved"]) < 25:
                    report["samples"]["resolved"].append(
                        {
                            **_form_label(word, form),
                            "definition": item.text,
                            "target": _form_label(target_word, target_form),
                            "resolved_definitions": resolved_texts,
                        }
                    )

    return EnrichmentStageResult(
        name="erhua_definition_enrichment",
        summary={
            "erhua_variant_definitions": report["scanned_erhua_definitions"],
            "erhua_variant_definitions_resolved": report["resolved_erhua_definitions"],
            "erhua_variant_definitions_duplicate_only": report["duplicate_only_erhua_definitions"],
            "erhua_variant_definitions_unresolved": report["unresolved_erhua_definitions"],
        },
        report=report,
    )
