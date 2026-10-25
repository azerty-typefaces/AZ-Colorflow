"""The color wheel's pure logic: which steps it shows, where they sit, which one the
cursor points at, and the click chords that open it. No AppKit, so it tests with
plain CPython.

Geometry is in points, y up (AppKit's unflipped space): slot 0 sits at 12 o'clock
and the steps run clockwise, so the wheel reads in step order like a clock.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import colornames

# Mirrors of AppKit.NSEventModifierFlag*, so this module imports without AppKit.
MOD_SHIFT = 1 << 17
MOD_CONTROL = 1 << 18
MOD_OPTION = 1 << 19
MOD_COMMAND = 1 << 20
RELEVANT_MODIFIERS = MOD_SHIFT | MOD_CONTROL | MOD_OPTION | MOD_COMMAND

# NSEventType values of the mouse-down events a trigger can be.
EVENT_LEFT_MOUSE_DOWN = 1
EVENT_RIGHT_MOUSE_DOWN = 3
EVENT_OTHER_MOUSE_DOWN = 25
# NSEvent.buttonNumber() of the middle button; side buttons (3+) never trigger.
MIDDLE_BUTTON = 2

# Hardware key codes for 0-9, top row and keypad, as AZ Keyring reads them: layout-
# independent, so AZERTY's top row picks a step without Shift.
_TOP_ROW_DIGITS = (29, 18, 19, 20, 21, 23, 22, 26, 28, 25)
_KEYPAD_DIGITS = (82, 83, 84, 85, 86, 87, 88, 89, 91, 92)
_DELETE_KEYS = (51, 117)  # ⌫ and ⌦


class Trigger(NamedTuple):
    button: str
    modifiers: int


# The modifiers a chord can hold, in Settings order: (name in the stored key, flag,
# symbol). Not ⇧: while the wheel is open it means "every master".
CHORD_MODIFIERS = (
    ("control", MOD_CONTROL, "⌃"),
    ("option", MOD_OPTION, "⌥"),
    ("command", MOD_COMMAND, "⌘"),
)
# button -> (word that ends the stored key, Settings title)
CHORD_BUTTONS = {
    "left": ("click", "Left-click"),
    "right": ("right-click", "Right-click"),
    "middle": ("middle-click", "Middle-click"),
}
# AZ Keyring defaults to ⌃ + Click and ⌃⇧ + Click; chords match exactly, so no clash.
DEFAULT_TRIGGER = Trigger("left", MOD_CONTROL | MOD_OPTION)


def trigger_allowed(trigger: Trigger) -> bool:
    """False for a plain left click, which would take every click from Glyphs."""
    return trigger.button != "left" or bool(trigger.modifiers)


def trigger_key(trigger: Trigger) -> str:
    """How ``trigger`` is stored, e.g. ``"control-option-click"``."""
    names = [name for name, flag, _symbol in CHORD_MODIFIERS if trigger.modifiers & flag]
    return "-".join([*names, CHORD_BUTTONS[trigger.button][0]])


def trigger_for(key: object) -> Trigger:
    """The chord stored under ``key``; the default for anything unset, unknown or not
    allowed."""
    if not isinstance(key, str):
        return DEFAULT_TRIGGER
    flags = {name: flag for name, flag, _symbol in CHORD_MODIFIERS}
    for button in ("right", "middle", "left"):  # "-click" also ends the other two
        word = CHORD_BUTTONS[button][0]
        if key == word or key.endswith(f"-{word}"):
            names = key[: -len(word)].split("-")[:-1]
            if not all(name in flags for name in names):
                return DEFAULT_TRIGGER
            trigger = Trigger(button, sum(flags[name] for name in set(names)))
            return trigger if trigger_allowed(trigger) else DEFAULT_TRIGGER
    return DEFAULT_TRIGGER


def describe(trigger: Trigger) -> str:
    """``trigger`` as the Settings button shows it, e.g. ``"⌃ + ⌥ + Left-click"``."""
    symbols = [symbol for _name, flag, symbol in CHORD_MODIFIERS if trigger.modifiers & flag]
    return " + ".join([*symbols, CHORD_BUTTONS[trigger.button][1]])


def recorded_trigger(event_type: int, button_number: int, modifier_flags: int) -> Trigger | None:
    """The chord a click recorded in Settings makes; ``None`` for a side button, a click
    with ⇧ held, or a plain left click."""
    button = mouse_button(event_type, button_number)
    if button is None or modifier_flags & MOD_SHIFT:
        return None
    trigger = Trigger(button, modifier_flags & RELEVANT_MODIFIERS)
    return trigger if trigger_allowed(trigger) else None


def mouse_button(event_type: int, button_number: int) -> str | None:
    """``"left"``, ``"right"`` or ``"middle"`` for a mouse-down event, else ``None``."""
    if event_type == EVENT_LEFT_MOUSE_DOWN:
        return "left"
    if event_type == EVENT_RIGHT_MOUSE_DOWN:
        return "right"
    if event_type == EVENT_OTHER_MOUSE_DOWN and button_number == MIDDLE_BUTTON:
        return "middle"
    return None


def trigger_matches(trigger: Trigger, button: str | None, modifier_flags: int) -> bool:
    """True when a mouse-down of ``button`` with exactly these modifiers opens the wheel."""
    if button != trigger.button:
        return False
    return int(modifier_flags) & RELEVANT_MODIFIERS == trigger.modifiers


def wheel_slots(steps: dict[int, str]) -> list[int]:
    """The wheel's color keys: the :func:`colornames.shown_steps` in step order, then
    No Color."""
    return [*steps, colornames.NO_COLOR]


def ring_radius(count: int, pitch: float, minimum: float) -> float:
    """Radius that puts ``count`` slots ``pitch`` points apart, never under ``minimum``."""
    return max(minimum, count * pitch / (2.0 * math.pi))


def slot_offset(index: int, count: int, radius: float) -> tuple[float, float]:
    """Center of slot ``index`` relative to the wheel's center."""
    angle = math.radians(90.0 - index * 360.0 / count)
    return radius * math.cos(angle), radius * math.sin(angle)


def wedge_span(index: int, count: int) -> tuple[float, float]:
    """Slot ``index``'s wedge as AppKit angles in degrees (counterclockwise from 3
    o'clock), start < end, centered on the slot: the wedges tile the ring and each covers
    exactly the directions :func:`hit_test` gives its slot."""
    middle = 90.0 - index * 360.0 / count
    half = 180.0 / count
    return middle - half, middle + half


def gap_degrees(gap: float, radius: float) -> float:
    """The angle to trim off a wedge's edge at ``radius`` so the gap between two wedges
    is ``gap`` points wide all the way across, not a wedge-shaped crack."""
    return math.degrees(math.asin(min(1.0, gap / 2.0 / radius)))


def wedge_arcs(
    index: int, count: int, inner: float, outer: float, gap: float, corner: float
) -> list[tuple[float, float, float, float, float, bool]]:
    """Slot ``index``'s wedge between radii ``inner`` and ``outer``, as arcs to join in
    order (straight sides fill the breaks), each ``(center_x, center_y, radius,
    from_deg, to_deg, clockwise)`` about the wheel's center. The sides keep ``gap``
    between neighbours; ``corner`` rounds the four corners, shrunk to what fits."""
    start, end = wedge_span(index, count)
    half = math.radians(end - start) / 2.0
    limit = (outer - inner) / 2.0
    if half < math.pi / 2.0:  # a narrow wedge: its two corners on an arc must not meet
        sine = math.sin(half)
        limit = min(limit, (outer * sine - gap / 2.0) / (1.0 + sine))
        limit = min(limit, (inner * sine - gap / 2.0) / (1.0 - sine))
    corner = max(0.0, min(corner, limit))
    # Each corner circle touches its arc and sits gap / 2 + corner off the wedge's edge.
    trim_out = gap_degrees(gap + 2.0 * corner, outer - corner)
    trim_in = gap_degrees(gap + 2.0 * corner, inner + corner)

    def at(distance: float, angle: float) -> tuple[float, float]:
        return distance * math.cos(math.radians(angle)), distance * math.sin(math.radians(angle))

    arcs = [
        (0.0, 0.0, outer, start + trim_out, end - trim_out, False),
        (*at(outer - corner, end - trim_out), corner, end - trim_out, end + 90.0, False),
        (*at(inner + corner, end - trim_in), corner, end + 90.0, end - trim_in + 180.0, False),
        (0.0, 0.0, inner, end - trim_in, start + trim_in, True),
        (
            *at(inner + corner, start + trim_in),
            corner,
            start + trim_in + 180.0,
            start + 270.0,
            False,
        ),
        (*at(outer - corner, start + trim_out), corner, start - 90.0, start + trim_out, False),
    ]
    return [arc for arc in arcs if arc[2] > 0.0]


def hit_test(dx: float, dy: float, dead_zone: float, count: int) -> int | None:
    """The slot whose direction the offset ``(dx, dy)`` points to, or ``None`` inside
    the dead zone. Reach is unlimited, so a fast flick past the ring still lands."""
    if count <= 0 or math.hypot(dx, dy) < dead_zone:
        return None
    clockwise_from_top = (90.0 - math.degrees(math.atan2(dy, dx))) % 360.0
    return round(clockwise_from_top * count / 360.0) % count


def ease_out(elapsed: float, duration: float) -> float:
    """Cubic ease-out of a fade ``elapsed`` seconds in: 0 until it starts, 1 once done."""
    progress = min(1.0, max(0.0, elapsed / duration))
    return 1.0 - (1.0 - progress) ** 3


def focus_levels(start: list[float], hot: int | None, count: int, progress: float) -> list[float]:
    """Each slot's focus ``progress`` (0 to 1) of the way from ``start`` (none when empty)
    to its target: 1 for the hot slot, 0 for the rest."""
    targets = [1.0 if index == hot else 0.0 for index in range(count)]
    start = start or [0.0] * count
    return [was + (target - was) * progress for was, target in zip(start, targets, strict=True)]


def slot_for_key(key_code: int, count: int) -> int | None:
    """The slot a key picks on a ``count``-slot wheel: 1-9 then 0 the first ten steps,
    ⌫ or ⌦ No Color (always the last slot); ``None`` for any other key."""
    if count <= 0:
        return None
    if key_code in _DELETE_KEYS:
        return count - 1
    for codes in (_TOP_ROW_DIGITS, _KEYPAD_DIGITS):
        if key_code in codes:
            index = (codes.index(key_code) or 10) - 1
            return index if index < count - 1 else None
    return None


def key_hint(index: int, count: int) -> str | None:
    """The key :func:`slot_for_key` maps to slot ``index``, for the name pill."""
    if index == count - 1:
        return "⌫"
    return str((index + 1) % 10) if index < 10 else None
