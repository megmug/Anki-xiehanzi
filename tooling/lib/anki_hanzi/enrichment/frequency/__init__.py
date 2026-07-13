"""Frequency-list enrichment stage for the hanzi LexiconState."""

from __future__ import annotations

import html
import re
import unicodedata
from pathlib import Path

from anki_hanzi.enrichment.model import EnrichmentStageResult
from anki_hanzi.lexicon import LexiconState


DEFAULT_DECK_INPUTS_DIR = Path("deck_inputs")
DEFAULT_FREQUENCY_LIST = (
    DEFAULT_DECK_INPUTS_DIR / "hsk-3.0-words-list/Scripts and data/blog_lit_news_tech_weibo_freq.release_sorted.txt"
)
TOP_FREQUENCY_THRESHOLDS = (500, 2500, 10000)


def normalize_field(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = unicodedata.normalize("NFC", value)
    return re.sub(r"\s+", "", value).strip().lower()


def load_frequency_ranks(frequency_list_path: Path) -> dict[str, int]:
    ranks: dict[str, int] = {}
    with frequency_list_path.open(encoding="utf-8") as handle:
        for rank, line in enumerate(handle, start=1):
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            key = normalize_field(parts[0])
            if key and key not in ranks:
                ranks[key] = rank
    return ranks


def top_frequency_tags(rank: int | None) -> list[str]:
    if rank is None:
        return []
    return [f"freq:top{threshold}" for threshold in TOP_FREQUENCY_THRESHOLDS if rank <= threshold]


def apply_frequency_enrichment_to_state(
    state: LexiconState,
    frequency_list_path: Path,
) -> EnrichmentStageResult:
    ranks = load_frequency_ranks(frequency_list_path)
    tagged_words_by_threshold = {f"top{threshold}": 0 for threshold in TOP_FREQUENCY_THRESHOLDS}
    tagged_forms_by_threshold = {f"top{threshold}": 0 for threshold in TOP_FREQUENCY_THRESHOLDS}
    matched_words = 0

    for word in state.sorted_words():
        rank = ranks.get(normalize_field(word.simplified))
        tags = top_frequency_tags(rank)
        if not tags:
            continue

        matched_words += 1
        word.frequency_rank = rank
        word.add_tags(tags)

        for tag in tags:
            tagged_words_by_threshold[tag.removeprefix("freq:")] += 1

        for form in word.forms.values():
            form.add_tags(tags)
            for tag in tags:
                tagged_forms_by_threshold[tag.removeprefix("freq:")] += 1

    report = {
        "stage": "frequency_enrichment",
        "source": str(frequency_list_path),
        "thresholds": list(TOP_FREQUENCY_THRESHOLDS),
        "source_entries": len(ranks),
        "matched_words": matched_words,
        "tagged_words_by_threshold": tagged_words_by_threshold,
        "tagged_forms_by_threshold": tagged_forms_by_threshold,
    }
    return EnrichmentStageResult(
        name="frequency_enrichment",
        summary={
            "frequency_tags_by_word": tagged_words_by_threshold,
            "frequency_tags_by_form": tagged_forms_by_threshold,
        },
        report=report,
    )
