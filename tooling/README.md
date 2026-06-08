# Tooling

This directory contains the Python build pipeline, project utilities, and shared helper code.

Run the full build with:

```sh
nix-build
```

## Build

`default.nix` invokes one build entry point during the normal APKG build.

- `build/generate_hanzi_deck.py`: build the typed lexicon state and generate the APKG.
  The build writes one stage-oriented `build_reports/build_report.json` with source, enrichment, matching, selection,
  audio, HanziWriter, and package summaries.
  Full diagnostic lexicon JSON dumps are off by default; pass `--master-db-output` and/or `--enriched-db-output`
  when running the CLI directly, or build with `nix-build --arg writeDiagnosticDatabases true` to include them under
  `result/diagnostics/`.

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
- `lib/anki_hanzi/deck/common.py`: shared paths and genanki deck assembly helpers.
- `lib/anki_hanzi/deck/config.py`: deck configuration data structures and parser.
- `lib/anki_hanzi/deck/entries.py`: enriched lexicon state to card-entry selection.
- `lib/anki_hanzi/deck/identity.py`: stable deck, note, model, and tag identity helpers.
- `lib/anki_hanzi/deck/reports.py`: build report assembly.
- `lib/anki_hanzi/deck/templates.py`: card template loading and marker injection.
- `lib/anki_hanzi/enrichment/`: hanzi HSK, xiehanzi, and frequency enrichment stages.
  Xiehanzi enrichment is resolved through explicit matching buckets and consumption rules; the build aborts if the
  terminal unresolved bucket is not empty.
- `lib/anki_hanzi/json_io.py`: stable JSON formatting and file output helpers.
- `lib/anki_hanzi/lexicon/`: internal lexicon state and CC-CEDICT source parser.
- `lib/anki_hanzi/rendering/meaning_html.py`: render hanzi-style Meaning HTML from structured word and form data.
- `lib/anki_hanzi/audio/`: provider-neutral audio generation plus Kokoro and edge-tts backends.
