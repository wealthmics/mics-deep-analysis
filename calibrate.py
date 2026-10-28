"""
Test the cycle rule across many stocks before changing it for everyone.

    python calibrate.py                         # the built-in universe, three multiples
    python calibrate.py --tickers UBER MSFT RELIANCE.NS --mults 0.6 0.8 1.0
    python calibrate.py --file tickers.txt --out calibration.csv

For each stock and each threshold multiple it runs cycle.analyse and records how the rule
behaved: how often phases changed, how many holds were whipsaws (out within three months
at a loss), what a holder captured, and what the page would say today. The summary at the
end is what to look at when choosing THRESHOLD_MULT and the cap in cycle.py: a good
setting gives most stocks one to three full cycles a decade, few whipsaws, and few stocks
sitting in a phase the trend has disagreed with for a long time. The stage columns do not
depend on the multiple; they show how often the stage changes (about twice a year is
normal) and how many stages lasted four weeks or less (should stay small).

Needs network access to Yahoo. Uses the same price fetch and disk cache as the app.
"""

import argparse
import math

import numpy as np
import pandas as pd

import cycle as cy
import data_fetcher as df_mod

# Deliberately mixed: US growth and defensives, banks, recent listings, India, Europe,
# Japan, and ETFs, so a setting that only suits one kind of stock shows up.
UNIVERSE = [
    'AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'TSLA', 'UBER', 'ABNB', 'PLTR', 'SNOW',
    'JPM', 'GS', 'XOM', 'JNJ', 'PG', 'KO', 'NEE', 'DUK', 'WMT', 'INTC',
    'RELIANCE.NS', 'HDFCBANK.NS', 'TCS.NS', 'INFY.NS', 'ITC.NS', 'TATAMOTORS.NS',
    'ADANIENT.NS', 'ZOMATO.NS', 'HSBA.L', 'SHEL.L', 'SAP.DE', 'MC.PA', 'NESN.SW',
    '7203.T', '0700.HK', 'SPY', 'QQQ', 'EEM', 'GLD', 'TLT',
]


def one(symbol, mults):
    hist = df_mod.get_price_history(symbol)
    if hist is None or 'Close' not in hist:
        return [{'symbol': symbol, 'mult': m, 'error': 'no history'} for m in mults]
    out = []
    for m in mults:
        r = cy.analyse(hist, threshold_mult=m)
        if r.get('error'):
            out.append({'symbol': symbol, 'mult': m, 'error': r['error']})
            continue
        years = (r['last_date'] - r['first_date']).days / 365.25
        holds = r['holdings']
        whips = sum(1 for h in holds if h['months'] < 3 and h['total_return'] < 0)
        tr = r['trend'] or {}
        sgr = r.get('stage') or {}
        eps = [] if sgr.get('error') else sgr.get('episodes', [])
        stage_years = ((eps[-1]['end'] - eps[0]['start']).days / 365.25) if eps else None
        out.append({
            'symbol': symbol, 'mult': m, 'error': '',
            'years': round(years, 1),
            'vol': round(r['vol'], 3) if r['vol'] is not None else None,
            'threshold': round(r['threshold'], 3),
            'capped': r['threshold'] >= cy.THRESHOLD_CAP - 1e-9,
            'phases': len(r['phases']),
            'cycles_per_decade': round(len(r['phases']) / 2 / years * 10, 2) if years else None,
            'holds': len(holds),
            'whipsaws': whips,
            'whipsaw_share': round(whips / len(holds), 2) if holds else None,
            'median_hold_months': r['all']['hold_months']['median'],
            'median_captured': r['all']['hold_total']['median'],
            'holds_won': r['all']['hold_won'][0],
            'state': r['current'].get('state'),
            'status': r['status']['label'],
            'trend': tr.get('direction'),
            'stage': sgr['current']['stage'] if eps else None,
            'stage_changes_per_year': round(len(eps) / stage_years, 2) if stage_years else None,
            'short_stage_share': round(sum(1 for e in eps if e['weeks'] <= 4 and not e['open'])
                                       / len(eps), 2) if eps else None,
            'confidence': r['confidence']['level'],
            'data_warnings': sum(1 for c in r['checks'] if c['level'] == 'warn'),
        })
    return out


def summary(df):
    ok = df[df['error'] == '']
    rows = []
    for m, g in ok.groupby('mult'):
        cpd = g['cycles_per_decade']
        rows.append({
            'mult': m, 'stocks': len(g),
            'median cycles/decade': round(float(cpd.median()), 2),
            'share with 1-3 cycles/decade': round(float(((cpd >= 1) & (cpd <= 3)).mean()), 2),
            'share capped at 35%': round(float(g['capped'].mean()), 2),
            'whipsaw share (all holds)': round(float(g['whipsaws'].sum() / max(1, g['holds'].sum())), 2),
            'median captured return': round(float(g['median_captured'].median()), 3)
            if g['median_captured'].notna().any() else None,
            'share where trend disagrees now': round(float(
                g['status'].str.contains('correcting|rebounding').mean()), 2),
            'median stage changes/year': round(float(g['stage_changes_per_year'].median()), 2),
            'share of stages 4 weeks or less': round(float(g['short_stage_share'].median()), 2),
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--tickers', nargs='*')
    ap.add_argument('--file')
    ap.add_argument('--mults', nargs='*', type=float, default=[0.7, 0.85, 1.0])
    ap.add_argument('--out', default='calibration.csv')
    args, _ = ap.parse_known_args()             # tolerate Jupyter's own arguments
    tickers = args.tickers or UNIVERSE
    if args.file:
        with open(args.file) as fh:
            tickers = [t.strip() for t in fh if t.strip() and not t.startswith('#')]
    rows = []
    for t in tickers:
        try:
            rows += one(t, args.mults)
        except Exception as e:                   # one bad ticker must not stop the run
            rows += [{'symbol': t, 'mult': m, 'error': str(e)} for m in args.mults]
        print(f'done {t}')
    df = pd.DataFrame(rows)
    df.to_csv(args.out, index=False)
    print(f'\nPer stock results written to {args.out}\n')
    with pd.option_context('display.width', 160, 'display.max_columns', 20):
        print(summary(df).to_string(index=False))


if __name__ == '__main__':
    main()
