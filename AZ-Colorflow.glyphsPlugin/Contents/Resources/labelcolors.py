"""Read Glyphs' twelve label colors (``Glyphs.defaults['LabelColors']``, an array
of NSArchiver-archived ``NSColor``s). Outside Glyphs, reads fall back to ``DEFAULTS``.
"""

from __future__ import annotations

# Glyphs' built-in label colors as (r, g, b, a) in 0..1, index 0-11. Used when the
# user has not overridden them (matches the Set Label Colors defaults).
DEFAULTS: list[tuple[float, float, float, float]] = [
    (0.85, 0.26, 0.06, 1.0),
    (0.99, 0.62, 0.11, 1.0),
    (0.65, 0.48, 0.20, 1.0),
    (0.97, 0.90, 0.00, 1.0),
    (0.67, 0.95, 0.38, 1.0),
    (0.04, 0.57, 0.04, 1.0),
    (0.06, 0.60, 0.98, 1.0),
    (0.00, 0.20, 0.88, 1.0),
    (0.50, 0.09, 0.79, 1.0),
    (0.98, 0.36, 0.67, 1.0),
    (0.75, 0.75, 0.75, 1.0),
    (0.25, 0.25, 0.25, 1.0),
]

DEFAULTS_KEY = "LabelColors"

try:
    from AppKit import NSUnarchiver  # type: ignore[import]
    from GlyphsApp import Glyphs  # type: ignore[import]  # pragma: no cover - Glyphs only
except Exception:
    NSUnarchiver = None
    Glyphs = None


def read_label_colors() -> list[tuple[float, float, float, float]]:
    """The twelve current label colors as ``(r, g, b, a)`` tuples, falling back to
    :data:`DEFAULTS` when nothing is stored or when running outside Glyphs."""
    stored = Glyphs.defaults[DEFAULTS_KEY] if Glyphs is not None else None
    if not stored or NSUnarchiver is None:
        return list(DEFAULTS)
    colors: list[tuple[float, float, float, float]] = []
    for index in range(12):
        try:
            color = NSUnarchiver.unarchiveObjectWithData_(stored[index])
            # Device RGB, the space the bars, legend and Settings list draw in.
            rgb = color.colorUsingColorSpaceName_("NSDeviceRGBColorSpace") or color
            colors.append(
                (
                    rgb.redComponent(),
                    rgb.greenComponent(),
                    rgb.blueComponent(),
                    rgb.alphaComponent(),
                )
            )
        except Exception:
            colors.append(DEFAULTS[index])
    return colors
