"""Reads and writes ``colorNames.txt``: the color-label step names and order.

Every reader (the Settings pane, the Font-view bars, Font Glyph Order, the color
wheel) goes through :func:`parse_settings`. No AppKit, so it tests with plain CPython.
"""

from __future__ import annotations

import os
from typing import Any

# Canonical color order — index 0..11 matches Glyphs' native layer color labels.
COLOR_ORDER = [
    "red",
    "orange",
    "brown",
    "yellow",
    "lightGreen",
    "darkGreen",
    "lightBlue",
    "darkBlue",
    "purple",
    "magenta",
    "lightGray",
    "charcoal",
]

# The key file's color names -> Glyphs' color index (layer.color).
NAME_TO_COLOR = {name: index for index, name in enumerate(COLOR_ORDER)}

# Uncolored glyphs' color key. Glyphs' .color is 0-11 or None, so the sentinel sits
# outside that range; grouping always places it last.
NO_COLOR = -1
NONE_TOKEN = "None"
# What uncolored glyphs are called everywhere; a None= label in the key file is ignored.
NO_COLOR_LABEL = "No Color"

KEY_FILE_NAME = "colorNames.txt"

# Optional in-font copy of the labels (same text as colorNames.txt). When present it
# wins over the file, so a shared .glyphs file shows its author's labels.
FONT_LABELS_KEY = "com.hugojourdan.ColorFlow.colorNames"


def _user_home() -> str:
    """Home directory. Glyphs' embedded Python can return ``~`` unexpanded, so
    fall back to ``$HOME``."""
    home = os.path.expanduser("~")
    if not home or home.startswith("~"):
        home = os.environ.get("HOME", "")
    return home


def _glyphs_support_dir() -> str:
    """Glyphs 4's application-support dir: Glyphs' own path inside Glyphs,
    ``~/Library/Application Support/Glyphs 4`` outside it (tests)."""
    try:
        from GlyphsApp import GSGlyphsInfo  # type: ignore[import]

        path = os.path.expanduser(str(GSGlyphsInfo.applicationSupportPath()))  # pragma: no cover
        if path and not path.startswith("~"):  # pragma: no cover - Glyphs only
            return path
    except Exception:
        pass
    return os.path.join(_user_home(), "Library", "Application Support", "Glyphs 4")


def default_info_dir() -> str:
    """Shared Glyphs info dir, resolved at call time (not import time)."""
    return os.path.join(_glyphs_support_dir(), "info")


# Each color's own name: what a step without a name of its own is called.
DEFAULT_LABELS = {
    0: "Red",
    1: "Orange",
    2: "Brown",
    3: "Yellow",
    4: "Light green",
    5: "Dark green",
    6: "Light blue",
    7: "Dark blue",
    8: "Purple",
    9: "Magenta",
    10: "Light gray",
    11: "Charcoal",
    NO_COLOR: NO_COLOR_LABEL,
}

# What a new colorNames.txt holds: every color shown under its own name.
DEFAULT_COLOR_NAMES = f"{NONE_TOKEN}={NO_COLOR_LABEL}\n" + "".join(
    f"{name}={DEFAULT_LABELS[index]}\n" for index, name in enumerate(COLOR_ORDER)
)


def font_labels_text(font: Any) -> str | None:
    """The in-font label text, or ``None`` when absent or blank. Never raises."""
    if font is None:
        return None
    try:
        value = font.userData[FONT_LABELS_KEY]
    except Exception:
        return None
    if isinstance(value, str) and value.strip():
        return value
    return None


def pick_settings_text(userdata_text: str | None, file_text: str | None) -> str:
    """The label text to use: the in-font copy, else the key file, else the
    defaults. Blank sources are skipped."""
    for candidate in (userdata_text, file_text):
        if candidate is not None and candidate.strip():
            return candidate
    return DEFAULT_COLOR_NAMES


def font_dir_of(font: Any) -> str | None:
    """The folder of ``font``'s file, ``None`` for an unsaved font or no font."""
    return os.path.dirname(font.filepath) if font is not None and font.filepath else None


def resolve_key_file(font_dir: str | None, info_dir: str | None = None) -> str:
    """The colorNames.txt to use: ``<font_dir>/colorNames.txt`` when it exists (it
    travels with the font), else the shared one in ``info_dir``."""
    if info_dir is None:
        info_dir = default_info_dir()
    if font_dir:
        local = os.path.join(font_dir, KEY_FILE_NAME)
        if os.path.exists(local):
            return local
    return os.path.join(info_dir, KEY_FILE_NAME)


def write_color_names(path: str, text: str) -> bool:
    """Write ``text`` to ``path``; True on success. A broken symlink is replaced by
    a real file; a valid one is written through."""
    try:
        if os.path.islink(path) and not os.path.exists(path):
            os.unlink(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as key_file:
            key_file.write(text)
        return True
    except OSError:
        return False


def settings_text(font: Any) -> str:
    """The steps in effect for ``font``: its own copy, else its colorNames.txt, else
    the defaults."""
    return pick_settings_text(
        font_labels_text(font), read_color_names(resolve_key_file(font_dir_of(font)))
    )


def read_color_names(path: str) -> str:
    """Read a colorNames.txt file as UTF-8 text (empty string if unreadable)."""
    try:
        with open(path, encoding="utf-8") as key_file:
            return key_file.read()
    except OSError:
        return ""


def label_for(index: int, meaning: dict[int, str]) -> str:
    """Display label for an int color index, falling back to the built-in default."""
    if index == NO_COLOR or index not in meaning:
        return DEFAULT_LABELS.get(index, f"Color {index}")
    return meaning[index]


def section_order(present: set[int], order: list[int]) -> list[int]:
    """Section sequence for the colors present in the font. Key-file order first,
    then remaining present colors numerically; :data:`NO_COLOR` always last, even
    when the key file lists it earlier (uncolored glyphs belong at the end)."""
    listed = [index for index in order if index in present and index != NO_COLOR]
    listed_set = set(listed)
    remaining = sorted(index for index in present if index not in listed_set and index != NO_COLOR)
    result = listed + remaining
    if NO_COLOR in present:
        result.append(NO_COLOR)
    return result


def build_glyph_order(
    glyph_colors: list[tuple[str, int | None]],
    steps: dict[int, str],
    header: str = "#ColorFlow",
) -> list[str]:
    """Build the ``glyphOrder`` custom-parameter value grouping glyphs by color, in
    the order of :func:`shown_steps` ``steps``. ``glyph_colors`` is ``(glyph_name,
    color_index_or_None)`` in font order."""
    buckets: dict[int, list[str]] = {}
    for name, color in glyph_colors:
        index = NO_COLOR if color is None else color
        buckets.setdefault(index, []).append(name)
    code: list[str] = [header]
    for index in section_order(set(buckets), list(steps)):
        code.append(f"**{label_for(index, steps)}**")
        code.extend(buckets[index])
    return code


def parse_settings(text: str) -> tuple[list[tuple[int, str, bool]], str]:
    """Parse colorNames.txt for the Settings pane into ``(rows, none_label)``.

    ``rows`` holds ``(index, label, visible)`` for all 12 colors, file order first,
    missing colors appended hidden. A ``#``-commented line is a hidden color that
    keeps its label."""
    rows: list[tuple[int, str, bool]] = []
    seen: set[int] = set()
    none_label = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        visible = True
        if line.startswith("#"):
            visible = False
            line = line[1:].strip()
        if "=" not in line:
            continue
        name, _, label = line.partition("=")
        name = name.strip()
        label = label.strip()
        if name == NONE_TOKEN:
            none_label = label
            continue
        index = NAME_TO_COLOR.get(name)
        if index is None or index in seen:
            continue
        seen.add(index)
        rows.append((index, label, visible))
    for index in range(12):
        if index not in seen:
            rows.append((index, DEFAULT_LABELS.get(index, ""), False))
    return rows, none_label


def shown_steps(text: str) -> dict[int, str]:
    """The shown steps, ``{index: label}`` in step order: what the sidebar bars, Font
    Glyph Order and the wheel use. A cleared name reads as its color's own name."""
    rows, _none_label = parse_settings(text)
    return {index: label or DEFAULT_LABELS[index] for index, label, visible in rows if visible}


def render_settings(rows: list[tuple[int, str, bool]], none_label: str = "") -> str:
    """Inverse of :func:`parse_settings`; hidden colors are written ``#name=label``."""
    lines: list[str] = []
    if none_label:
        lines.append(f"{NONE_TOKEN}={none_label}")
    for index, label, visible in rows:
        lines.append(f"{'' if visible else '#'}{COLOR_ORDER[index]}={label}")
    return "\n".join(lines) + "\n"


def reorder_visible_rows(
    rows: list[tuple[int, str, bool]], new_visible_order: list[int]
) -> list[tuple[int, str, bool]]:
    """``rows`` with the shown entries in ``new_visible_order``, hidden rows after
    them. Unknown or repeated indices are ignored; shown rows left out keep their
    order at the end."""
    shown = {index: (index, label, visible) for index, label, visible in rows if visible}
    ordered = [shown.pop(index) for index in new_visible_order if index in shown]
    return ordered + list(shown.values()) + [row for row in rows if not row[2]]
