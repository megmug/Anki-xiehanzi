"""Generate genanki model specs from hanzi card template resources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import genanki

from anki_hanzi.deck import common
from anki_hanzi.deck.config import DeckConfig
from anki_hanzi.deck.identity import stable_id
from anki_hanzi.deck.templates import (
    HANZI_WRITER_DATA_BUNDLE_MARKER,
    inject_card_settings,
    read_text,
    render_template_text,
    replace_unique_template_marker,
)


@dataclass(frozen=True)
class FieldSpec:
    name: str

    def to_genanki_field(self) -> dict[str, str]:
        return {"name": self.name}


@dataclass(frozen=True)
class CardTemplateSpec:
    name: str
    qfmt: str
    afmt: str

    def to_genanki_template(self) -> dict[str, str]:
        return {
            "name": self.name,
            "qfmt": self.qfmt,
            "afmt": self.afmt,
        }


@dataclass(frozen=True)
class ModelSpec:
    card_type: str
    name: str
    fields: tuple[FieldSpec, ...]
    templates: tuple[CardTemplateSpec, ...]
    css: str

    def to_genanki_model(self) -> genanki.Model:
        return genanki.Model(
            model_id=stable_id(f"model:{self.name}"),
            name=self.name,
            fields=[field.to_genanki_field() for field in self.fields],
            templates=[template.to_genanki_template() for template in self.templates],
            css=self.css,
        )


FIELD_SPECS = (
    FieldSpec("Simplified"),
    FieldSpec("Pinyin"),
    FieldSpec("Meaning"),
    FieldSpec("Audio"),
    FieldSpec("NoteID"),
    FieldSpec("BuildID"),
)

MORE_INFO_SIDEBAR_MARKER = "<!-- __MORE_INFO_SIDEBAR__ -->"
WRITE_FRONT_TEMPLATE_RESOURCE_PATH = "write/front.html"
WRITE_HANZI_WRITER_LOADER_RESOURCE_PATH = "write/fragments/hanzi_writer_loader.js"
WRITE_RUNTIME_TEMPLATE_RESOURCE_PATH = "write/fragments/runtime.js"
WRITE_FRONT_FRAGMENT_SPECS = (
    (
        "<!-- __WRITE_PERSISTENCE_SCRIPT__ -->",
        "write/fragments/persistence.js",
        "write persistence script",
    ),
    (
        "<!-- __WRITE_SETTINGS_SCRIPT__ -->",
        "write/fragments/settings.js",
        "write settings script",
    ),
    (
        "<!-- __WRITE_HANZI_WRITER_LOADER__ -->",
        WRITE_HANZI_WRITER_LOADER_RESOURCE_PATH,
        "write hanzi-writer loader",
    ),
    (
        "<!-- __WRITE_PINYIN_WRAPPER_SCRIPT__ -->",
        "write/fragments/pinyin_wrapper.js",
        "write pinyin wrapper script",
    ),
    (
        "<!-- __WRITE_RUNTIME_SCRIPT__ -->",
        WRITE_RUNTIME_TEMPLATE_RESOURCE_PATH,
        "write runtime script",
    ),
)
WRITE_RUNTIME_FRAGMENT_SPECS = (
    (
        "  /* __WRITE_RUNTIME_SIZING__ */",
        "write/fragments/runtime/sizing.js",
        "write runtime sizing",
    ),
    (
        "  /* __WRITE_RUNTIME_TONE_COLORS__ */",
        "write/fragments/runtime/tone_colors.js",
        "write runtime tone colors",
    ),
    (
        "  /* __WRITE_RUNTIME_AUDIO_BUTTON__ */",
        "write/fragments/runtime/audio_button.js",
        "write runtime audio button",
    ),
    (
        "  /* __WRITE_RUNTIME_GRID_RENDERING__ */",
        "write/fragments/runtime/grid_rendering.js",
        "write runtime grid rendering",
    ),
    (
        "  /* __WRITE_RUNTIME_SCORE_TRACKING__ */",
        "write/fragments/runtime/score_tracking.js",
        "write runtime score tracking",
    ),
    (
        "  /* __WRITE_RUNTIME_PRACTICE_FLOW__ */",
        "write/fragments/runtime/practice_flow.js",
        "write runtime practice flow",
    ),
)
SHARED_JS_FRAGMENT_SPECS = (
    (
        "  /* __SHARED_AUDIO__ */",
        "scripts/audio.js",
        "shared audio helpers",
    ),
    (
        "  /* __SHARED_AUDIO_BUTTON__ */",
        "scripts/audio_button.js",
        "shared audio button helper",
    ),
    (
        "  /* __SHARED_VISIBILITY__ */",
        "scripts/visibility.js",
        "shared visibility helper",
    ),
    (
        "  /* __SHARED_SIDEBAR__ */",
        "scripts/sidebar.js",
        "shared sidebar helpers",
    ),
)

STATIC_MEDIA_RESOURCE_PATHS = (
    "fonts/_MaterialSymbolsOutlined.woff2",
    "files/_pleco.png",
    "files/_youdao.png",
    "files/_rtega.png",
    "files/_tatoeba.png",
    "files/_hanzicraft.png",
    "files/_characterpop.svg",
)


def render_meaning_front_template(config: DeckConfig) -> str:
    return inject_card_settings(
        """<div class="header">
  Name one <span class="question-sub-text">meaning</span>.
</div>

<br />

<div id="char_pinyin">{{Pinyin}}</div>
<div id="char_sim" class="char-card">{{Simplified}}</div>

<script>
  window.HANZI_CARD_SETTINGS = __HANZI_CARD_SETTINGS__;

  (function () {
    var settings =
      (window.HANZI_CARD_SETTINGS && window.HANZI_CARD_SETTINGS.front) || {};

    function showHide(selector, isShow, style) {
      document.querySelectorAll(selector).forEach(function (element) {
        element.style.display = isShow ? style || "inline" : "none";
      });
    }

    showHide("#char_pinyin", settings.show_pinyin);
    showHide("#char_meaning", settings.show_meaning, "block");
    showHide("#char_sim", settings.show_simplified, "block");
    showHide(".pinyin", settings.show_pinyin);
    showHide("#char-sim-id", settings.show_simplified);
  })();
</script>
""",
        "Meaning",
        config,
    )


def render_pinyin_front_template(config: DeckConfig) -> str:
    return inject_card_settings(
        """<div class="header">
  Name a valid <span class="question-sub-text">pinyin reading</span>.
</div>

<br />

<div id="char_sim" class="char-card">{{Simplified}}</div>

<script>
  window.HANZI_CARD_SETTINGS = __HANZI_CARD_SETTINGS__;

  (function () {
    var frontSettings =
      (window.HANZI_CARD_SETTINGS && window.HANZI_CARD_SETTINGS.front) || {};

    function showHide(selector, isShow, style) {
      document.querySelectorAll(selector).forEach(function (element) {
        element.style.display = isShow ? style || "inline" : "none";
      });
    }

    showHide("#char_sim", frontSettings.show_simplified, "block");
    showHide(".pinyin", false);
  })();
</script>
""",
        "Pinyin",
        config,
    )


def render_more_info_sidebar() -> str:
    return """<div id="more-info-sidebar" class="more-info-sidebar">
  <a class="fieldset-item tappable">
    <div class="more-side-brand">
      <div class="brand-title">汉字</div>
      <div class="brand-sub-title">anki-hanzi {{BuildID}}</div>
    </div>
    <div
      onclick="closeSidebar('more-info-sidebar')"
      class="close-button close2"
    >
      ✖
    </div>
  </a>
  <a
    class="fieldset-item tappable"
    id="plecoMobile"
    href="plecoapi://x-callback-url/df?hw={{Simplified}}"
  >
    <img src="_pleco.png" />
    <small>Pleco</small>
  </a>
  <a
    class="fieldset-item tappable"
    href="http://dict.youdao.com/search?q={{Simplified}}"
  >
    <img src="_youdao.png" />
    <small>Youdao</small>
  </a>
  <a
    class="fieldset-item tappable"
    href="https://hanzicraft.com/character/{{Simplified}}"
  >
    <img src="_hanzicraft.png" />
    <small>HanziCraft</small>
  </a>
  <a
    class="fieldset-item tappable"
    href="https://characterpop.com/characters/{{Simplified}}"
  >
    <img src="_characterpop.svg" />
    <small>CharacterPop</small>
  </a>
  <a
    class="fieldset-item tappable"
    href="http://rtega.be/chmn/index.php?c={{Simplified}}"
  >
    <img src="_rtega.png" />
    <small>Rtega</small>
  </a>
  <a
    class="fieldset-item tappable"
    href="https://tatoeba.org/en/sentences/search?from=cmn&query={{Simplified}}&to="
  >
    <img src="_tatoeba.png" />
    <small>Tatoeba</small>
  </a>
</div>
<!-----sidebar------>
"""


def render_script_tag(source: str) -> str:
    if source.endswith("\n"):
        return f"<script>\n{source}</script>"
    return f"<script>\n{source}\n</script>"


def render_shared_js_markers(resource_dir: Path, source: str) -> str:
    for marker, fragment_path, label in SHARED_JS_FRAGMENT_SPECS:
        if marker in source:
            fragment = read_text(resource_dir / fragment_path).removesuffix("\n")
            source = replace_unique_template_marker(source, marker, fragment, label)
    return source


def render_js_resource(resource_dir: Path, resource_path: str) -> str:
    return render_shared_js_markers(resource_dir, read_text(resource_dir / resource_path))


def render_fragmented_resource(
    resource_dir: Path,
    template_path: str,
    fragment_specs: tuple[tuple[str, str, str], ...],
) -> str:
    template = read_text(resource_dir / template_path)
    for marker, fragment_path, label in fragment_specs:
        fragment = render_js_resource(resource_dir, fragment_path).removesuffix("\n")
        template = replace_unique_template_marker(template, marker, fragment, label)
    return template


def render_write_runtime_template(resource_dir: Path) -> str:
    return render_script_tag(
        render_fragmented_resource(
            resource_dir,
            WRITE_RUNTIME_TEMPLATE_RESOURCE_PATH,
            WRITE_RUNTIME_FRAGMENT_SPECS,
        ),
    )


def render_hanzi_writer_loader(resource_dir: Path) -> str:
    return "\n".join(
        [
            render_script_tag(read_text(resource_dir / WRITE_HANZI_WRITER_LOADER_RESOURCE_PATH)),
            HANZI_WRITER_DATA_BUNDLE_MARKER,
        ],
    )


def render_write_front_fragment(resource_dir: Path, fragment_path: str) -> str:
    if fragment_path == WRITE_RUNTIME_TEMPLATE_RESOURCE_PATH:
        return render_write_runtime_template(resource_dir)
    if fragment_path == WRITE_HANZI_WRITER_LOADER_RESOURCE_PATH:
        return render_hanzi_writer_loader(resource_dir)
    return render_script_tag(render_js_resource(resource_dir, fragment_path))


def render_write_front_template(resource_dir: Path) -> str:
    template = read_text(resource_dir / WRITE_FRONT_TEMPLATE_RESOURCE_PATH)
    for marker, fragment_path, label in WRITE_FRONT_FRAGMENT_SPECS:
        fragment = render_write_front_fragment(resource_dir, fragment_path).removesuffix("\n")
        template = replace_unique_template_marker(template, marker, fragment, label)
    return template


def render_basic_back_template(card_type: str, config: DeckConfig) -> str:
    template = (
        """<div id="char_pinyin">{{Pinyin}}</div>
<div id="char_sim" class="char-card">{{Simplified}}</div>
<div id="audio" style="display: none">{{Audio}}</div>

<div class="modal-footer1">
  <a class="btn" id="btnPlayAudio">
    <div class="icon">
      <span class="material-symbols-outlined">play_arrow</span>
    </div>
  </a>
  <a class="btn" id="btnMoreOptions" onclick="openSidebar('more-info-sidebar')">
    <div class="icon">
      <span class="material-symbols-outlined">more_vert</span>
    </div>
  </a>
</div>

<hr />

<div id="char_meaning" class="meaning-card">{{Meaning}}</div>

<script>
  window.HANZI_CARD_SETTINGS = __HANZI_CARD_SETTINGS__;

  /* __SHARED_AUDIO__ */

  /* __SHARED_AUDIO_BUTTON__ */

  /* __SHARED_VISIBILITY__ */

  function applyCardSettings() {
    var settings =
      (window.HANZI_CARD_SETTINGS && window.HANZI_CARD_SETTINGS.back) || {};
    showHide("#char_pinyin", settings.show_pinyin);
    showHide("#char_meaning", settings.show_meaning, "block");
    showHide("#char_sim", settings.show_simplified, "block");
    showHide(".pinyin", settings.show_pinyin);
    showHide("#char-sim-id", settings.show_simplified);
  }

  /* __SHARED_SIDEBAR__ */

  setupAudioButton();
  applyCardSettings();
</script>
"""
        + render_more_info_sidebar()
    )
    return inject_card_settings(
        render_shared_js_markers(common.TEMPLATE_RESOURCES_DIR, template),
        card_type,
        config,
    )


def render_write_back_template() -> str:
    return """<div id="back">{{FrontSide}}</div>
"""


@dataclass(frozen=True)
class BasicCardTemplateRenderer:
    card_type: str

    def render(self, config: DeckConfig, hw_data_bundle: Path | None = None) -> CardTemplateSpec:
        front = {
            "Meaning": render_meaning_front_template,
            "Pinyin": render_pinyin_front_template,
        }[self.card_type](config)
        return CardTemplateSpec(
            name=f"Card 1 - {self.card_type}",
            qfmt=front,
            afmt=render_basic_back_template(self.card_type, config),
        )


@dataclass(frozen=True)
class WriteCardTemplateRenderer:
    resource_dir: Path

    def render(self, config: DeckConfig, hw_data_bundle: Path | None = None) -> CardTemplateSpec:
        qfmt = render_write_front_template(self.resource_dir)
        qfmt = render_template_text("Write", qfmt, config, hw_data_bundle)
        qfmt = replace_unique_template_marker(
            qfmt,
            MORE_INFO_SIDEBAR_MARKER,
            render_more_info_sidebar(),
            "more-info sidebar",
        )
        return CardTemplateSpec(
            name="Card 1 - Write",
            qfmt=qfmt,
            afmt=render_write_back_template(),
        )


@dataclass(frozen=True)
class HanziTemplateGenerator:
    resource_dir: Path = common.TEMPLATE_RESOURCES_DIR
    fields: tuple[FieldSpec, ...] = FIELD_SPECS

    def static_media(self) -> list[str]:
        return [str(self.resource_dir / path) for path in STATIC_MEDIA_RESOURCE_PATHS]

    def css(self) -> str:
        return read_text(self.resource_dir / "styling-hanzi-3.0.css")

    def card_renderer(self, card_type: str) -> BasicCardTemplateRenderer | WriteCardTemplateRenderer:
        if card_type in {"Meaning", "Pinyin"}:
            return BasicCardTemplateRenderer(card_type)
        if card_type != "Write":
            raise ValueError(f"unknown card type: {card_type}")
        return WriteCardTemplateRenderer(resource_dir=self.resource_dir)

    def model_specs(self, config: DeckConfig, hw_data_bundle: Path | None = None) -> dict[str, ModelSpec]:
        css = self.css()
        specs: dict[str, ModelSpec] = {}
        for card_type in config.card_types:
            renderer = self.card_renderer(card_type)
            model_name = f"{common.DECK_ROOT}::{card_type}"
            specs[card_type] = ModelSpec(
                card_type=card_type,
                name=model_name,
                fields=self.fields,
                templates=(renderer.render(config, hw_data_bundle),),
                css=css,
            )
        return specs
