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


# ------------------------------------------------------------------ the status ------------
def test_long_fall_inside_bull_phase_reads_as_correcting():
    r = cy.analyse(uber_like(), threshold=0.35, today=TODAY)
    assert r['current']['state'] == 'bull'
    assert r['status']['qualifier'] == 'correcting'
    assert r['status']['label'] == 'Bull phase, correcting'
    assert r['trend']['direction'] == 'down'
    assert r['confidence']['level'] in ('Medium', 'Low')


def test_healthy_bull_phase_has_no_qualifier():
    r = cy.analyse(path([(400, -0.45), (700, 1.4)], noise=0.006), threshold=0.30, today=TODAY)
    assert r['current']['state'] == 'bull'
    assert r['status']['qualifier'] is None
    assert r['status']['label'] == 'Bull phase'


def test_recovery_inside_bear_phase_reads_as_rebounding():
    r = cy.analyse(path([(500, 1.0), (400, -0.5), (200, 0.25)], noise=0.006),
                   threshold=0.35, today=TODAY)
    assert r['current']['state'] == 'bear'
    assert r['status']['qualifier'] == 'rebounding'


def test_status_never_changes_history():
    """The qualifier is a reading of today. It must not move any turning point."""
    hist = uber_like()
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
    assert 'Bull phase, correcting' in html
    assert 'How much to trust this reading' in html
    meta = {'name': 'Test Co', 'symbol': 'TEST', 'exchange': 'NYSE', 'ccy': 'USD', 'isin': None}
    assert len(cye.build_xlsx(r, meta)) > 1000
    assert len(cye.build_pptx(r, meta)) > 1000
