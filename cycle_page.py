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
import stages as sg
from page import CSS, DOWN, NAVY, UP, GOLD, HOVER_BAND_UNITS, esc, f, minus

SUPPORT_FILL, RESIST_FILL, BEAR_FILL = '#bfe3cc', '#f4c4bf', '#eef2f8'
EMA_LINE = '#c47a1f'
STAGE_FILL = {1: '#cfdcee', 2: '#9fd4b2', 3: '#f1d39a', 4: '#efaaa3'}
STRIP = 9


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
TREND_LINE = '#3f6aa8'
# the ranges the chart offers, in trading days, as on the company page plus one month
SPANS = {'1M': 21, '3M': 63, '6M': 126, '1Y': 252, '2Y': 504, '5Y': 1260, '10Y': 2520,
         'Max': None}
DEFAULT_SPAN = '1Y'
# a level further than this beyond the prices in view is pinned to the edge of the chart
# as a label, instead of stretching the scale until the price line goes flat
ZOOM = 1.25


def svg_cycle(close, points, current, phases, zones, lines=(), stage_eps=(), stage_daily=None,
              marks=(), width=720, height=290):
    """Price on a log scale, so a 30% fall looks the same size at 10 as at 1,000.

    Past turning points are marked, the nearest support and resistance zones drawn as
    bands, the two stage triggers as dotted lines from the start of the current stage, and
    the stage of every week as a strip along the bottom. Dates run evenly across the width,
    so the markers and the line share one time axis.
    """
    s = rk.thin_series(close)
    t0, t1 = s.index[0], s.index[-1]
    span_t = max(1, (t1 - t0).days)
    levels = [float(v) for v in s.values]
    pmin, pmax = min(levels), max(levels)

    def near(v):
        return pmin / ZOOM <= v <= pmax * ZOOM
    zones = [zz for zz in zones if near(zz[0]['low']) or near(zz[0]['high'])]
    pinned = [m for m in marks if not near(m[1])]
    marks = [m for m in marks if near(m[1])]
    extra = [z['low'] for z, _, _ in zones] + [z['high'] for z, _, _ in zones]
    extra += [m[1] for m in marks]
    lo = math.log(min(levels + extra))
    hi = math.log(max(levels + extra))
    rng = (hi - lo) or 1
    top, bot = 8, 8 + (STRIP + 4 if stage_eps else 0)
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

    for series, colour, dash in lines:
        if series is None:
            continue
        avg = series.reindex(s.index).dropna()
        avg = avg[(avg > math.exp(lo)) & (avg < math.exp(hi))]
        if len(avg) > 1:
            ap = ' '.join(f'{x(t):.1f},{y(float(v)):.1f}' for t, v in avg.items())
            parts.append(f'<polyline fill="none" stroke="{colour}" stroke-width="1.4" '
                         + (f'stroke-dasharray="{dash}" ' if dash else '') + f'points="{ap}"/>')

    # the two stage triggers, from the start of the current stage on
    for start, level, colour, label in marks:
        xa = x(max(pd.Timestamp(start), t0))
        parts.append(f'<line x1="{xa:.1f}" x2="{width:.1f}" y1="{y(level):.1f}" '
                     f'y2="{y(level):.1f}" stroke="{colour}" stroke-width="1.8" '
                     f'stroke-dasharray="2,3"><title>{esc(label)}</title></line>')

    # the stage of every week, as a strip along the bottom
    for e in stage_eps:
        a, b = e['start'] - pd.Timedelta(days=6), e['end']
        if b < t0 or a > t1:
            continue
        xa, xb = x(max(a, t0)), x(min(b, t1))
        parts.append(f'<rect x="{xa:.1f}" y="{height - STRIP}" width="{max(1, xb - xa):.1f}" '
                     f'height="{STRIP}" fill="{STAGE_FILL[e["stage"]]}"><title>Stage '
                     f'{e["stage"]}, {sg.NAMES[e["stage"]]}: {day(e["start"])} to '
                     f'{day(e["end"])}</title></rect>')

    pts = ' '.join(f'{x(t):.1f},{y(v):.1f}' for t, v in zip(s.index, levels))
    parts.append(f'<polyline fill="none" stroke="{NAVY}" stroke-width="1.8" points="{pts}"/>')

    for p in points:
        if p['date'] < t0:
            continue
        cx, cyy = x(p['date']), y(p['price'])
        if p['kind'] == 'peak':
            tri = f'{cx - 5:.1f},{cyy - 9:.1f} {cx + 5:.1f},{cyy - 9:.1f} {cx:.1f},{cyy - 2:.1f}'
            colour, word = DOWN, 'Turning high'
        else:
            tri = f'{cx - 5:.1f},{cyy + 9:.1f} {cx + 5:.1f},{cyy + 9:.1f} {cx:.1f},{cyy + 2:.1f}'
            colour, word = UP, 'Turning low'
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
        lines_ = [day(idx[i]), f'Close {px(v)}']
        if stage_daily is not None:
            stv = stage_daily.get(idx[i])
            if stv is not None and not (isinstance(stv, float) and math.isnan(stv)):
                lines_.append(f'Stage {int(stv)}, {sg.NAMES[int(stv)]}')
        box_w, box_h = 150, 16 + 13 * len(lines_)
        bx = round(cx + 10 if cx < width - box_w - 14 else cx - box_w - 10, 1)
        by = round(min(max(4, cyy - box_h / 2), height - box_h - 4), 1)
        text = ''.join(f'<text x="{bx + 9}" y="{by + 17 + 13 * k}" font-size="10.5" '
                       f'font-weight="{700 if k == 0 else 500}" fill="#1a1a1a">{esc(t)}</text>'
                       for k, t in enumerate(lines_))
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
    fmt = '%Y' if span_t > 365 * 8 else '%b %Y' if span_t > 120 else '%d %b'
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
    for _, level, colour, label in marks:
        top_pct = max(0.0, min(100.0, y(level) / height * 100))
        tags += (f'<span class="cylab" title="{esc(label)}" style="top:{top_pct:.2f}%;'
                 f'color:{colour};border-color:{colour};left:auto;right:58px">{px(level)}</span>')
    for _, level, colour, label in pinned:
        above = level > pmax
        tags += (f'<span class="cylab" title="{esc(label)}, outside this range" '
                 f'style="top:{2 if above else 96}%;color:{colour};border-color:{colour};'
                 f'left:auto;right:58px">{"&#8593;" if above else "&#8595;"} {px(level)}</span>')
    return (f'<div class="plot"><div class="yaxis">{yaxis}</div>{"".join(parts)}{tags}</div>'
            f'<div class="xaxis">{"".join(dates)}</div>')


LEGEND = (f'<div class="clegend">'
          f'<span><i style="background:{NAVY};height:3px"></i>Close, log scale</span>'
          f'<span><i style="background:{EMA_LINE};height:2px"></i>50-day EMA</span>'
          f'<span><i style="background:repeating-linear-gradient(90deg,{TREND_LINE} 0 4px,'
          f'transparent 4px 7px)"></i>30-week average (stage line)</span>'
          + ''.join(f'<span><i style="background:{STAGE_FILL[k]};height:10px"></i>Stage {k}, '
                    f'{sg.NAMES[k]}</span>' for k in (1, 2, 3, 4)) +
          f'<span><b style="color:{DOWN}">&#9660;</b>Past turning high</span>'
          f'<span><b style="color:{UP}">&#9650;</b>Past turning low</span>'
          f'<span><i style="background:{SUPPORT_FILL};height:10px;border-top:2px solid {UP}">'
          f'</i>Nearest support</span>'
          f'<span><i style="background:{RESIST_FILL};height:10px;border-bottom:2px solid {DOWN}">'
          f'</i>Nearest resistance</span></div>')


def chart_lines(r):
    sgr = r.get('stage') or {}
    if sgr.get('error') or not sgr:
        return ()
    return ((sgr['short']['ema'], EMA_LINE, None), (sgr['ma_daily'], TREND_LINE, '4,3'))


def stage_triggers(r):
    sgr = r.get('stage') or {}
    if not sgr or sgr.get('error'):
        return {'up': None, 'down': None}
    return sgr['current']['triggers']


def trigger_label(g, side):
    arrow = '&#9650;' if side == 'up' else '&#9660;'
    return f'{arrow} {g["name"]}: {px(g["level"])}'


def trigger_marks(r):
    sgr = r.get('stage') or {}
    if not sgr or sgr.get('error'):
        return ()
    start = sgr['current']['start']
    out = []
    for side, colour in (('up', UP), ('down', DOWN)):
        g = sgr['current']['triggers'][side]
        if g:
            plain_label = (f'{"Up" if side == "up" else "Down"} to {g["name"]}: '
                           f'{"above" if side == "up" else "below"} {px(g["level"])}')
            out.append((start, g['level'], colour, plain_label))
    return tuple(out)


def trigger_legend(r):
    trig = stage_triggers(r)
    spans = []
    for side, colour in (('up', UP), ('down', DOWN)):
        g = trig[side]
        if g:
            spans.append(f'<span><i style="background:repeating-linear-gradient(90deg,{colour} 0 '
                         f'2px,transparent 2px 5px);height:2px"></i>{trigger_label(g, side)}'
                         f'{", moves weekly" if g["moves"] else ""}</span>')
    if not spans:
        return ''
    return ('<div class="clegend"><span><b>Stage triggers</b>, 2 weekly closes beyond</span>'
            + ''.join(spans) + '</div>')


def stage_eps(r):
    sgr = r.get('stage') or {}
    return () if sgr.get('error') or not sgr else sgr['episodes']


def stage_daily(r):
    sgr = r.get('stage') or {}
    if sgr.get('error') or not sgr:
        return None
    return sgr['weekly']['stage'].reindex(r['close'].index, method='ffill').to_dict()


def chart_spans(close):
    """Every range the history can fill, shortest first. A range is offered only when there
    is more history than it covers, so no two ranges draw the same chart."""
    out = [(lab, close.tail(n)) for lab, n in SPANS.items() if n is not None and len(close) > n]
    out.append(('Max', close))
    return out


def chart_card(r):
    """Every range from one month to the full record, all drawn now and switched in the
    browser with the same radio and CSS trick as the company page, so changing the range
    needs no reload."""
    close, cur = r['close'], r['current']
    shown = [(z, fill, edge) for z, fill, edge in ((r['support'], SUPPORT_FILL, UP),
                                                   (r['resistance'], RESIST_FILL, DOWN)) if z]
    ranges = chart_spans(close)
    labels = [lab for lab, _ in ranges]
    current = DEFAULT_SPAN if DEFAULT_SPAN in labels else labels[-1]
    lines, eps, sd, marks = chart_lines(r), stage_eps(r), stage_daily(r), trigger_marks(r)
    tabs, panels = [], []
    for lab, win in ranges:
        on = ' on' if lab == current else ''
        tabs.append(f'<label class="sbtn{on}"><input type="radio" name="cyspan" '
                    f'class="si-{lab}">{lab}</label>')
        panels.append(f'<div class="spanpanel sp-{lab}{on}">'
                      + svg_cycle(win, r['points'], cur, r['phases'], shown, lines, eps, sd,
                                  marks) + '</div>')
    body = (LEGEND + trigger_legend(r) + f'<div class="spanset"><div class="tabs">{"".join(tabs)}</div>'
            f'{"".join(panels)}</div>'
            '<div class="smallnote">Hover over the chart for the date, close and stage, over a '
            'marker for a past turning point, and over the strip along the bottom for each '
            'stage\'s dates. The dotted lines are the two levels that would change the stage; '
            'when one is far outside the range in view, its price is pinned to the top or bottom '
            'edge with an arrow.</div>')
    return card('Price, stages and the two triggers', body,
                f'{day(r["first_date"])} to {day(r["last_date"])}. Traded prices, adjusted '
                f'for splits, not for dividends.')


# ---------------------------------------------------------------- the reading ------------
def compare_basis(r, key):
    """The medians the reading compares against: excluding extremes when any remain."""
    clean, everything = r['clean'][key], r['all'][key]
    if clean['n']:
        return clean, r['extremes']
    return everything, 0


def headline(r):
    """The stage in one line, for the top of the page and the exports."""
    sgr = r.get('stage') or {}
    if sgr.get('error') or not sgr:
        return None
    return sgr['current']['label']


def stage_reading(r):
    sgr = r.get('stage') or {}
    if sgr.get('error') or not sgr:
        return (f'<b>No stage yet.</b> {esc((sgr or {}).get("error", ""))}' if sgr else '')
    o = r['outlook']
    first, rest = o['now'][0], o['now'][1:]
    head, _, meaning = first.partition('. ')
    return f'<b>{esc(head)}.</b> {esc(meaning)} ' + ' '.join(esc(x) for x in rest)


def reading(r):
    return stage_reading(r)


# ---------------------------------------------------------------- rail -------------------
def trend_text(tr):
    if not tr:
        return 'n/a'
    side = 'above' if tr['above'] else 'below'
    word = {'up': 'Up', 'down': 'Down', 'mixed': 'Mixed'}[tr['direction']]
    return f'{word}, {pct(abs(tr["gap"]), False)} {side} a {tr["slope_dir"]} average'


def trust_card(r):
    """How much weight the reading can bear, and every problem found in the data."""
    conf = r['confidence']
    rows = [kv('Confidence', conf['level'])]
    if conf['reasons']:
        rows.append('<div class="body-text">' + '</div><div class="body-text">'.join(
            esc(x[0].upper() + x[1:]).rstrip('.') + '.' for x in conf['reasons']) + '</div>')
    else:
        rows.append('<div class="body-text">The data passed every check, there is enough stage '
                    'history to learn from, no breakout is being tested and the price is not '
                    'close to either trigger.</div>')
    note = ('High means the data is clean and the reading is settled. Medium means the reading '
            'is sound but thin or unsettled. Low means the data itself may be wrong; check the '
            'price history before using any figure.')
    return card('How much to trust this reading', ''.join(rows)
                + f'<div class="cnote">{note}</div>')


def now_card(r):
    """The stage and the short-term picture, the part that moves week to week."""
    sgr = r.get('stage') or {}
    rows = [kv('Confidence', r['confidence']['level'], 'see the card below')]
    if sgr and not sgr.get('error'):
        c, sh = sgr['current'], sgr['short']
        slope = ('rising' if c['slope'] > c['band'] else 'falling' if c['slope'] < -c['band']
                 else 'flat')
        rows = [kv('Stage', c['label'].replace('Stage ', ''),
                   f'since week of {day(c["start"])}'),
                kv('Weeks in this stage', str(c['weeks'])),
                kv('Last finished week', px(c['close']), day(c['week'])),
                kv('30-week average', px(c['ma']), f'{slope}, {pct(c["slope"])} in 5 weeks'),
                kv('Price vs 30-week average', pct(-c['to_ma'] / (1 + c['to_ma']))),
                kv('50-day EMA', px(sh['ema_level']),
                   f'price {"above" if sh["above_ema"] else "below"} it')]
        if sh.get('sma_level') is not None:
            cross = ''
            if sh.get('cross_date') is not None:
                cross = (f'{"golden" if sh["cross_kind"] == "golden" else "death"} cross on '
                         f'{day(sh["cross_date"])}')
            rows.append(kv('50-day EMA vs 200-day', 'above' if sh['ema_over_sma'] else 'below',
                           cross))
        for side in ('up', 'down'):
            g = c['triggers'][side]
            arrow = '&#9650;' if side == 'up' else '&#9660;'
            if g:
                rows.append(kv(f'{arrow} Turns to {g["name"]}', px(g['level']),
                               f'{pct(g["distance"])} away'
                               + (', moves weekly' if g['moves'] else '')))
            else:
                rows.append(kv(f'{arrow} {"Upside" if side == "up" else "Downside"}', 'no change',
                               'the stage would only continue'))
        t = c.get('testing')
        if t:
            word = 'Breakout' if t['dir'] == 'up' else 'Breakdown'
            rows.append(kv(f'{word} being tested', px(t['pivot']),
                           f'proven {"above" if t["dir"] == "up" else "below"} '
                           f'{px(t["proof"])} or on {day(t["deadline"])}'))
        rows += [kv('From 52-week high', pct(sh['from_high52']), px(sh['high52'])),
                 kv('From 52-week low', pct(sh['from_low52']), px(sh['low52']))]
        run = c.get('running')
        if run and run['raw']:
            rows.append(kv('This week so far', run['raw'], f'{px(run["close"])} on '
                                                           f'{day(run["date"])}'))
        rows.append(kv('Confidence', r['confidence']['level'], 'see the card below'))
    else:
        rows.insert(0, kv('Stage', 'n/a', (sgr or {}).get('error', '')))
    note = ('The stage is read on finished weeks only. Each trigger needs two weekly closes in '
            'a row beyond its level, so one odd week cannot flip it. The 50-day EMA is an early '
            'warning, not a trigger.')
    return card('Where the stock is now', ''.join(rows) + f'<div class="cnote">{note}</div>')


def outlook_card(r):
    """What usually came next for this stock, and the levels that would change the stage."""
    o = r.get('outlook')
    if not o:
        return ''
    def block(title, items):
        if not items:
            return ''
        return (f'<div class="body-text" style="margin-top:8px"><b>{esc(title)}</b></div>'
                + ''.join(f'<div class="body-text">{esc(x)}</div>' for x in items))
    body = (block('What came next before', o['next'])
            + block('What would turn it up', o['up'])
            + block('What would turn it down', o['down']))
    note = ' '.join(o['caveat'])
    return card('What usually comes next, and what to watch', body
                + f'<div class="cnote">{esc(note)}</div>',
                'Built only from this stock\'s own past stages and today\'s levels.')


def stage_card(r):
    """Every past stage and how each kind usually behaved."""
    sgr = r.get('stage') or {}
    if not sgr or sgr.get('error'):
        return ''
    st = sgr['stats']
    rows = ['<table class="nw"><thead><tr><th>Stage</th><th>Past runs</th><th>Median weeks</th>'
            '<th>Middle half</th><th>Went next to</th><th>Higher 13 weeks on</th>'
            '<th>Median 13 weeks on</th><th>Higher 26 weeks on</th><th>Median 26 weeks on</th>'
            '</tr></thead><tbody>']
    for k in (1, 2, 3, 4):
        d = st[k]
        w = d['weeks']
        nxt = ', '.join(f'{j}: {v}' for j, v in sorted(d['next'].items(), key=lambda kv: -kv[1]))
        f13, f26 = d['forward'][13], d['forward'][26]
        rows.append(f'<tr><td class="lab">{k}, {sg.NAMES[k]}</td><td>{d["count"]}</td>'
                    f'<td class="val">{w["median"]:.0f}</td>' if w['n'] else
                    f'<tr><td class="lab">{k}, {sg.NAMES[k]}</td><td>{d["count"]}</td>'
                    f'<td class="val">n/a</td>')
        rows.append((f'<td>{w["p25"]:.0f} to {w["p75"]:.0f}</td>' if w['n'] else '<td>n/a</td>')
                    + f'<td>{nxt or "n/a"}</td>'
                    + (f'<td>{f13["up"]} of {f13["n"]}</td><td>{pct(f13["median"])}</td>'
                       if f13['n'] else '<td>n/a</td><td>n/a</td>')
                    + (f'<td>{f26["up"]} of {f26["n"]}</td><td>{pct(f26["median"])}</td>'
                       if f26['n'] else '<td>n/a</td><td>n/a</td>') + '</tr>')
    rows.append('</tbody></table>')
    bs = sgr['break_stats']
    lines = []
    for d, word in (('up', 'breakouts'), ('down', 'breakdowns')):
        b = bs[d]
        if b['n']:
            line = (f'{b["n"]} past {word} from a base or top, {b["failed"]} failed '
                    f'({b["failed"] / b["n"] * 100:.0f}%)')
            if b['failed'] and b['fail_weeks']['median'] is not None:
                line += f', a median of {b["fail_weeks"]["median"]:.0f} weeks after the move'
            lines.append(line + '.')
    if lines:
        rows.append('<div class="body-text" style="margin-top:12px">' + ' '.join(lines) + '</div>')
    recent = [e for e in sgr['episodes'] if not e['first']][::-1][:12]
    rows.append('<table class="nw" style="margin-top:14px"><thead><tr><th>Stage</th>'
                '<th>From week of</th><th>To week of</th><th>Weeks</th><th>Start</th>'
                '<th>End</th><th>Change</th><th>How it began</th></tr></thead><tbody>')
    for e in recent:
        ch = e['end_price'] / e['start_price'] - 1
        cls = 'up' if ch > 0 else 'down'
        rows.append(f'<tr><td class="lab">{e["stage"]}, {sg.NAMES[e["stage"]]}'
                    f'{" (open)" if e["open"] else ""}</td><td>{day(e["start"])}</td>'
                    f'<td>{day(e["end"])}</td><td>{e["weeks"]}</td><td>{px(e["start_price"])}</td>'
                    f'<td>{px(e["end_price"])}</td><td class="val {cls}">{pct(ch)}</td>'
                    f'<td>{esc(e.get("note") or "")}</td></tr>')
    rows.append('</tbody></table>')
    return card('Every stage this stock has been through', ''.join(rows),
                'Top table: how each stage usually behaved for this stock, counted from the '
                'week it began. "Went next to" counts which stage followed. Bottom table: the '
                'latest twelve stages, most recent first. The first stage in the record is left '
                'out because its start is only where the data begins.')


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
            'time the price turned inside it, and broke each time a later major move ran straight '
            'through it. These are levels where the price has turned before, not floors or '
            'ceilings.')
    return card('Support and resistance', ''.join(rows) + f'<div class="cnote">{note}</div>')


def rule_card(r):
    years = (r['last_date'] - r['first_date']).days / 365.25
    vol = r['vol']
    if vol is None:
        how = 'fixed for this run'
    else:
        yrs = r.get('threshold_years') or cy.THRESHOLD_YEARS
        base = f'volatility of {pct(vol, False)} over the last {yrs} year{"s" if yrs != 1 else ""}'
        if r['threshold'] >= cy.THRESHOLD_CAP - 1e-9 and vol * cy.THRESHOLD_MULT > cy.THRESHOLD_CAP:
            how = f'{base}, capped at {cy.THRESHOLD_CAP * 100:.0f}%'
        elif r['threshold'] <= cy.THRESHOLD_FLOOR + 1e-9 and vol * cy.THRESHOLD_MULT < cy.THRESHOLD_FLOOR:
            how = f'{base}, raised to the {cy.THRESHOLD_FLOOR * 100:.0f}% floor'
        else:
            how = base
    done = len(r['phases'])
    return card('How past major moves are found',
                kv('Rise size', pct(r['threshold'], False), how)
                + kv('Fall size', pct(r['fall'], False), 'the same move in log terms')
                + kv('History used', f'{years:.1f} years', f'from {day(r["first_date"])}')
                + kv('Confirmed turning points', str(len(r['points'])))
                + kv('Completed major moves', str(done),
                     f'{r["extremes"]} extreme' if r['extremes'] else 'none extreme'))


# ---------------------------------------------------------------- main column ------------
def typical_card(r):
    a, c = r['all'], r['clean']
    rows = [('Major rise length', 'bull_months', 'months', 'turning low to turning high'),
            ('Major rise gain', 'bull_change', 'pct', 'low to high, price only'),
            ('Major fall length', 'bear_months', 'months', 'turning high to turning low'),
            ('Major fall size', 'bear_change', 'pct', 'high to low, price only'),
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
        notes.append(f'{r["extremes"]} move{"s are" if r["extremes"] != 1 else " is"} '
                     f'marked extreme and left out of the right-hand columns. They are still '
                     f'shown in the history below.')
    else:
        notes.append('No move was far enough from the rest to count as extreme, so both '
                     'sets of columns match.' if a['bull_months']['n'] >= cy.MIN_CYCLES else
                     'Extremes are only judged once a stock has at least five completed '
                     'major moves of a kind, so nothing has been excluded.')
    if c['hold_total']['n'] and c['bull_change']['n']:
        notes.append(f'The median captured return of {pct(c["hold_total"]["median"])} compares '
                     f'with a median low to high gain of {pct(c["bull_change"]["median"])}. '
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
        return card('Every past major move', '<div class="body-text">None yet. A major move is '
                    'complete once the turn that ends it has been confirmed.</div>')
    rows = ['<table class="nw"><thead><tr><th>Move</th><th>From</th><th>To</th><th>Start price</th>'
            '<th>End price</th><th>Months</th><th>Change</th><th>Notes</th></tr></thead><tbody>']
    for p in reversed(r['phases']):
        cls = 'up' if p['kind'] == 'bull' else 'down'
        rows.append(f'<tr><td class="lab">{"Rise" if p["kind"] == "bull" else "Fall"}</td><td>{day(p["start"])}</td>'
                    f'<td>{day(p["end"])}</td><td>{px(p["start_price"])}</td>'
                    f'<td>{px(p["end_price"])}</td><td>{p["months"]:.1f}</td>'
                    f'<td class="val {cls}">{pct(p["change"])}</td><td>{tag(p)}</td></tr>')
    rows.append('</tbody></table>')
    bn = esc(r.get('bench_name') or 'S&P 500')
    sub = (f'Most recent first. A fall is marked market-wide when the {bn}, this '
           f'listing\'s own market, also fell at least {int(cy.MARKET_FALL * 100)}% inside it, '
           'and stock-specific when it did not.' if r['bench_ok'] else
           f'Most recent first. The {bn} did not load, so falls are not tagged as '
           'market-wide or stock-specific.')
    return card('Every past major move', ''.join(rows), sub)


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
    sub = ('In on the close that confirmed a major rise, out on the close that confirmed the '
           'next major fall. Dividends are counted as cash received, not reinvested.'
           + ('' if r['has_dividends'] else ' Yahoo shows no dividends for this stock, so both '
              'return columns are the same.'))
    return card('Every holding period', ''.join(rows), sub)


# ---------------------------------------------------------------- definitions, limits ----
DEFINITIONS = [
    ('Stage', 'Where the stock is now: 1 Basing, 2 Advancing, 3 Topping, 4 Declining.',
     'Read each finished week against the 30-week average. A week reads up when the close is '
     'above a rising average, down when below a falling one, neutral otherwise. The stage '
     'changes after two weeks in a row point the same way: from 2, weeks that stop reading up '
     'give 3 (or 4 if both read down); from 4, weeks that stop reading down give 1 (or 2 if '
     'both read up); from 1 or 3, two up weeks give 2 and two down weeks give 4, but only once '
     'the close also breaks out of that base or top: above its highest weekly close, or below '
     'its lowest, counting the 13 weeks before it began.'),
    ('Stage triggers', 'The two levels that would change the stage, one up and one down.',
     'The nearest stage-changing level on each side of the price, with the stage it leads to. '
     'In a base or top: its top and bottom. In Stage 2 or 4: the 30-week average (which moves '
     'weekly), or, while a breakout is being tested, the level that would fail it. Each needs '
     'two weekly closes in a row beyond it. Stage 2 has no upside trigger and Stage 4 no '
     'downside one, because those moves only continue the stage.'),
    ('Breakout and its test', 'A move out of a base or top, checked before it is trusted.',
     'When Stage 1 or 3 turns into Stage 2 or 4, the edge of the range it left is the '
     'breakout level. The move is proven by a weekly close one range-height beyond that level, '
     'or by holding for 13 weeks. Before that, two weekly closes back through the level, less '
     'a buffer of the stock\'s own volatility, send it back to the stage it came from as a '
     'failed breakout or breakdown, with the old range kept. While a move is being tested, a '
     'pause does not count as a new top or base.'),
    ('30-week average', 'The stage line.',
     'The average of the last 30 weekly closes. It counts as flat while its five-week change '
     'is smaller than a quarter of the stock\'s own five-week volatility, and never less than '
     '0.5%.'),
    ('50-day EMA', 'The short-term trend. An early warning, not a trigger.',
     'Exponential average of daily closes with a span of 50 days.'),
    ('Golden / death cross', 'The 50-day EMA crossing the 200-day average.',
     'Golden when it crosses above, death when it crosses below. Shown with the date of the '
     'latest one.'),
    ('What came next', 'How this stock\'s past stages ended and what the price did after.',
     'For every past stage of the same kind: which stage followed, and the price 13 and 26 '
     'weeks after the stage began, with the number of cases.'),
    ('Confidence', 'How much weight the stage reading can bear.',
     'Low if any data check failed. Medium if the stage history is thin, a breakout is being '
     'tested, the price is within 5% of a trigger, or this week reads differently from the '
     'last finished week. High otherwise.'),
    ('Past major move', 'A large rise or fall in the history, used for the cycle figures below.',
     'A rise ends at the highest close before a fall of at least the fall size; a fall ends at '
     'the lowest close before a rise of at least the rise size. These date the past only. '
     'They are not a reading of today.'),
    ('Move sizes', 'How large a move has to be to count as a major one.',
     'The rise size is the median annual volatility over each of the last five years, kept '
     'between 15% and 35%. The fall size is the same move in log terms, rise / (1 + rise), so '
     'a 35% rise pairs with a 25.9% fall.'),
    ('Turning high / low', 'The top of a major rise or the bottom of a major fall.',
     'Known only in hindsight, once the next major move is confirmed.'),
    ('Major rise / fall length', 'How long a past major move lasted.',
     'Months from turning low to turning high, or from high to low.'),
    ('Holding period', 'How long someone buying and selling on confirmed turns would have held.',
     'Months from the close that confirmed a major rise to the close that confirmed the next '
     'major fall.'),
    ('Captured return', 'What that holder would actually have earned.',
     'From the entry close to the exit close, plus dividends paid in between, not reinvested.'),
    ('Support / resistance zone', 'A band where past turns cluster.',
     'Turning highs and lows no more than 4% apart, grouped. Support is the nearest zone below '
     'the latest close, resistance the nearest above.'),
    ('Held / broke', 'How a zone has behaved.',
     'Held counts each turning point inside the zone. Broke counts each later major move that '
     'ran from one side of the zone to the other without turning in it.'),
    ('Extreme move', 'A major move unlike the stock\'s normal behaviour.',
     'Length or size more than 3.5 robust standard deviations from the median for that kind of '
     'move. Only judged once there are at least five of that kind.'),
    ('Median and middle half', 'The typical value and the usual spread.',
     'The middle value, and the range from the 25th to the 75th percentile.'),
]

LIMITATIONS = [
    ('The stage says where the stock is, not where it is going.',
     'Stages tend to follow each other in order, 1 to 2 to 3 to 4, but not always and not on a '
     'schedule. "What usually comes next" counts what this stock did before, with the number of '
     'cases. With only a handful of cases, those counts describe the past rather than give '
     'odds.'),
    ('A trigger is a level to watch, not a prediction.',
     'Crossing it changes the stage; not crossing it says nothing about which way the price '
     'will go. A trigger on the 30-week average moves a little every week, so check the '
     'current level rather than an old one.'),
    ('A failed breakout is only clear afterwards.',
     'For up to 13 weeks after a breakout the downside trigger is the level that would fail '
     'it. Many breakouts dip back towards the breakout level and then go on; the buffer and '
     'the two-week rule are there so a brief dip does not count, but a deeper or longer one '
     'will.'),
    ('The stage changes after the move has started.',
     'It waits for two finished weeks in a row, so the first part of any new move happens '
     'before the stage changes. The 50-day EMA is shown because it usually turns first.'),
    ('The cycle figures describe the past.',
     'Major moves are dated only in hindsight, once the next one is confirmed, so they say '
     'nothing about today on their own. A typical length is not a countdown.'),
    ('The holding figures are lower than low to high, and they are the honest ones.',
     'Nobody buys at the exact low or sells at the exact high. The holding period and the '
     'captured return assume buying on the close that confirmed a major rise and selling on '
     'the close that confirmed the next major fall. For a stock that moves sideways, that can '
     'be a loss.'),
    ('A few cycles make a weak average.',
     'The number of cases sits next to every median. With fewer than five, treat the figures '
     'as a description of this stock\'s history rather than a pattern to rely on.'),
    ('Leaving out extremes makes the history look calmer than it felt.',
     'The right-hand columns show normal behaviour. A holder would have lived through the '
     'extreme moves too, which is why both sets of figures are shown and every move stays in '
     'the history table.'),
    ('Support and resistance are tendencies, not floors or ceilings.',
     'They mark prices where the stock has turned before. Each zone shows how often it held and '
     'how often a later move went straight through it.'),
    ('Price is the only input.',
     'Earnings, valuation, debt and changes in the business are not part of this. After a '
     'merger, a new line of business or a collapse in its industry, past patterns may stop '
     'being a useful guide. The deep analysis page covers the business itself.'),
    ('The settings are choices.',
     'The 30-week average, the two-week rule, the 13-week test and the move sizes are standard '
     'choices applied the same way to every stock. Different settings would date some turns '
     'and stages differently.'),
    ('The data has limits.',
     'Daily closes from Yahoo, in the listing currency, checked for gaps, frozen prices, '
     'unrecorded splits and stale dates, with any problem shown under the confidence reading. '
     'Levels are traded prices adjusted for splits. Intraday highs and lows, trading costs, '
     'taxes and currency moves for an investor outside the listing market are not included. '
     'Nothing before Yahoo\'s history begins is covered.'),
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
.an .spanset:has(.si-1M:checked) .sp-1M{display:block}
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
    hl = headline(r)
    sgr = r.get('stage') or {}
    if hl:
        tone = sgr['current']['tone']
        state = (hl, tone if tone in ('up', 'down') else '')
    else:
        state = ('No stage yet', '')
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
         '<div class="grid"><div>', chart_card(r), outlook_card(r), '</div><div>', now_card(r),
         trust_card(r), '</div></div>',
         '<div class="full">', stage_card(r), '</div>',
         '<div class="grid"><div>', typical_card(r), '</div><div>', levels_card(r),
         rule_card(r), '</div></div>',
         '<div class="full">', history_card(r), holdings_card(r), '</div>',
         definitions_card(), limitations_card(),
         '<div class="disc"><b>MICS International internal research.</b> This page describes '
         'how a share price has moved. It is not a recommendation to buy, hold or sell, and '
         'past cycles do not guarantee future ones.</div></div>']
    return ''.join(H)
