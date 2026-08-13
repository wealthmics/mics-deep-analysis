"""
MICS Equity Analysis - single page, single file.

Source rule, applied everywhere on this page: if the TradingView export already publishes
a figure, that figure is used. It is trailing-twelve-month, computed identically across the
whole universe, and it is what the screener ranked on - so the analysis agrees with the
screen that surfaced the name. Yahoo is used only for what TradingView does not publish:
the forensic scores, the four-year statement trends, the decompositions and the daily
price series.

Every number carries where it came from and what period it covers, because a
trailing-twelve-month return sitting next to an annual margin with no label is how
analysis goes quietly wrong.

Needs data_fetcher.py and financial_formulas.py beside it, and the two JSON feeds the
screener publishes to GitHub Pages.
"""

import datetime
import json
import math

import numpy as np
import pandas as pd
import streamlit as st

import data_fetcher as df_mod
import financial_formulas as ff

st.set_page_config(page_title='MICS Equity Analysis', layout='wide',
                   initial_sidebar_state='collapsed')

# The sidebar held screening thresholds, which belong to a screener and mean nothing when
# you are reading one company. Screening already happened before anyone arrived here.
st.markdown("""
<style>
  section[data-testid="stSidebar"] {display:none;}
  div[data-testid="collapsedControl"] {display:none;}
  .block-container {padding-top:1.6rem; max-width:1500px;}
  #MainMenu, footer {visibility:hidden;}
</style>
""", unsafe_allow_html=True)



# ---------------------------------------------------------------- the TradingView feed --
# Published by marquee_screener.py next to index.html on the Pages site.
FEED_BASE = "https://wealthmics.github.io/Stock-Screener"
STOCKS_URL = f"{FEED_BASE}/stocks.json"
SECTOR_URL = f"{FEED_BASE}/sector_stats.json"

# how a metric should be read, so the page can colour and rank it correctly
HIGHER_IS_BETTER = {
    'roic': True, 'roce': True, 'roa': True, 'roe': True, 'gross_margin': True,
    'op_margin': True, 'net_margin': True, 'fcf_margin': True, 'current_ratio': True,
    'interest_cover': True, 'altman_z': True, 'piotroski_f': True,
    'pe': False, 'fpe': False, 'debt_equity': False,
}

LABELS = {
    'pe': 'P/E', 'fpe': 'P/E forward', 'roic': 'ROIC', 'roce': 'ROCE', 'roa': 'ROA',
    'roe': 'ROE', 'gross_margin': 'Gross margin', 'op_margin': 'Operating margin',
    'net_margin': 'Net margin', 'fcf_margin': 'FCF margin',
    'current_ratio': 'Current ratio', 'debt_equity': 'Debt / equity',
    'interest_cover': 'Interest coverage', 'ebitda_cover': 'EBITDA coverage',
    'altman_z': 'Altman Z', 'piotroski_f': 'Piotroski F',
}
PERCENT_METRICS = {'roic', 'roce', 'roa', 'roe', 'gross_margin', 'op_margin',
                   'net_margin', 'fcf_margin'}


def fetch_feed(url, timeout=20):
    """Read one of the published JSON feeds."""
    import requests
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def lookup(feed, isin=None, ticker=None):
    """Find a stock in the feed by ISIN, falling back to a ticker scan."""
    stocks = (feed or {}).get('stocks', {})
    if isin and isin.upper() in stocks:
        return isin.upper(), stocks[isin.upper()]
    if ticker:
        want = ticker.upper()
        for key, entry in stocks.items():
            if str(entry.get('ticker', '')).upper() == want:
                return key, entry
    return None, None


# ---------------------------------------------------------------- peer position ---------
def percentile_of(value, stats_block, metric):
    """Where a value sits against its sector, using the published quartiles.

    Only three points of the distribution are published, so this interpolates between
    them rather than pretending to a precision it does not have. The band it returns is
    what the page shows - a claim of "72nd percentile" from three quartiles would be
    false precision.
    """
    if value is None or not stats_block or metric not in stats_block:
        return None
    q = stats_block[metric]
    p25, med, p75 = q['p25'], q['median'], q['p75']
    higher_better = HIGHER_IS_BETTER.get(metric, True)

    if value <= p25:
        band, rank = 'bottom quartile', 1
    elif value <= med:
        band, rank = 'below median', 2
    elif value <= p75:
        band, rank = 'above median', 3
    else:
        band, rank = 'top quartile', 4

    # for a metric where low is good, the wording has to flip or it reads backwards
    if not higher_better:
        rank = 5 - rank
        band = {1: 'worst quartile', 2: 'below average', 3: 'better than median',
                4: 'best quartile'}[rank]
    else:
        band = {1: 'worst quartile', 2: 'below median', 3: 'above median',
                4: 'best quartile'}[rank]

    return {'band': band, 'rank': rank, 'p25': p25, 'median': med, 'p75': p75,
            'n': q.get('n')}


# ---------------------------------------------------------------- statement helpers -----
STMT_KEYS = {
    'revenue': ['Total Revenue', 'Operating Revenue'],
    'net_income': ['Net Income', 'Net Income Common Stockholders',
                   'Net Income From Continuing Operation Net Minority Interest'],
    'op_income': ['Operating Income', 'EBIT', 'Total Operating Income As Reported'],
    'gross_profit': ['Gross Profit'],
    'assets': ['Total Assets'],
    'equity': ['Stockholders Equity', 'Common Stock Equity',
               'Total Equity Gross Minority Interest'],
    'cfo': ['Operating Cash Flow', 'Cash Flow From Continuing Operating Activities',
            'Total Cash From Operating Activities'],
    'capex': ['Capital Expenditure', 'Purchase Of PPE'],
    'buyback': ['Repurchase Of Capital Stock', 'Common Stock Payments'],
    'dividend': ['Cash Dividends Paid', 'Common Stock Dividend Paid'],
    'debt_repaid': ['Repayment Of Debt', 'Long Term Debt Payments'],
    'debt_issued': ['Issuance Of Debt', 'Long Term Debt Issuance'],
    'acquisitions': ['Purchase Of Business', 'Net Business Purchase And Sale'],
    'shares': ['Basic Average Shares', 'Diluted Average Shares', 'Share Issued',
               'Ordinary Shares Number'],
    'fcf': ['Free Cash Flow'],
}


def pick(df, field, col=0):
    """One number off a statement, or None. A missing line is never a zero."""
    if df is None or getattr(df, 'columns', None) is None or len(df.columns) <= col:
        return None
    lower = {str(i).strip().lower(): i for i in df.index}
    for key in STMT_KEYS.get(field, [field]):
        hit = lower.get(key.strip().lower())
        if hit is not None:
            val = df.loc[hit, df.columns[col]]
            if pd.notna(val):
                return float(val)
    return None


def series_of(df, field, years=4):
    """A field across the columns Yahoo returned, oldest first, with its period labels."""
    if df is None or getattr(df, 'columns', None) is None:
        return [], []
    n = min(years, len(df.columns))
    vals, labels = [], []
    for i in range(n):
        vals.append(pick(df, field, i))
        col = df.columns[i]
        labels.append(col.strftime('%b %Y') if hasattr(col, 'strftime') else str(col))
    return list(reversed(vals)), list(reversed(labels))


# ---------------------------------------------------------------- the decompositions ----
def dupont(fin, bs):
    """ROE split into margin, turnover and leverage, oldest period first.

    Oldest first on purpose - every series on this page runs the same direction so they
    can be charted together without anyone having to check which way round a list is.

    An ROE of 18% earned on a 12% margin is a different company from one earned on 3x
    leverage. The headline number cannot tell them apart, which is the whole point of
    running the decomposition.
    """
    out = []
    cols = 0 if fin is None else len(fin.columns)
    for i in range(min(4, cols)):
        ni, rev = pick(fin, 'net_income', i), pick(fin, 'revenue', i)
        assets, equity = pick(bs, 'assets', i), pick(bs, 'equity', i)
        if None in (ni, rev, assets, equity) or 0 in (rev, assets, equity):
            out.append(None)
            continue
        margin, turnover, leverage = ni / rev, rev / assets, assets / equity
        col = fin.columns[i]
        out.append({
            'period': col.strftime('%b %Y') if hasattr(col, 'strftime') else str(col),
            'net_margin_pct': round(margin * 100, 2),
            'asset_turnover': round(turnover, 3),
            'equity_multiplier': round(leverage, 2),
            'roe_pct': round(margin * turnover * leverage * 100, 2),
        })
    return list(reversed([o for o in out if o is not None]))


def quality_of_earnings(fin, cf):
    """Cash flow against reported profit, over the years Yahoo reports.

    Profit rising while operating cash flow stays flat is the oldest warning sign there
    is, and it shows up here long before it shows up in a single-year accrual ratio.
    """
    ni, labels = series_of(fin, 'net_income')
    cfo, _ = series_of(cf, 'cfo')
    rows = []
    for i, label in enumerate(labels):
        n = ni[i] if i < len(ni) else None
        c = cfo[i] if i < len(cfo) else None
        rows.append({'period': label, 'net_income': n, 'cfo': c,
                     'cfo_to_ni': round(c / n, 2) if (n and c is not None and n != 0) else None})
    usable = [r for r in rows if r['cfo_to_ni'] is not None]
    verdict = None
    if len(usable) >= 2:
        avg = sum(r['cfo_to_ni'] for r in usable) / len(usable)
        if avg >= 1.1:
            verdict = (f'Cash conversion averages {avg:.2f}x reported profit over '
                       f'{len(usable)} years. Earnings are backed by cash.')
        elif avg >= 0.9:
            verdict = (f'Cash conversion averages {avg:.2f}x reported profit. Broadly in '
                       f'line, nothing to flag.')
        else:
            verdict = (f'Cash conversion averages only {avg:.2f}x reported profit over '
                       f'{len(usable)} years. Profit is running ahead of cash, which is '
                       f'worth understanding before anything else on this page.')
    return rows, verdict


def capital_allocation(cf):
    """Where the operating cash went across the years Yahoo reports.

    Yahoo signs outflows negative, so absolute values are taken and the direction is
    stated in the label instead.
    """
    cfo, labels = series_of(cf, 'cfo')
    total_cfo = sum(v for v in cfo if v is not None)
    uses = {}
    for field, name in (('capex', 'Capital expenditure'), ('buyback', 'Share buybacks'),
                        ('dividend', 'Dividends paid'), ('debt_repaid', 'Debt repaid'),
                        ('acquisitions', 'Acquisitions')):
        vals, _ = series_of(cf, field)
        total = sum(abs(v) for v in vals if v is not None)
        if total:
            uses[name] = total
    rows = []
    for name, total in sorted(uses.items(), key=lambda kv: -kv[1]):
        rows.append({'use': name, 'amount': total,
                     'pct_of_cfo': round(total / total_cfo * 100, 1) if total_cfo else None})
    return {'years': len(labels), 'period_from': labels[0] if labels else None,
            'period_to': labels[-1] if labels else None,
            'cumulative_cfo': total_cfo or None, 'uses': rows}


def per_share_growth(fin, bs):
    """Revenue and profit growth per share, which is the only growth a holder receives.

    Revenue up 15% on a share count up 12% is 3% to the owner. Absolute growth hides that.
    """
    rev, labels = series_of(fin, 'revenue')
    ni, _ = series_of(fin, 'net_income')
    sh, _ = series_of(fin, 'shares')
    if not any(s for s in sh):
        sh, _ = series_of(bs, 'shares')
    if len(labels) < 2:
        return None
    first, last = 0, len(labels) - 1
    def cagr(a, b, years):
        if not a or not b or a <= 0 or b <= 0 or years <= 0:
            return None
        return round(((b / a) ** (1 / years) - 1) * 100, 2)
    years = last - first
    out = {'from': labels[first], 'to': labels[last], 'years': years,
           'revenue_cagr_pct': cagr(rev[first], rev[last], years),
           'net_income_cagr_pct': cagr(ni[first], ni[last], years),
           'share_count_cagr_pct': cagr(sh[first], sh[last], years) if any(sh) else None}
    if out['share_count_cagr_pct'] is not None:
        rps_a = (rev[first] / sh[first]) if (rev[first] and sh[first]) else None
        rps_b = (rev[last] / sh[last]) if (rev[last] and sh[last]) else None
        eps_a = (ni[first] / sh[first]) if (ni[first] and sh[first]) else None
        eps_b = (ni[last] / sh[last]) if (ni[last] and sh[last]) else None
        out['revenue_per_share_cagr_pct'] = cagr(rps_a, rps_b, years)
        out['eps_cagr_pct'] = cagr(eps_a, eps_b, years)
    return out


def price_risk(hist, bench=None):
    """Risk from the daily series, which TradingView's performance columns cannot give."""
    out = {'vol_1y_pct': None, 'max_drawdown_pct': None, 'drawdown_from': None,
           'beta_2y': None, 'pct_vs_200dma': None}
    if hist is None or len(hist) < 60 or 'Close' not in hist:
        return out
    close = hist['Close'].dropna()
    ret = close.pct_change().dropna()
    if len(ret) > 30:
        out['vol_1y_pct'] = round(float(ret.tail(252).std() * math.sqrt(252) * 100), 1)
    peak = close.cummax()
    dd = (close / peak) - 1
    out['max_drawdown_pct'] = round(float(dd.min() * 100), 1)
    trough = dd.idxmin()
    out['drawdown_from'] = trough.strftime('%b %Y') if hasattr(trough, 'strftime') else None
    if len(close) >= 200:
        out['pct_vs_200dma'] = round(
            float((close.iloc[-1] / close.rolling(200).mean().iloc[-1] - 1) * 100), 1)
    if bench is not None and len(bench) > 60 and 'Close' in bench:
        b = bench['Close'].dropna().pct_change().dropna()
        joined = pd.concat([ret, b], axis=1, join='inner').dropna()
        if len(joined) > 60:
            var = joined.iloc[:, 1].var()
            if var:
                out['beta_2y'] = round(float(joined.cov().iloc[0, 1] / var), 2)
    return out


# ---------------------------------------------------------------- presentation ----------
NAVY, GOLD, GREEN, RED, GREY = '#1f3864', '#bf8f00', '#1f6b3b', '#a01b2b', '#6b7280'

CSS = """
<style>
  .dv-head {background:linear-gradient(90deg,#1f3864,#2e5c8a); color:#fff;
            padding:16px 20px; border-radius:8px; margin-bottom:6px;}
  .dv-head h1 {margin:0; font-size:24px; font-weight:650; color:#fff;}
  .dv-head .sub {opacity:.85; font-size:13px; margin-top:4px;}
  .dv-pill {display:inline-block; background:rgba(255,255,255,.15); border-radius:10px;
            padding:2px 9px; font-size:11px; margin-right:6px;}
  .dv-card {border:1px solid #d8dee9; border-left:4px solid #1f3864; border-radius:6px;
            padding:10px 13px; background:#fff; height:100%;}
  .dv-card .k {font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:#6b7280;}
  .dv-card .v {font-size:22px; font-weight:650; color:#1f3864; line-height:1.25;}
  .dv-card .m {font-size:11px; color:#6b7280; margin-top:2px;}
  .dv-thin {opacity:.55;}
  .dv-src  {display:inline-block; font-size:10px; padding:1px 6px; border-radius:8px;
            background:#eef2f8; color:#1f3864; border:1px solid #d8dee9;}
  .dv-src.yh {background:#f4efe0; color:#7a5c00; border-color:#e3d7ae;}
  .dv-sec {font-size:12px; text-transform:uppercase; letter-spacing:.06em;
           color:#1f3864; font-weight:700; border-bottom:2px solid #1f3864;
           padding-bottom:4px; margin:22px 0 10px;}
  .dv-note {font-size:11.5px; color:#6b7280; line-height:1.55;}
</style>
"""


def fmt(value, kind='num', dp=2):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return '-'
    if kind == 'pct':
        return f'{value:,.1f}%'
    if kind == 'x':
        return f'{value:,.2f}x'
    if kind == 'money':
        for cut, suffix in ((1e12, 'T'), (1e9, 'B'), (1e6, 'M'), (1e3, 'K')):
            if abs(value) >= cut:
                return f'{value/cut:,.2f}{suffix}'
        return f'{value:,.0f}'
    if kind == 'int':
        return f'{value:,.0f}'
    return f'{value:,.{dp}f}'


def badge(source, period=None):
    cls = 'dv-src yh' if source.lower().startswith('yahoo') else 'dv-src'
    text = source if not period else f'{source} · {period}'
    return f'<span class="{cls}">{text}</span>'


def card(label, value, meta='', thin=False):
    klass = 'dv-card dv-thin' if thin else 'dv-card'
    return (f'<div class="{klass}"><div class="k">{label}</div>'
            f'<div class="v">{value}</div><div class="m">{meta}</div></div>')


def section(title):
    return f'<div class="dv-sec">{title}</div>'


# ---------------------------------------------------------------- the page --------------
def render(st, tv, isin, yf_data, sector_stats, forensics, resolution=None):
    """Draw the analysis page.

    tv          the TradingView entry from stocks.json, the primary source
    yf_data     what data_fetcher returned for the resolved Yahoo symbol
    forensics   the scores financial_formulas produced, which TradingView does not publish
    """
    st.markdown(CSS, unsafe_allow_html=True)
    periods = (tv or {}).get('_periods', {})
    tvp = lambda k: periods.get(k)

    fin = (yf_data or {}).get('financials')
    bs = (yf_data or {}).get('balance_sheet')
    cf = (yf_data or {}).get('cashflow')
    hist = (yf_data or {}).get('history')
    stats = (sector_stats or {}).get(tv.get('gics')) if tv else None

    # ---------------- identity ----------------
    name = tv.get('name') if tv else (yf_data or {}).get('symbol', '')
    pills = ''.join(f'<span class="dv-pill">{p}</span>' for p in [
        tv.get('ticker') if tv else '',
        isin or '',
        tv.get('gics') if tv else '',
        tv.get('country') if tv else '',
        f"{tv.get('ccy')} {fmt(tv.get('price'))}" if tv and tv.get('price') else '',
    ] if p)
    st.markdown(
        f'<div class="dv-head"><h1>{name}</h1><div class="sub">{pills}</div></div>',
        unsafe_allow_html=True)

    tv_date = (tv or {}).get('_as_of', 'unknown')
    st.markdown(
        f'{badge("TradingView", tv_date)} every ratio it publishes, so this page agrees '
        f'with the screen that surfaced the name &nbsp; {badge("Yahoo", "live")} what '
        f'TradingView does not publish: the business description, forensic scores, '
        f'four-year statement trends, the return decomposition, cash-flow history, '
        f'per-share growth, daily price risk and news.',
        unsafe_allow_html=True)
    if resolution and resolution.get('symbol'):
        st.caption(f"Yahoo symbol {resolution['symbol']} · {resolution.get('exchange')} · "
                   f"{resolution.get('currency')} — {resolution.get('note')}")

    # ---------------- what the company actually does ----------------
    info = (yf_data or {}).get('info') or {}
    summary = info.get('longBusinessSummary')
    if summary or info.get('industry'):
        line = ' · '.join(str(x) for x in [info.get('sector'), info.get('industry'),
                                           info.get('fullTimeEmployees') and
                                           f"{info['fullTimeEmployees']:,} employees",
                                           info.get('website')] if x)
        st.markdown(section('The business'), unsafe_allow_html=True)
        if line:
            st.markdown(f'<div class="dv-note">{badge("Yahoo")} {line}</div>',
                        unsafe_allow_html=True)
        if summary:
            with st.expander('Business description', expanded=True):
                st.write(summary)

    # ---------------- headline, all TradingView ----------------
    st.markdown(section('Headline · TradingView'), unsafe_allow_html=True)
    heads = [('mcap', 'Market cap', 'money'), ('pe', 'P/E', 'x'), ('roe', 'ROE', 'pct'),
             ('op_margin', 'Operating margin', 'pct'), ('net_margin', 'Net margin', 'pct'),
             ('debt_equity', 'Debt / equity', 'x')]
    cols = st.columns(len(heads))
    for col, (key, label, kind) in zip(cols, heads):
        val = (tv or {}).get(key)
        peer = percentile_of(val, stats, key)
        meta = f'{tvp(key) or ""}'
        if peer:
            meta += (f' · sector median {fmt(peer["median"], kind)} · '
                     f'<b>{peer["band"]}</b>')
        col.markdown(card(label, fmt(val, kind), meta), unsafe_allow_html=True)

    # ---------------- solvency, TradingView with the Yahoo forensics beside it ----------
    st.markdown(section('Solvency and earnings integrity'), unsafe_allow_html=True)
    gics = (tv or {}).get('gics')
    financial_sector = gics in ('Financials', 'Real Estate')
    c = st.columns(5)

    if financial_sector:
        c[0].markdown(card('Altman Z', 'n/a',
                           'Neither Altman model applies to a bank, insurer or REIT '
                           'balance sheet', thin=True), unsafe_allow_html=True)
    else:
        z = (tv or {}).get('altman_z')
        band = ('distress' if z is not None and z < 1.8 else
                'grey zone' if z is not None and z < 3 else 'safe' if z is not None else '')
        c[0].markdown(card('Altman Z', fmt(z), f'TradingView · TTM · {band}'),
                      unsafe_allow_html=True)

    f = (tv or {}).get('piotroski_f')
    c[1].markdown(card('Piotroski F', f'{f:.0f}/9' if f is not None else '-',
                       'TradingView · TTM'), unsafe_allow_html=True)

    for slot, key, label, note in (
            (2, 'beneish', 'Beneish M', 'above -1.78 flags manipulation risk'),
            (3, 'ohlson', 'Ohlson O', 'distress probability'),
            (4, 'sloan', 'Sloan accruals', 'lower is cleaner')):
        got = (forensics or {}).get(key) or {}
        val, cov = got.get('score'), got.get('coverage')
        if val is None:
            why = got.get('details') or 'no Yahoo statements available'
            if isinstance(why, dict):
                why = 'inputs incomplete'
            why = str(why)
            c[slot].markdown(card(label, '-', f'Yahoo · {why[:90]}', thin=True),
                             unsafe_allow_html=True)
        else:
            extra = f' · coverage {cov:.0f}%' if cov else ''
            if key == 'ohlson' and got.get('as_pct'):
                # Ohlson returns a probability as a fraction, so it needs scaling before
                # it is printed as a percentage
                shown = fmt(val * 100, 'pct')
            else:
                shown = fmt(val)
            c[slot].markdown(card(label, shown, f'Yahoo · {note}{extra}'),
                             unsafe_allow_html=True)

    st.markdown('<div class="dv-note">Altman and Piotroski come from TradingView so they '
                'match the screener that surfaced this name. The three beside them are not '
                'published by TradingView and are computed here from Yahoo statements, so '
                'they carry a coverage figure - a score built on partial inputs is worth '
                'less than one built on complete inputs, and the page says which is '
                'which.</div>', unsafe_allow_html=True)

    # ---------------- what the market is paying, beyond the P/E ----------------
    # TradingView publishes P/E and forward P/E and nothing else on valuation. These come
    # off the Yahoo info block and are the multiples an analyst reaches for next.
    extra_val = [
        ('enterpriseToEbitda', 'EV / EBITDA', 'x'), ('priceToBook', 'Price / book', 'x'),
        ('priceToSalesTrailing12Months', 'Price / sales', 'x'),
        ('enterpriseToRevenue', 'EV / revenue', 'x'),
        ('trailingPegRatio', 'PEG', 'x'),
        ('dividendYield', 'Dividend yield', 'pct'),
    ]
    have = [(k, l, kind) for k, l, kind in extra_val if info.get(k) is not None]
    if have:
        st.markdown(section('Valuation beyond the P/E'), unsafe_allow_html=True)
        cc = st.columns(len(have))
        for col, (key, label, kind) in zip(cc, have):
            val = info.get(key)
            # Yahoo has reported dividend yield both as a fraction and as a percent across
            # versions, so a value under 1 is read as a fraction
            if key == 'dividendYield' and val is not None and val < 1:
                val *= 100
            col.markdown(card(label, fmt(val, kind), 'Yahoo · TTM'), unsafe_allow_html=True)
        payout = info.get('payoutRatio')
        if payout is not None:
            st.markdown(f'<div class="dv-note">{badge("Yahoo")} Payout ratio '
                        f'{payout*100:,.0f}% of earnings.</div>', unsafe_allow_html=True)

    # ---------------- the analyst view, which TradingView does not export ----------------
    target = info.get('targetMeanPrice')
    n_analysts = info.get('numberOfAnalystOpinions')
    if target or info.get('recommendationKey'):
        st.markdown(section('The analyst view'), unsafe_allow_html=True)
        a = st.columns(5)
        px_now = info.get('currentPrice') or info.get('regularMarketPrice') or tv.get('price')
        upside = ((target / px_now - 1) * 100) if (target and px_now) else None
        a[0].markdown(card('Consensus', str(info.get('recommendationKey') or '-').replace('_', ' ').title(),
                           f'{n_analysts or 0} analysts covering'), unsafe_allow_html=True)
        a[1].markdown(card('Mean target', fmt(target), f'{tv.get("ccy") or ""}'),
                      unsafe_allow_html=True)
        a[2].markdown(card('Implied upside', fmt(upside, 'pct'), 'against the last price'),
                      unsafe_allow_html=True)
        a[3].markdown(card('Target low', fmt(info.get('targetLowPrice')), 'Yahoo'),
                      unsafe_allow_html=True)
        a[4].markdown(card('Target high', fmt(info.get('targetHighPrice')), 'Yahoo'),
                      unsafe_allow_html=True)
        if n_analysts is not None and n_analysts < 4:
            st.markdown(f'<div class="dv-note">Only {n_analysts} analyst opinions sit behind '
                        f'that target. A consensus of three is a coincidence, not a '
                        f'consensus.</div>', unsafe_allow_html=True)

    # ---------------- where the price sits, and who is short ----------------
    lo, hi = info.get('fiftyTwoWeekLow'), info.get('fiftyTwoWeekHigh')
    short_pct = info.get('shortPercentOfFloat')
    if lo and hi:
        st.markdown(section('Position and positioning'), unsafe_allow_html=True)
        px_now = info.get('currentPrice') or info.get('regularMarketPrice') or tv.get('price')
        pos = ((px_now - lo) / (hi - lo) * 100) if (px_now and hi > lo) else None
        p = st.columns(5)
        p[0].markdown(card('52-week range', f'{fmt(lo)} – {fmt(hi)}', 'Yahoo'),
                      unsafe_allow_html=True)
        p[1].markdown(card('Position in range', fmt(pos, 'pct'),
                           '0% at the low, 100% at the high'), unsafe_allow_html=True)
        p[2].markdown(card('Short interest', fmt(short_pct*100 if short_pct else None, 'pct'),
                           'of free float' if short_pct else 'not reported'),
                      unsafe_allow_html=True)
        p[3].markdown(card('Held by institutions',
                           fmt(info.get('heldPercentInstitutions', 0)*100
                               if info.get('heldPercentInstitutions') else None, 'pct'),
                           'Yahoo'), unsafe_allow_html=True)
        p[4].markdown(card('Held by insiders',
                           fmt(info.get('heldPercentInsiders', 0)*100
                               if info.get('heldPercentInsiders') else None, 'pct'),
                           'Yahoo'), unsafe_allow_html=True)
        if short_pct and short_pct > 0.08:
            st.markdown(f'<div class="dv-note">Short interest of {short_pct*100:.1f}% of '
                        f'float is high. Someone has done work that reaches the opposite '
                        f'conclusion, and it is worth knowing what before acting on '
                        f'anything above.</div>', unsafe_allow_html=True)

    # ---------------- DuPont ----------------
    rows = dupont(fin, bs)
    if rows:
        st.markdown(section('What drives the return on equity'), unsafe_allow_html=True)
        table = pd.DataFrame(rows).rename(columns={
            'period': 'Period', 'net_margin_pct': 'Net margin %',
            'asset_turnover': 'Asset turnover', 'equity_multiplier': 'Equity multiplier',
            'roe_pct': 'ROE %'})
        st.dataframe(table, use_container_width=True, hide_index=True)
        last = rows[-1]
        driver = ('operating margin' if last['net_margin_pct'] >= 10 else
                  'asset turnover' if last['asset_turnover'] >= 1 else 'balance sheet leverage')
        st.markdown(
            f'<div class="dv-note">{badge("Yahoo", "annual")} ROE of '
            f'{last["roe_pct"]:.1f}% = margin {last["net_margin_pct"]:.1f}% × turnover '
            f'{last["asset_turnover"]:.2f} × leverage {last["equity_multiplier"]:.2f}. '
            f'The dominant contributor is {driver}. A high ROE earned on leverage is a '
            f'different proposition from the same ROE earned on margin, and the headline '
            f'figure cannot separate them.</div>', unsafe_allow_html=True)

    # ---------------- quality of earnings ----------------
    qrows, verdict = quality_of_earnings(fin, cf)
    if any(r['cfo_to_ni'] is not None for r in qrows):
        st.markdown(section('Does the profit arrive as cash'), unsafe_allow_html=True)
        q = pd.DataFrame([{'Period': r['period'],
                           'Net income': fmt(r['net_income'], 'money'),
                           'Operating cash flow': fmt(r['cfo'], 'money'),
                           'CFO / net income': fmt(r['cfo_to_ni'], 'x')} for r in qrows])
        st.dataframe(q, use_container_width=True, hide_index=True)
        if verdict:
            st.markdown(f'<div class="dv-note">{badge("Yahoo", "annual")} {verdict}</div>',
                        unsafe_allow_html=True)

    # ---------------- capital allocation ----------------
    ca = capital_allocation(cf)
    if ca.get('uses'):
        st.markdown(section('Where the cash went'), unsafe_allow_html=True)
        st.markdown(f'<div class="dv-note">{badge("Yahoo", "annual")} Cumulative operating '
                    f'cash flow of <b>{fmt(ca["cumulative_cfo"], "money")}</b> over '
                    f'{ca["years"]} years, {ca["period_from"]} to {ca["period_to"]}.</div>',
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([{'Use of cash': u['use'],
                                    'Amount': fmt(u['amount'], 'money'),
                                    '% of operating cash flow': f'{u["pct_of_cfo"]}%'
                                    if u['pct_of_cfo'] is not None else '-'}
                                   for u in ca['uses']]),
                     use_container_width=True, hide_index=True)

    # ---------------- per share growth ----------------
    ps = per_share_growth(fin, bs)
    if ps and ps.get('revenue_cagr_pct') is not None:
        st.markdown(section('Growth the holder actually received'), unsafe_allow_html=True)
        g = st.columns(4)
        g[0].markdown(card('Revenue CAGR', fmt(ps['revenue_cagr_pct'], 'pct'),
                           f'{ps["from"]} to {ps["to"]}'), unsafe_allow_html=True)
        g[1].markdown(card('Revenue per share CAGR',
                           fmt(ps.get('revenue_per_share_cagr_pct'), 'pct'),
                           'after any change in share count'), unsafe_allow_html=True)
        g[2].markdown(card('EPS CAGR', fmt(ps.get('eps_cagr_pct'), 'pct'), 'per share'),
                      unsafe_allow_html=True)
        sc = ps.get('share_count_cagr_pct')
        g[3].markdown(card('Share count CAGR', fmt(sc, 'pct'),
                           'buying back' if (sc or 0) < 0 else 'issuing'),
                      unsafe_allow_html=True)
        if sc is not None and ps.get('revenue_per_share_cagr_pct') is not None:
            gap = ps['revenue_cagr_pct'] - ps['revenue_per_share_cagr_pct']
            if gap > 1:
                st.markdown(f'<div class="dv-note">Revenue grew {gap:.1f} points a year '
                            f'faster than revenue per share. That gap is dilution, and a '
                            f'holder did not receive it.</div>', unsafe_allow_html=True)

    # ---------------- risk ----------------
    risk = price_risk(hist)
    if risk.get('vol_1y_pct') is not None:
        st.markdown(section('Price risk'), unsafe_allow_html=True)
        r = st.columns(5)
        r[0].markdown(card('Volatility 1Y', fmt(risk['vol_1y_pct'], 'pct'),
                           'Yahoo · annualised daily'), unsafe_allow_html=True)
        r[1].markdown(card('Max drawdown', fmt(risk['max_drawdown_pct'], 'pct'),
                           f'trough {risk.get("drawdown_from") or ""}'),
                      unsafe_allow_html=True)
        r[2].markdown(card('vs 200-day average', fmt(risk['pct_vs_200dma'], 'pct'),
                           'Yahoo · live'), unsafe_allow_html=True)
        r[3].markdown(card('1Y performance', fmt((tv or {}).get('perf_1y'), 'pct'),
                           f'TradingView · {tv_date}'), unsafe_allow_html=True)
        r[4].markdown(card('RSI 14', fmt((tv or {}).get('rsi14'), 'num', 1),
                           'TradingView'), unsafe_allow_html=True)
        if hist is not None and 'Close' in hist:
            close = hist['Close'].dropna()
            span = st.radio('Range', ['3M', '6M', '1Y', '2Y'], index=2, horizontal=True,
                            label_visibility='collapsed', key='span')
            days = {'3M': 63, '6M': 126, '1Y': 252, '2Y': 504}[span]
            # the moving averages are computed on the full series and then trimmed, so a
            # short view still shows a correct 200-day line instead of a truncated one
            chart = pd.DataFrame({'Price': close})
            if len(close) >= 50:
                chart['50-day average'] = close.rolling(50).mean()
            if len(close) >= 200:
                chart['200-day average'] = close.rolling(200).mean()
            st.line_chart(chart.tail(days), height=300)

            window = close.tail(days)
            if len(window) > 2:
                peak = window.cummax()
                dd = ((window / peak) - 1) * 100
                st.markdown(f'<div class="dv-note">Over the last {span.lower()}: '
                            f'high {fmt(float(window.max()))}, low {fmt(float(window.min()))}, '
                            f'change {fmt(float((window.iloc[-1]/window.iloc[0]-1)*100), "pct")}, '
                            f'deepest fall from a peak within the window '
                            f'{fmt(float(dd.min()), "pct")}.</div>',
                            unsafe_allow_html=True)
            with st.expander('Drawdown from the running peak, full two years'):
                full_peak = close.cummax()
                st.area_chart(((close / full_peak) - 1) * 100, height=200)
                st.caption('Zero means the price is at a new high. This is the line that '
                           'tells you what holding it actually felt like.')

    # ---------------- ownership, the piece nobody else has ----------------
    if tv and tv.get('marquee'):
        st.markdown(section('Superinvestor ownership · Dataroma'), unsafe_allow_html=True)
        o = st.columns(3)
        o[0].markdown(card('Investors holding', fmt(tv.get('marquee_investors'), 'int'),
                           f'as of {(tv or {}).get("_marquee_as_of", "")}'),
                      unsafe_allow_html=True)
        o[1].markdown(card('Aggregate portfolio weight',
                           fmt(tv.get('marquee_weight_pct'), 'pct'),
                           'across all tracked portfolios'), unsafe_allow_html=True)
        o[2].markdown(card('In the screen', 'Yes' if tv.get('screened') else 'No',
                           'cleared its sector thresholds'), unsafe_allow_html=True)

    # ---------------- the institutions on the register ----------------
    holders = (yf_data or {}).get('institutional_holders')
    if holders is not None and hasattr(holders, 'empty') and not holders.empty:
        st.markdown(section('Largest institutional holders'), unsafe_allow_html=True)
        st.markdown(f'<div class="dv-note">{badge("Yahoo")} The whole institutional '
                    f'register, index funds included. The Dataroma block above is a '
                    f'different question - not who owns it, but which discretionary '
                    f'investors chose it.</div>', unsafe_allow_html=True)
        h = holders.copy()
        for col in h.columns:
            if 'Value' in str(col) or 'Shares' in str(col):
                h[col] = h[col].apply(lambda v: fmt(v, 'money') if pd.notna(v) else '-')
            if 'Out' in str(col) or 'pctHeld' in str(col):
                h[col] = h[col].apply(
                    lambda v: fmt(v*100 if pd.notna(v) and v < 1 else v, 'pct')
                    if pd.notna(v) else '-')
        st.dataframe(h.head(10), use_container_width=True, hide_index=True)

    # ---------------- full TradingView table ----------------
    with st.expander('Every TradingView field, with its period'):
        table = []
        for key, label in LABELS.items():
            val = (tv or {}).get(key)
            kind = 'pct' if key in PERCENT_METRICS else (
                'x' if key in ('pe', 'fpe', 'current_ratio', 'debt_equity',
                               'interest_cover', 'ebitda_cover') else 'num')
            peer = percentile_of(val, stats, key)
            table.append({'Metric': label, 'Value': fmt(val, kind),
                          'Period': tvp(key) or '',
                          'Sector median': fmt(peer['median'], kind) if peer else '-',
                          'Position': peer['band'] if peer else '-'})
        st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)

    # ---------------- news, which only Yahoo carries ----------------
    news = (yf_data or {}).get('news') or []
    if news:
        st.markdown(section('Recent coverage'), unsafe_allow_html=True)
        st.markdown(f'<div class="dv-note">{badge("Yahoo")} Headlines as at the last fetch. '
                    f'Yahoo is the only source here that carries news at all, and it is '
                    f'thin - treat this as a pointer, not as coverage.</div>',
                    unsafe_allow_html=True)
        shown = 0
        for item in news:
            content = item.get('content') if isinstance(item.get('content'), dict) else item
            title = content.get('title') or item.get('title')
            if not title:
                continue
            link = ((content.get('canonicalUrl') or {}).get('url')
                    if isinstance(content.get('canonicalUrl'), dict)
                    else content.get('link') or item.get('link'))
            pub = (content.get('provider') or {}).get('displayName') \
                if isinstance(content.get('provider'), dict) else item.get('publisher')
            stamp = content.get('pubDate') or item.get('providerPublishTime')
            if isinstance(stamp, (int, float)):
                stamp = datetime.datetime.fromtimestamp(stamp).strftime('%d %b %Y')
            bits = ' · '.join(str(x)[:40] for x in [pub, stamp] if x)
            st.markdown(f"- [{title}]({link})  \n<span class='dv-note'>{bits}</span>"
                        if link else f"- {title}  \n<span class='dv-note'>{bits}</span>",
                        unsafe_allow_html=True)
            shown += 1
            if shown >= 6:
                break

    # ---------------- what is deliberately absent ----------------
    with st.expander('What this page does not show, and why'):
        st.markdown(
            '- **Ten years of history.** Yahoo returns four annual periods. Anything '
            'longer would have to be invented.\n'
            '- **Segment revenue, guidance, transcripts, analyst estimates.** Not in this '
            'data set at any price.\n'
            '- **Point-in-time statements.** Restatements silently overwrite prior years, '
            'so this is fine for analysis and unusable for backtesting.\n'
            '- **Altman for financials.** Both models assume a non-financial balance '
            'sheet, so the page shows nothing rather than a number that reads well and '
            'means little.\n'
            '- **A recommendation.** Every figure here is an input.')


# ---------------------------------------------------------------- landing page ----------
def _search_feed(feed, query, limit=25):
    """Match on ticker, company name or ISIN. Exact ticker hits rank first."""
    q = str(query or '').strip().upper()
    if len(q) < 2:
        return []
    exact, starts, contains = [], [], []
    for isin, e in (feed.get('stocks') or {}).items():
        ticker = str(e.get('ticker') or '').upper()
        name = str(e.get('name') or '').upper()
        row = (isin, e)
        if ticker == q or isin.upper() == q:
            exact.append(row)
        elif ticker.startswith(q) or name.startswith(q):
            starts.append(row)
        elif q in name or q in ticker:
            contains.append(row)
        if len(exact) + len(starts) + len(contains) > 400:
            break
    ranked = exact + sorted(starts, key=lambda r: -(r[1].get('mcap') or 0)) + \
        sorted(contains, key=lambda r: -(r[1].get('mcap') or 0))
    return ranked[:limit]


def render_landing(st, feed, sector_stats, screener_url=FEED_BASE):
    """The page someone sees when they open the app without a company in the URL.

    Deliberately built from the published feed alone, with no Yahoo call anywhere, so it
    opens immediately. Yahoo is only worth waking up once a company has been chosen.
    """
    st.markdown(CSS, unsafe_allow_html=True)
    stocks = feed.get('stocks') or {}
    total = len(stocks)
    marquee = sum(1 for e in stocks.values() if e.get('marquee'))
    screened = sum(1 for e in stocks.values() if e.get('screened'))
    both = sum(1 for e in stocks.values() if e.get('marquee') and e.get('screened'))

    st.markdown(
        f'<div class="dv-head"><h1>Equity Analysis</h1><div class="sub">'
        f'<span class="dv-pill">TradingView · {feed.get("as_of", "")}</span>'
        f'<span class="dv-pill">Dataroma · {feed.get("marquee_as_of", "")}</span>'
        f'<span class="dv-pill">{total:,} companies</span>'
        f'</div></div>', unsafe_allow_html=True)

    st.markdown(
        'Screening happens on the TradingView universe and produces the shortlist. This '
        'app is the second step: pick one company and it assembles the analysis Yahoo can '
        'add over and above what the screener already knows - how the return on equity is '
        'earned, whether reported profit arrives as cash, where the cash went, what a '
        'holder actually received per share, and the forensic scores TradingView does not '
        'publish.')

    c = st.columns(4)
    c[0].markdown(card('In this feed', f'{total:,}',
                       'screened names plus every marquee holding'), unsafe_allow_html=True)
    c[1].markdown(card('Cleared a screen', f'{screened:,}',
                       'passed their own sector thresholds'), unsafe_allow_html=True)
    c[2].markdown(card('Superinvestor held', f'{marquee:,}', 'tracked by Dataroma'),
                  unsafe_allow_html=True)
    c[3].markdown(card('Both', f'{both:,}',
                       'held by superinvestors and through the screen'),
                  unsafe_allow_html=True)

    # ---------------- search ----------------
    st.markdown(section('Find a company'), unsafe_allow_html=True)
    query = st.text_input('Ticker, company name or ISIN',
                          placeholder='NVDA, Nestle, US67066G1040',
                          label_visibility='collapsed')
    if query:
        hits = _search_feed(feed, query)
        if not hits:
            st.info(f'Nothing matching "{query}" in this feed. It carries screened names '
                    f'and marquee holdings, not the whole 30,000 stock universe, so a name '
                    f'that failed every screen will not appear here.')
        for isin, e in hits[:12]:
            row = st.columns([3, 2, 2, 2, 1.6])
            flag = ' ★' if e.get('marquee') else ''
            row[0].markdown(f"**{e.get('ticker')}**{flag}  \n{e.get('name')}")
            row[1].markdown(f"{e.get('gics') or '-'}  \n<span class='dv-note'>"
                            f"{e.get('country') or ''}</span>", unsafe_allow_html=True)
            row[2].markdown(f"{fmt(e.get('mcap'), 'money')}  \n<span class='dv-note'>"
                            f"market cap</span>", unsafe_allow_html=True)
            row[3].markdown(f"P/E {fmt(e.get('pe'), 'x')}  \n<span class='dv-note'>"
                            f"ROE {fmt(e.get('roe'), 'pct')}</span>", unsafe_allow_html=True)
            if row[4].button('Analyse', key=f'go_{isin}'):
                st.query_params['ticker'] = e.get('ticker') or ''
                st.query_params['isin'] = isin
                if e.get('ccy'):
                    st.query_params['ccy'] = e['ccy']
                st.rerun()

    # ---------------- where to start ----------------
    st.markdown(section('Somewhere to start'), unsafe_allow_html=True)
    tab_names = ['Most widely held', 'Cheapest that cleared a screen', 'Highest quality']
    tabs = st.tabs(tab_names)

    def show(rows, extra_label, extra_key, extra_kind):
        if not rows:
            st.caption('Nothing to show from this feed.')
            return
        table = []
        for isin, e in rows:
            row = {'Ticker': e.get('ticker'), 'Company': e.get('name'),
                   'Sector': e.get('gics'), 'Country': e.get('country'),
                   extra_label: fmt(e.get(extra_key), extra_kind)}
            # the ranking column is already shown, so do not repeat it below
            if extra_key != 'pe':
                row['P/E'] = fmt(e.get('pe'), 'x')
            if extra_key != 'roe':
                row['ROE'] = fmt(e.get('roe'), 'pct')
            row['Market cap'] = fmt(e.get('mcap'), 'money')
            row['ISIN'] = isin
            table.append(row)
        st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
        st.caption('Paste an ISIN into the search box above to open its analysis.')

    held = sorted([(k, v) for k, v in stocks.items() if v.get('marquee_investors')],
                  key=lambda r: -(r[1].get('marquee_investors') or 0))[:15]
    with tabs[0]:
        show(held, 'Investors holding', 'marquee_investors', 'int')

    # A P/E below about 2 is almost always a depositary receipt quoted per fractional
    # share, or a stale price, rather than a bargain. Anything under $300m is too thin to
    # act on. Both are excluded so this list is something you could actually use.
    cheap = sorted([(k, v) for k, v in stocks.items()
                    if v.get('screened') and (v.get('pe') or 0) >= 2
                    and (v.get('mcap') or 0) >= 3e8
                    and (v.get('roe') or 0) > 0],
                   key=lambda r: (r[1].get('pe') or 1e9))[:15]
    with tabs[1]:
        show(cheap, 'P/E', 'pe', 'x')

    quality = sorted([(k, v) for k, v in stocks.items()
                      if v.get('screened') and v.get('roe') is not None
                      and (v.get('piotroski_f') or 0) >= 8
                      and (v.get('mcap') or 0) >= 3e8],
                     key=lambda r: -(r[1].get('roe') or 0))[:15]
    with tabs[2]:
        show(quality, 'Piotroski F', 'piotroski_f', 'int')

    # ---------------- sector shape ----------------
    if sector_stats:
        st.markdown(section('What each sector looks like'), unsafe_allow_html=True)
        rows = []
        for gics, block in sorted(sector_stats.items()):
            rows.append({
                'Sector': gics, 'Companies': f"{block.get('count', 0):,}",
                'Median P/E': fmt((block.get('pe') or {}).get('median'), 'x'),
                'Median ROE': fmt((block.get('roe') or {}).get('median'), 'pct'),
                'Median op margin': fmt((block.get('op_margin') or {}).get('median'), 'pct'),
                'Median Altman Z': fmt((block.get('altman_z') or {}).get('median')),
                'Median Piotroski': fmt((block.get('piotroski_f') or {}).get('median'), 'int'),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.markdown('<div class="dv-note">These medians come from the full TradingView '
                    'universe, not from the screened subset. A median taken from names '
                    'that already passed a quality screen is a median of the winners, and '
                    'would make every company on this app look average.</div>',
                    unsafe_allow_html=True)

    st.divider()
    st.caption(f'Full screener with all filters: {screener_url}/')


# ---------------------------------------------------------------- routing ---------------
def read_link():
    """Read ?ticker=, ?isin= and ?ccy= off the URL, whichever Streamlit API exists."""
    def grab(params, key):
        raw = params.get(key)
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        return str(raw).strip() if raw else None

    try:
        params = st.query_params
        _ = params.get('ticker')
    except Exception:
        try:
            params = st.experimental_get_query_params()
        except Exception:
            return None, None, None
    return grab(params, 'ticker'), grab(params, 'isin'), grab(params, 'ccy')


@st.cache_data(ttl=900, show_spinner=False)
def load_tv_feed():
    return fetch_feed(STOCKS_URL)


@st.cache_data(ttl=3600, show_spinner=False)
def load_sector_stats():
    return fetch_feed(SECTOR_URL)


@st.cache_data(ttl=900, show_spinner=False)
def load_yahoo(symbol):
    """Cached per symbol, so paging back to a company does not refetch it."""
    return df_mod.get_ticker_data(symbol)


def compute_forensics(yf_data, tv_entry):
    """Only the scores TradingView does not publish. Altman and Piotroski come from the
    feed, so recomputing them here would only invite a disagreement with the screener."""
    out = {}
    beneish = ff.calc_beneish_m_score(yf_data)
    out['beneish'] = {'score': beneish.get('score'), 'coverage': beneish.get('coverage'),
                      'details': beneish.get('details')}
    try:
        ohlson = ff.calc_ohlson_o_score(yf_data)
        prob = ohlson.get('probability')
        out['ohlson'] = {'score': prob if prob is not None else ohlson.get('score'),
                         'as_pct': prob is not None, 'details': ohlson.get('details')}
    except Exception as e:
        out['ohlson'] = {'score': None, 'details': f'not computed: {e}'}
    try:
        sloan = ff.calc_sloan_accrual_ratio(yf_data)
        out['sloan'] = {'score': sloan.get('score') if isinstance(sloan, dict) else sloan,
                        'details': sloan.get('details') if isinstance(sloan, dict) else ''}
    except Exception as e:
        out['sloan'] = {'score': None, 'details': f'not computed: {e}'}
    return out


def run_company(ticker, isin, ccy):
    tv_entry, tv_isin, stats = None, isin, {}
    try:
        feed = load_tv_feed()
        tv_isin, tv_entry = lookup(feed, isin=isin, ticker=ticker)
        if tv_entry is not None:
            tv_entry = dict(tv_entry)
            tv_entry['_periods'] = feed.get('periods', {})
            tv_entry['_as_of'] = feed.get('as_of')
            tv_entry['_marquee_as_of'] = feed.get('marquee_as_of')
    except Exception as e:
        st.warning(f'The TradingView feed did not load ({e}), so the headline ratios below '
                   f'fall back to Yahoo annual figures instead of trailing twelve months.')
    try:
        stats = load_sector_stats().get('sectors', {})
    except Exception:
        stats = {}

    resolution, symbol = None, (ticker or '').upper() or None
    if isin and df_mod.looks_like_isin(isin):
        with st.spinner(f'Resolving {isin} on Yahoo...'):
            resolution = df_mod.resolve_isin(isin, expect_currency=ccy)
        if resolution.get('symbol'):
            symbol = resolution['symbol']

    yf_data, forensics = None, {}
    if symbol:
        with st.spinner(f'Pulling {symbol} from Yahoo...'):
            yf_data = load_yahoo(symbol)
        if yf_data and not yf_data.get('error'):
            forensics = compute_forensics(yf_data, tv_entry)
            # a partial fetch is still worth having, so say what is thin rather than
            # dropping the lot
            thin = {k: v for k, v in (yf_data.get('fetch_status') or {}).items()
                    if v != 'ok'}
            if thin:
                with st.expander(f'Yahoo returned {len(thin)} incomplete piece(s) - '
                                 f'what is affected'):
                    for part, why in thin.items():
                        st.markdown(f'- **{part}** — {why}')
                    st.caption('Yahoo throttles hosted apps, and the info endpoint goes '
                               'first. Statements and prices usually survive, which is why '
                               'each piece is now fetched on its own. Reloading in a minute '
                               'often fills the gaps.')
        else:
            st.warning(f'Yahoo returned nothing usable for {symbol}, so the forensic '
                       f'scores, four-year trends and price history are all missing from '
                       f'this page. Everything sourced from TradingView below is '
                       f'unaffected.')
            with st.expander('What Yahoo said'):
                st.code((yf_data or {}).get('error', 'no detail returned'))
            yf_data = None

    if tv_entry is None and yf_data is None:
        st.error(f'Neither source has anything for {ticker or isin}.')
        if st.button('Back'):
            st.query_params.clear()
            st.rerun()
        st.stop()
        return

    render(st, tv_entry or {}, tv_isin or isin, yf_data, stats, forensics, resolution)
    st.divider()
    if st.button('Back to search'):
        st.query_params.clear()
        st.rerun()
    st.caption(f'Full screener with every filter: {FEED_BASE}/')


def main():
    ticker, isin, ccy = read_link()
    if ticker or isin:
        run_company(ticker, isin, ccy)
        return
    try:
        feed = load_tv_feed()
    except Exception as e:
        st.error(f'Could not load the published feed ({e}). The screener build publishes '
                 f'it, so if that has not run yet there is nothing here to show.')
        st.stop()
        return
    try:
        stats = load_sector_stats().get('sectors', {})
    except Exception:
        stats = {}
    render_landing(st, feed, stats)


main()
