"""Card template loading and injection helpers."""

from __future__ import annotations

import json
from pathlib import Path

from anki_hanzi.deck import common
from anki_hanzi.deck.config import DeckConfig


HANZI_WRITER_BUNDLE_MARKER = "/*! Hanzi Writer v"
HANZI_WRITER_DATA_BUNDLE_MARKER = "<!-- __HANZI_WRITER_DATA_BUNDLE__ -->"


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def read_hanzi_writer_package_version() -> str:
    package_data = json.loads(common.HANZI_WRITER_PACKAGE_JSON.read_text(encoding="utf-8"))
    return str(package_data["version"])


def read_hanzi_writer_bundle() -> str:
    version = read_hanzi_writer_package_version()
    bundle = common.HANZI_WRITER_BUNDLE.read_text(encoding="utf-8").strip()
    return "\n".join(
        [
            f"/*! Hanzi Writer v{version} injected from npm package */",
            bundle,
        ]
    )


def replace_unique_template_marker(template: str, marker: str, replacement: str, label: str) -> str:
    marker_count = template.count(marker)
    if marker_count != 1:
        raise ValueError(f"Expected exactly one {label} marker, found {marker_count}")
    return template.replace(marker, replacement, 1)


def remove_optional_template_marker(template: str, marker: str, label: str) -> str:
    marker_count = template.count(marker)
    if marker_count > 1:
        raise ValueError(f"Expected at most one {label} marker, found {marker_count}")
    return template.replace(marker, "", 1)


def inject_hanzi_writer_bundle(template: str) -> str:
    start_marker = f"    {HANZI_WRITER_BUNDLE_MARKER}"
    script_start = template.find(start_marker)
    if script_start < 0:
        raise ValueError("Could not find embedded Hanzi Writer bundle start marker")

    script_end_marker = "\n</script>"
    script_end = template.find(script_end_marker, script_start)
    if script_end < 0:
        raise ValueError("Could not find embedded Hanzi Writer bundle end marker")

    injected_bundle = read_hanzi_writer_bundle()
    indented_bundle = "\n".join(f"    {line}" if line else "" for line in injected_bundle.splitlines())
    return template[:script_start] + indented_bundle + template[script_end:]


def inject_hanzi_data_bundle(template: str, bundle_path: Path) -> str:
    """Inject hanzi-writer-data JS bundle directly into the template as inline script."""
    if not bundle_path.exists():
        return remove_optional_template_marker(
            template,
            HANZI_WRITER_DATA_BUNDLE_MARKER,
            "hanzi-writer-data bundle",
        )

    bundle = bundle_path.read_text(encoding="utf-8")
    inline_script = f"<script>\n{bundle}\n</script>\n"
    return replace_unique_template_marker(
        template,
        HANZI_WRITER_DATA_BUNDLE_MARKER,
        inline_script,
        "hanzi-writer-data bundle",
    )


def inject_card_settings(template: str, card_type: str, config: DeckConfig) -> str:
    return template.replace("__HANZI_CARD_SETTINGS__", config.card_settings_json(card_type))


def read_template(
    card_type: str,
    path: str | Path,
    config: DeckConfig,
    hw_data_bundle: Path | None = None,
) -> str:
    template = read_text(path)
    template = inject_card_settings(template, card_type, config)
    if card_type == "Write" and HANZI_WRITER_BUNDLE_MARKER in template:
        template = inject_hanzi_writer_bundle(template)
        if hw_data_bundle:
            template = inject_hanzi_data_bundle(template, hw_data_bundle)
        else:
            template = remove_optional_template_marker(
                template,
                HANZI_WRITER_DATA_BUNDLE_MARKER,
                "hanzi-writer-data bundle",
            )
    return template
