"""
The stock cycle page, emitted as one block of HTML in the same design as the company page.

Takes what cycle.analyse returns and only lays it out. Every number on the page is read
from that one result, so the reading at the top, the levels in the rail, the tables and
the chart cannot disagree with each other.
"""

import math

import pandas as pd

import cycle as cy
import risk as rk
from page import CSS, DOWN, NAVY, UP, GOLD, HOVER_BAND_UNITS, esc, f, minus

SUPPORT_FILL, RESIST_FILL, BEAR_FILL = '#bfe3cc', '#f4c4bf', '#eef2f8'


# ---------------------------------------------------------------- formatting -------------
def day(ts):
    return pd.Timestamp(ts).strftime('%d %b %Y') if ts is not None else 'n/a'


def pct(x, sign=True):
    """A fraction as a percentage with a real minus sign."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 'n/a'
    s = f'{x * 100:+.1f}%' if sign else f'{x * 100:.1f}%'
    return minus(s)


def mo(x):
    return 'n/a' if x is None else f'{x:.1f} months'


def px(x):
    return f(x)


def kv(k, v, sub=''):
    sub = f'<span class="per">{sub}</span>' if sub else ''
    return f'<div class="kv"><span class="k">{k}</span><span class="v num">{v}{sub}</span></div>'


def card(title, body, sub=''):
    sub = f'<div class="sub">{sub}</div>' if sub else ''
    return f'<div class="card"><h2>{title}</h2>{sub}{body}</div>'


# ---------------------------------------------------------------- chart ------------------
def svg_cycle(close, points, current, phases, zones, width=720, height=280):
    """Price on a log scale, so a 30% fall looks the same size at 10 as at 1,000.

    Bear phases are shaded, peaks and troughs marked, the nearest support and resistance
    zones drawn as bands and the current trigger as a dashed line. Dates run evenly across
    the width, so the markers and the line share one time axis.
    """
    s = rk.thin_series(close)
    t0, t1 = s.index[0], s.index[-1]
    span_t = max(1, (t1 - t0).days)
    levels = [float(v) for v in s.values]
    extra = [z['low'] for z, _, _ in zones] + [z['high'] for z, _, _ in zones]
    if current.get('trigger'):
        extra.append(current['trigger'])
    lo = math.log(min(levels + extra))
    hi = math.log(max(levels + extra))
    rng = (hi - lo) or 1
    top, bot = 8, 8
    usable = height - top - bot

    def x(ts):
        return (pd.Timestamp(ts) - t0).days / span_t * width

    def y(v):
        return top + (hi - math.log(v)) / rng * usable

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
             f'style="height:{height}px;cursor:crosshair">']
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        yy = top + frac * usable
        parts.append(f'<line x1="0" y1="{yy:.0f}" x2="{width}" y2="{yy:.0f}" stroke="#e9edf3"/>')

    # bear phases, completed and open, clipped to the window
    spans = [(p['start'], p['end']) for p in phases if p['kind'] == 'bear']
    if current.get('state') == 'bear' and current.get('start') is not None:
        spans.append((current['start'], current['last_date']))
    for a, b in spans:
        if b < t0 or a > t1:
            continue
        xa, xb = x(max(a, t0)), x(min(b, t1))
        parts.append(f'<rect x="{xa:.1f}" y="0" width="{max(1, xb - xa):.1f}" '
                     f'height="{height}" fill="{BEAR_FILL}"/>')

    # A zone built from one turning point has no height of its own, which drew it as a
    # hairline nobody could see. Each zone is now at least 10 units tall, centred on its
    # levels, with a solid line in its own colour along the level itself.
    for z, fill, edge in zones:
        ya, yb = y(z['high']), y(z['low'])
        if yb - ya < 10:
            mid_y = (ya + yb) / 2
            ya, yb = mid_y - 5, mid_y + 5
        parts.append(f'<rect x="0" y="{ya:.1f}" width="{width}" height="{yb - ya:.1f}" '
                     f'fill="{fill}"/>')
        level = y(z['high'] if edge == UP else z['low'])
        parts.append(f'<line x1="0" y1="{level:.1f}" x2="{width}" y2="{level:.1f}" '
                     f'stroke="{edge}" stroke-width="1.6"/>')

    if current.get('trigger'):
        yt = y(current['trigger'])
        parts.append(f'<line x1="0" y1="{yt:.1f}" x2="{width}" y2="{yt:.1f}" stroke="{GOLD}" '
                     f'stroke-width="1.4" stroke-dasharray="6,4"/>')

    pts = ' '.join(f'{x(t):.1f},{y(v):.1f}' for t, v in zip(s.index, levels))
    parts.append(f'<polyline fill="none" stroke="{NAVY}" stroke-width="1.8" points="{pts}"/>')

    for p in points:
        if p['date'] < t0:
            continue
        cx, cyy = x(p['date']), y(p['price'])
        if p['kind'] == 'peak':
            tri = f'{cx - 5:.1f},{cyy - 9:.1f} {cx + 5:.1f},{cyy - 9:.1f} {cx:.1f},{cyy - 2:.1f}'
            colour, word = DOWN, 'Peak'
        else:
            tri = f'{cx - 5:.1f},{cyy + 9:.1f} {cx + 5:.1f},{cyy + 9:.1f} {cx:.1f},{cyy + 2:.1f}'
            colour, word = UP, 'Trough'
        parts.append(f'<polygon points="{tri}" fill="{colour}"><title>{word} {day(p["date"])} '
                     f'at {px(p["price"])}, confirmed {day(p["confirm_date"])}</title></polygon>')

    # hover readout, the same construction as the company page charts
    bands = max(1, int(width // HOVER_BAND_UNITS))
    bw = width / bands
    idx = list(s.index)
    for b in range(bands):
        target = (t0 + pd.Timedelta(days=(b + 0.5) * span_t / bands)).floor('D')
        i = min(len(idx) - 1, int(s.index.searchsorted(target)))
        v = levels[i]
        cx, cyy = b * bw + bw / 2, y(v)
        lines = [day(idx[i]), f'Close {px(v)}']
        box_w, box_h = 150, 42
        bx = round(cx + 10 if cx < width - box_w - 14 else cx - box_w - 10, 1)
        by = round(min(max(4, cyy - box_h / 2), height - box_h - 4), 1)
        text = ''.join(f'<text x="{bx + 9}" y="{by + 17 + 13 * k}" font-size="10.5" '
                       f'font-weight="{700 if k == 0 else 500}" fill="#1a1a1a">{esc(t)}</text>'
                       for k, t in enumerate(lines))
        parts.append(f'<g class="hb"><rect x="{b * bw:.2f}" y="0" width="{bw:.2f}" '
                     f'height="{height}" fill="transparent"/>'
                     f'<line class="xh" x1="{cx:.1f}" y1="0" x2="{cx:.1f}" y2="{height}" '
                     f'stroke="{GOLD}" stroke-width="1" stroke-dasharray="3,3"/>'
                     f'<circle class="dot" cx="{cx:.1f}" cy="{cyy:.1f}" r="3.5" fill="{NAVY}" '
                     f'stroke="#fff" stroke-width="1.5"/>'
                     f'<g class="tip"><rect x="{bx}" y="{by}" width="{box_w}" height="{box_h}" '
                     f'rx="4" fill="#ffffff" stroke="{NAVY}" stroke-width="1"/>{text}</g></g>')
    parts.append('</svg>')

    # axes as HTML, as on the company page, so the labels keep the page typeface
    mid = math.exp((hi + lo) / 2)
    yaxis = (f'<span class="hi">{px(math.exp(hi))}</span><span class="mid">{px(mid)}</span>'
             f'<span class="lo">{px(math.exp(lo))}</span>')
    fmt = '%Y' if span_t > 365 * 8 else '%b %Y'
    dates = []
    for t in range(6):
        when = t0 + pd.Timedelta(days=t / 5 * span_t)
        align = ('left:0;text-align:left' if t == 0 else 'right:0;text-align:right' if t == 5
                 else f'left:{t * 20}%;transform:translateX(-50%)')
        dates.append(f'<span style="position:absolute;{align}">{when.strftime(fmt)}</span>')
    tags = ''
    for z, _, edge in zones:
        level = z['high'] if edge == UP else z['low']
        top_pct = max(0.0, min(100.0, y(level) / height * 100))
        word = 'Support' if edge == UP else 'Resistance'
        tags += (f'<span class="cylab" style="top:{top_pct:.2f}%;color:{edge};'
                 f'border-color:{edge}">{word} {px(level)}</span>')
    if current.get('trigger'):
        top_pct = max(0.0, min(100.0, y(current['trigger']) / height * 100))
        tags += (f'<span class="cylab" style="top:{top_pct:.2f}%;color:#8a6300;'
                 f'border-color:{GOLD};left:auto;right:58px">Trigger {px(current["trigger"])}</span>')
    return (f'<div class="plot"><div class="yaxis">{yaxis}</div>{"".join(parts)}{tags}</div>'
            f'<div class="xaxis">{"".join(dates)}</div>')


LEGEND = (f'<div class="clegend">'
          f'<span><i style="background:{NAVY};height:3px"></i>Close, log scale</span>'
          f'<span><i style="background:{BEAR_FILL};height:10px"></i>Bear phase</span>'
          f'<span><b style="color:{DOWN}">&#9660;</b>Peak</span>'
          f'<span><b style="color:{UP}">&#9650;</b>Trough</span>'
          f'<span><i style="background:{SUPPORT_FILL};height:10px;border-top:2px solid {UP}">'
          f'</i>Nearest support</span>'
          f'<span><i style="background:{RESIST_FILL};height:10px;border-bottom:2px solid {DOWN}">'
          f'</i>Nearest resistance</span>'
          f'<span><i style="background:repeating-linear-gradient(90deg,{GOLD} 0 6px,'
          f'transparent 6px 10px)"></i>Trigger that ends the current phase</span></div>')


def chart_card(r):
    """Two ranges, switched in the browser with the same radio and CSS trick as the company
    page. Five years shows the levels that matter now; the full record shows every cycle."""
    close, cur = r['close'], r['current']
    shown = [(z, fill, edge) for z, fill, edge in ((r['support'], SUPPORT_FILL, UP),
                                                   (r['resistance'], RESIST_FILL, DOWN)) if z]
    ranges = [('5Y', close.loc[close.index[-1] - pd.DateOffset(years=5):]), ('Max', close)]
    if len(ranges[0][1]) > len(close) * 0.9:
        ranges = [('Max', close)]
    current = ranges[0][0]
    tabs, panels = [], []
    for lab, win in ranges:
        on = ' on' if lab == current else ''
        word = 'Last five years' if lab == '5Y' else 'Full record'
        tabs.append(f'<label class="sbtn{on}"><input type="radio" name="cyspan" '
                    f'class="si-{lab}">{word}</label>')
        panels.append(f'<div class="spanpanel sp-{lab}{on}">'
                      + svg_cycle(win, r['points'], cur, r['phases'], shown) + '</div>')
    body = (LEGEND + f'<div class="spanset"><div class="tabs">{"".join(tabs)}</div>'
            f'{"".join(panels)}</div>'
            '<div class="smallnote">Hover over the chart for the date and close. Hover over a '
            'marker for the turning point and the day it was confirmed.</div>')
    return card('Price and every confirmed cycle', body,
                f'{day(r["first_date"])} to {day(r["last_date"])}. Traded prices, adjusted '
                f'for splits, not for dividends.')


# ---------------------------------------------------------------- the reading ------------
def compare_basis(r, key):
    """The medians the reading compares against: excluding extremes when any remain."""
    clean, everything = r['clean'][key], r['all'][key]
    if clean['n']:
        return clean, r['extremes']
    return everything, 0


def reading(r):
    cur, T = r['current'], r['threshold']
    if not cur.get('state'):
        return (f'No cycle yet. Since {day(r["first_date"])} the price has not moved '
                f'{pct(T, False)} from any high or low, which is the move this stock needs to '
                f'start or end a phase.')
    if cur['state'] == 'bull':
        s = (f'<b>Bull phase</b> since the {day(cur["start"])} low of {px(cur["start_price"])}, '
             f'confirmed on {day(cur["confirm_date"])}. The latest close of '
             f'{px(cur["last_price"])} is {pct(-cur["from_extreme"], False)} below the '
             f'{px(cur["extreme"])} high, and the phase ends on a close below '
             f'<b>{px(cur["trigger"])}</b>.')
        key, word = 'bull_months', 'bull'
    else:
        s = (f'<b>Bear phase</b> since the {day(cur["start"])} high of {px(cur["start_price"])}, '
             f'confirmed on {day(cur["confirm_date"])}. The latest close of '
             f'{px(cur["last_price"])} is {pct(cur["from_extreme"], False)} above the '
             f'{px(cur["extreme"])} low, and the phase ends on a close above '
             f'<b>{px(cur["trigger"])}</b>.')
        key, word = 'bear_months', 'bear'
    basis, dropped = compare_basis(r, key)
    if basis['n']:
        share = cur['months'] / basis['median'] if basis['median'] else None
        ex = f', {dropped} extreme phase{"s" if dropped != 1 else ""} excluded' if dropped else ''
        typ = (f'{mo(basis["median"])}, median of {basis["n"]} '
               f'phase{"s" if basis["n"] != 1 else ""}{ex}')
        if share is not None and share >= 1:
            s += (f' At {mo(cur["months"])}, it is already longer than a typical {word} '
                  f'phase for this stock ({typ}).')
        elif share is not None:
            s += (f' At {mo(cur["months"])}, it has run {share * 100:.0f}% of the length of a '
                  f'typical {word} phase for this stock ({typ}).')
        if basis['n'] < cy.MIN_CYCLES:
            s += (f' With only {basis["n"]} completed {word} phase'
                  f'{"s" if basis["n"] != 1 else ""} to compare against, read this as a '
                  f'description of the past rather than a pattern.')
    else:
        s += f' There is no completed {word} phase yet to compare it with.'
    return s


# ---------------------------------------------------------------- rail -------------------
def now_card(r):
    cur = r['current']
    if not cur.get('state'):
        return card('Where the stock is now',
                    '<div class="body-text">No phase has been confirmed yet.</div>')
    bull = cur['state'] == 'bull'
    rows = [kv('Phase', 'Bull' if bull else 'Bear', 'confirmed'),
            kv('Started', px(cur['start_price']), f'{"low" if bull else "high"} on '
               f'{day(cur["start"])}'),
            kv('Confirmed', px(cur['confirm_price']), f'close on {day(cur["confirm_date"])}'),
            kv('Length so far', mo(cur['months'])),
            kv('Move since it started', pct(cur['change'])),
            kv(f'{"Highest" if bull else "Lowest"} close since', px(cur['extreme']),
               day(cur['extreme_date'])),
            kv('Latest close', px(cur['last_price']), day(cur['last_date'])),
            kv(f'Phase ends on a close {"below" if bull else "above"}', px(cur['trigger']),
               f'{"high" if bull else "low"} {"minus" if bull else "plus"} '
               f'{pct(r["threshold"], False)}'),
            kv('Distance to that level', pct(cur['to_trigger']))]
    if bull and cur.get('held_return') is not None:
        rows.append(kv('Held since confirmation', pct(cur['held_return']),
                       f'{mo(cur["held_months"])}, dividends included'))
    note = ('The phase stays open until the price closes beyond that level. Until then, every '
            'figure here is a reading of the phase so far, not a forecast of where it ends.')
    return card('Where the stock is now', ''.join(rows) + f'<div class="cnote">{note}</div>')


def zone_text(z):
    return px(z['low']) if abs(z['high'] - z['low']) < 1e-9 else f'{px(z["low"])} to {px(z["high"])}'


def zone_rows(z, label):
    turns = []
    if z['troughs']:
        turns.append(f'{z["troughs"]} trough{"s" if z["troughs"] != 1 else ""}')
    if z['peaks']:
        turns.append(f'{z["peaks"]} peak{"s" if z["peaks"] != 1 else ""}')
    return (kv(label, zone_text(z), ', '.join(turns) + f', last {day(z["last"])}')
            + kv('Times it held / broke', f'{z["holds"]} / {z["breaks"]}'))


def levels_card(r):
    price = r['current']['last_price']
    rows = []
    if r['inside']:
        rows.append(f'<div class="body-text">The latest close of {px(price)} sits inside the '
                    f'{zone_text(r["inside"])} zone.</div>')
    rows.append(zone_rows(r['support'], 'Nearest support') if r['support'] else
                kv('Nearest support', 'none', 'no past turn below the price'))
    rows.append(zone_rows(r['resistance'], 'Nearest resistance') if r['resistance'] else
                kv('Nearest resistance', 'none', 'no past turn above the price'))
    note = ('A zone is a band no wider than 4% where past peaks or troughs cluster. It held each '
            'time the price turned inside it, and broke each time a later phase ran straight '
            'through it. These are levels where the price has turned before, not floors or '
            'ceilings.')
    return card('Support and resistance', ''.join(rows) + f'<div class="cnote">{note}</div>')


def rule_card(r):
    years = (r['last_date'] - r['first_date']).days / 365.25
    vol = r['vol']
    if vol is None:
        how = 'fixed for this run'
    elif r['threshold'] > vol + 1e-9:
        how = f'volatility of {pct(vol, False)}, raised to the 15% floor'
    elif r['threshold'] < vol - 1e-9:
        how = f'volatility of {pct(vol, False)}, capped at 35%'
    else:
        how = 'its typical annual volatility'
    done = len(r['phases'])
    return card('The rule for this stock',
                kv('Threshold', pct(r['threshold'], False), how)
                + kv('History used', f'{years:.1f} years', f'from {day(r["first_date"])}')
                + kv('Confirmed turning points', str(len(r['points'])))
                + kv('Completed phases', str(done),
                     f'{r["extremes"]} extreme' if r['extremes'] else 'none extreme'))


# ---------------------------------------------------------------- main column ------------
def typical_card(r):
    a, c = r['all'], r['clean']
    rows = [('Bull phase length', 'bull_months', 'months', 'trough to peak'),
            ('Bull phase gain', 'bull_change', 'pct', 'trough to peak, price only'),
            ('Bear phase length', 'bear_months', 'months', 'peak to trough'),
            ('Bear phase fall', 'bear_change', 'pct', 'peak to trough, price only'),
            ('Holding period', 'hold_months', 'months', 'confirmation to confirmation'),
            ('Captured return', 'hold_total', 'pct', 'confirmation to confirmation, '
             'dividends included')]

    def cell(d, kind):
        if not d['n']:
            return '<td class="val">n/a</td><td>n/a</td><td>0</td>'
        fmt = (lambda v: f'{v:.1f}') if kind == 'months' else pct
        return (f'<td class="val">{fmt(d["median"])}</td>'
                f'<td>{fmt(d["p25"])} to {fmt(d["p75"])}</td><td>{d["n"]}</td>')

    body = ['<table class="nw"><thead><tr><th>Measure</th><th>Median</th><th>Middle half</th>'
            '<th>Cycles</th><th>Median, no extremes</th><th>Middle half</th><th>Cycles</th>'
            '</tr></thead><tbody>']
    for label, key, kind, what in rows:
        unit = ' (months)' if kind == 'months' else ''
        body.append(f'<tr><td class="lab">{label}{unit}'
                    f'<div class="smallnote" style="margin-top:2px">{what}</div></td>'
                    f'{cell(a[key], kind)}{cell(c[key], kind)}</tr>')
    won_a, won_c = a['hold_won'], c['hold_won']
    body.append(f'<tr><td class="lab">Holds that made money<div class="smallnote" '
                f'style="margin-top:2px">captured return above zero</div></td>'
                f'<td class="val">{won_a[0]} of {won_a[1]}</td><td></td><td></td>'
                f'<td class="val">{won_c[0]} of {won_c[1]}</td><td></td><td></td></tr>')
    body.append('</tbody></table>')

    n = min(a['bull_months']['n'], a['bear_months']['n'])
    notes = []
    if n < cy.MIN_CYCLES:
        notes.append(f'Only {n} completed cycle{"s" if n != 1 else ""}. With fewer than '
                     f'{cy.MIN_CYCLES}, these medians describe what happened rather than a '
                     f'reliable pattern.')
    if r['extremes']:
        notes.append(f'{r["extremes"]} phase{"s are" if r["extremes"] != 1 else " is"} '
                     f'marked extreme and left out of the right-hand columns. They are still '
                     f'shown in the history below.')
    else:
        notes.append('No phase was far enough from the rest to count as extreme, so both '
                     'sets of columns match.' if a['bull_months']['n'] >= cy.MIN_CYCLES else
                     'Extremes are only judged once a stock has at least five completed '
                     'phases of a kind, so nothing has been excluded.')
    if c['hold_total']['n'] and c['bull_change']['n']:
        notes.append(f'The median captured return of {pct(c["hold_total"]["median"])} compares '
                     f'with a median trough to peak gain of {pct(c["bull_change"]["median"])}. '
                     f'The difference is the cost of waiting for each turn to be confirmed, '
                     f'and the captured return is the honest figure for anyone following the '
                     f'rule.')
    return card('A typical cycle for this stock', ''.join(body)
                + f'<div class="cnote">{" ".join(notes)}</div>',
                'Medians, so one unusual cycle cannot move them. The middle half is the range '
                'between the 25th and 75th percentile.')


def tag(p):
    bits = []
    if p.get('extreme'):
        bits.append('<span class="pill a">extreme</span>')
    if p.get('market') == 'market-wide':
        bits.append(f'<span class="pill n">market-wide</span>')
    elif p.get('market') == 'stock-specific':
        bits.append('<span class="pill n">stock-specific</span>')
    return ''.join(bits)


def history_card(r):
    if not r['phases']:
        return card('Every completed phase', '<div class="body-text">None yet. A phase is '
                    'complete once the turn that ends it has been confirmed.</div>')
    rows = ['<table class="nw"><thead><tr><th>Phase</th><th>From</th><th>To</th><th>Start price</th>'
            '<th>End price</th><th>Months</th><th>Change</th><th>Notes</th></tr></thead><tbody>']
    for p in reversed(r['phases']):
        cls = 'up' if p['kind'] == 'bull' else 'down'
        rows.append(f'<tr><td class="lab">{p["kind"].title()}</td><td>{day(p["start"])}</td>'
                    f'<td>{day(p["end"])}</td><td>{px(p["start_price"])}</td>'
                    f'<td>{px(p["end_price"])}</td><td>{p["months"]:.1f}</td>'
                    f'<td class="val {cls}">{pct(p["change"])}</td><td>{tag(p)}</td></tr>')
    rows.append('</tbody></table>')
    sub = ('Most recent first. A bear phase is marked market-wide when the S&amp;P 500 also '
           f'fell at least {int(cy.MARKET_FALL * 100)}% inside it, and stock-specific when it '
           'did not.' if r['bench_ok'] else 'Most recent first. The S&amp;P 500 did not load, '
           'so bear phases are not tagged as market-wide or stock-specific.')
    return card('Every completed phase', ''.join(rows), sub)


def holdings_card(r):
    if not r['holdings']:
        return card('Every holding period', '<div class="body-text">None completed yet.</div>')
    rows = ['<table class="nw"><thead><tr><th>In on</th><th>At</th><th>Out on</th><th>At</th>'
            '<th>Months</th><th>Price return</th><th>With dividends</th><th>Notes</th>'
            '</tr></thead><tbody>']
    for h in reversed(r['holdings']):
        cls = 'up' if h['total_return'] > 0 else 'down'
        note = '<span class="pill a">extreme</span>' if h['extreme'] else ''
        rows.append(f'<tr><td class="lab">{day(h["entry_date"])}</td><td>{px(h["entry"])}</td>'
                    f'<td>{day(h["exit_date"])}</td><td>{px(h["exit"])}</td>'
                    f'<td>{h["months"]:.1f}</td><td>{pct(h["price_return"])}</td>'
                    f'<td class="val {cls}">{pct(h["total_return"])}</td><td>{note}</td></tr>')
    rows.append('</tbody></table>')
    sub = ('In on the close that confirmed a bull phase, out on the close that confirmed the '
           'next bear phase. Dividends are counted as cash received, not reinvested.'
           + ('' if r['has_dividends'] else ' Yahoo shows no dividends for this stock, so both '
              'return columns are the same.'))
    return card('Every holding period', ''.join(rows), sub)


# ---------------------------------------------------------------- definitions, limits ----
DEFINITIONS = [
    ('Threshold', 'The size of move this stock needs to change phase.',
     'Its median annual volatility across each year of history, kept between 15% and 35%.'),
    ('Peak', 'The high of a bull phase. Only known in hindsight.',
     'The highest close before a fall of at least the threshold.'),
    ('Trough', 'The low of a bear phase. Only known in hindsight.',
     'The lowest close before a rise of at least the threshold.'),
    ('Confirmation date', 'The day a phase change became certain.',
     'The first close at least the threshold beyond the last peak or trough.'),
    ('Trigger', 'The close that would end the current phase.',
     'In a bull phase, the highest close since the trough times one minus the threshold. '
     'In a bear phase, the lowest close since the peak times one plus the threshold.'),
    ('Bull / bear phase length', 'How long a phase lasted.',
     'Months from trough to peak, or from peak to trough.'),
    ('Holding period', 'How long someone following the rule would actually have held.',
     'Months from the close that confirmed a bull phase to the close that confirmed the next '
     'bear phase.'),
    ('Captured return', 'What that holder would actually have earned.',
     'From the entry close to the exit close, plus dividends paid in between, not reinvested.'),
    ('Support / resistance zone', 'A band where past turns cluster.',
     'Peaks and troughs no more than 4% apart, grouped. Support is the nearest zone below the '
     'latest close, resistance the nearest above.'),
    ('Held / broke', 'How a zone has behaved.',
     'Held counts each turning point inside the zone. Broke counts each later phase that ran '
     'from one side of the zone to the other without turning in it.'),
    ('Extreme phase', 'A phase unlike the stock\'s normal behaviour.',
     'Length or size more than 3.5 robust standard deviations from the median for that kind of '
     'phase. Only judged once there are at least five phases of that kind.'),
    ('Median and middle half', 'The typical value and the usual spread.',
     'The middle value, and the range from the 25th to the 75th percentile.'),
]

LIMITATIONS = [
    ('This describes the past. It does not forecast.',
     'The figures show how this stock behaved in earlier cycles. They do not say when the '
     'current phase will end or how far it will go. A typical length is not a countdown: a '
     'phase that has run half its typical length does not have the other half still to come.'),
    ('Turning points are only known late.',
     'A peak is confirmed only after the price has fallen by the full threshold from it, and a '
     'trough only after the price has risen by the full threshold. That is deliberate: it stops '
     'every dip being called a turn. It also means the current phase can end on any day, and '
     'the page will only show it once the trigger is crossed.'),
    ('The holding figures are lower than trough to peak, and they are the honest ones.',
     'Nobody buys at the exact low or sells at the exact high. The holding period and the '
     'captured return assume buying on the close that confirmed the bull phase and selling on '
     'the close that confirmed the next bear phase, which is what following this rule would '
     'actually have delivered. For a stock that moves sideways, that can be a loss.'),
    ('A few cycles make a weak average.',
     'The number of cycles sits next to every median. With fewer than five, treat the figures '
     'as a description of this stock\'s history rather than a pattern to rely on.'),
    ('Leaving out extremes makes the history look calmer than it felt.',
     'The right-hand columns show normal behaviour. A holder would have lived through the '
     'extreme phases too, which is why both sets of figures are shown and every phase stays in '
     'the history table.'),
    ('Support and resistance are tendencies, not floors or ceilings.',
     'They mark prices where the stock has turned before. Each zone shows how often it held and '
     'how often a later move went straight through it.'),
    ('Price is the only input.',
     'Earnings, valuation, debt and changes in the business are not part of this. After a '
     'merger, a new line of business or a collapse in its industry, past cycles may stop being '
     'a useful guide. The deep analysis page covers the business itself.'),
    ('The threshold is a choice.',
     'A smaller threshold finds more and shorter cycles, a larger one fewer and longer ones. '
     'Setting it from the stock\'s own volatility puts every stock on its own scale, but a '
     'different setting would date some turns differently.'),
    ('The data has limits.',
     'Daily closes from Yahoo, in the listing currency. Levels are traded prices adjusted for '
     'splits. Intraday highs and lows, trading costs, taxes and currency moves for an investor '
     'outside the listing market are not included. Nothing before Yahoo\'s history begins is '
     'covered.'),
]


def definitions_card():
    rows = ['<table><thead><tr><th>Term</th><th style="text-align:left">What it means</th>'
            '<th style="text-align:left">How it is calculated</th></tr></thead><tbody>']
    for term, meaning, how in DEFINITIONS:
        rows.append(f'<tr><td class="lab"><b>{esc(term)}</b></td>'
                    f'<td style="text-align:left">{esc(meaning)}</td>'
                    f'<td style="text-align:left">{esc(how)}</td></tr>')
    rows.append('</tbody></table>')
    return card('What each figure means', ''.join(rows),
                'Every figure on this page uses exactly these definitions.')


def limitations_card():
    body = ''.join(f'<div class="body-text"><b>{esc(t)}</b> {esc(x)}</div>' for t, x in LIMITATIONS)
    return card('Limitations', body, 'Read these before using any figure on this page.')


# ---------------------------------------------------------------- the page ---------------
# Rules for this page only, all scoped to .cy so the company page is untouched.
# Streamlit draws its own border round every table cell inside markdown and the shared
# stylesheet gives cells no side padding, which ran the columns into each other. Cells get
# room on both sides and only the horizontal rules stay. Tables of figures keep each value on
# one line; only the measure names wrap.
CY_CSS = """<style>
.an.cy table{border:none}
.an.cy th,.an.cy td{padding:9px 10px;border-left:none;border-right:none;border-top:none}
.an.cy th:first-child,.an.cy td:first-child{padding-left:0}
.an.cy th:last-child,.an.cy td:last-child{padding-right:0}
.an.cy .grid{margin-top:12px}
.an.cy .full{margin-top:12px}
.an.cy .full>.card{overflow-x:auto}
.an.cy .nw th,.an.cy .nw td{white-space:nowrap}
.an.cy .nw td.lab{white-space:normal}
.an.cy .cylab{position:absolute;left:6px;transform:translateY(-50%);font-size:10px;
font-weight:700;background:#fff;border:1px solid;border-radius:3px;padding:1px 6px;
pointer-events:none;white-space:nowrap}
</style>"""

def build(r, name, ticker, exchange, ccy, isin, company_query):
    """company_query is the ticker, ISIN and currency part of the link, so the back link
    returns to the same company's deep analysis."""
    cur = r['current']
    bits = [b for b in [ticker, exchange, isin, ccy and f'Prices in {ccy}'] if b]
    meta = '<span class="sep">/</span>'.join(
        (f'<b>{esc(b)}</b>' if i == 0 else esc(b)) for i, b in enumerate(bits))
    state = {'bull': ('Bull phase', 'up'), 'bear': ('Bear phase', 'down')}.get(
        cur.get('state'), ('No phase yet', ''))
    # the company page stretches its cards so both columns end level; here the rail is much
    # shorter than the tables, and stretching left large empty cards, so cards keep their size
    H = [CSS, CY_CSS, '<div class="an cy">',
         f'<div class="printhead"><span>MICS International, internal research</span>'
         f'<span>Prices to {day(r["last_date"])}</span></div>',
         f'<div class="mast"><div><div class="eyebrow">Stock cycle, prices to '
         f'{day(r["last_date"])}</div><h1>{esc(name)}</h1><div class="meta">{meta}</div></div>'
         f'<div class="quote"><div class="eyebrow">'
         f'<a class="back" href="?{company_query}" target="_self">Full deep analysis</a>'
         f'<span class="sep" style="margin:0 8px">/</span>'
         f'<a class="back" href="?view=cycle" target="_self">Cycle search</a></div>'
         f'<div class="eyebrow" style="margin-top:6px">Latest close</div>'
         f'<div class="px num">{px(cur["last_price"])}<span>{esc(ccy or "")}</span></div>'
         f'<div class="chg {state[1]}">{state[0]}</div></div></div>',
         f'<div class="read" style="margin-top:12px">{reading(r)}</div>',
         '<div class="grid"><div>', chart_card(r), '</div><div>', now_card(r), '</div></div>',
         '<div class="grid"><div>', typical_card(r), '</div><div>', levels_card(r),
         rule_card(r), '</div></div>',
         '<div class="full">', history_card(r), holdings_card(r), '</div>',
         definitions_card(), limitations_card(),
         '<div class="disc"><b>MICS International internal research.</b> This page describes '
         'how a share price has moved. It is not a recommendation to buy, hold or sell, and '
         'past cycles do not guarantee future ones.</div></div>']
    return ''.join(H)
