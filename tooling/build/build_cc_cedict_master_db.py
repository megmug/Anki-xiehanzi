#!/usr/bin/env python3
"""
Build a pinned CC-CEDICT master JSON database.

This is a thin CLI wrapper around the library lexicon importer:

    pinned CC-CEDICT text file -> LexiconState -> master JSON

The JSON output is intentionally kept stable while the internal build pipeline
moves toward passing a consistent Python state between stages.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from anki_hanzi.lexicon.cc_cedict import load_cedict_state, load_snapshot_manifest, resolve_source_file


DEFAULT_SNAPSHOT_MANIFEST = Path("deck_inputs/cc-cedict/snapshot.json")
DEFAULT_OUTPUT = Path("master_db_output/cc_cedict_master.json")


def build_database(source_file: Path, url: str, expected_sha256: str, output_path: Path) -> dict[str, Any]:
    state = load_cedict_state(
        source_file=source_file,
        url=url,
        expected_sha256=expected_sha256,
    )
    database = state.to_master_json()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(database, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot-manifest",
        type=Path,
        default=DEFAULT_SNAPSHOT_MANIFEST,
        help="Snapshot manifest with the pinned source filename, SHA256, and source URL.",
    )
    parser.add_argument("--source-file", type=Path, default=None, help="Optional pinned CC-CEDICT text file override.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output master JSON path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = load_snapshot_manifest(args.snapshot_manifest)
    except (FileNotFoundError, ValueError) as error:
        print(error, file=sys.stderr)
        return 2

    source_file = resolve_source_file(args.snapshot_manifest, manifest, args.source_file)
    if not source_file.exists():
        print(f"missing source file: {source_file}", file=sys.stderr)
        return 2

    database = build_database(
        source_file=source_file,
        url=manifest["source_url"],
        expected_sha256=manifest["sha256"],
        output_path=args.output,
    )
    print("CC-CEDICT master JSON generated")
    print(f"source file: {source_file}")
    print(f"output: {args.output}")
    print(json.dumps(database["summary"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
