#!/usr/bin/env python

"""
Enrich the compact CC-CEDICT master state with hanzi deck-source data.

This is a thin CLI wrapper around the library enrichment stage. The wrapper
keeps the existing JSON inputs and outputs stable while the internal pipeline
moves toward passing a consistent Python state between stages.

Run from the repository root inside the Nix shell:

    nix-shell --run "python tooling/build/enrich_hanzi_db.py"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from anki_hanzi.enrichment.hanzi import (
    DEFAULT_FREQUENCY_LIST,
    DEFAULT_HSK_DATA_DIR,
    DEFAULT_MASTER_DB,
    DEFAULT_OUTPUT,
    DEFAULT_REPORT,
    enrich_database,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master-db", type=Path, default=DEFAULT_MASTER_DB, help="Input compact CC-CEDICT master JSON.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output enriched JSON.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="Output enrichment report JSON.")
    parser.add_argument("--hsk-data-dir", type=Path, default=DEFAULT_HSK_DATA_DIR, help="Prepared hanzi HSK TSV directory.")
    parser.add_argument("--frequency-list", type=Path, default=DEFAULT_FREQUENCY_LIST, help="Simplified word frequency list sorted by usage.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.master_db.exists():
        print(f"missing master DB: {args.master_db}")
        return 2
    if not args.hsk_data_dir.exists():
        print(f"missing hanzi HSK data dir: {args.hsk_data_dir}")
        return 2
    if not args.frequency_list.exists():
        print(f"missing frequency list: {args.frequency_list}")
        return 2

    enriched, _report = enrich_database(
        master_db_path=args.master_db,
        output_path=args.output,
        report_path=args.report,
        hsk_data_dir=args.hsk_data_dir,
        frequency_list_path=args.frequency_list,
    )

    print("hanzi enrichment generated")
    print(f"input: {args.master_db}")
    print(f"output: {args.output}")
    print(f"report: {args.report}")
    print(json.dumps(enriched["summary"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
