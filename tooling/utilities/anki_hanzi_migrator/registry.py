"""Known migration checkpoints and strategies."""

from __future__ import annotations

import json
from pathlib import Path

from .handlers import CurrentDefaultMigration
from .routing import DefaultStrategy, MigrationRoute, SpecialTransition, plan_route


BUILD_INFO_PATH = Path(__file__).resolve().parent / "build_info.json"

CURRENT_DEFAULT = CurrentDefaultMigration()

DEFAULT_STRATEGIES = (
    DefaultStrategy(
        name=CURRENT_DEFAULT.name,
        description=CURRENT_DEFAULT.description,
        valid_from=None,
        valid_until=None,
        handler=CURRENT_DEFAULT,
    ),
)

SPECIAL_TRANSITIONS: tuple[SpecialTransition, ...] = ()


def _build_info() -> dict:
    if not BUILD_INFO_PATH.exists():
        return {}
    try:
        return json.loads(BUILD_INFO_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def known_build_ids() -> tuple[str, ...]:
    build_info = _build_info()
    raw_build_ids = build_info.get("known_build_ids")
    if isinstance(raw_build_ids, list):
        build_ids = [build_id for build_id in raw_build_ids if isinstance(build_id, str) and build_id]
        if build_ids:
            return tuple(dict.fromkeys(build_ids))

    current_build_id = build_info.get("build_id")
    if isinstance(current_build_id, str) and current_build_id:
        return (current_build_id,)
    return ()


def plan_migration_route(source_build: str, target_build: str):
    known_builds = known_build_ids()
    if not known_builds:
        return MigrationRoute(
            source_build=source_build,
            target_build=target_build,
            target_is_unknown_future=True,
            latest_known_build="<unknown>",
            steps=(),
            problems=("Migrator package does not contain known build IDs.",),
        )
    return plan_route(
        source_build=source_build,
        target_build=target_build,
        known_builds=known_builds,
        default_strategies=DEFAULT_STRATEGIES,
        special_transitions=SPECIAL_TRANSITIONS,
    )
