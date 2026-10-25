"""Per-master color counts for the Font-view sidebar bars, read in batches on a
real GSFont and attribute by attribute on test fakes.
"""

from __future__ import annotations

from collections.abc import Iterable

import colornames


def color_to_key(color) -> int:
    """Native ``layer.color`` (an int or ``None``) -> a color key: ``None`` becomes
    ``colornames.NO_COLOR``."""
    return colornames.NO_COLOR if color is None else int(color)


def glyph_names(font) -> list[str]:
    """Every glyph name, in one bridge crossing (``valueForKey_``) on a real GSFont
    instead of one per glyph."""
    getter = getattr(font, "valueForKey_", None)
    if getter is not None:
        try:  # pragma: no cover - app-only path
            return [str(name) for name in getter("glyphs").valueForKey_("name")]
        except Exception:  # pragma: no cover - app-only path
            pass
    return [glyph.name for glyph in font.glyphs]


def _layer_color_reader():
    """A ``layer -> color key`` reader. On a real GSLayer the unbound ``colorIndex``
    selector skips the ``layer.color`` wrapper (255 = no color); fakes use
    ``layer.color``."""
    try:
        import objc

        color_index = objc.lookUpClass(
            "GSLayer"
        ).pyobjc_instanceMethods.colorIndex  # pragma: no cover - app-only path
    except Exception:
        return lambda layer: color_to_key(layer.color)

    def read(layer) -> int:  # pragma: no cover - app-only path
        try:
            index = int(color_index(layer))
        except Exception:
            return color_to_key(layer.color)
        return colornames.NO_COLOR if index == 255 else index

    return read  # pragma: no cover - app-only path


def _master_keys(font, master_id) -> dict[str, int]:
    """``{glyph_name: color key}`` for one master (``NO_COLOR`` when uncolored or
    missing)."""
    glyphs = list(font.glyphs)
    names = glyph_names(font)
    read_color = _layer_color_reader()
    keys: dict[str, int] = {}
    for name, glyph in zip(names, glyphs, strict=True):
        layer = glyph.layers[master_id]
        keys[name] = colornames.NO_COLOR if layer is None else read_color(layer)
    return keys


def row_bar_census(font, master_id: str | None = None) -> dict:
    """What the row bars need for one master: the shown steps' ``labels`` by color key,
    in step order, and each glyph's color ``keys``. :func:`row_bar_dist` counts a row's
    glyphs."""
    steps = colornames.shown_steps(colornames.settings_text(font))
    labels = {str(index): label for index, label in steps.items()}
    if master_id is None:
        try:
            master_id = font.selectedFontMaster.id
        except Exception:
            master_id = font.masters[0].id if font.masters else None
    return {
        "master_id": master_id,
        "labels": labels,
        "keys": _master_keys(font, master_id) if master_id is not None else {},
    }


def row_bar_dist(names, keys: dict[str, int], steps: Iterable[str]) -> dict[str, int]:
    """``{colorKey: count}`` over one sidebar row's glyph ``names``, for the color keys
    in ``steps``. Uncolored glyphs (and names missing from ``keys``) are not counted."""
    counts = dict.fromkeys(steps, 0)
    for name in names:
        key = str(keys.get(name, colornames.NO_COLOR))
        if key in counts:
            counts[key] += 1
    return counts
