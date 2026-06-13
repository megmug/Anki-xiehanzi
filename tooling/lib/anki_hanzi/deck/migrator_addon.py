"""Package the Anki Hanzi Migrator add-on."""

from __future__ import annotations

import json
import zipfile
from collections.abc import Sequence
from pathlib import Path


EXCLUDED_PARTS = {"__pycache__"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def _iter_addon_files(source_dir: Path) -> list[Path]:
    files = []
    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        files.append(path)
    return sorted(files)


def _write_zip_file(
    archive: zipfile.ZipFile,
    arcname: str,
    data: bytes,
    zip_datetime: tuple[int, int, int, int, int, int],
) -> None:
    info = zipfile.ZipInfo(arcname, zip_datetime)
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, data)


def build_migrator_addon(
    *,
    source_dir: Path,
    output_path: Path,
    build_id: str,
    known_build_ids: Sequence[str],
    zip_datetime: tuple[int, int, int, int, int, int],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    build_info = {
        "build_id": build_id,
        "known_build_ids": list(dict.fromkeys(known_build_ids)),
        "schema": "anki-hanzi-migrator-build-info-v1",
    }

    with zipfile.ZipFile(output_path, "w") as archive:
        for path in _iter_addon_files(source_dir):
            arcname = path.relative_to(source_dir).as_posix()
            _write_zip_file(archive, arcname, path.read_bytes(), zip_datetime)
        _write_zip_file(
            archive,
            "build_info.json",
            (json.dumps(build_info, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            zip_datetime,
        )
