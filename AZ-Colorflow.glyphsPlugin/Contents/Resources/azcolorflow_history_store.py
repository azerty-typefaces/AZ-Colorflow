"""Compact, file-embeddable encoding of Color Flow's per-save color history.

The history — ``{stamp: {master_id: {glyph_name: int}}}`` — is the substrate for the
report's timeline. It is stored in the font's ``userData`` so a shared file shows the
same timeline on any machine, which makes its size part of every save of the font.

Payload (v3): ``"~" + base85(raw LZMA2(body + crc32(body)))``. The body holds three
string tables (save stamps oldest-first, master ids, glyph names) and the color values,
then, for every save and every master, only the layers that changed since the last save:

- counts: ``varint(changed * 2 + master appeared/disappeared)``
- gaps: ``varint(name index - previous changed index - 1)`` per changed layer
- colors: ``varint(rank)`` of the new color among the colors that have followed the
  layer's old color so far, most frequent first, so a usual workflow step costs ~nothing

Every master is absent before the first save, so the first save is the base snapshot. A
glyph missing from a master has the extra color index ``len(values)``. Glyph names take
the newest save's order (the font's glyph order): designers color runs of neighbouring
glyphs, and neighbours give zero gaps. Glyphs writes base85's characters into the file
unescaped, and it is denser than base64.

:func:`decode_history` also reads the base64 payloads of earlier builds: xz/gzip JSON
holding the delta model (v2) or the dense dict (v1).

This module is pure (no Glyphs) so the codec is unit-tested in isolation.
"""

from __future__ import annotations

import base64
import gzip
import json
import lzma
import zlib

History = dict[str, dict[str, dict[str, int]]]

SCHEMA_VERSION = 1  # legacy dense payload {"v":1,"h":history} (still decoded)
DELTA_VERSION = 2  # legacy delta payload (still decoded, see _from_delta)
PACKED_MARK = "~"  # starts a v3 payload; outside the base64 alphabet, so never a v1/v2 one

# Raw LZMA2 has no header: the decoder needs the encoder's settings. Preset 6 packs this
# data as small as preset 9 with a fraction of the encoder memory.
_LZMA2 = [{"id": lzma.FILTER_LZMA2, "preset": 6}]


class HistoryDecodeError(ValueError):
    """A history payload was *present* but could not be decoded.

    Deliberately distinct from empty/missing input (which decodes to ``{}``): a
    caller that gets ``{}`` back may safely write a fresh log, but on this error it
    must preserve the raw payload (e.g. stash it under a backup key) before any
    overwrite — otherwise one bad read silently destroys the font's timeline."""


_GZIP_MAGIC = b"\x1f\x8b"
_XZ_MAGIC = b"\xfd7zXZ\x00"


# --------------------------------------------------------------------------- #
# Packed v3 payload (see the module docstring).
# --------------------------------------------------------------------------- #


def _put(out: bytearray, value: int) -> None:
    """Append a non-negative int as a LEB128 varint."""
    while value >= 0x80:
        out.append(value & 0x7F | 0x80)
        value >>= 7
    out.append(value)


def _put_strings(out: bytearray, strings: list[str]) -> None:
    _put(out, len(strings))
    for string in strings:
        raw = string.encode("utf-8")
        _put(out, len(raw))
        out += raw


class _Reader:
    """Reads varints and string tables off one byte stream, in order."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def varint(self) -> int:
        value = shift = 0
        while True:
            byte = self.data[self.pos]
            self.pos += 1
            value |= (byte & 0x7F) << shift
            if byte < 0x80:
                return value
            shift += 7

    def take(self, size: int) -> bytes:
        chunk = self.data[self.pos : self.pos + size]
        self.pos += size
        return chunk

    def strings(self) -> list[str]:
        return [self.take(self.varint()).decode("utf-8") for _ in range(self.varint())]

    def done(self) -> bool:
        return self.pos == len(self.data)


class _ColorRanks:
    """For each old color, the new colors ranked by how often they have followed it.
    Encoder and decoder update it identically, so no table is stored."""

    def __init__(self, size: int) -> None:
        self.order = [list(range(size)) for _ in range(size)]
        self.hits = [[0] * size for _ in range(size)]

    def _bump(self, old: int, new: int, position: int) -> None:
        order, hits = self.order[old], self.hits[old]
        hits[new] += 1
        while position and hits[order[position - 1]] < hits[new]:
            order[position] = order[position - 1]
            position -= 1
        order[position] = new

    def rank(self, old: int, new: int) -> int:
        position = self.order[old].index(new)
        self._bump(old, new, position)
        return position

    def color(self, old: int, rank: int) -> int:
        new = self.order[old][rank]
        self._bump(old, new, rank)
        return new


def _seal(body: bytes) -> str:
    checked = body + zlib.crc32(body).to_bytes(4, "big")
    blob = lzma.compress(checked, format=lzma.FORMAT_RAW, filters=_LZMA2)
    return PACKED_MARK + base64.b85encode(blob).decode("ascii")


def _unseal(text: str) -> bytes:
    blob = base64.b85decode(text[len(PACKED_MARK) :])
    checked = lzma.decompress(blob, format=lzma.FORMAT_RAW, filters=_LZMA2)
    body = checked[:-4]
    if zlib.crc32(body).to_bytes(4, "big") != checked[-4:]:
        raise ValueError("checksum mismatch")
    return body


def encode_history(history: History) -> str:
    """Encode ``history`` to a compact v3 string for ``userData``. Deterministic, so
    re-encoding an unchanged history doesn't re-dirty the font."""
    stamps = sorted(history)
    newest_first = [history[stamp] for stamp in reversed(stamps)]
    masters = list(dict.fromkeys(master for snapshot in newest_first for master in snapshot))
    names = list(
        dict.fromkeys(
            name for snapshot in newest_first for glyphs in snapshot.values() for name in glyphs
        )
    )
    values = sorted(
        {
            key
            for snapshot in newest_first
            for glyphs in snapshot.values()
            for key in glyphs.values()
        }
    )
    name_index = {name: i for i, name in enumerate(names)}
    value_index = {value: i for i, value in enumerate(values)}
    absent = len(values)
    ranks = _ColorRanks(absent + 1)
    counts, gaps, colors = bytearray(), bytearray(), bytearray()
    previous: list[dict[str, int] | None] = [None] * len(masters)
    for stamp in stamps:
        for i, master in enumerate(masters):
            glyphs, before = history[stamp].get(master), previous[i]
            previous[i] = glyphs
            toggled = int((glyphs is None) != (before is None))
            if glyphs is None:
                _put(counts, toggled)
                continue
            before = before or {}
            changed = sorted(
                [name_index[name] for name, key in glyphs.items() if before.get(name) != key]
                + [name_index[name] for name in before.keys() - glyphs.keys()]
            )
            _put(counts, len(changed) * 2 + toggled)
            last = -1
            for index in changed:
                name = names[index]
                old = value_index[before[name]] if name in before else absent
                new = value_index[glyphs[name]] if name in glyphs else absent
                _put(gaps, index - last - 1)
                _put(colors, ranks.rank(old, new))
                last = index
    body = bytearray()
    for table in (stamps, masters, names):
        _put_strings(body, table)
    _put(body, len(values))
    for value in values:
        _put(body, value * 2 if value >= 0 else -value * 2 - 1)  # zigzag
    for stream in (counts, gaps):
        _put(body, len(stream))
        body += stream
    body += colors
    return _seal(bytes(body))


def _decode_packed(text: str) -> History:
    head = _Reader(_unseal(text))
    stamps, masters, names = head.strings(), head.strings(), head.strings()
    values = [(zig >> 1) ^ -(zig & 1) for zig in (head.varint() for _ in range(head.varint()))]
    counts = _Reader(head.take(head.varint()))
    gaps = _Reader(head.take(head.varint()))
    colors = _Reader(head.take(len(head.data) - head.pos))
    value_index = {value: i for i, value in enumerate(values)}
    absent = len(values)
    ranks = _ColorRanks(absent + 1)
    state: list[dict[str, int] | None] = [None] * len(masters)
    history: History = {}
    for stamp in stamps:
        for i in range(len(masters)):
            packed = counts.varint()
            if packed & 1:
                state[i] = {} if state[i] is None else None
            glyphs = state[i]
            if glyphs is None:
                continue
            index = -1
            for _ in range(packed >> 1):
                index += gaps.varint() + 1
                name = names[index]
                old = value_index[glyphs[name]] if name in glyphs else absent
                new = ranks.color(old, colors.varint())
                if new == absent:
                    del glyphs[name]
                else:
                    glyphs[name] = values[new]
        history[stamp] = {
            master: dict(glyphs)
            for master, glyphs in zip(masters, state, strict=True)
            if glyphs is not None
        }
    if not (counts.done() and gaps.done() and colors.done()):
        raise ValueError("payload streams don't line up")
    return history


# --------------------------------------------------------------------------- #
# Legacy v2 delta model: {"v":2, "dates":[iso...], "base":snapshot, "steps":{iso:step}}.
# ``base`` is the full snapshot at dates[0]. Each later date carries a ``step``:
#   "s":  {master: {glyph: key}}  changed-or-added glyphs (and whole new masters)
#   "d":  {master: [glyph, ...]}  glyphs removed from a surviving master
#   "dm": [master, ...]           masters removed entirely
# Empty members are omitted. Reconstruct by forward-filling base through the steps.
# --------------------------------------------------------------------------- #


def _decompress(blob: bytes) -> bytes:
    """Inflate a v1/v2 payload, gzip or xz, told apart by their magic bytes."""
    if blob[:2] == _GZIP_MAGIC:
        return gzip.decompress(blob)
    if blob[:6] == _XZ_MAGIC:
        return lzma.decompress(blob)
    raise ValueError("unrecognised compression header")


def _from_delta(model: dict) -> History:
    dates = model.get("dates")
    if not isinstance(dates, list) or not dates:
        return {}
    state: dict[str, dict[str, int]] = {}
    base = model.get("base")
    if isinstance(base, dict):
        for master, glyphs in base.items():
            if isinstance(glyphs, dict):
                state[str(master)] = {str(n): int(k) for n, k in glyphs.items()}
    out: History = {str(dates[0]): {m: dict(g) for m, g in state.items()}}
    steps = model.get("steps")
    steps = steps if isinstance(steps, dict) else {}
    for date in dates[1:]:
        step = steps.get(date)
        step = step if isinstance(step, dict) else {}
        for master in step.get("dm", []) or []:
            state.pop(str(master), None)
        for master, glyphs in (step.get("s") or {}).items():
            if isinstance(glyphs, dict):
                target = state.setdefault(str(master), {})
                for name, key in glyphs.items():
                    target[str(name)] = int(key)
        for master, names in (step.get("d") or {}).items():
            target = state.get(str(master))
            if target is not None:
                for name in names:
                    target.pop(str(name), None)
        out[str(date)] = {m: dict(g) for m, g in state.items()}
    return out


# --------------------------------------------------------------------------- #
# Public codec
# --------------------------------------------------------------------------- #


def decode_history(text: object) -> History:
    """Decode a string produced by :func:`encode_history` back to the history dict.

    Also reads the v2 delta and v1 dense payloads of earlier builds. Returns ``{}`` for
    empty/missing input, and coerces every value to plain ``str``/``int`` so a value
    read back from ``userData`` (which may be an ``NSString``/``NSDictionary``) behaves
    like a normal Python dict.

    Raises :class:`HistoryDecodeError` when a payload is present but undecodable
    (corrupt or truncated data, malformed JSON, unknown schema) — so callers can tell
    "no data" from "data I must not clobber"."""
    if not text:
        return {}
    text = str(text)
    try:
        if text.startswith(PACKED_MARK):
            return _decode_packed(text)
        decoded = json.loads(_decompress(base64.b64decode(text)).decode("utf-8"))
    except Exception as error:
        raise HistoryDecodeError(f"undecodable history payload: {error}") from error
    if not isinstance(decoded, dict):
        raise HistoryDecodeError("history payload is not a mapping")
    version = decoded.get("v")
    if version == DELTA_VERSION:
        try:
            return _from_delta(decoded)
        except Exception as error:
            raise HistoryDecodeError(f"malformed delta payload: {error}") from error
    if version == SCHEMA_VERSION:
        return _coerce_dense(decoded.get("h"))
    raise HistoryDecodeError(f"unknown history schema version: {version!r}")


def _coerce_dense(history: object) -> History:
    """Coerce a legacy (v1) dense ``{date:{master:{glyph:int}}}`` to plain types."""
    if not isinstance(history, dict):
        return {}
    out: History = {}
    for date, masters in history.items():
        if not isinstance(masters, dict):
            continue
        per_master: dict[str, dict[str, int]] = {}
        for master_id, glyphs in masters.items():
            if not isinstance(glyphs, dict):
                continue
            try:
                per_master[str(master_id)] = {str(name): int(key) for name, key in glyphs.items()}
            except (TypeError, ValueError):
                continue
        out[str(date)] = per_master
    return out
