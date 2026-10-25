"""Inline assets + HTML shell for the Color Font Dashboard.

Turns the data model (see azcolorflow_dashboard.build_model) into one
self-contained, offline .html with inline CSS + inline vanilla JS. No network,
no dependencies. The model is the single source of truth the JS app renders.
"""

from __future__ import annotations

import base64
import gzip
import json
import re
from xml.sax.saxutils import escape as xesc

# A self-contained ``data:image/...`` URI, restricted to characters that are safe
# to drop into a double-quoted ``href`` attribute. The payload allowlist covers
# base64 (``A-Za-z0-9+/=``) and percent-encoded SVG markup, but deliberately
# excludes ``"`` ``'`` ``<`` ``>`` ``&`` ``\`` and every whitespace/control char,
# so a hostile favicon value cannot close the attribute or inject new ones.
_DATA_IMAGE_URI = re.compile(
    r"data:image/[a-zA-Z0-9.+-]+"  # image/<subtype>, e.g. png, svg+xml, x-icon
    r"(?:;[a-zA-Z0-9.+=-]+)*"  # optional parameters (e.g. ;charset=utf-8;base64)
    r",[A-Za-z0-9+/=%_.!~*()-]+\Z"  # required comma + non-empty payload
)


def embed_model(model: dict) -> str:
    """Serialise the model, gzip it, and embed as base64 in a non-executed
    ``<script>`` block. The client decompresses it with ``DecompressionStream``.
    base64's alphabet (``A-Za-z0-9+/=``) contains no ``<`` ``>`` ``&`` ``"``, so
    it can't terminate the script element or break any attribute — no escaping
    needed — and it shrinks the (outline-heavy) model ~4-5x on disk."""
    raw = json.dumps(model, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload = base64.b64encode(gzip.compress(raw, compresslevel=9)).decode("ascii")
    return f'<script type="application/octet-stream" id="cfd-model-gz">{payload}</script>'


def _color_overrides(model: dict) -> str:
    """A ``:root`` ``--cN`` override built from the model's per-color hexes, so the
    report follows the user's Glyphs label colors. Placed after the base stylesheet
    so it wins. Empty when the model carries no colors."""
    colors = model.get("colors") or {}
    if not colors:
        return ""
    rules = "".join(f"--c{key}:{value};" for key, value in sorted(colors.items()))
    return f"<style>:root{{{rules}}}</style>"


def _favicon_link(model: dict) -> str:
    """A ``<link rel="icon">`` carrying the bundled brand favicon as a self-contained
    ``data:`` URI (built by the model). Empty when the model has none, or when the
    value isn't a well-formed ``data:image/...`` URI — the favicon is interpolated
    raw into the ``href`` attribute, so anything that could close the attribute or
    add new ones (a ``"``, ``<``, ``>`` or whitespace) is rejected outright rather
    than escaped, to keep an attacker-supplied value from breaking the markup."""
    favicon = model.get("favicon")
    if not favicon or not isinstance(favicon, str):
        return ""
    if not _DATA_IMAGE_URI.fullmatch(favicon):
        return ""
    return f'<link rel="icon" href="{favicon}">'


def build_html(model: dict) -> str:
    """Assemble the complete, self-contained dashboard page from a model."""
    title = xesc(f"{model.get('family') or 'Untitled'} - Colorflow")
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title>{_favicon_link(model)}"
        f"<style>{DASHBOARD_CSS}</style>{_color_overrides(model)}</head>"
        '<body><div id="cfd-app"></div>'
        "<noscript>This report needs JavaScript — please open it in a modern browser.</noscript>"
        f"{embed_model(model)}"
        f"<script>{DASHBOARD_JS}</script>"
        "</body></html>"
    )


DASHBOARD_CSS = """
:root{
  --bg:#0a0b0e;--surface:#0e1014;--surface-2:#101217;--border:#1c1f26;--border-2:#23262e;
  --text:#e6e8ec;--muted:#9aa0ab;--muted-2:#7a818e;--accent:#9f75ff;--ok:#3fb950;
  --track:#15171c;--swatch-outline:rgba(255,255,255,.10);
  --tl-dot:#ffffff;--tl-vgrid:rgba(255,255,255,.10);
  --c-none:#060709;
  --c0:#f97e55;--c1:#ffbe68;--c2:#ba9d6d;--c3:#fff157;--c4:#c1ec8a;--c5:#6bab59;
  --c6:#64a5ef;--c7:#576ef1;--c8:#a962e7;--c9:#e77eb4;--c10:#c5c5c5;--c11:#5f5f5f;
  --r:10px;--r-sm:7px;
  --fs-base:15px;--fs-row:14px;--fs-sm:13px;--fs-xs:12px;--fs-2xs:11.5px;--fs-big:46px;--fs-big-sm:24px;
  color-scheme:dark;
}
*{box-sizing:border-box}
html,body{margin:0}
*{font-family:"JetBrains Mono",monospace}
body{background:var(--bg);color:var(--text);font:var(--fs-base)/1.5 "JetBrains Mono",monospace;
  font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased;opacity:0}
body.ready{opacity:1;transition:opacity .35s ease}
@media (prefers-reduced-motion:reduce){body,body.ready{opacity:1;transition:none}.seg.intro{animation:none}.tl-seed-shimmer .tl-seed-ghost{animation:none}.funnel.intro .fnl-fill{animation:none}.lb-fill.intro{animation:none}}
#cfd-app{max-width:1440px;margin:0 auto;padding:0 20px}
#cfd-main{display:flex;gap:16px;align-items:flex-start}
#cfd-tower{position:sticky;top:0;flex:0 0 240px;width:240px}
#cfd-tower canvas{display:block;width:240px;height:560px;cursor:pointer}
/* the master dropdown above the discs; a select has no ::after, so its box draws the caret */
.cfd-master-box{position:relative;margin:14px 0 4px}
/* the dropdowns' caret (master list, date): an equilateral triangle */
.cfd-master-box::after,.cal-btn::after{content:"";width:10px;aspect-ratio:1/.866;background:var(--muted);clip-path:polygon(0 0,100% 0,50% 100%)}
.cfd-master-box::after{position:absolute;top:50%;right:12px;transform:translateY(-50%);pointer-events:none}
.cfd-master-box:has(#cfd-master-x:not([hidden]))::after{display:none}   /* a picked master: its cross replaces the caret */
#cfd-master{display:block;width:100%;margin:0;padding:7px 32px 7px 12px;appearance:none;-webkit-appearance:none;font:inherit;font-size:var(--fs-sm);color:var(--text);background-color:var(--surface);border:1px solid var(--border);border-radius:8px;cursor:pointer}
#cfd-master:hover{border-color:var(--border-2)}
#cfd-master:focus-visible{outline:none}
#cfd-master-x,.cal-x{position:absolute;top:50%;right:8px;transform:translateY(-50%);display:flex;background:none;border:0;padding:4px;color:var(--muted);cursor:pointer}
#cfd-master-x:hover,.cal-x:hover{color:var(--text)}
#cfd-master-x[hidden]{display:none}
#cfd-body{flex:1 1 auto;min-width:0;min-height:0;overflow-y:auto;padding-right:6px}
/* wide screens: lock the window, scroll the body internally (page never grows) */
@media screen and (min-width:781px){html,body{height:100%;overflow:hidden}#cfd-app{height:100vh;display:flex;flex-direction:column}#cfd-main{flex:1 1 auto;min-height:0;overflow:hidden}#cfd-body{height:100%}}
@media (max-width:780px){#cfd-main{flex-direction:column;align-items:stretch}#cfd-tower{position:static;width:100%;flex:0 0 auto}#cfd-tower canvas,.cfd-master-box{margin-left:auto;margin-right:auto}.cfd-master-box{max-width:240px}#cfd-tower canvas{display:none}#cfd-body{overflow:visible;padding-right:0}}
.hd{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:10px;padding:14px 0;min-height:57px;background:var(--bg);border-bottom:1px solid var(--border)}
.hd .fam-logo{height:22px;width:auto;color:var(--text);display:block}
.hd .fam{font-weight:600}
.overall{display:flex;align-items:center;gap:16px;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:12px 16px;margin:16px 0}
.master-overall{margin-top:8px}
/* Changes list: glyphs whose color changed between the two picked versions,
   one group per change (Outline -> Ready), names wrapped, two columns. */
.chg-range{margin:-4px 0 8px;font-size:var(--fs-xs);color:var(--muted-2)}
.chg-ar{color:var(--muted-2)}
.chg-n{margin-left:auto;color:var(--muted-2);font-variant-numeric:tabular-nums}
.chg-t{width:100%;border-collapse:collapse;font-size:var(--fs-xs);table-layout:fixed}
.chg-cw{width:64px}  /* old -> new discs; long names end in an ellipsis */
.chg-gh th{text-align:left;font-weight:400;padding:6px 8px;background:var(--surface);border-bottom:1px solid var(--border-2)}
.chg-gh-in{display:flex;align-items:center;gap:6px;width:100%;background:none;border:0;padding:0;color:var(--text);font:inherit;text-align:left;cursor:pointer}
.chg-gh-in::after{content:"›";color:var(--muted-2);transition:transform .15s}
.chg-gh-in[aria-expanded=true]::after{transform:rotate(90deg)}
@media screen and (min-width:781px){.chg-gh th{position:sticky;top:0;z-index:1}}  /* #cfd-body scrolls; narrower, the page does under .hd/.tb */
.chg-r td{padding:4px 8px;border-top:1px solid var(--border);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chg-gh+.chg-r td{border-top:0}
.chg-r:hover td{background:var(--surface-2)}
.chg-r.ncnt td{opacity:.45}
.chg-nm{display:block;overflow:hidden;text-overflow:ellipsis}
.chg-c{display:flex;align-items:center;gap:6px;min-width:0}
.ov-main{flex:1;min-width:0}
.ov-head{display:flex;flex-wrap:wrap;align-items:baseline;column-gap:9px;font-size:17px;color:var(--muted);margin-bottom:8px}   /* the name, the % and its change: one size */
.ov-head b{color:var(--text);white-space:nowrap}
.ov-head:last-child{margin-bottom:0}   /* the family's card: no bar under it */
.ov-delta{font-weight:600;white-space:nowrap}
.ov-name{color:var(--text);font-weight:650;letter-spacing:-.01em;white-space:nowrap;margin-right:auto}   /* the % and its change on the right */
.seg{display:flex;height:10px;border-radius:5px;overflow:visible;background:var(--track)}
.seg>span{display:block;height:100%;transform-origin:left center;transition:opacity .2s ease;filter:saturate(1.2) brightness(1.08)}
.seg>span:first-child{border-radius:5px 0 0 5px}
.seg>span:last-child{border-radius:0 5px 5px 0}
.segc{cursor:pointer}
.seg>span.off{opacity:.28}
.seg>span.on{filter:saturate(1.18)}
@keyframes segGrow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.seg.intro{transform-origin:left center;animation:segGrow .5s ease backwards}
.funnel{margin-top:12px;display:flex;flex-direction:column;gap:5px}
.fnl-row{display:flex;align-items:center;gap:9px;width:100%;padding:1px 4px}
.fnl-row>i{flex:0 0 auto}
.fnl-lab{flex:0 0 146px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--fs-xs);color:var(--muted)}
.fnl-track{flex:1;height:9px;border-radius:5px;background:var(--track);overflow:hidden}
.fnl-fill{display:block;height:100%;border-radius:5px;transform-origin:left center;filter:saturate(1.2) brightness(1.08)}
.fnl-pct{flex:0 0 auto;min-width:38px;text-align:right;font-size:var(--fs-xs);font-variant-numeric:tabular-nums;color:var(--text)}
.fnl-empty{font-size:var(--fs-xs);color:var(--muted-2);padding:4px 5px}
.funnel.intro .fnl-fill{animation:segGrow .5s ease backwards}
.ovc-leaderboard .ov-card-body{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:30px;align-content:start}
.ovc-leaderboard .lb-row+.lb-row{border-top:0}
.ovc-week .wk-head{display:flex;align-items:baseline;gap:6px 24px;flex-wrap:wrap}
.wk-stat{display:flex;align-items:baseline;gap:7px}
.wk-delta{font-size:22px;font-weight:680;font-variant-numeric:tabular-nums}
.wk-sub{font-size:var(--fs-2xs);color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.ov-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 16px}
.ov-card-h{display:flex;align-items:center;justify-content:space-between;gap:8px;width:100%;margin:0 0 10px;padding:0;background:none;border:0;font:inherit;font-size:var(--fs-2xs);font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;text-align:left}
button.ov-card-h{cursor:pointer}
.lb-row{display:flex;align-items:center;gap:9px;width:100%;background:none;border:0;padding:3px 6px;border-radius:5px;cursor:pointer;color:var(--text);font:inherit;text-align:left}
.lb-row+.lb-row{border-top:1px solid var(--track)}
.lb-n{flex:1 1 auto;min-width:60px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--fs-xs)}
.lb-bar{flex:0 0 104px;height:7px;border-radius:4px;background:color-mix(in srgb,var(--text) 7%,transparent);overflow:hidden}   /* a tint, so it shows on a zebra row too */
.lb-bar>span{display:block;height:100%;background:color-mix(in srgb,var(--text) 62%,transparent);border-radius:4px;transform-origin:left center}
.lb-fill.intro{animation:segGrow .55s ease backwards;animation-delay:calc(var(--i,0)*45ms)}
.lb-p{flex:0 0 36px;text-align:right;font-size:var(--fs-xs);color:var(--muted)}
.lb-expand,.mg-x{display:flex;background:none;border:0;padding:4px;margin:-4px;color:var(--muted);cursor:pointer}
.lb-expand:hover,.mg-x:hover{color:var(--text)}
/* Masters' progress, expanded: a modal grid of each master's chart, 4 across at most; darker than
   the page so its cards stand out */
.mg-dlg{--mg-bg:color-mix(in srgb,var(--bg) 50%,#000)}
.mg-dlg{width:min(1120px,calc(100vw - 32px));max-height:calc(100vh - 32px);padding:0;background:var(--mg-bg);color:var(--text);border:1px solid var(--border-2);border-radius:12px}
.mg-dlg::backdrop{background:rgba(0,0,0,.6)}
.mg-in{padding:14px 16px 16px}
.mg-head{position:sticky;top:0;z-index:1;background:var(--mg-bg);display:flex;align-items:center;justify-content:space-between;margin:-14px -16px 2px;padding:14px 16px 10px;font-size:var(--fs-2xs);font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.mg-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px}
.mg-tile{display:block;width:100%;background:var(--surface-2);border:1px solid var(--border);border-radius:8px;padding:8px 10px 4px;color:var(--text);font:inherit;text-align:left;cursor:pointer}
.mg-tile:hover{border-color:var(--muted-2)}
.mg-h{display:flex;justify-content:space-between;gap:8px;font-size:var(--fs-xs)}
.mg-n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mg-p{color:var(--muted)}
.mg-tile .tl-grid{stroke:var(--border-2)}
.lb-row:hover .lb-bar>span{filter:brightness(1.18)}
/* Global<->Focus master switch: fade ONLY the data panels that change (not the chrome);
   the disc tower runs its own per-disc focus crossfade. */
.empty{font-size:var(--fs-sm);color:var(--muted-2)}
.tl-chart{width:100%;height:auto;display:block;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:4px}
.tl-grid{stroke:var(--track);stroke-width:1}
.tl-axis{fill:var(--muted-2);font-size:10px}
.tl-xtick{fill:var(--muted-2);font-size:9px}
.tl-crossarea{fill:transparent;cursor:pointer}
.tl-chart{cursor:pointer}
.tl-lanes-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 28px}
.tl-lanes-cat2{grid-template-columns:1fr}
.tl-lanes-cat2 .tl-lanes{column-count:2;column-gap:28px}
.tl-lanes-cat2 .tl-lanes>div{break-inside:avoid;-webkit-column-break-inside:avoid}
@media (max-width:680px){.tl-lanes-grid{grid-template-columns:1fr}}
.tl-band{stroke:none;fill-opacity:.4}
.tl-band-top{fill:none;stroke-width:1.4;stroke-linejoin:round;stroke-linecap:round;opacity:.92}
.tl-band.on{fill-opacity:.75}
.tl-band.off{fill-opacity:.08}
.tl-band-top.off{opacity:.2}
.rg-sw{display:inline-block;width:12px;height:12px;border-radius:50%;flex:none;box-shadow:inset 0 0 0 1px var(--swatch-outline)}
.rg-sw.none{position:relative;background:var(--c-none)}
.rg-sw.none::before,.rg-sw.none::after{content:"";position:absolute;left:5.25px;top:2.5px;width:1.5px;height:7px;border-radius:1px;background:var(--muted-2);transform:rotate(45deg)}
.rg-sw.none::after{transform:rotate(-45deg)}
.ov-pct{border:0;background:none;font:inherit;font-weight:700;color:var(--text);cursor:pointer;padding:0;vertical-align:baseline}
.ov-pct:hover{text-decoration:underline;text-decoration-style:dotted;text-underline-offset:2px}
.ov-chart{flex:1 1 320px;min-width:0;position:relative}
.tl-tip{position:absolute;top:26px;transform:translateX(-50%);display:flex;flex-direction:column;gap:2px;padding:6px 10px;background:var(--surface-2);border:1px solid var(--border-2);border-radius:7px;font-size:var(--fs-xs);color:var(--muted);pointer-events:none;white-space:nowrap;box-shadow:0 4px 14px rgba(0,0,0,.4)}
.tl-tip[hidden]{display:none}
.tl-tip b{color:var(--text);font-weight:600}
.ov-chart .tl-chart,.mg-tile .tl-chart{background:none;border:0;border-radius:0;padding:0}
.ov-chart .tl-axis,.ov-chart .tl-xtick{font-size:var(--fs-2xs)}
/* Chart + context: the chart card (lanes under it) on the left, the context panel on the
   right. On wide screens it fills #cfd-body: the chart takes the card's spare height and
   the panel scrolls inside. */
.ctx{display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,38%);gap:16px;padding:14px 0 12px}
.ctx-main{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:12px 16px;min-width:0}
.ctx-side{display:flex;flex-direction:column;gap:12px;min-width:0}
.ctx-side>*{margin:0}
.ctx-side .ovc-leaderboard .ov-card-body{grid-template-columns:minmax(0,1fr)}
.ctx-side .lb-row{background:none}
.ctx-side .lb-row:nth-child(even){background:color-mix(in srgb,var(--text) 3%,transparent)}
.ctx-side.more{-webkit-mask-image:linear-gradient(#000 calc(100% - 36px),transparent);mask-image:linear-gradient(#000 calc(100% - 36px),transparent)}
.ctx-side .lb-row.on{background:color-mix(in srgb,var(--accent) 24%,transparent)}
.ovc-versions .lb-p{flex-basis:52px}
.chart-top{display:flex;align-items:center;gap:12px;margin:0 0 4px}
.ov-unfocus{background:var(--surface-2);border:1px solid var(--border-2);border-radius:6px;color:var(--text);font:inherit;font-size:var(--fs-xs);font-weight:500;padding:2px 10px;cursor:pointer}
.cal{position:relative;margin-left:auto}
.cal-btn{display:flex;align-items:center;gap:6px;background:var(--track);border:1px solid var(--border);border-radius:7px;color:var(--text);font:inherit;font-size:var(--fs-xs);font-variant-numeric:tabular-nums;padding:3px 9px;cursor:pointer}   /* stroked like the master list; 1px less padding keeps its size */
.cal-btn.picked{padding-right:25px}.cal-btn.picked::after{display:none}   /* a picked date: its cross replaces the caret */
.cal-x{right:6px}
.cal-btn:hover{background:var(--surface-2);border-color:var(--border-2)}
.cal-pop{position:absolute;right:0;top:calc(100% + 6px);z-index:5;width:224px;padding:10px;background:var(--surface-2);border:1px solid var(--border-2);border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.45)}
.cal-h{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;font-size:var(--fs-xs);font-weight:600;color:var(--text)}
.cal-nav{background:none;border:0;border-radius:5px;color:var(--muted);font:inherit;font-size:16px;line-height:1;padding:2px 8px;cursor:pointer}
.cal-nav:hover{color:var(--text);background:var(--track)}
.cal-nav:disabled{opacity:.3;cursor:default;background:none}
.cal-g{display:grid;grid-template-columns:repeat(7,1fr);gap:2px;text-align:center;font-size:var(--fs-2xs);font-variant-numeric:tabular-nums}
.cal-w{padding:2px 0;color:var(--muted-2)}
.cal-d{padding:5px 0;border-radius:6px;color:var(--muted-2);opacity:.6}   /* no version that day */
button.cal-d{opacity:1;background:none;border:0;font:inherit;font-weight:600;color:var(--text);cursor:pointer}
button.cal-d:hover{background:var(--track)}
button.cal-d.on{background:color-mix(in srgb,var(--accent) 52%,#15131c);color:#fff}
@media screen and (min-width:781px){
  .ctx{height:100%;grid-template-rows:minmax(0,1fr)}
  .ctx-main{display:flex;flex-direction:column;min-height:0;overflow-y:auto}
  .ctx-main .ov-chart{flex:1 1 0;min-height:160px;overflow:hidden}
  .ctx-side{min-height:0;overflow-y:auto;padding-right:4px}
}
@media (max-width:780px){.ctx{grid-template-columns:minmax(0,1fr)}}
.tl-d-up{color:var(--ok)}
.tl-d-down{color:var(--c0)}
.tl-d-flat{color:var(--muted-2)}
.tri{display:inline-block;width:.62em;aspect-ratio:1/.866;background:currentColor;clip-path:polygon(50% 0,100% 100%,0 100%)}   /* equilateral, unlike the font's ▲ */
.tri.down{clip-path:polygon(0 0,100% 0,50% 100%)}
.tl-seed{border:1px solid var(--border-2);border-radius:var(--r);background:var(--surface-2);padding:16px}
.tl-seed-head{font-weight:600;color:var(--text);margin-bottom:10px}
.tl-seed-sub{font-size:var(--fs-xs);color:var(--muted);margin:10px 0}
.tl-seed-svg{display:block;width:100%;max-width:360px;height:auto}
.tl-seed-ghost{stroke:var(--muted-2);fill:var(--muted-2);opacity:.4}
.tl-seed-line{fill:none;stroke-width:2;stroke-dasharray:4 4;stroke-linecap:round;stroke-linejoin:round}
.tl-seed-dot{stroke:none}
.tl-seed-today{fill:var(--accent);stroke:var(--bg);stroke-width:1.5}
@keyframes tlSeedShimmer{0%{opacity:.25}50%{opacity:.55}100%{opacity:.25}}
.tl-seed-shimmer .tl-seed-ghost{animation:tlSeedShimmer 1.8s ease-in-out infinite}
.tl-lanes{margin-top:14px;border-top:1px solid var(--border);padding-top:12px}
.tl-lane{display:flex;align-items:center;gap:10px;font-size:var(--fs-xs);color:var(--text);padding:4px 0}
.tl-lane+.tl-lane{border-top:1px solid var(--track)}
.tl-lane-n{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tl-lane-n small{color:var(--muted-2)}
.tl-lane-mid{flex:0 0 64px;display:flex;align-items:center;justify-content:center;height:16px}
.tl-lane-spark polyline{stroke:var(--muted);stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round;vector-effect:non-scaling-stroke}
.tl-lane.done .tl-lane-spark polyline{stroke:var(--ok)}
.tl-lane-pct{flex:0 0 auto;color:var(--text);font-variant-numeric:tabular-nums;text-align:right;min-width:34px}
.tl-lane-d{flex:0 0 auto}
.tl-lane[data-lane]{cursor:pointer;transition:opacity .2s}
.tl-lanes-grid.picking .tl-lane:not(.on){opacity:.4}   /* a picked lane: the others dim */
.tl-lanes-grid.picking .tl-lane:not(.on):hover{opacity:.75}
.tl-lane:focus-visible{outline:1px solid var(--border-2);outline-offset:2px;border-radius:4px}
.tl-scrubline{stroke:var(--accent);stroke-width:1.5;stroke-dasharray:3 3;opacity:.85;pointer-events:none}
.tl-hoverline{stroke:var(--muted-2);stroke-width:1;stroke-dasharray:3 3;pointer-events:none}   /* the version under the pointer */
.tl-scrubdot{fill:var(--accent);pointer-events:none}
/* In the Timeline calendar pane, stretch the month grid to the full available width
   (square cells grow with it); the compact Overview mini-calendar keeps its 28px cells. */
            /* half-height day cells (calendar 2x shorter) */
.ft{margin-top:24px;padding:12px 0 18px;border-top:1px solid var(--border);font-size:10px;color:var(--muted-2);line-height:1.4;display:flex;justify-content:space-between;gap:12px}
.ft-r{text-align:right}
/* Boot-failure card (start()'s catch). Pure CSS — it must render when the embedded
   model is broken, so the rainbow brand mark is a hard-coded gradient, not --cN data.
   Built from the theme tokens (--surface/--border/--text/--muted). */
.err-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
.err-card{max-width:460px;text-align:center;background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:34px 32px}
.err-mark{display:block;width:52px;height:10px;border-radius:5px;margin:0 auto 18px;background:linear-gradient(90deg,#f97e55,#ffbe68,#fff157,#6bab59,#64a5ef,#a962e7)}
.err-title{margin:0 0 10px;font-size:var(--fs-base);font-weight:600;color:var(--text)}
.err-msg{margin:0;font-size:var(--fs-xs);line-height:1.5;color:var(--muted);font-family:"JetBrains Mono",monospace;word-break:break-word}
button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
"""


DASHBOARD_JS = r"""
(function(){
  "use strict";
  var H, lastOrder;   // assigned once the gzipped model is decompressed (see start())

  var state = {
    master: null,                          // no master selected -> global overview
    focus: null,
    funnelOpen: false,                     // per-step funnel: collapsed by default, toggled by the master's % number
    chgOpen: {},                           // Changed groups opened, by color key (all closed at first)
    tlScrub: null,                         // picked version (snapshot index; null -> now)
    lane: null,                            // the category/script the chart narrows to ("cat:Letter", "scr:latin"); null = every glyph
    cal: null                              // the date picker's shown month ("YYYY-MM"); null = closed
  };
  // The color bar runs its fill animation once, on the first paint only — not on
  // master switches or any later re-render.
  var barsAnim = false, introPlayed = false;
  var scrubAnim = false;                        // a moment was just picked (scrub): animate the bars/cells/lines that follow it
  var lastRenderMaster = "__cfd_init__";              // last-rendered state.master, to fade cards+discs on a Global<->Focus switch
  var lastRenderLane = null;                    // last-rendered state.lane: a new pick morphs the chart too
  var sparkPrev = {};                           // last-rendered lane sparkline points per key, so the line can morph on scrub
  var laneNumCache = {};                        // last-shown lane % per lane key, for count-up tweening

  function esc(s){ return String(s).replace(/[&<>"]/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]; }); }
  function pct(n,t){ return t ? Math.round(n/t*100) : 0; }
  // WebKit (and therefore the plugin's embedded WKWebView) does not support canvas 2D
  // ctx.filter, so the disc/script-card blur silently no-ops there (hard wedges). Probe
  // once; the browser path (filter works) is untouched, and the canvas filters below
  // fall back to softFilter, which reproduces them in JS.
  var CTX_FILTER_OK = (function(){
    try {
      var c = document.createElement("canvas"); c.width = c.height = 9;
      var g = c.getContext("2d");
      g.fillStyle = "#fff"; g.fillRect(0, 0, 9, 9);
      g.filter = "blur(2px)"; g.fillStyle = "#000"; g.fillRect(0, 0, 4, 9); g.filter = "none";
      var p = g.getImageData(4, 4, 1, 1).data;
      return p[0] > 20 && p[0] < 235;            // boundary pixel is mid-gray only if blurred
    } catch(e){ return false; }
  })();
  // WebKit stand-in for drawing src through ctx.filter = "blur(sigma px) saturate(sat)
  // brightness(bright)": returns a new canvas the size of src. As in Chrome, sigma is in
  // bitmap px (the CTM doesn't scale it) and the blur fades to transparent past the
  // edges. A premultiplied Gaussian on a copy shrunk to sigma ~3px (so wide blurs stay
  // fast), then the CSS color matrices: within ~1/255 of Chrome's own filter.
  function blurPass(src, dst, w, h, kern, horiz){
    var r = (kern.length-1)/2, n = horiz ? w : h, lines = horiz ? h : w, step = horiz ? 4 : w*4;
    for (var l=0; l<lines; l++){
      var base = horiz ? l*w*4 : l*4;
      for (var x=0; x<n; x++){
        var c0=0, c1=0, c2=0, c3=0, hi=Math.min(n-1, x+r);
        for (var t=Math.max(0, x-r); t<=hi; t++){
          var k = kern[t-x+r], p = base+t*step;
          c0+=src[p]*k; c1+=src[p+1]*k; c2+=src[p+2]*k; c3+=src[p+3]*k;
        }
        var q = base+x*step; dst[q]=c0; dst[q+1]=c1; dst[q+2]=c2; dst[q+3]=c3;
      }
    }
  }
  // small: shrink to sigma ~1 and return the shrunk canvas (its full width in __w) for
  // the caller to upscale as it draws, ~6x faster and ~60x lighter than the full copy.
  function softFilter(src, sigma, sat, bright, small){
    var w = src.width, h = src.height, shrink = Math.max(1, Math.round(small ? sigma : sigma/3));
    var sw = Math.max(1, Math.round(w/shrink)), sh = Math.max(1, Math.round(h/shrink));
    var s = sigma*sw/w, i;
    // willReadFrequently keeps the scratch canvases on the CPU: a GPU-backed one makes
    // every getImageData wait for the GPU to flush.
    var t = document.createElement("canvas"); t.width = sw; t.height = sh;
    var tg = t.getContext("2d", {willReadFrequently:true});
    tg.imageSmoothingEnabled = true; tg.imageSmoothingQuality = "high";
    tg.drawImage(src, 0, 0, sw, sh);
    var img = tg.getImageData(0, 0, sw, sh), d = img.data, n = sw*sh*4;
    var a = new Float32Array(n), b = new Float32Array(n);
    for (i=0; i<n; i+=4){ var al = d[i+3]/255; a[i]=d[i]*al; a[i+1]=d[i+1]*al; a[i+2]=d[i+2]*al; a[i+3]=d[i+3]; }
    if (s > 0.05){
      var r = Math.ceil(s*3), kern = [], sum = 0;
      for (i=-r; i<=r; i++){ var v = Math.exp(-i*i/(2*s*s)); kern.push(v); sum += v; }
      for (i=0; i<kern.length; i++) kern[i] /= sum;
      blurPass(a, b, sw, sh, kern, true); blurPass(b, a, sw, sh, kern, false);
    }
    var m = [0.213+0.787*sat, 0.715-0.715*sat, 0.072-0.072*sat,
             0.213-0.213*sat, 0.715+0.285*sat, 0.072-0.072*sat,
             0.213-0.213*sat, 0.715-0.715*sat, 0.072+0.928*sat];
    for (i=0; i<n; i+=4){
      var A = a[i+3], R = 0, G = 0, B = 0;
      if (A > 0){ R = a[i]*255/A; G = a[i+1]*255/A; B = a[i+2]*255/A; }
      d[i]   = Math.min(255, Math.max(0, m[0]*R+m[1]*G+m[2]*B))*bright;
      d[i+1] = Math.min(255, Math.max(0, m[3]*R+m[4]*G+m[5]*B))*bright;
      d[i+2] = Math.min(255, Math.max(0, m[6]*R+m[7]*G+m[8]*B))*bright;
      d[i+3] = A;
    }
    tg.putImageData(img, 0, 0);
    if (small){ t.__w = w; return t; }
    var out = document.createElement("canvas"); out.width = w; out.height = h;
    var og = out.getContext("2d");
    og.imageSmoothingEnabled = true; og.imageSmoothingQuality = "high";
    og.drawImage(t, 0, 0, w, h);
    out.__t = t;
    return out;
  }
  function varFor(k){ return k===-1 ? "--c-none" : "--c"+k; }
  // A legend swatch dot that glows in its own color (matches the progress-bar glow).
  function legendDot(key){
    var v = varFor(key);
    return '<i style="background:var('+v+');box-shadow:inset 0 0 0 1px var(--swatch-outline),'
      + '0 0 7px color-mix(in srgb,var('+v+') 26%,transparent)"></i>';
  }
  function labelFor(k){
    if (k===-1 || String(k)==="-1") return H.noneLabel;
    // steps keys are ints, but callers pass H.order keys (strings) too — compare as
    // strings so the real label is returned (not the "Color N" fallback).
    for (var i=0;i<H.steps.length;i++){ if (String(H.steps[i].key)===String(k)) return H.steps[i].label; }
    return "Color "+k;
  }
  // A glyph painted with a HIDDEN color (a label hidden in the plugin) is not a
  // workflow step, so it must read as uncolored EVERYWHERE — otherwise it shows as a
  // phantom color the ring/breakdown deny, paints a stray wedge on the disc, and lands
  // in "None" while still tinted its real color. Rewrite any per-master key that isn't
  // in the visible order to -1, once, at load. (stateAt does the same for the timeline.)
  function normalizeHiddenKeys(){
    var inOrder = {}; (H.order||[]).forEach(function(k){ inOrder[String(k)] = 1; });
    (H.masters||[]).forEach(function(m){
      var ks = m.keys; if (!ks) return;
      for (var i=0;i<ks.length;i++){ if (ks[i] !== -1 && !inOrder[String(ks[i])]) ks[i] = -1; }
    });
  }
  function masterById(id){
    for (var i=0;i<H.masters.length;i++){ if (H.masters[i].id===id) return H.masters[i]; }
    return H.masters[0];
  }
  // A clickable segment of a stacked color bar. Clicking it focuses every glyph
  // with that color in the heatmap and dims the rest (state.focus). key -1 = None.
  function segSpan(key,w,lab,idx){
    if (!w) return "";
    var on = state.focus===key;
    var off = state.focus!==null && !on;   // a color is focused and it isn't this one
    return '<span class="segc'+(on?" on":"")+(off?" off":"")+'" data-fkey="'+key+'" style="width:'+w
      + '%;background:var('+varFor(key)+');--i:'+(idx||0)
      + ';box-shadow:0 0 9px color-mix(in srgb,var('+varFor(key)+') 22%,transparent),inset -6px 0 9px -3px rgba(0,0,0,.2)" title="'+esc(lab)+' — click to focus these glyphs"></span>';
  }
  // ----- Non-exporting exclusion ---------------------------------------------
  // Glyphs marked non-exporting in Glyphs (H.nonExporting) are ALWAYS dropped
  // from every completion percentage, matching the palette. PARITY: the
  // embedded masters[].counts/keys always ship ALL glyphs (raw truth); the
  // exclusion is applied HERE, client-side, so the displayed numbers match
  // the palette's. countedSet() centralises the exclusion: null when nothing
  // to exclude (every glyph exports), else a {name:1} lookup of the glyphs
  // that DO count. Heatmap cells of excluded glyphs dim (.ncnt) instead of
  // vanishing.
  var COUNTED = null, COUNTEDN = 0;            // memo; the exclusion never changes after load
  function countedSet(){
    if (!(H.nonExporting||[]).length) return null;
    if (COUNTED) return COUNTED;
    var off = {}; (H.nonExporting||[]).forEach(function(n){ off[n]=1; });
    var set = {}, n = 0;
    (H.glyphNames||[]).forEach(function(nm){ if (!off[nm]){ set[nm]=1; n++; } });
    COUNTEDN = n;
    return (COUNTED = set);
  }
  function isCounted(name){ var set = countedSet(); return !set || !!set[name]; }
  function countedTotal(){ return countedSet() ? COUNTEDN : (H.glyphTotal||0); }
  // Per-master tallies with the exclusion applied (memoised; consulted whenever
  // the font has non-exporting glyphs): the m.counts / m.uncolored equivalents,
  // recomputed from the raw m.keys. The cumulative "reached k or beyond" count
  // is the suffix sum of the exclusive distribution in workflow order.
  var CSTATS = {};
  function countedStats(m){
    if (CSTATS[m.id]) return CSTATS[m.id];
    var set = countedSet(), ks = m.keys||[], names = H.glyphNames||[];
    var dist = {}, none = 0;
    for (var i=0;i<ks.length;i++){
      if (set && !set[names[i]]) continue;
      var k = ks[i], sk = String(k);
      if (k===-1 || H.order.indexOf(sk)===-1) none++; else dist[sk]=(dist[sk]||0)+1;
    }
    var counts = {}, run = 0, order = H.order||[];
    for (var j=order.length-1;j>=0;j--){
      var key = order[j];
      run += dist[key]||0; counts[key] = run;
    }
    return (CSTATS[m.id] = { dist:dist, counts:counts, uncolored:none });
  }
  // Exclusive current-color tally for a master: how many glyphs sit at EACH color
  // right now (memoised per master). m.counts is cumulative ("reached step k or
  // beyond"), which made every earlier step inherit the most-advanced count — so the
  // legend/compare must use this, not m.counts, to match the stacked bar.
  var EXCL = {};
  // cumulative: glyphs that reached step k OR BEYOND (the model's m.counts). This is
  // the workflow-completion metric used by the legends and Compare grid.
  // With non-exporting glyphs present the counted recompute stands in for m.counts.
  function countFor(m,k){
    if (countedSet()){ var cs = countedStats(m); return k===-1 ? cs.uncolored : (cs.counts[String(k)]||0); }
    return k===-1 ? m.uncolored : (m.counts[String(k)]||0);
  }
  function uncoloredFor(m){ return countedSet() ? countedStats(m).uncolored : m.uncolored; }

  function header(){
    var fam = (H.logo && H.logo.d)
      ? '<svg class="fam-logo" viewBox="'+esc(H.logo.vb)+'" preserveAspectRatio="xMidYMid meet" role="img" aria-label="'+esc(H.family)+'"><path d="'+esc(H.logo.d)+'" fill="currentColor"/></svg>'
      : '<span class="fam">'+esc(H.family)+'</span>';
    return '<header class="hd">'+fam+'</header>';
  }
  // ----- Graded step progress -----------------------------------------------
  // Each color is a workflow step ranked by the Palette order; a glyph sitting
  // at step i of N counts as i/N (first step = 1/N, final = 100%). N = the shown
  // (labelled) colors actually used across the whole font, kept in Palette order.
  // Uncolored, hidden and off-palette glyphs count as 0, as they read everywhere else.
  var STEPW = null;
  function stepWeights(){
    if (STEPW) return STEPW;
    var used = {};
    H.masters.forEach(function(m){ var ks=m.keys||[]; for (var i=0;i<ks.length;i++){ if (ks[i]!==-1) used[ks[i]]=1; } });
    var shown = {}; H.steps.forEach(function(s){ shown[String(s.key)] = 1; });
    var steps = (H.order||[]).filter(function(k){ return used[k] && shown[k]; });
    var weight = {}, N = steps.length;
    steps.forEach(function(k,i){ weight[k] = (i+1)/N; });
    STEPW = { weight:weight, N:N, steps:steps };
    return STEPW;
  }
  function gradedSum(m){ var W=stepWeights().weight, ks=m.keys||[], names=H.glyphNames||[], set=countedSet(), s=0; for (var i=0;i<ks.length;i++){ if (set && !set[names[i]]) continue; var w=W[ks[i]]; if (w) s+=w; } return s; }
  function gradedMasterPct(m){ var n=countedTotal()||((m.keys||[]).length)||1; return Math.round(gradedSum(m)/n*100); }
  // Graded completion % of one master AT a past snapshot date — partial credit per
  // step (final step weight 1), the SAME metric the Overview % / Compare
  // use. Reconstructs the state at the date (stateAt) and sums step weights, so the
  // Line chart, the Overview % and Flow all tell one consistent story. (Was final-step-only,
  // which sat at 0 until glyphs reached the last color, then cliffed to 100.)
  // Memoised per master|date: the week card asks for the same pairs on every re-render,
  // and each answer is a full stateAt reconstruction. Keyed on the plotted history
  // (tlDatasetKey); scrubbing keeps it.
  var GPCACHE = {}, GPCACHE_KEY = "";
  function gradedPctAt(masterId, date){
    var sw = sweepOf(masterId), j = sw.at[date];
    if (j !== undefined) return sw.sum[j] / (countedTotal() || 1) * 100;
    var key = tlDatasetKey();
    if (GPCACHE_KEY !== key){ GPCACHE = {}; GPCACHE_KEY = key; }
    var ck = masterId + "|" + date;
    if (GPCACHE[ck] != null){ return GPCACHE[ck]; }
    var W = stepWeights().weight, total = countedTotal() || 1, snap = stateAt(masterId, date), s = 0;
    for (var name in snap){ if (!isCounted(name)) continue; var w = W[String(snap[name])]; if (w){ s += w; } }
    return (GPCACHE[ck] = s / total * 100);
  }
  function gradedOverallPct(){ var s=0, tot=0; H.masters.forEach(function(m){ s+=gradedSum(m); tot+=countedTotal(); }); return tot? Math.round(s/tot*100):0; }
  // Overall graded % AT a past snapshot date (avg of per-master gradedPctAt — countedTotal
  // is master-independent, so this matches gradedOverallPct's weighting).
  function gradedOverallPctAt(date){
    if (!H.masters.length) return 0;
    var s = 0; H.masters.forEach(function(m){ s += gradedPctAt(m.id, date); }); return Math.round(s / H.masters.length);
  }
  function masterStarted(m){ return (uncoloredFor(m)||0) < countedTotal(); }   // any counted color set at all
  // ----- Workflow funnel: cumulative "reached step k or beyond" as descending bars.
  // Replaces the flat text legend with the SAME cumulative metric drawn so a nearly
  // full makeup bar can't be misread as nearly complete — the funnel visibly narrows
  // toward "done". Read-only on purpose: it counts reached-or-beyond, while focusing a
  // color means the glyphs sitting AT it (exclusive) — different sets, so the click-to-
  // focus selector stays on the makeup bar above; the funnel is the progress reference.
  function funnelHTML(cumFor, total){
    // Collapsed by default; expanded by clicking the master's % number.
    // No caption or chevron — the percentage itself is the toggle (data-funnel on it).
    if (state.funnelOpen === false) return "";
    var rows = H.steps.map(function(s){
      var p = pct(cumFor(s.key)||0, total);
      if (p === 0) return "";                       // a step no glyph has reached yet
      return '<div class="fnl-row" title="'+esc(s.label+" — "+p+"% reached this step or beyond")+'">'
        + legendDot(s.key)
        + '<span class="fnl-lab">'+esc(s.label)+'</span>'
        + '<span class="fnl-track"><span class="fnl-fill" style="width:'+p+'%;background:var('+varFor(s.key)+')"></span></span>'
        + '<span class="fnl-pct">'+p+'%</span></div>';
    }).join("");
    if (!rows) rows = '<div class="fnl-empty">Not started yet</div>';
    return '<div class="funnel'+(barsAnim?" intro":"")+'" role="group" aria-label="Cumulative progress by step, reached or beyond">'+rows+'</div>';
  }
  // The stacked color chart (family-wide, or the focused master's): always the full
  // history. It draws at its on-screen size (1 SVG unit = 1px, see fitOvChart) so its text
  // matches the page: on wide screens it fills its card; narrower, it is data-ht tall.
  var ovChartW = 0, ovChartH = 0;
  function ovChart(Ht){
    if (((H.trend && H.trend.dates) || []).length < 2) return seedState();
    return '<div class="ov-chart" data-ht="'+Ht+'">'+streamParts(ovChartW || 560, ovChartH || Ht)+'</div>';
  }
  function fitOvChart(){
    var el = document.querySelector(".ov-chart"); if (!el) return;
    var fill = window.matchMedia && window.matchMedia("screen and (min-width:781px)").matches;
    var w = el.clientWidth, h = fill ? el.clientHeight : +el.getAttribute("data-ht");
    if (!w || !h || (w === ovChartW && h === ovChartH)) return;
    ovChartW = w; ovChartH = h;
    el.innerHTML = streamParts(w, h);
  }

  // The selected master rendered like the overall card (ring + stacked bar +
  // legend), but scoped to this one master instead of the whole font.
  function masterOverall(m){
    var total = countedTotal();
    var dates = (H.trend && H.trend.dates) || [];
    var scrubbing = (state.tlScrub != null) && dates.length > 1;
    var dist = {}, none = 0, started, headPct, cumFor;
    if (scrubbing){
      // Reconstruct this master's color distribution AT the navigated version (stateAt),
      // so the bar + % + funnel reflect the picked snapshot, not today.
      var date = dates[scrubIndex()], snap = stateAt(m.id, date), nm, sk;
      for (nm in snap){ if (!isCounted(nm)) continue; var k = snap[nm]; sk = String(k);
        if (k!==-1 && H.order.indexOf(sk)!==-1) dist[sk] = (dist[sk]||0) + 1; }
      var colored = 0; for (sk in dist){ colored += dist[sk]; }
      none = Math.max(0, total - colored); started = colored;
      headPct = Math.round(gradedPctAt(m.id, date));
      var cum = {}, order = H.order || [], run = 0;
      for (var j = order.length-1; j >= 0; j--){ run += dist[order[j]] || 0; cum[order[j]] = run; }
      cumFor = function(kk){ return kk===-1 ? none : (cum[kk] || 0); };
    } else {
      // exclusive current-color tally drives the makeup bar (exclusion-aware).
      var set = countedSet(), names = H.glyphNames || [];
      (m.keys||[]).forEach(function(k, i){ if (set && !set[names[i]]) return; var s2=String(k);
        if (k===-1 || H.order.indexOf(s2)===-1) none++; else dist[s2]=(dist[s2]||0)+1; });
      started = total - uncoloredFor(m); headPct = gradedMasterPct(m);
      cumFor = function(kk){ return countFor(m,kk)||0; };
    }
    var startP = pct(started,total);
    // one clear progress number; the started count is in the tooltip. The number is also
    // the funnel toggle (click to show/hide progress by step).
    var head = '<span class="ov-name">'+esc(m.name)+'</span>'
      + '<button type="button" class="ov-pct" data-funnel="1" aria-expanded="'+(state.funnelOpen!==false)+'" title="'+started+'/'+total+' glyphs started ('+startP+'%) · '+esc(weightsNote())+' · click for progress by step">'+headPct+'%</button>';
    var segParts = H.steps.map(function(s,i){
      return segSpan(s.key, pct(dist[String(s.key)]||0, total), s.label, i);
    }).join("") + segSpan(-1, pct(none, total), H.noneLabel, H.steps.length);
    return '<section class="overall master-overall" aria-label="'+esc(m.name+" totals")+'">'
      + '<div class="ov-main"><div class="ov-head">'+head+pickDelta()+'</div>'
      + '<div class="seg'+(barsAnim?" intro":"")+'" role="img" aria-label="'+esc(m.name+" color distribution")+'">'+segParts+'</div>'
      + funnelHTML(cumFor, total)+'</div></section>';
  }
  // Graded % of the focused master (else the family average) at snapshot j, unrounded.
  function scopePctAt(j){
    var d = H.trend.dates[j], ids = state.master != null ? [state.master] : H.masters.map(function(m){ return m.id; }), s = 0;
    ids.forEach(function(id){ s += gradedPctAt(id, d); });
    return ids.length ? s / ids.length : 0;
  }
  // The picked category/script ("cat:Letter"), or null: none picked, or no glyph has it any more.
  function pickedLane(){ var m = H.masters[0]; return state.lane != null && m && sweepOf(m.id).lane[state.lane] ? state.lane : null; }
  // What the chart's top line reads at snapshot j: scopePctAt, or the picked lane's graded %.
  function chartPctAt(j){
    var lane = pickedLane(); if (!lane) return scopePctAt(j);
    var ids = state.master != null ? [state.master] : H.masters.map(function(m){ return m.id; }), s = 0;
    ids.forEach(function(id){ var sw = sweepOf(id); s += sw[lane.slice(0, 3)][lane.slice(4)][j] / sw.n[lane] * 100; });
    return s / ids.length;
  }
  // "+1.9%" / "-0.4%", or "" when the change rounds to nothing (never "+0.0%").
  function deltaText(d){ return Math.abs(d) < 0.05 ? "" : (d > 0 ? "+" : "")+d.toFixed(1)+"%"; }
  // The picked version's change since the version before, beside its progress ("" at now, the
  // first version, or no change).
  function pickDelta(){
    var i = scrubIndex();
    if (state.tlScrub == null || i < 1) return "";
    var d = scopePctAt(i) - scopePctAt(i - 1), t = deltaText(d);
    return t ? '<span class="ov-delta '+(d > 0 ? "tl-d-up" : "tl-d-down")+'" title="Since the previous version">'+t+'</span>' : "";
  }
  // The family's card, heading the panel like a master's: its graded % (live at now, else at
  // the picked version) and the change since the version before.
  function familyVersion(){
    var live = state.tlScrub == null, p = live ? gradedOverallPct() : Math.round(scopePctAt(scrubIndex()));
    return '<section class="overall" aria-label="All masters totals"><div class="ov-main"><div class="ov-head">'
      + '<span class="ov-name">All masters</span><b title="'+esc(weightsNote())+'">'+p+'%</b>'+pickDelta()+'</div></div></section>';
  }
  // What the weighted % means: each step's weight, first to last ("✏️ Drawn 1/6, …").
  function weightsNote(){
    var w = stepWeights();
    return "Progress counts each glyph by its step: " + w.steps.map(function(k, i){ return labelFor(k)+" "+(i+1)+"/"+w.N; }).join(", ");
  }
  // ----- Changes list: glyphs whose color changed between two versions ------
  // To = the picked moment (state.tlScrub; unset = now), From = the version just before it.
  // At "now": your last report before today (H.changes; with nothing recorded there, each
  // glyph's previous color from its saved history).
  function changeRange(){
    var dates = (H.trend && H.trend.dates) || [], ti = scrubIndex();
    var live = state.tlScrub == null || ti < 0;
    var fi = live ? null : ti - 1;
    return { dates: dates, from: (fi != null && fi >= 0) ? fi : null, to: live ? null : ti };
  }
  function rangeLabel(){
    var r = changeRange();
    if (r.from != null) return "";   // the picked day heads the panel
    return r.to != null ? "first version" : "Since your last report before today";
  }
  // A hidden or unknown label reads as uncolored, like everywhere else in the report.
  function normKey(k){ return (k == null || !H.steps.some(function(s){ return String(s.key) === String(k); })) ? -1 : k; }
  // {glyphName: [fromKey, toKey]} for this master's glyphs whose color differs.
  function changePairs(m){
    var r = changeRange(), names = H.glyphNames, raw = {}, out = {}, n, i;
    if (r.from == null && r.to == null){
      var ch = (H.changes && H.changes[m.id]) || {}, any = false;
      for (n in ch){ any = true; raw[n] = ch[n]; }
      if (!any){
        var jidx = (H.journeyIndex && H.journeyIndex[m.id]) || {};
        for (n in jidx){ var ev = jidx[n]; if (ev && ev.length >= 2){ raw[n] = [ev[ev.length-2][1], ev[ev.length-1][1]]; } }
      }
    } else if (r.from != null){
      var a = stateAt(m.id, r.dates[r.from]), b = r.to != null ? stateAt(m.id, r.dates[r.to]) : null;
      for (i=0;i<names.length;i++){ n = names[i]; raw[n] = [a[n], b ? b[n] : m.keys[i]]; }
    }
    for (n in raw){ var f = normKey(raw[n][0]), t = normKey(raw[n][1]); if (String(f) !== String(t)) out[n] = [f, t]; }
    return out;
  }
  function changesList(m){
    var pairs = changePairs(m), rows = [], counts = {}, keys = [];
    H.glyphNames.forEach(function(n){                    // font order inside each group
      var p = pairs[n]; if (!p) return;
      rows.push({n:n, from:p[0], to:p[1]});
      if (!(p[1] in counts)){ counts[p[1]] = 0; keys.push(p[1]); }
      counts[p[1]]++;
    });
    // one group per color reached, last step first; losing a color comes last
    function rank(k){ return String(k) === "-1" ? -1 : H.order.indexOf(String(k)); }
    keys.sort(function(a, b){ return rank(b) - rank(a); });
    // old -> new as two discs; the labels are in the tooltip
    function cell(a, b){ var t = esc(labelFor(a)+" → "+labelFor(b));
      return '<td><span class="chg-c" role="img" aria-label="'+t+'" title="'+t+'">'+swatchFor(a)+'<span class="chg-ar">→</span>'+swatchFor(b)+'</span></td>'; }
    // each group opens on a click of its heading (state.chgOpen), closed at first
    var body = keys.map(function(k){
      var open = !!state.chgOpen[k];
      var lines = !open ? [] : rows.filter(function(r){ return String(r.to) === String(k); }).map(function(r){
        var counted = isCounted(r.n);   // hover and click show nothing
        return '<tr class="chg-r' + (counted ? '"' : ' ncnt" title="Non-exporting: not counted"') + '>'
          + '<td><span class="chg-nm">'+esc(r.n)+'</span></td>' + cell(r.from, k) + '</tr>';
      });
      return '<tbody class="chg-grp" aria-label="'+esc("→ " + labelFor(k))+'">'
        + '<tr class="chg-gh"><th colspan="2" scope="colgroup"><button type="button" class="chg-gh-in" data-chg="'+esc(k)+'" aria-expanded="'+open+'">'+swatchFor(k)
        + '<span>'+esc(labelFor(k))+'</span><span class="chg-n">'+counts[k]+'</span></button></th></tr>'
        + lines.join("") + '</tbody>';
    }).join("");
    return '<section class="ov-card ovc-changed chg" aria-label="Glyphs whose color changed">'
      + '<div class="ov-card-h chg-h"><span>Activity</span><span>'+rows.length.toLocaleString("en")+' glyph'+(rows.length===1?"":"s")+'</span></div>'
      + (rangeLabel() ? '<p class="chg-range">'+esc(rangeLabel())+'</p>' : '')
      + (body ? '<div class="chg-tw"><table class="chg-t"><colgroup><col><col class="chg-cw"></colgroup>' + body + '</table></div>'
        : '<p class="empty">No changes this day</p>')
      + '</section>';
  }
  // ----- Overview extras (only when no master is selected) ------------------
  function masterPct(m){   // graded step progress, at the picked version if any
    return state.tlScrub != null ? Math.round(gradedPctAt(m.id, H.trend.dates[scrubIndex()])) : gradedMasterPct(m);
  }
  // A titled dashboard card.
  function ovCard(key, title, bodyHtml, headExtra){   // headExtra: html at the header's right
    return '<div class="ov-card ovc-'+esc(key)+'"><div class="ov-card-h"><span>'+esc(title)+'</span>'+(headExtra || "")+'</div>'
      + '<div class="ov-card-body">'+bodyHtml+'</div></div>';
  }
  function lbRow(r, anim, i){
    // anim (first paint only) grows each bar 0->width with a small per-row cascade.
    var fillCls = "lb-fill" + (anim ? " intro" : "");
    var fillStyle = "width:" + r.p + "%" + (anim ? ";--i:" + i : "");
    return '<button type="button" class="lb-row" data-m="'+esc(r.id)+'" title="Focus '+esc(r.name)+'">'
      + '<span class="lb-n">'+esc(r.name)+'</span>'
      + '<span class="lb-bar"><span class="'+fillCls+'" style="'+fillStyle+'"></span></span>'
      + '<span class="lb-p">'+r.p+'%</span></button>';
  }
  // Ranked masters by graded step progress; click a row to focus that master.
  // Collapsed shows the top 10; expanded scrolls through every master.
  function rankedMasters(){
    var rows = H.masters.map(function(m){ return {id:m.id, name:m.name, p:masterPct(m), any:masterStarted(m)}; });
    return rows.sort(function(a,b){ return b.p-a.p || (a.name<b.name?-1:1); });
  }
  function leaderboard(){
    // Always show every master, fully expanded — no scroll, no "Show all" toggle.
    var bars = rankedMasters().map(function(r, i){ return lbRow(r, barsAnim, i); }).join("");
    var expand = ((H.trend && H.trend.dates) || []).length < 2 ? "" : '<button type="button" class="lb-expand" data-mgrid="1" title="Each master\'s chart" aria-label="Show each master\'s chart" aria-haspopup="dialog">'+EXPAND+'</button>';
    return ovCard("leaderboard", "Masters' progress", bars, expand);
  }
  // Masters' progress, expanded: a modal grid of each master's chart in the card's order; a
  // click on one focuses that master. Esc, the cross or a click outside closes it.
  var mgrid = null;
  function openMastersGrid(){
    if (!mgrid){
      mgrid = document.createElement("dialog"); mgrid.className = "mg-dlg"; mgrid.setAttribute("aria-label", "Masters' progress");
      document.body.appendChild(mgrid);
      mgrid.addEventListener("click", function(e){
        var t = e.target.closest("[data-m]");
        if (t){ state.master = t.getAttribute("data-m"); state.focus = null; mgrid.close(); update(); }
        else if (e.target === mgrid || e.target.closest(".mg-x")) mgrid.close();   // the backdrop or the cross
      });
    }
    mgrid.innerHTML = '<div class="mg-in"><div class="mg-head"><span>Masters\' progress</span><button type="button" class="mg-x" aria-label="Close">'+CROSS+'</button></div><div class="mg-grid">'
      + rankedMasters().map(function(r){
          return '<button type="button" class="mg-tile" data-m="'+esc(r.id)+'"><span class="mg-h"><span class="mg-n">'+esc(r.name)+'</span>'
            + '<span class="mg-p">'+r.p+'%</span></span>'+streamParts(260, 122, r.id)+'</button>';
        }).join("") + '</div></div>';
    mgrid.showModal();
  }
  // A master's last 5 earlier versions that changed something (date, % change); a click
  // picks that version, which stays listed and lit. Now is the changes table below.
  function recentVersions(m){
    var dates = H.trend.dates, chg = changeCounts(m.id), rows = [];
    for (var k = dates.length - 2; k > 0 && rows.length < 5; k--){
      if (!chg[k]) continue;
      var d = gradedPctAt(m.id, dates[k]) - gradedPctAt(m.id, dates[k-1]);
      var on = state.tlScrub != null && k === scrubIndex();
      rows.push('<button type="button" class="lb-row'+(on ? ' on" aria-current="true' : '')+'" data-ver="'+k+'" title="See what changed in this version">'
        + '<span class="lb-n">'+esc(tickLabel(dates[k]))+'</span>'
        + '<span class="lb-p '+(d > 0 ? "tl-d-up" : "tl-d-down")+'">'+deltaText(d)+'</span></button>');
    }
    return rows.length ? ovCard("versions", "Recent updates", rows.join("")) : "";
  }
  // canonical swatch; no color (null, -1 or "-1") is the dark dot with a cross in it
  function swatchFor(key){
    if (key == null || String(key) === "-1") return '<span class="rg-sw none"></span>';
    return '<span class="rg-sw" style="background:var('+varFor(key)+')"></span>';
  }
  // Overview "Recent progress" card: graded completion change over the last 7 and 30 days.
  // Hidden until there's a snapshot >=7 days back.
  function weekProgressCard(){
    var dates = (H.trend && H.trend.dates) || [];
    if (dates.length < 2) return "";
    var latest = dates[dates.length-1], weekAgo = snapDate(dates, isoMinusDays(latest, 7));
    if (weekAgo === latest) return "";
    var nowPct = gradedOverallPct(), thenPct = gradedOverallPctAt(weekAgo), delta = nowPct - thenPct;
    var monthAgo = snapDate(dates, isoMinusDays(latest, 30)), monthDelta = nowPct - gradedOverallPctAt(monthAgo);
    function wkStat(d, lab){ var a = rankArrow(d); return '<span class="wk-stat"><span class="wk-delta '+a.c+'">'+a.g+' '+(d>0?"+":"")+d+'%</span><span class="wk-sub">'+lab+'</span></span>'; }
    var monthStat = (monthAgo !== weekAgo) ? wkStat(monthDelta, "past 30 days") : "";   // short history: not twice
    var body = '<div class="wk-head">'+wkStat(delta, "past 7 days")+monthStat+'</div>';
    return ovCard("week", "Recent progress", body);
  }
  // Chart + context: the chart (category/script lanes under it) stays put on the left; the
  // panel on the right follows what's picked. On wide screens it fills the window and the
  // panel scrolls inside.
  function tabsView(){
    var m = state.master != null ? masterById(state.master) : null;
    var cats = categoryLanes(), scripts = scriptLanes();
    var lanes = (cats || scripts) ? '<div class="tl-lanes-grid'+(scripts ? '' : ' tl-lanes-cat2')+(pickedLane() ? ' picking' : '')+'">'+cats+scripts+'</div>' : '';
    var side = m ? masterOverall(m) + recentVersions(m) + changesList(m)
      : !H.masters.length ? ''
      : familyVersion() + (state.tlScrub != null ? '' : weekProgressCard()) + leaderboard();   // at the picked version
    return '<div class="ctx"><section class="ctx-main"><div class="chart-top">'+laneChip()+unfocusBtn()+datePicker()+'</div>'+ovChart(220)+lanes+'</section>'
      + '<div class="ctx-side">'+side+'</div></div>';
  }
  // While a color is focused: the visible way back, beside the date over the chart (Escape or
  // a second click also clear it).
  function unfocusBtn(){
    return state.focus != null ? '<button type="button" class="ov-unfocus" data-unfocus="1">Show all colors ✕</button>' : "";
  }
  // While the chart shows one category or script: its name, the way back to every glyph.
  function laneChip(){
    var lane = pickedLane(); if (!lane) return "";
    var key = lane.slice(4);
    return '<button type="button" class="ov-unfocus" data-unlane="1" title="Show every glyph">'+esc(lane.slice(0, 3) === "scr" ? prettyScript(key) : key)+' ✕</button>';
  }
  // A lane row is a toggle: a click (or Enter / Space) narrows the chart to its glyphs.
  function laneRow(key, done){
    var on = state.lane === key;
    return '<div class="tl-lane'+(done ? " done" : "")+(on ? " on" : "")+'" data-lane="'+esc(key)+'" role="button" tabindex="0" aria-pressed="'+on+'">';
  }
  function prettyScript(key){ return key==="Other" ? "Other" : key.charAt(0).toUpperCase()+key.slice(1); }
  // The report's one date format, day/month ("02/06"), with a 2-digit year ("02/06/26") once the
  // history and the report's date span two calendar years; a save's time is never shown.
  function tickLabel(iso){
    var s = String(iso), first = String(((H.trend && H.trend.dates) || [])[0] || H.generated);
    if (!/^\d{4}-\d\d-\d\d/.test(s)) return s;
    return s.slice(8,10) + "/" + s.slice(5,7) + (first.slice(0,4) !== String(H.generated).slice(0,4) ? "/" + s.slice(2,4) : "");
  }
  // ----- Shared X axis -----------------------------------------------------------
  // Plot geometry + the X scale (time: each snapshot at its date, so a busy week and a quiet
  // month take their real share of the width; dayOff() returns ms since the first snapshot),
  // the date ticks and the picked-version marker. The series is the window viewBounds()
  // (from j0); snapshot indices elsewhere stay full-history ones.
  function calendarAxis(W, Ht, nTicks){
    var b = viewBounds(), j0 = b[0], series = ((H.trend && H.trend.series) || []).slice(j0, b[1] + 1);
    var pl=40, pr=0, ptop=12, pb=26, iw=W-pl-pr, ih=Ht-ptop-pb;   // pl: the % labels' gutter, left of the plot; pb: the dates', 6 units clear of the axis
    var t0 = cfdDate(series[0].date).getTime();
    function dayOff(d){ return cfdDate(d).getTime() - t0; }
    var lastOff = Math.max(1, dayOff(series[series.length - 1].date));
    function X(o){ return pl + o/lastOff*iw; }
    // nTicks date labels (else as many as fit, up to 6, 1.5 label widths apart: 9px mono,
    // ~5.6 units a character, edge labels hang off their end), evenly spaced in time from the
    // first snapshot to the last; ticks that land on one day label it once.
    var last = series.length - 1;
    var labelW = tickLabel(series[last].date).length * 5.6 * 1.5 + 12;
    var nT = Math.min(series.length, nTicks || Math.max(2, Math.min(6, Math.floor(iw / labelW))));
    var xticks = "", prevLab = null;
    for (var t = 0; t < nT; t++){
      var tt = t * lastOff / Math.max(1, nT - 1), lab = tickLabel(new Date(t0 + tt).toISOString());
      if (lab === prevLab){ continue; }
      prevLab = lab;
      var anchor = t === 0 ? "start" : (t === nT - 1 ? "end" : "middle");
      xticks += '<text class="tl-xtick" x="'+X(tt).toFixed(1)+'" y="'+(ptop+ih+pb-3).toFixed(1)+'" text-anchor="'+anchor+'">'+esc(lab)+'</text>';   // off the edge: it clips a pixel row
    }
    // snapshot X anchors in SVG user-space: a click snaps to the nearest one.
    var snaps = series.map(function(p){ return { x:+X(dayOff(p.date)).toFixed(1), d:p.date }; });
    // Marker at the picked version (state.tlScrub); the color discs read the same index.
    var scrubRule = "";
    if (state.tlScrub != null && series[state.tlScrub - j0]){
      var srx = X(dayOff(series[state.tlScrub - j0].date));
      scrubRule = '<line class="tl-scrubline" x1="'+srx.toFixed(1)+'" y1="'+ptop+'" x2="'+srx.toFixed(1)+'" y2="'+(ptop+ih).toFixed(1)+'"/>'
        + '<circle class="tl-scrubdot" cx="'+srx.toFixed(1)+'" cy="'+(ptop+ih).toFixed(1)+'" r="3.5"/>';
    }
    return { series:series, pl:pl, pr:pr, ptop:ptop, pb:pb, iw:iw, ih:ih,
             dayOff:dayOff, X:X, xticks:xticks, snaps:snaps, scrubRule:scrubRule, j0:j0 };
  }
  // A master's chart starts at its first snapshot with a colored glyph (it is flat zero
  // before); the family's shows the whole history. Keeps 2 points so a chart can draw.
  function chartStart(){
    if (state.master == null) return 0;
    var sum = sweepOf(state.master).sum;
    for (var j = 0; j < sum.length; j++){ if (sum[j] > 0) return Math.min(j, Math.max(0, sum.length - 2)); }
    return 0;
  }
  // The chart's window [lo, hi] in full-history indices: from chartStart() to now.
  function viewBounds(){
    return [chartStart(), ((H.trend && H.trend.series) || []).length - 1];
  }
  // ----- Date picker ------------------------------------------------------------
  // The shown version's date over the chart; a click opens a month calendar (state.cal =
  // "YYYY-MM") where each day with a version a chart click could pick (one that changed the
  // scope, or now) is a button. While a version is picked, a cross before the caret goes back to now.
  function datePicker(){
    var dates = (H.trend && H.trend.dates) || [], picked = state.tlScrub != null;
    if (dates.length < 2) return "";
    return '<div class="cal"><button type="button" class="cal-btn'+(picked ? ' picked' : '')+'" data-cal="1" aria-expanded="'+(state.cal != null)+'" aria-label="Pick a date">'
      + (state.tlScrub == null ? "Today" : esc(tickLabel(dates[scrubIndex()])))+'</button>'
      + (picked ? '<button type="button" class="cal-x" data-now="1" title="Today" aria-label="Back to today">'+CROSS+'</button>' : '')
      + (state.cal != null ? calPop(state.cal) : "")+'</div>';
  }
  function calPop(ym){
    var dates = H.trend.dates, chg = scopeChanges(), lo = viewBounds()[0], last = dates.length - 1, days = {};
    for (var k = Math.max(1, lo); k <= last; k++){ if (chg[k] || k === last) days[dates[k].slice(0, 10)] = k; }   // a day's last version
    var y = +ym.slice(0, 4), mo = +ym.slice(5, 7), first = new Date(Date.UTC(y, mo - 1, 1));
    var cells = new Array((first.getUTCDay() + 6) % 7 + 1).join("<span></span>");   // weeks start on Monday
    for (var d = 1, n = new Date(Date.UTC(y, mo, 0)).getUTCDate(); d <= n; d++){
      var j = days[ym + (d < 10 ? "-0" : "-") + d];
      cells += j == null ? '<span class="cal-d">'+d+'</span>'
        : '<button type="button" class="cal-d'+(j === scrubIndex() ? ' on' : '')+'" data-calday="'+j+'">'+d+'</button>';
    }
    function nav(step, sym, label){
      var t = new Date(Date.UTC(y, mo - 1 + step, 1)).toISOString().slice(0, 7);
      var ok = t >= dates[lo].slice(0, 7) && t <= dates[last].slice(0, 7);
      return '<button type="button" class="cal-nav" aria-label="'+label+'"'+(ok ? ' data-calm="'+t+'"' : ' disabled')+'>'+sym+'</button>';
    }
    return '<div class="cal-pop" role="dialog" aria-label="Pick a date"><div class="cal-h">'+nav(-1, "‹", "Previous month")
      + '<span>'+first.toLocaleString("en", { month:"long", year:"numeric", timeZone:"UTC" })+'</span>'+nav(1, "›", "Next month")+'</div>'
      + '<div class="cal-g">'+"MTWTFSS".split("").map(function(w){ return '<span class="cal-w">'+w+'</span>'; }).join("")+cells+'</div></div>';
  }
  // A straight segment from each point to the next ([{x,y},...]): the chart is rectilinear,
  // never curved between two saves. Shared by the color-band edges and their top strokes.
  function linePath(ps){
    return ps.map(function(p, i){ return (i ? " L" : "M")+p.x.toFixed(1)+" "+p.y.toFixed(1); }).join("");
  }
  // mid: that master's small chart for the masters grid (0/50/100% lines, no date axis or clicks)
  function streamParts(W, Ht, mid){
    var ax = calendarAxis(W, Ht, 4);
    var pl = ax.pl, ptop = ax.ptop, ih = ax.ih, iw = ax.iw;
    var dayOff = ax.dayOff, X = ax.X;
    var order = H.order || [];
    // Scope: the focused master, else the AGGREGATE across all masters (the overall view).
    // Tally over the axis dates so the bands line up with the X.
    var scopeIds = mid != null ? [mid] : state.master != null ? [state.master] : H.masters.map(function(m){ return m.id; });
    var lane = mid != null ? null : pickedLane();   // the main chart only: the picked category/script's glyphs
    var tally = ax.series.map(function(p){
      var byKey = {}; order.forEach(function(k){ byKey[k] = 0; }); var none = 0;
      scopeIds.forEach(function(mid){
        var sw = lane && sweepOf(mid), t = lane ? sw.lane[lane][sw.at[p.date]] : colTally(mid, p.date);   // memoised per master|date
        order.forEach(function(k){ byKey[k] += t.byKey[k]; });
        none += t.none;
      });
      return { date:p.date, byKey:byKey, none:none };
    }).filter(function(t, i, all){
      // a line runs from one state to the next: a version that changed nothing here adds no
      // point, so a quiet stretch reads as a slope to the next change, not a flat line and a jump
      return !i || i === all.length - 1 || JSON.stringify(t.byKey) !== JSON.stringify(all[i-1].byKey);
    });
    // Weighted decomposition of the graded completion %: each band's height is that
    // color's WEIGHTED contribution (step weight x count / total). So the stack TOP
    // traces the same graded % as the Line, and the empty space above (up to 100%) is
    // the work remaining. denom = the scope's whole total (the graded-% denominator,
    // exclusion-aware via countedTotal).
    var WT = stepWeights().weight;
    var denom = scopeIds.length * (lane ? sweepOf(scopeIds[0]).n[lane] : countedTotal() || 1) || 1;   // 100% = the lane's glyphs
    function Y(p){ return ptop + ih - p / 100 * ih; }
    // The % labels sit in the gutter left of the plot, each level with the start of its gridline.
    var grid = "", yLabels = "";
    for (var g = 0; g <= 100; g += mid != null ? 50 : 25){
      var y = Y(g).toFixed(1);
      grid += '<line class="tl-grid" x1="'+pl+'" y1="'+y+'" x2="'+(W-ax.pr)+'" y2="'+y+'"/>';
      yLabels += '<text class="tl-axis" x="'+(pl-12)+'" y="'+(parseFloat(y)+4).toFixed(1)+'" text-anchor="end">'+g+'%</text>';
    }
    // Bands at lower opacity — no blur/saturate filter.
    // build a stacked Y for every date: running cumulative weighted-% from the baseline
    // up. bands stack bottom->top by H.order; no uncolored band (it has zero weight, so
    // it lives in the empty space above the stack).
    var nPts = tally.length;
    function bandPct(k, c){ return (WT[k] || 0) * c / denom * 100; }
    // Band edges use the same path as the top strokes (linePath), so the top band's
    // upper edge exactly coincides with the graded top line drawn over it.
    function bandPath(lowerVals, upperVals){
      var up = tally.map(function(t, i){ return { x:X(dayOff(t.date)), y:Y(upperVals[i]) }; });
      var lo = tally.map(function(t, i){ return { x:X(dayOff(t.date)), y:Y(lowerVals[i]) }; }).reverse();
      return linePath(up) + linePath(lo).replace(/^M/, " L") + "Z";
    }
    var bandKeys = order.slice();                          // bottom -> top by palette order
    // A focused color (legend click) stays lit and the other bands dim.
    var fk = state.focus != null && order.indexOf(String(state.focus)) !== -1 ? String(state.focus) : null;
    var bands = "";
    var bandTops = "";                                     // top-edge strokes, drawn over every fill
    // cumulative top of the stack at each date, seeded at 0 (baseline = Y(0)).
    var cum = tally.map(function(){ return 0; });
    bandKeys.forEach(function(k){
      var lower = cum.slice();
      var upper = tally.map(function(t, i){ return cum[i] + bandPct(k, t.byKey[k] || 0); });
      for (var i = 0; i < nPts; i++){ cum[i] = upper[i]; }
      // skip an all-zero band so empty steps add no markup on sparse history.
      var any = upper.some(function(v, i){ return v - lower[i] > 0.0001; });
      if (!any){ return; }
      var dim = fk !== null ? (k === fk ? " on" : " off") : "";
      bands += '<path class="tl-band'+dim+'" d="'+bandPath(lower, upper)+'" fill="var('+varFor(k)+')">'+(mid != null ? '' : '<title>'+esc(labelFor(k))+'</title>')+'</path>';   // no tips in the masters grid
      // Trace the band's TOP edge in its own color at higher opacity so each softened layer
      // still reads as a defined line. Same path as the fill's upper edge.
      var upPts = tally.map(function(t, i){ return { x:X(dayOff(t.date)), y:Y(upper[i]) }; });
      bandTops += '<path class="tl-band-top'+dim+'" d="'+linePath(upPts)+'" stroke="var('+varFor(k)+')"/>';
    });
    var bandGroup = '<g>'+bands+bandTops+'</g>';   // strokes above all fills
    // no % labels: the plot (2 units of air each side for the strokes) fills the tile
    if (mid != null) return '<svg class="tl-chart" viewBox="'+(ax.pl-2)+' 0 '+(W-ax.pl+4)+' '+(Ht-ax.pb+6)+'" aria-hidden="true">'+grid+bandGroup+ax.scrubRule+'</svg>';
    // The Overview chart marks the picked version with the dashed line (its date is in the panel).
    var crossData = ' data-snaps="'+esc(JSON.stringify(ax.snaps))+'"';
    var hitLayer = '<rect class="tl-crossarea" x="'+pl+'" y="'+ptop+'" width="'+iw.toFixed(1)+'" height="'+ih.toFixed(1)+'"/>';
    var chart = '<svg class="tl-chart tl-flow" viewBox="0 0 '+W+' '+Ht+'" role="img"'+crossData
      + ' aria-label="Stacked color completion over time. Click a version to see what changed in it; the left and right arrow keys step between versions.">'
      + grid+bandGroup+yLabels+ax.xticks+ax.scrubRule+hitLayer+'</svg>';
    return chart;
  }
  // Color tally of ONE master at ONE snapshot (exclusion-aware) for the Flow bands.
  // Every stacked-band render re-reads the same master|date pairs, and each tally is a
  // full stateAt reconstruction — so it's memoised like GPCACHE (key = the plotted
  // history; scrub and master switches reuse the entries).
  var COLCACHE = {}, COLCACHE_KEY = "";
  function colTally(mid, iso){
    var sw = sweepOf(mid), j = sw.at[iso];
    if (j !== undefined) return sw.tally[j];
    var key = tlDatasetKey();
    if (COLCACHE_KEY !== key){ COLCACHE = {}; COLCACHE_KEY = key; }
    var ck = mid + "|" + iso;
    if (COLCACHE[ck]) return COLCACHE[ck];
    var order = H.order || [], byKey = {}; order.forEach(function(k){ byKey[k] = 0; }); var none = 0;
    var snap = stateAt(mid, iso);
    for (var name in snap){ if (!isCounted(name)) continue; var sk = String(snap[name]);
      if (snap[name] === -1 || order.indexOf(sk) === -1){ none++; } else { byKey[sk]++; } }
    return (COLCACHE[ck] = { byKey:byKey, none:none });
  }
  // ----- #14 This-week digest card ------------------------------------------
  // Snap an ISO target to the real H.trend.dates entry nearest (but not after) it,
  // falling back to the earliest date when the target predates all history. Lets the
  // digest "label honestly": it always reports a date a snapshot actually exists for.
  function snapDate(dates, targetIso){
    var pick = dates[0];
    for (var i = 0; i < dates.length; i++){
      if (dates[i] <= targetIso) pick = dates[i]; else break;
    }
    return pick;
  }
  // Parse a timeline key — "YYYY-MM-DD" (per-day) or "YYYY-MM-DDTHH:MM:SS[.n]"
  // (per-commit) — into a stable Date. Avoids the "...T...T00:00:00Z" invalid-date
  // trap when commit-granularity datetime keys flow through the date math below.
  function cfdDate(iso){
    if (typeof iso !== "string") return new Date(NaN);
    return (iso.indexOf("T") > 0) ? new Date(iso.slice(0, 19) + "Z")
                                  : new Date(iso + "T00:00:00Z");
  }
  // ISO date N days before another ISO date (UTC midnight, timezone-stable).
  function isoMinusDays(iso, days){
    var d = cfdDate(iso);
    d.setUTCDate(d.getUTCDate() - days);
    return d.toISOString().slice(0, 10);
  }
  // Shared rank arrow + color class for a signed change (Recent progress and the
  // category/script lanes): a drawn equilateral triangle, or "▬" for no change.
  function rankArrow(value){
    return { g: value > 0 ? '<i class="tri"></i>' : (value < 0 ? '<i class="tri down"></i>' : "▬"),
             c: value > 0 ? "tl-d-up" : (value < 0 ? "tl-d-down" : "tl-d-flat") };
  }
  // The active master for the per-category / per-script lanes: the selected one, else
  // the first. (The full-history regression log + red chart flags were removed.)
  function reglogMaster(){ return state.master || (H.masters[0] && H.masters[0].id); }
  // ----- shared lane maths (category + script lanes) -------------------------
  // Graded completion % of a lane (kind "cat"/"scr", n counted glyphs) at snapshot j,
  // for ONE master, read off the master's sweep.
  function laneGradedPctOne(mid, kind, lane, n, j){
    var sums = sweepOf(mid)[kind][lane];
    return n && sums ? Math.round(sums[j]/n*100) : 0;
  }
  // ...scoped to the focused master, or AVERAGED across the family in Global view, so a
  // lane reads font-wide instead of silently tracking only the first master.
  function laneGradedPct(kind, lane, n, j){
    if (state.master != null) return laneGradedPctOne(state.master, kind, lane, n, j);
    var sum=0, m=0;
    for (var i=0;i<H.masters.length;i++){ sum += laneGradedPctOne(H.masters[i].id, kind, lane, n, j); m++; }
    return m ? Math.round(sum/m) : 0;
  }
  // The snapshot index the over-time lanes read: the moment picked by clicking the chart
  // (state.tlScrub, via scrubIndex), in both Global and focused views, so the category /
  // script panels follow the click. Defaults to the latest snapshot. Date-consistent.
  function scrubScopeIdx(){
    var dates = (H.trend && H.trend.dates) || [];
    if (!dates.length) return -1;
    return scrubIndex();
  }
  // Tiny completion-over-time polyline for a lane (chart Y-flip idiom, mini box).
  function laneSparkSVG(values, key){
    var n = values.length, w = 64, h = 16, pad = 1.5, iw = w - pad*2, ih = h - pad*2;
    if (n < 1) return "";
    // First snapshot has a single point: draw a flat line across the box at that level
    // (Hugo wants the line look at every moment, never a bar). morphSparks still tweens it.
    var yOf = function(v){ return pad + ih - Math.max(0, Math.min(100, v))/100*ih; };
    var pts = (n === 1)
      ? (pad.toFixed(1)+","+yOf(values[0]).toFixed(1)+" "+(w-pad).toFixed(1)+","+yOf(values[0]).toFixed(1))
      : values.map(function(v, i){
          var x = pad + i/(n-1)*iw;
          return x.toFixed(1)+","+yOf(v).toFixed(1);
        }).join(" ");
    // The data-spark key lets morphSparks() tween this line's shape when the moment or the master changes.
    return '<svg class="tl-lane-spark" width="'+w+'" height="'+h+'" viewBox="0 0 '+w+' '+h+'" aria-hidden="true">'
      + '<polyline data-spark="'+esc(key||"")+'" points="'+pts+'" fill="none"/></svg>';
  }
  // ----- #17 per-category progress lanes over time ---------------------------
  function categoryLanes(){
    // Shown in BOTH Global and focus mode. laneGradedPct scopes to the focused master
    // (or averages the family in Global), so the lanes read for whatever's in focus.
    var dates = (H.trend && H.trend.dates) || [];
    if (dates.length < 1) return "";
    // Map each glyph to its category from the parallel H.glyphNames / H.categories
    // arrays, grouping the glyph names by category (empty categories never appear).
    // Non-exporting glyphs are dropped here so the lane counts read counted sizes.
    var allNames = H.glyphNames || [], allCats = H.categories || [], groups = {};
    for (var gi = 0; gi < allNames.length; gi++){
      if (!isCounted(allNames[gi])) continue;
      var gcat = allCats[gi] || "Other";
      (groups[gcat] || (groups[gcat] = [])).push(allNames[gi]);
    }
    var cats = Object.keys(groups);
    if (!cats.length) return "";
    var mid = reglogMaster();
    if (!mid) return "";
    // Follow the moment picked on the chart (state.tlScrub via scrubScopeIdx), even in
    // Global view: the % is at that snapshot, the sparkline runs up to it, the delta is
    // vs the previous snapshot. Defaults to the latest snapshot when nothing is picked.
    var idx = scrubScopeIdx();
    var curJ = (idx>=0 && dates[idx]) ? idx : dates.length-1;
    var prevISO = idx > 0 ? dates[idx-1] : null;
    var uptoN = idx >= 0 ? idx+1 : dates.length;
    var lanes = cats.map(function(cat){
      var names = groups[cat], n = names.length, values = [];
      for (var j=0;j<uptoN;j++) values.push(laneGradedPct("cat", cat, n, j));
      var cur = laneGradedPct("cat", cat, n, curJ);
      var delta = prevISO ? cur - laneGradedPct("cat", cat, n, idx-1) : 0;
      return { cat:cat, count:names.length, values:values, cur:cur, delta:delta };
    });
    // Fixed canonical order (Glyphs Font-View style: Letter, Number, ...), so the lanes
    // never reshuffle when the picked moment / data changes. Unknown categories fall after,
    // alphabetically.
    var CAT_ORDER = ["Letter","Number","Punctuation","Mark","Separator","Symbol","Other"];
    lanes.sort(function(a, b){
      var ia = CAT_ORDER.indexOf(a.cat); ia = ia < 0 ? CAT_ORDER.length : ia;
      var ib = CAT_ORDER.indexOf(b.cat); ib = ib < 0 ? CAT_ORDER.length : ib;
      return (ia - ib) || (a.cat < b.cat ? -1 : 1);
    });
    var rows = lanes.map(function(ln){
      var ra = rankArrow(ln.delta); var arrow = ra.g, arrowCls = ra.c;
      var deltaTxt = prevISO ? ((ln.delta>0?"+":"")+ln.delta+"% vs "+esc(tickLabel(prevISO))) : "first snapshot";
      var mid2 = laneSparkSVG(ln.values, "cat:"+ln.cat);   // line at every moment (incl. first date)
      return laneRow("cat:"+ln.cat, ln.cur>=100)
        + '<span class="tl-lane-n" title="'+esc(ln.cat)+'">'+esc(ln.cat)+' <small>('+ln.count+')</small></span>'
        + '<span class="tl-lane-mid">'+mid2+'</span>'
        + '<span class="tl-lane-pct" data-lanekey="cat:'+esc(ln.cat)+'" data-to="'+ln.cur+'">'+ln.cur+'%</span>'
        + '<span class="tl-lane-d '+arrowCls+'" title="'+deltaTxt+'" aria-label="'+deltaTxt+'">'+arrow+'</span>'
        + '</div>';
    }).join("");
    return '<div class="tl-lanes">'+rows+'</div>';
  }
  // Compact per-category header strip for the Time Machine grid blocks (master view):
  // ----- #18 per-script progress lanes over time -----------------------------
  // Mirror of categoryLanes (#17) but grouped by the per-glyph H.scripts array
  // (writing systems: Latin, Cyrillic, Greek, ...) instead of H.categories.
  function scriptLanes(){
    var dates = (H.trend && H.trend.dates) || [];
    if (dates.length < 1) return "";
    // Map each glyph to its script from the parallel H.glyphNames / H.scripts
    // arrays, grouping the glyph names by script (empty scripts never appear).
    // Non-exporting glyphs are dropped here so the lane counts read counted sizes.
    var allNames = H.glyphNames || [], allScripts = H.scripts || [], groups = {};
    for (var gi = 0; gi < allNames.length; gi++){
      if (!isCounted(allNames[gi])) continue;
      var gscript = allScripts[gi] || "Other";
      (groups[gscript] || (groups[gscript] = [])).push(allNames[gi]);
    }
    var scripts = Object.keys(groups).filter(function(s){ return s !== "Other"; });   // skip the "Other" bucket
    if (!scripts.length) return "";
    // When Latin is the ONLY writing system, the per-script breakdown just mirrors the
    // overall progress -> hide the whole section (no point showing a single "Latin" lane).
    if (scripts.length === 1 && /^latin$/i.test(scripts[0])) return "";
    var mid = reglogMaster();
    if (!mid) return "";
    // read the scrubbed Time-Machine checkpoint (master view) / latest (global): the % at
    // that date, the sparkline up to it, and the delta vs the PREVIOUS snapshot, so the
    // script breakdown follows the slider the same way the category headers do.
    var idx = scrubScopeIdx();
    var curJ = (idx>=0 && dates[idx]) ? idx : dates.length-1;
    var prevISO = idx > 0 ? dates[idx-1] : null;
    var uptoN = idx >= 0 ? idx+1 : dates.length;
    var lanes = scripts.map(function(script){
      var names = groups[script], n = names.length, values = [];
      for (var j=0;j<uptoN;j++) values.push(laneGradedPct("scr", script, n, j));
      var cur = laneGradedPct("scr", script, n, curJ);
      var delta = prevISO ? cur - laneGradedPct("scr", script, n, idx-1) : 0;
      return { script:script, count:names.length, values:values, cur:cur, delta:delta };
    });
    // laggard-first: lowest current % on top (name as a stable tie-breaker).
    lanes.sort(function(a, b){ return (a.cur - b.cur) || (a.script < b.script ? -1 : 1); });
    var rows = lanes.map(function(ln){
      var ra = rankArrow(ln.delta); var arrow = ra.g, arrowCls = ra.c;
      var deltaTxt = prevISO ? ((ln.delta>0?"+":"")+ln.delta+"% vs "+esc(tickLabel(prevISO))) : "first snapshot";
      var mid2 = laneSparkSVG(ln.values, "scr:"+ln.script);   // line at every moment (incl. first date)
      return laneRow("scr:"+ln.script, ln.cur>=100)
        + '<span class="tl-lane-n" title="'+esc(prettyScript(ln.script))+'">'+esc(prettyScript(ln.script))+' <small>('+ln.count+')</small></span>'
        + '<span class="tl-lane-mid">'+mid2+'</span>'
        + '<span class="tl-lane-pct" data-lanekey="scr:'+esc(ln.script)+'" data-to="'+ln.cur+'">'+ln.cur+'%</span>'
        + '<span class="tl-lane-d '+arrowCls+'" title="'+deltaTxt+'" aria-label="'+deltaTxt+'">'+arrow+'</span>'
        + '</div>';
    }).join("");
    return '<div class="tl-lanes">'+rows+'</div>';
  }
  // (The #19 deadline / Target-date feature was removed — no target picker, no on-chart
  //  deadline rule, no verdict chips.)
  // ----- #11 moment scrubber -------------------------------------------------
  // The snapshot index currently scrubbed: state.tlScrub clamped to the dates range,
  // defaulting to the latest snapshot when unset.
  function scrubIndex(){
    var dates = (H.trend && H.trend.dates) || [];
    if (!dates.length) return -1;
    var idx = state.tlScrub == null ? dates.length-1 : state.tlScrub;
    return Math.max(0, Math.min(dates.length-1, idx));
  }
  // Set the scrub index (clamped) and re-render. A full update() makes picking a moment
  // update EVERYTHING tied to it — the color disc, the category/script lanes and their
  // %/deltas all recompute at the scrubbed index (scrubScopeIdx). Picking the latest
  // snapshot clears the scrub (back to "live").
  function scrubSet(idx){
    var dates = (H.trend && H.trend.dates) || [];
    if (!dates.length) return;
    var clamped = Math.max(0, Math.min(dates.length-1, idx));
    var prev = state.tlScrub;
    state.tlScrub = (clamped === dates.length-1) ? null : clamped;
    if (state.tlScrub !== prev) scrubAnim = true;   // a new moment: animate the bars/lines that follow it
    update();
  }
  // ----- Onboarding: fewer than 2 snapshots, so no chart yet ----------------------
  // In the chart's place, all theme-safe + a11y-labelled; reduced motion drops the
  // skeleton shimmer via the shared __cfdNoAnim / matchMedia gate.
  function seedState(){
    var noAnim = window.__cfdNoAnim ||
      (window.matchMedia && window.matchMedia("(prefers-reduced-motion:reduce)").matches);
    // <2 snapshots: skeleton preview. A dashed placeholder line + a couple of ghost
    // dots hint at the coming chart; ONE real solid "today" dot sits at the single
    // snapshot's completion % — the ghosts are decorative, the solid dot is the one
    // honest reading. No data invented.
    var single = (H.trend && H.trend.series && H.trend.series[0]) || null;
    var midOne = state.master || (H.masters[0] && H.masters[0].id);
    var pc = 0;
    if (single && midOne && single.masters[midOne] && single.masters[midOne].total){
      pc = gradedPctAt(midOne, single.date);        // graded (matches the Overview %), not final-step-only
    }
    var W = 320, Ht = 120, pad = 14, iw = W - pad*2, ih = Ht - pad*2;
    var gx = function(t){ return pad + t*iw; };                // t in [0,1]
    var gy = function(p){ return pad + ih - p/100*ih; };       // p in [0,100]
    var ghostLine = '<polyline class="tl-seed-ghost tl-seed-line" points="'
      + gx(0).toFixed(1)+','+gy(8).toFixed(1)+' '
      + gx(0.5).toFixed(1)+','+gy(22).toFixed(1)+' '
      + gx(1).toFixed(1)+','+gy(38).toFixed(1)+'"/>';
    var ghostDots = [0, 0.5].map(function(t, i){
      var gp = i === 0 ? 8 : 22;
      return '<circle class="tl-seed-ghost tl-seed-dot" cx="'+gx(t).toFixed(1)+'" cy="'+gy(gp).toFixed(1)+'" r="3"/>';
    }).join("");
    var todayDot = '<circle class="tl-seed-today" cx="'+gx(1).toFixed(1)+'" cy="'+gy(pc).toFixed(1)+'" r="4"><title>'
      + esc("Today · " + Math.round(pc) + "%") + '</title></circle>';
    var shimmer = noAnim ? "" : " tl-seed-shimmer";
    var skeleton = '<svg class="tl-seed-svg'+shimmer+'" viewBox="0 0 '+W+' '+Ht+'" role="img" aria-label="'
      + esc("One snapshot so far at " + Math.round(pc) + "%. The chart unlocks once a second day of history is saved.")+'">'
      + ghostLine + ghostDots + todayDot + '</svg>';
    return '<section class="tl-seed tl-seed-1" role="group" aria-label="Getting started">'
      + '<div class="tl-seed-head">Building your chart</div>'
      + skeleton
      + '<p class="tl-seed-sub">'+(H.fineKind === "commit" ? "AZ Colorflow reads a snapshot from each commit."   // a git font
          : "AZ Colorflow saves a snapshot each time you save the font.")+' The chart unlocks at 2 days of history.</p>'
      + '</section>';
  }
  // ----- Shared journey substrate: reconstruct color state from the sparse
  // change-event index (journeyIndex[masterId][glyphName] = [[date,key],...]) ----
  function stateAt(masterId, iso){
    var perMaster = H.journeyIndex && H.journeyIndex[masterId];
    var out = {};
    if (!perMaster) return out;
    for (var name in perMaster){
      var events = perMaster[name], key = null;
      for (var i=0;i<events.length;i++){
        if (events[i][0] <= iso) key = events[i][1]; else break;
      }
      // a hidden color (not in the visible order) reads as uncolored, like m.keys
      if (key !== null) out[name] = (key !== -1 && H.order.indexOf(String(key))===-1) ? -1 : key;
    }
    return out;
  }
  // ----- Shared caches over the journey substrate -----------------------------
  // Everything derived from journeyIndex only changes with the plotted history;
  // tlDatasetKey() is that identity: a key mismatch drops the cache, scrubbing and
  // master switches keep it.
  function tlDatasetKey(){
    var dates = (H.trend && H.trend.dates) || [];
    return dates.length + ":" + (dates.length ? dates[dates.length-1] : "");
  }
  // Per-master change counts per snapshot: chg[k] = how many glyphs' EFFECTIVE color
  // (hidden keys read as -1, same normalisation as stateAt) differs between dates[k-1]
  // and dates[k]; chg[0] = 0 (no predecessor). Walked straight off the sparse
  // journeyIndex events — O(events + dates) per master, ONCE — instead of
  // reconstructing and diffing a full per-glyph snapshot per date per render.
  // version picking and the activity calendar read it on every re-render. Events that
  // cancel out between two snapshots (away and back inside one gap) count as no
  // change, exactly like diffing the snapshots themselves.
  var CHGCACHE = {}, CHGCACHE_KEY = "";
  function changeCounts(masterId){
    var key = tlDatasetKey();
    if (CHGCACHE_KEY !== key){ CHGCACHE = {}; CHGCACHE_KEY = key; }
    if (CHGCACHE[masterId]) return CHGCACHE[masterId];
    var dates = (H.trend && H.trend.dates) || [];
    var chg = dates.map(function(){ return 0; });
    var perMaster = (H.journeyIndex && H.journeyIndex[masterId]) || {};
    for (var name in perMaster){
      var events = perMaster[name];
      // eff = the glyph's value once this bucket's events are applied; committed = its
      // value at the previous snapshot; undefined = not in the snapshot yet, so a glyph
      // APPEARING (first event, even uncolored) counts as a change. Explicit undefined
      // inits: vars are function-scoped and must not leak across glyphs.
      var bp = 0, cur = -1, eff = undefined, committed = undefined;
      for (var i=0;i<events.length;i++){
        while (bp < dates.length && dates[bp] < events[i][0]){ bp++; }
        if (bp >= dates.length) break;             // event after the last snapshot: never visible
        if (bp !== cur){                           // close the previous snapshot's event group
          if (cur > 0 && eff !== committed){ chg[cur]++; }
          if (cur !== -1){ committed = eff; }
          cur = bp;
        }
        var k = events[i][1];
        eff = (k !== -1 && H.order.indexOf(String(k)) === -1) ? -1 : k;
      }
      if (cur > 0 && eff !== committed){ chg[cur]++; }
    }
    return (CHGCACHE[masterId] = chg);
  }
  // Running totals of a master's color state at every snapshot date, from ONE forward
  // walk over its journeyIndex events (oldest-first, as stateAt reads them). Asking
  // stateAt for every master x date x lane rebuilt every glyph's color thousands of
  // times per render (seconds on a big font); here each event is applied once. Per date
  // j: sum[j] = graded step-weight sum of the counted glyphs (gradedPctAt), tally[j] =
  // per-color counts (colTally), cat/scr[lane][j] = the lane sums (category / script
  // lanes). Weights are summed as integer step ranks, divided by N on read, so long
  // histories don't drift. Same keying + reset discipline as CHGCACHE.
  var SWEEP = {}, SWEEP_KEY = "";
  function sweepOf(masterId){
    var key = tlDatasetKey();
    if (SWEEP_KEY !== key){ SWEEP = {}; SWEEP_KEY = key; }
    if (SWEEP[masterId]) return SWEEP[masterId];
    var dates = (H.trend && H.trend.dates) || [], order = H.order || [], sw = stepWeights();
    var rank = {}; sw.steps.forEach(function(k, i){ rank[k] = i + 1; });
    var names = H.glyphNames || [], cats = H.categories || [], scripts = H.scripts || [];
    var catOf = {}, scrOf = {}, cat = {}, scr = {}, lt = {}, ln = {}, i, q;   // lt/ln: per lane key ("cat:Letter"), color counts and size
    for (i=0;i<names.length;i++){
      if (!isCounted(names[i])) continue;
      catOf[names[i]] = cats[i] || "Other"; scrOf[names[i]] = scripts[i] || "Other";
      cat[catOf[names[i]]] = 0; scr[scrOf[names[i]]] = 0;
      var lk = ["cat:"+catOf[names[i]], "scr:"+scrOf[names[i]]];
      for (q=0;q<2;q++){
        if (!lt[lk[q]]){ lt[lk[q]] = { byKey:{}, none:0 }; order.forEach(function(k){ lt[lk[q]].byKey[k] = 0; }); }
        ln[lk[q]] = (ln[lk[q]] || 0) + 1;
      }
    }
    function bump(t, old, k){ if (old !== undefined){ if (old === -1) t.none--; else t.byKey[String(old)]--; } if (k === -1) t.none++; else t.byKey[String(k)]++; }
    var perMaster = (H.journeyIndex && H.journeyIndex[masterId]) || {}, ev = [], name;
    for (name in perMaster){ var es = perMaster[name]; for (i=0;i<es.length;i++) ev.push([es[i][0], name, es[i][1]]); }
    ev.sort(function(a, b){ return a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0; });   // stable: a glyph's own events keep their order
    var out = { at:{}, sum:[], tally:[], cat:{}, scr:{}, lane:{}, n:ln }, cur = {}, sum = 0, none = 0, byKey = {}, p = 0, N = sw.N || 1, c;
    order.forEach(function(k){ byKey[k] = 0; });
    for (c in cat) out.cat[c] = [];
    for (c in scr) out.scr[c] = [];
    for (c in lt) out.lane[c] = [];
    for (var j=0;j<dates.length;j++){
      for (; p < ev.length && ev[p][0] <= dates[j]; p++){
        var nm = ev[p][1], k = ev[p][2], old = cur[nm];
        if (k !== -1 && order.indexOf(String(k)) === -1) k = -1;   // hidden color reads as uncolored, like stateAt
        if (old === k) continue;
        cur[nm] = k;
        if (!isCounted(nm)) continue;
        var d = (rank[k] || 0) - (old === undefined ? 0 : (rank[old] || 0));
        sum += d;
        if (old !== undefined){ if (old === -1) none--; else byKey[String(old)]--; }
        if (k === -1) none++; else byKey[String(k)]++;
        if (catOf[nm] !== undefined){ cat[catOf[nm]] += d; scr[scrOf[nm]] += d; bump(lt["cat:"+catOf[nm]], old, k); bump(lt["scr:"+scrOf[nm]], old, k); }
      }
      out.at[dates[j]] = j;
      out.sum.push(sum / N);
      var tb = {}; for (c in byKey) tb[c] = byKey[c];
      out.tally.push({ byKey:tb, none:none });
      for (c in cat) out.cat[c].push(cat[c] / N);
      for (c in scr) out.scr[c].push(scr[c] / N);
      for (c in lt){ var lb = {}; for (var lc in lt[c].byKey) lb[lc] = lt[c].byKey[lc]; out.lane[c].push({ byKey:lb, none:lt[c].none }); }
    }
    return (SWEEP[masterId] = out);
  }

  // (The #6 hover crosshair + floating read-out popover were removed. The chart's only
  //  pointer interaction is now click-to-pick-a-moment; hover shows nothing.)

  // Map a client X to the NEAREST snapshot index. The forward map is
  // X(off)=pl+off/lastOff*iw drawn into the viewBox, so we only need the snapshot X
  // anchors (data-snaps) and the box->viewBox ratio — no interpolation, series is discrete.
  function chartIndexFromClient(svg, clientX){
    var snaps; try { snaps = JSON.parse(svg.getAttribute("data-snaps")||"[]"); } catch(e){ snaps = []; }
    if (!snaps.length){ return -1; }
    var box = svg.getBoundingClientRect(); if (!box.width){ return -1; }
    var vb = svg.viewBox && svg.viewBox.baseVal;
    var vbw = (vb && vb.width) || box.width;
    var ux = (clientX - box.left) / box.width * vbw;       // pointer X in SVG user-space
    var nearest = 0, best = Infinity;
    for (var i=0;i<snaps.length;i++){
      var d = Math.abs(snaps[i].x - ux);
      if (d < best){ best = d; nearest = i; }
    }
    return nearest;
  }
  // Click anywhere on the chart to pick the nearest version that changed something: the
  // color discs, the lanes and the panel follow it. Now clears the pick (back to live).
  function chartClick(evt){
    var svg = evt.target.closest && evt.target.closest(".tl-chart");
    if (!svg){ return; }
    var idx = chartIndexFromClient(svg, evt.clientX); if (idx < 0){ return; }
    scrubSet(nearestChange(viewBounds()[0] + idx));
  }
  // Hover readout: the date and progress at the version under the pointer,
  // without picking it (a click still does).
  function chartHover(evt){
    var tip = document.querySelector(".tl-tip"), svg = evt.target.closest && evt.target.closest(".tl-flow");
    if (!svg){ hoverOff(); return; }
    var idx = chartIndexFromClient(svg, evt.clientX); if (idx < 0) return;
    var j = viewBounds()[0] + idx;
    var snaps = JSON.parse(svg.getAttribute("data-snaps") || "[]"), x = snaps[idx] ? snaps[idx].x : 0;
    if (!tip){ tip = document.createElement("div"); tip.className = "tl-tip"; svg.parentNode.appendChild(tip); }
    tip.hidden = false;
    tip.innerHTML = '<b>'+esc(tickLabel(H.trend.dates[j]))+'</b><span>'+chartPctAt(j).toFixed(1)+'%</span>';
    // centered on the pointer, but never past the chart's edges (it clips); unrounded widths
    var half = tip.getBoundingClientRect().width / 2, w = svg.getBoundingClientRect().width;
    tip.style.left = Math.max(half, Math.min(w - half, x))+"px";
    // and a dashed line marks that version across the plot
    var area = svg.querySelector(".tl-crossarea"), line = svg.querySelector(".tl-hoverline");
    if (!line){ line = document.createElementNS(svg.namespaceURI, "line"); line.setAttribute("class", "tl-hoverline"); svg.insertBefore(line, area); }
    var y0 = +area.getAttribute("y");
    line.setAttribute("x1", x); line.setAttribute("x2", x); line.setAttribute("y1", y0); line.setAttribute("y2", y0 + +area.getAttribute("height"));
    line.style.display = "";
  }
  function hoverOff(){
    var t = document.querySelector(".tl-tip"), l = document.querySelector(".tl-hoverline");
    if (t) t.hidden = true;
    if (l) l.style.display = "none";
  }
  // Per-version change counts for the scope: the focused master's, else every master's summed.
  function scopeChanges(){
    if (state.master != null) return changeCounts(state.master);
    var sum = [];
    H.masters.forEach(function(m){ changeCounts(m.id).forEach(function(c, i){ sum[i] = (sum[i] || 0) + c; }); });
    return sum;
  }
  // The Overview chart picks only versions where the scope's colors changed (or now), so
  // the Changes list (that version vs the one before) is never empty.
  // Only inside the chart's window; now counts when the window reaches it.
  function nearestChange(idx){
    var chg = scopeChanges(), last = chg.length - 1, b = viewBounds(), best = b[1] === last ? last : -1;
    for (var k = Math.max(1, b[0]); k <= Math.min(b[1], last - 1); k++){
      if (chg[k] && (best < 0 || Math.abs(k - idx) < Math.abs(best - idx))) best = k;
    }
    return best < 0 ? b[1] : best;
  }
  function stepChange(dir){
    var chg = scopeChanges(), last = chg.length - 1, b = viewBounds(), lo = Math.max(1, b[0]);
    for (var k = scrubIndex() + dir; k >= lo && k <= b[1] && k < last; k += dir){ if (chg[k]) return k; }
    return dir > 0 && b[1] === last ? last : scrubIndex();
  }
  // Keyboard, from anywhere: Left/Right step to the previous / next version that changed something.
  function chartKey(evt){
    if (evt.key!=="ArrowLeft" && evt.key!=="ArrowRight" || evt.metaKey || evt.ctrlKey || evt.altKey){ return; }
    evt.preventDefault();
    scrubSet(stepChange(evt.key==="ArrowRight" ? 1 : -1));
  }

  // Count-up a lane's percentage from -> to (uses the rAF timestamp, no clock).
  function tweenNumber(el, from, to, dur){
    requestAnimationFrame(function step(ts){
      if (step.t0 == null){ step.t0 = ts; }
      var p = Math.min(1, (ts - step.t0) / dur), ease = p*p*(3-2*p);
      el.textContent = Math.round(from + (to - from) * ease) + "%";
      if (p < 1){ requestAnimationFrame(step); }
    });
  }
  // Animate the category/script lane numbers whenever they change (picking a different
  // moment on the chart, or focusing a master). Each render carries the new value in
  // data-to; we tween from the last shown value cached per lane key. Reduced-motion /
  // headless snap straight to the value. Zoom drags don't change the numbers, so they
  // never trigger a tween.
  function animateLaneNumbers(){
    var anim = !window.__cfdNoAnim && !(window.matchMedia && window.matchMedia("(prefers-reduced-motion:reduce)").matches);
    var els = document.querySelectorAll(".tl-lane-pct[data-lanekey]");
    for (var i = 0; i < els.length; i++){
      var el = els[i], key = el.getAttribute("data-lanekey"), to = parseInt(el.getAttribute("data-to"), 10) || 0;
      var from = (key in laneNumCache) ? laneNumCache[key] : to;
      laneNumCache[key] = to;
      if (!anim || from === to){ el.textContent = to + "%"; continue; }
      el.textContent = from + "%";
      tweenNumber(el, from, to, 460);
    }
  }

  // ----- chart morph (master switch) -------------------------------------------
  // On a master switch the chart's bands reshape from the old master's values to the new
  // one's: both charts' band edges are resampled on the union of their x's, and a band only
  // one side has lies flat on the stack below it. The rest of the page updates in place.
  // A switch mid-morph starts from the shapes on screen. Silenced under reduced-motion / headless.
  var chartMorphStop = null, MORPH_MS = 520;     // the lane lines take the same time on a master switch
  function easeInOut(k){ return k < .5 ? 4*k*k*k : 1 - Math.pow(2 - 2*k, 3)/2; }   // easeInOutCubic
  function chartBands(svg){
    var out = {keys:[], m:{}};
    if (svg) [].forEach.call(svg.querySelectorAll(".tl-band"), function(p){
      var n = p.getAttribute("d").match(/-?\d+(?:\.\d+)?/g).map(Number), pts = [];
      for (var i = 0; i < n.length; i += 2) pts.push([n[i], n[i+1]]);
      var k = p.getAttribute("fill"), half = pts.length/2;
      out.keys.push(k); out.m[k] = {up:pts.slice(0, half), lo:pts.slice(half).reverse(), cls:p.getAttribute("class")};
    });
    return out;
  }
  function morphChart(old){
    var svg = document.querySelector(".ov-chart svg.tl-flow"), g = svg && svg.querySelector("g");
    if (!g) return;
    var area = svg.querySelector(".tl-crossarea"), base = +area.getAttribute("y") + +area.getAttribute("height");
    var neu = chartBands(svg), keys = neu.keys.slice();
    // stack order: the new chart's, an old-only band slotted just above its old neighbour below
    old.keys.forEach(function(k, i){ if (keys.indexOf(k) < 0) keys.splice(i ? keys.indexOf(old.keys[i-1]) + 1 : 0, 0, k); });
    if (!keys.length) return;
    var seen = {}, xs = [];
    [old, neu].forEach(function(B){ B.keys.forEach(function(k){ B.m[k].up.forEach(function(p){ if (!seen[p[0]]){ seen[p[0]] = 1; xs.push(p[0]); } }); }); });
    xs.sort(function(a, b){ return a - b; });
    var rxs = xs.slice().reverse();
    function at(pts, x){
      if (x <= pts[0][0]) return pts[0][1];
      for (var i = 1; i < pts.length; i++) if (x <= pts[i][0]){ var a = pts[i-1], b = pts[i]; return a[1] + (b[1] - a[1])*(b[0] === a[0] ? 1 : (x - a[0])/(b[0] - a[0])); }
      return pts[pts.length-1][1];
    }
    function sample(B){
      var top = xs.map(function(){ return base; }), out = {};
      keys.forEach(function(k){
        var e = B.m[k];
        out[k] = e ? {up:xs.map(function(x){ return at(e.up, x); }), lo:xs.map(function(x){ return at(e.lo, x); })} : {up:top, lo:top};
        top = out[k].up;
      });
      return out;
    }
    function poly(px, ys){ return px.map(function(x, i){ return (i ? " L" : "M")+x.toFixed(1)+" "+ys[i].toFixed(1); }).join(""); }
    var from = sample(old), to = sample(neu), fills = {}, tops = {}, els = [], made = [];
    [].forEach.call(g.children, function(e){ if (e.getAttribute("fill")) fills[e.getAttribute("fill")] = e; else tops[e.getAttribute("stroke")] = e; });
    var firstTop = g.querySelector(".tl-band-top");
    keys.forEach(function(k){
      var band = fills[k], top = tops[k];
      if (!band){
        band = document.createElementNS(svg.namespaceURI, "path"); band.setAttribute("class", old.m[k].cls); band.setAttribute("fill", k);
        top = document.createElementNS(svg.namespaceURI, "path"); top.setAttribute("class", old.m[k].cls.replace("tl-band", "tl-band-top")); top.setAttribute("stroke", k);
        g.insertBefore(band, firstTop); g.appendChild(top); firstTop = firstTop || top; made.push(band, top);
      }
      els.push({k:k, band:band, top:top, d:band.getAttribute("d"), t:top.getAttribute("d")});
    });
    function draw(u){
      els.forEach(function(e){
        var a = from[e.k], b = to[e.k], line = poly(xs, a.up.map(function(y, i){ return y + (b.up[i] - y)*u; }));
        e.band.setAttribute("d", line + poly(rxs, a.lo.map(function(y, i){ return y + (b.lo[i] - y)*u; }).reverse()).replace(/^M/, " L") + "Z");
        e.top.setAttribute("d", line);
      });
    }
    var t0 = null, id = 0;
    function end(){
      cancelAnimationFrame(id); chartMorphStop = null;
      els.forEach(function(e){ if (e.d){ e.band.setAttribute("d", e.d); e.top.setAttribute("d", e.t); } });
      made.forEach(function(e){ e.remove(); });
    }
    function frame(ts){
      if (t0 == null) t0 = ts;
      var k = Math.min(1, (ts - t0)/MORPH_MS);
      if (k >= 1){ end(); return; }
      draw(easeInOut(k));
      id = requestAnimationFrame(frame);
    }
    draw(0);                                       // the old shapes from the first paint on
    id = requestAnimationFrame(frame);
    chartMorphStop = end;
  }
  function noAnim(){
    return !!window.__cfdNoAnim ||
      (window.matchMedia && window.matchMedia("(prefers-reduced-motion:reduce)").matches);
  }
  // ----- lane sparkline morph (scrub, master switch) ---------------------------
  // Tween each lane's polyline from its PREVIOUS shape to the new one when the picked
  // moment or the master changes, so the line reshapes instead of snapping. Points are
  // cached per data-spark key: the shape on screen, frame by frame while a tween runs, so
  // a redraw mid-tween (fast arrow presses) carries on from there instead of jumping.
  function _parsePts(s){
    return (s||"").trim().split(/\s+/).map(function(p){ var c=p.split(","); return [parseFloat(c[0]), parseFloat(c[1])]; })
      .filter(function(p){ return !isNaN(p[0]) && !isNaN(p[1]); });
  }
  function _ptsStr(a){ return a.map(function(p){ return p[0].toFixed(1)+","+p[1].toFixed(1); }).join(" "); }
  function _resample(pts, count){
    if (pts.length === count) return pts.slice();
    var out = [], last = pts.length - 1;
    for (var i=0;i<count;i++){
      var t = (count<2?0:i/(count-1))*last, lo = Math.floor(t), hi = Math.min(lo+1, last), f = t-lo;
      out.push([pts[lo][0]+(pts[hi][0]-pts[lo][0])*f, pts[lo][1]+(pts[hi][1]-pts[lo][1])*f]);
    }
    return out;
  }
  var sparkRaf = {};                              // data-spark key -> the frame of its tween in flight
  function _tweenSpark(poly, key, a, b, finalPts, withChart){   // withChart: in step with the chart's morph
    var dur = withChart ? MORPH_MS : 380, start = null;
    poly.setAttribute("points", _ptsStr(a));      // start from the old shape (no flash of the target)
    function frame(ts){
      if (start == null) start = ts;
      var k = Math.min(1, (ts - start)/dur), e = withChart ? easeInOut(k) : 1 - Math.pow(1-k, 3);   // else easeOutCubic
      if (k >= 1){ poly.setAttribute("points", _ptsStr(finalPts)); sparkPrev[key] = finalPts; delete sparkRaf[key]; return; }
      var cur = a.map(function(p,i){ return [p[0]+(b[i][0]-p[0])*e, p[1]+(b[i][1]-p[1])*e]; });
      sparkPrev[key] = cur; poly.setAttribute("points", _ptsStr(cur));
      sparkRaf[key] = requestAnimationFrame(frame);
    }
    sparkRaf[key] = requestAnimationFrame(frame);
  }
  function morphSparks(animate, withChart){
    var polys = document.querySelectorAll(".tl-lane-spark polyline[data-spark]");
    Array.prototype.forEach.call(polys, function(poly){
      var key = poly.getAttribute("data-spark");
      var target = _parsePts(poly.getAttribute("points"));
      var prev = sparkPrev[key], live = key in sparkRaf;
      if (live){ cancelAnimationFrame(sparkRaf[key]); delete sparkRaf[key]; }   // its line was just redrawn
      sparkPrev[key] = target;                     // always refresh, so the next morph is from what's shown
      if (!(animate || live) || noAnim() || !prev || prev.length < 2 || target.length < 2) return;
      if (_ptsStr(prev) === _ptsStr(target)) return;
      var npts = Math.max(prev.length, target.length, 2);
      _tweenSpark(poly, key, _resample(prev, npts), _resample(target, npts), target, withChart);
    });
  }
  function update(){
    barsAnim = !introPlayed;                    // fill the color bar once on first paint, never on master switches
    introPlayed = true;
    var masterChanged = (lastRenderMaster !== "__cfd_init__") && (state.master !== lastRenderMaster);
    var laneChanged = state.lane !== lastRenderLane;
    lastRenderMaster = state.master; lastRenderLane = state.lane;
    var bodyEl = document.getElementById("cfd-body");
    // read before stopping: a morph in flight carries on, through any redraw (an arrow at the list's end too)
    var oldBands = (masterChanged || laneChanged || chartMorphStop) && !noAnim() ? chartBands(document.querySelector(".ov-chart svg.tl-flow")) : null;
    if (chartMorphStop) chartMorphStop();
    bodyEl.innerHTML = tabsView();
    morphSparks(scrubAnim || masterChanged, masterChanged);   // tween lane sparkline shapes on scrub and master switch (always refresh the cache)
    animateLaneNumbers();                        // count-up the lane %s when the picked moment / focus changes
    fitOvChart();
    sideFade();
    if (oldBands) morphChart(oldBands);          // after the fit: it may redraw the chart
    document.getElementById("cfd-master").value = state.master == null ? "" : String(state.master);
    document.getElementById("cfd-master-x").hidden = state.master == null;
    scrubAnim = false;                           // consumed: the scrub animation runs once per picked moment
  }

  function setFocus(fk){ state.focus = fk; update(); }
  function pickLane(key){ state.lane = state.lane === key ? null : key; update(); }
  // The side panel fades at its foot while more sits below (macOS hides scrollbars).
  function sideFade(){
    var s = document.querySelector(".ctx-side");
    if (s) s.classList.toggle("more", s.scrollHeight - s.scrollTop - s.clientHeight > 2);
  }

  function bind(){
    // Escape steps back one level: the date picker, the color focus, the category/script, the
    // picked version, the master.
    document.addEventListener("keydown", function(e){
      if (e.key==="Escape"){
        if (state.cal != null){ state.cal = null; update(); }
        else if (state.focus!==null) setFocus(null);
        else if (state.lane != null){ state.lane = null; update(); }
        else if (state.tlScrub != null) scrubSet(Infinity);
        else if (state.master != null){ state.master = null; update(); }
      }
    });
    window.addEventListener("keydown", function(e){ if (mgrid && mgrid.open) e.stopPropagation(); }, true);   // the masters grid keeps Esc and the arrows
    window.addEventListener("resize", function(){ fitOvChart(); sideFade(); });
    document.addEventListener("scroll", function(e){ if (e.target.classList && e.target.classList.contains("ctx-side")) sideFade(); }, true);
    document.getElementById("cfd-master").addEventListener("change", function(e){
      var m = H.masters.filter(function(x){ return String(x.id) === e.target.value; })[0];
      state.master = m ? m.id : null; update();
    });
    document.getElementById("cfd-master-x").addEventListener("click", function(){ state.master = null; update(); });
    var bodyEl = document.getElementById("cfd-body");
    bodyEl.addEventListener("click", function(e){
      if (e.target.closest("[data-mgrid]")){ openMastersGrid(); return; }
      var fn = e.target.closest("[data-funnel]"); if (fn){ state.funnelOpen = (state.funnelOpen === false); update(); return; }
      var cg = e.target.closest("[data-chg]"); if (cg){ var ck = cg.getAttribute("data-chg"); state.chgOpen[ck] = !state.chgOpen[ck]; update(); return; }
      var cr = e.target.closest(".lb-row[data-m]"); if (cr){ var cid=cr.getAttribute("data-m"); state.master=(state.master===cid)?null:cid; state.focus = null; update(); return; }
      var lr = e.target.closest("[data-lane]"); if (lr){ pickLane(lr.getAttribute("data-lane")); return; }
      if (e.target.closest("[data-unlane]")){ state.lane = null; update(); return; }
      var nw = e.target.closest("[data-now]"); if (nw){ scrubSet(Infinity); return; }   // back to now
      var cb = e.target.closest("[data-cal]"); if (cb){ state.cal = state.cal != null ? null : H.trend.dates[scrubIndex()].slice(0, 7); update(); return; }
      var cm = e.target.closest("[data-calm]"); if (cm){ state.cal = cm.getAttribute("data-calm"); update(); return; }
      var cd = e.target.closest("[data-calday]"); if (cd){ state.cal = null; scrubSet(+cd.getAttribute("data-calday")); return; }
      var rv = e.target.closest("[data-ver]"); if (rv){ scrubSet(+rv.getAttribute("data-ver")); return; }
    });
    // Click the chart to PICK a moment (scrub -> sidebar discs + lanes follow); the
    // left/right arrow keys step the picked moment while the chart is focused.
    bodyEl.addEventListener("pointerdown", chartClick);
    bodyEl.addEventListener("pointermove", chartHover);
    bodyEl.addEventListener("pointerleave", hoverOff);
    bodyEl.addEventListener("keydown", function(e){   // a lane row by keyboard; it keeps the focus through the redraw
      var lr = (e.key === "Enter" || e.key === " ") && e.target.closest && e.target.closest("[data-lane]"); if (!lr) return;
      e.preventDefault(); var key = lr.getAttribute("data-lane"); pickLane(key);
      [].some.call(bodyEl.querySelectorAll("[data-lane]"), function(r){ if (r.getAttribute("data-lane") === key){ r.focus(); return true; } });
    });
    document.addEventListener("keydown", chartKey);
    // A press anywhere outside the date picker closes it.
    document.addEventListener("pointerdown", function(e){
      if (state.cal != null && !e.target.closest(".cal")){ state.cal = null; update(); }
    }, true);
    // Color-bar segments live both in the static global bar and in the per-master
    // card (inside #cfd-body), so delegate their clicks at the document level.
    document.addEventListener("click", function(e){
      if (e.target.closest("[data-unfocus]")){ setFocus(null); return; }
      var seg = e.target.closest("[data-fkey]");
      if (!seg) return;
      var fk = parseInt(seg.getAttribute("data-fkey"),10);
      setFocus(state.focus===fk ? null : fk);
    });
  }
  // ----- Color Tower: one disc per master, the master navigator -------------
  // A persistent canvas in the left sidebar. Each disc is a blurred wheel of that
  // master's label-color distribution; the focused (current) master lights up,
  // the rest are trimmed. Clicking a disc selects that master. Auto-spins.
  function initTower(){
    var cv = document.getElementById("cfd-tower-cv");
    if (!cv || !cv.getContext || !H.masters.length) return;
    var ctx = cv.getContext("2d");
    if (!ctx) return;                       // headless / no-canvas env: skip
    // Empty disc ~ page bg (--track).
    var emptyFillValue = null;
    function emptyFill(){
      if (!emptyFillValue) emptyFillValue = (getComputedStyle(document.documentElement).getPropertyValue("--track")||"").trim() || "#15171c";
      return emptyFillValue;
    }
    var W = cv.width, Hc = cv.height, FS = 320;
    // HiDPI: supersample every backing store by devicePixelRatio (capped at 3) while
    // keeping all geometry in CSS-pixel units. fit() recomputes dpr on resize; the
    // offscreen builders below read this same closure var. dpr=1 reproduces 1x exactly.
    var dpr = Math.min(window.devicePixelRatio || 1, 3);
    var DISC_ALPHA = 0.95, tilt = 0.5, trimVal = 0.5, opacityVal = 0.37;
    var DISC_BRIGHT = 1.2;  // every lit disc rendered 20% lighter (global)
    var FOCUS_GLOW = 1.4;   // selected disc: +40% halo glow on top
    var rot = -0.5;
    var VISIBLE = Math.min(16, H.masters.length);   // discs shown at once
    var vt = 0;                                      // scroll: master index at window top
    function hueHsl(i){ return "hsl(" + Math.round((i/12)*360) + ",100%,55%)"; }
    // the ACTUAL Glyphs label color for slot i (from the model / CSS vars), not a synthetic rainbow
    function slotColor(i){
      if (H.colors && H.colors[String(i)]) return H.colors[String(i)];
      var v=(getComputedStyle(document.documentElement).getPropertyValue("--c"+i)||"").trim();
      return v || hueHsl(i);
    }
    // Per-color glyph counts for a master. Scrub-aware: when a version is picked on the
    // chart (state.tlScrub set), reconstruct that master's color state at the
    // picked snapshot via stateAt — so clicking the graph spins these discs back in time.
    // Otherwise the live (current) label keys.
    function countsOf(m){
      var c = [0,0,0,0,0,0,0,0,0,0,0,0], i;
      if (state.tlScrub != null){
        var dates = (H.trend && H.trend.dates) || [], date = dates[scrubIndex()];
        if (date != null){
          var snap = stateAt(m.id, date);
          for (var name in snap){ var sk = snap[name]; if (sk>=0 && sk<12) c[sk]++; }
          return c;
        }
      }
      var keys = m.keys || [];
      for (i=0;i<keys.length;i++){ var k=keys[i]; if (k>=0 && k<12) c[k]++; }
      return c;
    }
    // Uncolored share consistent with countsOf: at a scrubbed moment it's whatever the
    // glyph total minus the colored count is; live it's the master's stored uncolored.
    function uncoloredOf(m, counts){
      if (state.tlScrub != null){
        var s=0; for (var i=0;i<12;i++){ s+=counts[i]; }
        return Math.max(0, (H.glyphTotal||0) - s);
      }
      return m.uncolored || 0;
    }
    var UNCOL = "hsl(225,8%,4%)";   // dark neutral gray for the uncolored share
    function buildField(counts, uncolored, gray){
      var off=document.createElement("canvas"); off.width=off.height=Math.round(FS*dpr);
      var g=off.getContext("2d"); g.setTransform(dpr,0,0,dpr,0,0);
      var cx=FS/2, cy=FS/2, R=FS*0.46, sum=0, i;
      for (i=0;i<12;i++) sum+=counts[i];
      var total=sum+uncolored;
      if (total){
        // one wedge per present color (hue) + the uncolored share (gray), all
        // proportional to the master's glyph total so uncolored glyphs show too
        var segs=[];
        for (i=0;i<12;i++){ if(counts[i]>0) segs.push([counts[i]/total, gray?"#3a3f49":slotColor(i)]); }
        if (uncolored>0) segs.push([uncolored/total, gray?"#23262d":UNCOL]);
        var filled=false;
        try {
          // true proportional wedges (hard edges): each color spans exactly its
          // share. Two stops per wedge (start + end, same color) give a crisp
          // boundary; the later blur softens it without distorting the proportion.
          var base=g.createConicGradient(-Math.PI/2,cx,cy), acc=0;
          for (i=0;i<segs.length;i++){
            base.addColorStop(Math.min(acc,1), segs[i][1]);
            acc+=segs[i][0];
            base.addColorStop(Math.min(acc,1), segs[i][1]);
          }
          g.fillStyle=base; g.fillRect(0,0,FS,FS); filled=true;
        } catch(e){ filled=false; }
        if (!filled){ var a=-Math.PI/2;
          for (i=0;i<segs.length;i++){ var a1=a+segs[i][0]*Math.PI*2;
            g.fillStyle=segs[i][1]; g.beginPath(); g.moveTo(cx,cy); g.arc(cx,cy,R*1.25,a,a1); g.closePath(); g.fill(); a=a1; } }
        var dk=g.createRadialGradient(cx,cy,0,cx,cy,R*0.72);
        dk.addColorStop(0,"rgba(0,0,0,0.58)"); dk.addColorStop(0.5,"rgba(0,0,0,0.26)"); dk.addColorStop(1,"rgba(0,0,0,0)");
        g.fillStyle=dk; g.beginPath(); g.arc(cx,cy,R*0.72,0,7); g.fill();
      }
      var bl=document.createElement("canvas"); bl.width=bl.height=Math.round(FS*dpr); var bg=bl.getContext("2d");
      bg.setTransform(dpr,0,0,dpr,0,0);
      if (CTX_FILTER_OK){
        bg.filter="blur("+Math.round(FS*0.125)+"px) saturate(1.6) brightness(0.92)"; bg.drawImage(off,0,0,FS,FS); bg.filter="none";
      } else {   // WebKit: the field also carries the lit discs' brightness (paintDisc undoes it to dim)
        var sf = softFilter(off, Math.round(FS*0.125), 1.6, 0.92*DISC_BRIGHT);
        bg.drawImage(sf, 0, 0, FS, FS); bl.__t = sf.__t;
      }
      bg.globalCompositeOperation="destination-in";
      bg.fillStyle="#000"; bg.beginPath(); bg.arc(FS/2,FS/2,FS*0.5,0,7); bg.fill();
      bg.globalCompositeOperation="source-over";
      return bl;
    }
    // When a color is focused (clicked in a progress bar), each disc shows only
    // that color's share; everything else folds into the uncolored gray. fk<0
    // or null restores the full label distribution.
    function focusedCounts(m, fk){
      var c = countsOf(m), unc = uncoloredOf(m, c);
      if (fk==null) return { counts:c, uncolored:unc };                                       // no focus -> full distribution
      if (fk<0 || fk>11) return { counts:[0,0,0,0,0,0,0,0,0,0,0,0], uncolored:unc };          // None focused -> gray share only
      var only=[0,0,0,0,0,0,0,0,0,0,0,0]; only[fk]=c[fk];
      return { counts:only, uncolored:(H.glyphTotal||0)-c[fk] };                               // one color -> its wedge + gray rest
    }
    var FIELDS, EMPTY;
    function buildFields(fk){
      FIELDS = H.masters.map(function(m){ var d=focusedCounts(m,fk); return buildField(d.counts, d.uncolored); });
      EMPTY = H.masters.map(function(m){ var d=focusedCounts(m,fk), s=0, i; for(i=0;i<12;i++) s+=d.counts[i]; return (s+d.uncolored)===0; });
    }
    var curFocus = (state.focus==null?null:state.focus);
    var curScrub = state.tlScrub;   // rebuild the disc fields when the picked moment changes
    buildFields(curFocus);
    // Smoothly crossfade each disc's color field old -> new when the focused color or
    // picked moment changes, instead of snapping. Reduced-motion / headless = instant.
    var TOWER_ANIM = !window.__cfdNoAnim && !(window.matchMedia && window.matchMedia("(prefers-reduced-motion:reduce)").matches);
    // ----- Color Bloom opening intro (variant 4: smootherstep, ~760ms/disc, ~120ms stagger) -----
    // Each disc starts as a blurry gray blank; its color BLOOMS in via a soft cross-fade (no
    // hard conic wipe / cut line), staggered top->bottom down the stack. Plays ONCE on open, frame-paced like the spin ramp
    // (~60fps). Reduced-motion / headless: skipped entirely (discs render full color at once).
    var GRAYFIELDS = H.masters.map(function(m){ var d=focusedCounts(m,null); return buildField(d.counts,d.uncolored,true); });
    function smootherstep(t){ t=t<0?0:(t>1?1:t); return t*t*t*(t*(t*6-15)+10); }
    var INTRO_PER = 23, INTRO_STAG = 4;            // 2x faster: ~380ms per disc, ~65ms stagger at 60fps
    var introFrame = 0, introDone = !TOWER_ANIM;   // reduced-motion: no intro, full color immediately
    function introReveal(i){ if (introDone) return 1; return smootherstep((introFrame - i*INTRO_STAG)/INTRO_PER); }
    var PREV_FIELDS = null, morph = 1, MORPH_STEP = 0.044;   // color dissolve, 2x faster
    var mtmp = document.createElement("canvas"); mtmp.width = mtmp.height = Math.round(FS*dpr);
    var mctx = mtmp.getContext("2d");
    function fieldFor(i){
      if (morph >= 1 || !PREV_FIELDS || !PREV_FIELDS[i]) return FIELDS[i];
      var nf = FIELDS[i];
      if (mtmp.width !== nf.width || mtmp.height !== nf.height){ mtmp.width = nf.width; mtmp.height = nf.height; }
      var t = morph*morph*(3-2*morph);                       // smoothstep dissolve
      mctx.clearRect(0,0,mtmp.width,mtmp.height);
      mctx.globalAlpha = 1; mctx.drawImage(PREV_FIELDS[i],0,0,mtmp.width,mtmp.height);   // old colors beneath
      mctx.globalAlpha = t; mctx.drawImage(nf,0,0,mtmp.width,mtmp.height);               // new colors fade in
      mctx.globalAlpha = 1;
      mtmp.__field = nf;
      return mtmp;
    }
    // WebKit halo: a padded, pre-blurred copy of a field, built once per field and blur
    // width instead of a ctx.filter blur every frame. Without the field's baked-in lit
    // brightness, as the browser blurs the plain field. A dissolve frame reuses the
    // incoming field's copy. Blurs the field's small pre-upscale copy (__t): reading
    // back the full GPU-backed field cost ~10x the blur itself.
    function haloOf(src, sigma){
      src = src.__field || src;
      var cache = src.__halo || (src.__halo = {}), key = sigma.toFixed(1);
      if (!cache[key]){
        var lo = src.__t || src, k = lo.width/src.width, pad = Math.ceil(sigma*k*3), c = document.createElement("canvas");
        c.width = c.height = lo.width + pad*2;
        var cg = c.getContext("2d", {willReadFrequently:true}); cg.drawImage(lo, pad, pad);
        cg.globalCompositeOperation = "destination-in";   // the field's own circle clip
        cg.beginPath(); cg.arc(c.width/2, c.width/2, lo.width/2, 0, 7); cg.fill();
        cache[key] = softFilter(c, sigma*k, 1, 1/DISC_BRIGHT, true);
        cache[key].__w = c.width/k;
      }
      return cache[key];
    }
    var FROST = (function(){
      var c=document.createElement("canvas"); c.width=c.height=Math.round(FS*dpr); var g=c.getContext("2d");
      g.setTransform(dpr,0,0,dpr,0,0);
      // white frost sparkle
      for (var k=0;k<1600;k++){ var x=Math.random()*FS,y=Math.random()*FS,r=Math.random()*1.6+0.3;
        g.fillStyle="rgba(255,255,255,"+(Math.random()*0.07)+")"; g.beginPath(); g.arc(x,y,r,0,7); g.fill(); }
      // fine dark dust grains interleaved so the surface reads as frozen/dusty texture
      // rather than only sparkle — finer + fainter than the frost, kept subtle.
      for (var kd=0;kd<1100;kd++){ var dx=Math.random()*FS,dy=Math.random()*FS,dr=Math.random()*0.9+0.2;
        g.fillStyle="rgba(0,0,0,"+(Math.random()*0.05+0.008)+")"; g.beginPath(); g.arc(dx,dy,dr,0,7); g.fill(); }
      var o=document.createElement("canvas"); o.width=o.height=Math.round(FS*dpr); var og=o.getContext("2d");
      og.setTransform(dpr,0,0,dpr,0,0);
      if (CTX_FILTER_OK){ og.filter="blur(0.6px)"; og.drawImage(c,0,0,FS,FS); og.filter="none"; }
      else { og.drawImage(softFilter(c, 0.6, 1, 1),0,0,FS,FS); }
      return o;
    })();
    // Scratch canvases, a fresh one for each layer drawn in a frame: WebKit copies a whole canvas
    // that is redrawn after being drawn from, and one shared scratch made every layer pay that.
    // LAYERS for disc layers, LOOKS for the crossfade's looks (render); used again next frame.
    var LAYERS={all:[], n:0}, LOOKS={all:[], n:0};
    function scratch(pool, w, h){   // the pool's next canvas, at least w x h device px, cleared
      var c = pool.all[pool.n] || (pool.all[pool.n] = document.createElement("canvas")); pool.n++;
      if (c.width!==w || c.height<h){ c.width=w; c.height=Math.max(c.height, h); }
      var g = c.getContext("2d"); g.setTransform(1,0,0,1,0,0); g.clearRect(0,0,w,h);
      return c;
    }

    function paintDisc(g,fA,cx,cy,rx,ry,holeFrac,glow,empty,grayA,reveal){
      if (glow===undefined) glow=1;
      if (reveal===undefined) reveal=1;
      if (empty){   // no colors: a near-background tone at lower opacity (mixes with the bg)
        g.save(); g.translate(cx,cy); g.scale(1,ry/rx);
        g.globalAlpha=0.6; g.fillStyle=emptyFill(); g.beginPath(); g.arc(0,0,rx,0,7); g.fill(); g.globalAlpha=1;
        g.restore();
        return;
      }
      var o=rx*1.14;
      // dreamy/shiny finish at HALF the original strength (all highlight alphas
      // halved) layered over the now-blurrier color field.
      g.save(); g.translate(cx,cy); g.scale(1,ry/rx); g.rotate(rot);
      var halo=[[1.006,3,0.11],[1.025,6,0.07],[1.06,12,0.04]];
      if (CTX_FILTER_OK){
        for (var h=0;h<halo.length;h++){ g.globalAlpha=halo[h][2]*glow*reveal; g.filter="blur("+halo[h][1]+"px)"; var hh=rx*halo[h][0]; g.drawImage(fA,-hh,-hh,hh*2,hh*2); }
        g.filter="none"; g.globalAlpha=1;
      } else if (glow*reveal>0){   // WebKit: same glow from cached blurred copies (sigma in field px)
        for (var hw=0;hw<halo.length;hw++){
          var hr=rx*halo[hw][0], hb=haloOf(fA, halo[hw][1]*fA.width/(2*hr*dpr)), he=hr*hb.__w/fA.width;
          g.globalAlpha=halo[hw][2]*glow*reveal; g.drawImage(hb,-he,-he,he*2,he*2);
        }
        g.globalAlpha=1;
      }
      g.restore();
      g.save(); g.translate(cx,cy); g.scale(1,ry/rx); g.rotate(rot);
      g.beginPath(); g.arc(0,0,rx,0,7); g.clip();
      // a focused disc renders the OTHERS as dark matte grayscale (glow<1 == not the
      // selected master): fully desaturate + darken to charcoal. WebKit applies the same
      // after drawing, as composites inside the clip.
      if (CTX_FILTER_OK){
        var desat = 1 - Math.max(0, Math.min(1, glow));   // 1 for non-focused -> grayscale
        var filt = "";
        if (desat>0) filt = "saturate("+(1-desat).toFixed(3)+") brightness("+(1-desat*0.5).toFixed(3)+")";
        else filt = "brightness("+DISC_BRIGHT.toFixed(3)+")";   // every lit disc 20% lighter (global)
        if (filt) g.filter=filt;
      }
      g.globalAlpha=DISC_ALPHA;
      if (reveal<1 && grayA){            // Color Bloom intro: cross-fade the already-blurry gray
        // base INTO the blurry color field — a soft bloom, NOT a hard conic wedge/cut line.
        // reveal is smootherstep-eased, so the color blooms in evenly with no edgy sweep.
        g.drawImage(grayA,-o,-o,o*2,o*2);
        if (reveal>0){ g.globalAlpha=DISC_ALPHA*reveal; g.drawImage(fA,-o,-o,o*2,o*2); }
      } else { g.drawImage(fA,-o,-o,o*2,o*2); }
      if (!CTX_FILTER_OK && glow<1){   // lit needs nothing: WebKit fields already carry DISC_BRIGHT
        var dim = 1 - Math.max(0, glow);
        g.fillStyle="#000";
        g.globalCompositeOperation="saturation"; g.globalAlpha=dim; g.fillRect(-o,-o,o*2,o*2);
        g.globalCompositeOperation="source-over"; g.globalAlpha=1-(1-dim*0.5)/DISC_BRIGHT; g.fillRect(-o,-o,o*2,o*2);
      }
      g.filter="none"; g.globalAlpha=1; g.restore();
      g.save(); g.translate(cx,cy); g.scale(1,ry/rx); g.beginPath(); g.arc(0,0,rx,0,7); g.clip();
      g.fillStyle="rgba(255,255,255,0.05)"; g.beginPath(); g.arc(0,0,rx,0,7); g.fill();
      g.globalAlpha=0.45; g.drawImage(FROST,-rx,-rx,rx*2,rx*2); g.globalAlpha=1;
      var sheen=g.createLinearGradient(0,-rx,0,rx);
      sheen.addColorStop(0,"rgba(0,0,0,0.11)"); sheen.addColorStop(0.34,"rgba(255,255,255,0.01)");
      sheen.addColorStop(0.66,"rgba(255,255,255,0.02)"); sheen.addColorStop(1,"rgba(255,255,255,0.09)");
      g.fillStyle=sheen; g.beginPath(); g.arc(0,0,rx,0,7); g.fill();
      var hot=g.createRadialGradient(0,rx*0.42,0,0,rx*0.42,rx*0.8);
      hot.addColorStop(0,"rgba(255,255,255,0.075)"); hot.addColorStop(1,"rgba(255,255,255,0)");
      g.fillStyle=hot; g.beginPath(); g.arc(0,0,rx,0,7); g.fill();
      if (holeFrac>0){ var hr=rx*0.26; g.globalCompositeOperation="destination-out";
        var pg=g.createRadialGradient(0,0,0,0,0,hr); pg.addColorStop(0,"rgba(0,0,0,1)"); pg.addColorStop(0.94,"rgba(0,0,0,1)"); pg.addColorStop(1,"rgba(0,0,0,0)");
        g.fillStyle=pg; g.beginPath(); g.arc(0,0,hr,0,7); g.fill(); g.globalCompositeOperation="source-over"; }
      g.restore();
      g.save(); g.translate(cx,cy); g.scale(1,ry/rx);
      var rim=g.createLinearGradient(0,-rx,0,rx); rim.addColorStop(0,"rgba(0,0,0,0.12)"); rim.addColorStop(0.5,"rgba(255,255,255,0.025)"); rim.addColorStop(1,"rgba(255,255,255,0.16)");
      g.strokeStyle=rim; g.lineWidth=2; g.beginPath(); g.arc(0,0,rx*0.992,0,7); g.stroke(); g.restore();
    }
    function shadowInto(g,cx,cy,rx,ry){
      // a deeper, wider drop shadow under each disc so the stack reads with clear
      // separation between discs (the disc below catches a stronger shadow)
      g.save(); g.translate(cx,cy+ry*0.62); g.scale(1,ry/rx);
      var sh=g.createRadialGradient(0,0,0,0,0,rx*1.12); sh.addColorStop(0,"rgba(0,0,0,0.28)"); sh.addColorStop(0.6,"rgba(0,0,0,0.14)"); sh.addColorStop(1,"rgba(0,0,0,0)");
      g.fillStyle=sh; g.beginPath(); g.arc(0,0,rx*1.12,0,7); g.fill(); g.restore();
    }
    var geo={rx:0,ry:0,cx:0,topY:0,dz:0,vt:0};
    function selIndex(){ if (state.master==null) return -1; for (var i=0;i<H.masters.length;i++){ if (H.masters[i].id===state.master) return i; } return -1; }
    var prevSel=-1;
    // A pick fades from what was on screen to the new resting stack (liveSel: -1 none picked, -2
    // every disc dimmed, the opening look): that last look is drawn once, frozen (fz, weight fw)
    // and faded out over the live stack. However fast the picks come, a frame draws one stack.
    var FROZEN=[document.createElement("canvas"), document.createElement("canvas")], fz=null, fw=0, liveSel=null;
    function render(){
      LAYERS.n = LOOKS.n = 0;
      ctx.setTransform(dpr,0,0,dpr,0,0);   // HiDPI: paint in CSS units at physical resolution (re-asserted each frame; save/restore below are balanced)
      ctx.clearRect(0,0,W,Hc);
      var M=H.masters.length; if (!M) return;
      var sel=selIndex(), maxTop=Math.max(0, M-VISIBLE);
      // scroll the focused master into view only when it's outside the window
      if (sel!==prevSel){
        if (sel>=0 && (sel < Math.floor(vt) || sel > Math.floor(vt)+VISIBLE-1)) vt = sel - Math.floor(VISIBLE/2);
        prevSel = sel;
      }
      vt = Math.max(0, Math.min(maxTop, vt));
      // Picking a master FADES the stack from its old look to the new one: the previously-selected
      // disc dims out and the new one lights in. Each look is drawn as it rests, so no disc moves
      // between layers mid-fade (that popped its overlaps). Reduced-motion / headless snaps.
      var FOCUS_STEP = 0.154;   // ease: ~0.5s (prev disc dims out / new lights in)
      if (liveSel===null) liveSel = sel>=0 ? sel : -2;
      var rx=Math.min(104, W*0.46), ry=rx*tilt;
      var topY=ry+16, botPad=ry+12;
      var dz=VISIBLE>1?Math.min(58,(Hc-topY-botPad)/(VISIBLE-1)):0, cx=W/2;   // ~15% tighter stack
      var winBot=topY+(VISIBLE-1)*dz, fade=dz*1.1;
      geo={rx:rx,ry:ry,cx:cx,topY:topY,dz:dz,vt:vt};
      function cyOf(i){ return topY+(i-vt)*dz; }
      function vis(i){ var c=cyOf(i); return c>=topY-dz*1.6 && c<=winBot+dz*1.6; }
      // soft top/bottom of the scroll window: a vertical alpha mask (purely a
      // function of y) so the no-overlap group composite still works
      function edgeFade(g){
        function cl(v){ return Math.max(0,Math.min(1,v)); }
        var gr=g.createLinearGradient(0,0,0,Hc);
        gr.addColorStop(0,"rgba(0,0,0,1)");                       // top: no fade, fully visible
        gr.addColorStop(cl(winBot/Hc),"rgba(0,0,0,1)");
        gr.addColorStop(cl((winBot+fade)/Hc),"rgba(0,0,0,0)");    // bottom fade only
        g.save(); g.globalCompositeOperation="destination-in"; g.fillStyle=gr; g.fillRect(0,0,W,Hc); g.restore();
      }
      // A layer of discs on a scratch canvas just tall enough for the rows they reach (halos blur
      // up to ~36px, shadows fall below), in page units shifted up to its first row.
      function layer(idxs){
        var lo=Infinity, hi=-Infinity;
        for (var k=0;k<idxs.length;k++){ var c=cyOf(idxs[k]); lo=Math.min(lo, c-ry*1.06-36); hi=Math.max(hi, c+Math.max(ry*1.74, ry*1.06+36)); }
        var y0=Math.max(0, Math.floor(lo*dpr)), h=Math.max(1, Math.min(cv.height, Math.ceil(hi*dpr)+1)-y0);
        var sc=scratch(LAYERS, cv.width, h), g=sc.getContext("2d"); g.setTransform(dpr,0,0,dpr,0,-y0);
        return {c:sc, g:g, y0:y0, h:h};
      }
      function layerOut(g, L){ g.drawImage(L.c,0,0,L.c.width,L.h,0,L.y0/dpr,L.c.width/dpr,L.h/dpr); }
      function group(g, idxs, over){   // over: the picked disc under these, cut out of them so it shows whole
        if (!idxs.length) return;
        var L=layer(idxs), lg=L.g;
        for (var k=0;k<idxs.length;k++){ var ii=idxs[k], cyy=cyOf(ii); if(!EMPTY[ii]) shadowInto(lg,cx,cyy,rx,ry); paintDisc(lg,fieldFor(ii),cx,cyy,rx,ry,1,0,EMPTY[ii],GRAYFIELDS[ii],introReveal(ii)); }
        lg.save(); lg.globalCompositeOperation="source-atop"; lg.fillStyle="rgba(0,0,0,"+trimVal+")"; lg.fillRect(0,0,W,Hc); lg.restore();
        edgeFade(lg);
        if (over!=null){ lg.save(); lg.globalCompositeOperation="destination-out"; lg.fillStyle="#000"; lg.translate(cx,cyOf(over)); lg.scale(1,ry/rx); lg.beginPath(); lg.arc(0,0,rx,0,7); lg.fill(); lg.restore(); }
        g.save(); g.globalAlpha=opacityVal; layerOut(g, L); g.restore();
      }
      function focusDisc(g, ii, glowV){ var cyy=cyOf(ii), L=layer([ii]);   // the selected disc: +40% halo glow (halo alpha *glow)
        if(!EMPTY[ii]) shadowInto(L.g,cx,cyy,rx,ry); paintDisc(L.g,fieldFor(ii),cx,cyy,rx,ry,1,glowV,EMPTY[ii],GRAYFIELDS[ii],introReveal(ii));
        edgeFade(L.g);
        layerOut(g, L);
      }
      // The stack at rest with disc s picked, back-to-front: with none (-1) every disc full;
      // else the dimmed discs composite together (one layer, no overlap seams) around the
      // selected one, and those above it leave it uncovered.
      function stack(g, s){
        var pend = [];
        for (var n=M-1;n>=0;n--){
          if (!vis(n)) continue;
          if (s===-1 || n===s){ group(g, pend); pend=[]; focusDisc(g, n, s<0 ? 1 : FOCUS_GLOW); }
          else pend.push(n);
        }
        group(g, pend, s>=0 && vis(s) ? s : null);
      }
      function look(s){ var c=scratch(LOOKS, cv.width, cv.height), g=c.getContext("2d"); g.setTransform(dpr,0,0,dpr,0,0); stack(g, s); return c; }
      function blend(g, a, b, wa){   // g = a*wa + b*(1-wa), device px
        g.save(); g.setTransform(1,0,0,1,0,0); g.globalCompositeOperation="lighter";
        g.globalAlpha=wa; g.drawImage(a,0,0); g.globalAlpha=1-wa; g.drawImage(b,0,0); g.restore();
      }
      var fits = fz && fz.width===cv.width && fz.height===cv.height;
      if (sel!==liveSel){
        if (TOWER_ANIM){   // freeze what is on screen (less the hole, punched below)
          var nf=FROZEN[fz===FROZEN[0] ? 1 : 0], ng=nf.getContext("2d"), shown=look(liveSel);
          if (nf.width!==cv.width || nf.height!==cv.height){ nf.width=cv.width; nf.height=cv.height; } else ng.clearRect(0,0,nf.width,nf.height);
          if (fits) blend(ng, fz, shown, fw); else ng.drawImage(shown,0,0);
          fz=nf; fw=1; fits=true;
        }
        liveSel = sel;
      }
      if (fz){ fw = (!fits || fw < 0.005) ? 0 : fw*(1-FOCUS_STEP); if (!fw) fz=null; }
      if (fz) blend(ctx, fz, look(liveSel), fw);
      else stack(ctx, liveSel);
      // The TOP disc shows the page background through its hole (not the disc
      // below): find the topmost visible non-empty disc and punch its hole through
      // the canvas with a soft destination-out matching paintDisc's hole gradient.
      var topI = -1;
      for (var ti=0; ti<M; ti++){ if (vis(ti)){ topI = ti; break; } }
      if (topI >= 0 && !EMPTY[topI]){
        ctx.save(); ctx.translate(cx, cyOf(topI)); ctx.scale(1, ry/rx);
        ctx.globalCompositeOperation = "destination-out";
        ctx.globalAlpha = 0.7;                 // clear 70% -> hole is 70% see-through, not a stark void
        var hrT = rx*0.26;
        var pgT = ctx.createRadialGradient(0,0,0,0,0,hrT);
        pgT.addColorStop(0,"rgba(0,0,0,1)"); pgT.addColorStop(0.94,"rgba(0,0,0,1)"); pgT.addColorStop(1,"rgba(0,0,0,0)");
        ctx.fillStyle=pgT; ctx.beginPath(); ctx.arc(0,0,hrT,0,7); ctx.fill();
        ctx.restore();
      }
    }
    // Size the canvas to fill the main column down to the footer, and show as
    // many discs as fit (the rest stay scrollable via the wheel).
    function fit(){
      var main=document.getElementById("cfd-main"), host=cv.parentNode;
      // stacked (narrow) the canvas is hidden and #cfd-main holds it, so its height would feed back
      var stacked = window.matchMedia && window.matchMedia("(max-width:780px)").matches;
      // from the canvas's top (under the master list) down to the column's foot, else the list's
      // height pushed the last discs past the clip
      var availW=(host&&host.clientWidth)||240, availH=stacked ? 560
        : main ? main.clientHeight - (cv.getBoundingClientRect().top - main.getBoundingClientRect().top) : 0;
      if (availH<240) availH=560;                      // pre-layout -> fallback
      dpr=Math.min(window.devicePixelRatio || 1, 3);   // HiDPI: recompute on resize (display may move screens)
      cv.style.width=availW+"px"; cv.style.height=availH+"px";   // CSS size stays in logical px (hit-test/layout unchanged)
      cv.width=Math.round(availW*dpr); cv.height=Math.round(availH*dpr);   // backing store = physical px
      W=availW; Hc=availH;                                       // logical drawing units (CSS px)
      var rx=Math.min(104,W*0.46), ry=rx*tilt, topY=ry+16, botPad=ry+12;   // mirror render() geometry
      VISIBLE=Math.max(4, Math.min(H.masters.length, Math.floor((Hc-topY-botPad)/33)+1));   // ~15% tighter disc gap
      vt=Math.max(0, Math.min(Math.max(0,H.masters.length-VISIBLE), vt));
    }
    fit();
    window.addEventListener("resize", function(){ fit(); schedule(); });   // back from narrow: spin again
    // Motion etiquette for the spin loop:
    //  - EASE-IN: the spin ramps 0 -> full speed over ~1.5s (smoothstep on the rot
    //    increment), gated by TOWER_ANIM (the shared __cfdNoAnim / reduced-motion flag).
    //  - PAUSE WHEN HIDDEN: visibilitychange stops scheduling rAF in hidden tabs and
    //    resumes on return — frame counters just continue, so no time-jump.
    //  - REDUCED-MOTION: TOWER_ANIM false = no spin at all; the stack renders once and
    //    repaints only when focus/scrub/master/scroll/size change (the crossfade morph
    //    is already instant in that mode: morph snaps to 1, never animates).
    var SPIN_SPEED = 0.00192;                  // full speed (a quarter of the earlier 0.00768)
    var SPIN_RAMP = 1/90, spinT = 0;           // ease-in progress: ~1.5s at 60fps
    var rafId = null;
    var lastVt = null, lastSel = null, lastW = 0, lastHc = 0;   // reduced-motion dirty tracking
    function loop(){
      rafId = null;
      var fk = (state.focus==null?null:state.focus);
      var sc = state.tlScrub;
      var changed = false;
      if (fk!==curFocus || sc!==curScrub){
        curFocus=fk; curScrub=sc;
        var old=FIELDS; buildFields(curFocus);               // new disc fields for the picked moment / color
        if (TOWER_ANIM){ PREV_FIELDS=old; morph=0; } else { PREV_FIELDS=null; morph=1; }   // crossfade old -> new colors
        changed = true;
      }
      if (morph<1){ morph=Math.min(1, morph+MORPH_STEP); if (morph>=1){ PREV_FIELDS=null; } changed = true; }
      var sel = selIndex();
      if (vt!==lastVt || sel!==lastSel || W!==lastW || Hc!==lastHc){
        lastVt=vt; lastSel=sel; lastW=W; lastHc=Hc; changed = true;   // wheel scroll / master pick / resize
      }
      if (TOWER_ANIM){
        if (!introDone){ introFrame++; if (introFrame > (VISIBLE-1)*INTRO_STAG + INTRO_PER + 4) introDone = true; }
        if (spinT<1) spinT = Math.min(1, spinT+SPIN_RAMP);
        var ramp = spinT*spinT*(3-2*spinT);                  // smoothstep ease-in on the increment
        rot += SPIN_SPEED*ramp;                              // keeps spinning under the pointer too
        render();
      } else if (changed){
        render();                                            // reduced motion: no spin, repaint on change only
      }
      schedule();
    }
    var PAUSED = false;
    function schedule(){
      if (rafId!=null || document.hidden || PAUSED || !cv.offsetWidth) return;  // hidden tab / host pause / narrow: no rAF
      rafId = requestAnimationFrame(loop);
    }
    document.addEventListener("visibilitychange", function(){
      if (document.hidden){ if (rafId!=null){ cancelAnimationFrame(rafId); rafId=null; } }
      else schedule();                                       // visible again: resume where we left off
    });
    // Native host hook: the Glyphs report window pauses the spin while it is not
    // the key window / is occluded — a continuously-spinning canvas forces a
    // compositor commit through the HOST app's main thread every frame, which is
    // what made the report feel laggy inside Glyphs. Browsers never call this.
    window.__cfdSpinPause = function(paused){
      PAUSED = !!paused;
      if (PAUSED){ if (rafId!=null){ cancelAnimationFrame(rafId); rafId=null; } }
      else schedule();
    };
    cv.addEventListener("wheel", function(e){ if (H.masters.length <= VISIBLE) return; e.preventDefault();   // else the page scrolls
      vt += e.deltaY*0.02; vt=Math.max(0, Math.min(Math.max(0,H.masters.length-VISIBLE), vt));
    }, {passive:false});
    cv.addEventListener("click", function(e){
      var rect=cv.getBoundingClientRect();
      var px=(e.clientX-rect.left)*(W/rect.width), py=(e.clientY-rect.top)*(Hc/rect.height);
      for (var i=0;i<H.masters.length;i++){ var cy=geo.topY+(i-geo.vt)*geo.dz;
        if (cy<geo.topY-geo.dz*1.6 || cy>geo.topY+(VISIBLE-1)*geo.dz+geo.dz*1.6) continue;
        var ex=(px-geo.cx)/geo.rx, ey=(py-cy)/geo.ry;
        if (ex*ex+ey*ey<=1){ var id=H.masters[i].id;
          state.master = (state.master===id) ? null : id;   // click the selected disc -> clear focus
          update(); return; } }  // keep the current view (tabs/coverage/...)
    });
    // up/down arrows switch the focused master from anywhere (up = toward the top disc)
    cv.setAttribute("aria-label", "Masters: click a disc, or use the up and down arrow keys");
    window.addEventListener("keydown", function(e){
      if (e.key!=="ArrowUp" && e.key!=="ArrowDown" || e.metaKey || e.ctrlKey || e.altKey) return;
      var M=H.masters.length; if (!M) return;
      var cur=selIndex(), step=(e.key==="ArrowDown")?1:-1;
      var ni = cur<0 ? (step>0?0:M-1) : Math.max(0, Math.min(M-1, cur+step));
      e.preventDefault();
      state.master=H.masters[ni].id; update();   // keep the current view
    });
    loop();
  }

  // The drawn X that clears a pick: the master list's and the date button's.
  var CROSS = '<svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true"><path d="M1.5 1.5l7 7M8.5 1.5l-7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';
  var EXPAND = '<svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true"><path d="M6 1.5h2.5V4M4 8.5H1.5V6M8.5 1.5L5.6 4.4M1.5 8.5l2.9-2.9" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  // Pick a master (or all of them) from a list, above the disc tower; while one is picked, a
  // cross beside the caret goes back to all masters.
  function masterSelect(){
    return '<div class="cfd-master-box"><select id="cfd-master" aria-label="Master"><option value="">All masters</option>'
      + H.masters.map(function(m){ return '<option value="'+esc(m.id)+'">'+esc(m.name)+'</option>'; }).join("")
      + '</select><button type="button" id="cfd-master-x" title="All masters" aria-label="Back to all masters" hidden>'+CROSS+'</button></div>';
  }
  function init(){
    document.getElementById("cfd-app").innerHTML =
      header()
      + '<div id="cfd-main"><aside id="cfd-tower" aria-label="Masters">'+masterSelect()+'<canvas id="cfd-tower-cv" width="240" height="560"></canvas></aside><div id="cfd-body"></div></div>'
      + '<footer class="ft"><span class="ft-l">'+esc(H.fileName)+' · v'+esc(H.version)+'</span>'
      + '<span class="ft-r">AZ Colorflow Report — '+esc(tickLabel(H.generated))+'</span></footer>';
    bind(); update(); initTower();
    // After the first paint the bars have run their fill animation once; stop
    // tagging them ".intro" so later re-renders don't re-animate.
    requestAnimationFrame(function(){ document.body.classList.add("ready"); });
  }
  // Decompress the gzipped model (base64 -> bytes -> gunzip stream -> JSON),
  // then boot. embed_model only ever emits the gzipped block; if it's missing the
  // page is corrupt, so fail loudly rather than silently null-deref a plain block.
  function b64bytes(b64){ var bin=atob(b64), n=bin.length, a=new Uint8Array(n); for (var i=0;i<n;i++) a[i]=bin.charCodeAt(i); return a; }
  function loadModel(){
    var gz = document.getElementById("cfd-model-gz");
    if (!gz)
      return Promise.reject(new Error("Report data block is missing — this file looks incomplete."));
    if (typeof DecompressionStream==="undefined" || typeof Response==="undefined" || typeof Blob==="undefined")
      return Promise.reject(new Error("This report needs a modern browser (gzip decompression)."));
    var stream = new Blob([b64bytes(gz.textContent.trim())]).stream().pipeThrough(new DecompressionStream("gzip"));
    return new Response(stream).text().then(function(t){ return JSON.parse(t); });
  }
  function start(){
    loadModel().then(function(model){
      H = model; normalizeHiddenKeys(); lastOrder = H.order.length ? H.order[H.order.length-1] : null;
      // H.trend is per day (each day's last save; today is the live state): saves on one day
      // are one version everywhere — the chart, the calendar, the arrows, Recent updates.
      init();
    }).catch(function(err){
      // Boot failure. The body ships opacity:0 until "ready" (the first-paint gate,
      // normally added by init()), so without it the error page renders invisibly —
      // add it here too. The card itself is pure CSS (.err-card, hard-coded rainbow
      // mark) — it must not lean on the model, which just failed.
      document.body.classList.add("ready");
      var app = document.getElementById("cfd-app");
      if (app) app.innerHTML =
        '<div class="err-wrap"><div class="err-card" role="alert">'
        + '<span class="err-mark" aria-hidden="true"></span>'
        + '<p class="err-title">This report couldn’t load its data.</p>'
        + '<p class="err-msg">'+esc(err && err.message || "Could not load the report data.")+'</p>'
        + '</div></div>';
    });
  }
  if (document.readyState!=="loading") start();
  else document.addEventListener("DOMContentLoaded", start);
})();
"""
