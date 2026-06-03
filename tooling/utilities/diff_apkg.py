#!/usr/bin/env python

"""Compare two APKG files semantically and write a Markdown report."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FIELD_SEPARATOR = "\x1f"
DEFAULT_REPORT = Path("build_reports/apkg_diff.md")
VOLATILE_FIELDS = {"BuildID"}


@dataclass(frozen=True)
class NoteSnapshot:
    key: str
    model: str
    guid: str
    fields: dict[str, str]
    tags: tuple[str, ...]

    @property
    def label(self) -> str:
        simplified = self.fields.get("Simplified", "").strip()
        pinyin = self.fields.get("Pinyin", "").strip()
        note_id = self.fields.get("NoteID", "").strip()
        pieces = [self.model]
        if simplified:
            pieces.append(simplified)
        if pinyin:
            pieces.append(pinyin)
        if note_id and not simplified:
            pieces.append(note_id[:12])
        return " / ".join(pieces)


@dataclass(frozen=True)
class CardSnapshot:
    key: str
    note_key: str
    deck: str
    template: str


@dataclass(frozen=True)
class ModelSnapshot:
    name: str
    fields: tuple[str, ...]
    css: str
    templates: dict[str, dict[str, str]]


@dataclass(frozen=True)
class ApkgSnapshot:
    path: Path
    notes: dict[str, NoteSnapshot]
    cards: dict[str, CardSnapshot]
    models: dict[str, ModelSnapshot]
    decks: dict[str, dict[str, Any]]
    media: dict[str, str]
    duplicate_note_keys: tuple[str, ...]


def resolve_apkg_path(path: Path) -> Path:
    if path.is_file():
        return path
    if path.is_dir():
        candidates = sorted(path.glob("*.apkg"))
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise ValueError(f"No .apkg file found in {path}")
        raise ValueError(f"Multiple .apkg files found in {path}: {', '.join(str(p) for p in candidates)}")
    raise ValueError(f"APKG path does not exist: {path}")


def collection_member(names: list[str]) -> str:
    for candidate in ("collection.anki21", "collection.anki2"):
        if candidate in names:
            return candidate
    raise ValueError("APKG does not contain collection.anki2 or collection.anki21")


def read_json(value: str | bytes | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(value or "{}")


def model_name(model: dict[str, Any]) -> str:
    return str(model.get("name") or "<unnamed model>")


def load_models(raw_models: dict[str, Any]) -> tuple[dict[int, ModelSnapshot], dict[str, ModelSnapshot]]:
    by_id: dict[int, ModelSnapshot] = {}
    by_name: dict[str, ModelSnapshot] = {}
    for raw_id, model in raw_models.items():
        name = model_name(model)
        fields = tuple(str(field.get("name") or "") for field in model.get("flds", []))
        templates = {
            str(template.get("name") or f"template-{index}"): {
                "qfmt": str(template.get("qfmt") or ""),
                "afmt": str(template.get("afmt") or ""),
            }
            for index, template in enumerate(model.get("tmpls", []))
        }
        snapshot = ModelSnapshot(
            name=name,
            fields=fields,
            css=str(model.get("css") or ""),
            templates=templates,
        )
        by_id[int(raw_id)] = snapshot
        by_name[name] = snapshot
    return by_id, by_name


def load_decks(raw_decks: dict[str, Any]) -> tuple[dict[int, str], dict[str, dict[str, Any]]]:
    names_by_id: dict[int, str] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for raw_id, deck in raw_decks.items():
        name = str(deck.get("name") or f"<deck {raw_id}>")
        names_by_id[int(raw_id)] = name
        by_name[name] = {
            key: value
            for key, value in deck.items()
            if key not in {"id", "mod", "usn", "conf"}
        }
    return names_by_id, by_name


def split_fields(raw_fields: str, field_names: tuple[str, ...]) -> dict[str, str]:
    values = raw_fields.split(FIELD_SEPARATOR)
    fields: dict[str, str] = {}
    for index, name in enumerate(field_names):
        fields[name] = values[index] if index < len(values) else ""
    for index in range(len(field_names), len(values)):
        fields[f"<extra {index}>"] = values[index]
    return fields


def note_key(guid: str, fields: dict[str, str]) -> str:
    note_id = fields.get("NoteID", "").strip()
    if note_id:
        return f"noteid:{note_id}"
    return f"guid:{guid}"


def template_name(model: ModelSnapshot | None, ordinal: int) -> str:
    if model is None:
        return f"template-{ordinal}"
    names = list(model.templates)
    if 0 <= ordinal < len(names):
        return names[ordinal]
    return f"template-{ordinal}"


def load_collection(db_path: Path, apkg_path: Path, media_hashes: dict[str, str]) -> ApkgSnapshot:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        col = connection.execute("select models, decks from col").fetchone()
        models_by_id, models_by_name = load_models(read_json(col["models"]))
        deck_names_by_id, decks_by_name = load_decks(read_json(col["decks"]))

        notes: dict[str, NoteSnapshot] = {}
        note_row_key: dict[int, str] = {}
        duplicate_keys: list[str] = []
        for row in connection.execute("select id, guid, mid, flds, tags from notes order by id"):
            model = models_by_id.get(int(row["mid"]))
            field_names = model.fields if model else ()
            fields = split_fields(str(row["flds"] or ""), field_names)
            key = note_key(str(row["guid"] or ""), fields)
            if key in notes:
                duplicate_keys.append(key)
                key = f"{key}#duplicate-note-{row['id']}"
            note_row_key[int(row["id"])] = key
            notes[key] = NoteSnapshot(
                key=key,
                model=model.name if model else f"<model {row['mid']}>",
                guid=str(row["guid"] or ""),
                fields=fields,
                tags=tuple(sorted(str(row["tags"] or "").split())),
            )

        cards: dict[str, CardSnapshot] = {}
        query = "select id, nid, did, ord from cards order by id"
        for row in connection.execute(query):
            note = notes.get(note_row_key.get(int(row["nid"]), ""))
            note_key_value = note.key if note else f"<missing note {row['nid']}>"
            model = models_by_name.get(note.model) if note else None
            tmpl = template_name(model, int(row["ord"]))
            deck = deck_names_by_id.get(int(row["did"]), f"<deck {row['did']}>")
            key = f"{note_key_value}\0{tmpl}"
            cards[key] = CardSnapshot(
                key=key,
                note_key=note_key_value,
                deck=deck,
                template=tmpl,
            )

        return ApkgSnapshot(
            path=apkg_path,
            notes=notes,
            cards=cards,
            models=models_by_name,
            decks=decks_by_name,
            media=media_hashes,
            duplicate_note_keys=tuple(duplicate_keys),
        )
    finally:
        connection.close()


def load_media_hashes(apkg_zip: zipfile.ZipFile) -> dict[str, str]:
    try:
        media_manifest = read_json(apkg_zip.read("media"))
    except KeyError:
        return {}

    hashes: dict[str, str] = {}
    for member_name, filename in media_manifest.items():
        try:
            data = apkg_zip.read(str(member_name))
        except KeyError:
            hashes[str(filename)] = "<missing media member>"
            continue
        hashes[str(filename)] = hashlib.sha256(data).hexdigest()
    return hashes


def load_apkg(path: Path) -> ApkgSnapshot:
    apkg_path = resolve_apkg_path(path)
    with zipfile.ZipFile(apkg_path) as apkg_zip:
        member = collection_member(apkg_zip.namelist())
        media_hashes = load_media_hashes(apkg_zip)
        with tempfile.TemporaryDirectory(prefix="anki-hanzi-apkg-diff-") as tmpdir:
            db_path = Path(tmpdir) / member
            db_path.write_bytes(apkg_zip.read(member))
            return load_collection(db_path, apkg_path, media_hashes)


def changed_model_fields(old: ModelSnapshot, new: ModelSnapshot) -> list[str]:
    changes: list[str] = []
    if old.fields != new.fields:
        changes.append("fields")
    if old.css != new.css:
        changes.append("css")
    if set(old.templates) != set(new.templates):
        changes.append("templates")
    else:
        changed_templates = [
            name
            for name in old.templates
            if old.templates[name] != new.templates[name]
        ]
        if changed_templates:
            changes.append("template bodies: " + ", ".join(changed_templates))
    return changes


def changed_template_fields(old: dict[str, str], new: dict[str, str]) -> list[str]:
    changes: list[str] = []
    for field_name in ("qfmt", "afmt"):
        if old.get(field_name, "") != new.get(field_name, ""):
            changes.append(field_name)
    return changes


def normalized_text(value: str, strip_html: bool) -> str:
    value = html.unescape(value or "")
    if strip_html:
        value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def truncate_text(value: str, limit: int) -> str:
    if len(value) > limit:
        return value[: limit - 1] + "…"
    return value


def markdown_code(value: str) -> str:
    return "`" + value.replace("`", "\\`") + "`"


def common_prefix_length(old_text: str, new_text: str) -> int:
    limit = min(len(old_text), len(new_text))
    index = 0
    while index < limit and old_text[index] == new_text[index]:
        index += 1
    return index


def common_suffix_length(old_text: str, new_text: str, prefix_length: int) -> int:
    limit = min(len(old_text), len(new_text)) - prefix_length
    index = 0
    while (
        index < limit
        and old_text[len(old_text) - index - 1] == new_text[len(new_text) - index - 1]
    ):
        index += 1
    return index


def token_left_boundary(text: str, index: int) -> bool:
    return index <= 0 or text[index - 1].isspace()


def token_right_boundary(text: str, index: int) -> bool:
    return index >= len(text) or text[index].isspace()


def expand_to_token_boundaries(
    old_text: str,
    new_text: str,
    old_start: int,
    old_end: int,
    new_start: int,
    new_end: int,
) -> tuple[int, int, int, int]:
    while not (token_left_boundary(old_text, old_start) and token_left_boundary(new_text, new_start)):
        if old_start > 0 and not old_text[old_start - 1].isspace():
            old_start -= 1
        if new_start > 0 and not new_text[new_start - 1].isspace():
            new_start -= 1

    while not (token_right_boundary(old_text, old_end) and token_right_boundary(new_text, new_end)):
        if old_end < len(old_text) and not old_text[old_end].isspace():
            old_end += 1
        if new_end < len(new_text) and not new_text[new_end].isspace():
            new_end += 1

    return old_start, old_end, new_start, new_end


def compact_segment(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    head = max(1, limit // 2 - 2)
    tail = max(1, limit - head - 3)
    return f"{value[:head]}...{value[-tail:]}"


def left_context(value: str, end: int, limit: int) -> str:
    if end <= limit:
        return value[:end]
    return "… " + value[end - limit:end]


def right_context(value: str, start: int, limit: int) -> str:
    if len(value) - start <= limit:
        return value[start:]
    return value[start:start + limit] + " …"


def inline_text_diff(old_value: str, new_value: str, *, strip_html: bool, context_chars: int = 80) -> str:
    old_text = normalized_text(old_value, strip_html=strip_html)
    new_text = normalized_text(new_value, strip_html=strip_html)
    if old_text == new_text:
        return "<visible text unchanged>" if strip_html else "<text unchanged>"

    prefix_length = common_prefix_length(old_text, new_text)
    suffix_length = common_suffix_length(old_text, new_text, prefix_length)
    old_start = prefix_length
    new_start = prefix_length
    old_end = len(old_text) - suffix_length
    new_end = len(new_text) - suffix_length
    old_start, old_end, new_start, new_end = expand_to_token_boundaries(
        old_text,
        new_text,
        old_start,
        old_end,
        new_start,
        new_end,
    )

    pieces = [
        left_context(new_text, new_start, context_chars),
    ]
    old_segment = compact_segment(old_text[old_start:old_end], context_chars * 2)
    new_segment = compact_segment(new_text[new_start:new_end], context_chars * 2)
    if old_segment:
        pieces.append(f"[old: {old_segment}]")
    if new_segment:
        pieces.append(f"[new: {new_segment}]")
    pieces.append(right_context(new_text, new_end, context_chars))
    return re.sub(r"\s+", " ", "".join(pieces)).strip() or "<changed>"


def field_diff_summary(old_value: str, new_value: str, preview_limit: int) -> str:
    diff = truncate_text(inline_text_diff(old_value, new_value, strip_html=True), preview_limit)
    return markdown_code(diff)


def template_diff_summary(old_value: str, new_value: str, preview_limit: int) -> str:
    diff = truncate_text(inline_text_diff(old_value, new_value, strip_html=False, context_chars=120), preview_limit)
    return markdown_code(diff)


def note_field_changes(
    old: NoteSnapshot,
    new: NoteSnapshot,
    include_build_id: bool,
) -> list[str]:
    ignored = set() if include_build_id else VOLATILE_FIELDS
    changes: list[str] = []
    field_names = sorted((set(old.fields) | set(new.fields)) - ignored)
    for field_name in field_names:
        if old.fields.get(field_name, "") != new.fields.get(field_name, ""):
            changes.append(field_name)
    if old.model != new.model:
        changes.append("<notetype>")
    if old.tags != new.tags:
        changes.append("<tags>")
    return changes


def card_changes(old: CardSnapshot, new: CardSnapshot) -> list[str]:
    changes: list[str] = []
    if old.deck != new.deck:
        changes.append("deck")
    if old.template != new.template:
        changes.append("template")
    return changes


def sorted_keys(values: set[str]) -> list[str]:
    return sorted(values)


def section_limited(lines: list[str], title: str, rows: list[str], limit: int | None) -> None:
    lines.append(f"## {title}")
    lines.append("")
    if not rows:
        lines.append("_None._")
        lines.append("")
        return

    displayed_rows = rows if limit is None else rows[:limit]
    for row in displayed_rows:
        lines.append(row)
    if limit is not None and len(rows) > limit:
        lines.append(f"- ... {len(rows) - limit} more omitted by --limit")
    lines.append("")


def build_report(
    old: ApkgSnapshot,
    new: ApkgSnapshot,
    include_build_id: bool,
    limit: int | None,
    preview_limit: int,
) -> str:
    old_note_keys = set(old.notes)
    new_note_keys = set(new.notes)
    added_note_keys = sorted_keys(new_note_keys - old_note_keys)
    removed_note_keys = sorted_keys(old_note_keys - new_note_keys)
    common_note_keys = sorted_keys(old_note_keys & new_note_keys)
    changed_note_keys = [
        key for key in common_note_keys
        if note_field_changes(old.notes[key], new.notes[key], include_build_id)
    ]

    old_card_keys = set(old.cards)
    new_card_keys = set(new.cards)
    added_card_keys = sorted_keys(new_card_keys - old_card_keys)
    removed_card_keys = sorted_keys(old_card_keys - new_card_keys)
    changed_card_keys = [
        key for key in sorted_keys(old_card_keys & new_card_keys)
        if card_changes(old.cards[key], new.cards[key])
    ]

    old_model_names = set(old.models)
    new_model_names = set(new.models)
    added_models = sorted_keys(new_model_names - old_model_names)
    removed_models = sorted_keys(old_model_names - new_model_names)
    changed_models = [
        name for name in sorted_keys(old_model_names & new_model_names)
        if changed_model_fields(old.models[name], new.models[name])
    ]

    old_decks = set(old.decks)
    new_decks = set(new.decks)
    added_decks = sorted_keys(new_decks - old_decks)
    removed_decks = sorted_keys(old_decks - new_decks)

    old_media = set(old.media)
    new_media = set(new.media)
    added_media = sorted_keys(new_media - old_media)
    removed_media = sorted_keys(old_media - new_media)
    changed_media = [
        name for name in sorted_keys(old_media & new_media)
        if old.media[name] != new.media[name]
    ]

    lines: list[str] = [
        "# APKG Diff",
        "",
        f"- old: `{old.path}`",
        f"- new: `{new.path}`",
        f"- BuildID field compared: `{include_build_id}`",
        "",
        "## Summary",
        "",
        f"- notes: {len(old.notes)} -> {len(new.notes)}",
        f"- notes added: {len(added_note_keys)}",
        f"- notes removed: {len(removed_note_keys)}",
        f"- notes changed: {len(changed_note_keys)}",
        f"- cards: {len(old.cards)} -> {len(new.cards)}",
        f"- cards added: {len(added_card_keys)}",
        f"- cards removed: {len(removed_card_keys)}",
        f"- cards changed: {len(changed_card_keys)}",
        f"- notetypes added: {len(added_models)}",
        f"- notetypes removed: {len(removed_models)}",
        f"- notetypes changed: {len(changed_models)}",
        f"- decks added: {len(added_decks)}",
        f"- decks removed: {len(removed_decks)}",
        f"- media files added: {len(added_media)}",
        f"- media files removed: {len(removed_media)}",
        f"- media files changed: {len(changed_media)}",
        "",
    ]

    if old.duplicate_note_keys or new.duplicate_note_keys:
        lines.extend([
            "## Warnings",
            "",
            f"- duplicate old note keys: {len(old.duplicate_note_keys)}",
            f"- duplicate new note keys: {len(new.duplicate_note_keys)}",
            "",
        ])

    changed_model_rows: list[str] = []
    for name in changed_models:
        old_model = old.models[name]
        new_model = new.models[name]
        changed_model_rows.append(f"- `{name}`: {', '.join(changed_model_fields(old_model, new_model))}")
        if old_model.fields != new_model.fields:
            changed_model_rows.append(
                f"  - fields: old `{', '.join(old_model.fields)}` / new `{', '.join(new_model.fields)}`"
            )
        if old_model.css != new_model.css:
            changed_model_rows.append(
                f"  - css: {template_diff_summary(old_model.css, new_model.css, preview_limit)}"
            )

        removed_templates = sorted(set(old_model.templates) - set(new_model.templates))
        added_templates = sorted(set(new_model.templates) - set(old_model.templates))
        for template in removed_templates:
            changed_model_rows.append(f"  - old-only template: `{template}`")
        for template in added_templates:
            changed_model_rows.append(f"  - new-only template: `{template}`")
        for template in sorted(set(old_model.templates) & set(new_model.templates)):
            template_changes = changed_template_fields(old_model.templates[template], new_model.templates[template])
            if not template_changes:
                continue
            changed_model_rows.append(f"  - template `{template}`: {', '.join(template_changes)}")
            for field_name in template_changes:
                changed_model_rows.append(
                    f"    - {field_name}: "
                    f"{template_diff_summary(old_model.templates[template].get(field_name, ''), new_model.templates[template].get(field_name, ''), preview_limit)}"
                )
    section_limited(lines, "Changed Notetypes", changed_model_rows, limit)

    note_rows: list[str] = []
    for key in changed_note_keys:
        old_note = old.notes[key]
        new_note = new.notes[key]
        changes = note_field_changes(old_note, new_note, include_build_id)
        note_rows.append(f"- `{new_note.label}`: {', '.join(changes)}")
        for field in changes:
            if field == "<notetype>":
                note_rows.append(f"  - notetype: old `{old_note.model}` / new `{new_note.model}`")
            elif field == "<tags>":
                note_rows.append(f"  - tags: old `{', '.join(old_note.tags)}` / new `{', '.join(new_note.tags)}`")
            else:
                note_rows.append(
                    "  - "
                    f"{field}: {field_diff_summary(old_note.fields.get(field, ''), new_note.fields.get(field, ''), preview_limit)}"
                )
    section_limited(lines, "Changed Notes", note_rows, None if limit is None else max(limit * 8, limit))

    added_note_rows = [
        f"- `{new.notes[key].label}`"
        for key in added_note_keys
    ]
    removed_note_rows = [
        f"- `{old.notes[key].label}`"
        for key in removed_note_keys
    ]
    section_limited(lines, "Added Notes", added_note_rows, limit)
    section_limited(lines, "Removed Notes", removed_note_rows, limit)

    changed_card_rows = [
        f"- `{new.cards[key].note_key}` / `{new.cards[key].template}`: {', '.join(card_changes(old.cards[key], new.cards[key]))}"
        for key in changed_card_keys
    ]
    section_limited(lines, "Changed Cards", changed_card_rows, limit)

    added_card_rows = [
        f"- `{new.cards[key].note_key}` / `{new.cards[key].template}` / `{new.cards[key].deck}`"
        for key in added_card_keys
    ]
    removed_card_rows = [
        f"- `{old.cards[key].note_key}` / `{old.cards[key].template}` / `{old.cards[key].deck}`"
        for key in removed_card_keys
    ]
    section_limited(lines, "Added Cards", added_card_rows, limit)
    section_limited(lines, "Removed Cards", removed_card_rows, limit)

    section_limited(lines, "Added Decks", [f"- `{name}`" for name in added_decks], limit)
    section_limited(lines, "Removed Decks", [f"- `{name}`" for name in removed_decks], limit)
    section_limited(lines, "Added Media", [f"- `{name}`" for name in added_media], limit)
    section_limited(lines, "Removed Media", [f"- `{name}`" for name in removed_media], limit)
    section_limited(lines, "Changed Media", [f"- `{name}`" for name in changed_media], limit)

    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_apkg", type=Path, help="Old APKG file or directory containing exactly one APKG.")
    parser.add_argument("new_apkg", type=Path, help="New APKG file or directory containing exactly one APKG.")
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT, help=f"Markdown report path. Default: {DEFAULT_REPORT}")
    parser.add_argument("--include-build-id", action="store_true", help="Compare the BuildID field instead of ignoring it.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum rows per top-level section. Default: unlimited")
    parser.add_argument("--preview-limit", type=int, default=240, help="Maximum inline value preview length. Default: 240")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    old = load_apkg(args.old_apkg)
    new = load_apkg(args.new_apkg)
    report = build_report(
        old=old,
        new=new,
        include_build_id=args.include_build_id,
        limit=args.limit,
        preview_limit=args.preview_limit,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
