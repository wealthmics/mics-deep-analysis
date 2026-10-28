"""
The stage a stock is in now, and what has usually come next for it.

The cycle in cycle.py dates the big swings of the past. It is right for history but slow
by design: a peak is only known once the price has fallen a long way from it. This module
answers the other question, where the stock is now, with the four-stage model
practitioners use (Weinstein):

    Stage 1  Basing      after a decline, the 30-week average flattens and price hovers
    Stage 2  Advancing   price above a rising 30-week average
    Stage 3  Topping     after an advance, the 30-week average flattens and price hovers
    Stage 4  Declining   price below a falling 30-week average

Rules, all on completed weekly closes so nothing is decided on a half-finished week:

    Each week reads up (close above a rising average), down (close below a falling one)
    or neutral (anything else). The average counts as flat while its five-week change is
    smaller than a quarter of the stock's own five-week volatility, so a utility and a
    chip stock are judged on their own scale.

    A stage changes only after CONFIRM_WEEKS weeks in a row point the same way, so one
    odd week cannot flip it. From Stage 2, weeks that stop reading up move it to Stage 3,
    or straight to Stage 4 if they all read down. From Stage 4, weeks that stop reading
    down move it to Stage 1, or straight to Stage 2 if they all read up. From Stages 1 and
    3, weeks that all read up give Stage 2 and weeks that all read down give Stage 4, but
    only once the close also breaks out of the range of that base or top: above its
    highest weekly close for Stage 2, below its lowest for Stage 4. The range includes the
    13 weeks before the base or top began, so the low of the decline is the floor of the
    base and the high of the advance is the ceiling of the top. A sideways stock that
    drifts with its average therefore stays a base or a top until it actually breaks out.

    A stage once decided is never changed by later prices, so the history and today can
    never disagree. The first stage in the record is a guess from where the history
    starts, and is left out of every statistic.

The outlook is built only from this stock's own past stages, with the count of cases next
to every figure, plus the exact price levels that would change the stage. It describes
what happened before. It does not forecast.
"""

import math

import numpy as np
import pandas as pd

MA_WEEKS = 30
SLOPE_WEEKS = 5
VOL_WEEKS = 52
FLAT_SHARE = 0.25           # flat while the 5-week change is under this share of 5-week vol
FLAT_FLOOR = 0.005          # and never narrower than 0.5%
CONFIRM_WEEKS = 2
BOX_LOOKBACK = 13           # a base or top's range includes the 13 weeks before it began,
                            # so the low of the decline is the floor of the base
FORWARD_WEEKS = (13, 26)    # what the price did over the next quarter and half year
MIN_CASES = 3               # below this, the page says the history is too thin to lean on
EMA_DAYS = 50
SMA_DAYS = 200

NAMES = {1: 'Basing', 2: 'Advancing', 3: 'Topping', 4: 'Declining'}
TONE = {1: 'mixed', 2: 'up', 3: 'mixed', 4: 'down'}
MEANING = {
    1: 'The fall has stopped and the price is moving sideways while the 30-week average '
       'flattens. Sellers are no longer in control, but buyers have not taken over either.',
    2: 'The price is above a rising 30-week average. Buyers are in control and dips have so '
       'far been bought.',
    3: 'After an advance, the 30-week average has flattened and the price is moving '
       'sideways around it. The uptrend has lost its push.',
    4: 'The price is below a falling 30-week average. Sellers are in control and rallies '
       'have so far been sold.',
}


# ---------------------------------------------------------------- weekly series ----------
def weekly(close, today=None):
    """Last close of each week. The latest week is dropped while it is still running, so
    a stage is only ever decided on a finished week. Returns (completed weeks, the running
    week's latest close or None)."""
    w = close.resample('W-FRI').last().dropna()
    today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
    running = None
    if len(w) and w.index[-1] > today:
        running = (close.index[-1], float(close.iloc[-1]))
        w = w.iloc[:-1]
    return w, running


def frame(w):
    """The weekly table every reading is made from."""
    ma = w.rolling(MA_WEEKS).mean()
    slope = ma / ma.shift(SLOPE_WEEKS) - 1
    vol = np.log(w).diff().rolling(VOL_WEEKS, min_periods=26).std() * math.sqrt(SLOPE_WEEKS)
    band = np.maximum(FLAT_FLOOR, FLAT_SHARE * vol)
    raw = pd.Series('neutral', index=w.index)
    raw[(w > ma) & (slope > band)] = 'up'
    raw[(w < ma) & (slope < -band)] = 'down'
    raw[ma.isna() | slope.isna() | band.isna()] = None
    return pd.DataFrame({'close': w, 'ma': ma, 'slope': slope, 'band': band, 'raw': raw})


def read_one(close, ma, slope, band):
    if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in (ma, slope, band)):
        return None
    if close > ma and slope > band:
        return 'up'
    if close < ma and slope < -band:
        return 'down'
    return 'neutral'


# ---------------------------------------------------------------- the stage walk ---------
def walk(df):
    """Stage for every completed week, oldest first. Nothing after a week is used on it."""
    stages, stage, began = [], None, 0
    raws = list(df['raw'])
    closes = list(df['close'])
    for i, r in enumerate(raws):
        if r is None:
            stages.append(None)
            continue
        if stage is None:
            if r == 'up':
                stage = 2
            elif r == 'down':
                stage = 4
            else:
                back = closes[max(0, i - 26)]
                stage = 3 if closes[i] > back else 1
            began = i
            stages.append(stage)
            continue
        recent = raws[i - CONFIRM_WEEKS + 1:i + 1] if i >= CONFIRM_WEEKS - 1 else []
        recent = [x for x in recent if x is not None]
        if len(recent) == CONFIRM_WEEKS:
            all_up = all(x == 'up' for x in recent)
            all_down = all(x == 'down' for x in recent)
            none_up = all(x != 'up' for x in recent)
            none_down = all(x != 'down' for x in recent)
            before = stage
            if stage == 2:
                stage = 4 if all_down else 3 if none_up else 2
            elif stage == 4:
                stage = 2 if all_up else 1 if none_down else 4
            else:
                box = closes[max(0, began - BOX_LOOKBACK):i - CONFIRM_WEEKS + 1]
                if all_up and (not box or closes[i] > max(box)):
                    stage = 2
                elif all_down and (not box or closes[i] < min(box)):
                    stage = 4
            if stage != before:
                began = i
        stages.append(stage)
    out = df.copy()
    out['stage'] = stages
    return out


def episodes(df):
    """Each run of one stage: start and end week, weeks, prices. The first is marked
    'first' because its start is only where the record begins; the last is open."""
    s = df.dropna(subset=['stage'])
    out = []
    for when, row in s.iterrows():
        st = int(row['stage'])
        if out and out[-1]['stage'] == st:
            out[-1].update(end=when, end_price=float(row['close']))
            out[-1]['weeks'] += 1
        else:
            out.append({'stage': st, 'start': when, 'end': when, 'weeks': 1,
                        'start_price': float(row['close']), 'end_price': float(row['close']),
                        'first': not out, 'open': False})
    if out:
        out[-1]['open'] = True
    return out


# ---------------------------------------------------------------- statistics -------------
def history(df, eps):
    """What this stock's past stages looked like and what followed each of them."""
    closes = df['close']
    idx = list(closes.index)
    pos = {d: k for k, d in enumerate(idx)}
    stats = {}
    for st in NAMES:
        done = [e for e in eps if e['stage'] == st and not e['first'] and not e['open']]
        nexts = {}
        for a, b in zip(eps[:-1], eps[1:]):
            if a['stage'] == st and not a['first']:
                nexts[b['stage']] = nexts.get(b['stage'], 0) + 1
        fwd = {}
        for h in FORWARD_WEEKS:
            vals = []
            for e in eps:
                if e['stage'] != st or e['first']:
                    continue
                k = pos[e['start']]
                if k + h < len(idx):
                    vals.append(float(closes.iloc[k + h]) / e['start_price'] - 1)
            fwd[h] = describe(vals, positive=True)
        weeks = [e['weeks'] for e in done]
        stats[st] = {'count': len(done), 'weeks': describe(weeks), 'next': nexts,
                     'forward': fwd}
    return stats


def describe(vals, positive=False):
    x = [v for v in vals if v is not None and not math.isnan(v)]
    if not x:
        return {'n': 0, 'median': None, 'p25': None, 'p75': None, 'up': None}
    d = {'n': len(x), 'median': float(np.median(x)), 'p25': float(np.percentile(x, 25)),
         'p75': float(np.percentile(x, 75)), 'up': None}
    if positive:
        d['up'] = sum(1 for v in x if v > 0)
    return d


# ---------------------------------------------------------------- everything -------------
def analyse(close, today=None):
    """The stage reading for one stock from its daily traded closes."""
    w, running = weekly(close, today)
    if len(w) < MA_WEEKS + SLOPE_WEEKS + CONFIRM_WEEKS:
        return {'error': f'Only {len(w)} completed weeks. A stage needs about '
                         f'{MA_WEEKS + SLOPE_WEEKS + CONFIRM_WEEKS} weeks of history.'}
    df = walk(frame(w))
    eps = episodes(df)
    if not eps:
        return {'error': 'No stage could be read from this history.'}
    stats = history(df, eps)
    last = df.iloc[-1]
    cur = dict(eps[-1])
    k0 = df.index.get_loc(cur['start'])
    since = df.iloc[max(0, k0 - BOX_LOOKBACK):] if cur['stage'] in (1, 3) else df.iloc[k0:]
    cur.update(ma=float(last['ma']), slope=float(last['slope']), band=float(last['band']),
               raw=last['raw'], week=df.index[-1], close=float(last['close']),
               range_high=float(since['close'].max()), range_low=float(since['close'].min()),
               name=NAMES[cur['stage']], tone=TONE[cur['stage']])
    cur['to_ma'] = cur['ma'] / cur['close'] - 1
    if running is not None:
        r = read_one(running[1], cur['ma'], cur['slope'], cur['band'])
        cur['running'] = {'date': running[0], 'close': running[1], 'raw': r}

    daily = close
    ema = daily.ewm(span=EMA_DAYS, adjust=False).mean()
    sma = daily.rolling(SMA_DAYS).mean()
    last_px = float(daily.iloc[-1])
    short = {'ema': ema, 'sma': sma, 'ema_level': float(ema.iloc[-1]),
             'sma_level': float(sma.iloc[-1]) if not math.isnan(sma.iloc[-1]) else None,
             'price': last_px}
    short['above_ema'] = last_px >= short['ema_level']
    short['to_ema'] = short['ema_level'] / last_px - 1
    if short['sma_level'] is not None:
        short['ema_over_sma'] = short['ema_level'] >= short['sma_level']
        cross = (ema > sma).astype(int).diff().fillna(0)
        cross = cross[sma.notna()]
        last_cross = cross[cross != 0]
        short['cross_date'] = last_cross.index[-1] if len(last_cross) else None
        short['cross_kind'] = (None if not len(last_cross) else
                               'golden' if last_cross.iloc[-1] > 0 else 'death')
    hi52 = float(daily.loc[daily.index[-1] - pd.Timedelta(days=365):].max())
    lo52 = float(daily.loc[daily.index[-1] - pd.Timedelta(days=365):].min())
    short.update(high52=hi52, low52=lo52, from_high52=last_px / hi52 - 1,
                 from_low52=last_px / lo52 - 1)
    ma_daily = df['ma'].reindex(daily.index, method='ffill')
    return {'weekly': df, 'episodes': eps, 'stats': stats, 'current': cur, 'short': short,
            'ma_daily': ma_daily}


# ---------------------------------------------------------------- the outlook ------------
def _p(x):
    return f'{x:,.2f}'


def _pc(x, sign=True):
    s = f'{x * 100:+.1f}%' if sign else f'{abs(x) * 100:.1f}%'
    return s


def _times(n):
    return f'{n} time{"s" if n != 1 else ""}'


def outlook(s, swing=None, support=None, resistance=None):
    """Plain sentences on what usually came next for this stock and what would change the
    stage, with the price levels. swing is cycle.py's current phase, if any; support and
    resistance are its nearest zones. Returns a dict of lists of sentences."""
    cur, st, sh = s['current'], s['stats'], s['short']
    stage = cur['stage']
    hist = st[stage]
    out = {'now': [], 'next': [], 'up': [], 'down': [], 'caveat': []}

    out['now'].append(f'Stage {stage}, {cur["name"]}. {MEANING[stage]}')
    typ = hist['weeks']
    if typ['n']:
        share = cur['weeks'] / typ['median'] if typ['median'] else None
        line = (f'This stage has lasted {cur["weeks"]} week{"s" if cur["weeks"] != 1 else ""} '
                f'so far. Past Stage {stage} runs for this stock lasted a median of '
                f'{typ["median"]:.0f} weeks (middle half {typ["p25"]:.0f} to {typ["p75"]:.0f}, '
                f'{typ["n"]} cases)')
        if share is not None and share >= 1:
            line += ', so this one is already longer than usual.'
        else:
            line += '.'
        out['now'].append(line)
    else:
        out['now'].append(f'This stage has lasted {cur["weeks"]} weeks. There is no completed '
                          f'Stage {stage} in this stock\'s record to compare it with.')

    nxt = hist['next']
    total = sum(nxt.values())
    if total:
        parts = [f'Stage {k} ({NAMES[k]}) {_times(v)}' for k, v in
                 sorted(nxt.items(), key=lambda kv: -kv[1])]
        out['next'].append(f'After past Stage {stage} runs, this stock moved to '
                           + ', '.join(parts) + f', out of {total}.')
    usual = {1: 'In the textbook sequence a base leads to an advance (Stage 2), but bases '
                'also fail and roll back into a decline (Stage 4).',
             2: 'In the textbook sequence an advance ends in a top (Stage 3) before any '
                'decline, though sharp falls can go straight to Stage 4.',
             3: 'In the textbook sequence a top resolves into a decline (Stage 4), but many '
                'tops are only pauses and the advance resumes (Stage 2).',
             4: 'In the textbook sequence a decline ends in a base (Stage 1) before any new '
                'advance, so a rally straight out of Stage 4 is the exception.'}[stage]
    out['next'].append(usual)
    for h in FORWARD_WEEKS:
        f = hist['forward'][h]
        if f['n']:
            out['next'].append(f'{h} weeks after entering Stage {stage}, the price was higher '
                               f'in {f["up"]} of {f["n"]} cases, with a median move of '
                               f'{_pc(f["median"])}.')
    if total < MIN_CASES:
        out['caveat'].append(f'Only {total} past Stage {stage} transition'
                             f'{"s" if total != 1 else ""} in this record, so treat these '
                             f'counts as a description of the past, not odds.')

    ma, ema = cur['ma'], sh['ema_level']
    ma_side = 'above' if cur['close'] >= ma else 'below'
    out['now'].append(f'The latest weekly close of {_p(cur["close"])} is '
                      f'{_pc(abs(cur["to_ma"]), False)} {ma_side} the 30-week average at '
                      f'{_p(ma)}, which is {"rising" if cur["slope"] > cur["band"] else "falling" if cur["slope"] < -cur["band"] else "flat"} '
                      f'({_pc(cur["slope"])} over five weeks). The 50-day EMA is at {_p(ema)}, '
                      f'with the price {"above" if sh["above_ema"] else "below"} it.')

    # what would move it up, and what would move it down
    lo, hi = cur['range_low'], cur['range_high']
    if stage == 4:
        out['up'].append(f'First sign: a close back above the 50-day EMA at {_p(ema)}.')
        out['up'].append(f'Stage 1 (Basing): {CONFIRM_WEEKS} weekly closes in a row that are '
                         f'not below a falling 30-week average, meaning closes above about '
                         f'{_p(ma)}, or the average itself stops falling.')
        out['up'].append(f'Stage 2 directly: {CONFIRM_WEEKS} weekly closes above a rising '
                         f'30-week average. Rare straight out of a decline.')
        out['down'].append(f'The decline stays in force while weekly closes stay below the '
                           f'falling average. The lowest weekly close of this stage is '
                           f'{_p(lo)}; a close under it means a new low.')
    elif stage == 1:
        out['up'].append(f'Stage 2 (Advancing): {CONFIRM_WEEKS} weekly closes above a rising '
                         f'30-week average (now {_p(ma)}), with a weekly close above the top '
                         f'of the base at {_p(hi)}.')
        out['down'].append(f'Back to Stage 4: {CONFIRM_WEEKS} weekly closes below a falling '
                           f'30-week average, with a weekly close under the bottom of the base '
                           f'at {_p(lo)}. That would mean the base has failed.')
    elif stage == 2:
        out['down'].append(f'First warning: a close below the 50-day EMA at {_p(ema)}.')
        out['down'].append(f'Stage 3 (Topping): {CONFIRM_WEEKS} weekly closes that are not '
                           f'above a rising 30-week average, meaning closes under about '
                           f'{_p(ma)}, or the average flattening.')
        out['down'].append(f'Stage 4 directly: {CONFIRM_WEEKS} weekly closes below a falling '
                           f'average, which happens in sharp sell-offs.')
        out['up'].append(f'The advance stays in force while weekly closes hold above the '
                         f'rising average. The highest weekly close of this stage is {_p(hi)}.')
    else:
        out['up'].append(f'Back to Stage 2: {CONFIRM_WEEKS} weekly closes above a rising '
                         f'30-week average (now {_p(ma)}), with a weekly close above the top of '
                         f'the range at {_p(hi)}.')
        out['down'].append(f'Stage 4 (Declining): {CONFIRM_WEEKS} weekly closes below a falling '
                           f'30-week average, with a weekly close under the bottom of the range '
                           f'at {_p(lo)}.')
    if resistance:
        out['up'].append(f'Overhead, past turns cluster at {_p(resistance["low"])}'
                         + (f' to {_p(resistance["high"])}' if resistance['high'] > resistance['low'] * 1.0001 else '')
                         + ', where the price has turned before.')
    if support:
        out['down'].append(f'Below, past turns cluster at {_p(support["low"])}'
                           + (f' to {_p(support["high"])}' if support['high'] > support['low'] * 1.0001 else '')
                           + ', where the price has turned before.')
    if swing and swing.get('state') and swing.get('trigger'):
        word = 'below' if swing['state'] == 'bull' else 'above'
        big = 'bull' if swing['state'] == 'bull' else 'bear'
        (out['down'] if big == 'bull' else out['up']).append(
            f'The big {big} swing that began in {pd.Timestamp(swing["start"]):%b %Y} ends on a '
            f'daily close {word} {_p(swing["trigger"])}.')

    run = cur.get('running')
    if run and run['raw'] is not None:
        out['now'].append(f'This week so far (to {pd.Timestamp(run["date"]):%d %b}), the price '
                          f'at {_p(run["close"])} reads {run["raw"]}. The stage only counts '
                          f'finished weeks.')
    out['caveat'].append('These are this stock\'s own past patterns and the levels that would '
                         'change the reading. They are not a forecast: any stage can end '
                         'earlier or run longer than it did before.')
    return out
