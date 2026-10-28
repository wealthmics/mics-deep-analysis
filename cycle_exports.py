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
from exports import GOLD, NAVY, plain

PCT = '0.0%;-0.0%'
PRICE = '#,##0.00'


def _p(x):
    return '-' if x is None else f'{x:,.2f}'


def _pc(x, sign=True):
    return cpg.pct(x, sign).replace('\u2212', '-')


def _mo(x):
    return '-' if x is None else f'{x:.1f}'


def now_rows(r):
    """Where the stock is now, as (measure, value, detail)."""
    cur, T = r['current'], r['threshold']
    if not cur.get('state'):
        return [('Phase', 'None yet', f'no move of {_pc(T, False)} since '
                                      f'{cpg.day(r["first_date"])}'),
                ('Latest close', _p(cur['last_price']), cpg.day(cur['last_date']))]
    bull = cur['state'] == 'bull'
    rows = [('Status', r['status']['label'], f'confidence {r["confidence"]["level"].lower()}'),
            ('Phase', 'Bull' if bull else 'Bear', 'confirmed'),
            ('Started', _p(cur['start_price']),
             f'{"low" if bull else "high"} on {cpg.day(cur["start"])}'),
            ('Confirmed', _p(cur['confirm_price']), f'close on {cpg.day(cur["confirm_date"])}'),
            ('Length so far', f'{cur["months"]:.1f} months', ''),
            ('Move since it started', _pc(cur['change']), ''),
            (f'{"Highest" if bull else "Lowest"} close since', _p(cur['extreme']),
             cpg.day(cur['extreme_date'])),
            ('Latest close', _p(cur['last_price']), cpg.day(cur['last_date'])),
            ('From the high' if bull else 'From the low', _pc(cur['from_extreme']),
             f'{abs(cur["from_extreme"]) / T * 100:.0f}% of the {_pc(T, False)} threshold'),
            ('Trend', cpg.trend_text(r['trend']).replace('\u2212', '-'), '200-day average'),
            (f'Phase ends on a close {"below" if bull else "above"}', _p(cur['trigger']),
             f'{"high minus" if bull else "low plus"} {_pc(T, False)}'),
            ('Distance to that level', _pc(cur['to_trigger']), '')]
    if bull and cur.get('held_return') is not None:
        rows.append(('Held since confirmation', _pc(cur['held_return']),
                     f'{cur["held_months"]:.1f} months, dividends included'))
    rows.append(('Confidence', r['confidence']['level'], ''))
    for why in r['confidence']['reasons']:
        rows.append(('  reason', '', why))
    return rows


def level_rows(r):
    out = []
    for label, z in (('Nearest support', r['support']), ('Nearest resistance', r['resistance'])):
        if not z:
            out.append((label, 'none', 'no past turn on that side of the price'))
            continue
        out.append((label, cpg.zone_text(z).replace('\u2212', '-'),
                    f'{z["troughs"]} trough(s), {z["peaks"]} peak(s), last {cpg.day(z["last"])}'))
        out.append(('  held / broke', f'{z["holds"]} / {z["breaks"]}', ''))
    if r['inside']:
        out.append(('Latest close sits inside', cpg.zone_text(r['inside']), ''))
    years = (r['last_date'] - r['first_date']).days / 365.25
    out += [('Threshold', _pc(r['threshold'], False),
             f'median annual volatility over the last {r.get("threshold_years", cy.THRESHOLD_YEARS)} '
             f'years, kept between 15% and 35%'),
            ('Market used for market-wide falls', r.get('bench_name') or 'S&P 500', ''),
            ('History used', f'{years:.1f} years', f'from {cpg.day(r["first_date"])}'),
            ('Completed phases', str(len(r['phases'])),
             f'{r["extremes"]} extreme' if r['extremes'] else 'none extreme')]
    return out


TYPICAL = [('Bull phase length (months)', 'bull_months', 'months'),
           ('Bull phase gain', 'bull_change', 'pct'),
           ('Bear phase length (months)', 'bear_months', 'months'),
           ('Bear phase fall', 'bear_change', 'pct'),
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
    """Month-end traded closes, with the current trigger and the nearest zones as levels."""
    m = r['close'].resample('ME').last().dropna()
    return m


def daily_phase(r):
    close = r['close']
    phase = pd.Series('before the first turn', index=close.index)
    for p in r['phases']:
        phase[(close.index >= p['start']) & (close.index < p['end'])] = p['kind']
    cur = r['current']
    if cur.get('state') and cur.get('start') is not None:
        phase[close.index >= cur['start']] = cur['state'] + ' (open)'
    return phase


def _meta_line(meta):
    return '   |   '.join(x for x in [meta.get('symbol'), meta.get('exchange'), meta.get('isin'),
                                       meta.get('ccy') and f'Prices in {meta["ccy"]}'] if x)


# ====================================================================== POWERPOINT =====
def build_pptx(r, meta):
    name = meta.get('name') or meta.get('symbol') or 'Company'
    last = cpg.day(r['last_date'])
    deck = Deck(f'MICS International   |   {name}   |   Stock cycle, prices to {last}')
    cur = r['current']
    if cur.get('state'):
        state_line = (f'{"Bull" if cur["state"] == "bull" else "Bear"} phase since '
                      f'{cpg.day(cur["start"])}, ends on a close '
                      f'{"below" if cur["state"] == "bull" else "above"} {_p(cur["trigger"])}')
    else:
        state_line = 'No phase confirmed yet'
    deck.cover(name, ['Stock cycle', state_line,
                      f'{_meta_line(meta)}   |   Prices to {last}   |   '
                      f'Prepared by MICS International'])

    # where it stands
    s = deck.content(f'Where {name} stands in its cycle')
    deck.text(s, X0, 1.4, CW, 0.9, plain(cpg.reading(r)), size=12, color=NAVY)
    rows = [['Where the stock is now', 'Value', '']] + [list(x) for x in now_rows(r)]
    deck.table(s, X0, 2.45, [2.75, 1.25, 2.0], rows, size=10.5, rowh=0.38,
               aligns=['l', 'r', 'l'])
    rows = [['Levels and the rule', 'Value', '']] + [list(x) for x in level_rows(r)]
    deck.table(s, 6.9, 2.45, [2.2, 1.35, 2.283], rows, size=10.5, rowh=0.38,
               aligns=['l', 'r', 'l'])

    # the chart
    m = monthly(r)
    if len(m) > 12:
        series = [('Close', list(m.values), NAVY, 2, False)]
        if cur.get('trigger'):
            series.append(('Trigger that ends the phase', [cur['trigger']] * len(m), GOLD, 1.5,
                           True))
        if r['support']:
            series.append(('Nearest support', [r['support']['high']] * len(m), UP, 1.25, False))
        if r['resistance']:
            series.append(('Nearest resistance', [r['resistance']['low']] * len(m), DOWN, 1.25,
                           False))
        yrs = round((m.index[-1] - m.index[0]).days / 365.25)
        s = deck.content(f'Price and every confirmed cycle, {yrs} years',
                         'Month end traded closes, adjusted for splits, not for dividends. The '
                         'levels are today\'s, drawn across the whole chart for reference.')
        deck.line_chart(s, X0, 1.85, 8.2, 4.95, [d.date() for d in m.index], series)
        pts = r['points'][-10:][::-1]
        rows = [['Turn', 'Date', 'Price', 'Confirmed']] + [
            ['Peak' if p['kind'] == 'peak' else 'Trough', cpg.day(p['date']), _p(p['price']),
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
    notes.append(f'{r["extremes"]} phase(s) marked extreme and left out of the shaded columns.'
                 if r['extremes'] else 'No phase was extreme enough to leave out, so both sets '
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
        s = deck.content('Every completed phase' + (' (continued)' if k else ''),
                         f'Most recent first. Market-wide means the {r.get("bench_name") or "S&P 500"} also fell at least '
                         f'{int(cy.MARKET_FALL * 100)}% inside the bear phase.')
        rows = [['Phase', 'From', 'To', 'Start price', 'End price', 'Months', 'Change', 'Notes']]
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
                         'In on the close that confirmed a bull phase, out on the close that '
                         'confirmed the next bear phase. Dividends counted as cash, not '
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
    rr = book.heading(ws, rr, 'Where the stock is now')
    rr = book.table(ws, rr, ['Measure', 'Value', 'Detail'], now_rows(r),
                    aligns=['left', 'right', 'left'])
    rr = book.heading(ws, rr, 'Support, resistance and the rule')
    book.table(ws, rr, ['Measure', 'Value', 'Detail'], level_rows(r),
               aligns=['left', 'right', 'left'])

    # ---- Typical cycle, as numbers
    ws = book.sheet('Typical cycle', widths=(36, 12, 12, 12, 9, 14, 12, 12, 9))
    rr = book.title(ws, 'A typical cycle for this stock',
                    'Medians and the middle half (25th to 75th percentile), with and without '
                    'extreme phases. Shaded columns leave extremes out.')
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
    ws = book.sheet('Phases', widths=(9, 13, 13, 12, 12, 9, 10, 26, 14, 14))
    rr = book.title(ws, 'Every completed phase',
                    'Oldest first. A phase runs from one confirmed turning point to the next.')
    rows = [(p['kind'].title(), p['start'].date(), p['end'].date(), p['start_price'],
             p['end_price'], round(p['months'], 1), p['change'], phase_note(p))
            for p in r['phases']]
    styles = {(i, 6): {'color': UP if p['change'] > 0 else DOWN, 'bold': True}
              for i, p in enumerate(r['phases'])}
    book.table(ws, rr, ['Phase', 'From', 'To', 'Start price', 'End price', 'Months', 'Change',
                        'Notes'], rows, aligns=['left', 'left', 'left', 'right', 'right', 'right',
                                                'right', 'left'],
               formats={1: 'dd mmm yyyy', 2: 'dd mmm yyyy', 3: PRICE, 4: PRICE, 5: '0.0', 6: PCT},
               styles=styles)

    # ---- Holding periods
    ws = book.sheet('Holding periods', widths=(13, 11, 13, 11, 9, 13, 11, 14, 11))
    rr = book.title(ws, 'Every holding period',
                    'In on the close that confirmed a bull phase, out on the close that confirmed '
                    'the next bear phase. Dividends counted as cash, not reinvested.')
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
    cur = r['current']
    ws = book.sheet('Price chart', widths=(13, 12, 12, 12, 12))
    rr = book.title(ws, 'Month end closes and today\'s levels',
                    'Traded prices adjusted for splits, not dividends. The levels are today\'s, '
                    'repeated down the column so they draw as lines.')
    head = ['Month end', 'Close', 'Trigger', 'Support', 'Resistance']
    rows = [(d.date(), float(v), cur.get('trigger'),
             r['support']['high'] if r['support'] else None,
             r['resistance']['low'] if r['resistance'] else None) for d, v in m.items()]
    first = rr + 1
    book.table(ws, rr, head, rows, formats={0: 'mmm yyyy', 1: PRICE, 2: PRICE, 3: PRICE,
                                            4: PRICE})
    if len(rows) > 2:
        ch = LineChart()
        ch.title = f'{name}, month end close'
        ch.height, ch.width = 11, 26
        ch.y_axis.title, ch.x_axis.number_format = 'Price', 'mmm yy'
        data = Reference(ws, min_col=2, max_col=5, min_row=first - 1, max_row=first + len(rows) - 1)
        ch.add_data(data, titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=first, max_row=first + len(rows) - 1))
        for ser, colour, width, dash in zip(ch.series, (NAVY, GOLD, UP, DOWN),
                                            (28000, 19000, 16000, 16000),
                                            (None, 'dash', None, None)):
            ser.graphicalProperties.line.solidFill = colour
            ser.graphicalProperties.line.width = width
            ser.smooth = False
            if dash:
                ser.graphicalProperties.line.dashStyle = dash
        ws.add_chart(ch, 'G4')

    # ---- Daily closes with the phase each day sat in
    ws = book.sheet('Daily closes', widths=(13, 12, 24))
    rr = book.title(ws, 'Every daily close used', 'Traded prices, and the phase each day '
                    'belongs to once its turning points were confirmed.')
    ph = daily_phase(r)
    rows = [(d.date(), float(v), ph[d]) for d, v in r['close'].items()]
    book.table(ws, rr, ['Date', 'Close', 'Phase'], rows, aligns=['left', 'right', 'left'],
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
