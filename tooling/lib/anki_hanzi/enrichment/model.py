"""Shared result model for lexicon enrichment stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class EnrichmentStageResult:
    """Summary and diagnostic report produced by one enrichment stage."""

    name: str
    summary: dict[str, Any]
    report: dict[str, Any]


def merge_stage_summaries(results: Iterable[EnrichmentStageResult]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for result in results:
        duplicate_keys = summary.keys() & result.summary.keys()
        if duplicate_keys:
            duplicates = ", ".join(sorted(duplicate_keys))
            raise ValueError(f"Duplicate enrichment summary keys from {result.name!r}: {duplicates}")
        summary.update(result.summary)
    return summary


def stage_reports_by_name(results: Iterable[EnrichmentStageResult]) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for result in results:
        if result.name in reports:
            raise ValueError(f"Duplicate enrichment stage name: {result.name!r}")
        reports[result.name] = result.report
    return reports
