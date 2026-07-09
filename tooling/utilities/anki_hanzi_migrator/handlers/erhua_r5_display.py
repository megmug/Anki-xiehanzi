"""Migration handler for the erhua `r5` display-to-suffix transition."""

from __future__ import annotations

import re

from .current_default import (
    CurrentDefaultMigration,
    index_by_loose_key,
    normalized_match_text,
    plain_text,
    unique_records,
)


def migrate_erhua_r5_display_reading(reading: str) -> str:
    reading = plain_text(reading)
    if normalized_match_text(reading) == "r5":
        return "r"
    return re.sub(r"(?i)(\S)\s+r5\b", r"\1r", reading)


def build_erhua_r5_display_keys(record: dict) -> list[str]:
    if record.get("kind") != "Meaning":
        return []

    fields = record.get("fields", {})
    simplified = normalized_match_text(fields.get("Simplified", ""))
    if not simplified:
        return []

    readings = [reading for reading in re.split(r"\s*/\s*", plain_text(fields.get("Pinyin", ""))) if reading]
    migrated_readings = [migrate_erhua_r5_display_reading(reading) for reading in readings]
    if [normalized_match_text(reading) for reading in migrated_readings] == [
        normalized_match_text(reading) for reading in readings
    ]:
        return []

    keys: list[str] = []
    for reading in migrated_readings:
        pinyin_key = normalized_match_text(reading)
        if pinyin_key:
            keys.append(f"Meaning::{simplified}::{pinyin_key}")

    full_pinyin_key = normalized_match_text(" / ".join(migrated_readings))
    if full_pinyin_key:
        keys.append(f"Meaning::{simplified}::{full_pinyin_key}")

    return list(dict.fromkeys(keys))


class ErhuaR5DisplayMigration(CurrentDefaultMigration):
    key = "erhua_r5_display"
    name = "Erhua r5 display migration"
    description = "Stateful migration for the Pinyin display change from separate r5 to attached erhua -r."

    def build_match_plan(self, source_by_key, target_by_key):
        plan = super().build_match_plan(source_by_key, target_by_key)
        matches_by_source_key = dict(plan["matches_by_source_key"])
        matched_target_keys = set(plan["matched_target_keys"])
        loose_target_index = index_by_loose_key(
            [record for key, record in target_by_key.items() if key not in matched_target_keys]
        )
        erhua_display_source_keys: list[str] = []

        for source_key in plan["unmatched_source_keys"]:
            source_record = source_by_key[source_key]
            erhua_display_keys = build_erhua_r5_display_keys(source_record)
            if not erhua_display_keys:
                continue

            candidates = unique_records(
                [
                    record
                    for erhua_display_key in erhua_display_keys
                    for record in loose_target_index.get(erhua_display_key, [])
                    if record.get("key") not in matched_target_keys
                ]
            )
            if len(candidates) != 1:
                continue

            target_key = candidates[0]["key"]
            matched_erhua_display_keys = [
                erhua_display_key
                for erhua_display_key in erhua_display_keys
                if candidates[0] in loose_target_index.get(erhua_display_key, [])
            ]
            matches_by_source_key[source_key] = {
                "source_key": source_key,
                "target_key": target_key,
                "match_type": "erhua_r5_display",
                "erhua_display_key": matched_erhua_display_keys[0]
                if matched_erhua_display_keys
                else erhua_display_keys[0],
                "erhua_display_keys": erhua_display_keys,
                "matched_erhua_display_keys": matched_erhua_display_keys,
            }
            matched_target_keys.add(target_key)
            erhua_display_source_keys.append(source_key)

        matched_source_keys = sorted(matches_by_source_key)
        return {
            **plan,
            "matches_by_source_key": matches_by_source_key,
            "matched_source_keys": matched_source_keys,
            "matched_target_keys": sorted(matched_target_keys),
            "erhua_r5_display_source_keys": sorted(erhua_display_source_keys),
            "unmatched_source_keys": sorted(set(source_by_key) - set(matches_by_source_key)),
            "target_only_keys": sorted(set(target_by_key) - matched_target_keys),
        }
