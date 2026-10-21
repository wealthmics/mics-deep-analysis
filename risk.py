"""
Price risk for the deep analysis page, computed once per time window.

Kept out of app.py so it can be tested without Streamlit, and so the page and the two
exports (Excel and PowerPoint) all read the same numbers.

Every window is measured on the full daily series, never on the thinned series the chart
draws, so the figures are exact even though the chart is not drawn point for point.
"""

import math

import numpy as np
import pandas as pd

BENCH_SYMBOL = '^GSPC'
BENCH_NAME = 'S&P 500'

# trading days per window; None is the whole record
SPANS = {'3M': 63, '6M': 126, '1Y': 252, '2Y': 504, '5Y': 1260, '10Y': 2520, 'Max': None}
SPAN_WORDS = {'3M': 'three months', '6M': 'six months', '1Y': 'one year', '2Y': 'two years',
              '5Y': 'five years', '10Y': 'ten years', 'Max': 'the full record'}


def dated(series):
    """A clean daily series on a plain date index, so two markets can be lined up.

    Yahoo stamps each market in its own time zone. Converting to a date first means a
    Tokyo close and a New York close for the same calendar day sit on the same row.
    """
    if series is None:
        return None
    s = pd.Series(series).dropna()
    if s.empty:
        return None
    idx = pd.to_datetime(s.index)
    if getattr(idx, 'tz', None) is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    s = s[~s.index.duplicated(keep='last')].sort_index()
    return s.astype(float)


def window(series, label):
    n = SPANS.get(label)
    return series if n is None else series.tail(n)


def drawdown(close):
    """The worst fall from a high inside the series, with its dates and whether it healed.

    peak       the date of the high the fall started from
    trough     the date of the low
    recovered  the first date the price got back to that high, or None
    now_below  how far the last price sits below the highest price in the series
    """
    s = dated(close)
    if s is None or len(s) < 5:
        return None
    running = s.cummax()
    dd = s / running - 1
    trough = dd.idxmin()
    worst = float(dd.min()) * 100
    peak = s.loc[:trough].idxmax()
    peak_level = float(s.loc[peak])
    after = s.loc[trough:]
    back = after[after >= peak_level]
    recovered = back.index[0] if len(back) and worst < 0 else None
    return {
        'worst_pct': round(worst, 1),
        'peak': peak, 'trough': trough, 'recovered': recovered,
        'peak_level': peak_level, 'trough_level': float(s.loc[trough]),
        'days_down': int((trough - peak).days),
        'days_to_recover': int((recovered - trough).days) if recovered is not None else None,
        'now_below_high_pct': round((float(s.iloc[-1]) / float(s.max()) - 1) * 100, 1),
    }


def versus_benchmark(close, bench, label, weekly):
    """Beta and correlation against the benchmark over the same dates, plus both changes.

    Weekly returns are used for anything a year or longer, and for every window on a
    listing outside the US. A daily return in Tokyo is set before New York opens, so daily
    returns from two time zones line up badly and pull the beta towards zero. Friday to
    Friday returns remove most of that.
    """
    a, b = dated(close), dated(bench)
    if a is None or b is None or len(a) < 10:
        return None
    b = b.loc[a.index[0]:a.index[-1]]
    if len(b) < 10:
        return None
    bench_change = (float(b.iloc[-1]) / float(b.iloc[0]) - 1) * 100
    if weekly:
        a, b = a.resample('W-FRI').last(), b.resample('W-FRI').last()
    joined = pd.concat([a.pct_change(), b.pct_change()], axis=1, join='inner').dropna()
    out = {'bench_change_pct': round(bench_change, 1), 'beta': None, 'corr': None,
           'obs': int(len(joined)), 'freq': 'weekly' if weekly else 'daily'}
    if len(joined) < (12 if weekly else 40):
        return out
    var = float(joined.iloc[:, 1].var())
    if not var:
        return out
    out['beta'] = round(float(joined.cov().iloc[0, 1]) / var, 2)
    out['corr'] = round(float(joined.corr().iloc[0, 1]), 2)
    return out


def window_stats(close, bench, label, us_listed):
    s = dated(close)
    if s is None or len(s) < 5:
        return {}
    w = window(s, label)
    first, last = float(w.iloc[0]), float(w.iloc[-1])
    rets = w.pct_change().dropna()
    weekly = (not us_listed) or SPANS.get(label) is None or SPANS[label] >= 252
    stats = {
        'label': label, 'start': w.index[0], 'end': w.index[-1],
        'hi': float(w.max()), 'lo': float(w.min()),
        'change_pct': round((last / first - 1) * 100, 1) if first else None,
        'vol_pct': round(float(rets.std() * math.sqrt(252) * 100), 1) if len(rets) > 20 else None,
        'dd': drawdown(w),
        'bench': versus_benchmark(w, bench, label, weekly) if bench is not None else None,
    }
    b = stats['bench']
    if b and stats['change_pct'] is not None:
        stats['relative_pts'] = round(stats['change_pct'] - b['bench_change_pct'], 1)
    return stats


def all_windows(close, bench, labels, us_listed):
    return {lab: window_stats(close, bench, lab, us_listed) for lab in labels}


# ------------------------------------------------------------------ plain words --------
def _d(ts, fmt='%d %b %Y'):
    return ts.strftime(fmt).lstrip('0') if hasattr(ts, 'strftime') else str(ts)


def _span(days):
    if days is None:
        return ''
    if days < 45:
        return f'{days} days'
    months = round(days / 30.4)
    if months < 24:
        return f'{months} month{"s" if months != 1 else ""}'
    years = days / 365.25
    return f'{years:.1f} years'


def drawdown_sentence(dd, where='in this window'):
    """One or two sentences that say what the drawdown chart shows, with its dates."""
    if not dd:
        return ''
    w = dd['worst_pct']
    if w > -5:
        return (f'No meaningful fall {where}. The deepest dip below a previous high was '
                f'{abs(w):.1f}%.')
    text = (f'The worst fall {where} was {abs(w):.1f}%, from a high on {_d(dd["peak"])} to a '
            f'low on {_d(dd["trough"])}, {_span(dd["days_down"])} later.')
    if dd['recovered'] is not None:
        text += (f' It was back at that high by {_d(dd["recovered"])}, '
                 f'{_span(dd["days_to_recover"])} after the low.')
    else:
        # nothing after the low reached the old high, so the highest price in the window is
        # that high, and now_below_high is the distance still to go
        now = dd.get('now_below_high_pct')
        text += (' It has not yet regained that high'
                 + (f' and sits {abs(now):.1f}% below it.' if now is not None and now < 0 else '.'))
    return text


def beta_sentence(b, ccy=None):
    """What the beta means here, including when it should not be leaned on."""
    if not b or b.get('beta') is None:
        if b and b.get('obs') is not None:
            return (f'Too few {b["freq"]} observations ({b["obs"]}) in this window for a '
                    f'beta against the {BENCH_NAME} to mean anything.')
        return ''
    beta, corr, freq, obs = b['beta'], b['corr'], b['freq'], b['obs']
    if corr is not None and abs(corr) < 0.3:
        text = (f'Beta against the {BENCH_NAME} is {beta:.2f}, but the correlation is only '
                f'{corr:.2f}, so the index explains little of how this stock moves. Read the '
                f'beta as weak.')
    elif beta < 0:
        text = (f'Beta against the {BENCH_NAME} is {beta:.2f}: the stock has tended to move '
                f'against the index over this window.')
    else:
        size = ('more than the index' if beta > 1.15 else
                'less than the index' if beta < 0.85 else 'roughly in step with the index')
        text = (f'Beta of {beta:.2f} against the {BENCH_NAME}: on {freq} returns the stock '
                f'has typically moved about {beta:.1f}% for each 1% move in the index, '
                f'{size}.')
    if obs < 26:
        text += f' Based on only {obs} {freq} returns, so treat it as a rough reading.'
    if ccy and str(ccy).upper() != 'USD':
        text += (f' Measured in {ccy} against an index in US dollars, so currency moves are '
                 f'part of the figure.')
    return text
