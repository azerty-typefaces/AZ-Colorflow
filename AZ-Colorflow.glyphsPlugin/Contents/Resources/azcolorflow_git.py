"""Reconstruct Color Flow's dated history from a font's git commits.

Color Flow normally accrues one snapshot per day, only on the days the report is
run — so a fresh install has no timeline. When the font lives in a git repo we can
backfill that history: for each past day, check out that day's last commit of the
font, read its per-master ``layer.color`` state, and synthesise the exact same
``{iso_date: {master_id: {glyph_name: key}}}`` shape the live snapshots use. Every
downstream journey function then works unchanged.

This module is the import-clean, fully unit-tested plumbing: it shells out to git
and extracts historical file content, but the font-reading step is injected as a
``load_colors`` callable so the orchestration is testable without Glyphs. The Glyphs
side (open a historical font headlessly, run ``build_master_glyph_colors``) lives in
``azcolorflow_dashboard`` where GlyphsApp is already imported.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path

# Every git-history path is bounded to the most-recent `DEFAULT_CAP` points (days or
# commits) unless the caller passes another positive cap explicitly — each point costs
# a headless font open, so an unbounded ancient repo must not stall a report run.
# When capping actually drops history a notice is printed (see _note_truncation).
DEFAULT_CAP = 300

# Hard ceiling for one git subprocess. These run on Glyphs' main thread; a stalled
# git (fs hiccup, credential prompt, huge pack) must fail fast, not freeze the app.
_GIT_TIMEOUT = 10

# One per-master color snapshot: {master_id: {glyph_name: key}}.
Snapshot = dict[str, dict[str, int]]


def _note_truncation(kind: str, cap: int, dropped: int) -> None:
    """Make a cap that actually drops history visible (Macro window / test capture)
    instead of silently truncating the timeline."""
    print(
        f"Color Flow: git history capped to the {cap} most recent {kind} "
        f"({dropped} older {kind} skipped)."
    )


def _git_text(args: list[str], cwd: Path) -> str | None:
    """Run ``git <args>`` in ``cwd`` and return stdout as text, or ``None`` if git
    is missing, times out, or the command fails (non-zero exit)."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _git_bytes(args: list[str], cwd: Path) -> bytes | None:
    """Run ``git <args>`` in ``cwd`` and return stdout as raw bytes, or ``None`` on
    failure/timeout — used for blob/archive content that should not be text-decoded."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            check=False,
            timeout=_GIT_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def git_root(path: Path) -> Path | None:
    """The repository root containing ``path`` (a file or directory), or ``None`` if
    ``path`` is not inside a git working tree."""
    start = path if path.is_dir() else path.parent
    if not start.exists():
        return None
    out = _git_text(["rev-parse", "--show-toplevel"], start)
    if not out:
        return None
    root = out.strip()
    return Path(root) if root else None


def _rel(repo: Path, target: Path) -> str | None:
    """``target`` as a POSIX path relative to ``repo`` (git speaks forward slashes),
    or ``None`` when it can't be expressed relative to the repo — symlinked working
    copies or APFS case differences can make ``relative_to`` raise, and the git
    plumbing should then degrade gracefully instead of blowing up the backfill."""
    try:
        return target.resolve().relative_to(repo.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def is_tracked(repo: Path, target: Path) -> bool:
    """Whether ``target`` (a file or a ``.glyphspackage`` directory) is tracked in
    ``repo`` — true when git lists at least one file at that path."""
    rel = _rel(repo, target)
    if rel is None:
        return False
    out = _git_text(["ls-files", "--", rel], repo)
    return bool(out and out.strip())


def extract_commit(repo: Path, target: Path, sha: str, dest_dir: Path) -> Path | None:
    """Materialise ``target`` as it was at ``sha`` into ``dest_dir`` and return the
    path to the extracted font. Handles both a single ``.glyphs`` file (``git show``)
    and a ``.glyphspackage`` directory (``git archive`` -> in-memory tar extract).
    Returns ``None`` if the content can't be retrieved."""
    rel = _rel(repo, target)
    if rel is None:
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        data = _git_bytes(["archive", "--format=tar", sha, "--", rel], repo)
        if data is None:
            return None
        try:
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                archive.extractall(dest_dir)  # noqa: S202 - our own repo's tree
        except (tarfile.TarError, OSError):
            return None
        extracted = dest_dir / rel
        return extracted if extracted.exists() else None
    data = _git_bytes(["show", f"{sha}:{rel}"], repo)
    if data is None:
        return None
    out_path = dest_dir / Path(rel).name
    try:
        out_path.write_bytes(data)
    except OSError:
        return None
    return out_path


def commit_points(repo: Path, target: Path, cap: int = DEFAULT_CAP) -> list[tuple[str, str]]:
    """Every commit of ``target`` (first-parent), oldest-first, as ``(key, sha)``.

    Each commit is its own point, keyed by a sortable local datetime
    (``YYYY-MM-DDTHH:MM:SS``). At most ``cap`` most-recent commits are kept. Keys are
    made unique (commits within the same second get a ``.1``/``.2`` suffix) so they can
    index a snapshot dict and still sort lexicographically."""
    rel = _rel(repo, target)
    if rel is None:
        return []
    out = _git_text(
        [
            "log",
            "--first-parent",
            "--date=format-local:%Y-%m-%dT%H:%M:%S",
            "--format=%cd|%H",
            "--",
            rel,
        ],
        repo,
    )
    if not out:
        return []
    raw: list[tuple[str, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        when, sha = line.split("|", 1)
        if when and sha:
            raw.append((when, sha))
    raw.reverse()  # git log is newest-first -> oldest-first
    if cap and len(raw) > cap:
        _note_truncation("commits", cap, len(raw) - cap)
        raw = raw[-cap:]  # keep the most-recent `cap` commits
    counts: dict[str, int] = {}
    points: list[tuple[str, str]] = []
    for when, sha in raw:
        seen = counts.get(when, 0)
        counts[when] = seen + 1
        key = when if seen == 0 else f"{when}.{seen}"
        points.append((key, sha))
    return points


def _collect_snapshots(
    repo: Path,
    target: Path,
    load_colors: Callable[[Path], Snapshot | None],
    points: list[tuple[str, str]],
    progress: Callable[[float], None] | None,
) -> dict[str, Snapshot]:
    """Extract each ``(key, sha)`` point's font into a temp dir and load its snapshot,
    returning ``{key: snapshot}``. Points that fail to extract or load are skipped."""
    history: dict[str, Snapshot] = {}
    if not points:
        return history
    work_root = Path(tempfile.mkdtemp(prefix="cfgit-"))
    try:
        for index, (key, sha) in enumerate(points):
            sub = work_root / sha[:12]
            extracted = extract_commit(repo, target, sha, sub)
            if extracted is not None:
                try:
                    colors = load_colors(extracted)
                except Exception:  # noqa: BLE001 - one bad commit must not abort the rest
                    colors = None
                if colors:
                    history[key] = colors
            if progress is not None:
                try:
                    progress((index + 1) / len(points))
                except Exception:  # noqa: BLE001 - progress is best-effort
                    pass
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
    return history


def collect_commit_history(
    font_path: str | Path,
    load_colors: Callable[[Path], Snapshot | None],
    cap: int = DEFAULT_CAP,
    progress: Callable[[float], None] | None = None,
    cache: dict[str, Snapshot] | None = None,
) -> dict[str, Snapshot]:
    """Reconstruct ``{commit_datetime: snapshot}`` from EVERY commit of ``font_path``
    (not collapsed to one per day, capped to the ``cap`` most-recent commits) — the
    substrate for the timeline's per-commit view. ``cache`` (``{sha: snapshot}``,
    updated in place) makes it incremental: a cached commit is never opened again, and
    commits no longer in the history (amended, rebased away, past the cap) are dropped
    from it. Returns ``{}`` when the path is not in a git repo or not tracked."""
    target = Path(font_path)
    repo = git_root(target)
    if repo is None or not is_tracked(repo, target):
        return {}
    points = commit_points(repo, target, cap)
    if cache is None:
        return _collect_snapshots(repo, target, load_colors, points, progress)
    if not points:
        return {}  # git hiccup: keep the cache rather than wipe it
    missing = [(sha, sha) for _key, sha in points if sha not in cache]
    cache.update(_collect_snapshots(repo, target, load_colors, missing, progress))
    wanted = {sha for _key, sha in points}
    for sha in [sha for sha in cache if sha not in wanted]:
        del cache[sha]
    return {key: cache[sha] for key, sha in points if sha in cache}
