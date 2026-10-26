"""
Competitors: the company against the companies it actually competes with.

Added under the company page as its own section. Nothing in page.py is changed; this module
emits one block of HTML that uses the classes page.py already defines, plus a few rules of
its own scoped to .comp, so the existing sections render exactly as before.

Source rule, the same as the rest of the app: every company in the TradingView feed is
compared on the feed's own trailing-twelve-month figures, so the numbers agree with the
screener. A competitor that is not in the feed can be added by its Yahoo symbol; its figures
then come from Yahoo, are marked as such, and fields Yahoo does not publish stay empty
rather than being estimated.
"""

import math

from page import esc, f, minus

# label, feed key, format, higher is better (None: not ranked)
METRICS = [
    ('Size and valuation', [
        ('Market cap (USD)', 'mcap', 'money', None),
        ('P/E', 'pe', 'x', False),
        ('P/E forward', 'fpe', 'x', False)]),
    ('Profitability', [
        ('ROIC', 'roic', 'pct', True),
        ('ROE', 'roe', 'pct', True),
        ('Gross margin', 'gross_margin', 'pct', True),
        ('Operating margin', 'op_margin', 'pct', True),
        ('Net margin', 'net_margin', 'pct', True),
        ('FCF margin', 'fcf_margin', 'pct', True)]),
    ('Balance sheet', [
        ('Current ratio', 'current_ratio', 'num', True),
        ('Debt / equity', 'debt_equity', 'num', False),
        ('Interest cover', 'interest_cover', 'x', True)]),
    ('Quality scores', [
        ('Altman Z', 'altman_z', 'num', True),
        ('Piotroski F', 'piotroski_f', 'int', True)]),
    ('Price return, own currency', [
        ('Year to date', 'perf_ytd', 'pct', True),
        ('1 year', 'perf_1y', 'pct', True),
        ('5 years', 'perf_5y', 'pct', True)]),
]
VALUATION = {'pe', 'fpe'}
# how each measure reads in the middle of a sentence
SAY = {'pe': 'P/E', 'fpe': 'forward P/E', 'roic': 'ROIC', 'roe': 'ROE',
       'gross_margin': 'gross margin', 'op_margin': 'operating margin',
       'net_margin': 'net margin', 'fcf_margin': 'FCF margin', 'current_ratio': 'current ratio',
       'debt_equity': 'debt to equity', 'interest_cover': 'interest cover',
       'altman_z': 'Altman Z', 'piotroski_f': 'Piotroski F', 'perf_ytd': 'year to date return',
       'perf_1y': '1 year return', 'perf_5y': '5 year return'}
MAX_PEERS = 8
AUTO_PEERS = 5


# ---------------------------------------------------------------- choosing peers ---------
def auto_peers(feed, subject_key, subject, n=AUTO_PEERS):
    """The starting list: the same TradingView industry, closest in market cap.

    Industries are broad (Semiconductors holds memory makers, chip designers and equipment
    makers alike), so this is only a starting point. The page says so and lets the reader
    edit it to the companies that really compete.
    """
    stocks = (feed or {}).get('stocks') or {}
    industry = (subject or {}).get('industry')
    if not industry:
        return []
    size = (subject or {}).get('mcap')
    same = [(k, e) for k, e in stocks.items() if k != subject_key and
            e.get('industry') == industry and e.get('ticker') != subject.get('ticker')]
    if size and size > 0:
        same.sort(key=lambda r: abs(math.log((r[1].get('mcap') or 1) / size)))
    else:
        same.sort(key=lambda r: -(r[1].get('mcap') or 0))
    return [k for k, _ in same[:n]]


def option_order(feed, subject_key, subject):
    """Every company in the feed, the subject's own industry first by size, then the rest."""
    stocks = (feed or {}).get('stocks') or {}
    industry = (subject or {}).get('industry')
    keys = [k for k in stocks if k != subject_key]
    return sorted(keys, key=lambda k: (stocks[k].get('industry') != industry,
                                       -(stocks[k].get('mcap') or 0)))


def label(entry):
    return (f"{entry.get('ticker')}  {entry.get('name') or ''}  "
            f"({entry.get('country') or ''}, {entry.get('industry') or 'no industry'})")


# ---------------------------------------------------------------- Yahoo competitors ------
def from_yahoo(symbol, info, usd_rate):
    """Map Yahoo's info block onto the feed's field names, in the feed's units.

    Yahoo gives margins and returns as fractions and debt to equity as a percentage; the
    feed gives percentages and a plain ratio. ROIC, ROCE, interest cover, Altman Z,
    Piotroski F and the year to date and five year returns are not published by Yahoo and
    are left empty.
    """
    info = info or {}

    def pc(key):
        v = info.get(key)
        return v * 100 if isinstance(v, (int, float)) else None

    rev, fcf = info.get('totalRevenue'), info.get('freeCashflow')
    de = info.get('debtToEquity')
    cap = info.get('marketCap')
    return {
        'ticker': symbol, 'name': info.get('shortName') or info.get('longName') or symbol,
        'country': info.get('country'), 'industry': info.get('industry'),
        'ccy': info.get('currency'), '_source': 'Yahoo',
        'mcap': cap * usd_rate if isinstance(cap, (int, float)) and usd_rate else None,
        'pe': info.get('trailingPE'), 'fpe': info.get('forwardPE'),
        'roe': pc('returnOnEquity'), 'roa': pc('returnOnAssets'),
        'gross_margin': pc('grossMargins'), 'op_margin': pc('operatingMargins'),
        'net_margin': pc('profitMargins'),
        'fcf_margin': fcf / rev * 100 if isinstance(fcf, (int, float)) and rev else None,
        'current_ratio': info.get('currentRatio'),
        'debt_equity': de / 100 if isinstance(de, (int, float)) else None,
        'perf_1y': pc('52WeekChange'),
    }


# ---------------------------------------------------------------- ranking ----------------
def usable(key, v):
    """A value that can be ranked. A negative P/E is a loss, not a cheap stock."""
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return False
    if key in VALUATION and v <= 0:
        return False
    return True


def ranks(companies, key, higher):
    """1 is best, and equal values share a rank. Companies without a usable value get none."""
    vals = [(i, c.get(key)) for i, c in enumerate(companies) if usable(key, c.get(key))]
    better = (lambda a, b: a > b) if higher else (lambda a, b: a < b)
    return {i: 1 + sum(1 for _, w in vals if better(w, v)) for i, v in vals}, len(vals)


def median(values):
    x = sorted(v for v in values if v is not None)
    if not x:
        return None
    m = len(x) // 2
    return x[m] if len(x) % 2 else (x[m - 1] + x[m]) / 2


def ordinal(n):
    return f'{n}{"th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")}'


# ---------------------------------------------------------------- the section -----------
CSS = """
<style>
.an .comp .wrap{overflow-x:auto}
.an .comp table{min-width:720px}
.an .comp th,.an .comp td{padding:8px 10px;white-space:nowrap}
.an .comp th:first-child,.an .comp td:first-child{padding-left:0}
.an .comp th a{color:#1f3864;text-decoration:none;border-bottom:1px solid #d8dee9}
.an .comp th small{display:block;font-size:9.5px;font-weight:600;letter-spacing:0;
text-transform:none;margin-top:2px}
.an .comp .me{background:#f4f7fb}
.an .comp .best{color:#12703a;font-weight:700}
.an .comp tr.grp td{font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
color:#1f3864;padding-top:16px;border-bottom:1px solid #d8dee9}
.an .comp td.rk{font-weight:600;color:#1f3864}
</style>
"""


def reading(subject, companies, rows):
    """What the table says about the subject, in two sentences."""
    name = subject.get('name') or subject.get('ticker')
    top, bottom, upper, counted = [], [], 0, 0
    for lab, key, rk, n in rows:
        if rk is None or n < 3:
            continue
        counted += 1
        if rk <= n // 2:
            upper += 1
        words = SAY.get(key, lab)
        if rk == 1:
            top.append(words)
        elif rk == n:
            bottom.append(words)
    if not counted:
        return (f'Too few of these companies report the same figures to rank {esc(name)} '
                f'against them.')

    def join(items):
        items = [esc(i) for i in items]
        return items[0] if len(items) == 1 else ', '.join(items[:-1]) + ' and ' + items[-1]

    s = (f'Against these {len(companies) - 1} competitor{"s" if len(companies) != 2 else ""}, '
         f'<b>{esc(name)}</b> sits in the top half on {upper} of the {counted} measures that '
         f'at least three of them report.')
    if top:
        s += f' It is the best of the group on {join(top)}.'
    if bottom:
        s += f' It is the weakest on {join(bottom)}.'
    return s


def build(subject_key, subject, peers, sector_median, as_of):
    """subject and peers are feed entries (or Yahoo stand-ins marked _source='Yahoo')."""
    companies = [subject] + peers
    head = ['<th>Measure</th>']
    for i, c in enumerate(companies):
        tick = esc(c.get('ticker') or '')
        if c.get('_source') == 'Yahoo':
            name = f'{tick}<small>{esc((c.get("name") or "")[:22])}, Yahoo</small>'
        elif i == 0:
            name = f'{tick}<small>{esc((c.get("name") or "")[:22])}</small>'
        else:
            q = '&amp;'.join(f'{k}={esc(v)}' for k, v in (('ticker', c.get('ticker')),
                                                         ('isin', c.get('_key')),
                                                         ('ccy', c.get('ccy'))) if v)
            name = (f'<a href="?{q}" target="_self">{tick}</a>'
                    f'<small>{esc((c.get("name") or "")[:22])}</small>')
        head.append(f'<th class="{"me" if i == 0 else ""}">{name}</th>')
    head += ['<th>Rank</th>', '<th>Peer median</th>', '<th>Sector median</th>']

    body, rows = [], []
    for group, items in METRICS:
        body.append(f'<tr class="grp"><td colspan="{len(companies) + 4}">{esc(group)}</td></tr>')
        for lab, key, kind, higher in items:
            rk_map, n = ranks(companies, key, higher) if higher is not None else ({}, 0)
            cells = []
            for i, c in enumerate(companies):
                v = c.get(key)
                txt = minus(f(v, kind))
                if key in VALUATION and v is not None and v <= 0:
                    txt = 'loss'
                cls = ' '.join(x for x in ('me' if i == 0 else '',
                                           'best' if rk_map.get(i) == 1 and n >= 2 else '') if x)
                cells.append(f'<td class="num {cls}">{txt}</td>')
            rk = rk_map.get(0)
            rows.append((lab, key, rk, n))
            rank_txt = f'{ordinal(rk)} of {n}' if rk else 'n/a'
            peer_vals = [c.get(key) for c in peers if usable(key, c.get(key))]
            pm = median(peer_vals)
            sm = (sector_median or {}).get(key)
            fmt = (lambda v: minus(f(v, kind)))
            body.append(f'<tr><td class="lab">{esc(lab)}</td>{"".join(cells)}'
                        f'<td class="rk">{rank_txt if higher is not None else ""}</td>'
                        f'<td class="num">{fmt(pm)}</td>'
                        f'<td class="num">{fmt(sm) if key != "mcap" else ""}</td></tr>')

    yahoo = [c.get('ticker') for c in peers if c.get('_source') == 'Yahoo']
    notes = [f'TradingView figures as at {esc(as_of or "the latest feed")}, trailing twelve '
             f'months unless the measure says otherwise, the same figures the screener ranks on.',
             'Rank is this company\'s place among every company in the table that reports the '
             'measure, 1st being the best. Lower is better for P/E, forward P/E and debt to '
             'equity. A loss-making company has no P/E and is not ranked on it. The best value '
             'in each row is in green.',
             'Peer median is the middle value of the competitors shown, excluding this company. '
             'Sector median is the whole TradingView universe for its GICS sector, not only the '
             'names in the feed.',
             'Price returns are in each stock\'s own listing currency, so currency moves are '
             'part of any gap between them.']
    if yahoo:
        notes.append(f'{esc(", ".join(yahoo))} {"is" if len(yahoo) == 1 else "are"} not in the '
                     f'TradingView feed, so {"its" if len(yahoo) == 1 else "their"} figures come '
                     f'from Yahoo and may cover a different period. Yahoo does not publish ROIC, '
                     f'interest cover, Altman Z, Piotroski F, or year to date and five year '
                     f'returns, so those cells are empty.')

    return (CSS + '<div class="an"><div class="card comp"><h2>Competitors</h2>'
            f'<div class="sub">{esc(subject.get("name") or "")} against the companies chosen '
            f'above, measure by measure.</div>'
            f'<div class="read" style="margin:0 0 14px">{reading(subject, companies, rows)}</div>'
            f'<div class="wrap"><table><thead><tr>{"".join(head)}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>'
            f'<div class="cnote">{" ".join(notes)}</div></div></div>')
