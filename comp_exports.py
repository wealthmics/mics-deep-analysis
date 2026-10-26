"""
Competitor comparison as Excel and PowerPoint, in the house style.

Two ways in, one set of pages:
    build_xlsx(cx), build_pptx(cx)   the comparison as files of its own
    add_sheet(book, cx)              its sheet inside the company workbook
    add_slides(deck, cx)             its slides inside the company presentation

cx is what competitors.compute returned, the same object the page section is drawn from.
"""

import datetime
import re

import competitors as cp
from deck import CW, PALE, X0, Book, Deck, UP
from exports import NAVY, plain

FORMATS = {'pct': '0.0"%";-0.0"%"', 'x': '0.00"x"', 'num': '0.00', 'int': '0',
           'money': '#,##0.0,,,"B"'}


def _name(cx):
    s = cx['subject']
    return (s.get('name') or s.get('ticker') or 'Company').rstrip('.')


def short(c):
    """The company name without its legal suffix, for the second line of a column head."""
    n = re.sub(r'[,.]?\s+(Inc|Co|Ltd|Corp|Corporation|Holding|Holdings|Group|N\.?V|plc|PLC|'
               r'S\.?A|AG|SE|Limited|Company)\b.*$', '', c.get('name') or '').strip()
    if len(n) > 20:
        n = n[:21].rsplit(' ', 1)[0]
    return n


def head_label(c):
    return f'{c.get("ticker") or ""}\n{short(c)}' if short(c) else (c.get('ticker') or '')


def _rank(row):
    if row['higher'] is None:
        return ''
    return f'{cp.ordinal(row["rank"])} of {row["n"]}' if row['rank'] else 'n/a'


def _text(v, row):
    out = cp.cell_text(v, row['kind'], row['key'])
    return '-' if out == 'n/a' else out.replace('\u2212', '-')


def group_rows(cx):
    """(label, key, kind, source) for every company, for the 'who is in it' table."""
    out = []
    for i, c in enumerate(cx['companies']):
        out.append([c.get('ticker') or '', (c.get('name') or '')[:40], c.get('country') or '',
                    c.get('industry') or '', c.get('mcap'),
                    'This company' if i == 0 else ('Yahoo' if c.get('_source') == 'Yahoo'
                                                   else 'TradingView feed')])
    return out


# ====================================================================== POWERPOINT =====
def _table_slide(deck, cx, groups, title):
    companies = cx['companies']
    n = len(companies)
    s = deck.content(title, plain(cx['reading']))
    head = ['Measure'] + [head_label(c) for c in companies] + ['Rank', 'Peer median']
    rows, styles, grp = [head], {}, set()
    for group, items in groups:
        grp.add(len(rows))
        rows.append([group] + [''] * (len(head) - 1))
        for row in items:
            i = len(rows)
            line = [row['label']] + [_text(v, row) for v in row['values']] + \
                   [_rank(row), _text(row['peer_median'], row)]
            for j in row['best']:
                styles[(i, j + 1)] = {'color': UP, 'bold': True}
            styles[(i, n + 1)] = {'color': NAVY, 'bold': True}
            rows.append(line)
    comp_w = (CW - 1.9 - 0.95 - 1.1) / n
    size = 10.5 if n <= 6 else 9.5
    rowh = min(0.35, (6.75 - 2.25) / len(rows))
    deck.table(s, X0, 2.0, [1.9] + [comp_w] * n + [0.95, 1.1], rows, size=size, rowh=rowh,
               col_fill={1: PALE}, styles=styles, group_rows=grp)
    return s


def add_slides(deck, cx):
    name = _name(cx)
    g = cx['groups']
    _table_slide(deck, cx, g[:2], 'Against its competitors: valuation and profitability')
    _table_slide(deck, cx, g[2:], 'Against its competitors: balance sheet, quality, returns')
    s = deck.content('Who is in the comparison',
                     f'Started from the companies closest in size in the TradingView industry '
                     f'{cx.get("industry") or "given"}, then edited by hand. The best value in '
                     f'each row of the previous slides is in green; the shaded column is {name}.')
    rows = [['Ticker', 'Company', 'Country', 'Industry', 'Market cap (USD)', 'Source']]
    for r in group_rows(cx):
        r = list(r)
        r[4] = '-' if r[4] is None else cp.f(r[4], 'money')
        rows.append(r)
    deck.table(s, X0, 1.95, [1.2, 3.6, 1.7, 2.6, 1.5, 1.533], rows, size=10.5, rowh=0.34,
               aligns=['l', 'l', 'l', 'l', 'r', 'l'], col_fill={})
    y = 1.95 + 0.34 * len(rows) + 0.25
    deck.text(s, X0, y, CW, 6.85 - y, [(t, {'space': 4 if i else 0})
                                       for i, t in enumerate(cx['notes'])], size=10, color=NAVY)


def build_pptx(cx):
    name = _name(cx)
    deck = Deck(f'MICS International   |   {name}   |   Competitor comparison, '
                f'data as at {cx.get("as_of") or ""}')
    others = ', '.join(short(c) or c.get('ticker') or '' for c in cx['companies'][1:])
    deck.cover(name, ['Against its competitors',
                      f'Compared with {others}',
                      f'TradingView data as at {cx.get("as_of") or ""}   |   '
                      f'Prepared by MICS International'])
    add_slides(deck, cx)
    return deck.save()


# ====================================================================== EXCEL ==========
def add_sheet(book, cx):
    companies = cx['companies']
    n = len(companies)
    name = _name(cx)
    ws = book.sheet('Competitors', widths=[30] + [15] * n + [11, 13, 13])
    r = book.title(ws, f'{name} against its competitors',
                   f'TradingView data as at {cx.get("as_of") or ""}. The shaded column is '
                   f'{name}; the best value in each row is in green.')
    r = book.note(ws, r, plain(cx['reading']), n + 4)
    head = ['Measure'] + [head_label(c) for c in companies] + \
           ['Rank', 'Peer median', 'Sector median']
    rows, styles, formats, grp = [], {}, {}, set()
    for group, items in cx['groups']:
        grp.add(len(rows))
        rows.append([group] + [None] * (len(head) - 1))
        for row in items:
            i = len(rows)
            fmt = FORMATS[row['kind']]
            vals = []
            for j, v in enumerate(row['values']):
                if row['key'] in cp.VALUATION and v is not None and v <= 0:
                    vals.append('loss')
                else:
                    vals.append(v)
                    formats[(i, j + 1)] = fmt
            formats[(i, n + 2)] = fmt
            formats[(i, n + 3)] = fmt
            for j in row['best']:
                styles[(i, j + 1)] = {'color': UP, 'bold': True}
            styles[(i, n + 1)] = {'color': NAVY, 'bold': True}
            rows.append([row['label']] + vals + [_rank(row), row['peer_median'],
                                                 row['sector_median']])
    r = book.table(ws, r, head, rows, formats=formats, col_fill={1: PALE}, styles=styles,
                   group_rows=grp)
    r = book.heading(ws, r, 'Who is in the comparison')
    # the company name goes in the wide first column so it is never cut short
    r = book.table(ws, r, ['Company', 'Ticker', 'Country', 'Industry', 'Market cap (USD)',
                           'Source'], [[g[1], g[0]] + g[2:] for g in group_rows(cx)],
                   aligns=['left', 'left', 'left', 'left', 'right', 'left'],
                   formats={4: FORMATS['money']})
    for t in cx['notes']:
        r = book.note(ws, r, t, n + 4, chars=150) - 1
    return ws


def build_xlsx(cx):
    book = Book()
    add_sheet(book, cx)
    ws = book.sheet('Notes', widths=(24, 100))
    r = book.title(ws, 'Notes and sources', f'Prepared {datetime.date.today():%d %B %Y}')
    book.table(ws, r, ['Item', 'Note'],
               [('Figures', cx['notes'][0]), ('Ranking', cx['notes'][1]),
                ('Medians', cx['notes'][2]), ('Returns', cx['notes'][3])]
               + ([('Yahoo', cx['notes'][4])] if len(cx['notes']) > 4 else [])
               + [('Use', 'For internal research. Not investment advice or a recommendation.')],
               aligns=['left', 'left'], wrap_cols=(1,))
    return book.save()
