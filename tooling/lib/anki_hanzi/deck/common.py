"""Shared helpers for building the custom hanzi APKG."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import genanki

if TYPE_CHECKING:
    from anki_hanzi.deck.config import DeckConfig


DECK_ROOT = "汉字 (Hànzì)"
OUTPUT_APKG = Path("anki-hanzi.apkg")
DECK_INPUTS_DIR = Path("deck_inputs")
CARD_TEMPLATES_DIR = DECK_INPUTS_DIR / "card_templates"
EXTRA_AUDIO_DIR = DECK_INPUTS_DIR / "extra_audio"
HANZI_WRITER_PACKAGE_JSON = Path("node_modules/hanzi-writer/package.json")
HANZI_WRITER_BUNDLE = Path("node_modules/hanzi-writer/dist/hanzi-writer.min.js")
HANZI_WRITER_DATA_DIR = Path("node_modules/hanzi-writer-data")
HANZI_WRITER_BUNDLE_MARKER = "/*! Hanzi Writer v"
HANZI_WRITER_DATA_BUNDLE_MARKER = "<!-- __HANZI_WRITER_DATA_BUNDLE__ -->"

LEVELS = ["1", "2", "3", "4", "5", "6", "7-9"]
CARD_TYPES = ["Meaning", "Pinyin", "Write"]

FIELDS = [
    {"name": "Simplified"},
    {"name": "Pinyin"},
    {"name": "Meaning"},
    {"name": "Audio"},
    {"name": "NoteID"},
    {"name": "BuildID"},
]

DEFAULT_CONFIG_PATH = DECK_INPUTS_DIR / "deck_config.json"
TAG_NAMESPACE = "hanzi"


class NoteEntry(Protocol):
    def fields(self, card_type: str, build_id: str) -> list[str]: ...

    @property
    def tags(self) -> tuple[str, ...]: ...


def stable_id(label: str) -> int:
    digest = hashlib.sha256(label.encode("utf-8")).digest()
    return (int.from_bytes(digest[:4], "big") % (1 << 30)) + (1 << 30)


def stable_hex_id(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def normalized_note_pinyin(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def note_pinyin_id_key(card_type: str, pinyin: str) -> str:
    if card_type == "Meaning":
        return str(pinyin or "").strip()
    return normalized_note_pinyin(pinyin)


def stable_note_id(card_type: str, simplified: str, pinyin: str) -> str:
    return stable_hex_id(f"{card_type}\0{str(simplified or '').strip()}\0{note_pinyin_id_key(card_type, pinyin)}")


def stable_note_guid(note_id: str) -> str:
    return genanki.guid_for(str(note_id or "").strip())


def anki_tag_name(tag: str) -> str:
    tag = tag.strip()
    if not tag:
        return ""
    if tag.casefold().startswith(f"{TAG_NAMESPACE}::"):
        return TAG_NAMESPACE + tag[len(TAG_NAMESPACE) :]
    if ":" in tag:
        return f"{TAG_NAMESPACE}::" + "::".join(part for part in tag.split(":") if part)
    return f"{TAG_NAMESPACE}::{tag}"


def anki_tag_names(tags: tuple[str, ...]) -> list[str]:
    return sorted({formatted for tag in tags if (formatted := anki_tag_name(tag))})


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def read_hanzi_writer_package_version() -> str:
    package_data = json.loads(HANZI_WRITER_PACKAGE_JSON.read_text(encoding="utf-8"))
    return str(package_data["version"])


def read_hanzi_writer_bundle() -> str:
    version = read_hanzi_writer_package_version()
    bundle = HANZI_WRITER_BUNDLE.read_text(encoding="utf-8").strip()
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


def create_models(config: DeckConfig | None = None, hw_data_bundle: Path | None = None) -> dict[str, genanki.Model]:
    if config is None:
        from anki_hanzi.deck.config import DeckConfig

        config = DeckConfig()
    css = read_text(CARD_TEMPLATES_DIR / "styling-hanzi-3.0.css")
    models: dict[str, genanki.Model] = {}

    for card_type in config.card_types:
        front_path, back_path = config.template_files(card_type)
        model_name = f"{DECK_ROOT}::{card_type}"
        models[card_type] = genanki.Model(
            model_id=stable_id(f"model:{model_name}"),
            name=model_name,
            fields=FIELDS,
            templates=[
                {
                    "name": f"Card 1 - {card_type}",
                    "qfmt": read_template(card_type, front_path, config, hw_data_bundle),
                    "afmt": read_template(card_type, back_path, config),
                }
            ],
            css=css,
        )

    return models


def create_deck(
    deck_name: str,
    card_type: str,
    model: genanki.Model,
    entries: list[NoteEntry],
    build_id: str,
) -> genanki.Deck:
    deck = genanki.Deck(stable_id(f"deck:{deck_name}"), deck_name)
    for entry in entries:
        fields = entry.fields(card_type, build_id)
        note_id = fields[-2]
        deck.add_note(
            genanki.Note(
                model=model,
                fields=fields,
                tags=anki_tag_names(entry.tags),
                guid=stable_note_guid(note_id),
            )
        )
    return deck


def remove_failed_audio_output(path: Path) -> None:
    if path.exists() and path.stat().st_size == 0:
        path.unlink()
