"""Base interfaces shared by migration step handlers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal


ReportStatus = Literal["ok", "warn", "error"]
ReportItem = dict[str, Any]


def report_item(status: ReportStatus, title: str, detail: str, details: list[str] | None = None) -> ReportItem:
    return {
        "status": status,
        "title": title,
        "detail": detail,
        "details": details or [],
    }


class MigrationStepHandler(ABC):
    key: str
    name: str
    description: str

    @abstractmethod
    def prepare_preflight(self, *, apkg_path: str, deck_root: str, target_preset_name: str) -> dict[str, Any]:
        """Return structured preflight data for this migration step."""

    @abstractmethod
    def apply(self, *, apkg_path: str, deck_root: str, target_preset_name: str) -> dict[str, Any]:
        """Apply this migration step and return structured result data."""

    @abstractmethod
    def preflight_items(self, report_json: dict[str, Any]) -> list[ReportItem]:
        """Render preflight JSON into UI summary items."""

    @abstractmethod
    def result_items(self, report_json: dict[str, Any] | None) -> list[ReportItem]:
        """Render result JSON into UI summary items."""
