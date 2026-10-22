"""
The scorecard behind the opinion on the company page.

Every measure is turned into a 0 to 100 score against the company's own sector, using the
sector quartiles in sector_stats.json, so a bank is compared with banks and a software
company with software companies. Scores roll up into five pillars, the pillars into one
overall score, and the overall score into Buy, Hold or Sell. Red flags cap the opinion.

    momentum(close)                       -> trend stage from the full daily history
    score(tv, stats, info, risk, qoe_rows, forensics, dupont_rows) -> dict
"""

import math

import pandas as pd

FINANCIAL = ('Financials',)
WEIGHTS = {'Quality': 30, 'Financial strength': 20, 'Valuation': 25, 'Momentum': 15,
           'Signals': 10}
BUY_AT, SELL_BELOW = 70, 45


def _num(v):
    try:
        v = float(v)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def sector_pct(value, block, higher=True):
    """Where a value sits in its sector, 0 to 100, from the quartiles. Beyond the quartiles
    the score keeps moving, but more slowly, and stops at 3 and 97."""
    v = _num(value)
    if v is None or not block:
        return None
    p25, p50, p75 = (_num(block.get(k)) for k in ('p25', 'median', 'p75'))
    if None in (p25, p50, p75):
        return None
    spread = max(abs(p75 - p25), 1e-9)
    if v <= p25:
        pct = 25 - 22 * min(1.0, (p25 - v) / spread)
    elif v <= p50:
        pct = 25 + 25 * (v - p25) / max(p50 - p25, 1e-9)
    elif v <= p75:
        pct = 50 + 25 * (v - p50) / max(p75 - p50, 1e-9)
    else:
        pct = 75 + 22 * min(1.0, (v - p75) / spread)
    return round(pct if higher else 100 - pct, 1)


def where(pct):
    return ('in the best quarter of its sector' if pct >= 75 else
            'better than its sector median' if pct >= 50 else
            'worse than its sector median' if pct >= 25 else 'in the worst quarter of its sector')


def cheap(pct):
    return ('in the cheapest quarter of its sector' if pct >= 75 else
            'cheaper than its sector median' if pct >= 50 else
            'dearer than its sector median' if pct >= 25 else 'in the dearest quarter of its sector')


# ------------------------------------------------------------------ momentum -----------
def momentum(close, bench=None):
    """Trend stage from the full history: where the price sits against its 50 and 200 day
    averages, when the 50 day last crossed the 200 day, and how stretched it is."""
    if close is None:
        return None
    s = pd.Series(close).dropna().astype(float)
    if len(s) < 220:
        return None
    m50, m200 = s.rolling(50).mean(), s.rolling(200).mean()
    px, a, b = float(s.iloc[-1]), float(m50.iloc[-1]), float(m200.iloc[-1])
    above = (m50 > m200).astype(int).dropna()
    flips = above.diff().fillna(0)
    last_up = flips[flips > 0].index[-1] if (flips > 0).any() else None
    days_since = int((above.index[-1] - last_up).days) if last_up is not None and above.iloc[-1] == 1 else None
    delta = s.diff()
    up, dn = delta.clip(lower=0).ewm(alpha=1 / 14).mean(), (-delta.clip(upper=0)).ewm(alpha=1 / 14).mean()
    rsi = float(100 - 100 / (1 + up.iloc[-1] / dn.iloc[-1])) if dn.iloc[-1] else 100.0
    stretch = (px / a - 1) * 100
    r3 = (px / float(s.iloc[-64]) - 1) * 100 if len(s) > 64 else None
    r6 = (px / float(s.iloc[-127]) - 1) * 100 if len(s) > 127 else None
    accel = r3 is not None and r6 is not None and r3 > 0 and r3 > r6 / 2
    if px > a and a > b and days_since is not None and days_since <= 90 and stretch <= 15:
        stage, base = 'Early', 80
        text = (f'The 50 day average crossed above the 200 day {days_since} days ago and the '
                f'price is {stretch:.0f}% above its 50 day: an uptrend in its early stage.')
    elif px > a * 1.25 or (rsi > 75 and px > a):
        stage, base = 'Extended', 50
        text = (f'The price is {stretch:.0f}% above its 50 day average with an RSI of {rsi:.0f}: '
                f'strong, but stretched.')
    elif px > a and a > b:
        stage, base = 'Established', 70
        text = ('Above both averages with the 50 day over the 200 day'
                + (f' since {days_since} days ago' if days_since else '') + ': an established uptrend.')
    elif px < a and a < b:
        stage, base = 'Downtrend', 20
        text = 'Below both averages with the 50 day under the 200 day: a downtrend.'
    else:
        stage, base = 'No clear trend', 45
        text = 'Between its averages: no clear trend either way.'
    if accel and stage in ('Early', 'Established', 'No clear trend'):
        base += 5
        text += ' The last three months are ahead of the six month pace.'
    return {'stage': stage, 'score': base, 'text': text, 'rsi': round(rsi, 1),
            'stretch_pct': round(stretch, 1), 'days_since_cross': days_since}


# ------------------------------------------------------------------ the score ----------
def score(tv, stats, info, risk, qoe_rows, forensics, dupont_rows):
    stats, info, risk = stats or {}, info or {}, risk or {}
    gics = tv.get('gics')
    fin = gics in FINANCIAL
    items = {p: [] for p in WEIGHTS}       # (score, sentence)
    expected = 0

    def rel(pillar, key, label, kind, higher=True):
        nonlocal expected
        expected += 1
        v = _num(tv.get(key))
        if v is None:
            return
        p = sector_pct(v, stats.get(key), higher)
        if p is None:
            return
        shown = f'{v:.1f}%' if kind == 'pct' else f'{v:.1f}x' if kind == 'x' else f'{v:.2f}'
        items[pillar].append((p, f'{label} of {shown} is {where(p)}'))

    # quality
    if fin:
        rel('Quality', 'roe', 'Return on equity', 'pct')
        rel('Quality', 'roa', 'Return on assets', 'pct')
        rel('Quality', 'net_margin', 'Net margin', 'pct')
    else:
        rel('Quality', 'roic', 'Return on invested capital', 'pct')
        rel('Quality', 'op_margin', 'Operating margin', 'pct')
        rel('Quality', 'fcf_margin', 'Free cash flow margin', 'pct')
        usable = [r['cfo_to_ni'] for r in (qoe_rows or []) if r.get('cfo_to_ni') is not None]
        expected += 1
        if len(usable) >= 2:
            avg = sum(usable) / len(usable)
            sc = 85 if avg >= 1.2 else 70 if avg >= 1.0 else 45 if avg >= 0.8 else 20
            items['Quality'].append((sc, f'Operating cash flow averaged {avg:.2f} times profit'))

    # financial strength
    if not fin:
        expected += 1
        de = _num(tv.get('debt_equity'))
        if de is not None:
            if de < 0:
                items['Financial strength'].append((10, 'Shareholders\' equity is negative'))
            else:
                p = sector_pct(de, stats.get('debt_equity'), higher=False)
                if p is not None:
                    items['Financial strength'].append((p, f'Debt to equity of {de:.2f} is {where(p)}'))
        rel('Financial strength', 'interest_cover', 'Interest cover', 'x')
        expected += 1
        z = _num(tv.get('altman_z'))
        if z is not None and gics != 'Real Estate':
            sc = 85 if z > 3 else 50 if z >= 1.8 else 15
            items['Financial strength'].append(
                (sc, f'Altman Z of {z:.2f} is in the {"safe" if z > 3 else "grey" if z >= 1.8 else "distress"} zone'))
    expected += 1
    pf = _num(tv.get('piotroski_f'))
    if pf is not None:
        items['Financial strength'].append((pf / 9 * 100, f'Piotroski score of {pf:.0f} of 9'))

    # valuation
    expected += 1
    pe = _num(tv.get('pe'))
    if pe is not None:
        if pe <= 0:
            items['Valuation'].append((15, 'Loss making, so there are no earnings to value'))
        else:
            p = sector_pct(pe, stats.get('pe'), higher=False)
            if p is not None:
                items['Valuation'].append((p, f'A P/E of {pe:.1f} is {cheap(p)}'))
    expected += 1
    fpe = _num(tv.get('fpe'))
    if fpe is not None and fpe > 0:
        p = sector_pct(fpe, stats.get('fpe'), higher=False)
        if p is not None:
            note = (' and below the trailing P/E, so earnings are expected to grow'
                    if pe and pe > 0 and fpe < pe * 0.9 else '')
            items['Valuation'].append((min(97, p + (5 if note else 0)),
                                       f'A forward P/E of {fpe:.1f} is {cheap(p)}{note}'))

    # momentum
    expected += 1
    mo = risk.get('momentum')
    if mo:
        sc = mo['score']
        rel1 = ((risk.get('windows') or {}).get('1Y') or {}).get('relative_pts')
        if rel1 is not None:
            sc = max(3, min(97, sc + max(-15, min(15, rel1 / 2))))
        items['Momentum'].append((sc, mo['text'] + (
            f' Over the last year it ran {abs(rel1):.0f} points {"ahead of" if rel1 > 0 else "behind"} '
            f'the S&P 500.' if rel1 is not None and abs(rel1) >= 5 else '')))

    # signals: optional extras, so they never count towards data coverage
    if tv.get('marquee'):
        n = _num(tv.get('marquee_investors')) or 1
        items['Signals'].append((70 if n >= 2 else 62, f'Held by {n:.0f} superinvestor'
                                                         f'{"s" if n != 1 else ""} tracked on Dataroma'))
    n_an, tgt = _num(info.get('numberOfAnalystOpinions')), _num(info.get('targetMeanPrice'))
    px = _num(info.get('currentPrice') or info.get('regularMarketPrice'))
    if n_an and n_an >= 4 and tgt and px:
        up = (tgt / px - 1) * 100
        sc = 80 if up > 20 else 65 if up > 5 else 50 if up > -5 else 30
        items['Signals'].append((sc, f'{n_an:.0f} analysts see {up:+.0f}% to their average target'))
    sp = _num(info.get('shortPercentOfFloat'))
    if sp is not None:
        sp *= 100
        if sp > 8:
            items['Signals'].append((25, f'Short interest is high at {sp:.1f}% of float'))
        elif sp < 3:
            items['Signals'].append((60, f'Short interest is low at {sp:.1f}% of float'))

    # roll up
    pillars, total_w, total = {}, 0, 0.0
    available = 0
    for p, w in WEIGHTS.items():
        xs = items[p]
        if p != 'Signals':
            available += len(xs)
        if not xs:
            pillars[p] = None
            continue
        val = sum(x[0] for x in xs) / len(xs)
        best, worst = max(xs, key=lambda x: x[0]), min(xs, key=lambda x: x[0])
        pillars[p] = {'score': round(val), 'best': best[1], 'worst': worst[1],
                      'items': [{'score': round(a), 'text': b} for a, b in xs]}
        total += val * w
        total_w += w
    coverage = min(1.0, available / max(expected, 1))
    overall = round(total / total_w) if total_w else None

    flags = []
    bm = _num(((forensics or {}).get('beneish') or {}).get('score'))
    if bm is not None and bm > -1.78:
        flags.append(f'Beneish M-score of {bm:.2f} flags possible earnings manipulation')
    z = _num(tv.get('altman_z'))
    if not fin and gics != 'Real Estate' and z is not None and z < 1.8:
        flags.append(f'Altman Z of {z:.2f} is in the distress zone')
    usable = [r['cfo_to_ni'] for r in (qoe_rows or []) if r.get('cfo_to_ni') is not None]
    if not fin and len(usable) >= 2 and sum(usable) / len(usable) < 0.7:
        flags.append('Profit is not turning into cash')
    if dupont_rows and dupont_rows[-1].get('net_margin_pct') is not None and \
            dupont_rows[-1]['net_margin_pct'] <= 0:
        flags.append(f'The latest year ({dupont_rows[-1]["period"]}) was a loss')

    if overall is None or coverage < 0.5:
        opinion = 'Insufficient data'
    else:
        opinion = 'Buy' if overall >= BUY_AT else 'Sell' if overall < SELL_BELOW else 'Hold'
    capped = False
    if opinion == 'Buy' and flags:
        opinion, capped = 'Hold', True

    every = [(a, b) for xs in items.values() for a, b in xs]
    lifts = [b for a, b in sorted(every, key=lambda x: -x[0]) if a >= 65][:3]
    # Holding it back: the clear weaknesses first (bottom third of the sector), then the
    # softer ones (below the sector median), so a strong company still shows where it is
    # weakest. Only when nothing is below the median does it say so, naming the weakest reading.
    ranked = sorted(every, key=lambda x: x[0])
    drags = [b for a, b in ranked if a <= 35][:3]
    drags += [b for a, b in ranked if 35 < a < 50][:3 - len(drags)]
    if coverage < 0.75 and len(drags) < 3:
        drags.append(f'Only {round(coverage * 100)}% of the expected figures were available, '
                     f'so the score rests on a partial picture')
    if not drags and ranked:
        a, b = ranked[0]
        drags = [f'Nothing is below its sector median. The weakest reading: '
                 f'{b[0].lower() + b[1:]}']
    return {'overall': overall, 'opinion': opinion, 'capped': capped, 'flags': flags,
            'pillars': pillars, 'weights': WEIGHTS, 'coverage': round(coverage * 100),
            'lifts': lifts, 'drags': drags, 'momentum': mo}
