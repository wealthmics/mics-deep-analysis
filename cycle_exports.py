"""
The stock cycle page as Excel and PowerPoint, in the house style.

    build_xlsx(r, meta) -> bytes
    build_pptx(r, meta) -> bytes

r is what cycle.analyse returned, the same object the page is drawn from, so the page and
both files always carry the same figures. meta holds name, symbol, exchange, ccy and isin.
"""

import datetime

import pandas as pd

import cycle as cy
import cycle_page as cpg
from deck import CW, DOWN, PALE, UP, X0, Book, Deck
from exports import NAVY, plain

PCT = '0.0%;-0.0%'
PRICE = '#,##0.00'


def _p(x):
    return '-' if x is None else f'{x:,.2f}'


def _pc(x, sign=True):
    return cpg.pct(x, sign).replace('\u2212', '-')


def _mo(x):
    return '-' if x is None else f'{x:.1f}'


def stage_rows(r):
    """The stage and the short-term picture, as (measure, value, detail)."""
    sgr = r.get('stage') or {}
    if not sgr or sgr.get('error'):
        return [('Stage', 'n/a', (sgr or {}).get('error', ''))]
    c, sh = sgr['current'], sgr['short']
    slope = ('rising' if c['slope'] > c['band'] else 'falling' if c['slope'] < -c['band']
             else 'flat')
    rows = [('Stage', c['label'].replace('Stage ', ''), f'since week of {cpg.day(c["start"])}'),
            ('Weeks in this stage', str(c['weeks']), ''),
            ('Last finished week', _p(c['close']), cpg.day(c['week'])),
            ('30-week average', _p(c['ma']), f'{slope}, {_pc(c["slope"])} in 5 weeks'),
            ('50-day EMA', _p(sh['ema_level']), f'price {"above" if sh["above_ema"] else "below"} it')]
    if sh.get('sma_level') is not None:
        cross = ''
        if sh.get('cross_date') is not None:
            cross = f'{sh["cross_kind"]} cross on {cpg.day(sh["cross_date"])}'
        rows.append(('50-day EMA vs 200-day', 'above' if sh['ema_over_sma'] else 'below', cross))
    rows += [('From 52-week high', _pc(sh['from_high52']), _p(sh['high52'])),
             ('From 52-week low', _pc(sh['from_low52']), _p(sh['low52']))]
    run = c.get('running')
    if run and run['raw']:
        rows.append(('This week so far', run['raw'], f'{_p(run["close"])} on {cpg.day(run["date"])}'))
    return rows


def confidence_rows(r):
    rows = [('Confidence', r['confidence']['level'], '')]
    for why in r['confidence']['reasons']:
        rows.append(('  reason', '', why))
    return rows


def triggers_of(r):
    sgr = r.get('stage') or {}
    return [] if not sgr or sgr.get('error') else sgr['current']['triggers']


def trigger_colour(g):
    """The export colour (hex, no #) of a trigger line: the colour of the stage it leads to."""
    return cpg.STAGE_LINE[g['to']].lstrip('#').upper()


def trigger_rows(r):
    """Every level that would change the stage, as (measure, value, detail)."""
    sgr = r.get('stage') or {}
    if not sgr or sgr.get('error'):
        return []
    c = sgr['current']
    rows = []
    for side in ('up', 'down'):
        here = [g for g in c['triggers'] if g['side'] == side]
        for g in here:
            rows.append((f'{"Up" if side == "up" else "Down"}: {g["name"]}', _p(g['level']),
                         ('already crossed, waiting for confirmation. ' if g['crossed'] else
                          f'{_pc(abs(g["distance"]), False)} '
                          f'{"above" if side == "up" else "below"} the price. ')
                         + f'{g["rule"][0].upper()}{g["rule"][1:]}'
                         + ('. Moves weekly with the average' if g['moves'] else '') + '.'))
        if not here:
            rows.append((f'{"Up" if side == "up" else "Down"}: no stage change', '',
                         'a move this way only continues the current stage'))
    t = c.get('testing')
    if t:
        word = 'Breakout' if t['dir'] == 'up' else 'Breakdown'
        rows.append((f'{word} being tested', _p(t['pivot']),
                     f'proven {"above" if t["dir"] == "up" else "below"} {_p(t["proof"])} or on '
                     f'{cpg.day(t["deadline"])}'))
    return rows


def outlook_rows(r):
    o = r.get('outlook')
    if not o:
        return []
    rows = []
    for title, key in (('Now', 'now'), ('What came next before', 'next'),
                       ('What would turn it up', 'up'), ('What would turn it down', 'down'),
                       ('Read this first', 'caveat')):
        for i, x in enumerate(o[key]):
            rows.append((title if i == 0 else '', '', x))
    return rows


def stage_stat_rows(r):
    sgr = r.get('stage') or {}
    if not sgr or sgr.get('error'):
        return []
    out = []
    for k in (1, 2, 3, 4):
        d = sgr['stats'][k]
        w, f13, f26 = d['weeks'], d['forward'][13], d['forward'][26]
        nxt = ', '.join(f'{j}: {v}' for j, v in sorted(d['next'].items(), key=lambda kv: -kv[1]))
        out.append([f'{k}, {cpg.sg.NAMES[k]}', d['count'],
                    f'{w["median"]:.0f}' if w['n'] else '-',
                    f'{w["p25"]:.0f} to {w["p75"]:.0f}' if w['n'] else '-', nxt or '-',
                    f'{f13["up"]} of {f13["n"]}' if f13['n'] else '-',
                    _pc(f13['median']) if f13['n'] else '-',
                    f'{f26["up"]} of {f26["n"]}' if f26['n'] else '-',
                    _pc(f26['median']) if f26['n'] else '-'])
    return out


def stage_episode_rows(r):
    sgr = r.get('stage') or {}
    if not sgr or sgr.get('error'):
        return []
    return [[f'{e["stage"]}, {cpg.sg.NAMES[e["stage"]]}' + (' (open)' if e['open'] else ''),
             cpg.day(e['start']), cpg.day(e['end']), e['weeks'], _p(e['start_price']),
             _p(e['end_price']), _pc(e['end_price'] / e['start_price'] - 1),
             e.get('note') or '']
            for e in sgr['episodes'] if not e['first']][::-1]


def level_rows(r):
    out = []
    for label, z in (('Nearest support', r['support']), ('Nearest resistance', r['resistance'])):
        if not z:
            out.append((label, 'none', 'no past turn on that side of the price'))
            continue
        out.append((label, cpg.zone_text(z).replace('\u2212', '-'),
                    f'{z["troughs"]} turning low(s), {z["peaks"]} turning high(s), last {cpg.day(z["last"])}'))
        out.append(('  held / broke', f'{z["holds"]} / {z["breaks"]}', ''))
    if r['inside']:
        out.append(('Latest close sits inside', cpg.zone_text(r['inside']), ''))
    years = (r['last_date'] - r['first_date']).days / 365.25
    out += [('Rise size for a major move', _pc(r['threshold'], False),
             f'median annual volatility over the last {r.get("threshold_years", cy.THRESHOLD_YEARS)} '
             f'years, kept between 15% and 35%'),
            ('Fall size for a major move', _pc(r['fall'], False), 'the same move in log terms'),
            ('Market used for market-wide falls', r.get('bench_name') or 'S&P 500', ''),
            ('History used', f'{years:.1f} years', f'from {cpg.day(r["first_date"])}'),
            ('Completed major moves', str(len(r['phases'])),
             f'{r["extremes"]} extreme' if r['extremes'] else 'none extreme')]
    return out


TYPICAL = [('Major rise length (months)', 'bull_months', 'months'),
           ('Major rise gain', 'bull_change', 'pct'),
           ('Major fall length (months)', 'bear_months', 'months'),
           ('Major fall size', 'bear_change', 'pct'),
           ('Holding period (months)', 'hold_months', 'months'),
           ('Captured return, dividends included', 'hold_total', 'pct')]


def typical_rows(r, as_text=True):
    rows = []
    for label, key, kind in TYPICAL:
        line = [label]
        for basis in (r['all'], r['clean']):
            d = basis[key]
            if as_text:
                fmt = _mo if kind == 'months' else _pc
                line += [fmt(d['median']) if d['n'] else '-',
                         f'{fmt(d["p25"])} to {fmt(d["p75"])}' if d['n'] else '-', d['n']]
            else:
                line += [d['median'], d['p25'], d['p75'], d['n']]
        rows.append(line)
    wa, wc = r['all']['hold_won'], r['clean']['hold_won']
    if as_text:
        rows.append(['Holds that made money', f'{wa[0]} of {wa[1]}', '', '',
                     f'{wc[0]} of {wc[1]}', '', ''])
    else:
        rows.append(['Holds that made money', f'{wa[0]} of {wa[1]}', None, None, wa[1],
                     f'{wc[0]} of {wc[1]}', None, None, wc[1]])
    return rows


def phase_note(p):
    bits = []
    if p.get('extreme'):
        bits.append('extreme')
    if p.get('market'):
        bits.append(p['market'])
    return ', '.join(bits)


def monthly(r):
    """Month-end traded closes."""
    m = r['close'].resample('ME').last().dropna()
    return m


def daily_phase(r):
    close = r['close']
    word = {'bull': 'rise', 'bear': 'fall'}
    phase = pd.Series('before the first turn', index=close.index)
    for p in r['phases']:
        phase[(close.index >= p['start']) & (close.index < p['end'])] = word[p['kind']]
    cur = r['current']
    if cur.get('state') and cur.get('start') is not None:
        phase[close.index >= cur['start']] = word[cur['state']] + ' (not yet confirmed)'
    stage = None
    sgr = r.get('stage') or {}
    if sgr and not sgr.get('error'):
        stage = sgr['weekly']['stage'].reindex(close.index, method='ffill')
    return phase, stage


def _meta_line(meta):
    return '   |   '.join(x for x in [meta.get('symbol'), meta.get('exchange'), meta.get('isin'),
                                       meta.get('ccy') and f'Prices in {meta["ccy"]}'] if x)


# ====================================================================== POWERPOINT =====
def build_pptx(r, meta):
    name = meta.get('name') or meta.get('symbol') or 'Company'
    last = cpg.day(r['last_date'])
    deck = Deck(f'MICS International   |   {name}   |   Stock cycle, prices to {last}')
    hl = cpg.headline(r)
    state_line = hl or 'No stage yet'
    bits = [f'{"above" if g["side"] == "up" else "below"} {_p(g["level"])}: Stage {g["to"]}'
            for g in triggers_of(r)]
    if bits:
        state_line += '.   Triggers ' + ';  '.join(bits)
    deck.cover(name, ['Stock cycle', state_line,
                      f'{_meta_line(meta)}   |   Prices to {last}   |   '
                      f'Prepared by MICS International'])

    # where it stands
    s = deck.content(f'Where {name} stands now',
                     f'{hl or "No stage yet"}. Confidence {r["confidence"]["level"].lower()}.')
    rows = [['Stage and short-term trend', 'Value', '']] + [list(x) for x in stage_rows(r)]
    deck.table(s, X0, 1.85, [2.6, 1.35, 2.05], rows, size=10.5, rowh=0.38,
               aligns=['l', 'r', 'l'])
    rows = [['Stage triggers', 'Level', '']] + [list(x) for x in trigger_rows(r)]
    deck.table(s, 6.9, 1.85, [1.9, 1.0, 2.933], rows, size=10, rowh=0.62,
               aligns=['l', 'r', 'l'])

    # what usually comes next
    o = r.get('outlook')
    if o:
        s = deck.content('What usually comes next, and what to watch',
                         'Built only from this stock\'s own past stages and today\'s levels. '
                         'Not a forecast.')
        cols = (('What came next before', o['next']),
                ('What would turn it up', o['up'] + [''] + ['What would turn it down']
                 + o['down']))
        for k, (title, items) in enumerate(cols):
            lines = [(title, {'bold': True, 'color': NAVY, 'size': 12})]
            for x in items:
                if x == 'What would turn it down':
                    lines.append((x, {'bold': True, 'color': NAVY, 'size': 12, 'space': 6}))
                elif x:
                    lines.append((x, {'size': 10.5, 'space': 4}))
            deck.text(s, X0 + k * (CW / 2), 1.85, CW / 2 - 0.25, 4.5, lines, size=10.5)
        deck.text(s, X0, 6.45, CW, 0.4, ' '.join(o['caveat']), size=9.5, color=NAVY)

    # every stage
    srows = stage_stat_rows(r)
    if srows:
        s = deck.content('Every stage this stock has been through',
                         'How each stage usually behaved, counted from the week it began. '
                         'Went next to counts which stage followed.')
        rows = [['Stage', 'Past runs', 'Median weeks', 'Middle half', 'Went next to',
                 'Higher 13w on', 'Median 13w', 'Higher 26w on', 'Median 26w']] + srows
        deck.table(s, X0, 1.85, [1.6, 0.95, 1.2, 1.3, 1.6, 1.3, 1.2, 1.3, 1.233], rows,
                   size=10.5, rowh=0.42)
        eps = stage_episode_rows(r)[:8]
        if eps:
            rows = [['Stage', 'From week of', 'To week of', 'Weeks', 'Start', 'End', 'Change',
                     'How it began']] + eps
            deck.table(s, X0, 4.2, [1.9, 1.5, 1.5, 0.8, 1.2, 1.2, 1.1, 2.0], rows, size=9.5,
                       rowh=0.3)

    # levels, the rule and confidence
    s = deck.content('Levels, the rule and how much to trust this reading')
    rows = [['Levels and the rule', 'Value', '']] + [list(x) for x in level_rows(r)]
    deck.table(s, X0, 1.85, [2.4, 1.35, 2.25], rows, size=10.5, rowh=0.38,
               aligns=['l', 'r', 'l'])
    lines = [(f'Confidence: {r["confidence"]["level"]}', {'bold': True, 'color': NAVY,
                                                         'size': 12})]
    for why in r['confidence']['reasons']:
        lines.append((why[0].upper() + why[1:], {'size': 10.5, 'space': 4}))
    deck.text(s, 6.9, 1.85, 5.9, 4.8, lines, size=10.5)

    # the chart
    m = monthly(r)
    if len(m) > 12:
        series = [('Close', list(m.values), NAVY, 2, False)]
        sgr = r.get('stage') or {}
        for g in triggers_of(r):
            series.append((f'Stage {g["to"]} trigger', [g['level']] * len(m), trigger_colour(g),
                           1.75, True))
        if sgr and not sgr.get('error'):
            ma = sgr['ma_daily'].reindex(m.index, method='ffill')
            if ma.notna().sum() > 12:
                series.append(('30-week average', [None if pd.isna(v) else float(v) for v in ma],
                               '3F6AA8', 1.25, True))
        if r['support']:
            series.append(('Nearest support', [r['support']['high']] * len(m), UP, 1.25, False))
        if r['resistance']:
            series.append(('Nearest resistance', [r['resistance']['low']] * len(m), DOWN, 1.25,
                           False))
        yrs = round((m.index[-1] - m.index[0]).days / 365.25)
        s = deck.content(f'Price, stage triggers and past turns, {yrs} years',
                         'Month end traded closes, adjusted for splits, not for dividends. The '
                         'levels are today\'s, drawn across the whole chart for reference.')
        deck.line_chart(s, X0, 1.85, 8.2, 4.95, [d.date() for d in m.index], series)
        pts = r['points'][-10:][::-1]
        rows = [['Turn', 'Date', 'Price', 'Confirmed']] + [
            ['High' if p['kind'] == 'peak' else 'Low', cpg.day(p['date']), _p(p['price']),
             cpg.day(p['confirm_date'])] for p in pts]
        deck.table(s, 9.05, 1.9, [0.75, 1.1, 0.8, 1.033], rows, size=9.5, rowh=0.36,
                         aligns=['l', 'l', 'r', 'l'],
                         styles={(i + 1, 0): {'color': DOWN if p['kind'] == 'peak' else UP,
                                              'bold': True} for i, p in enumerate(pts)})

    # typical cycle
    s = deck.content('A typical cycle for this stock',
                     'Medians, so one unusual cycle cannot move them. The middle half runs from '
                     'the 25th to the 75th percentile.')
    rows = [['Measure', 'Median', 'Middle half', 'Cycles', 'Median, no extremes',
             'Middle half', 'Cycles']] + typical_rows(r)
    deck.table(s, X0, 1.95, [3.4, 1.35, 2.0, 0.85, 1.75, 2.0, 0.783], rows, size=11, rowh=0.42,
               col_fill={4: PALE, 5: PALE, 6: PALE})
    n = min(r['all']['bull_months']['n'], r['all']['bear_months']['n'])
    notes = []
    if n < cy.MIN_CYCLES:
        notes.append(f'Only {n} completed cycle(s). Below {cy.MIN_CYCLES}, these medians '
                     f'describe what happened rather than a reliable pattern.')
    notes.append(f'{r["extremes"]} move(s) marked extreme and left out of the shaded columns.'
                 if r['extremes'] else 'No move was extreme enough to leave out, so both sets '
                 'of columns match.')
    c = r['clean']
    if c['hold_total']['n'] and c['bull_change']['n']:
        notes.append(f'The median captured return of {_pc(c["hold_total"]["median"])} compares '
                     f'with a median trough to peak gain of {_pc(c["bull_change"]["median"])}. '
                     f'The difference is the cost of waiting for each turn to be confirmed.')
    y = 1.95 + 0.42 * len(rows) + 0.3
    deck.text(s, X0, y, CW, 6.85 - y, [(t, {'space': 4 if i else 0})
                                       for i, t in enumerate(notes)], size=11, color=NAVY)

    # every phase, most recent first, a page at a time
    phases = list(reversed(r['phases']))
    per = 13
    for k in range(0, max(1, len(phases)), per):
        chunk = phases[k:k + per]
        if not chunk:
            break
        s = deck.content('Every past major move' + (' (continued)' if k else ''),
                         f'Most recent first. Market-wide means the {r.get("bench_name") or "S&P 500"} also fell at least '
                         f'{int(cy.MARKET_FALL * 100)}% inside the fall.')
        rows = [['Move', 'From', 'To', 'Start price', 'End price', 'Months', 'Change', 'Notes']]
        styles = {}
        for i, p in enumerate(chunk, 1):
            rows.append([p['kind'].title(), cpg.day(p['start']), cpg.day(p['end']),
                         _p(p['start_price']), _p(p['end_price']), _mo(p['months']),
                         _pc(p['change']), phase_note(p)])
            styles[(i, 6)] = {'color': UP if p['change'] > 0 else DOWN, 'bold': True}
        deck.table(s, X0, 1.85, [1.0, 1.55, 1.55, 1.35, 1.35, 1.0, 1.25, 3.083], rows,
                   size=10.5, rowh=0.36, aligns=['l', 'l', 'l', 'r', 'r', 'r', 'r', 'l'],
                   styles=styles)

    # every holding period
    holds = list(reversed(r['holdings']))
    for k in range(0, len(holds), per):
        chunk = holds[k:k + per]
        s = deck.content('Every holding period' + (' (continued)' if k else ''),
                         'In on the close that confirmed a major rise, out on the close that '
                         'confirmed the next major fall. Dividends counted as cash, not '
                         'reinvested.')
        rows = [['In on', 'At', 'Out on', 'At', 'Months', 'Price return', 'With dividends',
                 'Notes']]
        styles = {}
        for i, h in enumerate(chunk, 1):
            rows.append([cpg.day(h['entry_date']), _p(h['entry']), cpg.day(h['exit_date']),
                         _p(h['exit']), _mo(h['months']), _pc(h['price_return']),
                         _pc(h['total_return']), 'extreme' if h['extreme'] else ''])
            styles[(i, 6)] = {'color': UP if h['total_return'] > 0 else DOWN, 'bold': True}
        deck.table(s, X0, 1.85, [1.6, 1.2, 1.6, 1.2, 1.0, 1.6, 1.7, 2.233], rows, size=10.5,
                   rowh=0.36, aligns=['l', 'r', 'l', 'r', 'r', 'r', 'r', 'l'], styles=styles)

    # definitions, two pages so nothing is squeezed
    half = (len(cpg.DEFINITIONS) + 1) // 2
    for k, part in enumerate((cpg.DEFINITIONS[:half], cpg.DEFINITIONS[half:])):
        s = deck.content('What each figure means' + (' (continued)' if k else ''),
                         'Every figure in this file uses exactly these definitions.')
        rows = [['Term', 'What it means', 'How it is calculated']] + [list(x) for x in part]
        deck.table(s, X0, 1.85, [2.4, 3.6, CW - 6.0], rows, size=11, rowh=0.62,
                   aligns=['l', 'l', 'l'])

    # limitations, in two columns
    s = deck.content('Limitations', 'Read these before using any figure in this file.')
    items = cpg.LIMITATIONS
    half = (len(items) + 1) // 2
    for k, part in enumerate((items[:half], items[half:])):
        lines = []
        for i, (t, body) in enumerate(part):
            lines.append((t, {'bold': True, 'color': NAVY, 'size': 11.5, 'space': 10 if i else 0}))
            lines.append((body, {'size': 10, 'space': 2}))
        deck.text(s, X0 + k * (CW / 2), 1.85, CW / 2 - 0.25, 5.0, lines, size=10)
    deck.text(s, X0, 6.6, CW, 0.3, 'MICS International internal research. Not a recommendation '
              'to buy, hold or sell; past cycles do not guarantee future ones.', size=9.5,
              color=NAVY)
    return deck.save()


# ====================================================================== EXCEL ==========
def build_xlsx(r, meta):
    from openpyxl.chart import LineChart, Reference
    name = meta.get('name') or meta.get('symbol') or 'Company'
    last = cpg.day(r['last_date'])
    book = Book()

    # ---- Summary
    ws = book.sheet('Summary', widths=(34, 16, 46))
    rr = book.title(ws, f'{name}: stock cycle', f'{_meta_line(meta)}   |   Prices to {last}')
    rr = book.note(ws, rr, plain(cpg.reading(r)), 3, chars=95)
    rr = book.heading(ws, rr, 'Stage and short-term trend')
    rr = book.table(ws, rr, ['Measure', 'Value', 'Detail'], stage_rows(r),
                    aligns=['left', 'right', 'left'])
    rr = book.heading(ws, rr, 'Stage triggers (2 weekly closes beyond the level)')
    rr = book.table(ws, rr, ['Measure', 'Level', 'Detail'], trigger_rows(r),
                    aligns=['left', 'right', 'left'], wrap_cols=(2,))
    rr = book.heading(ws, rr, 'What usually comes next, and what to watch')
    rr = book.table(ws, rr, ['Section', '', 'Detail'], outlook_rows(r),
                    aligns=['left', 'left', 'left'], wrap_cols=(2,))
    rr = book.heading(ws, rr, 'How much to trust this reading')
    rr = book.table(ws, rr, ['Measure', 'Value', 'Detail'], confidence_rows(r),
                    aligns=['left', 'right', 'left'], wrap_cols=(2,))
    rr = book.heading(ws, rr, 'Support, resistance and how past major moves are found')
    book.table(ws, rr, ['Measure', 'Value', 'Detail'], level_rows(r),
               aligns=['left', 'right', 'left'])

    # ---- Stages
    srows = stage_stat_rows(r)
    if srows:
        ws = book.sheet('Stages', widths=(26, 13, 13, 13, 18, 14, 13, 18, 13))
        rr = book.title(ws, 'Every stage this stock has been through',
                        'How each stage usually behaved, counted from the week it began, then '
                        'every stage, most recent first.')
        rr = book.table(ws, rr, ['Stage', 'Past runs', 'Median weeks', 'Middle half',
                                 'Went next to', 'Higher 13w on', 'Median 13w', 'Higher 26w on',
                                 'Median 26w'], srows)
        rr = book.heading(ws, rr + 1, 'Every stage')
        book.table(ws, rr, ['Stage', 'From week of', 'To week of', 'Weeks', 'Start', 'End',
                            'Change', 'How it began'], stage_episode_rows(r))

    # ---- Typical cycle, as numbers
    ws = book.sheet('Typical cycle', widths=(36, 12, 12, 12, 9, 14, 12, 12, 9))
    rr = book.title(ws, 'A typical cycle for this stock',
                    'Medians and the middle half (25th to 75th percentile), with and without '
                    'extreme moves. Shaded columns leave extremes out.')
    rows = typical_rows(r, as_text=False)
    fm = {}
    for i, (_, key, kind) in enumerate(TYPICAL):
        f = '0.0' if kind == 'months' else PCT
        for j in (1, 2, 3, 5, 6, 7):
            fm[(i, j)] = f
    book.table(ws, rr, ['Measure', 'Median', '25th pct', '75th pct', 'Cycles',
                        'Median, no extremes', '25th pct', '75th pct', 'Cycles'], rows,
               formats=fm, col_fill={5: PALE, 6: PALE, 7: PALE, 8: PALE})

    # ---- Phases
    ws = book.sheet('Major moves', widths=(9, 13, 13, 12, 12, 9, 10, 26, 14, 14))
    rr = book.title(ws, 'Every past major move',
                    'Oldest first. A major move runs from one confirmed turning point to the next.')
    rows = [('Rise' if p['kind'] == 'bull' else 'Fall', p['start'].date(), p['end'].date(), p['start_price'],
             p['end_price'], round(p['months'], 1), p['change'], phase_note(p))
            for p in r['phases']]
    styles = {(i, 6): {'color': UP if p['change'] > 0 else DOWN, 'bold': True}
              for i, p in enumerate(r['phases'])}
    book.table(ws, rr, ['Move', 'From', 'To', 'Start price', 'End price', 'Months', 'Change',
                        'Notes'], rows, aligns=['left', 'left', 'left', 'right', 'right', 'right',
                                                'right', 'left'],
               formats={1: 'dd mmm yyyy', 2: 'dd mmm yyyy', 3: PRICE, 4: PRICE, 5: '0.0', 6: PCT},
               styles=styles)

    # ---- Holding periods
    ws = book.sheet('Holding periods', widths=(13, 11, 13, 11, 9, 13, 11, 14, 11))
    rr = book.title(ws, 'Every holding period',
                    'In on the close that confirmed a major rise, out on the close that confirmed '
                    'the next major fall. Dividends counted as cash, not reinvested.')
    rows = [(h['entry_date'].date(), h['entry'], h['exit_date'].date(), h['exit'],
             round(h['months'], 1), h['dividends'], h['price_return'], h['total_return'],
             'extreme' if h['extreme'] else '') for h in r['holdings']]
    styles = {(i, 7): {'color': UP if h['total_return'] > 0 else DOWN, 'bold': True}
              for i, h in enumerate(r['holdings'])}
    book.table(ws, rr, ['In on', 'At', 'Out on', 'At', 'Months', 'Dividends', 'Price return',
                        'With dividends', 'Notes'], rows,
               aligns=['left', 'right', 'left', 'right', 'right', 'right', 'right', 'right',
                       'left'],
               formats={0: 'dd mmm yyyy', 1: PRICE, 2: 'dd mmm yyyy', 3: PRICE, 4: '0.0',
                        5: PRICE, 6: PCT, 7: PCT}, styles=styles)

    # ---- Monthly prices with the levels, feeding a native chart
    m = monthly(r)
    trig = triggers_of(r)
    ws = book.sheet('Price chart', widths=(13, 12) + (16,) * len(trig) + (12, 12))
    rr = book.title(ws, 'Month end closes and today\'s levels',
                    'Traded prices adjusted for splits, not dividends. The levels are today\'s, '
                    'repeated down the column so they draw as lines.')
    head = (['Month end', 'Close'] + [f'Stage {g["to"]} trigger' for g in trig]
            + ['Support', 'Resistance'])
    rows = [tuple([d.date(), float(v)] + [g['level'] for g in trig]
                  + [r['support']['high'] if r['support'] else None,
                     r['resistance']['low'] if r['resistance'] else None]) for d, v in m.items()]
    first = rr + 1
    book.table(ws, rr, head, rows,
               formats={0: 'mmm yyyy', **{j: PRICE for j in range(1, len(head))}})
    if len(rows) > 2:
        ch = LineChart()
        ch.title = f'{name}, month end close'
        ch.height, ch.width = 11, 26
        ch.y_axis.title, ch.x_axis.number_format = 'Price', 'mmm yy'
        data = Reference(ws, min_col=2, max_col=len(head), min_row=first - 1,
                         max_row=first + len(rows) - 1)
        ch.add_data(data, titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=first, max_row=first + len(rows) - 1))
        styles = ([(NAVY, 28000, None)] + [(trigger_colour(g), 19000, 'dash') for g in trig]
                  + [(UP, 12000, None), (DOWN, 12000, None)])
        for ser, (colour, width, dash) in zip(ch.series, styles):
            ser.graphicalProperties.line.solidFill = colour
            ser.graphicalProperties.line.width = width
            ser.smooth = False
            if dash:
                ser.graphicalProperties.line.dashStyle = dash
        ws.add_chart(ch, 'G4')

    # ---- Daily closes with the phase each day sat in
    ws = book.sheet('Daily closes', widths=(13, 12, 26, 18))
    rr = book.title(ws, 'Every daily close used', 'Traded prices, the stage of each week, and '
                    'the past major move each day '
                    'belongs to once its turning points were confirmed.')
    ph, stg = daily_phase(r)
    def stage_name(d):
        if stg is None or pd.isna(stg.get(d)):
            return ''
        k = int(stg[d])
        return f'{k}, {cpg.sg.NAMES[k]}'
    rows = [(d.date(), float(v), ph[d], stage_name(d)) for d, v in r['close'].items()]
    book.table(ws, rr, ['Date', 'Close', 'Past major move', 'Stage'], rows,
               aligns=['left', 'right', 'left', 'left'],
               formats={0: 'dd mmm yyyy', 1: PRICE})

    # ---- Definitions and limitations
    ws = book.sheet('Definitions', widths=(26, 46, 80))
    rr = book.title(ws, 'What each figure means', 'Every figure in this workbook uses exactly '
                    'these definitions.')
    book.table(ws, rr, ['Term', 'What it means', 'How it is calculated'], cpg.DEFINITIONS,
               aligns=['left', 'left', 'left'], wrap_cols=(1, 2))
    ws = book.sheet('Limitations', widths=(52, 100))
    rr = book.title(ws, 'Limitations', f'Prepared {datetime.date.today():%d %B %Y}. Read these '
                    f'before using any figure in this workbook.')
    book.table(ws, rr, ['Limitation', 'What it means'],
               list(cpg.LIMITATIONS) + [('Use', 'MICS International internal research. Not a '
                                                'recommendation to buy, hold or sell.')],
               aligns=['left', 'left'], wrap_cols=(0, 1))
    return book.save()
