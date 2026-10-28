"""
Stock cycle for one company, computed from its daily price history.

One rule, applied the same way to the past and to today, so the history and the current
reading can never disagree and a confirmed turning point never moves when new prices
arrive:

    A bull phase ends when the price closes the fall threshold below the highest close
    since the last trough. That high is then a confirmed peak.
    A bear phase ends when the price closes the rise threshold above the lowest close
    since the last peak. That low is then a confirmed trough.

The two are the same distance in log terms: a fall of F = T / (1 + T) is undone by a rise
of T. A 35% rise threshold therefore needs a 25.9% fall, not a 35% one, because a 35% fall
needs a 54% rise to recover. Using the same percentage both ways made bear phases much
harder to confirm than bull phases, which is how a stock 30% off its high could still read
as a bull phase.

The threshold is the stock's typical annual volatility over the last five years, kept between
15% and 35%, so a utility and a semiconductor are each measured on their own scale, and a
stock is measured as it trades now rather than as it traded just after listing.

The cycle is deliberately slow, so the page never shows it on its own. Next to it sits a
trend reading from the 200-day average, and the two are combined into one status: a bull
phase that has given back half its threshold, or whose trend has turned down, reads as
"correcting"; a bear phase that has recovered half its threshold, or whose trend has
turned up, reads as "rebounding". The status changes what the page says about today. It
never moves a confirmed turning point, so the history and every median are unaffected.

Before any of this is trusted, the price series is checked for gaps, frozen prices, jumps
that look like a missing split, stale data and short history, and the page states how
much weight the reading can bear.

Prices are traded prices: adjusted for splits but not for dividends. That keeps every level
on the page equal to a price that actually printed, so a support zone means what a trader
would expect it to mean, and every trigger ties out exactly to the high or low it comes
from. Dividends are added back separately when the holding return is measured.

Kept out of app.py so it can be tested without Streamlit, the same way risk.py is.
"""

import math

import numpy as np
import pandas as pd

import risk as rk
import stages as sg

THRESHOLD_FLOOR, THRESHOLD_CAP = 0.15, 0.35
ZONE_BAND = 0.04            # turning points within 4% of each other form one zone
MIN_DAYS = 504              # two years of trading days before anything is shown
MIN_CYCLES = 5              # below this many completed phases, averages are flagged as thin
OUTLIER_Z = 3.5             # robust z score above which a phase counts as extreme
MARKET_FALL = 0.20          # a benchmark fall this deep during a bear phase makes it market-wide
DAYS_PER_MONTH = 30.4375

THRESHOLD_YEARS = 5         # volatility measured over this many recent years
THRESHOLD_MULT = 1.0        # threshold = multiple x volatility; calibrate.py tests other values
LOG_SYMMETRIC = True        # fall threshold = T / (1 + T), the same log move as a rise of T


def fall_for(threshold):
    """The fall that ends a bull phase, for a rise threshold T."""
    return threshold / (1 + threshold) if LOG_SYMMETRIC else threshold

TREND_DAYS = 200            # the trend is the 200-day average of traded closes
TREND_SLOPE_DAYS = 21       # its direction is its change over the last month
TREND_FLAT = 0.005          # a change smaller than this either way counts as flat
CORRECTION_SHARE = 0.5      # half the threshold given back from the extreme
NEAR_TRIGGER = 0.05         # within 5% of the trigger counts as close to turning

JUMP = 0.40                 # a one-day move this large with no split recorded is suspect
FLAT_RUN = 10               # this many identical closes in a row looks like a frozen price
GAP_DAYS = 10               # calendar days between closes that counts as a hole in the data
STALE_DAYS = 7              # a latest close older than this is stale
SHORT_YEARS = 5             # less history than this is flagged as short

# Each listing is compared with its own market. Yahoo suffix -> (index symbol, name).
# Anything not listed, US listings included, uses the S&P 500.
BENCHMARKS = {
    '.NS': ('^NSEI', 'Nifty 50'), '.BO': ('^BSESN', 'BSE Sensex'),
    '.L': ('^FTSE', 'FTSE 100'), '.DE': ('^GDAXI', 'DAX'), '.F': ('^GDAXI', 'DAX'),
    '.PA': ('^FCHI', 'CAC 40'), '.AS': ('^AEX', 'AEX'), '.SW': ('^SSMI', 'SMI'),
    '.T': ('^N225', 'Nikkei 225'), '.HK': ('^HSI', 'Hang Seng'),
    '.TO': ('^GSPTSE', 'S&P/TSX Composite'), '.AX': ('^AXJO', 'S&P/ASX 200'),
    '.KS': ('^KS11', 'KOSPI'), '.SI': ('^STI', 'Straits Times Index'),
    '.SR': ('^TASI.SR', 'Tadawul All Share'),
}
DEFAULT_BENCHMARK = ('^GSPC', 'S&P 500')


def benchmark_for(symbol):
    """The index a listing is judged against for market-wide falls: (symbol, name)."""
    sym = str(symbol or '').upper()
    for suffix, bench in BENCHMARKS.items():
        if sym.endswith(suffix.upper()):
            return bench
    return DEFAULT_BENCHMARK


# ---------------------------------------------------------------- prices -----------------
def traded_prices(hist):
    """Split-adjusted closes with the dividend adjustment taken back out.

    Yahoo's adjusted close scales every price before an ex-dividend date by
    f = 1 - D / (close the day before). Walking the dividends from the latest backwards, the
    raw close the day before each ex-date is adjusted_close / (later factors) + D, which
    gives f exactly. Returns (traded closes, dividends per share), both on a plain date index.
    """
    close = rk.dated(hist['Close'])
    if close is None:
        return None, pd.Series(dtype=float)
    divs = pd.Series(dtype=float)
    if 'Dividends' in hist:
        d = rk.dated(hist['Dividends'])
        if d is not None:
            divs = d[d > 0]
    if divs.empty:
        return close, divs
    factor = pd.Series(1.0, index=close.index)
    later = 1.0
    for ex in sorted(divs.index, reverse=True):
        before = close.loc[:ex - pd.Timedelta(days=1)]
        if before.empty:
            continue
        amount = float(divs[ex])
        raw_prev = float(before.iloc[-1]) / later + amount
        if raw_prev <= amount:
            continue                         # a bad dividend record; leave the series alone
        f = 1 - amount / raw_prev
        factor[factor.index < ex] *= f
        later *= f
    return close / factor, divs


def threshold_for(close, years=THRESHOLD_YEARS, mult=THRESHOLD_MULT):
    """The stock's typical annual volatility over its recent years, times the multiple,
    kept between the floor and the cap.

    Measured year by year over the last few years and the median taken, so one crash year
    cannot set the scale, and the volatile first years after a listing do not set it for a
    stock that has since calmed down. Years are counted back from the latest close so the
    most recent one is complete. Returns (threshold, volatility).
    """
    r = np.log(close).diff().dropna()
    have = len(r) // 252
    if have >= 1:
        use = min(have, years) if years else have
        r = r.iloc[len(r) - use * 252:]
        vols = [float(r.iloc[i * 252:(i + 1) * 252].std()) * math.sqrt(252)
                for i in range(use)]
        vol = float(np.median(vols))
    else:
        vol = float(r.std()) * math.sqrt(252)
    return min(THRESHOLD_CAP, max(THRESHOLD_FLOOR, vol * mult)), vol


# ---------------------------------------------------------------- the walk ---------------
def turning_points(close, threshold):
    """One pass through the closes, oldest first. Nothing after a day is used on that day.

    Returns the confirmed turning points and the state of the open phase. Until the first
    turn there is no phase at all, because the history begins in the middle of one.
    """
    dates, vals = list(close.index), [float(v) for v in close.values]
    up, down = 1 + threshold, 1 - fall_for(threshold)
    state, points = None, []
    hi = lo = vals[0]
    hi_i = lo_i = 0

    def point(kind, at, i):
        return {'kind': kind, 'date': dates[at], 'price': vals[at],
                'confirm_date': dates[i], 'confirm_price': vals[i]}

    for i, v in enumerate(vals):
        if state is None:
            if v > hi:
                hi, hi_i = v, i
            if v < lo:
                lo, lo_i = v, i
            if v <= hi * down:
                points.append(point('peak', hi_i, i))
                state, lo, lo_i = 'bear', v, i
            elif v >= lo * up:
                points.append(point('trough', lo_i, i))
                state, hi, hi_i = 'bull', v, i
        elif state == 'bull':
            if v > hi:
                hi, hi_i = v, i
            elif v <= hi * down:
                points.append(point('peak', hi_i, i))
                state, lo, lo_i = 'bear', v, i
        else:
            if v < lo:
                lo, lo_i = v, i
            elif v >= lo * up:
                points.append(point('trough', lo_i, i))
                state, hi, hi_i = 'bull', v, i

    current = {'state': state, 'last_date': dates[-1], 'last_price': vals[-1]}
    if state == 'bull':
        current.update(extreme=hi, extreme_date=dates[hi_i], trigger=hi * down)
    elif state == 'bear':
        current.update(extreme=lo, extreme_date=dates[lo_i], trigger=lo * up)
    return points, current


def months_between(a, b):
    return (pd.Timestamp(b) - pd.Timestamp(a)).days / DAYS_PER_MONTH


def phases_from(points):
    """Every completed phase, from one confirmed turning point to the next."""
    out = []
    for a, b in zip(points[:-1], points[1:]):
        out.append({'kind': 'bull' if a['kind'] == 'trough' else 'bear',
                    'start': a['date'], 'end': b['date'],
                    'start_price': a['price'], 'end_price': b['price'],
                    'months': months_between(a['date'], b['date']),
                    'change': b['price'] / a['price'] - 1,
                    'extreme': False, 'market': None})
    return out


def dividends_between(divs, after, upto):
    if divs is None or divs.empty:
        return 0.0
    return float(divs[(divs.index > after) & (divs.index <= upto)].sum())


def holdings_from(points, divs):
    """What someone following the rule would actually have held: in on the day a bull phase
    was confirmed, out on the day the next bear phase was confirmed, at those closes."""
    out = []
    for a, b in zip(points[:-1], points[1:]):
        if a['kind'] != 'trough':
            continue
        entry, exit_ = a['confirm_price'], b['confirm_price']
        paid = dividends_between(divs, a['confirm_date'], b['confirm_date'])
        out.append({'entry_date': a['confirm_date'], 'exit_date': b['confirm_date'],
                    'entry': entry, 'exit': exit_, 'dividends': paid,
                    'months': months_between(a['confirm_date'], b['confirm_date']),
                    'price_return': exit_ / entry - 1,
                    'total_return': (exit_ + paid) / entry - 1,
                    'trough': a['date'], 'extreme': False})
    return out


# ---------------------------------------------------------------- extremes ---------------
def robust_z(values):
    """Distance from the median in units of the median absolute deviation, scaled so it
    reads like an ordinary z score. None when there is too little to judge."""
    x = np.asarray(values, dtype=float)
    if len(x) < MIN_CYCLES:
        return None
    med = np.median(x)
    mad = np.median(np.abs(x - med))
    if mad == 0:
        return None
    return 0.6745 * (x - med) / mad


def flag_extremes(phases):
    """Mark phases far outside this stock's normal depth or length, bull and bear judged
    separately. Prices are never removed; flagged phases are only left out of the medians."""
    for kind in ('bull', 'bear'):
        group = [p for p in phases if p['kind'] == kind]
        z_len = robust_z([math.log(max(p['months'], 0.25)) for p in group])
        z_size = robust_z([abs(math.log(1 + p['change'])) for p in group])
        for k, p in enumerate(group):
            if (z_len is not None and abs(z_len[k]) > OUTLIER_Z) or \
                    (z_size is not None and abs(z_size[k]) > OUTLIER_Z):
                p['extreme'] = True


def tag_market(phases, bench):
    """A bear phase is market-wide when the S&P 500 also fell at least 20% inside it."""
    b = rk.dated(bench) if bench is not None else None
    if b is None:
        return
    for p in phases:
        if p['kind'] != 'bear':
            continue
        w = b.loc[p['start']:p['end']]
        if len(w) < 5 or w.index[0] - p['start'] > pd.Timedelta(days=10):
            continue                         # the benchmark does not reach back that far
        fall = float((w / w.cummax() - 1).min())
        p['market'] = 'market-wide' if fall <= -MARKET_FALL else 'stock-specific'
        p['market_fall'] = fall


# ---------------------------------------------------------------- trend and status -------
def trend_of(close):
    """Where the latest close sits against its 200-day average, and which way that average
    is moving. None until there are enough closes to measure it."""
    if len(close) < TREND_DAYS + TREND_SLOPE_DAYS:
        return None
    sma = close.rolling(TREND_DAYS).mean()
    now, before = float(sma.iloc[-1]), float(sma.iloc[-1 - TREND_SLOPE_DAYS])
    last = float(close.iloc[-1])
    slope = now / before - 1
    slope_dir = 'rising' if slope > TREND_FLAT else 'falling' if slope < -TREND_FLAT else 'flat'
    above = last >= now
    if above and slope_dir != 'falling':
        direction = 'up'
    elif not above and slope_dir != 'rising':
        direction = 'down'
    else:
        direction = 'mixed'
    return {'sma': sma, 'level': now, 'gap': last / now - 1, 'slope': slope,
            'slope_dir': slope_dir, 'above': above, 'direction': direction}


def status_of(current, trend, threshold):
    """The one-line status the page leads with, and the reasons for it.

    The cycle says which big phase the stock is in. The qualifier says whether the price is
    currently moving with that phase or against it, judged two ways: how much of the
    threshold has been given back from the extreme, and which way the trend points."""
    state = current.get('state')
    if not state:
        return {'label': 'No phase yet', 'tone': '', 'qualifier': None, 'near': False,
                'reasons': []}
    trend_dir = trend['direction'] if trend else None
    move = abs(current['from_extreme'])
    need = fall_for(threshold) if state == 'bull' else threshold
    deep = move >= CORRECTION_SHARE * need
    reasons = []
    if state == 'bull':
        against = trend_dir == 'down'
        if deep:
            reasons.append(f'it is {move * 100:.0f}% below the swing high, more than half the '
                           f'{need * 100:.0f}% fall that would end the swing')
        if against:
            reasons.append('it is below a 200-day average that is no longer rising')
        qualifier = 'correcting' if (deep or against) else None
        tone = 'mixed' if qualifier else 'up'
    else:
        against = trend_dir == 'up'
        if deep:
            reasons.append(f'it is {move * 100:.0f}% above the swing low, more than half the '
                           f'{need * 100:.0f}% rise that would end the swing')
        if against:
            reasons.append('it is above a 200-day average that is no longer falling')
        qualifier = 'rebounding' if (deep or against) else None
        tone = 'mixed' if qualifier else 'down'
    near = abs(current['to_trigger']) <= NEAR_TRIGGER
    label = f'{state.title()} swing' + (f', {qualifier}' if qualifier else '')
    return {'label': label, 'tone': tone, 'qualifier': qualifier, 'near': near,
            'reasons': reasons}


# ---------------------------------------------------------------- data checks ------------
def data_checks(close, today=None):
    """Problems in the price series that would make the reading wrong rather than merely
    uncertain. Each is {'level': 'warn' or 'note', 'text': ...}."""
    out = []
    today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
    ratio = (close / close.shift(1)).dropna()
    jumps = ratio[(ratio > 1 + JUMP) | (ratio < 1 / (1 + JUMP))]
    if len(jumps):
        last = jumps.index[-1]
        out.append({'level': 'warn',
                    'text': f'{len(jumps)} one-day move{"s" if len(jumps) != 1 else ""} of more '
                            f'than {JUMP * 100:.0f}%, the latest on {last:%d %b %Y}. If that '
                            f'was a split or a consolidation Yahoo has not recorded, the cycle '
                            f'around it is wrong.'})
    same = (close.diff() == 0).astype(int)
    run = int(same.groupby((same == 0).cumsum()).cumsum().max() or 0) + 1
    if run >= FLAT_RUN:
        out.append({'level': 'warn',
                    'text': f'The close stayed exactly the same for {run} trading days in a '
                            f'row at one point, which usually means the stock did not trade '
                            f'or the price feed froze.'})
    gaps = pd.Series(close.index).diff().dt.days
    holes = int((gaps > GAP_DAYS).sum())
    if holes:
        out.append({'level': 'warn' if holes > 2 else 'note',
                    'text': f'{holes} gap{"s" if holes != 1 else ""} of more than {GAP_DAYS} '
                            f'days with no close, such as a suspension or missing data.'})
    age = (today - close.index[-1]).days
    if age > STALE_DAYS:
        out.append({'level': 'warn',
                    'text': f'The latest close is from {close.index[-1]:%d %b %Y}, {age} days '
                            f'ago. The reading describes that date, not today.'})
    years = (close.index[-1] - close.index[0]).days / 365.25
    if years < SHORT_YEARS:
        out.append({'level': 'note',
                    'text': f'Only {years:.1f} years of history, so few full cycles can have '
                            f'happened yet.'})
    return out


def confidence_of(r):
    """How much weight the stage reading can bear: High, Medium or Low, with the reasons.

    Low when the price data itself is suspect. Medium when the reading is sound but thin
    or unsettled: little stage history to learn from, a breakout still being tested, the
    price close to a level that would change the stage, or the current week reading
    differently from the last finished one."""
    low, medium = [], []
    for c in r['checks']:
        if c['level'] == 'warn':
            low.append(c['text'])
    sgr = r.get('stage') or {}
    if sgr.get('error') or not sgr:
        medium.append('not enough weekly history for a stage reading')
    else:
        sc = sgr['current']
        total = sum(sgr['stats'][sc['stage']]['next'].values())
        if total < sg.MIN_CASES:
            medium.append(f'{"no" if total == 0 else "only " + str(total)} past '
                          f'exit{"s" if total != 1 else ""} from Stage {sc["stage"]} in the record '
                          f'to learn what usually comes next')
        t = sc.get('testing')
        if t:
            word = 'breakout' if t['dir'] == 'up' else 'breakdown'
            medium.append(f'the {word} of the week of {t["week"]:%d %b %Y} is still being '
                          f'tested and could fail back to Stage {t["from"]}')
        for g in sc['triggers']:
            if abs(g['distance']) <= NEAR_TRIGGER:
                medium.append(f'the price is within {NEAR_TRIGGER * 100:.0f}% of the level that '
                              f'would turn it to {g["name"]}')
        run = sc.get('running')
        if run and run['raw'] and run['raw'] != sc['raw']:
            medium.append('this week so far reads differently from the last finished week')
    level = 'Low' if low else 'Medium' if medium else 'High'
    return {'level': level, 'reasons': low + medium}


# ---------------------------------------------------------------- statistics -------------
def describe(values):
    x = [v for v in values if v is not None and not math.isnan(v)]
    if not x:
        return {'n': 0, 'median': None, 'p25': None, 'p75': None}
    return {'n': len(x), 'median': float(np.median(x)),
            'p25': float(np.percentile(x, 25)), 'p75': float(np.percentile(x, 75))}


def typical(phases, holdings, exclude_extremes):
    keep = [p for p in phases if not (exclude_extremes and p['extreme'])]
    hold = [h for h in holdings if not (exclude_extremes and h['extreme'])]
    bull = [p for p in keep if p['kind'] == 'bull']
    bear = [p for p in keep if p['kind'] == 'bear']
    return {'bull_months': describe([p['months'] for p in bull]),
            'bull_change': describe([p['change'] for p in bull]),
            'bear_months': describe([p['months'] for p in bear]),
            'bear_change': describe([p['change'] for p in bear]),
            'hold_months': describe([h['months'] for h in hold]),
            'hold_total': describe([h['total_return'] for h in hold]),
            'hold_price': describe([h['price_return'] for h in hold]),
            'hold_won': (sum(1 for h in hold if h['total_return'] > 0), len(hold))}


# ---------------------------------------------------------------- support / resistance ---
def zones_from(points, phases, current):
    """Turning point prices grouped into zones no wider than ZONE_BAND.

    A peak and a trough at the same level share a zone, because a level that capped the price
    once and later held it up is the same level. Every turning point inside a zone counts as
    the zone holding. A later phase that ran straight through the zone, starting on one side
    and ending on the other, counts as the zone breaking.
    """
    if not points:
        return []
    ordered = sorted(points, key=lambda p: p['price'])
    groups, cur = [], [ordered[0]]
    for p in ordered[1:]:
        if p['price'] <= cur[0]['price'] * (1 + ZONE_BAND):
            cur.append(p)
        else:
            groups.append(cur)
            cur = [p]
    groups.append(cur)

    moves = [(p['start'], p['start_price'], p['end_price']) for p in phases]
    if points and current.get('state'):
        moves.append((points[-1]['date'], points[-1]['price'], current['last_price']))

    zones = []
    for g in groups:
        low, high = g[0]['price'], g[-1]['price']
        first = min(p['date'] for p in g)
        breaks = sum(1 for start, a, b in moves
                     if start >= first and min(a, b) < low and max(a, b) > high)
        zones.append({'low': low, 'high': high,
                      'troughs': sum(1 for p in g if p['kind'] == 'trough'),
                      'peaks': sum(1 for p in g if p['kind'] == 'peak'),
                      'holds': len(g), 'breaks': breaks,
                      'last': max(p['date'] for p in g)})
    return zones


def nearest_zones(zones, price):
    below = [z for z in zones if z['high'] < price]
    above = [z for z in zones if z['low'] > price]
    inside = [z for z in zones if z['low'] <= price <= z['high']]
    return (max(below, key=lambda z: z['high']) if below else None,
            min(above, key=lambda z: z['low']) if above else None,
            inside[0] if inside else None)


# ---------------------------------------------------------------- everything -------------
def analyse(hist, bench=None, threshold=None, bench_name=None, today=None,
            threshold_mult=THRESHOLD_MULT):
    """The whole cycle reading for one stock. Every figure on the page comes from here.

    hist       Yahoo daily history with Close and, if available, Dividends
    bench      closes of the listing's own market index (benchmark_for), for tagging
               market-wide bear phases; optional
    threshold  fixed threshold for tests; normally worked out from the stock itself
    bench_name the index's name, for the page
    today      the date the data checks measure staleness against; defaults to today
    threshold_mult  multiple of volatility used for the threshold; calibrate.py varies it
    """
    if hist is None or 'Close' not in hist:
        return {'error': 'No price history arrived from Yahoo.'}
    close, divs = traded_prices(hist)
    if close is None or len(close) < MIN_DAYS:
        n = 0 if close is None else len(close)
        return {'error': f'Only {n} trading days of history. The cycle needs at least two '
                         f'years before it can say anything.'}

    vol = None
    if threshold is None:
        threshold, vol = threshold_for(close, mult=threshold_mult)
    points, current = turning_points(close, threshold)
    phases = phases_from(points)
    holdings = holdings_from(points, divs)
    flag_extremes(phases)
    extreme_troughs = {p['start'] for p in phases if p['kind'] == 'bull' and p['extreme']}
    for h in holdings:
        h['extreme'] = h['trough'] in extreme_troughs
    tag_market(phases, bench)

    # the open phase, from the last confirmed turn to the latest close
    if points:
        last = points[-1]
        current['start'] = last['date']
        current['start_price'] = last['price']
        current['confirm_date'] = last['confirm_date']
        current['confirm_price'] = last['confirm_price']
        current['months'] = months_between(last['date'], current['last_date'])
        current['change'] = current['last_price'] / last['price'] - 1
        current['from_extreme'] = current['last_price'] / current['extreme'] - 1
        current['to_trigger'] = current['trigger'] / current['last_price'] - 1
        if current['state'] == 'bull':
            paid = dividends_between(divs, last['confirm_date'], current['last_date'])
            current['held_months'] = months_between(last['confirm_date'],
                                                    current['last_date'])
            current['held_return'] = ((current['last_price'] + paid)
                                      / last['confirm_price'] - 1)

    zones = zones_from(points, phases, current)
    support, resistance, inside = nearest_zones(zones, current['last_price'])
    trend = trend_of(close)
    r = {'close': close, 'dividends': divs, 'threshold': threshold, 'vol': vol,
         'points': points, 'phases': phases, 'holdings': holdings, 'current': current,
         'all': typical(phases, holdings, False), 'clean': typical(phases, holdings, True),
         'extremes': sum(1 for p in phases if p['extreme']),
         'zones': zones, 'support': support, 'resistance': resistance, 'inside': inside,
         'has_dividends': not divs.empty, 'bench_ok': bench is not None,
         'bench_name': bench_name or DEFAULT_BENCHMARK[1],
         'threshold_years': min(THRESHOLD_YEARS, max(1, (len(close) - 1) // 252)),
         'first_date': close.index[0], 'last_date': close.index[-1],
         'trend': trend, 'status': status_of(current, trend, threshold),
         'checks': data_checks(close, today),
         'fall': fall_for(threshold)}
    r['stage'] = sg.analyse(close, today)
    if not r['stage'].get('error'):
        r['outlook'] = sg.outlook(r['stage'], support, resistance)
    r['confidence'] = confidence_of(r)
    return r
