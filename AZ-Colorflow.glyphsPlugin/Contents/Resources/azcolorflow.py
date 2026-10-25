"""AZ Colorflow's scripting API, for the Macro Panel and glyphs-cli's ``glyphs run``:

from azcolorflow import save_report

save_report(Font, "Reports/")
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import azcolorflow_assets
import azcolorflow_dashboard


def save_report(font, path: str | Path) -> Path:
    """Write ``font``'s Colorflow report, the page *File ▸ Open Colorflow Report…*
    shows, and return where it went. ``path`` is the HTML file, or a folder (one that
    exists, or ends with "/"), which gets the report's usual name. Missing folders
    are created.

    Unlike the menu it opens nothing, asks nothing and leaves the report's "since your
    last report" starting point alone. Raises ``ValueError`` without a font or glyphs,
    ``OSError`` when the file can't be written."""
    if font is None:
        raise ValueError("No font: pass a GSFont, such as Font.")
    if len(font.glyphs) == 0:
        raise ValueError(f"{font.familyName} has no glyphs to report on.")
    target = Path(path).expanduser()
    if target.is_dir() or str(path).endswith("/"):
        target = target / cast(Path, azcolorflow_dashboard.report_path_for(font)).name
    model, _snapshot = cast("tuple[dict, dict]", azcolorflow_dashboard.build_report_model(font))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(azcolorflow_assets.build_html(model), encoding="utf-8")
    return target.resolve()
