"""BCT source loading."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from anki_hanzi.enrichment.bct.model import BctSourceEntry, BctSourceTerm


DEFAULT_DECK_INPUTS_DIR = Path("deck_inputs")
DEFAULT_BCT_DATA_DIR = DEFAULT_DECK_INPUTS_DIR / "hsk-3.0-words-list/BCT"
BCT_LEVEL_FILES = {
    "a": "BCTA_cihui.txt",
    "b": "BCTB_cihui.txt",
}
BCT_LEVELS = tuple(BCT_LEVEL_FILES)


def load_bct_entries(bct_data_dir: Path) -> list[BctSourceEntry]:
    entries: list[BctSourceEntry] = []
    for level, filename in BCT_LEVEL_FILES.items():
        path = bct_data_dir / filename
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 2 or not parts[1].strip():
                    continue
                entries.append(
                    BctSourceEntry(
                        level=level,
                        index=parts[0].strip(),
                        word=parts[1].strip(),
                        path=str(path),
                        line_number=line_number,
                    )
                )
    return entries


def group_bct_source_terms(entries: list[BctSourceEntry]) -> list[BctSourceTerm]:
    entries_by_word: dict[str, list[BctSourceEntry]] = defaultdict(list)
    for entry in entries:
        entries_by_word[entry.word].append(entry)
    return [
        BctSourceTerm(word=word, entries=tuple(records))
        for word, records in sorted(entries_by_word.items())
    ]


def duplicate_source_terms(source_terms: list[BctSourceTerm]) -> dict[str, list[dict[str, object]]]:
    return {
        term.word: [entry.to_report() for entry in term.entries]
        for term in source_terms
        if len({entry.level for entry in term.entries}) != len(term.entries)
    }
