"""genanki model construction for the hanzi deck."""

from __future__ import annotations

from pathlib import Path

import genanki

from anki_hanzi.deck import common
from anki_hanzi.deck.config import DeckConfig
from anki_hanzi.deck.templates import read_template, read_text


FIELDS = [
    {"name": "Simplified"},
    {"name": "Pinyin"},
    {"name": "Meaning"},
    {"name": "Audio"},
    {"name": "NoteID"},
    {"name": "BuildID"},
]


def create_models(config: DeckConfig | None = None, hw_data_bundle: Path | None = None) -> dict[str, genanki.Model]:
    if config is None:
        config = DeckConfig()
    css = read_text(common.CARD_TEMPLATES_DIR / "styling-hanzi-3.0.css")
    models: dict[str, genanki.Model] = {}

    for card_type in config.card_types:
        front_path, back_path = config.template_files(card_type)
        model_name = f"{common.DECK_ROOT}::{card_type}"
        models[card_type] = genanki.Model(
            model_id=common.stable_id(f"model:{model_name}"),
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
