# pyright: reportUndefinedVariable=false
# The star-imported names only exist inside Glyphs; pyright can't see them.


# AZ Colorflow: a color-label workflow for Glyphs 4.
# Docs: https://github.com/azerty-typefaces/AZ-Colorflow

from __future__ import annotations

import colorsys
import os
import shutil
import time
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import AppKit

import azcolorflow_census
import azcolorflow_dashboard
import azcolorflow_wheel
import colornames
import fontview
import labelcolors
import objc
from Foundation import NSDate, NSNotificationCenter, NSObject, NSRunLoop, NSRunLoopCommonModes

try:
    import WebKit
except ImportError:  # the HTML report then opens in the browser
    WebKit: Any = None

# Order matters: GlyphsApp's names must win over vanilla's.
from vanilla import *
from GlyphsApp.plugins import *
from GlyphsApp.UI import *
from GlyphsApp import *

# GlyphsApp.UI's Button is a title-first factory; the pane uses vanilla's.
from vanilla import Button


def _report(where: str) -> None:
    """Print the current exception to the Macro panel, tagged with where it happened."""
    print(f"AZ Colorflow [{where}] error:\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------- #
#  Glyphs 4 Font-view left sidebar: a color bar under each of Glyphs' own rows
# ---------------------------------------------------------------------------- #
# Glyphs has no sidebar API: these ride on its own outline view.
_FONTVIEW_BARS_KEY = "com.hugojourdan.ColorFlow.fontViewRowBars"
_FONTVIEW_LEGEND_KEY = "com.hugojourdan.ColorFlow.fontViewLegend"
_FONTVIEW_INSTALLER = None
_ROW_BARS_TAG = "AZColorflowRowBars"  # associated-object key on Glyphs' outline view
_ROW_CELL_ID = "ImageTextCell"  # Glyphs' sidebar row cell: [icon, name, count] stack
_ROW_BAR_TAG = "AZColorflowRowBar"  # associated-object key on such a cell
_ROW_BAR_GROW = 2.5  # extra row height that makes room for the bar
_ROW_BAR_H = 2.0
_ROW_BAR_BOTTOM = 2.0
_ROW_BAR_ALPHA = 0.9  # the bar's opacity, track and colors together
# Where Glyphs' counts end, so the bar stays inside the row's selection highlight.
_ROW_BAR_TRAILING_INSET = 13.0
# The compact option: the bar as a soft tint behind the row, in Glyphs' own row height.
_FONTVIEW_BARS_BEHIND_KEY = "com.hugojourdan.ColorFlow.fontViewRowBarsBehind"
_ROW_TINT_H = 19.0
_ROW_TINT_LEAD = 3.0  # starts just before the name, inside Glyphs' icon-name gap
_ROW_TINT_PAD_X = 5.0  # runs this far past the count
_ROW_TINT_ALPHA = 0.30  # a background: Glyphs' text stays the foreground on any label color
_ROW_HOOK_INSTALLED = False
_FV_LEGEND_INSET_X = 14.0
_FV_LEGEND_COLS = 2
_FV_LEGEND_ROW_H = 18.0  # a swatch + color name
_FV_LEGEND_TOP = 6.0  # hairline -> first swatch row
_FV_LEGEND_BOTTOM = 6.0
_FV_LEGEND_SWATCH = 13.0  # the size of Glyphs' own color buttons


def _row_bars_enabled() -> bool:
    """The Settings checkbox; on until switched off."""
    return bool(Glyphs.defaults.get(_FONTVIEW_BARS_KEY, True))


def _row_bars_behind() -> bool:
    """The compact option: bars behind each row's name instead of under it."""
    return bool(Glyphs.defaults[_FONTVIEW_BARS_BEHIND_KEY])


def _legend_enabled() -> bool:
    """The legend sub-option; on until switched off."""
    return bool(Glyphs.defaults.get(_FONTVIEW_LEGEND_KEY, True))


def _edge_to_sibling(root: Any, item: Any, attribute: Any, other_attribute: Any) -> tuple:
    """The constraint on ``root`` tying ``item``'s ``attribute`` to another view's
    ``other_attribute`` (either way round), and that view; ``(None, None)`` if none."""
    for constraint in root.constraints():
        ends = [
            (constraint.firstItem(), constraint.firstAttribute()),
            (constraint.secondItem(), constraint.secondAttribute()),
        ]
        for (near, near_attribute), (far, far_attribute) in (ends, ends[::-1]):
            if (
                near == item
                and near_attribute == attribute
                and far is not None
                and far_attribute == other_attribute
            ):
                return constraint, far
    return None, None


def _draw_row_bar(rect: Any, behind: bool, segs: Any, focus: Any) -> None:
    """One row's bar: ``segs`` is ``[(fraction, rgba, colorKey)]`` over a track, so an
    empty or partly filled bar still reads as a groove. Behind the name it is a faint
    tint instead. With a ``focus`` color key, every other color fades."""
    if behind:
        radius, track_color = 5.0, AppKit.NSColor.labelColor().colorWithAlphaComponent_(0.03)
    else:
        radius, track_color = rect.size.height / 2.0, AppKit.NSColor.tertiaryLabelColor()
    track = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius)
    context = AppKit.NSGraphicsContext.currentContext()
    context.saveGraphicsState()
    track_color.set()
    track.fill()
    track.addClip()  # rounds the outer corners; segments fill flat inside
    x = rect.origin.x
    for fraction, rgba, color_key in segs:
        width = fraction * rect.size.width
        if width <= 0.0:
            continue
        dim = focus is not None and color_key != focus
        if behind:
            alpha = _ROW_TINT_ALPHA * (0.25 if dim else 1.0)
        else:
            alpha = 0.16 if dim else 1.0
        AppKit.NSColor.colorWithDeviceRed_green_blue_alpha_(rgba[0], rgba[1], rgba[2], alpha).set()
        # +0.5 overlap so neighbouring segments leave no hairline seam.
        AppKit.NSBezierPath.bezierPathWithRect_(
            AppKit.NSMakeRect(x, rect.origin.y, width + 0.5, rect.size.height)
        ).fill()
        x += width
    context.restoreGraphicsState()


class _AZRowBarView(AppKit.NSView):
    """The thin color bar under one of Glyphs' sidebar rows. Clicks fall through
    to the row (NSView passes mouseDown up the responder chain)."""

    def initWithFrame_(self, frame: Any) -> Any:
        self = objc.super(_AZRowBarView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._segs = []
        self._on = False
        self._behind = False
        self._focus = None
        return self

    @objc.python_method
    def setSegments(self, segs: Any, tooltip: str) -> None:
        self._segs = segs
        self.setToolTip_(tooltip)
        self.setNeedsDisplay_(True)

    def drawRect_(self, dirtyRect: Any) -> None:
        _draw_row_bar(self.bounds(), self._behind, self._segs, self._focus)


class _AZFontViewLegendView(AppKit.NSView):
    """The color legend under Glyphs' Font-view list, lined up with its section
    titles. Clicking a color spotlights it in every bar; clicking it again clears."""

    def initWithFrame_(self, frame: Any) -> Any:
        self = objc.super(_AZFontViewLegendView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._entries = []
        self._focus = None
        self._cell_hits = []  # [(x0, x1, y0, y1, colorKey)]
        self._inset = None
        return self

    def isFlipped(self) -> bool:
        return True

    def acceptsFirstMouse_(self, event: Any) -> bool:
        return True

    @objc.python_method
    def set_entries(self, entries: list) -> None:
        self._entries = entries
        self.setNeedsDisplay_(True)

    @objc.python_method
    def content_height(self) -> float:
        rows = (len(self._entries) + _FV_LEGEND_COLS - 1) // _FV_LEGEND_COLS
        return _FV_LEGEND_TOP + rows * _FV_LEGEND_ROW_H + _FV_LEGEND_BOTTOM

    def drawRect_(self, dirtyRect: Any) -> None:
        self._cell_hits = []
        bounds = self.bounds()
        window = self.window()
        # One device pixel, like the separator Glyphs draws above its bottom bar.
        hairline = 1.0 / (window.backingScaleFactor() if window is not None else 2.0)
        AppKit.NSColor.separatorColor().set()
        AppKit.NSBezierPath.bezierPathWithRect_(
            AppKit.NSMakeRect(0.0, 0.0, bounds.size.width, hairline)
        ).fill()
        inset = self._inset or _FV_LEGEND_INSET_X
        col_w = (bounds.size.width - 2 * inset) / _FV_LEGEND_COLS
        style = AppKit.NSMutableParagraphStyle.alloc().init()
        style.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
        swatch_size = _FV_LEGEND_SWATCH
        for index, (rgba, name, color_key) in enumerate(self._entries):
            x = inset + (index % _FV_LEGEND_COLS) * col_w
            y = _FV_LEGEND_TOP + (index // _FV_LEGEND_COLS) * _FV_LEGEND_ROW_H
            dim = self._focus is not None and color_key != self._focus
            swatch = AppKit.NSMakeRect(
                x, y + (_FV_LEGEND_ROW_H - swatch_size) / 2.0, swatch_size, swatch_size
            )
            chip = AppKit.NSBezierPath.bezierPathWithOvalInRect_(swatch)
            AppKit.NSColor.colorWithDeviceRed_green_blue_alpha_(
                rgba[0], rgba[1], rgba[2], 0.22 if dim else 1.0
            ).set()
            chip.fill()
            name_color = AppKit.NSColor.tertiaryLabelColor() if dim else AppKit.NSColor.labelColor()
            attrs = {
                AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(11.5),
                AppKit.NSForegroundColorAttributeName: name_color,
                AppKit.NSParagraphStyleAttributeName: style,
            }
            AppKit.NSAttributedString.alloc().initWithString_attributes_(name, attrs).drawInRect_(
                AppKit.NSMakeRect(
                    x + swatch_size + 6.0,
                    y + (_FV_LEGEND_ROW_H - 14.0) / 2.0,
                    col_w - swatch_size - 10.0,
                    14.0,
                )
            )
            self._cell_hits.append((x, x + col_w, y, y + _FV_LEGEND_ROW_H, color_key))
        if window is not None:
            window.invalidateCursorRectsForView_(self)

    def resetCursorRects(self) -> None:
        hand = AppKit.NSCursor.pointingHandCursor()
        for x0, x1, y0, y1, _key in self._cell_hits:
            self.addCursorRect_cursor_(AppKit.NSMakeRect(x0, y0, x1 - x0, y1 - y0), hand)

    def mouseDown_(self, event: Any) -> None:
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        for x0, x1, y0, y1, color_key in self._cell_hits:
            if x0 <= point.x <= x1 and y0 <= point.y <= y1:
                owner = self._owner_ref()
                if owner is not None:
                    owner.focusColor_(str(color_key))
                return


def _row_bar(cell: Any, create: bool) -> Any:
    """The bar on one of Glyphs' sidebar cells, made on first use. None when the cell
    isn't the layout this was built for (a fixed height and a vertically centered stack)."""
    bar = objc.getAssociatedObject(cell, _ROW_BAR_TAG)
    if bar is not None or not create:
        return bar
    stack = next(
        (view for view in cell.subviews() if view.isKindOfClass_(AppKit.NSStackView)), None
    )
    label = cell.textField()
    height = center = None
    for constraint in cell.constraints():
        first, second = constraint.firstItem(), constraint.secondItem()
        if first == cell and second is None:
            if constraint.firstAttribute() == AppKit.NSLayoutAttributeHeight:
                height = constraint
        elif first == stack and second == cell:
            if constraint.firstAttribute() == AppKit.NSLayoutAttributeCenterY:
                center = constraint
    if stack is None or label is None or height is None or center is None:
        return None
    bar = _AZRowBarView.alloc().initWithFrame_(AppKit.NSZeroRect)
    bar.setTranslatesAutoresizingMaskIntoConstraints_(False)
    bar.setHidden_(True)
    cell.addSubview_positioned_relativeTo_(bar, AppKit.NSWindowBelow, stack)  # under the text
    bar._fit = (height, center, height.constant(), center.constant())
    bar._own = {  # keyed by "behind the name"
        False: [
            bar.leadingAnchor().constraintEqualToAnchor_(label.leadingAnchor()),
            bar.trailingAnchor().constraintEqualToAnchor_constant_(
                cell.trailingAnchor(), -_ROW_BAR_TRAILING_INSET
            ),
            bar.heightAnchor().constraintEqualToConstant_(_ROW_BAR_H),
            bar.bottomAnchor().constraintEqualToAnchor_constant_(
                cell.bottomAnchor(), -_ROW_BAR_BOTTOM
            ),
        ],
        True: [
            bar.leadingAnchor().constraintEqualToAnchor_constant_(
                label.leadingAnchor(), -_ROW_TINT_LEAD
            ),
            bar.trailingAnchor().constraintEqualToAnchor_constant_(
                cell.trailingAnchor(), _ROW_TINT_PAD_X - _ROW_BAR_TRAILING_INSET
            ),
            bar.heightAnchor().constraintEqualToConstant_(_ROW_TINT_H),
            bar.centerYAnchor().constraintEqualToAnchor_(cell.centerYAnchor()),
        ],
    }
    objc.setAssociatedObject(cell, _ROW_BAR_TAG, bar, objc.OBJC_ASSOCIATION_RETAIN)
    return bar


def _set_row_bar(cell: Any, show: bool, behind: bool) -> tuple[Any, bool]:
    """Show the cell's bar under its name (the cell grows) or behind it (Glyphs' own
    height), or undo exactly that. Returns the bar (None when there is none) and
    whether the cell's height changed."""
    bar = _row_bar(cell, create=show)
    if bar is None or (bar._on == show and (not show or bar._behind == behind)):
        return bar, False
    height, center, height0, center0 = bar._fit
    was_grown = bar._on and not bar._behind
    if bar._on:
        AppKit.NSLayoutConstraint.deactivateConstraints_(bar._own[bar._behind])
    grow = show and not behind
    # Glyphs centers the stack in the cell: lift it by half the growth so the name
    # stays exactly where Glyphs draws it and the bar takes the new bottom strip.
    height.setConstant_(height0 + _ROW_BAR_GROW if grow else height0)
    center.setConstant_(center0 - _ROW_BAR_GROW / 2.0 if grow else center0)
    if show:
        AppKit.NSLayoutConstraint.activateConstraints_(bar._own[behind])
    bar.setAlphaValue_(1.0 if behind else _ROW_BAR_ALPHA)
    bar.setHidden_(not show)
    bar._on, bar._behind = show, behind
    bar.setNeedsDisplay_(True)
    return bar, grow != was_grown


def _sidebar_row_added(self: Any, outline: Any, row_view: Any, row: int) -> None:
    """-[GSFontViewSidebarController outlineView:didAddRowView:forRow:], added by
    Colorflow (Glyphs doesn't implement it): every row Glyphs shows or reuses gets
    its bar, or loses it when the bars are off."""
    try:
        bars = objc.getAssociatedObject(outline, _ROW_BARS_TAG)
        if bars is not None:
            bars.rowAdded(row_view, row)
    except Exception:
        _report("Font-view row")


def _install_row_hook() -> bool:
    """Add the row hook to Glyphs' sidebar controller once. False when Glyphs
    implements that delegate method itself (never shadow it)."""
    global _ROW_HOOK_INSTALLED
    if _ROW_HOOK_INSTALLED:
        return True
    controller = objc.lookUpClass("GSFontViewSidebarController")
    if controller.instancesRespondToSelector_(b"outlineView:didAddRowView:forRow:"):
        return False
    objc.classAddMethods(
        controller,
        [
            objc.selector(
                _sidebar_row_added,
                selector=b"outlineView:didAddRowView:forRow:",
                signature=b"v@:@@q",
            )
        ],
    )
    _ROW_HOOK_INSTALLED = True
    return True


class _AZFontViewRowBars(NSObject):
    """The row bars and the color legend of one window's Font-view sidebar. Retained
    by Glyphs' outline view (associated object) and holding it only weakly; its
    live-refresh callback unregisters itself once that outline is gone."""

    @objc.python_method
    def attach(self, outline: Any) -> None:
        self._outline_ref = objc.WeakRef(outline)
        self._census = None
        self._colors = []
        self._glyphs = None
        self._members = {}
        self._lastMaster = None
        self._heightPending = False
        self._legend = None
        self._focus = None  # the color key the legend spotlights in every bar
        # While the spotlit color narrows the grid: Glyphs' array controller, its own
        # filter under ours, and the glyph names ours keeps.
        self._gridCtrl = None
        self._gridBase = None
        self._gridNames = None
        self._gridSetting = False
        Glyphs.addCallback(self.refreshInterface, UPDATEINTERFACE)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "colorFlowSettingsChanged:", COLORFLOW_SETTINGS_CHANGED, None
        )
        self.refresh()

    @objc.python_method
    def _font(self) -> Any:
        outline = self._outline_ref()
        window = outline.window() if outline is not None else None
        controller = window.windowController() if window is not None else None
        if controller is None or not controller.respondsToSelector_(b"documentFont"):
            return None
        return controller.documentFont()

    # UPDATEINTERFACE fires constantly: a master switch refreshes at once, anything else
    # (a color edit) coalesces into one refresh after the churn settles.
    @objc.python_method
    def refreshInterface(self, sender: Any) -> None:
        if self._outline_ref() is None:
            # Glyphs is iterating its callbacks right now: unregister on the next turn.
            self.performSelector_withObject_afterDelay_("detach:", None, 0.0)
            return
        font = self._font()
        if font is None or not _row_bars_enabled():
            return
        try:
            master_id = str(font.selectedFontMaster.id)
        except Exception:
            master_id = None
        if master_id != self._lastMaster:
            self.refresh()
            return
        NSObject.cancelPreviousPerformRequestsWithTarget_selector_object_(
            self, "rowBarsRefresh:", None
        )
        self.performSelector_withObject_afterDelay_("rowBarsRefresh:", None, 0.12)

    def rowBarsRefresh_(self, sender: Any) -> None:
        self.refresh()

    def colorFlowSettingsChanged_(self, notification: Any) -> None:
        self.refresh()

    def detach_(self, sender: Any) -> None:
        Glyphs.removeCallback(self.refreshInterface, UPDATEINTERFACE)
        NSNotificationCenter.defaultCenter().removeObserver_(self)
        self._stop_watching_grid()

    @objc.python_method
    def refresh(self) -> None:
        try:
            if not _row_bars_enabled():
                self.show_bars(False)
                self.show_legend(False)
                self._focus = None  # no legend left to clear it from
                self.filter_grid()
                return
            font = self._font()
            if font is None:
                return
            census = azcolorflow_census.row_bar_census(font)
            if self._census is None or census["keys"].keys() != self._census["keys"].keys():
                self._members = {}  # a glyph was added, deleted or renamed
            self._census = census
            self._lastMaster = self._census["master_id"]
            self._colors = labelcolors.read_label_colors()
            self._glyphs = AppKit.NSArray.arrayWithArray_(list(font.glyphs))
            legend = _legend_enabled()
            if not legend or self._focus not in self._census["labels"]:
                self._focus = None  # no legend to clear it from, or no longer a step
            self.filter_grid()
            self.show_bars(True)
            self.show_legend(legend)
        except Exception:
            _report("Font-view bars")

    @objc.python_method
    def rowAdded(self, row_view: Any, row: int) -> None:
        self.decorate_row(row_view, row, _row_bars_enabled())

    @objc.python_method
    def show_bars(self, show: bool) -> None:
        outline = self._outline_ref()
        if outline is None:
            return

        def visit(row_view: Any, row: int) -> None:
            self.decorate_row(row_view, row, show)

        outline.enumerateAvailableRowViewsUsingBlock_(visit)

    @objc.python_method
    def decorate_row(self, row_view: Any, row: int, show: bool) -> None:
        """Show or remove one row's bar, and re-measure the rows if its height changed."""
        outline = self._outline_ref()
        cell = row_view.viewAtColumn_(0)
        if outline is None or cell is None or cell.identifier() != _ROW_CELL_ID:
            return
        node = outline.itemAtRow_(row)
        segments = self._segments_for(node) if show else None
        bar, changed = _set_row_bar(cell, segments is not None, _row_bars_behind())
        if bar is not None and segments is not None:
            bar._focus = self._focus
            bar.setSegments(*segments)
        if changed:
            self._note_heights()

    def focusColor_(self, color_key: Any) -> None:
        # A legend click: spotlight that color in every bar; the same one again clears.
        try:
            key = str(color_key)
            self._focus = None if self._focus == key else key
            if self._legend is not None:
                self._legend._focus = self._focus
                self._legend.setNeedsDisplay_(True)
            self.show_bars(True)
            self.filter_grid()
        except Exception:
            _report("Font-view legend")

    @objc.python_method
    def filter_grid(self) -> None:
        """With Font Glyph Order on, narrow Glyphs' grid to the spotlit color's glyphs,
        on top of Glyphs' own filter (sidebar row, search); otherwise hand the grid
        back to Glyphs' filter alone."""
        font, census, focus = self._font(), self._census, self._focus
        if focus is None or census is None or not _glyph_order_on(font):
            if self._gridCtrl is not None:
                self._set_grid_predicate(self._gridBase)
                self._stop_watching_grid()
            return
        names = frozenset(name for name, key in census["keys"].items() if str(key) == focus)
        if self._gridCtrl is None:
            outline = self._outline_ref()
            window = outline.window() if outline is not None else None
            ctrl = self._glyph_array(window)
            if ctrl is None:
                return
            self._gridCtrl, self._gridBase = ctrl, ctrl.filterPredicate()
            ctrl.addObserver_forKeyPath_options_context_(self, "filterPredicate", 0, None)
            NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
                self, "gridWindowWillClose:", AppKit.NSWindowWillCloseNotification, window
            )
        elif names == self._gridNames:
            return  # re-filtering would only reshuffle Glyphs' grid
        ours = AppKit.NSPredicate.predicateWithFormat_argumentArray_(
            "name IN %@", [AppKit.NSSet.setWithArray_(sorted(names))]
        )
        base = self._gridBase
        self._gridNames = names
        self._set_grid_predicate(
            AppKit.NSCompoundPredicate.andPredicateWithSubpredicates_([base, ours])
            if base is not None
            else ours
        )

    def observeValueForKeyPath_ofObject_change_context_(
        self, path: Any, ctrl: Any, change: Any, context: Any
    ) -> None:
        # Glyphs rebuilt its own filter (a sidebar row, the search field): ours goes on
        # top of the new one.
        if self._gridSetting or ctrl != self._gridCtrl:
            return
        try:
            self._gridBase, self._gridNames = ctrl.filterPredicate(), None
            self.filter_grid()
        except Exception:
            _report("Font-view filter")

    def gridWindowWillClose_(self, notification: Any) -> None:
        self._stop_watching_grid()

    @objc.python_method
    def _set_grid_predicate(self, predicate: Any) -> None:
        ctrl = self._gridCtrl
        if ctrl is None:
            return
        self._gridSetting = True
        try:
            ctrl.setFilterPredicate_(predicate)
        finally:
            self._gridSetting = False

    @objc.python_method
    def _stop_watching_grid(self) -> None:
        ctrl, self._gridCtrl = self._gridCtrl, None
        self._gridBase = self._gridNames = None
        if ctrl is None:
            return
        ctrl.removeObserver_forKeyPath_(self, "filterPredicate")
        NSNotificationCenter.defaultCenter().removeObserver_name_object_(
            self, AppKit.NSWindowWillCloseNotification, None
        )

    @objc.python_method
    def _glyph_array(self, window: Any) -> Any:
        controller = window.windowController() if window is not None else None
        if controller is None or not controller.respondsToSelector_(b"fontViewController"):
            return None
        font_view = controller.fontViewController()
        return font_view.glyphsArrayController() if font_view is not None else None

    @objc.python_method
    def show_legend(self, show: bool) -> None:
        """Put the legend between Glyphs' list and its bottom bar, or take it out and
        reattach the list to the bar exactly as Glyphs had it."""
        outline, census, colors = self._outline_ref(), self._census, self._colors
        scroll = outline.enclosingScrollView() if outline is not None else None
        root = scroll.superview() if scroll is not None else None
        legend = self._legend
        if not show or census is None or scroll is None or root is None:
            if legend is not None:
                AppKit.NSLayoutConstraint.deactivateConstraints_(self._legend_own)
                legend.removeFromSuperview()
                self._legend_link.setActive_(True)
                self._legend = None
            return
        if legend is None:
            link, bar_area = _edge_to_sibling(
                root, scroll, AppKit.NSLayoutAttributeBottom, AppKit.NSLayoutAttributeTop
            )
            if link is None or not link.isActive():
                return  # not the layout this was built for: bars only
            legend = _AZFontViewLegendView.alloc().initWithFrame_(AppKit.NSZeroRect)
            legend.setTranslatesAutoresizingMaskIntoConstraints_(False)
            legend._owner_ref = objc.WeakRef(self)
            root.addSubview_(legend)
            self._legend_height = legend.heightAnchor().constraintEqualToConstant_(0.0)
            self._legend_own = [
                legend.leadingAnchor().constraintEqualToAnchor_(root.leadingAnchor()),
                legend.trailingAnchor().constraintEqualToAnchor_(root.trailingAnchor()),
                legend.topAnchor().constraintEqualToAnchor_(scroll.bottomAnchor()),
                legend.bottomAnchor().constraintEqualToAnchor_(bar_area.topAnchor()),
                self._legend_height,
            ]
            link.setActive_(False)
            AppKit.NSLayoutConstraint.activateConstraints_(self._legend_own)
            self._legend, self._legend_link = legend, link
        entries = [(colors[int(key)], label, key) for key, label in census["labels"].items()]
        legend._inset = self._header_inset() or legend._inset
        legend._focus = self._focus
        legend.set_entries(entries)
        self._legend_height.setConstant_(legend.content_height() if entries else 0.0)

    @objc.python_method
    def _header_inset(self) -> Any:
        """Where the text of Glyphs' own section titles (Categories…) starts, read off a
        visible header row; None when none is on screen."""
        outline = self._outline_ref()
        if outline is None:
            return None
        delegate = outline.delegate()
        if delegate is None:
            return None
        found = []

        def visit(row_view: Any, row: int) -> None:
            cell = row_view.viewAtColumn_(0)
            if found or cell is None or not cell.respondsToSelector_(b"textField"):
                return
            field = cell.textField()
            node = outline.itemAtRow_(row)
            if field is None or not delegate.outlineView_isGroupItem_(outline, node):
                return
            text = field.alignmentRectForFrame_(field.frame())
            found.append(field.superview().convertPoint_toView_(text.origin, outline).x)

        outline.enumerateAvailableRowViewsUsingBlock_(visit)
        return found[0] if found else None

    @objc.python_method
    def _segments_for(self, node: Any) -> Any:
        """``(segs, tooltip)`` for one sidebar row, or None for a row that gets no
        bar (section headers, filter folders)."""
        outline, census = self._outline_ref(), self._census
        if outline is None or census is None or node is None:
            return None
        delegate = outline.delegate()
        if delegate is not None and delegate.outlineView_isGroupItem_(outline, node):
            return None
        item = node.representedObject() if node.respondsToSelector_(b"representedObject") else node
        names = self._row_names(item)
        if names is None:
            return None
        labels, colors = census["labels"], self._colors
        dist = azcolorflow_census.row_bar_dist(names, census["keys"], labels)
        total = len(names)
        segs = [(dist[key] / total, colors[int(key)], key) for key in labels if dist[key]]
        parts = [f"{label} {dist[key]}" for key, label in labels.items() if dist[key]]
        uncolored = total - sum(dist.values())
        if uncolored:
            parts.append(f"uncolored {uncolored}")
        return segs, " · ".join(parts) or "No glyphs"

    @objc.python_method
    def _row_names(self, item: Any) -> Any:
        # Glyphs' own filter for the row, so a bar holds exactly the glyphs the row
        # counts. Cached per filter and master until Glyphs' count for it changes.
        font, census, glyphs = self._font(), self._census, self._glyphs
        if font is None or census is None or glyphs is None:
            return None
        master_index = int(getattr(font, "masterIndex", 0) or 0)
        predicate = objc.lookUpClass(
            "GSFontViewController"
        ).filterForItem_sortDescriptors_font_masterIndex_(
            item, AppKit.NSMutableArray.array(), font, master_index
        )
        if predicate is None and not item.isLeaf():
            return None  # a filter folder, not a glyph set
        key = (
            str(predicate.predicateFormat()) if predicate is not None else "*",
            master_index,
            int(item.count()),
        )
        names = self._members.get(key)
        if names is None:
            if predicate is None:  # "All"
                names = list(census["keys"])
            else:
                names = [
                    str(glyph.name) for glyph in glyphs.filteredArrayUsingPredicate_(predicate)
                ]
            self._members[key] = names
        return names

    @objc.python_method
    def _note_heights(self) -> None:
        # Rows size themselves (automatic row heights) but only re-measure when told.
        if self._heightPending:
            return
        self._heightPending = True
        self.performSelector_withObject_afterDelay_("noteRowHeights:", None, 0.0)

    def noteRowHeights_(self, sender: Any) -> None:
        self._heightPending = False
        outline = self._outline_ref()
        if outline is None:
            return
        rows = outline.numberOfRows()
        if rows:
            outline.noteHeightOfRowsWithIndexesChanged_(
                AppKit.NSIndexSet.indexSetWithIndexesInRange_((0, rows))
            )


def _install_fontview_row_bars(window_controller: Any) -> None:
    """Give one window's Font-view sidebar its row bars (idempotent)."""
    if window_controller is None or not window_controller.respondsToSelector_(
        b"fontViewController"
    ):
        return
    font_view = window_controller.fontViewController()
    sidebar = font_view.glyphsGroupViewController() if font_view is not None else None
    if sidebar is None or not sidebar.respondsToSelector_(b"myOutlineView"):
        return
    outline = sidebar.myOutlineView()
    if outline is None or objc.getAssociatedObject(outline, _ROW_BARS_TAG) is not None:
        return
    if not _install_row_hook():
        return
    bars = _AZFontViewRowBars.alloc().init()
    objc.setAssociatedObject(outline, _ROW_BARS_TAG, bars, objc.OBJC_ASSOCIATION_RETAIN)
    bars.attach(outline)


class _AZFontViewSidebarInstaller(NSObject):
    def windowDidBecomeMain_(self, notification: Any) -> None:
        try:
            _install_fontview_row_bars(notification.object().windowController())
        except Exception:
            _report("Font-view row bars")


def _register_fontview_row_bars() -> None:
    """Give every Font-view sidebar its row bars (once per session)."""
    global _FONTVIEW_INSTALLER
    if _FONTVIEW_INSTALLER is not None:
        return
    _FONTVIEW_INSTALLER = _AZFontViewSidebarInstaller.alloc().init()
    NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
        _FONTVIEW_INSTALLER, "windowDidBecomeMain:", AppKit.NSWindowDidBecomeMainNotification, None
    )
    for font in Glyphs.fonts:
        _install_fontview_row_bars(font.parent.windowController())


# ---------------------------------------------------------------------------- #
#  Font Glyph Order: follow master switches, color edits and step changes
# ---------------------------------------------------------------------------- #
_GLYPH_ORDER_REFRESHER = None


class _AZGlyphOrderRefresher(NSObject):
    """Rebuilds the front font's Font Glyph Order when its master or a selected glyph's
    color changes, or the steps change in Settings. Debounced: a burst of interface
    updates costs one rebuild."""

    @objc.python_method
    def start(self) -> None:
        self._pending = None
        Glyphs.addCallback(self.refreshInterface, UPDATEINTERFACE)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "colorFlowSettingsChanged:", COLORFLOW_SETTINGS_CHANGED, None
        )

    @objc.python_method
    def refreshInterface(self, sender: Any) -> None:
        font = Glyphs.font
        try:
            if font is None or not fontview.is_enabled(font):
                return
            if fontview.is_dirty(font):
                self._schedule(font)
        except Exception:
            pass  # fires on every interface update: never spam the Macro panel

    def colorFlowSettingsChanged_(self, notification: Any) -> None:
        # Step names or order changed: regroup although no color moved. Other open
        # fonts regroup when they next come to the front.
        for other in Glyphs.fonts:
            del other.tempData[fontview.SNAPSHOT_KEY]
        font = Glyphs.font
        if font is not None and fontview.is_enabled(font):
            self._schedule(font)

    @objc.python_method
    def _schedule(self, font: Any) -> None:
        self._pending = font
        NSObject.cancelPreviousPerformRequestsWithTarget_selector_object_(
            self, "glyphOrderRebuild:", None
        )
        self.performSelector_withObject_afterDelay_("glyphOrderRebuild:", None, 0.15)

    def glyphOrderRebuild_(self, sender: Any) -> None:
        font, self._pending = self._pending, None
        try:
            if font is not None and fontview.is_enabled(font):
                fontview.rebuild(font)
        except Exception:
            _report("Font Glyph Order")


def _register_glyph_order_refresh() -> None:
    """Keep Font Glyph Order current (once per session)."""
    global _GLYPH_ORDER_REFRESHER
    if _GLYPH_ORDER_REFRESHER is not None:
        return
    _GLYPH_ORDER_REFRESHER = _AZGlyphOrderRefresher.alloc().init()
    _GLYPH_ORDER_REFRESHER.start()


# ---------------------------------------------------------------------------- #
#  Color wheel: hold the trigger click, drag to a step, release to color layers
# ---------------------------------------------------------------------------- #
_WHEEL_ENABLED_KEY = "com.hugojourdan.ColorFlow.wheelEnabled"
_WHEEL_TRIGGER_KEY = "com.hugojourdan.ColorFlow.wheelTrigger"
_WHEEL_BAND = 22.0  # the wedges' depth across the band, before the rim
_WHEEL_CORNER = 2.0  # the wedges' corner radius
_WHEEL_PADDING = 3.0  # band showing around each wedge
_WHEEL_GAP = 3.0  # between neighbours, the same width all across
# Every wedge rests at this opacity; the hot one comes up to full.
_WHEEL_REST_OPACITY = 0.85
_WHEEL_FOCUS_TIME = 0.2  # seconds to bring it up, or back down
_WHEEL_NO_COLOR_MARK = 14.0  # No Color's struck ring
# Each slot's least share of the ring's middle circle: a crowded wheel grows past
# _WHEEL_MIN_RADIUS rather than thin its wedges.
_WHEEL_PITCH = 36.0
_WHEEL_MIN_RADIUS = 41.5
_WHEEL_DEAD_ZONE = 10.0  # releasing this close to the center cancels
_WHEEL_RIM = 8.0  # backdrop past the wedges, both edges
_WHEEL_HOLE_SCALE = 0.8  # the empty center, shrunk; the wedges reach in to meet it
_WHEEL_PILL_GAP = 10.0  # wheel -> name pill
_WHEEL_PILL_H = 20.0
_WHEEL_PILL_TEXT = 12.0
_WHEEL_PILL_PAD = 9.0
_WHEEL_MARGIN = 2.0  # transparent room around the drawing, for the hairline's edge
_WHEEL_FADE_IN = 0.2  # seconds, for the fade and the zoom alike
_WHEEL_ZOOM_FROM = 0.95  # a hint of growth, not a pop
_WHEEL_TICK = 1.0 / 60.0
_KEY_ESCAPE = 53
_WHEEL_DOWN_TYPES = (
    AppKit.NSEventTypeLeftMouseDown,
    AppKit.NSEventTypeRightMouseDown,
    AppKit.NSEventTypeOtherMouseDown,
)
_WHEEL_UP_TYPES = (
    AppKit.NSEventTypeLeftMouseUp,
    AppKit.NSEventTypeRightMouseUp,
    AppKit.NSEventTypeOtherMouseUp,
)
_WHEEL_DRAG_TYPES = (
    AppKit.NSEventTypeLeftMouseDragged,
    AppKit.NSEventTypeRightMouseDragged,
    AppKit.NSEventTypeOtherMouseDragged,
)
_WHEEL_EVENT_MASK = (
    AppKit.NSEventMaskLeftMouseDown
    | AppKit.NSEventMaskLeftMouseUp
    | AppKit.NSEventMaskLeftMouseDragged
    | AppKit.NSEventMaskRightMouseDown
    | AppKit.NSEventMaskRightMouseUp
    | AppKit.NSEventMaskRightMouseDragged
    | AppKit.NSEventMaskOtherMouseDown
    | AppKit.NSEventMaskOtherMouseUp
    | AppKit.NSEventMaskOtherMouseDragged
    | AppKit.NSEventMaskKeyDown
    | AppKit.NSEventMaskFlagsChanged
)
_WHEEL = None


class _AZColorWheelPanel(AppKit.NSPanel):
    """Never key or main, so Glyphs keeps focus; input reaches the wheel through its
    event monitor."""

    def canBecomeKeyWindow(self) -> bool:
        return False

    def canBecomeMainWindow(self) -> bool:
        return False


class _AZColorWheelView(AppKit.NSView):
    """Colored wedges around the cursor; the hot one at full opacity, named in a pill
    below."""

    def initWithFrame_(self, frame: Any) -> Any:
        self = objc.super(_AZColorWheelView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._slots = []  # [(colorKey, rgba or None for No Color, label)]
        self._hot = None
        self._every_master = False  # ⇧ held: the pill says the pick covers every master
        self._progress = 1.0  # zoom-in, 0 -> 1
        self._focus_from: list = []  # each slot's focus when the hot slot last changed
        self._focus_since = 0.0
        self._focus_timer = None
        return self

    @objc.python_method
    def configure(self, slots: list, radius: float) -> tuple:
        """Take the wheel's content (before anything draws); return the ``(width,
        height)`` it needs."""
        self._slots, self._radius = slots, radius
        widest = max(
            _wheel_pill_text(label, azcolorflow_wheel.key_hint(index, len(slots)), True)
            .size()
            .width
            for index, (_key, _rgba, label) in enumerate(slots)
        )
        width = max(2.0 * self._rim(), widest + 2.0 * _WHEEL_PILL_PAD)
        height = 2.0 * self._rim() + _WHEEL_PILL_GAP + _WHEEL_PILL_H
        return width + 2.0 * _WHEEL_MARGIN, height + 2.0 * _WHEEL_MARGIN

    @objc.python_method
    def _rim(self) -> float:
        return self._radius + _WHEEL_BAND / 2.0 + _WHEEL_RIM

    @objc.python_method
    def center(self) -> tuple:
        """The wheel's center in this view: the pill hangs below it."""
        bounds = self.bounds()
        return AppKit.NSMidX(bounds), AppKit.NSMaxY(bounds) - _WHEEL_MARGIN - self._rim()

    @objc.python_method
    def hot(self) -> int | None:
        return self._hot

    @objc.python_method
    def set_hot(self, index: int | None) -> None:
        if index != self._hot:
            self._focus_from = self._levels()  # mid-fade too: carry on from there
            self._focus_since = time.monotonic()
            self._hot = index
            self._run_focus()
            self.setNeedsDisplay_(True)

    @objc.python_method
    def _levels(self) -> list:
        """Each slot's focus now (0 to 1), on its way up for the hot slot, down for the
        rest."""
        progress = azcolorflow_wheel.ease_out(
            time.monotonic() - self._focus_since, _WHEEL_FOCUS_TIME
        )
        return azcolorflow_wheel.focus_levels(
            self._focus_from, self._hot, len(self._slots), progress
        )

    @objc.python_method
    def _run_focus(self) -> None:
        """Redraw every tick until the focus settles; a running timer just reads the
        new start time."""
        if self._focus_timer is not None:
            return

        def tick(timer: Any) -> None:
            try:
                self.setNeedsDisplay_(True)
                if time.monotonic() - self._focus_since < _WHEEL_FOCUS_TIME:
                    return
            except Exception:
                _report("color wheel focus")  # a raising timer block would take Glyphs down
            timer.invalidate()
            self._focus_timer = None

        self._focus_timer = _start_wheel_timer(tick)

    @objc.python_method
    def set_every_master(self, on: bool) -> None:
        if on != self._every_master:
            self._every_master = on
            self.setNeedsDisplay_(True)

    @objc.python_method
    def set_progress(self, progress: float) -> None:
        self._progress = progress
        self.setNeedsDisplay_(True)

    @objc.python_method
    def _zoom(self, progress: float) -> None:
        """Scale what follows about the wheel's center: ``_WHEEL_ZOOM_FROM`` at 0, full
        size at 1."""
        center_x, center_y = self.center()
        zoom = AppKit.NSAffineTransform.transform()
        zoom.translateXBy_yBy_(center_x, center_y)
        zoom.scaleBy_(_WHEEL_ZOOM_FROM + (1.0 - _WHEEL_ZOOM_FROM) * progress)
        zoom.translateXBy_yBy_(-center_x, -center_y)
        zoom.concat()

    def drawRect_(self, dirtyRect: Any) -> None:
        center_x, center_y = self.center()
        self._zoom(self._progress)
        rim = self._rim()
        hole = (self._radius - _WHEEL_BAND / 2.0 - _WHEEL_RIM) * _WHEEL_HOLE_SCALE
        # A band under the wedges, empty in the middle.
        band = AppKit.NSBezierPath.bezierPathWithOvalInRect_(
            AppKit.NSMakeRect(center_x - rim, center_y - rim, 2 * rim, 2 * rim)
        )
        band.appendBezierPathWithOvalInRect_(
            AppKit.NSMakeRect(center_x - hole, center_y - hole, 2 * hole, 2 * hole)
        )
        band.setWindingRule_(AppKit.NSWindingRuleEvenOdd)
        _draw_wheel_backdrop(band)
        self._draw_slots(center_x, center_y, rim, hole)

    @objc.python_method
    def _wedge(self, center: tuple, index: int, inner: float, outer: float) -> Any:
        """Slot ``index``'s wedge between radii ``inner`` and ``outer``: even gaps to
        its neighbours, rounded corners."""
        arcs = azcolorflow_wheel.wedge_arcs(
            index, len(self._slots), inner, outer, _WHEEL_GAP, _WHEEL_CORNER
        )
        path = AppKit.NSBezierPath.bezierPath()
        for arc_x, arc_y, radius, start, end, clockwise in arcs:
            path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                (center[0] + arc_x, center[1] + arc_y), radius, start, end, clockwise
            )
        path.closePath()
        return path

    @objc.python_method
    def _draw_slots(self, center_x: float, center_y: float, rim: float, hole: float) -> None:
        count = len(self._slots)
        for index, ((_color_key, rgba, _label), level) in enumerate(
            zip(self._slots, self._levels(), strict=True)
        ):
            opacity = _WHEEL_REST_OPACITY + (1.0 - _WHEEL_REST_OPACITY) * level
            if rgba is None:
                # No Color: a struck ring alone.
                middle = (hole + rim) / 2.0  # the band's middle
                offset_x, offset_y = azcolorflow_wheel.slot_offset(index, count, middle)
                half = _WHEEL_NO_COLOR_MARK / 2.0
                mark_x, mark_y = center_x + offset_x, center_y + offset_y
                mark = AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                    AppKit.NSMakeRect(mark_x - half, mark_y - half, 2 * half, 2 * half)
                )
                mark.moveToPoint_((mark_x - half * 0.7071, mark_y - half * 0.7071))
                mark.lineToPoint_((mark_x + half * 0.7071, mark_y + half * 0.7071))
                AppKit.NSColor.labelColor().colorWithAlphaComponent_(0.5 * opacity).set()
                mark.setLineWidth_(1.5)
                mark.stroke()
            else:
                wedge = self._wedge(
                    (center_x, center_y), index, hole + _WHEEL_PADDING, rim - _WHEEL_PADDING
                )
                red, green, blue, alpha = rgba
                AppKit.NSColor.colorWithDeviceRed_green_blue_alpha_(
                    red, green, blue, alpha * opacity
                ).set()
                wedge.fill()
                # A faint edge, so Charcoal shows on a dark backdrop and Light Gray on a light one.
                AppKit.NSColor.labelColor().colorWithAlphaComponent_(0.25 * opacity).set()
                wedge.stroke()

        if self._hot is not None:
            text = _wheel_pill_text(
                self._slots[self._hot][2],
                azcolorflow_wheel.key_hint(self._hot, len(self._slots)),
                self._every_master,
            )
            text_size = text.size()
            width = text_size.width + 2.0 * _WHEEL_PILL_PAD
            top = center_y - rim - _WHEEL_PILL_GAP
            pill = AppKit.NSMakeRect(
                center_x - width / 2.0, top - _WHEEL_PILL_H, width, _WHEEL_PILL_H
            )
            radius = _WHEEL_PILL_H / 2.0
            _draw_wheel_backdrop(
                AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(pill, radius, radius)
            )
            text.drawAtPoint_(
                (
                    center_x - text_size.width / 2.0,
                    AppKit.NSMidY(pill) - text_size.height / 2.0,
                )
            )


def _wheel_enabled() -> bool:
    """The Settings checkbox; on until switched off."""
    return bool(Glyphs.defaults.get(_WHEEL_ENABLED_KEY, True))


def _start_wheel_timer(tick: Any) -> Any:
    """A repeating timer calling ``tick`` every frame, in the common modes so it keeps
    running while AppKit tracks the mouse."""
    timer = AppKit.NSTimer.timerWithTimeInterval_repeats_block_(_WHEEL_TICK, True, tick)
    AppKit.NSRunLoop.currentRunLoop().addTimer_forMode_(timer, AppKit.NSRunLoopCommonModes)
    return timer


def _wheel_pill_text(label: str, hint: str | None, every_master: bool) -> Any:
    """The step's name (and "all masters" while ⇧ is held), then the key that picks
    it, dimmed."""
    font = AppKit.NSFont.systemFontOfSize_weight_(_WHEEL_PILL_TEXT, AppKit.NSFontWeightMedium)
    text = AppKit.NSMutableAttributedString.alloc().initWithString_attributes_(
        f"{label} · all masters" if every_master else label,
        {
            AppKit.NSFontAttributeName: font,
            AppKit.NSForegroundColorAttributeName: AppKit.NSColor.labelColor(),
        },
    )
    if hint is not None:
        text.appendAttributedString_(
            AppKit.NSAttributedString.alloc().initWithString_attributes_(
                f"   {hint}",
                {
                    AppKit.NSFontAttributeName: font,
                    AppKit.NSForegroundColorAttributeName: AppKit.NSColor.tertiaryLabelColor(),
                },
            )
        )
    return text


def _draw_wheel_backdrop(path: Any) -> None:
    """The wheel's and the pill's shared look: a fill and a hairline, no shadow."""
    AppKit.NSColor.windowBackgroundColor().set()
    path.fill()
    AppKit.NSColor.separatorColor().set()
    path.setLineWidth_(0.5)
    path.stroke()


def _wheel_over_glyphs(font: Any, event: Any) -> bool:
    """Whether ``event`` landed on the Edit-view canvas, or on the Font view's grid or
    list, of ``font``'s window. Elsewhere the trigger click stays Glyphs'."""
    window = event.window()
    if window is None:
        return False
    hit = window.contentView().hitTest_(event.locationInWindow())
    if hit is None:
        return False
    owner = font.currentTab
    if owner is not None:
        # Glyphs 4 lays the frame view over the canvas, so it takes the canvas' clicks.
        selectors = ("graphicView", "frameView")
    else:
        owner = font.parent.windowController().fontViewController()
        selectors = ("fontIconView", "listViewTableview")
    targets = [
        getattr(owner, selector)() for selector in selectors if owner.respondsToSelector_(selector)
    ]
    return any(target is not None and hit.isDescendantOf_(target) for target in targets)


def _every_master_layer(font: Any, layers: list) -> list:
    """The master layers of every glyph behind ``layers``, each glyph once."""
    glyphs = {layer.parent.name: layer.parent for layer in layers}
    return [glyph.layers[master.id] for glyph in glyphs.values() for master in font.masters]


def _set_layer_colors(font: Any, layers: list, color_key: int) -> None:
    """Give every layer ``color_key`` (No Color clears it): one interface update, and
    one undo step per glyph."""
    value = None if color_key == colornames.NO_COLOR else color_key
    by_glyph: dict = {}
    for layer in layers:
        by_glyph.setdefault(layer.parent.name, []).append(layer)
    font.disableUpdateInterface()
    try:
        for glyph_layers in by_glyph.values():
            glyph = glyph_layers[0].parent
            glyph.beginUndo()
            try:
                for layer in glyph_layers:
                    layer.color = value
            finally:
                glyph.endUndo()
    finally:
        font.enableUpdateInterface()


def _shift_held(event: Any) -> bool:
    return bool(int(event.modifierFlags()) & azcolorflow_wheel.MOD_SHIFT)


class _AZColorWheel:
    """Idle until the trigger click lands on glyphs; then owns every mouse and key event
    until that button comes back up."""

    def __init__(self) -> None:
        self._panel = None
        self._view = None
        self._center = (0.0, 0.0)  # screen point the wheel hit-tests from
        self._button_number: int | None = None  # set while the wheel owns the mouse
        self._font = None
        self._layers: list = []
        self._slots: list = []
        self._timer = None  # the fade-in

    def handle(self, event: Any) -> bool:
        """True to swallow ``event``."""
        event_type = event.type()
        if self._button_number is None:
            return event_type in _WHEEL_DOWN_TYPES and self._open(event)
        if event_type in _WHEEL_DOWN_TYPES and event.buttonNumber() == self._button_number:
            # The button went down again, so its mouse-up was lost: start over rather
            # than color the old selection on this press's release.
            self.hide()
            return self._open(event)
        if event_type == AppKit.NSEventTypeFlagsChanged:
            if self._view is not None:
                self._view.set_every_master(_shift_held(event))
            return False  # Glyphs tracks its own modifiers
        if event_type in _WHEEL_UP_TYPES and event.buttonNumber() == self._button_number:
            self._fire(event)
        elif event_type in _WHEEL_DRAG_TYPES:
            self._track(AppKit.NSEvent.mouseLocation())
        elif event_type == AppKit.NSEventTypeKeyDown:
            self._key(event)
        elif not AppKit.NSEvent.pressedMouseButtons() & (1 << self._button_number):
            self.hide()  # its mouse-up never reached us
        return True

    def _open(self, event: Any) -> bool:
        if not _wheel_enabled():
            return False
        trigger = azcolorflow_wheel.trigger_for(Glyphs.defaults[_WHEEL_TRIGGER_KEY])
        button = azcolorflow_wheel.mouse_button(int(event.type()), int(event.buttonNumber()))
        if not azcolorflow_wheel.trigger_matches(trigger, button, int(event.modifierFlags())):
            return False
        font = Glyphs.font
        if font is None or not _wheel_over_glyphs(font, event):
            return False
        layers = [layer for layer in (font.selectedLayers or []) if layer is not None]
        if not layers:
            return False

        steps = colornames.shown_steps(colornames.settings_text(font))
        rgba = labelcolors.read_label_colors()
        slots = [
            (
                key,
                None if key == colornames.NO_COLOR else rgba[key],
                colornames.label_for(key, steps),
            )
            for key in azcolorflow_wheel.wheel_slots(steps)
        ]
        radius = azcolorflow_wheel.ring_radius(len(slots), _WHEEL_PITCH, _WHEEL_MIN_RADIUS)

        view = _AZColorWheelView.alloc().initWithFrame_(AppKit.NSZeroRect)
        width, height = view.configure(slots, radius)
        rect = AppKit.NSMakeRect(0.0, 0.0, width, height)
        view.setFrame_(rect)
        panel = _AZColorWheelPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, AppKit.NSWindowStyleMaskBorderless, AppKit.NSBackingStoreBuffered, False
        )
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setHasShadow_(False)
        panel.setLevel_(AppKit.NSPopUpMenuWindowLevel)
        panel.setIgnoresMouseEvents_(True)
        panel.setReleasedWhenClosed_(False)
        panel.setContentView_(view)

        # Centered on the cursor even at a screen edge, so a release that never moved
        # stays in the dead zone; slots pushed off screen still answer by direction.
        cursor = AppKit.NSEvent.mouseLocation()
        center_x, center_y = view.center()
        panel.setFrameOrigin_((cursor.x - center_x, cursor.y - center_y))

        self._panel, self._view = panel, view
        self._center = (cursor.x, cursor.y)
        self._button_number = int(event.buttonNumber())
        self._font, self._layers, self._slots = font, layers, slots
        self._fade_in(panel, view)
        panel.orderFrontRegardless()
        self._track(cursor)
        return True

    def _fade_in(self, panel: Any, view: Any) -> None:
        """Fade the wheel in while it grows from ``_WHEEL_ZOOM_FROM`` to full size."""
        started = time.monotonic()

        def tick(timer: Any) -> None:
            try:
                progress = azcolorflow_wheel.ease_out(time.monotonic() - started, _WHEEL_FADE_IN)
                panel.setAlphaValue_(progress)
                view.set_progress(progress)
                if progress >= 1.0:
                    timer.invalidate()
            except Exception:
                timer.invalidate()  # a raising timer block would take Glyphs down
                _report("color wheel fade-in")

        panel.setAlphaValue_(0.0)
        view.set_progress(0.0)
        self._timer = _start_wheel_timer(tick)

    def _track(self, point: Any) -> None:
        if self._view is None:
            return
        self._view.set_hot(
            azcolorflow_wheel.hit_test(
                point.x - self._center[0],
                point.y - self._center[1],
                _WHEEL_DEAD_ZONE,
                len(self._slots),
            )
        )

    def _key(self, event: Any) -> None:
        """Esc cancels; 1-9, 0 and ⌫ pick at once. Every other key is swallowed while the
        wheel is open, as in AZ Keyring."""
        if self._view is None or event.isARepeat():
            return
        if event.keyCode() == _KEY_ESCAPE:
            self._close(None, False)
            return
        index = azcolorflow_wheel.slot_for_key(int(event.keyCode()), len(self._slots))
        if index is not None:
            self._close(index, _shift_held(event))

    def _fire(self, event: Any) -> None:
        index = self._view.hot() if self._view is not None else None
        self._button_number = None
        self._close(index, _shift_held(event))

    def _close(self, index: int | None, every_master: bool) -> None:
        """Apply slot ``index`` (``None`` cancels), to every master of the glyphs when
        ``every_master``, and take the wheel off screen. A button still down stays the
        wheel's until it comes up: Glyphs must never get a drag or mouse-up without its
        mouse-down."""
        font, layers, slots = self._font, self._layers, self._slots
        if self._button_number is None:
            self.hide()
        else:
            if self._panel is not None:
                self._panel.orderOut_(None)
            self._view = None
        if index is not None and font is not None:
            if every_master:
                layers = _every_master_layer(font, layers)
            _set_layer_colors(font, layers, slots[index][0])

    def hide(self) -> None:
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None
        if self._panel is not None:
            self._panel.orderOut_(None)
        self._panel = self._view = self._font = self._button_number = None
        self._layers, self._slots = [], []


def _register_color_wheel() -> None:
    """Install the color wheel's event monitor (once per session)."""
    global _WHEEL
    if _WHEEL is not None:
        return
    wheel = _WHEEL = _AZColorWheel()

    def handler(event: Any) -> Any:
        try:
            return None if wheel.handle(event) else event
        except Exception:
            _report("color wheel")
            wheel.hide()  # never leave a half-open wheel swallowing every event
            return event

    AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(_WHEEL_EVENT_MASK, handler)


# ---------------------------------------------------------------------------- #
#  Progress report (File ▸ Open Colorflow Report…)
# ---------------------------------------------------------------------------- #
_REPORT_MENU_TITLE = "Open Colorflow Report…"
_REPORT_FAILED = "Couldn't build the AZ Colorflow report. The details are in the Macro panel."
_REPORT_MENU_HANDLER = None
_HISTORY_RECORDER = None
_REPORT_WINDOW = None  # the HTML report's window; dropped when it closes
_PUMP_STATE = {"last": 0.0}
_PUMP_INTERVAL = 1.0 / 60.0
# WKNavigationActionPolicy raw values, with named constants when WebKit has them.
_WK_CANCEL = getattr(WebKit, "WKNavigationActionPolicyCancel", 0) if WebKit else 0
_WK_ALLOW = getattr(WebKit, "WKNavigationActionPolicyAllow", 1) if WebKit else 1
# The chromeless window floats the traffic lights and the Save button over the page,
# and the drag strip owns the same band: push the report below it. The wide layout is
# a 100vh app with overflow hidden, so it shrinks by the same band.
_REPORT_TOPBAR_HEIGHT = 40.0
_REPORT_TOPBAR_SCRIPT = (
    "var azcfPad = document.createElement('style');"
    f" azcfPad.textContent = '@media screen {{ body {{ padding-top: {_REPORT_TOPBAR_HEIGHT:.0f}px"
    " !important; } }"
    " @media screen and (min-width:781px) { #cfd-app { height: calc(100vh -"
    f" {_REPORT_TOPBAR_HEIGHT:.0f}px) !important; }} }}';"
    " document.head.appendChild(azcfPad);"
)
_HISTORY_QUESTION = "Keep a color history in this file?"
_HISTORY_EXPLAINER = (
    "Each time you save, AZ Colorflow can store a small compressed snapshot of your "
    "glyph colors inside this .glyphs file. The report uses these snapshots to show "
    "your progress over time; without them it shows only the current state.\n\n"
    "The history travels with the file, so anyone you send it to gets it too. Change "
    "this any time in Glyphs ▸ Settings ▸ AZ Toolkit ▸ AZ Colorflow.\n\n"
    "Fonts tracked in git are never asked: their commits are the history."
)
_HISTORY_ALREADY_THERE = (
    "\n\nThis file already holds a history from an earlier version. With Don't "
    "Store it stays and still shows, but nothing is added to it."
)


def _pump_runloop() -> None:
    """Run the run loop once so the loader bar repaints while the build holds the main
    thread. Throttled to ~60 Hz. Input events stay queued: a click mid-build could
    change the font being reported."""
    now = time.monotonic()
    if now - _PUMP_STATE["last"] < _PUMP_INTERVAL:
        return
    _PUMP_STATE["last"] = now
    try:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.distantPast())
    except Exception:
        pass


class _AZColorflowLoaderBar(AppKit.NSView):
    # The workflow colors fill a rounded track with a live percentage. The build calls
    # set_progress() at each phase while _pump_runloop() keeps the view repainting; a
    # 30 Hz timer eases the shown value toward the latest milestone between calls.
    _SPECTRUM = (0, 1, 3, 4, 5, 6, 8, 9)  # red->green->blue->purple->pink (no browns/grays)

    @objc.python_method
    def configure(self, rgba_colors: list) -> None:
        raw = [rgba_colors[i] for i in self._SPECTRUM if i < len(rgba_colors)]
        if not raw:
            raw = list(rgba_colors)
        self._colors = [self._saturate(rgba, 1.6) for rgba in raw]
        self._value = 0.0  # shown fraction, eased toward _target
        self._target = 0.0  # latest milestone; never decreases
        self.start()

    @objc.python_method
    def _saturate(self, rgba: tuple, factor: float) -> tuple:
        hue, sat, val = colorsys.rgb_to_hsv(rgba[0], rgba[1], rgba[2])
        val = min(1.0, val * 1.15 + 0.12)  # bright as well as vivid, so the hues glow
        red, green, blue = colorsys.hsv_to_rgb(hue, min(1.0, sat * factor), val)
        return (red, green, blue, rgba[3] if len(rgba) > 3 else 1.0)

    @objc.python_method
    def start(self) -> None:
        self.stop()
        self._timer = AppKit.NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0 / 30.0, self, "tick:", None, True
        )
        NSRunLoop.currentRunLoop().addTimer_forMode_(self._timer, NSRunLoopCommonModes)

    @objc.python_method
    def stop(self) -> None:
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.invalidate()
        self._timer = None

    def tick_(self, timer: Any) -> None:
        self.setNeedsDisplay_(True)

    def viewDidMoveToWindow(self) -> None:
        if self.window() is None:
            self.stop()

    @objc.python_method
    def set_progress(self, frac: float) -> None:
        frac = min(1.0, max(0.0, float(frac)))
        if frac > getattr(self, "_target", 0.0):
            self._target = frac
        self.setNeedsDisplay_(True)

    @objc.python_method
    def _progress(self) -> float:
        # A quarter of the gap per tick, so the bar glides between milestones.
        target = getattr(self, "_target", 0.0)
        value = getattr(self, "_value", 0.0)
        value += (target - value) * 0.25
        if target - value < 0.002:
            value = target
        self._value = value
        return value

    def drawRect_(self, dirtyRect: Any) -> None:
        colors = getattr(self, "_colors", None) or []
        prog = self._progress()
        bounds = self.bounds()
        width = bounds.size.width
        height = bounds.size.height
        bar_h = 7.0
        pct_w = 46.0  # the percentage, right of the bar
        gap = 10.0
        bar_w = max(10.0, width - pct_w - gap)
        bar_y = (height - bar_h) / 2.0
        radius = bar_h / 2.0
        bar_rect = AppKit.NSMakeRect(0.0, bar_y, bar_w, bar_h)
        filled = prog * bar_w
        nscolors = [
            AppKit.NSColor.colorWithDeviceRed_green_blue_alpha_(rgba[0], rgba[1], rgba[2], 1.0)
            for rgba in colors
        ]
        blend = AppKit.NSGradient.alloc().initWithColors_(nscolors) if len(nscolors) >= 2 else None
        # A glow cast by the filled pill, drawn first and then covered by the track, so it
        # hugs the rounded bar instead of showing a rectangle behind it.
        if colors and prog > 0.0:
            mid = colors[len(colors) // 2]
            context = AppKit.NSGraphicsContext.currentContext()
            context.saveGraphicsState()
            glow = AppKit.NSShadow.alloc().init()
            glow.setShadowColor_(
                AppKit.NSColor.colorWithDeviceRed_green_blue_alpha_(mid[0], mid[1], mid[2], 0.55)
            )
            glow.setShadowBlurRadius_(bar_h * 0.9)
            glow.setShadowOffset_(AppKit.NSMakeSize(0.0, 0.0))
            glow.set()
            pill = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                AppKit.NSMakeRect(0.0, bar_y, filled, bar_h), radius, radius
            )
            AppKit.NSColor.colorWithDeviceRed_green_blue_alpha_(mid[0], mid[1], mid[2], 1.0).set()
            pill.fill()
            context.restoreGraphicsState()
        track = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            bar_rect, radius, radius
        )
        AppKit.NSColor.colorWithDeviceRed_green_blue_alpha_(0.137, 0.149, 0.180, 1.0).set()
        track.fill()
        if colors and prog > 0.0:
            context = AppKit.NSGraphicsContext.currentContext()
            context.saveGraphicsState()
            track.addClip()
            # Reveal the gradient up to the filled fraction: the colors stay anchored.
            AppKit.NSBezierPath.bezierPathWithRect_(
                AppKit.NSMakeRect(0.0, bar_y, filled, bar_h)
            ).addClip()
            if blend is not None:
                blend.drawInRect_angle_(bar_rect, 0.0)
            elif nscolors:
                nscolors[0].set()
                AppKit.NSRectFill(AppKit.NSMakeRect(0.0, bar_y, filled, bar_h))
            top = AppKit.NSColor.colorWithDeviceRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.30)
            bottom = AppKit.NSColor.colorWithDeviceRed_green_blue_alpha_(0.0, 0.0, 0.0, 0.16)
            sheen = AppKit.NSGradient.alloc().initWithStartingColor_endingColor_(top, bottom)
            if sheen is not None:
                sheen.drawInRect_angle_(bar_rect, -90.0)
            context.restoreGraphicsState()
        paragraph = AppKit.NSMutableParagraphStyle.alloc().init()
        paragraph.setAlignment_(AppKit.NSTextAlignmentRight)
        attributes = {
            AppKit.NSForegroundColorAttributeName: AppKit.NSColor.secondaryLabelColor(),
            AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(11.0),
            AppKit.NSParagraphStyleAttributeName: paragraph,
        }
        label = AppKit.NSAttributedString.alloc().initWithString_attributes_(
            f"{int(round(prog * 100))}%", attributes
        )
        text_h = label.size().height
        label.drawInRect_(AppKit.NSMakeRect(bar_w + gap, (height - text_h) / 2.0, pct_w, text_h))


class _AZColorflowReportDragStrip(AppKit.NSView):
    """Transparent strip over the report window's top band. WKWebView swallows mouse
    events, so without it the title-less window can't be dragged; scrolls go on to the
    page so the band isn't a dead scroll zone."""

    def mouseDown_(self, event: Any) -> None:
        window = self.window()
        if window is not None:
            window.performWindowDragWithEvent_(event)

    def scrollWheel_(self, event: Any) -> None:
        webview = getattr(self, "_webview", None)
        if webview is not None:
            webview.scrollWheel_(event)


class _AZColorflowReportWindow(AppKit.NSObject):
    """The HTML report in a WKWebView, byte-identical to the browser version: a Save…
    button in the title bar, web links sent to the browser. Rebuilt for the next
    report once closed."""

    _window: Any = None
    _webview: Any = None
    _path = ""

    def showPath_(self, path: Any) -> bool:
        self._path = str(path)
        if self._ensure_window() is None:
            return False
        try:
            file_url = AppKit.NSURL.fileURLWithPath_(self._path)
            read_access = AppKit.NSURL.fileURLWithPath_(str(Path(self._path).parent))
            self._webview.loadFileURL_allowingReadAccessToURL_(file_url, read_access)
            family = Path(self._path).stem.replace(" — AZ Colorflow", "")
            self._window.setTitle_(f"AZ Colorflow — {family}")
            self._window.makeKeyAndOrderFront_(None)
            return True
        except Exception:
            _report("report window")
            return False

    @objc.python_method
    def _ensure_window(self) -> Any:
        if getattr(self, "_window", None) is not None:
            return self._window
        try:
            config = WebKit.WKWebViewConfiguration.alloc().init()
            pad = WebKit.WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
                _REPORT_TOPBAR_SCRIPT, 1, True
            )  # 1 = WKUserScriptInjectionTimeAtDocumentEnd
            config.userContentController().addUserScript_(pad)

            # As big as the screen allows, up to 1440 x 1000, so the one-screen layout fits.
            screen = AppKit.NSScreen.mainScreen()
            width, height = 1180.0, 840.0
            if screen is not None:
                visible = screen.visibleFrame().size
                width = min(1440.0, visible.width)
                height = max(640.0, min(1000.0, visible.height - 40.0))
            rect = AppKit.NSMakeRect(0, 0, width, height)
            mask = (
                AppKit.NSWindowStyleMaskTitled
                | AppKit.NSWindowStyleMaskClosable
                | AppKit.NSWindowStyleMaskMiniaturizable
                | AppKit.NSWindowStyleMaskResizable
                | AppKit.NSWindowStyleMaskFullSizeContentView
            )
            window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                rect, mask, AppKit.NSBackingStoreBuffered, False
            )
            window.setReleasedWhenClosed_(False)
            window.setMinSize_(AppKit.NSMakeSize(800, 600))
            window.setFrameAutosaveName_("com.hugojourdan.ColorFlow.reportWindow")
            window.setDelegate_(self)
            # No visible title bar: the report fills the window and the traffic lights and
            # Save button float over it. The title stays set for Mission Control and ⌘`.
            window.setTitlebarAppearsTransparent_(True)
            window.setTitleVisibility_(AppKit.NSWindowTitleHidden)
            # The report is dark-only: keep the window chrome dark in light mode too.
            window.setAppearance_(
                AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameDarkAqua)
            )

            container = AppKit.NSView.alloc().initWithFrame_(rect)
            webview = WebKit.WKWebView.alloc().initWithFrame_configuration_(rect, config)
            webview.setNavigationDelegate_(self)
            webview.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
            container.addSubview_(webview)
            strip = _AZColorflowReportDragStrip.alloc().initWithFrame_(
                AppKit.NSMakeRect(
                    0,
                    rect.size.height - _REPORT_TOPBAR_HEIGHT,
                    rect.size.width,
                    _REPORT_TOPBAR_HEIGHT,
                )
            )
            strip._webview = webview
            strip.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewMinYMargin)
            container.addSubview_(strip)  # above the webview, so it owns the top band
            window.setContentView_(container)

            # Title-bar accessories size from their frame: an unpinned auto-layout stack
            # collapses to zero and the button never shows.
            save = AppKit.NSButton.buttonWithTitle_target_action_("Save…", self, "saveReport:")
            save.setControlSize_(AppKit.NSControlSizeSmall)
            save.setFont_(AppKit.NSFont.systemFontOfSize_(AppKit.NSFont.smallSystemFontSize()))
            save.setTranslatesAutoresizingMaskIntoConstraints_(True)
            save.sizeToFit()
            margin, bar_h = 10.0, 24.0
            size = save.frame().size
            holder = AppKit.NSView.alloc().initWithFrame_(
                AppKit.NSMakeRect(0, 0, size.width + margin, bar_h)
            )
            save.setFrameOrigin_((0.0, (bar_h - size.height) / 2.0))
            holder.addSubview_(save)
            accessory = AppKit.NSTitlebarAccessoryViewController.alloc().init()
            accessory.setView_(holder)
            accessory.setLayoutAttribute_(AppKit.NSLayoutAttributeTrailing)
            window.addTitlebarAccessoryViewController_(accessory)

            self._window = window
            self._webview = webview
            return window
        except Exception:
            _report("report window build")
            self._window = None
            return None

    def saveReport_(self, sender: Any) -> None:
        try:
            panel = AppKit.NSSavePanel.savePanel()
            panel.setNameFieldStringValue_(Path(self._path).name)
            if panel.runModal() == AppKit.NSModalResponseOK:
                shutil.copyfile(self._path, panel.URL().path())
        except Exception as error:
            _report("report save")
            reason = (
                "macOS has cleared the temporary report. Reopen the report, then save."
                if not Path(self._path).exists()
                else str(error)
            )
            Message(f"Couldn't save the report.\n\n{reason}", title="AZ Colorflow")

    def webView_decidePolicyForNavigationAction_decisionHandler_(
        self, webview: Any, action: Any, handler: Any
    ) -> None:
        try:
            url = action.request().URL()
            scheme = (url.scheme() or "").lower() if url is not None else ""
            if scheme in ("http", "https"):  # anything external goes to the browser
                AppKit.NSWorkspace.sharedWorkspace().openURL_(url)
                handler(_WK_CANCEL)
                return
            handler(_WK_ALLOW)
        except Exception:
            handler(_WK_ALLOW)

    # The report's animations pause while its window is hidden or in the background, so
    # they don't push 60 fps compositor commits through Glyphs' main thread.
    @objc.python_method
    def _set_spin_paused(self, paused: bool) -> None:
        webview = getattr(self, "_webview", None)
        if webview is None:
            return
        flag = "true" if paused else "false"
        webview.evaluateJavaScript_completionHandler_(
            f"window.__cfdSpinPause && window.__cfdSpinPause({flag});", None
        )

    @objc.python_method
    def _sync_spin_state(self) -> None:
        window = getattr(self, "_window", None)
        if window is None:
            return
        try:
            visible = bool(window.occlusionState() & AppKit.NSWindowOcclusionStateVisible)
            self._set_spin_paused(not (visible and window.isKeyWindow()))
        except Exception:
            _report("report window state")

    def windowDidBecomeKey_(self, notification: Any) -> None:
        self._sync_spin_state()

    def windowDidResignKey_(self, notification: Any) -> None:
        self._sync_spin_state()

    def windowDidChangeOcclusionState_(self, notification: Any) -> None:
        self._sync_spin_state()

    def windowWillClose_(self, notification: Any) -> None:
        global _REPORT_WINDOW
        try:
            self._webview.setNavigationDelegate_(None)
            self._window.setDelegate_(None)
        except Exception:
            _report("report window close")
        self._window = None
        self._webview = None
        _REPORT_WINDOW = None


def _show_report_window(path: Path) -> bool:
    """Open a written report in the report window; False when there is none to use."""
    global _REPORT_WINDOW
    if WebKit is None:
        return False
    try:
        if _REPORT_WINDOW is None:
            _REPORT_WINDOW = _AZColorflowReportWindow.alloc().init()
        return bool(_REPORT_WINDOW.showPath_(path))
    except Exception:
        _report("report window")
        return False


def _report_loader_panel() -> tuple[Any, Any]:
    """The "Generating…" sheet and its progress bar: ``(panel, loader)``."""
    rect = AppKit.NSMakeRect(0, 0, 256, 54)
    panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        rect, AppKit.NSWindowStyleMaskTitled, AppKit.NSBackingStoreBuffered, False
    )
    panel.setTitle_("AZ Colorflow")
    content = panel.contentView()
    label = AppKit.NSTextField.labelWithString_("Generating AZ Colorflow report…")
    label.setFrame_(AppKit.NSMakeRect(16, 30, 224, 16))
    content.addSubview_(label)
    loader = _AZColorflowLoaderBar.alloc().initWithFrame_(AppKit.NSMakeRect(16, 5, 224, 22))
    loader.configure(labelcolors.read_label_colors())
    content.addSubview_(loader)
    return panel, loader


def _ask_history_choice(font: Any) -> None:
    """At a font's first report, ask once whether its color history may be stored in
    the file. Git-tracked fonts are never asked: their commits are the history."""
    if font is None or azcolorflow_dashboard.history_choice(font) is not None:
        return
    if azcolorflow_dashboard.is_git_tracked(font):
        return
    alert = AppKit.NSAlert.alloc().init()
    alert.setMessageText_(_HISTORY_QUESTION)
    text = _HISTORY_EXPLAINER
    if azcolorflow_dashboard.load_history(font):
        text += _HISTORY_ALREADY_THERE
    alert.setInformativeText_(text)
    alert.addButtonWithTitle_("Store History")
    alert.addButtonWithTitle_("Don't Store").setKeyEquivalent_("\x1b")
    store = alert.runModal() == AppKit.NSAlertFirstButtonReturn
    azcolorflow_dashboard.set_history_choice(font, store)


def _build_behind_loader(build: Any) -> Any:
    """Run ``build(progress)`` behind the loader sheet and return its result, after the
    font's one-time history question. The sheet drops from the open report window (the
    report being refreshed), else the font's window; with neither the build runs bare."""
    _ask_history_choice(Glyphs.font)
    parent = getattr(_REPORT_WINDOW, "_window", None)
    if parent is None or not parent.isVisible():
        try:
            parent = Glyphs.font.parent.windowController().window()
        except Exception:
            parent = None
    if parent is None:
        return build(None)
    panel, loader = _report_loader_panel()
    parent.beginSheet_completionHandler_(panel, None)
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.08))  # paint

    def progress(frac: float) -> None:
        loader.set_progress(frac)
        _pump_runloop()

    try:
        result = build(progress)
        loader.set_progress(1.0)
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.3))
        return result
    finally:
        loader.stop()
        parent.endSheet_(panel)
        panel.orderOut_(None)


def _open_report() -> None:
    """Build the HTML report for the font in front and show it; rebuilt on every open,
    so an open report window reloads in place."""
    font = Glyphs.font
    if font is None:
        Message("Open a font first.", title="AZ Colorflow")
        return
    path = _build_behind_loader(
        lambda progress: azcolorflow_dashboard.main(font, progress=progress, open_when_done=False)
    )
    if path is not None and not _show_report_window(path):
        webbrowser.open(path.as_uri())


def _record_history(font: Any) -> bool:
    """Add the font's colors to the history in its file, when it may hold one; True
    when that wrote something (a save that changed no color adds nothing)."""
    if font is None or azcolorflow_dashboard.history_choice(font) is not True:
        return False
    if azcolorflow_dashboard.is_git_tracked(font):
        return False  # its commits are the history
    snapshot = azcolorflow_dashboard.build_master_glyph_colors(font)
    return azcolorflow_dashboard.record_history(font, snapshot, datetime.now())


class _AZHistoryRecorder(NSObject):
    """Records the color history at each save. Glyphs has no will-save hook, so the
    snapshot goes into userData just after the write, and one follow-up save puts it
    on disk. That save records nothing new, which ends the loop."""

    def documentDidSave_(self, notification: Any) -> None:
        try:
            document = notification.object()
            if document is None:
                return
            font = document.font() if document.respondsToSelector_(b"font") else document
            if not _record_history(font):
                return
            document.updateChangeCount_(AppKit.NSChangeDone)
            document.performSelector_withObject_afterDelay_("saveDocument:", None, 0.0)
        except Exception:
            _report("color history")


def _register_history_recorder() -> None:
    """Observe every successful save (once per session)."""
    global _HISTORY_RECORDER
    if _HISTORY_RECORDER is not None:
        return
    _HISTORY_RECORDER = _AZHistoryRecorder.alloc().init()
    # Glyphs' only save notification (GlyphsApp.DOCUMENTWASSAVED), posted after the write.
    NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
        _HISTORY_RECORDER, "documentDidSave:", "GSDocumentWasSavedSuccessfully", None
    )


class AZColorflowReportMenuHandler(NSObject):
    """File ▸ Open Colorflow Report…'s target, retained for the session."""

    def validateMenuItem_(self, menu_item: Any) -> bool:
        return Glyphs.font is not None

    def openReport_(self, sender: Any) -> None:
        try:
            _open_report()
        except Exception:
            _report("report")
            Message(_REPORT_FAILED, title="AZ Colorflow")


def _install_report_menu() -> None:
    """Add File ▸ Open Colorflow Report… (once per session)."""
    global _REPORT_MENU_HANDLER
    if _REPORT_MENU_HANDLER is not None:
        return
    handler = _REPORT_MENU_HANDLER = AZColorflowReportMenuHandler.alloc().init()
    item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        _REPORT_MENU_TITLE, "openReport:", ""
    )
    item.setTarget_(handler)
    menu = Glyphs.menu[FILE_MENU].submenu()
    for old in list(menu.itemArray()):  # a reloaded plugin finds its old item still there
        if old.title() == _REPORT_MENU_TITLE:
            menu.removeItem_(old)
    menu.addItem_(item)


# ---------------------------------------------------------------------------- #
#  Settings pane (Glyphs ▸ Settings ▸ AZ Toolkit ▸ AZ Colorflow)
# ---------------------------------------------------------------------------- #
# Posted after every Settings edit, so the bars and Font Glyph Order refresh.
COLORFLOW_SETTINGS_CHANGED = "AZColorflowSettingsChanged"

# The pane's tab identifier and its label (see initWithSettingsView_).
COLORFLOW_PREF_IDENTIFIER = "AZ Colorflow"

# Held module-globally so AppKit can't deallocate the pane.
_PREF_PANE_VC = None


def _broadcast_settings_changed() -> None:
    """Tell the Font-view bars and Font Glyph Order to re-read the settings."""
    NSNotificationCenter.defaultCenter().postNotificationName_object_(
        COLORFLOW_SETTINGS_CHANGED, None
    )


def _save_settings_text(font, text: str) -> None:
    """Write the steps where they are read from: the font's own copy when it has one,
    else its colorNames.txt; then broadcast."""
    if colornames.font_labels_text(font) is not None:
        font.userData[colornames.FONT_LABELS_KEY] = text
    else:
        colornames.write_color_names(
            colornames.resolve_key_file(colornames.font_dir_of(font)), text
        )
    _broadcast_settings_changed()


def _apply_color_order(font, new_visible_order: list[int]) -> None:
    """Reorder the shown steps."""
    rows, none_label = colornames.parse_settings(colornames.settings_text(font))
    rows = colornames.reorder_visible_rows(rows, new_visible_order)
    _save_settings_text(font, colornames.render_settings(rows, none_label))


def _poke_default_sort(font) -> None:
    """Make Glyphs re-sort the Font View: flipping ``storeSortName`` on a glyph and
    back triggers it, and leaves the glyph as it was."""
    try:
        if len(font.glyphs) == 0:
            return
        glyph = font.glyphs[0]
        stored = bool(glyph.storeSortName)
        glyph.storeSortName = not stored
        glyph.storeSortName = stored
    except Exception:
        _report("default sort poke")


def _set_glyph_order(font, on: bool) -> None:
    """The Settings checkbox: group the Font View by layer color, or restore the font's
    own order. Best-effort; broadcasts."""
    if font is None:
        return
    try:
        if on:
            if not fontview.is_enabled(font):
                fontview.enable(font)
        else:
            if fontview.is_enabled(font):
                fontview.disable(font)
            _poke_default_sort(font)
        _broadcast_settings_changed()
    except Exception:
        _report("Font Glyph Order")


def _glyph_order_on(font) -> bool:
    """Whether ``font`` has Font Glyph Order on (the Settings checkbox state)."""
    try:
        return font is not None and fontview.is_enabled(font)
    except Exception:
        return False


# Settings > Color Labels list.
_LC_ROW_H = 21.0
_LC_DOT = 12.0  # the color dot's diameter
_LC_GAP = 8.0  # eye -> dot -> name, the same both times
# No space between columns: the eye's column is as wide as the eye, and the dot sits
# centered in a column one gap wider than it on each side.
_LC_EYE_W = 17
_LC_COLOR_W = _LC_DOT + 2 * _LC_GAP
_DRAG_TYPE = "dev.azcolorflow.slotRow"


def _place_bezel(button: Any, right: float, center_y: float, width: float | None = None) -> None:
    """Put a push button's bezel itself, not vanilla's padded frame, ending at ``right``
    and centered on ``center_y`` (pane coordinates, y down); no ``width`` makes it square.
    Vanilla pads the frame for a bezel drawn inset within it, but Glyphs 4's buttons fill
    their frame, so the padding pushed them past the pane's margins."""
    height = button.intrinsicContentSize().height
    across = height if width is None else width
    top = center_y - height / 2
    parent = button.superview()
    if not parent.isFlipped():
        top = parent.frame().size.height - top - height
    rect = AppKit.NSMakeRect(right - across, top, across, height)
    button.setFrame_(button.frameForAlignmentRect_(rect))


def _color_dot(rgba: tuple) -> Any:
    """A filled circle of ``rgba`` for the color column, drawn at display time so it
    stays sharp on any screen."""
    color = AppKit.NSColor.colorWithDeviceRed_green_blue_alpha_(*rgba)

    def draw(rect: Any) -> bool:
        color.set()
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(rect).fill()
        return True

    return AppKit.NSImage.imageWithSize_flipped_drawingHandler_((_LC_DOT, _LC_DOT), False, draw)


class EyeToggleList2Cell(CheckBoxList2Cell):
    """The visibility column as an eye toggle (``eye.fill`` shown, ``eye.slash``
    hidden): a restyled CheckBox, so a click still updates the row and fires editCallback."""

    def __init__(self, editable=False, callback=None) -> None:
        super().__init__(editable=editable, callback=callback)
        button = self.getNSButton()
        button.setButtonType_(AppKit.NSButtonTypeToggle)
        button.setBordered_(False)
        button.setImagePosition_(AppKit.NSImageOnly)
        button.setImageScaling_(AppKit.NSImageScaleProportionallyDown)
        button.setTitle_("")
        symbol = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_
        button.setImage_(symbol("eye.slash", None))  # state OFF = hidden
        button.setAlternateImage_(symbol("eye.fill", None))  # state ON = shown


class AZColorflowSettingsView:
    """The Settings pane's vanilla controls. Global: built once per session and
    shared by every document window."""

    WIDTH = 320
    MARGIN = 12

    def __init__(self) -> None:
        self._slot_items: list[dict] = []
        self._recorder = None  # the trigger recorder's event monitor, while it listens
        self._history_font = self._history_in_git = None
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        # Positive, absolute coordinates only: vanilla resolves negative ones against the
        # parent's frame, ~0 wide when Glyphs first lays the pane out.
        font = self._shown_font = Glyphs.font
        self._shown_text = colornames.settings_text(font)
        margin = self.MARGIN
        inner = self.WIDTH - 2 * margin

        lc_help_y = 12
        lc_help_h = 28  # two lines, which stop short of the reset button on their right
        lc_list_y = lc_help_y + lc_help_h + 8
        # Every row in view, never a scroll: the table pads its rows 5 pt above and 10 pt
        # below, inside a 1 pt border.
        lc_list_h = int(12 * _LC_ROW_H + 17)
        fgo_order_y = lc_list_y + lc_list_h + 14
        bars_y = fgo_order_y + 24
        behind_y = bars_y + 22  # its sub-options, indented under it
        legend_y = behind_y + 22
        wheel_sep_y = legend_y + 30
        wheel_y = wheel_sep_y + 12
        wheel_check_w = 142  # "Show Color Wheel:", then the trigger button
        wheel_gap = 8  # label -> button; the button still ends with the separators
        history_sep_y = wheel_y + 30
        history_y = history_sep_y + 12
        height = history_y + 18 + margin
        self._height = height

        self.group = Group((0, 0, self.WIDTH, height))
        group = self.group
        # Vanilla sizes a Group from its parent and this one has none: set the frame before
        # adding children, which lay out against it.
        group.getNSView().setFrame_(AppKit.NSMakeRect(0, 0, self.WIDTH, height))

        group.resetButton = Button(
            (margin + inner - 24, lc_help_y, 24, 24), "", callback=self._reset_clicked
        )
        reset = group.resetButton.getNSButton()
        reset.setImage_(
            AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "arrow.clockwise", "Reset names and order"
            )
        )
        reset.setImagePosition_(AppKit.NSImageOnly)
        reset.setToolTip_("Reset names and order")
        _place_bezel(reset, margin + inner, lc_help_y + lc_help_h / 2)

        group.lcHelp = TextBox(
            (margin, lc_help_y, inner - 40, lc_help_h),
            "Double-click a name to rename it.\nClick the eye to hide, and drag to reorder.",
            sizeStyle="small",
        )

        # All 12 slots: eye, color dot, name. Shown rows drag to reorder; hidden rows
        # stay pinned below.
        group.lcList = List2(
            (margin, lc_list_y, inner, lc_list_h),
            self._slot_list_items(font),
            columnDescriptions=[
                dict(
                    identifier="visible",
                    title="",
                    cellClass=EyeToggleList2Cell,
                    editable=True,
                    width=_LC_EYE_W,
                ),
                dict(
                    identifier="color",
                    title="",
                    cellClass=ImageList2Cell,
                    width=_LC_COLOR_W,
                ),
                dict(identifier="name", title="", cellClass=EditTextList2Cell, editable=True),
            ],
            showColumnTitles=False,
            allowsSorting=False,
            allowsMultipleSelection=False,
            allowsEmptySelection=True,
            drawFocusRing=False,
            editCallback=self._slot_edited,
            dragSettings=dict(
                dragCandidateCallback=self._slot_drag_candidate,
                makeDragDataCallback=self._slot_make_drag_data,
            ),
            dropSettings=dict(
                pasteboardTypes=[_DRAG_TYPE],
                dropCandidateCallback=self._slot_drop_candidate,
                performDropCallback=self._slot_perform_drop,
            ),
        )
        group.lcList.getNSTableView().setRowHeight_(_LC_ROW_H)
        group.lcList.getNSTableView().setIntercellSpacing_((0.0, 0.0))  # macOS puts 17 pt
        scroll = group.lcList.getNSScrollView()
        scroll.setHasVerticalScroller_(False)
        scroll.setHasHorizontalScroller_(False)
        scroll.setVerticalScrollElasticity_(AppKit.NSScrollElasticityNone)
        scroll.setHorizontalScrollElasticity_(AppKit.NSScrollElasticityNone)

        # Font Glyph Order -----------------------------------------------------
        group.colorOrder = CheckBox(
            (margin, fgo_order_y, inner, 18),
            "Sort Glyph Order by colors",
            value=_glyph_order_on(font),
            callback=self._color_order_changed,
        )
        group.rowBars = CheckBox(
            (margin, bars_y, inner, 18),
            "Show color progress bars in Font View",
            value=_row_bars_enabled(),
            callback=self._row_bars_changed,
        )
        group.rowBarsBehind = CheckBox(
            (margin + 18, behind_y, inner - 18, 18),
            "Show bars behind categories",
            value=_row_bars_behind(),
            callback=self._row_bars_behind_changed,
        )
        group.rowBarsBehind.enable(_row_bars_enabled())
        group.rowBarsLegend = CheckBox(
            (margin + 18, legend_y, inner - 18, 18),
            "Show color meanings",
            value=_legend_enabled(),
            callback=self._legend_changed,
        )
        group.rowBarsLegend.enable(_row_bars_enabled())

        # Color Wheel ------------------------------------------------------------
        group.wheelSep = HorizontalLine((margin, wheel_sep_y, inner, 1))
        group.wheelEnabled = CheckBox(
            (margin, wheel_y, wheel_check_w, 18),
            "Show Color Wheel:",
            value=_wheel_enabled(),
            callback=self._wheel_enabled_changed,
        )
        group.wheelTrigger = Button(
            (
                margin + wheel_check_w + wheel_gap,
                wheel_y - 5,
                inner - wheel_check_w - wheel_gap,
                24,
            ),
            "",
            callback=self._record_wheel_trigger,
        )
        # 2 pt above the checkbox's center, which looks centered.
        _place_bezel(
            group.wheelTrigger.getNSButton(),
            margin + inner,
            wheel_y + 7,
            inner - wheel_check_w - wheel_gap,
        )
        group.wheelTrigger.getNSButton().setToolTip_(
            "Click, then hold any mix of ⌃ ⌥ ⌘ and click the mouse button that opens the "
            "wheel. ⇧ can't be one: in the wheel it colors every master."
        )
        self._show_wheel_trigger()
        group.wheelTrigger.enable(_wheel_enabled())

        # Report -----------------------------------------------------------------
        group.historySep = HorizontalLine((margin, history_sep_y, inner, 1))
        group.keepHistory = CheckBox(
            (margin, history_y, inner, 18),
            "Keep color history in this file",
            callback=self._keep_history_changed,
        )
        group.keepHistory.getNSButton().setToolTip_(
            "Each save stores a small snapshot of the glyph colors in the font's file, for "
            "the report's chart. Fonts tracked in git use their commits instead."
        )
        self._show_history(font)
        self._dim_hidden_rows()

    # ------------------------------------------------------------------ slot list
    def _slot_list_items(self, font) -> list[dict]:
        """All 12 label slots as List2 rows (slot, color, name, visible), shown rows
        first. Also cached in ``self._slot_items`` for the callbacks."""
        rgba_list = labelcolors.read_label_colors()
        rows, _none = colornames.parse_settings(colornames.settings_text(font))
        # Stable sort: shown rows first, each block keeping its workflow order.
        self._slot_items = [
            dict(
                slot=int(index),
                color=_color_dot(rgba_list[index]),
                name=label,
                visible=visible,
            )
            for index, label, visible in sorted(rows, key=lambda row: not row[2])
        ]
        return self._slot_items

    def _dim_hidden_rows(self) -> None:
        """Fade hidden rows so they read as inactive."""
        table = self.group.lcList.getNSTableView()
        for row, item in enumerate(self._slot_items):
            row_view = table.rowViewAtRow_makeIfNecessary_(row, True)
            if row_view is not None:
                row_view.setAlphaValue_(1.0 if item.get("visible") else 0.4)

    def _slot_drag_candidate(self, indexes) -> bool:
        """Only shown rows can be dragged."""
        return bool(indexes) and all(
            0 <= int(i) < len(self._slot_items) and self._slot_items[int(i)].get("visible")
            for i in indexes
        )

    def _slot_make_drag_data(self, index) -> dict:
        """Pack the dragged source row index onto the pasteboard for the self-reorder."""
        return {_DRAG_TYPE: int(index)}

    def _slot_drop_candidate(self, info) -> str:
        """Accept a self-move drop (rejects external drags, which carry no source)."""
        return "move" if info.get("source") is self.group.lcList else "none"

    def _slot_perform_drop(self, info) -> bool:
        """Move the dragged rows to the drop position (never below the hidden rows),
        then persist the new order."""
        try:
            sender = info.get("sender")
            source_indexes = sorted(
                int(i) for i in sender.getDropItemValues(info.get("items") or [], _DRAG_TYPE)
            )
            items = self._slot_items
            moved = [items[i] for i in source_indexes if 0 <= i < len(items)]
            if not moved or not all(item.get("visible") for item in moved):
                return False
            source_set = set(source_indexes)
            remaining = [item for pos, item in enumerate(items) if pos not in source_set]
            drop_index = info.get("index")
            visible_remaining = sum(1 for item in remaining if item.get("visible"))
            if drop_index is None:
                insert_at = visible_remaining
            else:
                insert_at = int(drop_index) - sum(1 for i in source_indexes if i < int(drop_index))
            # Keep the moved (visible) rows inside the visible block, above hidden rows.
            insert_at = max(0, min(visible_remaining, insert_at))
            new_items = remaining[:insert_at] + moved + remaining[insert_at:]
            self._slot_items = new_items
            self.group.lcList.set(new_items)
            self._dim_hidden_rows()
            new_order = [item["slot"] for item in new_items if item.get("visible")]
            _apply_color_order(Glyphs.font, new_order)
            return True
        except Exception:
            _report("pane slot drop")
            return False

    # ------------------------------------------------------------------ refresh
    def _reload_list(self) -> None:
        """Re-read the slots into the list."""
        self.group.lcList.set(self._slot_list_items(Glyphs.font))
        self._dim_hidden_rows()

    def follow_font(self, font) -> None:
        """Show ``font``'s steps and Font Glyph Order. Edits diff against what the
        list shows, so re-read when the font or its steps changed (another font's
        edit, a Save As next to another colorNames.txt)."""
        self._show_history(font)  # its answer may have come from the report since
        text = colornames.settings_text(font)
        if font is self._shown_font and text == self._shown_text:
            return
        self._shown_font, self._shown_text = font, text
        self._reload_list()
        self.group.colorOrder.set(_glyph_order_on(font))

    def _show_history(self, font) -> None:
        """Tick the history checkbox for ``font``; grayed without a font or for a
        git-tracked one, whose commits are its history."""
        if font is not self._history_font:  # asking git takes two processes: once per font
            self._history_font = font
            self._history_in_git = font is not None and azcolorflow_dashboard.is_git_tracked(font)
        stored = azcolorflow_dashboard.history_choice(font) is True
        self.group.keepHistory.enable(font is not None and not self._history_in_git)
        self.group.keepHistory.set(stored and not self._history_in_git)

    # ------------------------------------------------------------------ callbacks
    def _color_order_changed(self, sender) -> None:
        try:
            _set_glyph_order(Glyphs.font, bool(sender.get()))
        except Exception:
            _report("pane glyph order")

    def _row_bars_changed(self, sender) -> None:
        """Show or hide the color bars in every open Font-view sidebar."""
        try:
            on = bool(sender.get())
            Glyphs.defaults[_FONTVIEW_BARS_KEY] = on
            self.group.rowBarsBehind.enable(on)
            self.group.rowBarsLegend.enable(on)
            _broadcast_settings_changed()
        except Exception:
            _report("pane row bars")

    def _row_bars_behind_changed(self, sender) -> None:
        """Draw the bars behind the row names (Glyphs' row height) or under them."""
        try:
            Glyphs.defaults[_FONTVIEW_BARS_BEHIND_KEY] = bool(sender.get())
            _broadcast_settings_changed()
        except Exception:
            _report("pane row bars behind")

    def _legend_changed(self, sender) -> None:
        """Show or hide the color legend under the Font-view sidebar."""
        try:
            Glyphs.defaults[_FONTVIEW_LEGEND_KEY] = bool(sender.get())
            _broadcast_settings_changed()
        except Exception:
            _report("pane legend")

    def _wheel_enabled_changed(self, sender) -> None:
        """Store the checkbox for the next click; the trigger button works only while it
        is on."""
        try:
            on = bool(sender.get())
            Glyphs.defaults[_WHEEL_ENABLED_KEY] = on
            self._stop_recording()
            self.group.wheelTrigger.enable(on)
        except Exception:
            _report("pane color wheel")

    def _keep_history_changed(self, sender) -> None:
        try:
            azcolorflow_dashboard.set_history_choice(Glyphs.font, bool(sender.get()))
        except Exception:
            _report("pane history")

    def _show_wheel_trigger(self) -> None:
        trigger = azcolorflow_wheel.trigger_for(Glyphs.defaults[_WHEEL_TRIGGER_KEY])
        self.group.wheelTrigger.setTitle(azcolorflow_wheel.describe(trigger))

    def _stop_recording(self) -> None:
        if self._recorder is not None:
            AppKit.NSEvent.removeMonitor_(self._recorder)
            self._recorder = None
            self._show_wheel_trigger()

    def _record_wheel_trigger(self, sender) -> None:
        """Listen for the next click in this window: with the keys held, it is the new
        trigger. A key press or a click in another window cancels; a click that can't be
        a trigger (a plain left click, ⇧ held, a side button) beeps and cancels."""

        def handler(event: Any) -> Any:
            try:
                self._stop_recording()
                if event.window() != self.group.getNSView().window():
                    return event
                if event.type() == AppKit.NSEventTypeKeyDown:
                    return None
                trigger = azcolorflow_wheel.recorded_trigger(
                    int(event.type()), int(event.buttonNumber()), int(event.modifierFlags())
                )
                if trigger is None:
                    AppKit.NSBeep()
                else:
                    Glyphs.defaults[_WHEEL_TRIGGER_KEY] = azcolorflow_wheel.trigger_key(trigger)
                    self._show_wheel_trigger()
                return None
            except Exception:
                _report("pane trigger recorder")
                return event

        try:
            self._stop_recording()
            sender.setTitle("Hold keys and click…")
            self._recorder = AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                AppKit.NSEventMaskKeyDown
                | AppKit.NSEventMaskLeftMouseDown
                | AppKit.NSEventMaskRightMouseDown
                | AppKit.NSEventMaskOtherMouseDown,
                handler,
            )
        except Exception:
            _report("pane trigger recorder")

    def _reset_clicked(self, sender) -> None:
        """Confirm, then reset the steps' names, order and visibility to the defaults."""
        try:
            alert = AppKit.NSAlert.alloc().init()
            alert.setMessageText_("Reset names and order?")
            alert.setInformativeText_(
                "This restores the workflow names, order and visibility to their defaults."
            )
            alert.addButtonWithTitle_("Reset")
            alert.addButtonWithTitle_("Cancel")
            if alert.runModal() != AppKit.NSAlertFirstButtonReturn:
                return
            _save_settings_text(Glyphs.font, colornames.DEFAULT_COLOR_NAMES)
            self._reload_list()
        except Exception:
            _report("pane reset")

    def _slot_edited(self, sender) -> None:
        """After any cell edit. List2 can't say which column changed, so compare the rows
        with what is saved and write only on a change."""
        try:
            font = Glyphs.font
            rows, none_label = colornames.parse_settings(colornames.settings_text(font))
            shown = {
                int(item["slot"]): (str(item["name"]).strip(), bool(item["visible"]))
                for item in self._slot_items
            }
            edited = [(index, *shown[index]) for index, _label, _visible in rows]
            if edited == rows:
                return
            _save_settings_text(font, colornames.render_settings(edited, none_label))
            if any(new[2] != old[2] for new, old in zip(edited, rows, strict=True)):
                # Re-pin the row into the shown or hidden block. A rename skips this, so
                # typing keeps focus.
                self._reload_list()
        except Exception:
            _report("pane slot edit")


class AZColorflowPreferencesController(AppKit.NSViewController):
    """The Settings pane's view controller; the controls live on
    AZColorflowSettingsView."""

    def initWithSettingsView_(self, settings_view) -> Any:
        self = objc.super(AZColorflowPreferencesController, self).init()
        if self is None:
            return None
        self._settingsView = settings_view
        # The hub labels the tab with the title and selects it by representedObject.
        self.setTitle_(COLORFLOW_PREF_IDENTIFIER)
        self.setRepresentedObject_(COLORFLOW_PREF_IDENTIFIER)
        # NSTabView stretches our frame, so the size request goes through here.
        self.setPreferredContentSize_(AppKit.NSMakeSize(settings_view.WIDTH, settings_view._height))
        # Built once per session: re-sync to the front font whenever any window turns key
        # (a font switch, a close, or coming back to Settings).
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "windowDidBecomeKey:", AppKit.NSWindowDidBecomeKeyNotification, None
        )
        return self

    def loadView(self) -> None:
        self.setView_(self._settingsView.group.getNSView())

    def windowDidBecomeKey_(self, notification: Any) -> None:
        try:
            self._settingsView.follow_font(Glyphs.font)
        except Exception:
            _report("pane follow font")


# ---------------------------------------------------------------------------- #
#  AZ Toolkit Settings hub, shared by every AZ plugin (protocol v1.1, see CLAUDE.md)
# ---------------------------------------------------------------------------- #
# The hub takes the SELECTED pane's size, not the largest (v1.2): Glyphs' Settings
# window follows preferredContentSize live, top edge fixed.
_HUB_KEY = "AZToolkit.SettingsHub.v1"
_HUB_TITLE = "AZ Toolkit"
_POPUP_BAR_H = 41.0  # 10 top + 25 popup + 6 gap


def _open_settings_on(controller: Any) -> None:
    """Open Glyphs > Settings on a pane added with addViewToPreferences:.

    Glyphs 3 files the pane under its title, Glyphs 4 under its CLASS NAME, and an
    identifier it does not know raises — so the title is tried first and the
    class name catches the raise.
    """
    delegate = Glyphs.delegate()
    if delegate is None or not delegate.respondsToSelector_(b"showMainPreferencesWithIdentifier:"):
        return
    for identifier in (controller.title(), controller.className()):
        try:
            delegate.showMainPreferencesWithIdentifier_(identifier)
            return
        except Exception:
            continue


class AZColorflowToolkitHub(AppKit.NSViewController):
    def init(self) -> Any:
        self = objc.super(AZColorflowToolkitHub, self).init()
        if self is None:
            return None
        self._panes = []
        self._sizes = {}  # tab identifier -> the pane's designed (width, height)
        self.setTitle_(_HUB_TITLE)
        self.setRepresentedObject_(_HUB_TITLE)
        self.setPreferredContentSize_(AppKit.NSMakeSize(360.0, 240.0))
        return self

    def loadView(self) -> None:
        root = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 360, 240))
        popup = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
            AppKit.NSMakeRect(12, 240 - 35, 360 - 24, 25), False
        )
        popup.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewMinYMargin)
        popup.setTarget_(self)
        popup.setAction_("azToolkitPopupChanged:")
        tabs = AppKit.NSTabView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, 360, 240 - _POPUP_BAR_H)
        )
        tabs.setTabViewType_(AppKit.NSNoTabsNoBorder)
        tabs.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        root.addSubview_(popup)
        root.addSubview_(tabs)
        self._popup = popup
        self._tabs = tabs
        self.setView_(root)

    def azToolkitPopupChanged_(self, sender: Any) -> None:
        try:
            self._tabs.selectTabViewItemAtIndex_(sender.indexOfSelectedItem())
            self._fit_selected()
        except Exception:
            pass

    # Glyphs 4's Settings sidebar asks each pane for -imageName, then -image.
    def imageName(self) -> str:
        return "wrench.and.screwdriver"

    def image(self) -> Any:
        image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "wrench.and.screwdriver", _HUB_TITLE
        )
        image.setTemplate_(True)
        return image

    def addSettingsPane_(self, pane: Any) -> None:
        try:
            self.view()  # force loadView so _popup/_tabs exist
            tabs = self._tabs
            ident = pane.representedObject() or pane.title() or ""
            for index in range(tabs.numberOfTabViewItems()):
                if tabs.tabViewItemAtIndex_(index).identifier() == ident:
                    return  # already registered (e.g. two document windows)
            title = pane.title() or str(ident)
            label = title[3:] if title.startswith("AZ ") else title
            size = pane.preferredContentSize()
            view = pane.view()
            if size.width < 1 or size.height < 1:
                size = view.frame().size
            self._sizes[str(ident)] = (float(size.width), float(size.height))
            # Pin the pane at its designed size, top-left; the flexible right/bottom
            # margins absorb the stretch NSTabView applies to item views.
            container = AppKit.NSView.alloc().initWithFrame_(
                AppKit.NSMakeRect(0, 0, size.width, size.height)
            )
            view.setFrame_(AppKit.NSMakeRect(0, 0, size.width, size.height))
            view.setAutoresizingMask_(AppKit.NSViewMaxXMargin | AppKit.NSViewMinYMargin)
            container.addSubview_(view)
            item = AppKit.NSTabViewItem.alloc().initWithIdentifier_(ident)
            item.setLabel_(label)
            item.setView_(container)
            insert_at = tabs.numberOfTabViewItems()
            for index in range(tabs.numberOfTabViewItems()):
                if label < str(tabs.tabViewItemAtIndex_(index).label()):
                    insert_at = index
                    break
            tabs.insertTabViewItem_atIndex_(item, insert_at)
            # Popup shows the FULL plugin name ("AZ Colorflow"), not the stripped
            # tab label — the sort above still uses the label.
            self._popup.insertItemWithTitle_atIndex_(title, insert_at)
            if self._pane_licensed(pane):
                text = AppKit.NSMutableAttributedString.alloc().initWithString_attributes_(
                    title + "  ", {AppKit.NSFontAttributeName: AppKit.NSFont.menuFontOfSize_(0)}
                )
                text.appendAttributedString_(self._badge_string())
                self._popup.itemAtIndex_(insert_at).setAttributedTitle_(text)
            self._panes.append(pane)  # retain: AppKit must not dealloc the pane
            self._popup.selectItemAtIndex_(tabs.indexOfTabViewItem_(tabs.selectedTabViewItem()))
            self._fit_selected()
        except Exception:
            _report("toolkit hub addPane")

    @objc.python_method
    def _badge_string(self) -> Any:
        """The licensed badge after a plugin name: a white-on-accent seal symbol."""
        image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "checkmark.seal.fill", "licensed"
        )
        size_conf = AppKit.NSImageSymbolConfiguration.configurationWithPointSize_weight_(
            12.0, AppKit.NSFontWeightRegular
        )
        palette = AppKit.NSImageSymbolConfiguration.configurationWithPaletteColors_(
            [AppKit.NSColor.whiteColor(), AppKit.NSColor.controlAccentColor()]
        )
        image = image.imageWithSymbolConfiguration_(
            size_conf.configurationByApplyingConfiguration_(palette)
        )
        attachment = AppKit.NSTextAttachment.alloc().init()
        attachment.setImage_(image)
        size = image.size()
        # Center the seal on the menu font's cap height.
        offset_y = round((AppKit.NSFont.menuFontOfSize_(0).capHeight() - size.height) / 2.0)
        attachment.setBounds_(AppKit.NSMakeRect(0, offset_y, size.width, size.height))
        return AppKit.NSAttributedString.attributedStringWithAttachment_(attachment)

    @objc.python_method
    def _pane_licensed(self, pane: Any) -> bool:
        """Protocol v1.1: a pane MAY expose azLicensed (bought, not trial)."""
        return bool(pane.respondsToSelector_(b"azLicensed") and pane.valueForKey_("azLicensed"))

    def showSettingsPaneWithIdentifier_(self, identifier: Any) -> None:
        try:
            self.view()
            tabs = self._tabs
            for index in range(tabs.numberOfTabViewItems()):
                if tabs.tabViewItemAtIndex_(index).identifier() == identifier:
                    tabs.selectTabViewItemAtIndex_(index)
                    self._popup.selectItemAtIndex_(index)
                    break
            self._fit_selected()
        except Exception:
            pass
        try:
            _open_settings_on(self)
        except Exception:
            pass

    @objc.python_method
    def _fit_selected(self) -> None:
        """Size the hub to the selected pane (v1.2). AppKit pins the hub's view to
        preferredContentSize, so a shown Settings window resizes with it."""
        try:
            item = self._tabs.selectedTabViewItem()
            if item is None:
                return
            width, height = self._sizes.get(str(item.identifier()), (300.0, 200.0))
            self.setPreferredContentSize_(
                AppKit.NSMakeSize(max(300.0, width), max(200.0, height) + _POPUP_BAR_H)
            )
        except Exception:
            _report("toolkit hub size")


def _toolkit_hub() -> Any:
    """Find-or-create the shared AZ Toolkit hub (None if it can't be hosted)."""
    try:
        pool = AppKit.NSThread.mainThread().threadDictionary()
        hub = pool.objectForKey_(_HUB_KEY)
        if hub is not None:
            return hub
        delegate = Glyphs.delegate()
        if delegate is None or not delegate.respondsToSelector_(b"addViewToPreferences:"):
            return None
        hub = AZColorflowToolkitHub.alloc().init()
        pool.setObject_forKey_(hub, _HUB_KEY)  # retained here for the app's lifetime
        delegate.addViewToPreferences_(hub)
        return hub
    except Exception:
        _report("toolkit hub")
        return None


def _register_preferences_pane() -> None:
    """Add the AZ Colorflow tab to the shared AZ Toolkit Settings entry, once per session."""
    global _PREF_PANE_VC
    if _PREF_PANE_VC is not None:
        return
    hub = _toolkit_hub()
    if hub is None:
        return
    _PREF_PANE_VC = AZColorflowPreferencesController.alloc().initWithSettingsView_(
        AZColorflowSettingsView()
    )
    hub.addSettingsPane_(_PREF_PANE_VC)


# Glyphs' own setting (Settings ▸ Advanced ▸ App): "glyph", its default, or "layer".
_LABEL_SCOPE_KEY = "GSDefaultColorLabelScope"
_LABEL_SCOPE_ASKED_KEY = "com.hugojourdan.ColorFlow.labelScopeAsked"
_LABEL_SCOPE_QUESTION = "Set layer colors by default?"
_LABEL_SCOPE_LINKED = "layer colors"
_LABEL_SCOPE_LINK = "https://handbook.glyphsapp.com/glyph-display/#glyph-and-layer-colors"
_LABEL_SCOPE_EXPLAINER = (
    f"AZ Colorflow tracks progress with {_LABEL_SCOPE_LINKED}, so each master has its "
    "own. Right now a color label goes on the whole glyph, and on the layer only when "
    "you hold Option.\n\n"
    "Use Layer Colors swaps the two. Change it any time in Glyphs ▸ Settings… ▸ "
    "Advanced ▸ App ▸ Default color label scope."
)
_LABEL_SCOPE_TEXT_W = 220.0


def _label_scope_alert() -> Any:
    """The label-scope question, with Colorflow's icon and "layer colors" linked to the
    Glyphs Handbook. An alert's informative text can't hold a link, so the explainer
    is a text view in the accessory slot."""
    alert = AppKit.NSAlert.alloc().init()
    alert.setMessageText_(_LABEL_SCOPE_QUESTION)
    icon = AppKit.NSImage.alloc().initWithContentsOfFile_(str(Path(__file__).with_name("icon.png")))
    if icon is not None:
        alert.setIcon_(icon)
    # The size of an alert's own informative text: regular from macOS 26, small before.
    modern = AppKit.NSProcessInfo.processInfo().isOperatingSystemAtLeastVersion_((26, 0, 0))
    size = AppKit.NSFont.systemFontSize() if modern else AppKit.NSFont.smallSystemFontSize()
    text = AppKit.NSMutableAttributedString.alloc().initWithString_attributes_(
        _LABEL_SCOPE_EXPLAINER,
        {
            AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(size),
            AppKit.NSForegroundColorAttributeName: AppKit.NSColor.labelColor(),
        },
    )
    text.addAttribute_value_range_(
        AppKit.NSLinkAttributeName,
        AppKit.NSURL.URLWithString_(_LABEL_SCOPE_LINK),
        (_LABEL_SCOPE_EXPLAINER.index(_LABEL_SCOPE_LINKED), len(_LABEL_SCOPE_LINKED)),
    )
    view = AppKit.NSTextView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, _LABEL_SCOPE_TEXT_W, 1))
    view.setEditable_(False)
    view.setDrawsBackground_(False)
    view.textContainer().setLineFragmentPadding_(2)  # a text field's inset: lines up with the title
    view.textStorage().setAttributedString_(text)
    used = view.layoutManager().usedRectForTextContainer_(view.textContainer())
    view.setFrameSize_((_LABEL_SCOPE_TEXT_W, int(used.size.height) + 1))
    alert.setAccessoryView_(view)
    alert.addButtonWithTitle_("Use Layer Colors")
    alert.addButtonWithTitle_("Keep Glyph Colors").setKeyEquivalent_("\x1b")
    # An accessory view left-aligns the icon that a plain alert centers. NSAlert lets its
    # views move after layout(); only an icon on its own row above the text is moved, not
    # one beside the text (older macOS layouts).
    alert.layout()
    content = alert.window().contentView()
    below = content.convertRect_fromView_(view.bounds(), view)
    for icon_view in content.subviews():
        frame = icon_view.frame()
        if (
            icon_view.isKindOfClass_(AppKit.NSImageView)
            and abs(frame.origin.x - below.origin.x) < 1
            and frame.origin.y >= AppKit.NSMaxY(below)
        ):
            left = (content.bounds().size.width - frame.size.width) / 2
            icon_view.setFrameOrigin_((left, frame.origin.y))
    return alert


def _ask_label_scope() -> None:
    """Once per Mac, offer to make layer colors Glyphs' default: Colorflow reads them,
    and many users have never met them. Never asked when they are already the default."""
    if Glyphs.defaults[_LABEL_SCOPE_ASKED_KEY]:
        return
    Glyphs.defaults[_LABEL_SCOPE_ASKED_KEY] = True
    if Glyphs.defaults[_LABEL_SCOPE_KEY] == "layer":
        return
    if _label_scope_alert().runModal() == AppKit.NSAlertFirstButtonReturn:
        Glyphs.defaults[_LABEL_SCOPE_KEY] = "layer"


class AZColorflowLoader(GeneralPlugin):
    """Registers the Settings pane, the Font-view sidebar bars, the Font Glyph Order
    refresher, the color wheel, the report's File-menu item and the color history's
    save observer, each once per session, then asks the label-scope question. Under
    glyphs-cli it registers nothing: scripts there call ``azcolorflow.save_report``."""

    @objc.python_method
    def settings(self) -> None:
        self.name = "AZ Colorflow"

    @objc.python_method
    def start(self) -> None:
        # glyphs-cli runs plugins headless: no menus, windows or alerts to hook into.
        if os.environ.get("GLYPHS_HEADLESS"):
            return
        for label, register in (
            ("prefs pane", _register_preferences_pane),
            ("Font-view row bars", _register_fontview_row_bars),
            ("Font Glyph Order refresh", _register_glyph_order_refresh),
            ("color wheel", _register_color_wheel),
            ("report menu", _install_report_menu),
            ("color history", _register_history_recorder),
        ):
            try:
                register()
            except Exception:
                _report(label)
        # Default run-loop mode only: the alert waits for Glyphs' launch and any
        # startup dialog instead of landing over them.
        self.performSelector_withObject_afterDelay_("askLabelScope:", None, 1.0)

    def askLabelScope_(self, sender: Any) -> None:
        try:
            _ask_label_scope()
        except Exception:
            _report("label scope question")

    @objc.python_method
    def __file__(self) -> str:
        return __file__
