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
  .block-container {padding-top:0.4rem; padding-bottom:1rem; max-width:1500px;}
  /* Streamlit leaves a gap for every element it renders. The page is one markdown block,
  so those gaps only create empty bands. Note the indentation: four spaces would make
  markdown treat the line as a code block and drop the rule. */
  div[data-testid="stVerticalBlock"] > div:empty {display:none;}
  div[data-testid="stMarkdownContainer"] > :first-child {margin-top:0;}
  .stApp > header {height:0;}
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
        # a ratio against a loss is meaningless: -40m of profit and 200m of cash gives
        # -5.00x, which reads as terrible when it is in fact the opposite. Those years are
        # left blank and excluded from the average.
        ratio = round(c / n, 2) if (n is not None and n > 0 and c is not None) else None
        rows.append({'period': label, 'net_income': n, 'cfo': c, 'cfo_to_ni': ratio})
    usable = [r for r in rows if r['cfo_to_ni'] is not None]
    verdict = None
    if len(usable) >= 2:
        avg = sum(r['cfo_to_ni'] for r in usable) / len(usable)
        loss_years = sum(1 for r in rows if (r.get('net_income') or 0) <= 0)
        caveat = ((f' The loss year is excluded' if loss_years == 1 else
                   f' The {loss_years} loss years are excluded')
                  + ', since a ratio against a loss carries no meaning.'
                  if loss_years else '')
        if avg >= 1.1:
            verdict = ('<b>The profit is backed by cash.</b> Operating cash flow has run '
                       'ahead of reported earnings in every profitable year here, which is '
                       'the order you want them in.' + caveat)
        elif avg >= 0.9:
            verdict = ('<b>Cash and profit track each other.</b> Nothing here to flag either '
                       'way.' + caveat)
        else:
            verdict = ('<b>Profit is running ahead of cash.</b> That gap is the first thing '
                       'to understand about this company, ahead of anything else on this '
                       'page.' + caveat)
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
# ---------------------------------------------------------------- the page --------------
SPANS = {'3M': 63, '6M': 126, '1Y': 252, '2Y': 504, '5Y': 1260, '10Y': 2520, 'Max': None}


def render(st, tv, isin, yf_data, sector_stats, forensics, resolution=None):
    """Draw the analysis page.

    The page itself is one block of HTML built by page.build. Only the range selector is a
    Streamlit widget, because it has to trigger a rerun; everything else is laid out in the
    HTML so the result matches the design rather than Streamlit's default spacing.
    """
    import page as pg

    fin = (yf_data or {}).get('financials')
    bs = (yf_data or {}).get('balance_sheet')
    cf = (yf_data or {}).get('cashflow')
    hist = (yf_data or {}).get('history')
    stats = (sector_stats or {}).get((tv or {}).get('gics')) or {}

    # the range comes off the query string, so the buttons can live inside the chart card
    # rather than above the whole page as a Streamlit widget
    def qp(key):
        raw = st.query_params.get(key) if hasattr(st, 'query_params') else None
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        return raw

    span_label, close, ma50, ma200, spans = '1Y', None, None, None, []
    if hist is not None and 'Close' in hist and len(hist) > 5:
        spans = [k for k, n in SPANS.items() if n is None or len(hist) >= n * 0.6]
        wanted = qp('span')
        span_label = wanted if wanted in spans else ('1Y' if '1Y' in spans else spans[-1])
        full = hist['Close'].dropna()
        # averages are computed on the full series and then sliced, so a short window still
        # carries a correct 200 day line rather than a truncated one
        full_ma50, full_ma200 = full.rolling(50).mean(), full.rolling(200).mean()
        n = SPANS[span_label]
        close = full if n is None else full.tail(n)
        ma50, ma200 = full_ma50.reindex(close.index), full_ma200.reindex(close.index)

    # everything except span, so a range click keeps the company it is looking at
    keep = [(k, qp(k)) for k in ('ticker', 'isin', 'ccy')]
    base_query = ''.join(f'{k}={v}&' for k, v in keep if v)

    risk = price_risk(hist)
    # a second beta over five years, now that the full history is available
    if hist is not None and 'Close' in hist and len(hist) > 1300:
        risk['beta_5y'] = price_risk(hist.tail(1260)).get('beta_2y')
    else:
        risk['beta_5y'] = None

    lede = st.session_state.get('lede', '')

    html = pg.build(tv or {}, isin, yf_data, stats, forensics, resolution, risk,
                    dupont(fin, bs), *quality_of_earnings(fin, cf),
                    capital_allocation(cf), per_share_growth(fin, bs),
                    span_label, close, ma50, ma200, lede, spans, base_query,
                    percentile_of)
    st.markdown(html, unsafe_allow_html=True)

    # the report, as a standalone file. The page is already one block of self contained
    # HTML with print rules, so the download opens and prints to PDF with the layout intact.
    ticker = (tv or {}).get('ticker') or 'company'
    name = (tv or {}).get('name') or ticker
    stamp = (tv or {}).get('_as_of', '')
    # A clean document title matters: if the browser's print header is left on, it prints
    # the title, so this makes it read as a report rather than as a file path.
    doc_title = f'{name} equity analysis, {stamp}' if stamp else f'{name} equity analysis'
    report = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
              '<meta name="viewport" content="width=device-width,initial-scale=1">'
              f'<title>{doc_title}</title>'
              '<style>@page{size:A4 portrait;margin:11mm 9mm}'
              'body{margin:0;background:#e7ecf3;padding:16px}'
              '@media print{body{background:#fff;padding:0}}</style></head><body>'
              + html + '</body></html>')
    st.download_button('Download this report', report,
                       file_name=f'{ticker}_equity_analysis_'
                                 f'{datetime.date.today():%Y-%m-%d}.html',
                       mime='text/html')
    st.caption('Downloads one self contained file. Open it and print to PDF, or press '
               'Ctrl+P on this page. Before saving, untick **Headers and footers** in the '
               'print dialog: that setting is what prints the date, the page title and the '
               'file path down the edges of the page, and no stylesheet can switch it off. '
               'Chrome remembers the choice afterwards. The report prints its own header '
               'with the company, the ticker and the data date, so nothing is lost by '
               'turning the browser one off.')

    with st.expander('Write the reading that appears at the foot of this page'):
        st.text_area('One paragraph, in your own words. The three columns below it are '
                     'generated from the figures; this paragraph is the judgement, so it is '
                     'left to a person.', key='lede', height=110,
                     placeholder='Left blank, the paragraph is omitted and only the '
                                 'evidence columns show.')
        st.caption('Saved for this session only.')


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

    Same shape it always had: a header, four counts, a search box, three starting lists and
    the sector table. Only the palette and the typeface have changed, so that it matches the
    company page instead of carrying a second design of its own.

    Built from the published feed alone, with no Yahoo call anywhere, so it opens straight
    away. Yahoo is only worth waking up once a company has been chosen.
    """
    import page as pg
    st.markdown(pg.CSS, unsafe_allow_html=True)
    stocks = feed.get('stocks') or {}
    total = len(stocks)
    marquee = sum(1 for e in stocks.values() if e.get('marquee'))
    screened = sum(1 for e in stocks.values() if e.get('screened'))
    both = sum(1 for e in stocks.values() if e.get('marquee') and e.get('screened'))

    st.markdown(
        f'<div class="an"><div class="mast"><div>'
        f'<div class="eyebrow">MICS International, internal research</div>'
        f'<h1>Equity analysis</h1>'
        f'<div class="meta"><b>TradingView</b> {pg.esc(feed.get("as_of", ""))}'
        f'<span class="sep">/</span><b>Dataroma</b> '
        f'{pg.esc(feed.get("marquee_as_of", ""))}'
        f'<span class="sep">/</span>{total:,} companies in this feed</div>'
        f'</div></div></div>', unsafe_allow_html=True)

    st.markdown(pg.lede(
        'Screening runs on the TradingView universe and produces the shortlist. This is the '
        'second step: pick one company and the page assembles what Yahoo can add over and '
        'above the screen. How the return on equity is earned, whether reported profit '
        'arrives as cash, where that cash went, what a holder actually received per share, '
        'and the forensic scores TradingView does not publish.'), unsafe_allow_html=True)

    # One markdown call, not four columns. Four calls meant four separate blocks and the
    # browser stacked them down the left of the page.
    st.markdown(pg.counts([
        ('In this feed', f'{total:,}', 'screened names and marquee holdings'),
        ('Cleared a screen', f'{screened:,}', 'passed their own sector thresholds'),
        ('Superinvestor held', f'{marquee:,}', 'tracked by Dataroma'),
        ('Both', f'{both:,}', 'through the screen and held')]),
        unsafe_allow_html=True)

    st.markdown(pg.section('Find a company'), unsafe_allow_html=True)
    query = st.text_input('Ticker, company name or ISIN',
                          placeholder='NVDA, Nestle, US67066G1040',
                          label_visibility='collapsed')
    if query:
        hits = _search_feed(feed, query)
        if not hits:
            st.info(f'Nothing matching "{query}". This feed carries screened names and '
                    f'marquee holdings, not the whole 30,000 stock universe, so a company '
                    f'that failed every screen will not be here.')
        for isin, e in hits[:12]:
            row = st.columns([3, 2, 2, 2, 1.5])
            flag = ' held' if e.get('marquee') else ''
            row[0].markdown(f"**{e.get('ticker')}**{flag}  \n{e.get('name')}")
            row[1].markdown(f"{e.get('gics') or ''}  \n{e.get('country') or ''}")
            row[2].markdown(f"{pg.f(e.get('mcap'), 'money')}  \nmarket cap")
            row[3].markdown(f"P/E {pg.f(e.get('pe'), 'x')}  \nROE {pg.f(e.get('roe'), 'pct')}")
            if row[4].button('Analyse', key=f'go_{isin}'):
                st.query_params['ticker'] = e.get('ticker') or ''
                st.query_params['isin'] = isin
                if e.get('ccy'):
                    st.query_params['ccy'] = e['ccy']
                st.rerun()

    st.markdown(pg.section('Somewhere to start',
                           'paste any ISIN below into the box above'),
                unsafe_allow_html=True)

    def table(rows, extra_label, extra_key, extra_kind):
        if not rows:
            st.caption('Nothing to show from this feed.')
            return
        out = []
        for isin, e in rows:
            r = {'Ticker': e.get('ticker'), 'Company': e.get('name'),
                 'Sector': e.get('gics'), 'Country': e.get('country'),
                 extra_label: pg.f(e.get(extra_key), extra_kind)}
            if extra_key != 'pe':
                r['P/E'] = pg.f(e.get('pe'), 'x')
            if extra_key != 'roe':
                r['ROE'] = pg.f(e.get('roe'), 'pct')
            r['Market cap'] = pg.f(e.get('mcap'), 'money')
            r['ISIN'] = isin
            out.append(r)
        st.dataframe(pd.DataFrame(out), use_container_width=True, hide_index=True)

    tabs = st.tabs(['Most widely held', 'Highest conviction', 'Cheapest that cleared',
                    'Highest quality'])
    with tabs[0]:
        table(sorted([(k, v) for k, v in stocks.items() if v.get('marquee_investors')],
                     key=lambda r: -(r[1].get('marquee_investors') or 0))[:15],
              'Investors holding', 'marquee_investors', 'int')
    with tabs[1]:
        # the largest single position is the conviction measure, not the aggregate weight
        table(sorted([(k, v) for k, v in stocks.items() if v.get('marquee_max_pct')],
                     key=lambda r: -(r[1].get('marquee_max_pct') or 0))[:15],
              'Largest single position', 'marquee_max_pct', 'pct')
    with tabs[2]:
        table(sorted([(k, v) for k, v in stocks.items()
                      if v.get('screened') and (v.get('pe') or 0) >= 2
                      and (v.get('mcap') or 0) >= 3e8 and (v.get('roe') or 0) > 0],
                     key=lambda r: (r[1].get('pe') or 1e9))[:15], 'P/E', 'pe', 'x')
    with tabs[3]:
        table(sorted([(k, v) for k, v in stocks.items()
                      if v.get('screened') and v.get('roe') is not None
                      and (v.get('piotroski_f') or 0) >= 8 and (v.get('mcap') or 0) >= 3e8],
                     key=lambda r: -(r[1].get('roe') or 0))[:15],
              'Piotroski F', 'piotroski_f', 'int')

    if sector_stats:
        st.markdown(pg.section('What each sector looks like'), unsafe_allow_html=True)
        rows = [{'Sector': g, 'Companies': f"{b.get('count', 0):,}",
                 'Median P/E': pg.f((b.get('pe') or {}).get('median'), 'x'),
                 'Median ROE': pg.f((b.get('roe') or {}).get('median'), 'pct'),
                 'Median op margin': pg.f((b.get('op_margin') or {}).get('median'), 'pct'),
                 'Median Altman Z': pg.f((b.get('altman_z') or {}).get('median')),
                 'Median Piotroski': pg.f((b.get('piotroski_f') or {}).get('median'), 'int')}
                for g, b in sorted(sector_stats.items())]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.markdown('<div class="an"><div class="smallnote">These medians come from the full '
                    'TradingView universe, not the screened subset. A median taken from '
                    'names that already passed a quality screen is a median of the winners, '
                    'and would make every company on this app look average.</div></div>',
                    unsafe_allow_html=True)

    st.divider()
    st.caption(f'Full screener with every filter: {screener_url}/')


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

    # keep a short history for the landing page. Session only, nothing stored anywhere.
    if tv_entry and tv_entry.get('ticker'):
        recent = [r for r in st.session_state.get('recent', [])
                  if r.get('ticker') != tv_entry['ticker']]
        recent.insert(0, {'ticker': tv_entry['ticker'], 'isin': tv_isin or isin or '',
                          'ccy': tv_entry.get('ccy') or ''})
        st.session_state['recent'] = recent[:8]

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
