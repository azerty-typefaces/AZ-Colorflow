"""Color Font Dashboard — data model + entry point for Color Flow's report.

Summarises, per master, how the font's glyphs are distributed across the
steps, and which glyphs changed color since the last run. This module builds
the data model and writes the report; the interactive HTML/CSS/JS that renders
it lives in ``azcolorflow_assets`` (one self-contained, offline file).

The steps are ``colornames.shown_steps``, the same ones the sidebar bars, Font
Glyph Order and the wheel use (same glyph set: ALL glyphs, the layer's own
``layer.color`` only). The per-group ``dist`` data is the exact census
(:func:`single_counts`); ``masters[].counts`` is the cumulative "reached step k
or beyond" view (:func:`master_counts`). The uncolored "None" row is tallied
separately.

Design notes:
  * the "what changed since last run" snapshot lives in ``Glyphs.defaults`` keyed
    by file path — NOT in the .glyphs file and NOT in a sidecar — so the source
    stays clean while the diff still survives across sessions;
  * ``build_model`` returns a plain dict; ``azcolorflow_assets.build_html`` embeds it
    as JSON and the inline JS app renders it (search/filter/sort, tabs + compare,
    per-glyph heatmap) with no network and no dependencies.

The data layer imports nothing from Glyphs so it stays unit-testable; only the
snapshot helpers and ``main`` touch the running app.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import cast

import azcolorflow_assets
import azcolorflow_git
import azcolorflow_history_store
import colornames
import glyphsvg
import labelcolors

try:
    from GlyphsApp import Glyphs, Message  # type: ignore[import]
except Exception:  # pragma: no cover - only importable inside Glyphs
    Glyphs = None

    def Message(*args, **kwargs) -> None:
        pass


# Where the cross-session diff snapshot is stored (app prefs, not the font file).
DEFAULTS_KEY = "com.hugojourdan.ColorFlow.reportSnapshot"


# --------------------------------------------------------------------------- #
# Pure data layer (no GlyphsApp) — unit-tested in tests/test_azcolorflow_dashboard
# --------------------------------------------------------------------------- #


def color_to_key(color) -> int:
    """Native ``layer.color`` (int 0-11 or ``None``) -> a plist-safe storage/
    display key: ``None`` becomes ``colornames.NO_COLOR`` (-1)."""
    return colornames.NO_COLOR if color is None else int(color)


def _unwrap(value, default=None):
    """A KVC column entry as plain Python: a nil ObjC field arrives as ``NSNull``
    (which is truthy and stringifies to "<null>"), so it has to become ``default``."""
    if value is None or type(value).__name__ == "NSNull":
        return default
    return value


def _glyph_columns(font, *keys: str) -> list[list] | None:
    """The named ``GSGlyph`` field for every glyph, ONE bridge crossing per field.

    Iterating ``font.glyphs`` in Python costs a crossing per glyph, which dominates
    these whole-font reads on big families; ``valueForKey_`` lets Foundation collect
    the column instead (measured 12.8 ms -> 1.9 ms for name+category+script on 860
    glyphs). ``None`` when ``font`` is not a real GSFont — fakes and headless
    callers fall back to the plain loop at each call site."""
    getter = getattr(font, "valueForKey_", None)
    if getter is None:
        return None
    try:
        glyphs = getter("glyphs")
        columns = [list(glyphs.valueForKey_(key)) for key in keys]
    except Exception:
        return None
    if not columns or any(len(column) != len(columns[0]) for column in columns):
        return None  # ragged columns are unusable
    return columns


def _layer_color_reader():
    """A ``layer -> storage key`` reader for :func:`build_master_glyph_colors`.

    On a real GSLayer the unbound ``colorIndex`` selector skips the ``layer.color``
    property wrapper, which matters because this runs once per glyph per master;
    255 is GSLayer's "no color" sentinel. Falls back to ``layer.color`` for fakes
    and for anything without the selector."""
    try:
        import objc

        color_index = objc.lookUpClass("GSLayer").pyobjc_instanceMethods.colorIndex
    except Exception:
        return lambda layer: color_to_key(layer.color)

    def read(layer) -> int:
        try:
            index = int(color_index(layer))
        except Exception:
            return color_to_key(layer.color)
        return colornames.NO_COLOR if index == 255 else index

    return read


def snapshot_to_colors(per_glyph: dict[str, int]) -> list[int | None]:
    """Inverse of :func:`color_to_key` over a master's ``{glyph_name: key}`` map:
    a list of native colors (``int`` or ``None``) ready for the ``colornames``
    counting functions. ``NO_COLOR`` (-1) becomes ``None``."""
    return [None if key == colornames.NO_COLOR else int(key) for key in per_glyph.values()]


def master_counts(colors: list[int | None], order: list[str]) -> dict[str, int]:
    """Cumulative per-step counts ("reached step k or beyond"): a color credits
    its own step and every step before it in ``order``. ``None`` and colors
    outside ``order`` credit nothing."""
    counts = dict.fromkeys(order, 0)
    position = {key: index for index, key in enumerate(order)}
    for color in colors:
        reached = None if color is None else position.get(str(color))
        if reached is not None:
            for key in order[: reached + 1]:
                counts[key] += 1
    return counts


def single_counts(colors: list[int | None], order: list[str]) -> dict[str, int]:
    """Exact census: how many layers have each step's color."""
    counts = dict.fromkeys(order, 0)
    for color in colors:
        if color is not None and str(color) in counts:
            counts[str(color)] += 1
    return counts


def uncolored_count(colors: list[int | None], order: list[str]) -> int:
    """How many layers fall outside the counted steps — the exact complement of
    "credited to a step": ``None`` or a color whose ``str`` is not in ``order``
    (hidden / unknown). The ``colornames`` counters never emit a None bucket, so
    the dashboard tallies it itself."""
    order_set = set(order)
    return sum(1 for color in colors if color is None or str(color) not in order_set)


def compute_changes(current: dict, previous: dict) -> dict:
    """Per master id, ``{glyph_name: (old_key, new_key)}`` for glyphs whose
    color changed since the previous snapshot.

    Both arguments are ``{master_id: {glyph_name: key}}``. Glyphs absent from the
    previous snapshot (newly added) are not reported as changes."""
    changes: dict = {}
    for master_id, colors in current.items():
        previous_master = previous.get(master_id, {})
        master_changes = {}
        for name, key in colors.items():
            if name in previous_master and previous_master[name] != key:
                master_changes[name] = (previous_master[name], key)
        changes[master_id] = master_changes
    return changes


def display_from_meaning(meaning: dict[str, str]) -> list[tuple[int, str]]:
    """Ordered ``[(int_key, label)]`` of the rows to show: the steps in the user's
    order, then the None bucket last. Int keys (so the swatch CSS variables line
    up); counting stays in str space."""
    display = [(int(index), label) for index, label in meaning.items()]
    display.append((colornames.NO_COLOR, colornames.NO_COLOR_LABEL))
    return display


# --------------------------------------------------------------------------- #
# GlyphsApp-touching helpers
# --------------------------------------------------------------------------- #


def non_exporting_names(font) -> list[str]:
    """Sorted names of this font's non-exporting glyphs (``glyph.export`` is
    falsy). Cheap (one ``font.glyphs`` pass) and shipped in the model so the
    report can ALWAYS exclude these glyphs from every displayed percentage —
    empty list when every glyph exports (nothing to exclude)."""
    columns = _glyph_columns(font, "name", "export")
    if columns is not None:
        names, exports = columns
        # A nil export field counts as exporting, matching Glyphs' default.
        return sorted(
            str(names[index]) for index in range(len(names)) if not _unwrap(exports[index], True)
        )
    return sorted(str(glyph.name) for glyph in font.glyphs if not getattr(glyph, "export", True))


def glyph_meta(font) -> dict:
    """``{glyph_name: {category, script}}`` feeding the per-glyph ``categories`` /
    ``scripts`` model lists (heatmap lanes + coverage grouping)."""
    columns = _glyph_columns(font, "name", "category", "script")
    if columns is not None:
        names, categories, scripts = columns
        return {
            str(names[index]): {
                "category": str(_unwrap(categories[index]) or ""),
                "script": str(_unwrap(scripts[index]) or ""),
            }
            for index in range(len(names))
        }
    return {
        glyph.name: {
            "category": str(getattr(glyph, "category", None) or ""),
            "script": str(getattr(glyph, "script", None) or ""),
        }
        for glyph in font.glyphs
    }


def _meaning(font) -> dict[str, str]:
    """``{str(color index): step name}`` for the font's shown steps, in step order."""
    steps = colornames.shown_steps(colornames.settings_text(font))
    return {str(index): label for index, label in steps.items()}


def build_master_glyph_colors(font) -> dict[str, dict[str, int]]:
    """``{master_id: {glyph_name: key}}`` over ALL glyphs, taking the layer's own
    ``layer.color`` only (a missing layer is uncolored) — exactly the set and
    source the sidebar bars count."""
    master_ids = [master.id for master in font.masters]
    data: dict[str, dict[str, int]] = {master_id: {} for master_id in master_ids}
    read_color = _layer_color_reader()
    # ONE font.glyphs pass, ONE glyph.layers access per glyph. Both are bridge
    # crossings and the old master-outer/glyph-inner shape paid them masters-times
    # over: 1253 ms -> 218 ms on 860 glyphs x 18 masters, same output.
    for glyph in font.glyphs:
        name = glyph.name
        layers = glyph.layers
        for master_id in master_ids:
            layer = layers[master_id]
            data[master_id][name] = colornames.NO_COLOR if layer is None else read_color(layer)
    return data


def _coerce_snapshot(raw) -> dict[str, dict[str, int]]:
    """Coerce a possibly NSDictionary-backed snapshot into plain
    ``{master_id: {glyph_name: int}}`` so iteration/indexing behave normally."""
    snapshot: dict[str, dict[str, int]] = {}
    if not raw:
        return snapshot
    for master_id in raw:
        inner = raw[master_id]
        snapshot[str(master_id)] = {str(name): int(inner[name]) for name in inner}
    return snapshot


def _today(today: str | None) -> str:
    return today or datetime.now().strftime("%Y-%m-%d")


def load_snapshot(font, today: str | None = None) -> dict[str, dict[str, int]]:
    """Today's Before/After baseline for this font from ``Glyphs.defaults`` (keyed by
    file path): the state at the last report of an EARLIER day, held for the whole
    day so re-opening the report keeps showing the day's changes. Older builds kept
    one bare snapshot (the last report), which reads as that. Empty dict if none /
    unsaved / unavailable."""
    if Glyphs is None or not font.filepath:
        return {}
    store = Glyphs.defaults[DEFAULTS_KEY]
    if not store or not hasattr(store, "get"):
        return {}
    entry = store.get(font.filepath)
    if not entry or "day" not in entry:
        return _coerce_snapshot(entry)
    return _coerce_snapshot(entry["baseline"] if entry["day"] == _today(today) else entry["last"])


def save_snapshot(font, snapshot: dict, today: str | None = None) -> None:
    """Persist this run's snapshot in ``Glyphs.defaults`` (not the .glyphs file),
    alongside today's baseline (see :func:`load_snapshot`; a first-ever run is its
    own baseline).

    On the way, entries whose font file no longer exists on disk are pruned — the
    store is keyed by file path and would otherwise accumulate a per-glyph snapshot
    for every font ever reported. The current font's entry is always kept."""
    if Glyphs is None or not font.filepath:
        return
    day = _today(today)
    baseline = load_snapshot(font, day) or snapshot
    store = Glyphs.defaults[DEFAULTS_KEY]
    store = dict(store) if hasattr(store, "keys") else {}
    store[font.filepath] = {"day": day, "baseline": baseline, "last": snapshot}
    store = {
        path: snap
        for path, snap in store.items()
        if path == font.filepath or Path(str(path)).exists()
    }
    Glyphs.defaults[DEFAULTS_KEY] = store


# --------------------------------------------------------------------------- #
# Dated history — a capped series of per-glyph snapshots, the substrate for the
# dashboard's burndown / velocity and the per-glyph step-journey sparkline.
#
# Stored IN THE FONT (userData), packed by azcolorflow_history_store, so the timeline travels
# WITH the file: a shared .glyphs/.glyphspackage shows the same history on any
# machine, with no git repo or sidecar needed.
# --------------------------------------------------------------------------- #

TIMELINE_USERDATA_KEY = "com.hugojourdan.ColorFlow.timelineHistory"  # primary (font userData)
CORRUPT_HISTORY_SUFFIX = ".corrupt"  # where an undecodable timeline payload is stashed
STORE_HISTORY_KEY = "com.hugojourdan.ColorFlow.storeHistory"  # userData: True once agreed
DECLINED_HISTORY_KEY = "com.hugojourdan.ColorFlow.historyDeclined"  # defaults: [paths]; tempData


def _read_user_data(font, key: str) -> object:
    """Safely read ``font.userData[key]`` (``None`` when absent / unavailable)."""
    try:
        user_data = getattr(font, "userData", None)
        if user_data is None:
            return None
        try:
            return user_data[key]
        except (KeyError, TypeError):
            return None
    except Exception:
        return None


def _write_user_data(font, key: str, value: object) -> None:
    """Safely set ``font.userData[key] = value`` (no-op when unavailable)."""
    try:
        user_data = getattr(font, "userData", None)
        if user_data is None:
            return
        user_data[key] = value
    except Exception:
        pass


def history_choice(font) -> bool | None:
    """Whether this font's color history may be stored inside its file: ``True`` once
    the user agreed (a flag in userData, so it travels with the file), ``False`` once
    declined (remembered on this Mac by file path, or for the session while the font
    is unsaved), ``None`` when never asked. Nothing is recorded until ``True``.
    Git-tracked fonts are never asked: their commits are the history."""
    if Glyphs is None or font is None:
        return None
    if _read_user_data(font, STORE_HISTORY_KEY):
        return True
    try:
        if font.tempData[DECLINED_HISTORY_KEY]:
            return False
    except Exception:
        pass
    declined = [str(path) for path in Glyphs.defaults[DECLINED_HISTORY_KEY] or []]
    if font.filepath and str(font.filepath) in declined:
        return False
    return None


def set_history_choice(font, store: bool) -> None:
    """Record the user's answer (see :func:`history_choice`). Declining writes nothing
    into the file and keeps any history already there (still shown, never added to)."""
    if Glyphs is None or font is None:
        return
    path = str(font.filepath) if font.filepath else None
    declined = [
        str(other)
        for other in Glyphs.defaults[DECLINED_HISTORY_KEY] or []
        if str(other) != path and Path(str(other)).exists()
    ]
    if store:
        _write_user_data(font, STORE_HISTORY_KEY, True)
    elif _read_user_data(font, STORE_HISTORY_KEY) is not None:
        del font.userData[STORE_HISTORY_KEY]
    if not store and path:
        declined.append(path)
    try:
        font.tempData[DECLINED_HISTORY_KEY] = None if store else True
    except Exception:
        pass
    Glyphs.defaults[DECLINED_HISTORY_KEY] = declined


def _stash_corrupt_history(font, raw: object) -> None:
    """Preserve an undecodable timeline payload under a ``.corrupt`` backup key so a
    later save (which rewrites the primary key with a fresh log) can never silently
    destroy it. The FIRST corrupt copy wins — the stash is recovery evidence, not a
    rolling buffer — and the incident is printed so the loss of a readable timeline
    is visible rather than a mystery."""
    backup_key = TIMELINE_USERDATA_KEY + CORRUPT_HISTORY_SUFFIX
    if _read_user_data(font, backup_key) is None:
        _write_user_data(font, backup_key, str(raw))
    print(
        "AZ Colorflow: this font's embedded timeline history could not be decoded; "
        f"the raw payload was preserved in userData[{backup_key!r}]."
    )


def load_history(font) -> dict[str, dict[str, dict[str, int]]]:
    """This font's per-*save* snapshot log, ordered oldest-first — one entry per save,
    keyed by ISO datetime (``%Y-%m-%dT%H:%M:%S``). The report groups these by date for
    the per-day timeline (:func:`group_saves_by_date`) and uses the raw log for the
    per-save view. Read from the font's ``userData``, so the timeline travels with the
    file. Empty when none / unavailable. A payload that is present but *undecodable* is stashed under a
    ``.corrupt`` backup key first (see :func:`_stash_corrupt_history`), so the
    subsequent fresh log never silently wipes the original data. Datetime keys sort
    lexicographically = chronologically."""
    if Glyphs is None or font is None:
        return {}
    raw = _read_user_data(font, TIMELINE_USERDATA_KEY)
    try:
        history = azcolorflow_history_store.decode_history(raw)
    except azcolorflow_history_store.HistoryDecodeError:
        _stash_corrupt_history(font, raw)
        history = {}
    return {key: history[key] for key in sorted(history)}


def group_saves_by_date(log: dict) -> dict[str, dict[str, dict[str, int]]]:
    """Collapse a per-save log (``{iso_datetime: snapshot}``) to a per-day history
    (``{iso_date: snapshot}``), keeping the LAST save of each day (the latest state
    that day). Legacy date-keyed entries (10-char keys) pass through unchanged."""
    grouped: dict[str, dict[str, dict[str, int]]] = {}
    for key in sorted(log):  # chronological; later same-day wins
        grouped[str(key)[:10]] = log[key]
    return grouped


def _keep_last_save_of_past_days(series: dict) -> dict:
    """Collapse every *past* day to its final save (end-of-day state), keeping every
    save of the most-recent day. Once work moves to a new day the old day's intra-day
    saves stop mattering, so only its closing state is kept — this is what bounds the
    log's growth (one entry per past day, forever; no day-window cap)."""
    keys = sorted(series)
    latest_day = str(keys[-1])[:10]
    last_of_day: dict[str, str] = {}
    for key in keys:  # chronological; later same-day wins
        last_of_day[str(key)[:10]] = key
    return {
        key: series[key]
        for key in keys
        if str(key)[:10] == latest_day or last_of_day[str(key)[:10]] == key
    }


def record_history(font, snapshot: dict, now: datetime) -> bool:
    """Append a per-glyph ``snapshot`` to this font's per-*save* log in ``userData``,
    keyed by save datetime (one entry per save, not per day). Skips a no-op save: if
    the snapshot equals the most-recent stored one (e.g. an outline-only edit or a
    double save with no color change), nothing is written, so the log only grows on
    color-changing saves. The log is never day-capped; instead each *past* day keeps
    only its final save (see :func:`_keep_last_save_of_past_days`). The value is
    written into the font object; Glyphs persists it on the next save. True when an
    entry landed in userData; False for a no-op save, a font that can't hold it, or
    without Glyphs/font."""
    if Glyphs is None or font is None:
        return False
    series = load_history(font)
    series = {str(key): series[key] for key in series}
    if series and series[max(series)] == snapshot:
        return False  # nothing changed -> no junk entry
    series[now.strftime("%Y-%m-%dT%H:%M:%S")] = snapshot
    series = _keep_last_save_of_past_days(series)
    payload = azcolorflow_history_store.encode_history(series)
    _write_user_data(font, TIMELINE_USERDATA_KEY, payload)
    # Only a write that landed counts: the plugin saves again on True, and a False here
    # is what keeps a font that can't hold the history from saving forever.
    return _read_user_data(font, TIMELINE_USERDATA_KEY) == payload


def _git_open_colors(path) -> dict | None:
    """Open a historical font (a ``.glyphs`` file or ``.glyphspackage`` extracted from
    a git commit) headlessly and return its ``{master_id: {glyph_name: key}}``
    color snapshot. Glyphs-only; ``None`` outside Glyphs or on any open failure."""
    if Glyphs is None:
        return None
    font = None
    try:
        font = Glyphs.open(str(path), showInterface=False)
        if font is None:
            return None
        return build_master_glyph_colors(font)
    except Exception:
        return None
    finally:  # close the document we opened so it doesn't linger in the app
        if font is not None:
            try:
                document = getattr(font, "parent", None)
                if document is not None:
                    document.close()
            except Exception:
                pass


def is_git_tracked(font) -> bool:
    """Whether this font's source file lives in a git repo and is tracked there.

    A tracked font's history comes from its commits alone: it is never asked to store
    history in the file. Cheap (two quick git calls); ``False`` when the font is
    unsaved or git is unavailable."""
    path = getattr(font, "filepath", None)
    if not path:
        return False
    try:
        target = Path(path)
        repo = azcolorflow_git.git_root(target)
        return repo is not None and azcolorflow_git.is_tracked(repo, target)
    except Exception:
        return False


# Git-tracked fonts keep nothing in the file: each commit's color snapshot is cached
# on this Mac instead, keyed by commit SHA, so a commit is opened headless only once.
GIT_CACHE_DIR = Path.home() / "Library" / "Caches" / "com.hugojourdan.ColorFlow" / "git"


def _git_cache_path(font_path: str) -> Path:
    digest = hashlib.sha1(str(Path(font_path).resolve()).encode("utf-8")).hexdigest()
    return GIT_CACHE_DIR / f"{digest}.txt"


def collect_report_git_commits(font, progress=None) -> dict | None:
    """THE single per-report git pass: ``{commit_datetime: snapshot}`` for every commit
    of this font (capped to the most-recent ``azcolorflow_git.DEFAULT_CAP``). Commits
    already in this Mac's cache (:data:`GIT_CACHE_DIR`) are not reopened; nothing is
    ever written into the font. Feeds both the per-day and the per-commit timeline
    (see :func:`build_model`). Returns ``None`` when the font is unsaved, not
    git-tracked, Glyphs is unavailable, or the pass failed — so callers can tell
    "no git" from "git, no commits" (``{}``)."""
    if Glyphs is None or not getattr(font, "filepath", None) or not is_git_tracked(font):
        return None
    cache_path = _git_cache_path(font.filepath)
    try:
        cache = azcolorflow_history_store.decode_history(cache_path.read_text(encoding="utf-8"))
    except Exception:  # missing or unreadable: rebuilt from git
        cache = {}
    known = set(cache)
    try:
        commits = cast(
            dict,
            azcolorflow_git.collect_commit_history(
                font.filepath, _git_open_colors, progress=progress, cache=cache
            ),
        )
    except Exception:
        return None
    if set(cache) != known:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(azcolorflow_history_store.encode_history(cache), encoding="utf-8")
        except OSError:
            pass  # next report reopens the new commits
    return commits


# --------------------------------------------------------------------------- #
# Burndown / velocity — pure functions over the dated history.
# "final" is the completion metric: the cumulative count at the last workflow
# step.
# --------------------------------------------------------------------------- #


def _master_point(per_glyph: dict, order: list[str]) -> dict[str, int]:
    """One master's ``{final, started, total}`` for a single dated snapshot."""
    colors = snapshot_to_colors(per_glyph)
    counts = master_counts(colors, order)
    total = len(per_glyph)
    started = total - uncolored_count(colors, order)
    last = order[-1] if order else None
    final = started if last is None else counts.get(last, 0)
    return {"final": final, "started": started, "total": total}


def history_series(history: dict, order: list[str]) -> list[dict]:
    """The dated history reduced to a per-master count time series, oldest-first:
    ``[{"date": iso, "masters": {master_id: {final, started, total}}}]``."""
    series = []
    for date in sorted(history):
        masters = {
            master_id: _master_point(per_glyph, order)
            for master_id, per_glyph in history[date].items()
        }
        series.append({"date": date, "masters": masters})
    return series


def cross_master_summary(
    current: dict, master_ids: list[str], glyph_names: list[str], order: list[str]
) -> dict:
    """Cross-master agreement over the reported glyphs. For each glyph, gather its
    color key in *every* master (absent/uncolored == ``NO_COLOR``); a glyph is
    ``identical`` when all masters share one key, and ``doneEverywhere`` when that
    shared key is the workflow's final step (``order[-1]`` — the same "done" step
    the report grades 100%). Returns counts plus ``byStep`` (how identical glyphs
    split across the shared keys, including the uncolored ``-1`` bucket) and
    ``differGlyphs`` (the names that disagree, in glyph order) for the expandable
    list. A single-master font has every glyph identical; an empty/no-master font
    returns all-zero with empty lists."""
    final_step = int(order[-1]) if order else None
    identical = differ = done_everywhere = 0
    by_step: dict[int, int] = {}
    differ_glyphs: list[str] = []
    for name in glyph_names:
        keys = [
            int(current.get(master_id, {}).get(name, colornames.NO_COLOR))
            for master_id in master_ids
        ]
        if not keys:
            continue
        shared = keys[0] if len(set(keys)) == 1 else None
        if shared is not None:
            identical += 1
            by_step[shared] = by_step.get(shared, 0) + 1
            if final_step is not None and shared == final_step:
                done_everywhere += 1
        else:
            differ += 1
            differ_glyphs.append(name)
    return {
        "total": identical + differ,
        "masterCount": len(master_ids),
        "finalStep": final_step,
        "identical": identical,
        "differ": differ,
        "doneEverywhere": done_everywhere,
        "byStep": {str(key): count for key, count in sorted(by_step.items())},
        "differGlyphs": differ_glyphs,
    }


# --------------------------------------------------------------------------- #
# Full JSON model
# --------------------------------------------------------------------------- #


def _master_layers(font, master_id: str, names: tuple) -> list:
    """``[(layer, dx)]`` for the named glyphs on one master, each offset by the
    running advance width so they sit side by side. Missing glyphs/layers are
    skipped. Used to preview a master's design (e.g. "Aa") on its tab."""
    layers: list = []
    advance = 0.0
    for name in names:
        glyph = font.glyphs[name]
        if glyph is None:
            continue
        layer = glyph.layers[master_id]
        if layer is None:
            continue
        layers.append((layer, advance))
        advance += layer.width
    return layers


def _master_previews(font) -> dict:
    """Per-master ``{"d", "vb"}`` outline of "Aa" for the master-tab preview, so
    each tab shows that master's actual letterforms (weight/width) instead of a
    plain name. ``{}`` for any master whose A/a have no outline."""
    return {
        master.id: glyphsvg.layers_outline(_master_layers(font, master.id, ("A", "a")))
        for master in font.masters
    }


def _logo_master(font):
    """The master to draw the header logo with: Regular, else Bold, else the first."""
    if not font.masters:
        return None
    for target in ("regular", "bold"):
        for master in font.masters:
            if (master.name or "").lower() == target:
                return master
    return font.masters[0]


def _family_logo(font) -> dict:
    """The family name set in the font's own glyphs (via :func:`_logo_master`) as a
    single ``{"d", "vb"}`` outline, so the report header shows the typeface in
    itself. ``{}`` when it can't be drawn (no master / name / matching glyphs)."""
    master = _logo_master(font)
    name = font.familyName or ""
    if master is None or not name:
        return {}
    upm = float(getattr(font, "upm", None) or 1000.0)
    space = upm * 0.28
    layers: list = []
    advance = 0.0
    for char in name:
        glyph = None if char == " " else font.glyphs[char]
        layer = glyph.layers[master.id] if glyph is not None else None
        if layer is None:
            advance += space
            continue
        layers.append((layer, advance))
        advance += getattr(layer, "width", 0) or 0
    return glyphsvg.layers_outline(layers)


def _hex(rgba: tuple) -> str:
    """``(r, g, b[, a])`` floats in 0..1 as ``#rrggbb`` (alpha ignored)."""
    return "#" + "".join(f"{round(min(1.0, max(0.0, channel)) * 255):02x}" for channel in rgba[:3])


def _glyph_groups(font, attr: str) -> dict[str, list[str]]:
    """``{group_value: [glyph_name]}`` grouping all glyphs by a per-glyph
    attribute (``script`` or ``category``); a missing/blank value -> ``"Other"``."""
    groups: dict[str, list[str]] = {}
    for glyph in font.glyphs:
        value = getattr(glyph, attr, None) or "Other"
        groups.setdefault(str(value), []).append(glyph.name)
    return groups


def _coverage_for(
    current: dict, groups: dict[str, list[str]], order: list[str]
) -> dict[str, list[dict]]:
    """Per-master coverage rows for one grouping: each row is a group's
    ``{key, total, final, started, uncolored, counts}`` using the SAME counting
    as the rest of the report, restricted to that group's glyphs. Rows are sorted
    largest group first."""
    last = order[-1] if order else None
    result: dict[str, list[dict]] = {}
    for master_id, per_glyph in current.items():
        rows = []
        for group, names in groups.items():
            colors = snapshot_to_colors(
                {name: per_glyph.get(name, colornames.NO_COLOR) for name in names}
            )
            counts = master_counts(colors, order)
            total = len(names)
            started = total - uncolored_count(colors, order)
            final = started if last is None else counts.get(last, 0)
            rows.append(
                {
                    "key": group,
                    "total": total,
                    "final": final,
                    "started": started,
                    "uncolored": total - started,
                    "counts": counts,
                    "dist": single_counts(colors, order),
                }
            )
        rows.sort(key=lambda row: (-row["total"], row["key"]))
        result[master_id] = rows
    return result


_SCRIPT_DISPLAY = {
    "latin": "Latin",
    "greek": "Greek",
    "cyrillic": "Cyrillic",
    "arabic": "Arabic",
    "hebrew": "Hebrew",
    "devanagari": "Devanagari",
    "bengali": "Bangla",
    "gujarati": "Gujarati",
    "gurmukhi": "Gurmukhi",
    "tamil": "Tamil",
    "telugu": "Telugu",
    "kannada": "Kannada",
    "malayalam": "Malayalam",
    "oriya": "Odia",
    "sinhala": "Sinhala",
    "thai": "Thai",
    "lao": "Lao",
    "tibetan": "Tibetan",
    "myanmar": "Myanmar",
    "khmer": "Khmer",
    "georgian": "Georgian",
    "armenian": "Armenian",
    "hangul": "Hangul",
    "han": "Han",
    "hiragana": "Hiragana",
    "katakana": "Katakana",
    "kana": "Kana",
    "cherokee": "Cherokee",
    "Other": "Other",
}


def _script_display(key: str) -> str:
    """Human label for a Glyphs script id (``latin`` -> ``Latin``)."""
    if key in _SCRIPT_DISPLAY:
        return _SCRIPT_DISPLAY[key]
    return key[:1].upper() + key[1:]


def _script_meta(font) -> dict[str, dict]:
    """``{scriptKey: {"name": display}}`` so the dashboard's script grid can label
    each square."""
    return {key: {"name": _script_display(key)} for key in _glyph_groups(font, "script")}


def build_coverage(font, current: dict, order: list[str]) -> dict:
    """Completion broken down by Unicode script and by glyph category, per master
    — the data behind the dashboard's Coverage view (#13). ``scriptMeta`` adds a
    display name + representative glyph per script for the script grid."""
    return {
        "byScript": _coverage_for(current, _glyph_groups(font, "script"), order),
        "byCategory": _coverage_for(current, _glyph_groups(font, "category"), order),
        "scriptMeta": _script_meta(font),
    }


def build_journey_index(history: dict, dates: list) -> dict:
    """Sparse per-master ``{glyph_name: [[iso_date, step_key], ...]}`` of color
    *change-events* — the first observation of each glyph plus every date its key
    actually changed. Reconstructs full state at any date by carrying the last
    event forward, so it stays small for big fonts. Missing dates read as uncolored. Covers every glyph seen in history,
    aligned to ``dates`` (oldest-first).

    Built by diffing each date's snapshot against a carried per-glyph state — one
    pass over the history instead of the previous dense
    ``masters x glyphs x dates`` re-lookup — with identical output: a glyph absent
    on a date reads as uncolored, and a glyph first seen mid-history gets its
    implicit uncolored first-observation at ``dates[0]`` exactly as before."""
    if not dates:
        return {}
    index: dict = {}
    master_ids: set = set()
    for per_master in history.values():
        master_ids.update(per_master.keys())
    first_date = dates[0]
    for master_id in master_ids:
        per_glyph: dict = {}
        state: dict = {}  # name -> key of its last event
        for date in dates:
            snapshot = history.get(date, {}).get(master_id, {})
            for name, key in snapshot.items():
                previous = state.get(name)
                if previous is None:  # first sighting of this glyph
                    if date == first_date:
                        per_glyph[name] = [[date, key]]
                    else:  # implicitly uncolored since dates[0]
                        per_glyph[name] = [[first_date, colornames.NO_COLOR]]
                        if key != colornames.NO_COLOR:
                            per_glyph[name].append([date, key])
                    state[name] = key
                elif key != previous:
                    per_glyph[name].append([date, key])
                    state[name] = key
            # A glyph seen before but absent from this date's snapshot reads as
            # uncolored — emit the change once, when it actually disappears.
            for name in state.keys() - snapshot.keys():
                if state[name] != colornames.NO_COLOR:
                    per_glyph[name].append([date, colornames.NO_COLOR])
                    state[name] = colornames.NO_COLOR
        index[master_id] = per_glyph
    return index


def _days_ago(value, now: datetime) -> int | None:
    """Whole days between ``value`` (a Glyphs ``lastChange`` NSDate or a
    ``datetime``) and ``now``; ``None`` when absent/unreadable. Glyphs' per-glyph
    ``lastChange`` is often disabled in foundry setups, hence the tolerant None."""
    if value is None:
        return None
    edited = None
    timestamp = getattr(value, "timeIntervalSince1970", None)
    if callable(timestamp):
        try:
            edited = datetime.fromtimestamp(cast(float, timestamp()))
        except Exception:
            edited = None
    if edited is None and isinstance(value, datetime):
        edited = value
    if edited is None:
        return None
    return max(0, (now - edited).days)


def glyph_last_edit(font, now: datetime) -> dict:
    """``{glyph_name: days_since_edit}`` for glyphs that carry a ``lastChange``.
    Per-GLYPH only (Glyphs has no per-layer timestamp), and sparse — glyphs whose
    timestamp is missing/disabled are simply absent."""
    result = {}
    for glyph in font.glyphs:
        days = _days_ago(getattr(glyph, "lastChange", None), now)
        if days is not None:
            result[glyph.name] = days
    return result


def build_model(
    font,
    now: datetime,
    current: dict,
    previous: dict,
    progress=None,
    git_commits: dict | None = None,
) -> dict:
    """The full data model the JS app renders. Pure aside from reading the
    font's steps (via _meaning) — the same source the sidebar bars use, so
    counts stay in lockstep.

    ``progress`` (optional ``Callable[[float], None]``) receives a 0->1 fraction
    so a caller can drive a determinate loader; the outline phase dominates the
    cost, so it gets most of the band.

    ``git_commits`` is this run's git pass (:func:`collect_report_git_commits`) for a
    git-tracked font: both timelines then come from it alone. ``None`` (not in git)
    reads the font's own per-save log instead."""
    meaning = _meaning(font)
    order = list(meaning.keys())
    steps = [
        {"key": key, "label": label}
        for key, label in display_from_meaning(meaning)
        if key != colornames.NO_COLOR
    ]
    glyph_total = len(font.glyphs)
    # Font order, glyphOrder parameter included: reading Glyphs' default order would
    # mean flipping that parameter, which re-sorts Glyphs' sidebar under its counts.
    glyph_names = list(current[font.masters[0].id].keys()) if font.masters else []

    previews = _master_previews(font)
    masters = []
    for master in font.masters:
        per_glyph = current.get(master.id, {})
        colors = snapshot_to_colors(per_glyph)
        masters.append(
            {
                "id": master.id,
                "name": master.name,
                "keys": [per_glyph.get(name, colornames.NO_COLOR) for name in glyph_names],
                "counts": master_counts(colors, order),
                "uncolored": uncolored_count(colors, order),
                "preview": previews.get(master.id, {}),
            }
        )

    # One history log, from one store: a git-tracked font reads its commits only (any
    # history left in its userData is ignored), any other font its own per-save log.
    # The day timeline keeps each day's last point; today folds in the live state.
    today = now.strftime("%Y-%m-%d")
    log = load_history(font) if git_commits is None else git_commits
    day_history = group_saves_by_date(log)
    history = {**day_history, today: current}
    series = history_series(history, order)
    dates = [point["date"] for point in series]
    trend = {
        "series": series,
        "dates": dates,
        "today": today,
    }
    journey_index = build_journey_index(history, dates)
    # Where the history comes from, for the seed card's wording.
    fine_kind = ("save" if git_commits is None else "commit") if log else None

    meta = glyph_meta(font)
    metas = [meta.get(name, {}) for name in glyph_names]
    categories = [(entry.get("category") or "Other") for entry in metas]
    scripts = [(entry.get("script") or "Other") for entry in metas]

    if progress is not None:
        try:
            progress(1.0)
        except Exception:
            pass

    return {
        "family": font.familyName or "",
        "fileName": Path(font.filepath).name if font.filepath else (font.familyName or "Untitled"),
        "version": f"{font.versionMajor}.{font.versionMinor:03d}",
        "generated": now.strftime("%Y-%m-%d"),
        "glyphTotal": glyph_total,
        "order": order,
        "steps": steps,
        "noneLabel": colornames.NO_COLOR_LABEL,
        "glyphNames": glyph_names,
        "categories": categories,
        "scripts": scripts,
        # Parity invariant: masters[].counts/keys above ship ALL glyphs (raw
        # truth — the heatmap needs them to render the dimmed cells); the report
        # ALWAYS applies this exclusion client-side to every percentage.
        "nonExporting": non_exporting_names(font),
        "masters": masters,
        "colors": {
            str(index): _hex(rgba) for index, rgba in enumerate(labelcolors.read_label_colors())
        },
        "filePath": font.filepath or "",
        "logo": _family_logo(font),
        "trend": trend,
        "journeyIndex": journey_index,
        "fineKind": fine_kind,  # "commit" | "save" | None
        "lastEdit": glyph_last_edit(font, now),
        "coverage": build_coverage(font, current, order),
        "changes": compute_changes(current, previous),
        "crossMaster": cross_master_summary(
            current, [master.id for master in font.masters], glyph_names, order
        ),
    }


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def report_path_for(font, when=None) -> Path | None:
    """Deterministic output path for ``font``'s report (temp dir, keyed by the font
    name + date): the path :func:`main` writes. ``None`` when there is no font."""
    if font is None:
        return None
    when = when or datetime.now()
    base = Path(font.filepath).stem if font.filepath else (font.familyName or "font")
    base = re.sub(r"[/\\:]+", "-", base)  # family names may contain path separators
    return Path(tempfile.gettempdir()) / f"{when.strftime('%Y%m%d')} {base} — AZ Colorflow.html"


def build_report_model(font=None, progress=None) -> tuple[dict, dict] | None:
    """The data half of :func:`main`: the report model for ``font`` plus the live
    color snapshot the caller persists via :func:`save_snapshot`. ``progress``
    receives 0 -> 0.80 like ``main``.
    ``None`` when there is no font / no glyphs (after a Message)."""

    def _emit(frac: float) -> None:
        if progress is not None:
            try:
                progress(frac)
            except Exception:
                pass

    if font is None and Glyphs is not None:
        font = Glyphs.font
    if font is None:
        Message("Open a font first.", "Color Font Dashboard")
        return None
    total = len(font.glyphs)
    if total == 0:
        Message("No glyphs to report on.", "Color Font Dashboard")
        return None

    _emit(0.02)
    now = datetime.now()
    current = build_master_glyph_colors(font)
    _emit(0.05)
    # ONE git pass per report, shared by both timelines (None when not in git).
    git_commits = collect_report_git_commits(font, progress=lambda frac: _emit(0.05 + 0.10 * frac))
    _emit(0.15)
    previous = load_snapshot(font) or current
    model = build_model(
        font,
        now,
        current,
        previous,
        progress=lambda frac: _emit(0.15 + 0.65 * frac),
        git_commits=git_commits,
    )
    _emit(0.80)
    return model, current


def main(font=None, progress=None, open_when_done: bool = True) -> Path | None:
    """Build the report, write it to a temp file, and (when ``open_when_done``)
    open it in the browser. ``progress`` (optional ``Callable[[float], None]``)
    receives a monotonic 0->1 fraction at each phase boundary so a caller can drive
    a determinate loading bar. Returns the written ``Path`` (so a caller can offer
    Open/Save itself), or ``None`` if nothing was produced."""

    def _emit(frac: float) -> None:
        if progress is not None:
            try:
                progress(frac)
            except Exception:
                pass

    if font is None and Glyphs is not None:
        font = Glyphs.font
    built = build_report_model(font, progress)
    if built is None or font is None:
        return None
    model, current = built
    now = datetime.now()
    html = azcolorflow_assets.build_html(model)
    _emit(0.94)
    save_snapshot(font, current)
    # Note: today's snapshot is NOT persisted here — generating a report must not modify
    # the font. The plugin records it into userData on save (a will-save hook); the
    # report still shows today via the in-memory fold above.
    _emit(0.96)

    out_path = cast(Path, report_path_for(font, now))  # None only without a font
    try:
        out_path.write_text(html, encoding="utf-8")
    except OSError as error:
        Message(f"Could not write the dashboard:\n{error}", "Color Font Dashboard")
        return None
    _emit(0.98)
    if open_when_done:
        webbrowser.open(out_path.as_uri())
    _emit(1.0)
    return out_path
