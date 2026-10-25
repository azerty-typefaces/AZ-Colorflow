"""Font Glyph Order: groups the Font View into labelled color sections by
rewriting the font's ``glyphOrder`` parameter from each glyph's layer color on
the selected master. The user's own glyphOrder is saved on enable and restored
on disable.
"""

from __future__ import annotations

import contextlib
from typing import Any

import azcolorflow_census
import colornames

# Saved in the font (userData).
ENABLED_KEY = "com.hugojourdan.ColorFlow.glyphOrderEnabled"
SAVED_ORDER_KEY = "com.hugojourdan.ColorFlow.savedGlyphOrder"
HAD_ORDER_KEY = "com.hugojourdan.ColorFlow.hadGlyphOrder"
SAVED_ACTIVE_KEY = "com.hugojourdan.ColorFlow.savedGlyphOrderActive"

# Volatile cache (font.tempData; not saved).
SNAPSHOT_KEY = "com.hugojourdan.ColorFlow.glyphOrderSnapshot"
MASTER_KEY = "com.hugojourdan.ColorFlow.glyphOrderMaster"

GLYPH_ORDER = "glyphOrder"
HEADER = "#ColorFlow"


def is_enabled(font: Any) -> bool:
    return bool(font.userData[ENABLED_KEY])


def enable(font: Any) -> None:
    # Back up from the parameter itself: by name, Glyphs hides an unticked one, which
    # the rebuild would then overwrite.
    param = _glyph_order_param(font)
    value = param.value if param is not None else None
    if param is not None and value is not None:
        font.userData[SAVED_ORDER_KEY] = value if isinstance(value, str) else list(value)
        font.userData[SAVED_ACTIVE_KEY] = bool(param.active)
        font.userData[HAD_ORDER_KEY] = True
    else:
        font.userData[HAD_ORDER_KEY] = False
    font.userData[ENABLED_KEY] = True
    rebuild(font)


def disable(font: Any) -> None:
    font.userData[ENABLED_KEY] = False
    saved = font.userData[SAVED_ORDER_KEY] if font.userData[HAD_ORDER_KEY] else None
    if saved:
        font.customParameters[GLYPH_ORDER] = saved
        was_active = font.userData[SAVED_ACTIVE_KEY]
        param = _glyph_order_param(font)
        if param is not None and was_active is not None and not was_active:
            param.active = False
    else:
        # An empty but active glyphOrder would still override the font's order.
        _clear(font.customParameters, GLYPH_ORDER)
    _clear(font.userData, SAVED_ORDER_KEY)
    _clear(font.userData, HAD_ORDER_KEY)
    _clear(font.userData, SAVED_ACTIVE_KEY)
    _clear(font.tempData, SNAPSHOT_KEY)
    _clear(font.tempData, MASTER_KEY)


def rebuild(font: Any) -> None:
    """Rewrite the glyphOrder parameter from the current colors and steps."""
    master_id = _master_id(font)
    if master_id is None:
        return
    glyph_keys: list[tuple[str, int | None]] = [
        (glyph.name, _color_key(glyph, master_id)) for glyph in font.glyphs
    ]
    steps = colornames.shown_steps(colornames.settings_text(font))
    font.customParameters[GLYPH_ORDER] = colornames.build_glyph_order(
        glyph_keys, steps, header=HEADER
    )
    _ensure_active(font)
    font.tempData[SNAPSHOT_KEY] = dict(glyph_keys)
    font.tempData[MASTER_KEY] = master_id


def is_dirty(font: Any) -> bool:
    """Cheap check before a rebuild: a missing snapshot, a master switch, an added
    or deleted glyph, or a recolored SELECTED glyph. Recoloring an unselected
    glyph waits for the next selection or master change."""
    snapshot = font.tempData[SNAPSHOT_KEY]
    if snapshot is None:
        return True
    master_id = _master_id(font)
    if master_id is None:
        return False
    if font.tempData[MASTER_KEY] != master_id:
        return True
    if set(snapshot) != set(azcolorflow_census.glyph_names(font)):
        return True
    for layer in font.selectedLayers or []:
        glyph = layer.parent
        if glyph is not None and snapshot.get(glyph.name) != _color_key(glyph, master_id):
            return True
    return False


def _master_id(font: Any) -> str | None:
    master = font.selectedFontMaster if font.parent is not None else None
    if master is None:
        master = font.masters[0] if font.masters else None
    return master.id if master is not None else None


def _color_key(glyph: Any, master_id: str) -> int:
    layer = glyph.layers[master_id]
    return azcolorflow_census.color_to_key(layer.color if layer is not None else None)


def _glyph_order_param(font: Any) -> Any:
    for param in font.customParameters:
        if param.name == GLYPH_ORDER:
            return param
    return None


def _ensure_active(font: Any) -> None:
    """Re-tick a glyphOrder the user unticked. Never flip it off and on to refresh:
    each change re-sorts Glyphs' glyph list under its sidebar count ("Invalid
    filter in sidebar")."""
    param = _glyph_order_param(font)
    if param is not None and not param.active:
        param.active = True


def _clear(proxy: Any, key: str) -> None:
    with contextlib.suppress(KeyError, TypeError):
        del proxy[key]
