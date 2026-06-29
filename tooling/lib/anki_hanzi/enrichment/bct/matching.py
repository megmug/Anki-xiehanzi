"""Matching rules for BCT source terms."""

from __future__ import annotations

from dataclasses import dataclass
import re

from anki_hanzi.enrichment.bct.model import (
    BctBucketMatch,
    BctMatchingRuleDefinition,
    BctSourceTerm,
    BctTargetMatch,
    BctUnresolvedTerm,
)
from anki_hanzi.lexicon import LexiconState
from anki_hanzi.lexicon.state import LexiconForm
from anki_hanzi.pinyin import (
    numbered_pinyin_token_pairs,
    pinyin_base_key,
    strict_numbered_preserve_case,
)


PLAIN_HANZI_TERM_RE = re.compile(r"^[\u3400-\u9fff]+$")
PINYIN_HINT_RE = re.compile(r"^[A-Za-züÜv:ǖǘǚǜāáǎàēéěèīíǐìōóǒòūúǔù]+[1-5]?$")
POS_MARKER_RE = re.compile(r"^(?P<base>[\u3400-\u9fff]+)<[^>]+>$")
FULLWIDTH_PAREN_RE = re.compile(r"^(?P<base>[\u3400-\u9fff]+)（(?P<inner>[^）]+)）$")
LATIN_SUFFIX_RE = re.compile(r"^(?P<base>[\u3400-\u9fff]+)(?P<pinyin>[A-Za-züÜv:]+[1-5]?)$")
TONE_LABELS = {
    "一声": "1",
    "二声": "2",
    "三声": "3",
    "四声": "4",
    "轻声": "5",
}
MANUAL_SOURCE_FORM_TARGETS = {
    "上（面）": (("上", "shang4"), ("上面", "shang4 mian4")),
    "六/陆": (("六", "liu4"), ("陆", "liu4")),
    "十/拾": (("十", "shi2"), ("拾", "shi2")),
    "哪（哪儿）": (("哪", "na3"), ("哪儿", "na3 r5")),
    "这（这儿）": (("这", "zhe4"), ("这儿", "zhe4 r5")),
    "那（那儿）": (("那", "na4"), ("那儿", "na4 r5")),
}


@dataclass(frozen=True)
class BctTargetRequest:
    simplified: str
    source_notation: str
    pinyin_hint: str | None = None
    pinyin_base_hint: str | None = None
    tone_hint: str | None = None


def is_plain_hanzi_term(value: str) -> bool:
    return bool(PLAIN_HANZI_TERM_RE.fullmatch(value))


def is_lowercase_pinyin_form(form: LexiconForm) -> bool:
    pinyin = form.pinyin_reading_string
    return pinyin == pinyin.casefold()


def unique_lowercase_form(forms: list[LexiconForm]) -> LexiconForm | None:
    candidates = [form for form in forms if is_lowercase_pinyin_form(form)]
    if len(candidates) == 1:
        return candidates[0]
    return None


def form_readings(form: LexiconForm) -> list[str]:
    return form.pinyin_readings or [form.pinyin]


def resolve_plain_target(
    state: LexiconState,
    simplified: str,
    *,
    source_notation: str,
) -> BctTargetMatch | None:
    word = state.words.get(simplified)
    if word is None:
        return None

    forms = word.forms_in_order()
    if len(forms) == 1:
        return BctTargetMatch(
            word=word,
            forms=tuple(forms),
            tag_word=True,
            report={
                "source_notation": source_notation,
                "resolution": "single_form",
            },
        )

    lowercase_form = unique_lowercase_form(forms)
    if lowercase_form is None:
        return None

    return BctTargetMatch(
        word=word,
        forms=(lowercase_form,),
        tag_word=False,
        report={
            "source_notation": source_notation,
            "resolution": "unique_lowercase_form",
            "selected_pinyin": lowercase_form.pinyin_reading_string,
            "ignored_pinyin": [
                form.pinyin_reading_string for form in forms if form is not lowercase_form
            ],
        },
    )


def form_has_exact_pinyin_hint(form: LexiconForm, pinyin_hint: str) -> bool:
    hint_key = strict_numbered_preserve_case(pinyin_hint)
    return any(strict_numbered_preserve_case(reading) == hint_key for reading in form_readings(form))


def form_has_base_pinyin_hint(form: LexiconForm, pinyin_hint: str) -> bool:
    hint_base = pinyin_base_key(pinyin_hint)
    for reading in form_readings(form):
        for base, _tone in numbered_pinyin_token_pairs(strict_numbered_preserve_case(reading)):
            if pinyin_base_key(base) == hint_base:
                return True
    return False


def form_has_single_syllable_tone_hint(form: LexiconForm, tone_hint: str) -> bool:
    for reading in form_readings(form):
        pairs = numbered_pinyin_token_pairs(strict_numbered_preserve_case(reading))
        if len(pairs) == 1 and pairs[0][1] == tone_hint:
            return True
    return False


def form_has_strict_pinyin(form: LexiconForm, pinyin: str) -> bool:
    target = strict_numbered_preserve_case(pinyin)
    return any(strict_numbered_preserve_case(reading) == target for reading in form_readings(form))


def resolve_manual_source_form_targets(
    state: LexiconState,
    source_word: str,
) -> tuple[BctTargetMatch, ...] | None:
    targets = MANUAL_SOURCE_FORM_TARGETS.get(source_word)
    if targets is None:
        return None

    resolved: list[BctTargetMatch] = []
    for simplified, pinyin in targets:
        word = state.words.get(simplified)
        if word is None:
            return None

        forms = word.forms_in_order()
        matching_forms = [form for form in forms if form_has_strict_pinyin(form, pinyin)]
        if len(matching_forms) != 1:
            return None

        resolved.append(
            BctTargetMatch(
                word=word,
                forms=(matching_forms[0],),
                tag_word=len(forms) == 1,
                report={
                    "source_notation": source_word,
                    "selected_pinyin": matching_forms[0].pinyin_reading_string,
                },
            )
        )

    return tuple(resolved)


def resolve_pinyin_target(
    state: LexiconState,
    request: BctTargetRequest,
) -> BctTargetMatch | None:
    word = state.words.get(request.simplified)
    if word is None:
        return None

    forms = word.forms_in_order()
    if request.pinyin_hint is not None:
        matches = [
            form for form in forms if form_has_exact_pinyin_hint(form, request.pinyin_hint)
        ]
        resolution = "exact_pinyin_hint"
    elif request.pinyin_base_hint is not None:
        matches = [
            form for form in forms if form_has_base_pinyin_hint(form, request.pinyin_base_hint)
        ]
        resolution = "base_pinyin_hint"
    elif request.tone_hint is not None:
        matches = [
            form for form in forms if form_has_single_syllable_tone_hint(form, request.tone_hint)
        ]
        resolution = "single_syllable_tone_hint"
    else:
        return None

    if len(matches) != 1:
        return None

    return BctTargetMatch(
        word=word,
        forms=(matches[0],),
        tag_word=len(forms) == 1,
        report={
            "source_notation": request.source_notation,
            "resolution": resolution,
            "selected_pinyin": matches[0].pinyin_reading_string,
        },
    )


def parse_hanzi_parenthetical_source(term: str) -> tuple[BctTargetRequest, ...] | None:
    match = FULLWIDTH_PAREN_RE.fullmatch(term)
    if match is None:
        return None

    base = match.group("base")
    inner = match.group("inner").strip()
    if not inner:
        return None

    tone_hint = TONE_LABELS.get(inner)
    if tone_hint is not None:
        return (
            BctTargetRequest(
                simplified=base,
                source_notation=term,
                tone_hint=tone_hint,
            ),
        )

    if is_plain_hanzi_term(inner):
        expanded = inner if inner.startswith(base) else f"{base}{inner}"
        variants = tuple(dict.fromkeys([base, expanded]))
        return tuple(
            BctTargetRequest(
                simplified=variant,
                source_notation=term,
            )
            for variant in variants
        )

    if PINYIN_HINT_RE.fullmatch(inner):
        return (
            BctTargetRequest(
                simplified=base,
                source_notation=term,
                pinyin_hint=inner,
            ),
        )

    return None


def parse_structured_source_term(term: str) -> tuple[BctTargetRequest, ...] | None:
    term = term.strip()
    if not term or "……" in term:
        return None

    if "/" in term:
        variants = [variant.strip() for variant in term.split("/") if variant.strip()]
        if variants and all(is_plain_hanzi_term(variant) for variant in variants):
            return tuple(
                BctTargetRequest(
                    simplified=variant,
                    source_notation=term,
                )
                for variant in dict.fromkeys(variants)
            )

    if " " in term:
        compact = re.sub(r"\s+", "", term)
        if is_plain_hanzi_term(compact):
            return (
                BctTargetRequest(
                    simplified=compact,
                    source_notation=term,
                ),
            )

    parenthetical = parse_hanzi_parenthetical_source(term)
    if parenthetical is not None:
        return parenthetical

    pos_marker = POS_MARKER_RE.fullmatch(term)
    if pos_marker is not None:
        return (
            BctTargetRequest(
                simplified=pos_marker.group("base"),
                source_notation=term,
            ),
        )

    latin_suffix = LATIN_SUFFIX_RE.fullmatch(term)
    if latin_suffix is not None:
        return (
            BctTargetRequest(
                simplified=latin_suffix.group("base"),
                source_notation=term,
                pinyin_base_hint=latin_suffix.group("pinyin"),
            ),
        )

    return None


def resolve_structured_target(
    state: LexiconState,
    request: BctTargetRequest,
) -> BctTargetMatch | None:
    if request.pinyin_hint or request.pinyin_base_hint or request.tone_hint:
        return resolve_pinyin_target(state, request)
    return resolve_plain_target(
        state,
        request.simplified,
        source_notation=request.source_notation,
    )


def match_structured_source_term_variants(
    state: LexiconState,
    source: BctSourceTerm,
) -> BctBucketMatch | None:
    requests = parse_structured_source_term(source.word)
    if requests is None:
        return None

    targets: list[BctTargetMatch] = []
    for request in requests:
        target = resolve_structured_target(state, request)
        if target is None:
            return None
        targets.append(target)

    return BctBucketMatch(
        source=source,
        method="structured_source_term_variants",
        targets=tuple(targets),
        report={
            "source_notation": source.word,
            "resolved_terms": [request.simplified for request in requests],
        },
    )


def match_manual_source_form_targets(
    state: LexiconState,
    source: BctSourceTerm,
) -> BctBucketMatch | None:
    targets = resolve_manual_source_form_targets(state, source.word)
    if targets is None:
        return None

    return BctBucketMatch(
        source=source,
        method="manual_source_form_targets",
        targets=targets,
        report={
            "source_notation": source.word,
            "resolved_targets": [
                {
                    "word": target.word.simplified,
                    "pinyin": target.forms[0].pinyin_reading_string,
                    "tag_word": target.tag_word,
                }
                for target in targets
            ],
        },
    )


def match_exact_word_single_form(
    state: LexiconState,
    source: BctSourceTerm,
) -> BctBucketMatch | None:
    if not is_plain_hanzi_term(source.word):
        return None

    word = state.words.get(source.word)
    if word is None:
        return None

    forms = word.forms_in_order()
    if len(forms) != 1:
        return None

    return BctBucketMatch(
        source=source,
        method="exact_word_single_form",
        targets=(
            BctTargetMatch(
                word=word,
                forms=tuple(forms),
                tag_word=True,
            ),
        ),
    )


def match_exact_word_unique_lowercase_form(
    state: LexiconState,
    source: BctSourceTerm,
) -> BctBucketMatch | None:
    if not is_plain_hanzi_term(source.word):
        return None

    word = state.words.get(source.word)
    if word is None:
        return None

    forms = word.forms_in_order()
    if len(forms) == 1:
        return None

    lowercase_form = unique_lowercase_form(forms)
    if lowercase_form is None:
        return None

    ignored_pinyin = [
        form.pinyin_reading_string for form in forms if form is not lowercase_form
    ]
    return BctBucketMatch(
        source=source,
        method="exact_word_unique_lowercase_form",
        targets=(
            BctTargetMatch(
                word=word,
                forms=(lowercase_form,),
                tag_word=False,
            ),
        ),
        report={
            "selected_pinyin": lowercase_form.pinyin_reading_string,
            "ignored_pinyin": ignored_pinyin,
        },
    )


def source_unique_dictionary_word_candidate(source_word: str) -> str | None:
    if is_plain_hanzi_term(source_word):
        return source_word

    requests = parse_structured_source_term(source_word)
    if requests is None:
        return None

    if any(
        request.pinyin_hint is not None
        or request.pinyin_base_hint is not None
        or request.tone_hint is not None
        for request in requests
    ):
        return None

    simplified_values = tuple(dict.fromkeys(request.simplified for request in requests))
    if len(simplified_values) != 1:
        return None

    return simplified_values[0]


def match_unique_dictionary_word_all_forms(
    state: LexiconState,
    source: BctSourceTerm,
) -> BctBucketMatch | None:
    simplified = source_unique_dictionary_word_candidate(source.word)
    if simplified is None:
        return None

    word = state.words.get(simplified)
    if word is None:
        return None

    forms = word.forms_in_order()
    if len(forms) <= 1:
        return None

    return BctBucketMatch(
        source=source,
        method="unique_dictionary_word_all_forms",
        targets=(
            BctTargetMatch(
                word=word,
                forms=tuple(forms),
                tag_word=True,
            ),
        ),
        report={
            "resolved_word": simplified,
            "selected_pinyin": [form.pinyin_reading_string for form in forms],
        },
    )


def match_missing_dictionary_word(
    state: LexiconState,
    source: BctSourceTerm,
) -> BctBucketMatch | None:
    if not is_plain_hanzi_term(source.word):
        return None
    if source.word in state.words:
        return None
    return BctBucketMatch(
        source=source,
        method="missing_dictionary_word",
        targets=(),
        report={
            "reason": "missing_dictionary_word",
            "action": "ignored",
        },
    )


def match_non_lexical_pattern(
    _state: LexiconState,
    source: BctSourceTerm,
) -> BctBucketMatch | None:
    if "……" not in source.word:
        return None
    return BctBucketMatch(
        source=source,
        method="non_lexical_pattern",
        targets=(),
        report={
            "reason": "non_lexical_pattern",
            "action": "ignored",
            "source_notation": source.word,
        },
    )


def diagnose_unresolved_term(
    state: LexiconState,
    source: BctSourceTerm,
) -> BctUnresolvedTerm:
    if not is_plain_hanzi_term(source.word):
        return BctUnresolvedTerm(
            source=source,
            reason="non_plain_hanzi_source_term",
        )

    word = state.words.get(source.word)
    if word is None:
        return BctUnresolvedTerm(
            source=source,
            reason="missing_dictionary_word",
        )

    return BctUnresolvedTerm(
        source=source,
        reason="ambiguous_dictionary_forms",
        report={
            "dictionary_pinyin": [
                form.pinyin_reading_string for form in word.forms_in_order()
            ],
        },
    )


EXACT_WORD_SINGLE_FORM_RULE = BctMatchingRuleDefinition(
    name="exact_word_single_form",
    description=(
        "Plain Hanzi BCT term whose exact simplified dictionary word has exactly "
        "one form."
    ),
    match=match_exact_word_single_form,
)

EXACT_WORD_UNIQUE_LOWERCASE_FORM_RULE = BctMatchingRuleDefinition(
    name="exact_word_unique_lowercase_form",
    description=(
        "Plain Hanzi BCT term whose exact simplified dictionary word has multiple "
        "forms, but exactly one form uses lowercase Pinyin and the remaining forms "
        "are casing variants such as proper names."
    ),
    match=match_exact_word_unique_lowercase_form,
)

UNIQUE_DICTIONARY_WORD_ALL_FORMS_RULE = BctMatchingRuleDefinition(
    name="unique_dictionary_word_all_forms",
    description=(
        "BCT source term that points to exactly one dictionary word without "
        "Pinyin or tone evidence, after higher-priority BCT rules could not "
        "select one specific form. BCT is treated as word-level evidence here, "
        "so the term is consumed by tagging the word and all of its forms."
    ),
    match=match_unique_dictionary_word_all_forms,
)

STRUCTURED_SOURCE_TERM_VARIANTS_RULE = BctMatchingRuleDefinition(
    name="structured_source_term_variants",
    description=(
        "BCT source term with explicit source notation such as spaces, slash "
        "variants, full-width parenthetical variants, POS markers, or explicit "
        "Pinyin/tone hints. The rule consumes the term only if every explicit "
        "target resolves to one safe dictionary form."
    ),
    match=match_structured_source_term_variants,
)

MANUAL_SOURCE_FORM_TARGETS_RULE = BctMatchingRuleDefinition(
    name="manual_source_form_targets",
    description=(
        "Curated BCT source notation whose exact target dictionary forms are "
        "known. The rule matches each configured source term to exact "
        "simplified+Pinyin forms and does not tag unrelated forms of the same "
        "word."
    ),
    match=match_manual_source_form_targets,
)

MISSING_DICTIONARY_WORD_RULE = BctMatchingRuleDefinition(
    name="missing_dictionary_word",
    description=(
        "Plain Hanzi BCT term whose exact simplified word does not exist in the "
        "dictionary. The source term is consumed intentionally without adding "
        "tags or creating dictionary data."
    ),
    match=match_missing_dictionary_word,
)

NON_LEXICAL_PATTERN_RULE = BctMatchingRuleDefinition(
    name="non_lexical_pattern",
    description=(
        "BCT source term containing the explicit ellipsis construction marker "
        "`……`. These entries describe grammar patterns rather than lexical "
        "dictionary words and are consumed intentionally without adding tags."
    ),
    match=match_non_lexical_pattern,
)
