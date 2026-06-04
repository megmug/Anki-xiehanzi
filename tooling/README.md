# Tooling

This directory contains the Python build pipeline, project utilities, and shared helper code.

Run the full build with:

```sh
nix-build
```

## Build

`default.nix` invokes one build entry point during the normal APKG build.

- `build/generate_hanzi_deck.py`: build the typed lexicon state, write diagnostic JSON artifacts, and generate the APKG.
  The build also writes `master_db_output/hanzi_matching_report.json`, a report-only xiehanzi-to-CC-CEDICT candidate matching report.

## Utilities

These programs are run manually for maintenance, analysis, or upgrades.

- `utilities/diff_apkg.py`: compare two APKG files semantically and write a Markdown diff report.
- `utilities/migrate-*.py`: stateful Anki Debug Console migration scripts.
  A filename `migrate-<old-hash>.py` migrates from that old build hash to the target APKG it is released with.
- `utilities/update_cc_cedict_snapshot.py`: refresh the pinned CC-CEDICT snapshot when an intentional source-data update is needed.

## Formatting

Run `nix-shell --run "treefmt"` to format maintained Python and Nix code.
Treefmt uses Ruff for Python and nixfmt for Nix.
Generated migration scripts and vendored deck inputs are excluded.

## Library

These modules are imported by build programs and are not direct entry points.

- `lib/anki_hanzi/deck/build.py`: typed lexicon-to-APKG build orchestration.
- `lib/anki_hanzi/deck/common.py`: shared template, media, model, config, and stable-id helpers.
- `lib/anki_hanzi/enrichment/`: hanzi HSK, xiehanzi, and frequency enrichment stages.
  This includes the report-only matching scaffold used to inspect candidate evidence before changing enrichment rules.
- `lib/anki_hanzi/lexicon/`: internal lexicon state and CC-CEDICT source parser.
- `lib/anki_hanzi/rendering/meaning_html.py`: render hanzi-style Meaning HTML from structured word and form data.
- `lib/anki_hanzi/audio/`: provider-neutral audio generation plus Kokoro and edge-tts backends.
