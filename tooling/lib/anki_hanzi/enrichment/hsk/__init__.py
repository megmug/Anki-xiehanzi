"""HSK tag and form enrichment stage."""

from __future__ import annotations

from pathlib import Path

from anki_hanzi.enrichment.hsk.pipeline import (
    HskEnrichmentResult,
    apply_hsk_enrichment_to_state,
)
from anki_hanzi.enrichment.hsk.source import HANZI_DEDUPE_KEY


DEFAULT_DECK_INPUTS_DIR = Path("deck_inputs")
DEFAULT_HSK_DATA_DIR = DEFAULT_DECK_INPUTS_DIR / "hsk-3.0-words-list/New HSK (2025)/Anki xiehanzi"


__all__ = [
    "DEFAULT_DECK_INPUTS_DIR",
    "DEFAULT_HSK_DATA_DIR",
    "HANZI_DEDUPE_KEY",
    "HskEnrichmentResult",
    "apply_hsk_enrichment_to_state",
]
