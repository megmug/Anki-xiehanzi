"""Stable JSON formatting helpers used by build and utility scripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_text(data), encoding="utf-8")
