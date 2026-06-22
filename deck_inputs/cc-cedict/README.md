# CC-CEDICT Snapshot

This directory contains the pinned CC-CEDICT source snapshot used by the local
deck build.

The upstream MDBG export URL is mutable, so the build vendors the exact
CC-CEDICT text file needed for reproducible APKG generation instead of
downloading the latest file during `nix-build`.

To update the snapshot from the latest upstream export, run:

```sh
nix-shell --run "python tooling/utilities/update_cc_cedict_snapshot.py"
```

The update command downloads the current archive from the URL below, validates
it, extracts `cedict_ts.u8`, and rewrites this directory. Then rebuild
and commit the changed snapshot, manifest, and reports if the new data is
intentional.

- Source URL: `https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.zip`
- Snapshot date from file header: `2026-06-22T04:29:46Z`
- Entries from file header: `125052`
- Publisher from file header: `MDBG`
- Snapshot file: `cedict_ts.u8`
- Snapshot SHA256: `f477e6f22d097b134ec01878f738e3c536c3324535edf2f089af03b4fc0354dc`
- License: https://creativecommons.org/licenses/by-sa/4.0/
