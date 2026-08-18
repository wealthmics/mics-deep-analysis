"""
The analysis page, emitted as one block of HTML.

Why HTML rather than Streamlit's own components: the layout is a two column grid of cards
with a fixed type scale, and Streamlit's columns and containers bring their own spacing and
chrome that cannot be tuned out. Building the page as a single string means what ships is
what was designed, and the charts are inline SVG drawn from the real series rather than a
chart library's idea of a chart.

Palette and typography are taken from the screener page so the two read as one product.
"""

import math
import re

import pandas as pd

INK, NAVY, GOLD = '#1a1a1a', '#1f3864', '#bf8f00'

# Hover bands are sized by pixels, not by data points, and this is the reason why.
#
# A browser only shows an SVG title once the pointer has RESTED on one element. Giving every
# data point its own band made each band about a pixel wide, so the smallest movement of the
# mouse crossed into the next element and cancelled the tooltip timer. The tooltip then never
# appeared at all - more precision produced less function.
#
# So each band is at least this many viewBox units wide, which lands around eleven screen
# pixels once the chart is stretched to its container. That is wide enough to rest on. The
# band still reports the real date and close of the point beneath it, so nothing is invented,
# and on a 3M chart the bands come out roughly one per trading day anyway.
HOVER_BAND_UNITS = 9
UP, DOWN, MID = '#12703a', '#a5201a', '#8a6300'

CSS = """
<style>
.an *{box-sizing:border-box}
/* No width cap. It was 1180px, then 1380px, and on a laptop that is wider than the cap the
leftover shows up as an empty band beside the page, which is what was being reported. The
page now takes whatever width its container gives it. The main column carries the long
paragraphs, so it is the one that would suffer from an unlimited line length, and it is
capped on its own below instead of capping the whole page. */
.an{font:14px/1.45 -apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1a1a1a;
max-width:none;margin:0}
.an .num{font-variant-numeric:tabular-nums}
.an .mast{background:#fff;border:1px solid #d8dee9;border-radius:8px;padding:22px 26px;
display:flex;justify-content:space-between;align-items:flex-start;gap:28px}
.an .eyebrow{font-size:10.5px;font-weight:700;letter-spacing:.11em;text-transform:uppercase;
color:#bf8f00;margin-bottom:8px}
.an a.back{color:#1f3864;text-decoration:none;border-bottom:1px solid #d8dee9}
.an a.back:hover{border-bottom-color:#1f3864}
@media print{.an a.back{display:none}}
.an .mast h1{margin:0;font-size:27px;font-weight:650;line-height:1.15;letter-spacing:-.01em}
.an .meta{margin-top:8px;font-size:12.5px;font-weight:500}
.an .meta b{font-weight:700}
.an .meta .sep{color:#1f3864;margin:0 7px;font-weight:700}
.an .quote{text-align:right;white-space:nowrap}
.an .quote .px{font-size:31px;font-weight:650;line-height:1;letter-spacing:-.01em}
.an .quote .px span{font-size:13px;font-weight:600;color:#1f3864;margin-left:5px}
.an .quote .chg{margin-top:5px;font-size:13px;font-weight:700}
.an .quote .rng{margin-top:11px;font-size:11px;font-weight:600;color:#1f3864}
.an .bar52{margin-top:5px;width:200px;height:5px;border-radius:2px;background:#e9edf3;
border:1px solid #d8dee9;position:relative}
.an .bar52 i{position:absolute;top:-2px;width:3px;height:9px;background:#1f3864;border-radius:1px}
.an .up{color:#12703a} .an .down{color:#a5201a} .an .mid{color:#8a6300}  /* down and mid are applied from Python, not always present in a given page */
/* The strip of forensic scores.
Flex rather than grid, and hairlines drawn as box shadows rather than a 1px grid gap. Grid
gaps need grid; a renderer that does not have it drops every cell onto its own line, which
is how six scores ended up in a column down one side of the page. Each cell paints its own
left and top hairline in the same colour as the container border, so the cells on the edge
have theirs hidden under the border and the ones in the middle divide the row. */
.an .strip{display:flex;flex-wrap:wrap;background:#d8dee9;
border:1px solid #d8dee9;border-radius:8px;overflow:hidden;margin-top:12px}
.an .strip>div{background:#fff;padding:15px 16px 16px;flex:1 1 0;min-width:145px;
box-shadow:-1px 0 0 #d8dee9,0 -1px 0 #d8dee9}
.an .strip .k{font-size:10px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
color:#1f3864}
.an .strip .v{margin-top:6px;font-size:21px;font-weight:650;line-height:1}
.an .strip .v small{font-size:12px;font-weight:600;color:#1f3864}
.an .strip .n{margin-top:6px;font-size:10.5px;font-weight:500;line-height:1.4}
.an .pill{display:inline-block;padding:1px 6px;border-radius:3px;font-size:9.5px;
font-weight:700;letter-spacing:.04em;text-transform:uppercase;margin-right:4px}
.an .pill.g{background:#e3f1e8;color:#12703a} .an .pill.a{background:#fbf1dc;color:#8a6300}
.an .pill.r{background:#fbe6e4;color:#a5201a} .an .pill.n{background:#e9edf3;color:#1f3864}
/* Flex, not grid, and margins rather than gap. Grid and gap are both fine in a current
browser, but the saved preview file gets opened in whatever is to hand, and an older engine
that does not know grid falls back to stacked blocks, which is the exact fault being fixed.
Flex with a negative margin gutter degrades to a row everywhere. */
.an .counts{display:flex;flex-wrap:wrap;margin:14px -6px 0}
.an .counts>.card{flex:1 1 0;min-width:180px;margin:0 6px 12px;display:flex;
flex-direction:column}
.an .counts>.card .big{margin-top:6px;font-size:26px;font-weight:650;line-height:1;
letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.an .counts>.card .smallnote{margin-top:auto;padding-top:8px}
@media print{.an .counts>.card{min-width:0}}
/* The body of the company page: a wide column and a 348px rail.
Both columns finish level without any card changing place. The rail is a flex item so it
already stretches to the height of the taller side; laying its own cards out as a spread
column means the extra height is shared between the gaps instead of pooling as dead space
at the foot. Nothing is moved and nothing is invented, and the two sides end together
whatever each company's data happens to contain. */
.an .grid{display:flex;align-items:stretch;margin-top:12px}
/* Both columns finish level, whichever of the two happens to be shorter.
The leftover height used to be pushed into the gaps between cards, which made the spacing
change from one pair of cards to the next and read as a fault rather than a layout. It now
goes into the cards themselves: every card grows by an equal share, so the gaps stay at a
constant 12px the whole way down and the extra height shows up as a little more room at the
foot of each card. Nothing is moved and nothing is invented to fill the space. */
.an .grid>div{display:flex;flex-direction:column}
.an .grid>div>.card{flex:1 1 auto}
/* The main column is the one that yields.
Its basis was auto, meaning the natural width of the widest table inside it, which on this
page is very wide. That made the total basis of the two columns exceed the row, and flex
resolves that by shrinking both in proportion to their basis. So every time the rail's basis
went up it was handed a larger share of the shrinking and came out the same or narrower,
which is why raising the number kept doing nothing. Basis 0 here, no shrink on the rail. */
.an .grid>div:first-child{flex:1 1 0;min-width:0}
/* The rail gives ground before it gives up.
It used to be a fixed 348px that stacked under the main column the moment the window fell
below 940px, and a preview opened in a narrow pane or a phone therefore showed the whole
page down one side. It now shrinks to 240px first and only stacks below 700px, where two
columns genuinely stop being readable. */
/* The rail is a share of the width rather than a fixed number of pixels, so a wider window
widens the rail instead of pushing everything into the main column and leaving the right of
the screen bare. The bounds stop it collapsing on a small laptop and stop it turning into a
second main column on a large monitor. */
.an .grid>div:last-child{flex:0 0 36%;min-width:300px;max-width:760px;margin-left:12px}
.an .grid>div>.card{margin-bottom:12px}
.an .grid>div>.card:last-child{margin-bottom:0}
@media(max-width:700px){.an .grid,.an .grid>div{display:block}
.an .grid>div:last-child{min-width:0;margin-left:0}
.an .grid>div>.card:last-child{margin-bottom:12px}}
@media print{.an .grid,.an .grid>div{display:block}
.an .grid>div:last-child{min-width:0;margin-left:0}
.an .grid>div>.card:last-child{margin-bottom:12px}}
@media(max-width:940px){.an .strip>div{flex-basis:33.33%;min-width:33.33%}}
@media(max-width:700px){.an .vcols>.vcol{flex-basis:100%;min-width:100%}}
@media(max-width:560px){.an .strip>div{flex-basis:50%;min-width:50%}}
.an .card{background:#fff;border:1px solid #d8dee9;border-radius:8px;
padding:20px 24px 22px;margin-bottom:12px}
/* Line length. The prose was capped at 110 characters, which on a wide screen left the
paragraph ending halfway across a card that was otherwise full width, and the card read as
half empty. The text now runs the full width of whatever card holds it, the same as the
tables and the bars above and below it. */
.an .card .sub,.an .read,.an .cnote,.an .smallnote,.an .view .lede,
.an .body-text{max-width:none}
/* The footer and the disclaimer are text blocks that also draw a rule or a border, so
capping the block itself would shorten the rule with it. The cap goes on the lines instead,
by way of the text indent that the wide reading measure needs anyway. */
.an .disc,.an .foot{text-wrap:pretty}
.an .disc>b:first-child,.an .foot>b:first-child{display:inline}
.an .card h2{margin:0 0 3px;font-size:13.5px;font-weight:700;letter-spacing:-.01em}
.an .card .sub{font-size:11.5px;font-weight:500;margin-bottom:16px;line-height:1.5}
.an .src{float:right;font-size:9.5px;font-weight:700;letter-spacing:.05em;
text-transform:uppercase;padding:2px 7px;border-radius:3px;background:#e8edf5;color:#1f3864}
.an .src.y{background:#f7f1de;color:#bf8f00}
/* In the rail there is rarely room for a source badge and a heading on one line, and a
floated badge wider than the space left pushed the heading into a ragged second line. Inside
the rail the badge sits on its own line above the heading instead. */
.an .grid>div:last-child .src{float:none;display:inline-block;margin-bottom:7px}
.an table{width:100%;border-collapse:collapse}
.an th,.an td{text-align:right;padding:9px 0;font-size:12.5px;
border-bottom:1px solid #e9edf3}
.an th{font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#1f3864}
.an th:first-child,.an td:first-child{text-align:left}
.an tr:last-child td{border-bottom:none}
.an td.lab{font-weight:500}
.an td.val{font-weight:700;font-variant-numeric:tabular-nums}
.an tfoot td{border-top:1.5px solid #1f3864;border-bottom:none;font-weight:700;padding-top:9px}
.an .brow{display:flex;align-items:center;gap:10px;margin:9px 0}
.an .brow .bl{width:132px;font-size:12px;font-weight:600;flex:none}
.an .brow .bt{flex:1;height:19px;background:#f4f7fb;border:1px solid #d8dee9;border-radius:3px;
position:relative;overflow:hidden}
.an .brow .bt i{position:absolute;left:0;top:0;bottom:0;background:#1f3864}
.an .brow .bt u{position:absolute;top:-1px;bottom:-1px;width:2px;background:#bf8f00;
text-decoration:none}
.an .brow .bv{width:88px;text-align:right;font-size:12px;font-weight:700;
font-variant-numeric:tabular-nums;flex:none}
.an .brow .bp{width:64px;text-align:right;font-size:11px;font-weight:600;color:#1f3864;flex:none}
/* mirrors the bar row below it column for column, or the headings sit over the wrong
things: 132px label, the flexible bar, 88px amount, 64px share */
.an .usehead{display:flex;align-items:flex-end;gap:10px;font-size:9.5px;font-weight:700;
letter-spacing:.06em;text-transform:uppercase;color:#1f3864;margin-bottom:6px;
padding-bottom:5px;border-bottom:1px solid #e9edf3}
.an .usehead .lab{width:132px;flex:none}
.an .usehead .spacer{flex:1}
.an .usehead .amt{width:88px;text-align:right;flex:none}
.an .usehead .shr{width:64px;text-align:right;flex:none;line-height:1.2}
.an .legend{margin-top:11px;font-size:10.5px;font-weight:500}
.an .legend i{display:inline-block;width:9px;height:9px;background:#1f3864;border-radius:2px;
margin-right:4px;vertical-align:-1px}
.an .legend u{display:inline-block;width:2px;height:11px;background:#bf8f00;margin:0 4px 0 12px;
vertical-align:-2px;text-decoration:none}
.an .read{margin-top:16px;padding:14px 16px;background:#f4f7fb;border:1px solid #d8dee9;
border-left:3px solid #1f3864;border-radius:5px;font-size:12.5px;font-weight:500;
line-height:1.6}
.an .read b{font-weight:700}
.an .cnote{margin-top:12px;padding-top:11px;border-top:1px solid #e9edf3;font-size:11.5px;
font-weight:500;line-height:1.55}
.an .cnote b{font-weight:700}
/* A standalone heading between blocks. The company page puts every heading inside a card,
but the landing page has Streamlit widgets between its sections and needs a rule of its
own to separate them. */
.an .sec{display:flex;align-items:baseline;gap:12px;margin:26px 0 10px}
.an .sec .t{font-size:12px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;
color:#1f3864;white-space:nowrap}
.an .sec .r{flex:1;height:1px;background:#d8dee9}
.an .sec .n{font-size:11px;font-weight:500;color:#1f3864;white-space:nowrap}
.an .smallnote{font-size:11.5px;font-weight:500;line-height:1.6;margin-top:10px}
.an .chart{width:100%;display:block;cursor:crosshair}

/* Chart axes.
The labels are HTML rather than SVG text, because the chart SVG is stretched with
preserveAspectRatio="none" and any text inside it stretches with it, which made the
numbers look like a different typeface from the page.
The plot reserves room on the right for the vertical scale so the labels sit beside the
chart instead of on top of it, and the horizontal row below is positioned by percentage
against the same width as the plot area. */
.an .plot{position:relative;padding-right:54px}
.an .yaxis{position:absolute;right:0;top:0;bottom:0;width:50px;pointer-events:none}
.an .yaxis span{position:absolute;right:0;font-size:10px;font-weight:600;color:#1f3864;
white-space:nowrap;line-height:1}
/* the outer two are anchored to the plot edges. Centring all three hung half of the top
label above the chart, where it was clipped. */
.an .yaxis .hi{top:1px}
.an .yaxis .mid{top:50%;transform:translateY(-50%)}
.an .yaxis .lo{bottom:1px}
.an .xaxis{position:relative;display:block;height:15px;margin:6px 54px 0 0;
font-size:10px;font-weight:600;color:#1f3864}
.an .xaxis span{position:absolute;top:0;white-space:nowrap}
.an .ddlabel{clear:both;font-size:10px;font-weight:700;letter-spacing:.07em;
text-transform:uppercase;color:#1f3864;margin:20px 0 8px;padding-top:16px;
border-top:1px solid #e9edf3}
/* Hover readout. A native SVG title waits on the browser's own delay and often never
fires, so the tooltip is drawn inside the SVG and revealed with CSS. No script is
involved, which matters because Streamlit strips script tags out of markdown. */
.an .hb .tip,.an .hb .xh,.an .hb .dot{opacity:0;transition:opacity .06s}
.an .hb .tip{pointer-events:none}
.an .hb:hover .tip,.an .hb:hover .xh,.an .hb:hover .dot{opacity:1}
.an .tabs{display:flex;gap:5px;margin-bottom:11px;flex-wrap:wrap}
.an .sbtn{border:1px solid #d8dee9;background:#fff;color:#1f3864;font-size:11px;
font-weight:700;padding:5px 11px;border-radius:4px;text-decoration:none;display:inline-block}
.an .sbtn:hover{border-color:#1f3864}
.an .sbtn.on{background:#1f3864;border-color:#1f3864;color:#fff}
/* Every row in the rail is the same two column grid, so the values line up down the
whole column instead of each card finding its own right edge. */
.an .kv{display:flex;justify-content:space-between;align-items:baseline;
padding:8px 0;font-size:12.5px;border-bottom:1px solid #e9edf3}
.an .kv:last-child{border-bottom:none}
.an .kv .k{font-weight:500;padding-right:12px}
.an .kv .v{flex:none;font-weight:700;font-variant-numeric:tabular-nums;text-align:right;
white-space:nowrap}
.an .kv .per{display:block;font-size:9.5px;font-weight:600;color:#1f3864;
letter-spacing:.05em;text-transform:uppercase;margin-top:2px}
.an .kv .band{display:block;font-size:9.5px;font-weight:600;color:#1f3864;margin-top:2px;
text-transform:lowercase;letter-spacing:0}
.an .holder{display:flex;justify-content:space-between;font-size:12px;
padding:7px 0;border-bottom:1px solid #e9edf3}
.an .holder:last-child{border-bottom:none}
.an .holder .n{font-weight:500;padding-right:12px}
.an .holder .p{flex:none;font-weight:700;font-variant-numeric:tabular-nums;text-align:right}
.an .news a{display:block;font-size:12.5px;font-weight:600;color:#1a1a1a;
text-decoration:none;padding:10px 0;border-bottom:1px solid #e9edf3;line-height:1.45}
.an .news a:last-child{border-bottom:none}
.an .news .m{font-size:10.5px;font-weight:600;color:#1f3864;margin-top:3px}
.an .body-text{font-size:12.5px;font-weight:500;line-height:1.6;margin-top:10px}
.an .view{background:#fff;border:1px solid #d8dee9;border-top:3px solid #1f3864;
border-radius:8px;padding:22px 24px 24px;margin-top:14px}
.an .view h2{margin:0;font-size:14px;font-weight:700}
.an .view .lede{font-size:13px;font-weight:500;line-height:1.65;margin:12px 0 0}
.an .view .lede b{font-weight:700}
.an .vcols{display:flex;flex-wrap:wrap;margin:22px -8px 0}
.an .vcols>.vcol{flex:1 1 0;min-width:210px;margin:0 8px 16px}
@media(max-width:940px){.an .vcols>.vcol{flex-basis:47%;min-width:47%}}
.an .vcol{border:1px solid #d8dee9;border-radius:6px;padding:15px 17px 17px;background:#f4f7fb}
.an .vcol.s{border-left:3px solid #12703a}
.an .vcol.c{border-left:3px solid #8a6300}
.an .vcol.v{border-left:3px solid #1f3864}
.an .vcol h3{margin:0 0 12px;font-size:10px;font-weight:700;letter-spacing:.08em;
text-transform:uppercase;padding-bottom:9px;border-bottom:1px solid #d8dee9}
.an .vcol ul{margin:0;padding-left:17px}
.an .vcol li{font-size:12px;font-weight:500;line-height:1.6;margin-bottom:10px}
.an .vcol li:last-child{margin-bottom:0}
.an .disc{margin-top:20px;padding-top:15px;border-top:1px solid #d8dee9;font-size:10.5px;
font-weight:500;line-height:1.6}
.an .disc b{font-weight:700}
.an .foot{margin-top:16px;padding:15px 18px;background:#fff;border:1px solid #d8dee9;
border-radius:8px;font-size:11px;font-weight:500;line-height:1.75}
.an .foot b{font-weight:700}
.an .printhead{display:none}
@media print{.an .printhead{display:flex !important;justify-content:space-between;
align-items:baseline;font-size:9.5px;font-weight:700;letter-spacing:.07em;
text-transform:uppercase;color:#1f3864;border-bottom:1px solid #1f3864;
padding-bottom:7px;margin-bottom:12px}}

/* Print to PDF. Cards must not be split across a page break, the grid collapses to one
column so nothing is cut off at the right margin, and colour is forced on because
browsers drop backgrounds by default. */
@media print{
@page{size:A4 portrait;margin:12mm 10mm}
body,.stApp,.an{background:#fff !important}
.an{max-width:none;font-size:10.5px}
.an .grid{grid-template-columns:1fr !important;gap:8px}
.an .strip{grid-template-columns:repeat(3,1fr)}
.an .card,.an .view,.an .foot,.an .mast,.an .strip{break-inside:avoid;
page-break-inside:avoid;box-shadow:none}
.an .card,.an .view,.an .foot,.an .mast{border:1px solid #bbb}
.an .mast h1{font-size:22px}
.an .quote .px{font-size:24px}
.an .tabs{display:none}
.an *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
.stApp header,section[data-testid="stSidebar"],div[data-testid="stExpander"],
.stDownloadButton,.stButton{display:none !important}
}
</style>
"""


def _assert_css_is_markdown_safe():
    """Markdown turns a line indented four spaces into a code block.

    Streamlit runs markdown over the string before it renders any HTML, so an indented CSS
    continuation line silently drops the rule it belongs to. The page then looks correct in a
    saved preview file, which never goes through markdown, and wrong inside the app. This
    catches that at import rather than on screen.
    """
    bad = [n for n, line in enumerate(CSS.split('\n'), 1)
           if line.startswith('    ') and line.strip()]
    if bad:
        raise AssertionError(
            f'CSS lines {bad[:6]} are indented four spaces or more. Markdown will turn them '
            f'into a code block and the rules will not reach the page.')


_assert_css_is_markdown_safe()


# ------------------------------------------------------------------ formatting ----------
def f(value, kind='num', dp=2):
    if value is None or (isinstance(value, float) and (pd.isna(value) or math.isinf(value))):
        return 'n/a'
    if kind == 'pct':
        # a portfolio weight of 0.14% must not print as 0.1%
        return f'{value:,.2f}%' if 0 < abs(value) < 1 else f'{value:,.1f}%'
    if kind == 'x':
        return f'{value:,.2f}x'
    if kind == 'money':
        for cut, suffix in ((1e12, 'T'), (1e9, 'B'), (1e6, 'M'), (1e3, 'K')):
            if abs(value) >= cut:
                return f'{value/cut:,.2f}{suffix}'
        return f'{value:,.0f}'
    if kind == 'int':
        return f'{value:,.0f}'
    return f'{value:,.{dp}f}'


def minus(text):
    """A real minus sign reads better than a hyphen in a column of numbers."""
    return str(text).replace('-', '\u2212')


def sentence(clauses):
    """Join clauses into one sentence.

    Any clause can be absent, because the feed does not always carry the field behind it.
    Each is written to read as a continuation, so the leading conjunction is stripped from
    all of them and put back only where it belongs. Joining blindly produced lines that
    opened with "And momentum is unremarkable".
    """
    parts = []
    for c in clauses:
        c = (c or '').strip().rstrip('.')
        for lead in ('and ', 'but ', 'with '):
            if c.lower().startswith(lead):
                c = c[len(lead):].lstrip()
                break
        if c:
            parts.append(c)
    if not parts:
        return ''
    parts[0] = parts[0][0].upper() + parts[0][1:]
    if len(parts) == 1:
        return parts[0] + '.'
    return ', '.join(parts[:-1]) + ', and ' + parts[-1] + '.'


def section(title, note_text=''):
    """A standalone heading, used by the landing page between Streamlit widgets."""
    return (f'<div class="an"><div class="sec"><span class="t">{title}</span>'
            f'<span class="r"></span><span class="n">{note_text}</span></div></div>')


def lede(text):
    """The paragraph under the landing masthead.

    Handed to Streamlit as plain markdown it came out in Streamlit's own font and sat
    outside the card system, which was the one place on the page where two typefaces were
    visible at once.
    """
    return f'<div class="an"><div class="body-text">{text}</div></div>'


def counts(items):
    """The four headline counts as one row.

    Takes (label, value, note) triples and returns a single block, because four separate
    Streamlit column writes are what put the boxes down one side.
    """
    cards = ''.join(
        f'<div class="card"><div class="eyebrow">{esc(label)}</div>'
        f'<div class="big">{esc(value)}</div>'
        f'<div class="smallnote">{esc(meta)}</div></div>'
        for label, value, meta in items)
    return f'<div class="an"><div class="counts">{cards}</div></div>'


def note(text):
    """A single line conclusion under a small card. Every box should answer, not just list."""
    return f'<div class="cnote">{text}</div>'


def read(text):
    """The sentence that says what a block of numbers means."""
    return f'<div class="read">{text}</div>'


def esc(text):
    return (str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            if text is not None else '')


# ------------------------------------------------------------------ charts --------------
def _points(values, width, height, pad_top=6, pad_bottom=6):
    """Map a series onto an SVG viewBox, oldest left."""
    clean = [v for v in values if v is not None and not pd.isna(v)]
    if len(clean) < 2:
        return '', None, None
    lo, hi = min(clean), max(clean)
    span = (hi - lo) or 1
    usable = height - pad_top - pad_bottom
    step = width / (len(values) - 1)
    pts = []
    for i, v in enumerate(values):
        if v is None or pd.isna(v):
            continue
        x = i * step
        y = pad_top + (hi - v) / span * usable
        pts.append(f'{x:.1f},{y:.1f}')
    return ' '.join(pts), lo, hi


def svg_price(close, ma50, ma200, width=720, height=250):
    """Close with its two moving averages, and a hover readout at every point.

    Streamlit strips script tags out of markdown, so the hover is built from SVG title
    elements on a row of invisible bands. The browser draws the tooltip itself, which is
    slower to appear than a charting library but cannot be stripped out.
    """
    values = list(close)
    body, lo, hi = _points(values, width, height)
    if not body:
        return '<div class="sub">Not enough price history to draw a chart.</div>'
    span = (hi - lo) or 1
    usable = height - 12
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" '
             f'preserveAspectRatio="none" style="height:{height}px;cursor:crosshair">']
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = 6 + frac * usable
        parts.append(f'<line x1="0" y1="{y:.0f}" x2="{width}" y2="{y:.0f}" stroke="#e9edf3"/>')

    def overlay(series, colour, dash=''):
        if series is None:
            return
        vals = list(series)
        step = width / max(1, len(vals) - 1)
        pts = [f'{i*step:.1f},{6 + (hi - v)/span*usable:.1f}'
               for i, v in enumerate(vals) if v is not None and not pd.isna(v)]
        if len(pts) > 1:
            d = f' stroke-dasharray="{dash}"' if dash else ''
            parts.append(f'<polyline fill="none" stroke="{colour}" stroke-width="1.3"'
                         f'{d} points="{" ".join(pts)}"/>')

    overlay(ma50, '#8fa3bf')
    overlay(ma200, '#b9c4d4', '4,3')
    parts.append(f'<polyline fill="none" stroke="{NAVY}" stroke-width="2" points="{body}"/>')

    idx = list(close.index)
    bands = max(1, min(len(values), int(width // HOVER_BAND_UNITS)))
    if bands > 1:
        bw = width / bands
        ma50_list = list(ma50) if ma50 is not None else []
        ma200_list = list(ma200) if ma200 is not None else []
        for b in range(bands):
            i = min(len(values) - 1, int((b + 0.5) * len(values) / bands))
            v = values[i]
            if v is None or pd.isna(v):
                continue
            when = idx[i]
            label = when.strftime('%d %b %Y') if hasattr(when, 'strftime') else str(when)
            lines = [label, f'Close {v:,.2f}']
            if i < len(ma50_list) and ma50_list[i] is not None and not pd.isna(ma50_list[i]):
                lines.append(f'50 day {ma50_list[i]:,.2f}')
            if i < len(ma200_list) and ma200_list[i] is not None and not pd.isna(ma200_list[i]):
                lines.append(f'200 day {ma200_list[i]:,.2f}')
            cx = b * bw + bw / 2
            cy = 6 + (hi - v) / span * usable
            # the box flips to the left near the right edge so it never runs off the chart
            box_w, box_h = 150, 16 + 13 * len(lines)
            bx = round(cx + 10 if cx < width - box_w - 14 else cx - box_w - 10, 1)
            by = round(min(max(4, cy - box_h / 2), height - box_h - 4), 1)
            text = ''.join(
                f'<text x="{bx + 9}" y="{by + 18 + 13 * k}" font-size="10.5" '
                f'font-weight="{700 if k == 0 else 500}" fill="#1a1a1a">{esc(t)}</text>'
                for k, t in enumerate(lines))
            parts.append(
                f'<g class="hb">'
                f'<rect x="{b*bw:.2f}" y="0" width="{bw:.2f}" height="{height}" '
                f'fill="transparent"/>'
                f'<line class="xh" x1="{cx:.1f}" y1="0" x2="{cx:.1f}" y2="{height}" '
                f'stroke="#bf8f00" stroke-width="1" stroke-dasharray="3,3"/>'
                f'<circle class="dot" cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" fill="#1f3864" '
                f'stroke="#fff" stroke-width="1.5"/>'
                f'<g class="tip"><rect x="{bx}" y="{by}" width="{box_w}" height="{box_h}" '
                f'rx="4" fill="#ffffff" stroke="#1f3864" stroke-width="1"/>{text}</g></g>')
    parts.append('</svg>')
    return ''.join(parts)


def svg_drawdown(close, width=720, height=88):
    """Fall from the running peak, with the same hover readout as the price chart.

    This is the line that says what holding the thing actually felt like, which no single
    performance figure can.
    """
    series = pd.Series(list(close), index=list(close.index)).dropna()
    if len(series) < 3:
        return ''
    dd = ((series / series.cummax()) - 1) * 100
    worst = float(dd.min()) or -1
    step = width / max(1, len(dd) - 1)
    pts = [f'{i*step:.1f},{4 + (v / worst) * (height - 12):.1f}' for i, v in enumerate(dd)]
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
             f'style="height:{height}px;cursor:crosshair">',
             f'<line x1="0" y1="4" x2="{width}" y2="4" stroke="#d8dee9"/>',
             f'<polyline fill="none" stroke="{DOWN}" stroke-width="1.5" '
             f'points="{" ".join(pts)}"/>']
    vals, idx = list(dd), list(dd.index)
    bands = max(1, min(len(vals), int(width // HOVER_BAND_UNITS)))
    if bands > 1:
        bw = width / bands
        for b in range(bands):
            i = min(len(vals) - 1, int((b + 0.5) * len(vals) / bands))
            when = idx[i]
            label = when.strftime('%d %b %Y') if hasattr(when, 'strftime') else str(when)
            cx = b * bw + bw / 2
            cy = 4 + (vals[i] / worst) * (height - 12)
            lines = [label, f'{vals[i]:,.1f}% below its peak']
            box_w, box_h = 158, 42
            bx = round(cx + 10 if cx < width - box_w - 14 else cx - box_w - 10, 1)
            by = 4 if cy > height / 2 else height - box_h - 4
            text = ''.join(
                f'<text x="{bx + 9}" y="{by + 17 + 13 * k}" font-size="10.5" '
                f'font-weight="{700 if k == 0 else 500}" fill="#1a1a1a">{esc(t)}</text>'
                for k, t in enumerate(lines))
            parts.append(
                f'<g class="hb">'
                f'<rect x="{b*bw:.2f}" y="0" width="{bw:.2f}" height="{height}" '
                f'fill="transparent"/>'
                f'<line class="xh" x1="{cx:.1f}" y1="0" x2="{cx:.1f}" y2="{height}" '
                f'stroke="#bf8f00" stroke-width="1" stroke-dasharray="3,3"/>'
                f'<circle class="dot" cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="{DOWN}" '
                f'stroke="#fff" stroke-width="1.5"/>'
                f'<g class="tip"><rect x="{bx}" y="{by}" width="{box_w}" height="{box_h}" '
                f'rx="4" fill="#ffffff" stroke="{DOWN}" stroke-width="1"/>{text}</g></g>')
    parts.append('</svg>')
    return ''.join(parts)


def chart_frame(close, span_label, price_svg, dd_svg):
    """Wrap both charts with axes that are HTML rather than SVG text.

    The vertical scale sits against the plot on the right, aligned to the gridlines, and the
    dates run underneath. Both inherit the page typeface, which SVG text inside a stretched
    viewBox cannot do.
    """
    vals = [v for v in list(close) if v is not None and not pd.isna(v)]
    if len(vals) < 2:
        return price_svg
    hi, lo = max(vals), min(vals)
    mid = (hi + lo) / 2
    n = len(close)
    idx = list(close.index)

    fmt = '%d %b %y' if span_label in ('3M', '6M') else '%b %Y'
    if span_label in ('10Y', 'Max') and n > 2000:
        fmt = '%Y'
    ticks = 6
    dates = []
    for t in range(ticks):
        i = int(round(t * (n - 1) / (ticks - 1)))
        when = idx[i]
        label = when.strftime(fmt) if hasattr(when, 'strftime') else str(when)
        pct = t / (ticks - 1) * 100
        align = ('left:0;text-align:left' if t == 0 else
                 'right:0;text-align:right' if t == ticks - 1 else
                 f'left:{pct:.2f}%;transform:translateX(-50%)')
        dates.append(f'<span style="position:absolute;{align}">{label}</span>')
    date_row = f'<div class="xaxis">{"".join(dates)}</div>'

    # The gridlines inside the chart are drawn at y = 6 and y = height - 6, not at the very
    # edges, so the labels have to match those positions or they float off the lines. The
    # outer two are anchored rather than centred, because a centred label at the top hangs
    # half of itself above the plot and gets clipped.
    yaxis = (f'<span class="hi">{f(hi)}</span>'
             f'<span class="mid">{f(mid)}</span>'
             f'<span class="lo">{f(lo)}</span>')

    dd_vals = ((pd.Series(vals) / pd.Series(vals).cummax()) - 1) * 100
    worst = float(dd_vals.min())
    dd_axis = (f'<span class="hi">0%</span>'
               f'<span class="lo">{worst:,.0f}%</span>')

    return (f'<div class="plot"><div class="yaxis">{yaxis}</div>{price_svg}</div>'
            f'{date_row}'
            f'<div class="ddlabel">Fall from the running peak, same period</div>'
            f'<div class="plot dd"><div class="yaxis">{dd_axis}</div>{dd_svg}</div>'
            f'{date_row}')


# Labels and formatting for every ratio the feed carries. These live here rather than in the
# app module because this file is the one that renders them.
LABELS = {
    'pe': 'P/E', 'fpe': 'P/E forward', 'roic': 'ROIC', 'roce': 'ROCE', 'roa': 'ROA',
    'roe': 'ROE', 'gross_margin': 'Gross margin', 'op_margin': 'Operating margin',
    'net_margin': 'Net margin', 'fcf_margin': 'FCF margin',
    'current_ratio': 'Current ratio', 'debt_equity': 'Debt / equity',
    'interest_cover': 'Interest coverage', 'ebitda_cover': 'EBITDA coverage',
    'altman_z': 'Altman Z', 'piotroski_f': 'Piotroski F',
}
PERCENT_METRICS = {'roic', 'roce', 'roa', 'roe', 'gross_margin', 'op_margin',
                   'net_margin', 'fcf_margin'}


# ------------------------------------------------------------------ peer bars -----------
PEER_ROWS = [('pe', 'P/E', 'x', False), ('roe', 'Return on equity', 'pct', True),
             ('op_margin', 'Operating margin', 'pct', True),
             ('net_margin', 'Net margin', 'pct', True),
             ('interest_cover', 'Interest cover', 'x', True),
             ('debt_equity', 'Debt / equity', 'x', False)]

# The sector median is drawn at the same point on every row. Scaling each row to its own
# maximum put the gold marker somewhere different each time, which made the column
# impossible to scan, and one extreme value such as an interest cover of 708x against a
# median of 4.4x pushed the marker to zero and wasted the whole row. With the median fixed,
# a bar past the marker beats its sector and the column reads in a single pass.
MEDIAN_AT = 34.0


def peer_bars(tv, stats):
    """One row per ratio: navy bar for the company, gold line for the sector median."""
    rows = []
    for key, label, kind, _higher in PEER_ROWS:
        val = tv.get(key)
        block = (stats or {}).get(key)
        if val is None or not block or not block.get('median'):
            continue
        med = block['median']
        if med == 0:
            continue
        ratio = abs(val) / abs(med)
        wid = min(100.0, ratio * MEDIAN_AT)
        capped = ratio * MEDIAN_AT > 100
        tip = (f'{label}: {minus(f(val, kind))} against a sector median of '
               f'{minus(f(med, kind))}, {ratio:,.1f} times the median')
        cap = ('<span style="position:absolute;right:4px;top:3px;font-size:9px;'
               'font-weight:700;color:#fff">&#9656;</span>' if capped else '')
        rows.append(
            f'<div class="brow" title="{esc(tip)}"><div class="bl">{label}</div>'
            f'<div class="bt"><i style="width:{wid:.1f}%"></i>'
            f'<u style="left:{MEDIAN_AT:.0f}%"></u>{cap}</div>'
            f'<div class="bv num">{minus(f(val, kind))}</div>'
            f'<div class="bp num">{minus(f(med, kind))}</div></div>')
    return ''.join(rows)

def peer_summary(tv, stats):
    """How many of the compared ratios sit in the better half of the sector."""
    better = total = 0
    for key, _label, _kind, higher in PEER_ROWS:
        val, block = tv.get(key), (stats or {}).get(key)
        if val is None or not block:
            continue
        total += 1
        med = block['median']
        if (val > med) if higher else (val < med):
            better += 1
    return better, total


# ------------------------------------------------------------------ the page ------------
def span_links(spans, current, base_query):
    """Range buttons as links rather than a widget, so they sit inside the chart card.

    A Streamlit radio can only render where Streamlit puts it, which was above the whole
    page. These carry the existing query string plus a span, so a click reloads in place.
    """
    out = []
    for label in spans:
        cls = 'sbtn on' if label == current else 'sbtn'
        out.append(f'<a class="{cls}" href="?{base_query}span={label}" '
                   f'target="_self">{label}</a>')
    return f'<div class="tabs">{"".join(out)}</div>'


def build(tv, isin, yf_data, stats, forensics, resolution, risk, dupont_rows, qoe_rows,
          qoe_verdict, capital, per_share, span_label, close, ma50, ma200, lede='',
          spans=None, base_query='', percentile_of=None):
    """Assemble the whole page. Every argument is already computed; this only lays out."""
    info = (yf_data or {}).get('info') or {}
    ccy = tv.get('ccy') or info.get('currency') or ''
    price = tv.get('price') or info.get('currentPrice')
    ytd = tv.get('perf_ytd')
    tv_date = tv.get('_as_of', '')
    gics = tv.get('gics')
    # what period each TradingView field covers, published alongside the feed. Without this
    # a trailing twelve month return can sit next to an annual margin with nothing to say so.
    periods = tv.get('_periods') or {}

    def tvp(key):
        return periods.get(key)

    H = [CSS, '<div class="an">']
    # printed at the top of every page of the PDF. The browser adds its own header with a
    # date and a file path, which the print dialog controls rather than the page, so this
    # gives the document a proper identification of its own.
    # A running header for the printed page only. The company and the ticker are in the
    # masthead immediately below, so repeating them here would just be noise. This carries
    # the two things a printed page needs and the screen does not: whose research it is and
    # what date the data is as at.
    H.append(f'<div class="printhead"><span>MICS International, internal research</span>'
             f'<span>Data as at {esc(tv.get("_as_of", ""))}</span></div>')
    # ---------- masthead ----------
    bits = [x for x in [tv.get('ticker'), gics, info.get('industry'), tv.get('country'),
                        isin, (resolution or {}).get('exchange')] if x]
    meta = '<span class="sep">/</span>'.join(
        (f'<b>{esc(b)}</b>' if i == 0 else esc(b)) for i, b in enumerate(bits))
    lo52, hi52 = info.get('fiftyTwoWeekLow'), info.get('fiftyTwoWeekHigh')
    rng = ''
    if lo52 and hi52 and hi52 > lo52 and price:
        pos = max(0, min(100, (price - lo52) / (hi52 - lo52) * 100))
        rng = (f'<div class="rng">52 week range {f(lo52)} to {f(hi52)}, at {pos:.0f}%</div>'
               f'<div class="bar52"><i style="left:{pos:.0f}%"></i></div>')
    cls = 'up' if (ytd or 0) > 0 else ('down' if (ytd or 0) < 0 else '')
    arrow = '&#9650;' if (ytd or 0) > 0 else ('&#9660;' if (ytd or 0) < 0 else '')
    H.append(
        f'<div class="mast"><div><div class="eyebrow">Equity analysis, {esc(tv_date)}</div>'
        f'<h1>{esc(tv.get("name") or tv.get("ticker") or "")}</h1>'
        f'<div class="meta">{meta}</div></div>'
        f'<div class="quote"><div class="eyebrow"><a class="back" href="?">'
        f'Back to search</a></div>'
        f'<div class="eyebrow" style="margin-top:6px">Last price</div>'
        f'<div class="px num">{f(price)}<span>{esc(ccy)}</span></div>'
        f'<div class="chg {cls} num">{arrow} {minus(f(ytd, "pct"))} year to date</div>'
        f'{rng}</div></div>')

    # ---------- the business ----------
    summary = info.get('longBusinessSummary')
    if summary:
        extra = ', '.join(str(x) for x in [
            info.get('sector'), info.get('industry'),
            f'{info["fullTimeEmployees"]:,} employees' if info.get('fullTimeEmployees') else None
        ] if x)
        H.append(f'<div class="card" style="margin-top:12px;margin-bottom:0">'
                 f'<span class="src y">Yahoo</span><h2>The business</h2>'
                 f'<div class="body-text">{esc(summary)}</div>'
                 + (f'<div class="sub" style="margin:10px 0 0">{esc(extra)}</div>'
                    if extra else '') + '</div>')

    # ---------- verdict strip ----------
    def cell(k, v, pill, pill_cls, note):
        p = f'<span class="pill {pill_cls}">{pill}</span>' if pill else ''
        return (f'<div><div class="k">{k}</div><div class="v num">{v}</div>'
                f'<div class="n">{p}{note}</div></div>')

    cells = []
    if gics in ('Financials', 'Real Estate'):
        cells.append(cell('Altman Z', 'n/a', 'n/a', 'n', 'model does not fit this balance sheet'))
    else:
        z = tv.get('altman_z')
        if z is None:
            cells.append(cell('Altman Z', 'n/a', '', '', 'not reported'))
        else:
            band, c = (('Distress', 'r') if z < 1.8 else
                       ('Grey zone', 'a') if z < 3 else ('Safe', 'g'))
            cells.append(cell('Altman Z', f(z), band, c, 'TradingView, TTM'))
    pf = tv.get('piotroski_f')
    if pf is None:
        cells.append(cell('Piotroski F', 'n/a', '', '', 'not reported'))
    else:
        band, c = (('Strong', 'g') if pf >= 7 else ('Middling', 'a') if pf >= 4
                   else ('Weak', 'r'))
        cells.append(cell('Piotroski F', f'{pf:,.0f}<small> / 9</small>', band, c,
                          'TradingView, TTM'))

    bm = (forensics or {}).get('beneish') or {}
    if bm.get('score') is None:
        cells.append(cell('Beneish M', 'n/a', '', '', 'inputs incomplete'))
    else:
        v = bm['score']
        cov = f", {bm['coverage']:.0f}% inputs" if bm.get('coverage') else ''
        cells.append(cell('Beneish M', minus(f(v)),
                          'Flagged' if v > -1.78 else 'Clean',
                          'r' if v > -1.78 else 'g', f'flag above {minus("-1.78")}{cov}'))
    oh = (forensics or {}).get('ohlson') or {}
    if oh.get('score') is None:
        cells.append(cell('Distress prob.', 'n/a', '', '', 'not computed'))
    else:
        prob = oh['score'] * 100 if oh.get('as_pct') else oh['score']
        band, c = (('High', 'r') if prob > 10 else ('Watch', 'a') if prob > 5
                   else ('Low', 'g'))
        cells.append(cell('Distress prob.', f(prob, 'pct'), band, c, 'Ohlson O, Yahoo'))
    sl = (forensics or {}).get('sloan') or {}
    if sl.get('score') is None:
        cells.append(cell('Accruals', 'n/a', '', '', 'not computed'))
    else:
        pct = sl['score'] * 100
        band, c = (('Profit ahead', 'r') if pct > 5 else ('Cash ahead', 'g') if pct < -5
                   else ('Neutral', 'n'))
        cells.append(cell('Accruals', minus(f(pct, 'pct')), band, c, 'Sloan, Yahoo'))
    usable = [r['cfo_to_ni'] for r in (qoe_rows or []) if r.get('cfo_to_ni') is not None]
    if usable:
        avg = sum(usable) / len(usable)
        band, c = (('Backed', 'g') if avg >= 1.1 else ('In line', 'n') if avg >= 0.9
                   else ('Thin', 'r'))
        cells.append(cell('Cash conversion', f(avg, 'x'), band, c,
                          f'{len(usable)} year CFO / profit'))
    else:
        cells.append(cell('Cash conversion', 'n/a', '', '', 'no cash flow statement'))
    H.append(f'<div class="strip">{"".join(cells)}</div>')

    # ---------- two column grid ----------
    # Cards are collected rather than written straight out, so their heights can be measured
    # and the two columns balanced before anything is emitted.
    LEFT, RAIL = [], []

    def left(html):
        LEFT.append(html)

    def rail(html):
        RAIL.append(html)


    # sector comparison
    bars = peer_bars(tv, stats)
    if bars:
        better, total = peer_summary(tv, stats)
        n = (stats or {}).get('pe', {}).get('n') or (stats or {}).get('roe', {}).get('n')
        left(
            f'<div class="card"><span class="src">TradingView, {esc(tv_date)}</span>'
            f'<h2>Against its sector</h2>'
            f'<div class="sub">Navy bar is the company, gold line is the {esc(gics or "sector")} '
            f'median. The median is taken across every company in the sector'
            + (f', {n:,} of them' if n else '') +
            ', not only those that cleared a screen, because a median of the winners would '
            'make everything look average.</div>'
            f'{bars}<div class="legend"><i></i>company<u></u>sector median</div>'
            + (read(
                (f'<b>Better than its sector on every measure compared.</b> ' if better == total
                 else f'<b>Better than its sector on most of what is compared</b>, '
                      f'{better} of {total}. ' if better > total / 2
                 else f'<b>Behind its sector on most of what is compared</b>, only '
                      f'{better} of {total}. ')
                + ('The question that raises is durability rather than quality.'
                   if better > total / 2
                   else 'Whatever the case for owning it, these ratios are not it.'))
               if total else '') +
            '</div>')

    # price and drawdown
    if close is not None and len(close) > 5:
        first, last = close.index[0], close.index[-1]
        start_txt = first.strftime('%B %Y') if hasattr(first, 'strftime') else str(first)
        window = close
        change = (float(window.iloc[-1] / window.iloc[0] - 1) * 100
                  if float(window.iloc[0]) else None)
        full_dd = risk.get('max_drawdown_pct')
        rows = [
            ('Window high and low', f'{f(float(window.max()))} / {f(float(window.min()))}',
             'Change over the window', minus(f(change, 'pct'))),
            ('Deepest fall, full history', minus(f(full_dd, 'pct')),
             'Volatility, annualised', f(risk.get('vol_1y_pct'), 'pct')),
            ('Against the 200 day average', minus(f(risk.get('pct_vs_200dma'), 'pct')),
             'Beta, 2 year and 5 year',
             f'{f(risk.get("beta_2y"))} / {f(risk.get("beta_5y"))}'),
        ]
        table = ''.join(
            f'<tr><td class="lab">{a}</td><td class="val num">{b}</td>'
            f'<td class="lab">{c}</td><td class="val num">{d}</td></tr>'
            for a, b, c, d in rows)
        tail = ''
        if full_dd is not None and full_dd < -50:
            tail = read(f'<b>This has fallen further than most holders would sit through.</b> '
                        f'A company can read well on every current ratio and still have put '
                        f'its owners through a decline like that, which is why the full '
                        f'record is shown here rather than the last two years.')
        left(
            f'<div class="card"><span class="src y">Yahoo, daily</span>'
            f'<h2>Price and drawdown</h2>'
            f'<div class="sub">History available from {esc(start_txt)}. Navy is the close, '
            f'the two lighter lines are the 50 and 200 day averages. The lower panel is the '
            f'fall from each running peak. Hover anywhere on either chart for the date and '
            f'the level.</div>'
            + (span_links(spans, span_label, base_query) if spans else '')
            + chart_frame(close, span_label, svg_price(close, ma50, ma200),
                          svg_drawdown(close))
            + f'<table style="margin-top:16px">{table}</table>{tail}</div>')

    # DuPont
    if dupont_rows:
        body = ''.join(
            f'<tr><td>{esc(r["period"])}</td>'
            f'<td class="val num">{minus(f(r["net_margin_pct"], "pct"))}</td>'
            f'<td class="val num">{f(r["asset_turnover"])}</td>'
            f'<td class="val num">{f(r["equity_multiplier"])}</td>'
            f'<td class="val num">{minus(f(r["roe_pct"], "pct"))}</td></tr>'
            for r in dupont_rows)
        last = dupont_rows[-1]
        driver = ('operating margin' if last['net_margin_pct'] >= 10 else
                  'asset turnover' if last['asset_turnover'] >= 1 else
                  'balance sheet leverage')
        direction = ''
        if len(dupont_rows) > 1:
            firstr = dupont_rows[0]
            d_margin = last['net_margin_pct'] - firstr['net_margin_pct']
            d_lev = last['equity_multiplier'] - firstr['equity_multiplier']
            if abs(d_margin) > 2 and abs(d_lev) < 0.3:
                direction = (' The improvement came from the business rather than the '
                             'balance sheet, which is the version worth having.'
                             if d_margin > 0 else
                             ' Margin has gone backwards while the balance sheet held still, '
                             'so the pressure is operational.')
            elif d_lev > 0.5:
                direction = (' Leverage has risen over the period, so part of the return is '
                             'borrowed rather than earned.')
        left(
            f'<div class="card"><span class="src y">Yahoo, annual</span>'
            f'<h2>What drives the return on equity</h2>'
            f'<div class="sub">DuPont decomposition. The same return can come from margin, '
            f'from turnover or from leverage, and those are not the same business.</div>'
            f'<table><thead><tr><th>Year</th><th>Net margin</th><th>Asset turnover</th>'
            f'<th>Equity multiplier</th><th>ROE</th></tr></thead><tbody>{body}</tbody></table>'
            + read(f'The return is driven mainly by <b>{driver}</b>.{direction} A return '
                   f'earned on leverage is a different proposition from the same return '
                   f'earned on margin, and the headline figure cannot tell them '
                   f'apart.') + '</div>')

    # cash conversion and capital allocation
    if qoe_rows and any(r.get('cfo_to_ni') is not None for r in qoe_rows):
        body = ''.join(
            f'<tr><td>{esc(r["period"])}</td>'
            f'<td class="val num">{minus(f(r["net_income"], "money"))}</td>'
            f'<td class="val num">{minus(f(r["cfo"], "money"))}</td>'
            f'<td class="val num">{f(r["cfo_to_ni"], "x")}</td></tr>' for r in qoe_rows)
        tot_ni = sum(r['net_income'] for r in qoe_rows if r.get('net_income') is not None)
        tot_cfo = sum(r['cfo'] for r in qoe_rows if r.get('cfo') is not None)
        foot = (f'<tfoot><tr><td>Cumulative</td>'
                f'<td class="num">{minus(f(tot_ni, "money"))}</td>'
                f'<td class="num">{minus(f(tot_cfo, "money"))}</td>'
                f'<td class="num">{f(tot_cfo/tot_ni, "x") if tot_ni else "n/a"}</td>'
                f'</tr></tfoot>')
        uses = ''
        if capital and capital.get('uses'):
            top = max(u['amount'] for u in capital['uses'])
            cum = capital.get('cumulative_cfo')
            uses = ''.join(
                f'<div class="brow" title="{esc(u["use"])}: {f(u["amount"], "money")}, which is '
                f'{f(u["pct_of_cfo"], "pct")} of the {f(cum, "money")} of operating cash flow '
                f'generated across these years"><div class="bl">{esc(u["use"])}</div>'
                f'<div class="bt"><i style="width:{u["amount"]/top*100:.0f}%"></i></div>'
                f'<div class="bv num">{f(u["amount"], "money")}</div>'
                f'<div class="bp num">{f(u["pct_of_cfo"], "pct")}</div></div>'
                for u in capital['uses'])
            head = ('<div class="usehead"><span class="lab">Use of cash</span>'
                    '<span class="spacer"></span>'
                    '<span class="amt">Amount</span>'
                    '<span class="shr">Share of<br>cash flow</span></div>')
            uses = (f'<div style="margin-top:18px;padding-top:16px;'
                    f'border-top:1px solid #d8dee9">{head}{uses}</div>')
        left(
            f'<div class="card"><span class="src y">Yahoo, annual</span>'
            f'<h2>Does the profit arrive as cash, and where does it go</h2>'
            f'<div class="sub">Reported profit against operating cash flow, then what that '
            f'cash was spent on. In the lower block, the percentage is that use of cash as a '
            f'share of the cumulative operating cash flow in the row above, so it answers '
            f'how much of the cash the business generated went to each place.</div>'
            f'<table><thead><tr><th>Year</th><th>Net income</th><th>Operating cash flow</th>'
            f'<th>CFO / profit</th></tr></thead><tbody>{body}</tbody>{foot}</table>{uses}'
            + (read(qoe_verdict) if qoe_verdict else '') + '</div>')

    # per share growth
    if per_share and per_share.get('revenue_cagr_pct') is not None:
        ps = per_share
        gap = None
        if ps.get('revenue_per_share_cagr_pct') is not None:
            gap = ps['revenue_cagr_pct'] - ps['revenue_per_share_cagr_pct']
        body = (
            f'<tr><td class="lab">Revenue</td>'
            f'<td class="val num">{minus(f(ps["revenue_cagr_pct"], "pct"))}</td>'
            f'<td class="val num">{minus(f(ps.get("revenue_per_share_cagr_pct"), "pct"))}</td>'
            f'<td class="val num">{minus(f(gap, "pct")) if gap is not None else "n/a"}</td></tr>'
            f'<tr><td class="lab">Net income</td>'
            f'<td class="val num">{minus(f(ps.get("net_income_cagr_pct"), "pct"))}</td>'
            f'<td class="val num">{minus(f(ps.get("eps_cagr_pct"), "pct"))}</td>'
            f'<td class="val">per share</td></tr>'
            f'<tr><td class="lab">Share count</td>'
            f'<td class="val num">{minus(f(ps.get("share_count_cagr_pct"), "pct"))}</td>'
            f'<td class="val" colspan="2">'
            f'{"buying back" if (ps.get("share_count_cagr_pct") or 0) < 0 else "issuing"}'
            f'</td></tr>')
        tail = ''
        if gap is not None and gap > 1:
            tail = read(f'Revenue grew <b>{f(gap, "pct")} a year faster</b> than revenue per '
                        f'share. That gap is dilution, and a holder did not receive it.')
        elif gap is not None and gap < -1:
            tail = read(f'Revenue per share grew <b>{f(abs(gap), "pct")} a year faster</b> '
                        f'than revenue, because the share count fell. Buybacks are doing '
                        f'part of the work.')
        left(
            f'<div class="card"><span class="src y">Yahoo, per share</span>'
            f'<h2>Growth the holder actually received</h2>'
            f'<div class="sub">Absolute growth against per share growth, {ps.get("years")} '
            f'years, {esc(ps.get("from"))} to {esc(ps.get("to"))}. The gap between them is '
            f'dilution, and a holder does not receive it.</div>'
            f'<table><thead><tr><th>CAGR</th><th>Absolute</th><th>Per share</th><th>Gap</th>'
            f'</tr></thead><tbody>{body}</tbody></table>{tail}</div>')

    # ---------- right rail ----------
    # The two columns are emitted together at the end, so nothing here writes raw div tags.
    # A leftover marker from before that change was landing in the left column as an empty
    # div, which gave the grid a third child. Three children in a two column grid pushes the
    # third onto its own row, which is why the rail was appearing underneath.

    # ---- the ratios that appear nowhere else. P/E, ROE, both margins, interest cover and
    #      debt to equity are in the sector bars, and Altman and Piotroski are in the strip
    #      at the top, so listing them again would be the third time a reader saw them.
    ALREADY_SHOWN = {'pe', 'roe', 'op_margin', 'net_margin', 'interest_cover',
                     'debt_equity', 'altman_z', 'piotroski_f'}
    ratio_rows = ''
    for key, label in LABELS.items():
        if key in ALREADY_SHOWN:
            continue
        v = tv.get(key)
        if v is None:
            continue
        kind = ('pct' if key in PERCENT_METRICS else
                'x' if key in ('fpe', 'current_ratio', 'ebitda_cover') else 'num')
        peer = percentile_of(v, stats, key) if percentile_of else None
        band = f'<span class="band">{peer["band"]}</span>' if peer else ''
        ratio_rows += (f'<div class="kv"><span class="k">{label}'
                       f'<span class="per">{tvp(key) or ""}</span></span>'
                       f'<span class="v num">{minus(f(v, kind))}{band}</span></div>')
    if ratio_rows:
        rail(f'<div class="card"><span class="src">TradingView, {esc(tv_date)}</span>'
                 f'<h2>The rest of the ratios</h2>'
                 f'<div class="sub">Everything the feed carries that is not already above, '
                 f'with the period each covers</div>{ratio_rows}</div>')

    val_rows = [('enterpriseToEbitda', 'EV / EBITDA', 'x'),
                ('priceToBook', 'Price / book', 'x'),
                ('priceToSalesTrailing12Months', 'Price / sales', 'x'),
                ('enterpriseToRevenue', 'EV / revenue', 'x'),
                ('trailingPegRatio', 'PEG', 'x')]
    kv = ''.join(f'<div class="kv"><span class="k">{lbl}</span>'
                 f'<span class="v num">{f(info.get(k), kind)}</span></div>'
                 for k, lbl, kind in val_rows if info.get(k) is not None)
    dy = info.get('dividendYield')
    if dy is not None:
        dy = dy * 100 if dy < 1 else dy
        kv += (f'<div class="kv"><span class="k">Dividend yield</span>'
               f'<span class="v num">{f(dy, "pct")}</span></div>')
    if kv:
        # A conclusion has to say what the numbers mean, not read them back. The figures are
        # in the rows immediately above, so repeating them here would waste the line.
        pe, med_pe = tv.get('pe'), stats.get('pe', {}).get('median')
        ev, pb = info.get('enterpriseToEbitda'), info.get('priceToBook')
        verdict = []
        if pe is not None and med_pe:
            ratio = pe / med_pe
            verdict.append(
                'Materially cheaper than its sector on earnings' if ratio < 0.7 else
                'Cheaper than its sector on earnings' if ratio < 0.95 else
                'Priced in line with its sector' if ratio <= 1.15 else
                'Dearer than its sector on earnings' if ratio < 1.6 else
                'Priced well above its sector on earnings')
        if ev is not None:
            verdict.append('and the cash flow multiple is undemanding' if ev < 10 else
                           'and the cash flow multiple is reasonable' if ev < 15 else
                           'and the cash flow multiple leaves little room for '
                           'disappointment')
        if pb is not None and pb > 5:
            verdict.append('most of the value sits in the earnings rather than the assets, '
                           'so the multiple depends on those earnings holding')
        concl = note(sentence(verdict)) if verdict else ''
        rail(f'<div class="card"><span class="src y">Yahoo</span><h2>Valuation</h2>'
                 f'<div class="sub">Multiples TradingView does not export</div>{kv}'
                 f'{concl}</div>')

    # ---- returns. The feed carries four horizons and the page was showing one of them.
    perf = [('perf_ytd', 'Year to date'), ('perf_6m', 'Six months'),
            ('perf_1y', 'One year'), ('perf_5y', 'Five years, cumulative')]
    rows = ''
    for key, label in perf:
        v = tv.get(key)
        if v is None:
            continue
        cls = 'up' if v > 0 else ('down' if v < 0 else '')
        rows += (f'<div class="kv"><span class="k">{label}</span>'
                 f'<span class="v num {cls}">{minus(f(v, "pct"))}</span></div>')
    five = tv.get('perf_5y')
    if five is not None and five > -100:
        ann = ((1 + five / 100) ** 0.2 - 1) * 100
        cls = 'up' if ann > 0 else 'down'
        rows += (f'<div class="kv"><span class="k">Five years, annualised</span>'
                 f'<span class="v num {cls}">{minus(f(ann, "pct"))}</span></div>')
    if rows:
        one, fiveann = tv.get('perf_1y'), None
        if five is not None and five > -100:
            fiveann = ((1 + five / 100) ** 0.2 - 1) * 100
        say = ''
        ytd = tv.get('perf_ytd')
        if one is None and ytd is not None:
            say = ('Positive so far this year.' if ytd > 0 else
                   'Negative so far this year.')
        elif one is not None and fiveann is None:
            say = ('The one year figure is the only horizon the feed carries here, so there '
                   'is no longer record to weigh it against.')
        if one is not None and fiveann is not None:
            say = ('The last year has run well ahead of the longer record, so recent strength '
                   'is doing the work.' if one > fiveann * 2 + 5 else
                   'The last year has lagged the longer record, so the recent period is the '
                   'weaker part of the story.' if one < fiveann - 5 else
                   'The last year is broadly in line with the longer record, which is the '
                   'steadier version of this.')
        rail(f'<div class="card"><span class="src">TradingView, {esc(tv_date)}</span>'
                 f'<h2>Returns</h2><div class="sub">Price only, dividends excluded</div>'
                 f'{rows}' + (note(say) if say else '') + '</div>')

    # ---- trend. Price against its own moving averages, which the chart shows but does not
    #      quantify, plus the momentum reading.
    ema50, ema200, rsi = tv.get('ema50'), tv.get('ema200'), tv.get('rsi14')
    trend_rows = ''
    for label, ema in (('Against the 50 day average', ema50),
                       ('Against the 200 day average', ema200)):
        if ema and price:
            gap = (price / ema - 1) * 100
            cls = 'up' if gap > 0 else 'down'
            trend_rows += (f'<div class="kv"><span class="k">{label}</span>'
                           f'<span class="v num {cls}">{minus(f(gap, "pct"))}</span></div>')
    if rsi is not None:
        trend_rows += (f'<div class="kv"><span class="k">RSI, 14 day</span>'
                       f'<span class="v num">{f(rsi, "num", 1)}</span></div>')
    if trend_rows:
        say = []
        if ema50 and ema200 and price:
            above_both = price > ema50 and price > ema200
            below_both = price < ema50 and price < ema200
            say.append('Trading above both averages, so the trend is with it' if above_both
                       else 'Trading below both averages, so the trend is against it'
                       if below_both else 'Caught between its two averages, with no trend '
                       'either way')
        if rsi is not None:
            say.append('and momentum is stretched' if rsi > 70 else
                       'and momentum is washed out' if rsi < 30 else
                       'and momentum is unremarkable')
        rail(f'<div class="card"><span class="src">TradingView, {esc(tv_date)}</span>'
                 f'<h2>Trend</h2><div class="sub">Where the price sits against its own '
                 f'averages</div>{trend_rows}'
                 + (note(sentence(say)) if say else '') + '</div>')

    target = info.get('targetMeanPrice')
    if target or info.get('recommendationKey'):
        n_an = info.get('numberOfAnalystOpinions')
        up = ((target / price - 1) * 100) if (target and price) else None
        lo, hi = info.get('targetLowPrice'), info.get('targetHighPrice')
        rows = [('Consensus', str(info.get('recommendationKey') or 'n/a').replace('_', ' ').title()),
                ('Mean target', f(target)),
                ('Implied upside', minus(f(up, 'pct'))),
                ('Target range', f'{f(lo)} to {f(hi)}' if lo and hi else 'n/a')]
        kv = ''.join(f'<div class="kv"><span class="k">{a}</span>'
                     f'<span class="v num">{b}</span></div>' for a, b in rows)
        tail = ''
        if lo and hi and price and (hi - lo) / price > 0.5:
            tail = ('<div class="read" style="margin-top:12px;font-size:11.5px">The targets '
                    'disagree by more than half the share price, so there is no consensus '
                    'here, only a midpoint between two opposing views.</div>')
        elif n_an is not None and n_an < 4:
            tail = ('<div class="read" style="margin-top:12px;font-size:11.5px">Too few '
                    'analysts follow this for the target to carry weight. A consensus of '
                    'three is a coincidence.</div>')
        rail(f'<div class="card"><span class="src y">Yahoo</span><h2>The analyst view</h2>'
                 f'<div class="sub">{n_an or 0} analysts covering</div>{kv}{tail}</div>')

    if tv.get('marquee'):
        n_inv = tv.get('marquee_investors')
        mx = tv.get('marquee_max_pct')
        hold = tv.get('marquee_hold_price')
        rows_m = ''
        if n_inv:
            rows_m += (f'<div class="kv"><span class="k">Investors holding</span>'
                       f'<span class="v num">{f(n_inv, "int")}</span></div>')
        if mx:
            rows_m += (f'<div class="kv"><span class="k">Largest single position'
                       f'<span class="per">of that investor\'s book</span></span>'
                       f'<span class="v num">{f(mx, "pct")}</span></div>')
        if hold and price:
            gap = (price / hold - 1) * 100
            cls = 'up' if gap > 0 else 'down'
            rows_m += (f'<div class="kv"><span class="k">Average entry price</span>'
                       f'<span class="v num">{f(hold)}</span></div>'
                       f'<div class="kv"><span class="k">Holders are</span>'
                       f'<span class="v num {cls}">{minus(f(gap, "pct"))}</span></div>')
        rows_m += (f'<div class="kv"><span class="k">Cleared the screen</span>'
                   f'<span class="v">{"Yes" if tv.get("screened") else "No"}</span></div>')

        # Conviction is the largest single position, not the aggregate. The aggregate is a
        # share of the entire tracked superportfolio, so it is small for everything and says
        # nothing. One manager with a third of their book in a name is a real signal.
        say = []
        if mx is not None:
            say.append(
                'At least one manager has made this a cornerstone of their book'
                if mx > 20 else
                'At least one manager holds it at meaningful size' if mx > 7 else
                'Nobody holds it at size, so it is a position rather than a conviction')
        if n_inv:
            say.append('and it is widely held across the managers tracked' if n_inv >= 15
                       else 'and only a handful of managers hold it at all' if n_inv <= 3
                       else 'and it is held by a moderate number of them')
        if hold and price and price < hold:
            say.append('with the average holder currently under water, so the thesis has not '
                       'worked yet for them')
        H_note = note(sentence(say)) if say else ''
        rail(f'<div class="card"><span class="src">Dataroma, '
             f'{esc(tv.get("_marquee_as_of",""))}</span>'
             f'<h2>Superinvestor ownership</h2>'
             f'<div class="sub">Discretionary managers who file 13F, as tracked by '
             f'Dataroma</div>{rows_m}{H_note}</div>')

    pos_rows = []
    sp = info.get('shortPercentOfFloat')
    if sp is not None:
        pos_rows.append(('Short interest', f(sp * 100, 'pct'),
                         'mid' if sp > 0.08 else ''))
    for k, lbl in (('heldPercentInstitutions', 'Held by institutions'),
                   ('heldPercentInsiders', 'Held by insiders')):
        if info.get(k) is not None:
            pos_rows.append((lbl, f(info[k] * 100, 'pct'), ''))
    if pos_rows:
        kv = ''.join(f'<div class="kv"><span class="k">{a}</span>'
                     f'<span class="v num {c}">{b}</span></div>' for a, b, c in pos_rows)
        extra_note = ''
        if sp and sp > 0.08:
            extra_note = (f'<div class="read" style="margin-top:12px;font-size:11.5px">Short '
                          f'interest of <b>{f(sp*100, "pct")} of float</b> is high. Someone '
                          f'has done work that reaches the opposite conclusion.</div>')
        inst = info.get('heldPercentInstitutions')
        say = []
        if inst is not None:
            say.append(
                'The register is already full of institutions, so the next buyer has to come '
                'from somewhere else' if inst > 0.8 else
                'Institutions hold a normal share, leaving room for new money' if inst > 0.4
                else 'Thinly held by institutions, which cuts both ways on liquidity')
        if sp is not None:
            say.append('and there is a real short case worth reading before acting'
                       if sp > 0.08 else
                       'and the bears are not making much of a case' if sp < 0.03 else
                       'and short interest is unremarkable')
        concl = note(sentence(say)) if say else ''
        rail(f'<div class="card"><span class="src y">Yahoo</span><h2>Positioning</h2>'
                 f'{kv}{extra_note}{concl}</div>')

    holders = (yf_data or {}).get('institutional_holders')
    if holders is not None and hasattr(holders, 'empty') and not holders.empty:
        name_col = next((c for c in holders.columns if 'holder' in str(c).lower()), None)
        pct_col = next((c for c in holders.columns
                        if 'out' in str(c).lower() or 'pct' in str(c).lower()), None)
        rows = ''
        for _, r in holders.head(6).iterrows():
            nm = esc(r[name_col]) if name_col else ''
            pv = r[pct_col] if pct_col else None
            if pv is not None and not pd.isna(pv):
                pv = pv * 100 if pv < 1 else pv
            rows += (f'<div class="holder"><span class="n">{nm}</span>'
                     f'<span class="p num">{f(pv, "pct")}</span></div>')
        if rows:
            rail(f'<div class="card"><span class="src y">Yahoo</span>'
                     f'<h2>Largest holders</h2>{rows}'
                     f'<div class="sub" style="margin:11px 0 0">Index funds included. The '
                     f'Dataroma block is a different question, not who owns it but who '
                     f'chose it.</div></div>')

    news = (yf_data or {}).get('news') or []
    items = ''
    for item in news[:5]:
        c = item.get('content') if isinstance(item.get('content'), dict) else item
        title = c.get('title') or item.get('title')
        if not title:
            continue
        link = ((c.get('canonicalUrl') or {}).get('url')
                if isinstance(c.get('canonicalUrl'), dict) else c.get('link') or item.get('link'))
        pub = ((c.get('provider') or {}).get('displayName')
               if isinstance(c.get('provider'), dict) else item.get('publisher'))
        stamp = c.get('pubDate') or ''
        if isinstance(stamp, str) and 'T' in stamp:
            stamp = stamp.split('T')[0]
        m = ', '.join(str(x) for x in [pub, stamp] if x)
        href = f' href="{esc(link)}" target="_blank" rel="noopener"' if link else ''
        items += f'<a{href}>{esc(title)}<div class="m">{esc(m)}</div></a>'
    if items:
        rail(f'<div class="card news"><span class="src y">Yahoo</span>'
                 f'<h2>Recent coverage</h2>{items}</div>')

    H.append('<div class="grid"><div>' + ''.join(LEFT)
             + '</div><div>' + ''.join(RAIL) + '</div></div>')    # close rail and grid

    # ---------- the reading, last, after the evidence ----------
    supports, against, verify = assessment(tv, stats, forensics, risk, dupont_rows,
                                           qoe_rows, capital, per_share, info)
    def col(cls, title, items):
        lis = ''.join(f'<li>{x}</li>' for x in items) or '<li>Nothing conclusive.</li>'
        return f'<div class="vcol {cls}"><h3>{title}</h3><ul>{lis}</ul></div>'
    lede_html = f'<div class="lede">{esc(lede)}</div>' if lede else ''
    H.append(
        f'<div class="view"><span class="src">Author\'s reading</span>'
        f'<h2>Where the numbers point</h2>{lede_html}'
        f'<div class="vcols">'
        + col('s', 'Supported by the data', supports)
        + col('c', 'Cuts against it', against)
        + col('v', 'Verify before acting', verify)
        + '</div><div class="disc"><b>The author\'s own reading, for internal research.</b> '
          'Not investment advice, not a recommendation, and it takes no account of any '
          'person\'s objectives or circumstances. Figures come from third party sources, '
          'believed reliable but not independently verified.</div></div>')

    # ---------- sources ----------
    H.append(
        f'<div class="foot"><b>Sources.</b> TradingView export of {esc(tv_date)} for every '
        f'ratio it publishes, so this page agrees with the screen that surfaced the name. '
        f'Yahoo, live, for the business description, forensic scores, statement trends, the '
        f'return decomposition, cash flow history, per share growth, the full price history, '
        f'positioning and news.<br><b>Not shown, deliberately.</b> More than four years of '
        f'statements, because that is all Yahoo returns even though the price history runs '
        f'much longer. Segment revenue, guidance, transcripts and analyst revision history, '
        f'none of which are in this data at any price. Point in time statements, since '
        f'restatements overwrite prior years, which makes this fine for analysis and '
        f'unusable for backtesting. Altman for banks, insurers and REITs, because neither '
        f'model fits that balance sheet.<br><b>Every figure here is an input, not a '
        f'recommendation.</b></div>')
    H.append('</div>')
    return ''.join(H)


def assessment(tv, stats, forensics, risk, dupont_rows, qoe_rows, capital, per_share, info):
    """Three lists built mechanically from the figures on the page.

    Every line traces to a number shown above it. Nothing here is a judgement about what to
    do, which is why the paragraph above it is left for a person to write.
    """
    s, c, v = [], [], []

    better, total = peer_summary(tv, stats)
    if total:
        if better >= total - 1:
            s.append(f'{better} of {total} compared ratios sit on the better side of the '
                     f'sector median.')
        elif better <= 1:
            c.append(f'Only {better} of {total} compared ratios beat the sector median.')

    if dupont_rows:
        last = dupont_rows[-1]
        if last['net_margin_pct'] >= 10 and last['equity_multiplier'] < 2.5:
            s.append(f'Return on equity of {f(last["roe_pct"], "pct")} earned on margin, not '
                     f'leverage. Equity multiplier {f(last["equity_multiplier"])}.')
        elif last['equity_multiplier'] >= 3:
            c.append(f'Equity multiplier of {f(last["equity_multiplier"])} means the return '
                     f'leans on the balance sheet.')

    usable = [r['cfo_to_ni'] for r in (qoe_rows or []) if r.get('cfo_to_ni') is not None]
    if usable:
        avg = sum(usable) / len(usable)
        if avg >= 1.1:
            s.append(f'Cash conversion averages {f(avg, "x")} of reported profit over '
                     f'{len(usable)} years.')
        elif avg < 0.9:
            c.append(f'Cash conversion averages only {f(avg, "x")} of reported profit. '
                     f'Profit is running ahead of cash.')
            v.append('Why profit exceeds cash flow, line by line, before anything else.')

    de, cover = tv.get('debt_equity'), tv.get('interest_cover')
    if de is not None and de < 0.5 and (cover or 0) > 5:
        s.append(f'Debt to equity {f(de, "x")} with interest cover {f(cover, "x")}. Little '
                 f'refinancing risk.')
    elif de is not None and de > 2:
        c.append(f'Debt to equity {f(de, "x")}, so the balance sheet carries real leverage.')
        v.append('The maturity profile of that debt and the cost of refinancing it.')

    z, pf = tv.get('altman_z'), tv.get('piotroski_f')
    bm = ((forensics or {}).get('beneish') or {}).get('score')
    if z is not None and z > 3 and (pf or 0) >= 7 and bm is not None and bm < -1.78:
        s.append(f'Altman {f(z)}, Piotroski {pf:,.0f} of 9 and a clean Beneish all agree.')
    if bm is not None and bm > -1.78:
        c.append(f'Beneish M of {minus(f(bm))} sits above the {minus("-1.78")} threshold.')
        v.append('Which Beneish component is driving the flag, receivables or accruals.')
    if z is not None and z < 1.8 and tv.get('gics') not in ('Financials', 'Real Estate'):
        c.append(f'Altman Z of {f(z)} is inside the distress band.')

    if capital and capital.get('uses') and capital.get('cumulative_cfo'):
        capex = next((u for u in capital['uses'] if 'Capital' in u['use']), None)
        returns = sum(u['amount'] for u in capital['uses']
                      if u['use'] in ('Share buybacks', 'Dividends paid'))
        if capex and (capex.get('pct_of_cfo') or 0) > 70:
            c.append(f'{f(capex["pct_of_cfo"], "pct")} of operating cash flow went into '
                     f'capital expenditure.')
            v.append('Utilisation and pricing on the capacity that spending bought.')
        if returns and capital['cumulative_cfo']:
            share = returns / capital['cumulative_cfo'] * 100
            if share > 40:
                s.append(f'{f(share, "pct")} of operating cash flow returned to holders '
                         f'through buybacks and dividends.')

    if per_share:
        sc = per_share.get('share_count_cagr_pct')
        gap = None
        if per_share.get('revenue_cagr_pct') is not None and                 per_share.get('revenue_per_share_cagr_pct') is not None:
            gap = per_share['revenue_cagr_pct'] - per_share['revenue_per_share_cagr_pct']
        if gap is not None and gap > 2:
            c.append(f'Revenue grew {f(gap, "pct")} a year faster than revenue per share. '
                     f'That gap is dilution.')
        elif sc is not None and sc < -1:
            s.append(f'Share count falling {f(abs(sc), "pct")} a year, so per share growth '
                     f'runs ahead of absolute growth.')

    dd = risk.get('max_drawdown_pct')
    if dd is not None and dd < -50:
        v.append(f'The {minus(f(dd, "pct"))} fall in the price record. The same business was '
                 f'priced very differently once.')
    lo52, hi52, price = info.get('fiftyTwoWeekLow'), info.get('fiftyTwoWeekHigh'), tv.get('price')
    if lo52 and hi52 and price and hi52 > lo52:
        pos = (price - lo52) / (hi52 - lo52) * 100
        if pos > 85:
            c.append(f'Trading at {f(pos, "pct")} of its 52 week range.')
        elif pos < 15:
            v.append(f'Why it sits at {f(pos, "pct")} of its 52 week range when the ratios '
                     f'read well.')
    sp = info.get('shortPercentOfFloat')
    if sp and sp > 0.08:
        c.append(f'Short interest {f(sp*100, "pct")} of float. Somebody informed disagrees.')
    lo, hi = info.get('targetLowPrice'), info.get('targetHighPrice')
    if lo and hi and price and (hi - lo) / price > 0.5:
        c.append(f'Analyst targets span {f(lo)} to {f(hi)}. There is no consensus, only a '
                 f'midpoint.')

    v.append('Whether the current margin is contracted or spot, since neither this page nor '
             'the screen can tell.')
    return s[:4], c[:4], v[:4]
