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

import pandas as pd

INK, NAVY, GOLD = '#1a1a1a', '#1f3864', '#bf8f00'
UP, DOWN, MID = '#12703a', '#a5201a', '#8a6300'

CSS = """
<style>
 .an *{box-sizing:border-box}
 .an{font:14px/1.45 -apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1a1a1a;
     max-width:1180px;margin:0 auto}
 .an .num{font-variant-numeric:tabular-nums}
 .an .mast{background:#fff;border:1px solid #d8dee9;border-radius:8px;padding:20px 24px;
     display:flex;justify-content:space-between;align-items:flex-start;gap:28px}
 .an .eyebrow{font-size:10.5px;font-weight:700;letter-spacing:.11em;text-transform:uppercase;
     color:#bf8f00;margin-bottom:8px}
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
 .an .up{color:#12703a} .an .down{color:#a5201a} .an .mid{color:#8a6300}
 .an .strip{display:grid;grid-template-columns:repeat(6,1fr);gap:1px;background:#d8dee9;
     border:1px solid #d8dee9;border-radius:8px;overflow:hidden;margin-top:12px}
 .an .strip>div{background:#fff;padding:12px 14px}
 .an .strip .k{font-size:10px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
     color:#1f3864}
 .an .strip .v{margin-top:6px;font-size:21px;font-weight:650;line-height:1}
 .an .strip .v small{font-size:12px;font-weight:600;color:#1f3864}
 .an .strip .n{margin-top:6px;font-size:10.5px;font-weight:500;line-height:1.4}
 .an .pill{display:inline-block;padding:1px 6px;border-radius:3px;font-size:9.5px;
     font-weight:700;letter-spacing:.04em;text-transform:uppercase;margin-right:4px}
 .an .pill.g{background:#e3f1e8;color:#12703a} .an .pill.a{background:#fbf1dc;color:#8a6300}
 .an .pill.r{background:#fbe6e4;color:#a5201a} .an .pill.n{background:#e9edf3;color:#1f3864}
 .an .grid{display:grid;grid-template-columns:1fr 348px;gap:12px;margin-top:12px;
     align-items:start}
 @media(max-width:940px){.an .grid{grid-template-columns:1fr}
     .an .strip{grid-template-columns:repeat(3,1fr)}}
 .an .card{background:#fff;border:1px solid #d8dee9;border-radius:8px;padding:17px 19px;
     margin-bottom:12px}
 .an .card h2{margin:0 0 3px;font-size:13.5px;font-weight:700;letter-spacing:-.01em}
 .an .card .sub{font-size:11.5px;font-weight:500;margin-bottom:13px;line-height:1.45}
 .an .src{float:right;font-size:9.5px;font-weight:700;letter-spacing:.05em;
     text-transform:uppercase;padding:2px 7px;border-radius:3px;background:#e8edf5;color:#1f3864}
 .an .src.y{background:#f7f1de;color:#bf8f00}
 .an table{width:100%;border-collapse:collapse}
 .an th,.an td{text-align:right;padding:7px 0;font-size:12.5px;border-bottom:1px solid #e9edf3}
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
 .an .legend{margin-top:11px;font-size:10.5px;font-weight:500}
 .an .legend i{display:inline-block;width:9px;height:9px;background:#1f3864;border-radius:2px;
     margin-right:4px;vertical-align:-1px}
 .an .legend u{display:inline-block;width:2px;height:11px;background:#bf8f00;margin:0 4px 0 12px;
     vertical-align:-2px;text-decoration:none}
 .an .read{margin-top:13px;padding:12px 14px;background:#f4f7fb;border:1px solid #d8dee9;
     border-left:3px solid #1f3864;border-radius:5px;font-size:12.5px;font-weight:500;
     line-height:1.6}
 .an .read b{font-weight:700}
 .an .chart{width:100%;display:block}
 .an .kv{display:flex;justify-content:space-between;gap:10px;padding:6px 0;font-size:12.5px;
     border-bottom:1px solid #e9edf3}
 .an .kv:last-child{border-bottom:none}
 .an .kv .k{font-weight:500} .an .kv .v{font-weight:700;font-variant-numeric:tabular-nums}
 .an .holder{display:flex;justify-content:space-between;font-size:12px;padding:5px 0;
     border-bottom:1px solid #e9edf3}
 .an .holder:last-child{border-bottom:none}
 .an .holder .n{font-weight:500}
 .an .holder .p{font-weight:700;font-variant-numeric:tabular-nums}
 .an .news a{display:block;font-size:12.5px;font-weight:600;color:#1a1a1a;text-decoration:none;
     padding:8px 0;border-bottom:1px solid #e9edf3;line-height:1.45}
 .an .news a:last-child{border-bottom:none}
 .an .news .m{font-size:10.5px;font-weight:600;color:#1f3864;margin-top:3px}
 .an .body-text{font-size:12.5px;font-weight:500;line-height:1.6;margin-top:10px}
 .an .view{background:#fff;border:1px solid #d8dee9;border-top:3px solid #1f3864;
     border-radius:8px;padding:14px 18px;margin-top:12px}
 .an .view h2{margin:0;font-size:13px;font-weight:700}
 .an .view .lede{font-size:12.5px;font-weight:500;line-height:1.55;margin:8px 0 11px}
 .an .view .lede b{font-weight:700}
 .an .vcols{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
 @media(max-width:940px){.an .vcols{grid-template-columns:1fr}}
 .an .vcol{border:1px solid #d8dee9;border-radius:5px;padding:9px 11px;background:#f4f7fb}
 .an .vcol.s{border-left:3px solid #12703a}
 .an .vcol.c{border-left:3px solid #8a6300}
 .an .vcol.v{border-left:3px solid #1f3864}
 .an .vcol h3{margin:0 0 6px;font-size:9.5px;font-weight:700;letter-spacing:.07em;
     text-transform:uppercase}
 .an .vcol ul{margin:0;padding-left:14px}
 .an .vcol li{font-size:11.5px;font-weight:500;line-height:1.45;margin-bottom:4px}
 .an .vcol li:last-child{margin-bottom:0}
 .an .disc{margin-top:10px;font-size:10.5px;font-weight:500;line-height:1.5}
 .an .disc b{font-weight:700}
 .an .foot{margin-top:16px;padding:15px 18px;background:#fff;border:1px solid #d8dee9;
     border-radius:8px;font-size:11px;font-weight:500;line-height:1.75}
 .an .foot b{font-weight:700}
</style>
"""


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


def svg_price(close, ma50, ma200, width=720, height=206):
    """Close with its two moving averages. Averages are computed on the full series and
    then sliced, so a short window still shows a correct 200 day line."""
    body, lo, hi = _points(list(close), width, height)
    if not body:
        return '<div class="sub">Not enough price history to draw a chart.</div>'
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" '
             f'preserveAspectRatio="none" style="height:{height}px">']
    for gy in (0.25, 0.5, 0.75):
        y = 6 + gy * (height - 12)
        parts.append(f'<line x1="0" y1="{y:.0f}" x2="{width}" y2="{y:.0f}" stroke="#e9edf3"/>')

    def overlay(series, colour, dash=''):
        if series is None:
            return
        vals = list(series)
        if not any(v is not None and not pd.isna(v) for v in vals):
            return
        # scaled against the price range so the lines sit correctly against the close
        span = (hi - lo) or 1
        usable = height - 12
        step = width / max(1, len(vals) - 1)
        pts = [f'{i*step:.1f},{6 + (hi - v)/span*usable:.1f}'
               for i, v in enumerate(vals) if v is not None and not pd.isna(v)]
        if len(pts) > 1:
            d = f' stroke-dasharray="{dash}"' if dash else ''
            parts.append(f'<polyline fill="none" stroke="{colour}" stroke-width="1.3"'
                         f'{d} points="{" ".join(pts)}"/>')

    overlay(ma50, '#8fa3bf')
    overlay(ma200, '#b9c4d4', '4,3')
    parts.append(f'<polyline fill="none" stroke="{NAVY}" stroke-width="2" '
                 f'points="{body}"/>')
    parts.append('</svg>')
    return ''.join(parts)


def svg_drawdown(close, width=720, height=66):
    """Fall from the running peak, which is what holding it actually felt like."""
    series = pd.Series(list(close)).dropna()
    if len(series) < 3:
        return ''
    dd = ((series / series.cummax()) - 1) * 100
    worst = float(dd.min()) or -1
    step = width / max(1, len(dd) - 1)
    pts = [f'{i*step:.1f},{2 + (v / worst) * (height - 8):.1f}'
           for i, v in enumerate(dd)]
    return (f'<svg class="chart" viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
            f'style="height:{height}px"><line x1="0" y1="2" x2="{width}" y2="2" '
            f'stroke="#d8dee9"/><polyline fill="none" stroke="{DOWN}" stroke-width="1.5" '
            f'points="{" ".join(pts)}"/></svg>')


# ------------------------------------------------------------------ peer bars -----------
PEER_ROWS = [('pe', 'P/E', 'x', False), ('roe', 'Return on equity', 'pct', True),
             ('op_margin', 'Operating margin', 'pct', True),
             ('net_margin', 'Net margin', 'pct', True),
             ('debt_equity', 'Debt / equity', 'x', False),
             ('interest_cover', 'Interest cover', 'x', True)]


def peer_bars(tv, stats):
    """One row per ratio: navy bar for the company, gold line for the sector median.

    Both are scaled against the same ceiling so the bar and the marker are comparable. The
    ceiling is the wider of the company value and twice the median, which keeps a company
    far above its sector on the chart instead of pinning it at 100%.
    """
    rows = []
    for key, label, kind, _higher in PEER_ROWS:
        val = tv.get(key)
        block = (stats or {}).get(key)
        if val is None and not block:
            continue
        med = block.get('median') if block else None
        ceiling = max(abs(val or 0), abs(med or 0) * 2, 1e-9)
        wid = min(100, abs(val or 0) / ceiling * 100)
        marker = min(99, abs(med or 0) / ceiling * 100) if med is not None else None
        mark = f'<u style="left:{marker:.0f}%"></u>' if marker is not None else ''
        rows.append(
            f'<div class="brow"><div class="bl">{label}</div>'
            f'<div class="bt"><i style="width:{wid:.0f}%"></i>{mark}</div>'
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
def build(tv, isin, yf_data, stats, forensics, resolution, risk, dupont_rows, qoe_rows,
          qoe_verdict, capital, per_share, span_label, close, ma50, ma200, lede=''):
    """Assemble the whole page. Every argument is already computed; this only lays out."""
    info = (yf_data or {}).get('info') or {}
    ccy = tv.get('ccy') or info.get('currency') or ''
    price = tv.get('price') or info.get('currentPrice')
    ytd = tv.get('perf_ytd')
    tv_date = tv.get('_as_of', '')
    gics = tv.get('gics')
    H = [CSS, '<div class="an">']

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
        f'<div class="quote"><div class="eyebrow">Last price</div>'
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
    H.append('<div class="grid"><div>')

    # sector comparison
    bars = peer_bars(tv, stats)
    if bars:
        better, total = peer_summary(tv, stats)
        n = (stats or {}).get('pe', {}).get('n') or (stats or {}).get('roe', {}).get('n')
        H.append(
            f'<div class="card"><span class="src">TradingView, {esc(tv_date)}</span>'
            f'<h2>Against its sector</h2>'
            f'<div class="sub">Navy bar is the company, gold line is the {esc(gics or "sector")} '
            f'median. The median is taken across every company in the sector'
            + (f', {n:,} of them' if n else '') +
            ', not only those that cleared a screen, because a median of the winners would '
            'make everything look average.</div>'
            f'{bars}<div class="legend"><i></i>company<u></u>sector median</div>'
            + (read(f'<b>{better} of {total}</b> compared measures sit on the better side of '
                    f'the {esc(gics or "sector")} median.') if total else '') +
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
        note = ''
        if full_dd is not None and full_dd < -50:
            note = read(f'That <b>{minus(f(full_dd, "pct"))}</b> fall is measured across the '
                        f'whole history Yahoo holds, starting {esc(start_txt)}. A company can '
                        f'look excellent today and still have taken its holders through a '
                        f'decline like that, which is why the full record is shown rather '
                        f'than the last two years.')
        H.append(
            f'<div class="card"><span class="src y">Yahoo, daily</span>'
            f'<h2>Price and drawdown</h2>'
            f'<div class="sub">Showing {esc(span_label)}. History available from '
            f'{esc(start_txt)}. Navy is the close, the two lighter lines are the 50 and 200 '
            f'day averages. The lower panel is the fall from each running peak.</div>'
            f'{svg_price(close, ma50, ma200)}{svg_drawdown(close)}'
            f'<table style="margin-top:12px">{table}</table>{note}</div>')

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
        moved = ''
        if len(dupont_rows) > 1:
            firstr = dupont_rows[0]
            d_margin = last['net_margin_pct'] - firstr['net_margin_pct']
            d_lev = last['equity_multiplier'] - firstr['equity_multiplier']
            moved = (f' Across the period margin moved {minus(f(d_margin, "pct"))} while the '
                     f'equity multiplier moved {minus(f(d_lev))}.')
        H.append(
            f'<div class="card"><span class="src y">Yahoo, annual</span>'
            f'<h2>What drives the return on equity</h2>'
            f'<div class="sub">DuPont decomposition. The same return can come from margin, '
            f'from turnover or from leverage, and those are not the same business.</div>'
            f'<table><thead><tr><th>Year</th><th>Net margin</th><th>Asset turnover</th>'
            f'<th>Equity multiplier</th><th>ROE</th></tr></thead><tbody>{body}</tbody></table>'
            + read(f'The latest return of <b>{minus(f(last["roe_pct"], "pct"))}</b> is driven '
                   f'mainly by <b>{driver}</b>.{moved} A return earned on leverage is a '
                   f'different proposition from the same return earned on margin, and the '
                   f'headline figure cannot separate them.') + '</div>')

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
            uses = ''.join(
                f'<div class="brow"><div class="bl">{esc(u["use"])}</div>'
                f'<div class="bt"><i style="width:{u["amount"]/top*100:.0f}%"></i></div>'
                f'<div class="bv num">{f(u["amount"], "money")}</div>'
                f'<div class="bp num">{f(u["pct_of_cfo"], "pct")}</div></div>'
                for u in capital['uses'])
            uses = f'<div style="margin-top:14px">{uses}</div>'
        H.append(
            f'<div class="card"><span class="src y">Yahoo, annual</span>'
            f'<h2>Does the profit arrive as cash, and where does it go</h2>'
            f'<div class="sub">Reported profit against operating cash flow, then what that '
            f'cash was spent on. Percentages are of cumulative operating cash flow.</div>'
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
        H.append(
            f'<div class="card"><span class="src y">Yahoo, per share</span>'
            f'<h2>Growth the holder actually received</h2>'
            f'<div class="sub">Absolute growth against per share growth, {ps.get("years")} '
            f'years, {esc(ps.get("from"))} to {esc(ps.get("to"))}. The gap between them is '
            f'dilution, and a holder does not receive it.</div>'
            f'<table><thead><tr><th>CAGR</th><th>Absolute</th><th>Per share</th><th>Gap</th>'
            f'</tr></thead><tbody>{body}</tbody></table>{tail}</div>')

    H.append('</div><div>')     # ---------- right rail ----------

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
        H.append(f'<div class="card"><span class="src y">Yahoo</span><h2>Valuation</h2>'
                 f'<div class="sub">Multiples TradingView does not export</div>{kv}</div>')

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
        note = ''
        if lo and hi and price and (hi - lo) / price > 0.5:
            note = (f'<div class="read" style="margin-top:11px;font-size:11.5px">A '
                    f'{f(lo)} to {f(hi)} spread on a {f(price)} price is a wide '
                    f'disagreement. The consensus is the midpoint of different views, not a '
                    f'shared one.</div>')
        elif n_an is not None and n_an < 4:
            note = (f'<div class="read" style="margin-top:11px;font-size:11.5px">Only '
                    f'<b>{n_an}</b> opinions sit behind that target. A consensus of three is '
                    f'a coincidence, not a consensus.</div>')
        H.append(f'<div class="card"><span class="src y">Yahoo</span><h2>The analyst view</h2>'
                 f'<div class="sub">{n_an or 0} analysts covering</div>{kv}{note}</div>')

    if tv.get('marquee'):
        H.append(
            f'<div class="card"><span class="src">Dataroma, {esc(tv.get("_marquee_as_of",""))}'
            f'</span><h2>Superinvestor ownership</h2>'
            f'<div class="kv"><span class="k">Investors holding</span>'
            f'<span class="v num">{f(tv.get("marquee_investors"), "int")}</span></div>'
            f'<div class="kv"><span class="k">Aggregate weight</span>'
            f'<span class="v num">{f(tv.get("marquee_weight_pct"), "pct")}</span></div>'
            f'<div class="kv"><span class="k">Cleared the screen</span>'
            f'<span class="v">{"Yes" if tv.get("screened") else "No"}</span></div></div>')

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
        note = ''
        if sp and sp > 0.08:
            note = (f'<div class="read" style="margin-top:11px;font-size:11.5px">Short '
                    f'interest of <b>{f(sp*100, "pct")} of float</b> is high. Someone has '
                    f'done work that reaches the opposite conclusion.</div>')
        H.append(f'<div class="card"><span class="src y">Yahoo</span><h2>Positioning</h2>'
                 f'{kv}{note}</div>')

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
            H.append(f'<div class="card"><span class="src y">Yahoo</span>'
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
        H.append(f'<div class="card news"><span class="src y">Yahoo</span>'
                 f'<h2>Recent coverage</h2>{items}</div>')

    H.append('</div></div>')    # close rail and grid

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
          'not independently verified.</div></div>')

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
