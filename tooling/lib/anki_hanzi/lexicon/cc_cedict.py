"""CC-CEDICT parser for the internal lexicon state."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from anki_hanzi.lexicon.state import LexiconSource, LexiconState, LexiconWord, ParseSummary
from anki_hanzi.pinyin import normalize_single_pinyin


LINE_RE = re.compile(r"^\S+\s+(?P<simplified>\S+)\s+\[(?P<pinyin>.+?)\]\s+/(?P<definitions>.*)/$")
MISSING_IDEOGRAPH_PLACEHOLDERS = frozenset({"□"})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_pinyin(value: str) -> str:
    return normalize_single_pinyin(value)


def split_definitions(definitions_blob: str) -> list[str]:
    return [part.strip() for part in definitions_blob.split("/") if part.strip()]


def has_missing_ideograph_placeholder(value: str) -> bool:
    return any(char in MISSING_IDEOGRAPH_PLACEHOLDERS for char in value or "")


def parse_cedict_text(
    text: str,
    *,
    source_url: str,
    source_sha256: str,
    source_path: Path,
) -> LexiconState:
    comments: list[str] = []
    words: dict[str, LexiconWord] = {}
    parsed_entries = 0
    rejected_count = 0
    skipped_placeholder_count = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            comments.append(line)
            continue

        match = LINE_RE.match(line)
        if not match:
            rejected_count += 1
            continue

        simplified = match.group("simplified")
        if has_missing_ideograph_placeholder(simplified):
            skipped_placeholder_count += 1
            continue

        parsed_entries += 1
        word = words.get(simplified)
        if word is None:
            word = LexiconWord(simplified=simplified)
            words[simplified] = word

        word.add_entry(
            pinyin=parse_pinyin(match.group("pinyin")),
            definitions=split_definitions(match.group("definitions")),
        )

    return LexiconState(
        source=LexiconSource(
            name="CC-CEDICT",
            url=source_url,
            sha256=source_sha256,
            path=source_path,
            comment_header=tuple(comments),
        ),
        words=words,
        parse_summary=ParseSummary(
            source_entries=parsed_entries,
            comments=len(comments),
            rejected_lines=rejected_count,
            skipped_missing_ideograph_placeholder_entries=skipped_placeholder_count,
        ),
    )


def load_snapshot_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"missing snapshot manifest: {path}")

    manifest = json.loads(path.read_text(encoding="utf-8"))
    missing_fields = [field for field in ["source_filename", "sha256", "source_url"] if not manifest.get(field)]
    if missing_fields:
        raise ValueError(f"snapshot manifest is missing required fields: {', '.join(missing_fields)}")
    return manifest


def resolve_source_file(manifest_path: Path, manifest: dict[str, Any], override: Path | None) -> Path:
    if override is not None:
        return override
    return manifest_path.parent / manifest["source_filename"]


def load_cedict_state(source_file: Path, url: str, expected_sha256: str) -> LexiconState:
    actual_sha256 = sha256_file(source_file)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"CC-CEDICT source hash mismatch: expected {expected_sha256}, got {actual_sha256}. "
            "Update the pin intentionally if this is a new desired snapshot."
        )

    return parse_cedict_text(
        source_file.read_text(encoding="utf-8-sig"),
        source_url=url,
        source_sha256=actual_sha256,
        source_path=source_file,
    )
