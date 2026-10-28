"""
Tests for the stock cycle. Run with:  python -m pytest tests

Synthetic prices only, so the tests need no network and give the same answer every time.
Each test checks one promise the page makes to its reader.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cycle as cy  # noqa: E402

TODAY = pd.Timestamp('2026-10-28')


def path(legs, noise=0.012, seed=1, end=TODAY):
    """A price series built from legs of (trading days, total move), with daily noise."""
    rng = np.random.default_rng(seed)
    steps = []
    for days, move in legs:
        drift = np.log(1 + move) / days
        steps.append(drift + rng.normal(0, noise, days))
    logp = np.log(50) + np.cumsum(np.concatenate(steps))
    idx = pd.bdate_range(end=end, periods=len(logp))
    return pd.DataFrame({'Close': np.exp(logp)}, index=idx)


def uber_like():
    """Up from the lows, a peak, then a long fall of about 33% that has not crossed a 35%
    trigger: the case that read as a plain bull phase."""
    return path([(400, -0.45), (700, 1.4), (250, -0.33)], noise=0.008)


# ------------------------------------------------------------------ the stage -------------
def flat(days, noise=0.006, seed=11):
    return (days, 0.0)


def stage_now(legs, noise=0.008, seed=1):
    r = cy.analyse(path(legs, noise=noise, seed=seed), threshold=0.30, today=TODAY)
    return r['stage']['current']['stage'], r


def test_steady_advance_is_stage_2():
    assert stage_now([(300, 0.1), (600, 1.0)])[0] == 2


def test_steady_decline_is_stage_4():
    assert stage_now([(300, 0.1), (600, -0.5)])[0] == 4


def with_range(legs, weeks=50, amp=0.05, seed=4):
    """A trend followed by a sideways range: price swinging about 5% either way around a
    level, the shape of a real base or top."""
    hist = path(legs, noise=0.006, end=TODAY - pd.Timedelta(weeks=weeks))
    last = float(hist['Close'].iloc[-1])
    idx = pd.bdate_range(start=hist.index[-1] + pd.Timedelta(days=1), end=TODAY)
    t = np.arange(len(idx))
    rng = np.random.default_rng(seed)
    side = last * (1 + amp * np.sin(t / 18) + rng.normal(0, 0.004, len(idx)))
    return pd.concat([hist, pd.DataFrame({'Close': side}, index=idx)])


def test_range_after_decline_is_stage_1():
    r = cy.analyse(with_range([(300, 0.1), (500, -0.5)]), threshold=0.30, today=TODAY)
    assert r['stage']['current']['stage'] == 1


def test_range_after_advance_is_stage_3():
    r = cy.analyse(with_range([(300, 0.1), (500, 1.0)]), threshold=0.30, today=TODAY)
    assert r['stage']['current']['stage'] == 3


def test_breakdown_from_a_top_is_stage_4():
    hist = with_range([(300, 0.1), (500, 1.0)], weeks=70)
    tail = path([(100, -0.25)], noise=0.004)['Close'].values
    hist.iloc[-100:, 0] = hist['Close'].iloc[-101] * tail / tail[0]
    r = cy.analyse(hist, threshold=0.30, today=TODAY)
    assert r['stage']['current']['stage'] == 4


def test_stage_never_repaints():
    """Every stage decided on a finished week stays the same when more prices arrive."""
    hist = path([(300, 0.8), (200, -0.4), (250, 0.6), (300, -0.45), (300, 0.7)], seed=7)
    close = cy.traded_prices(hist)[0]
    full = cy.sg.analyse(close, TODAY)['weekly']['stage']
    for cut in range(400, len(close), 53):
        part_close = close.iloc[:cut]
        part = cy.sg.analyse(part_close, part_close.index[-1])['weekly']['stage']
        common = part.index.intersection(full.index)
        pd.testing.assert_series_equal(part.loc[common], full.loc[common], check_names=False)


def test_running_week_is_not_used_for_the_stage():
    hist = path([(300, 0.1), (600, 1.0)])         # ends on a Wednesday
    s = cy.sg.analyse(cy.traded_prices(hist)[0], TODAY)
    assert s['current']['week'] < TODAY
    assert s['current']['running']['date'] == hist.index[-1]


def test_fifty_day_ema_is_reported():
    _, r = stage_now([(300, 0.1), (600, 1.0)])
    sh = r['stage']['short']
    close = r['close']
    expect = close.ewm(span=50, adjust=False).mean().iloc[-1]
    assert sh['ema_level'] == pytest.approx(expect)
    assert '50-day EMA' in ' '.join(r['outlook']['now'])


# ------------------------------------------------------------------ the uber case ---------
def test_fall_threshold_is_log_symmetric():
    assert cy.fall_for(0.35) == pytest.approx(0.35 / 1.35)
    assert (1 - cy.fall_for(0.35)) * 1.35 == pytest.approx(1.0)


def test_uber_case_leads_with_the_stage_not_the_big_swing():
    """About 24% off the high with a 35% rise threshold: the fall needed to end the big
    swing is 25.9%, so the swing can still be bull, but the stage must say Declining and
    the page must say why the two differ."""
    hist = path([(400, -0.45), (700, 1.4), (230, -0.24)], noise=0.006)
    r = cy.analyse(hist, threshold=0.35, today=TODAY)
    assert r['stage']['current']['stage'] == 4
    import cycle_page as cpg
    assert cpg.headline(r) == 'Stage 4, Declining'
    if r['current']['state'] == 'bull':
        assert any('opposite ways' in x for x in r['confidence']['reasons'])
    assert r['outlook']['up'] and r['outlook']['down']


def test_long_fall_ends_the_big_bull_swing():
    """A 33% fall now ends a big bull swing with a 35% rise threshold (fall 25.9%)."""
    r = cy.analyse(path([(400, -0.45), (700, 1.4), (250, -0.33)], noise=0.006),
                   threshold=0.35, today=TODAY)
    assert r['current']['state'] == 'bear'


def test_outlook_counts_only_real_past_stages():
    _, r = stage_now([(300, 0.8), (200, -0.4), (250, 0.6), (300, -0.45), (300, 0.7)],
                     noise=0.01)
    stats = r['stage']['stats']
    eps = [e for e in r['stage']['episodes'] if not e['first']]
    assert sum(sum(d['next'].values()) for d in stats.values()) == len(eps) - 1 + (
        0 if r['stage']['episodes'][0]['first'] is False else 0)


def test_status_never_changes_history():
    hist = path([(400, -0.45), (700, 1.4), (250, -0.20)], noise=0.008)
    r = cy.analyse(hist, threshold=0.35, today=TODAY)
    points, _ = cy.turning_points(cy.traded_prices(hist)[0], 0.35)
    assert [p['date'] for p in r['points']] == [p['date'] for p in points]


# ------------------------------------------------------------------ the rule --------------
def test_confirmed_turns_never_move_when_new_prices_arrive():
    """Cut the history at many dates. Every turn confirmed before a cut must be identical
    in the full run: same kind, same date, same price, same confirmation day."""
    hist = path([(300, 0.8), (200, -0.4), (250, 0.6), (300, -0.45), (300, 0.7)], seed=7)
    close = cy.traded_prices(hist)[0]
    full, _ = cy.turning_points(close, 0.25)
    for cut in range(300, len(close), 97):
        part, _ = cy.turning_points(close.iloc[:cut], 0.25)
        assert part == full[:len(part)]


def test_phases_alternate():
    hist = path([(300, 0.8), (200, -0.4), (250, 0.6), (300, -0.45)], seed=3)
    r = cy.analyse(hist, threshold=0.25, today=TODAY)
    kinds = [p['kind'] for p in r['points']]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))


def test_threshold_uses_recent_years_only():
    """A wild first few years must not set the scale for a stock that has since calmed."""
    rng = np.random.default_rng(0)
    wild = rng.normal(0, 0.04, 252 * 4)       # about 63% a year
    calm = rng.normal(0, 0.012, 252 * 6)      # about 19% a year
    close = pd.Series(np.exp(np.log(50) + np.cumsum(np.concatenate([wild, calm]))),
                      index=pd.bdate_range(end=TODAY, periods=252 * 10))
    t_recent, _ = cy.threshold_for(close)
    t_all, _ = cy.threshold_for(close, years=None)
    assert t_recent < 0.25
    assert t_all >= t_recent


# ------------------------------------------------------------------ data checks -----------
def test_unrecorded_split_is_flagged_and_lowers_confidence():
    hist = path([(800, 0.6)], noise=0.006)
    hist.iloc[500:, 0] = hist.iloc[500:, 0] / 2          # a 2-for-1 split Yahoo missed
    r = cy.analyse(hist, threshold=0.25, today=TODAY)
    assert any('one-day move' in c['text'] for c in r['checks'])
    assert r['confidence']['level'] == 'Low'


def test_frozen_price_is_flagged():
    hist = path([(800, 0.6)], noise=0.006)
    hist.iloc[300:320, 0] = hist.iloc[300, 0]
    assert any('exactly the same' in c['text'] for c in cy.data_checks(hist['Close'], TODAY))


def test_stale_data_is_flagged():
    hist = path([(800, 0.6)], end=TODAY - pd.Timedelta(days=30))
    assert any('days ago' in c['text'] for c in cy.data_checks(hist['Close'], TODAY))


def test_clean_data_raises_nothing():
    hist = path([(1600, 0.6)], noise=0.008)
    assert cy.data_checks(hist['Close'], TODAY) == []


# ------------------------------------------------------------------ benchmarks ------------
@pytest.mark.parametrize('symbol,expect', [
    ('RELIANCE.NS', '^NSEI'), ('500325.BO', '^BSESN'), ('VOD.L', '^FTSE'),
    ('7203.T', '^N225'), ('UBER', '^GSPC'), ('EMAAR.AE', '^GSPC'), (None, '^GSPC')])
def test_benchmark_for(symbol, expect):
    assert cy.benchmark_for(symbol)[0] == expect


# ------------------------------------------------------------------ the page --------------
def test_page_and_exports_build():
    """Every figure the page shows must come out of analyse without errors."""
    pytest.importorskip('openpyxl')
    pytest.importorskip('pptx')
    import cycle_page as cpg
    import cycle_exports as cye
    r = cy.analyse(uber_like(), threshold=0.35, today=TODAY, bench_name='S&P 500')
    html = cpg.build(r, 'Test Co', 'TEST', 'NYSE', 'USD', None, 'ticker=TEST')
    for part in ('Stage ', 'What usually comes next', 'How much to trust this reading',
                 '50-day EMA', 'The big swing', 'Every stage this stock has been through'):
        assert part in html
    meta = {'name': 'Test Co', 'symbol': 'TEST', 'exchange': 'NYSE', 'ccy': 'USD', 'isin': None}
    assert len(cye.build_xlsx(r, meta)) > 1000
    assert len(cye.build_pptx(r, meta)) > 1000
