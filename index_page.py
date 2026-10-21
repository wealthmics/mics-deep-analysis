"""
The index page of the deep analysis app.

An index is not a company, so this page asks different questions: what has it returned,
in its own currency and to a US dollar investor; how deep and how long were its falls;
how closely does it move with the S&P 500; what does the fund that tracks it hold, what does
it cost and what is it priced at. Same design system as the company page.

    compute(entry, index_hist, etf_hist, fund, bench_hist, spy_fund) -> ctx
    build(ctx) -> html
"""

import math

import pandas as pd

import page as pg
import risk as rk
from page import esc, f, minus, note, read

SECTOR_NAMES = {
    'realestate': 'Real estate', 'consumer_cyclical': 'Consumer cyclical',
    'basic_materials': 'Basic materials', 'consumer_defensive': 'Consumer defensive',
    'technology': 'Technology', 'communication_services': 'Communication services',
    'financial_services': 'Financial services', 'utilities': 'Utilities',
    'industrials': 'Industrials', 'energy': 'Energy', 'healthcare': 'Health care',
}


def _close(hist):
    if hist is None or not hasattr(hist, 'columns') or 'Close' not in hist or len(hist) < 30:
        return None
    return rk.dated(hist['Close'])


def expense_pct(info):
    """Yahoo reports the expense ratio either as a percent (0.09) or a fraction (0.0009)."""
    for k in ('netExpenseRatio', 'annualReportExpenseRatio'):
        v = info.get(k)
        if v is None:
            continue
        return v * 100 if v < 0.01 else v
    return None


def fund_summary(fund):
    fund = fund or {}
    info = fund.get('info') or {}
    th = fund.get('top_holdings')
    holdings = []
    if th is not None and hasattr(th, 'iterrows') and len(th):
        wcol = next((c for c in th.columns if 'percent' in str(c).lower()), None)
        ncol = next((c for c in th.columns if 'name' in str(c).lower()), None)
        for sym, r in th.iterrows():
            w = r[wcol] if wcol else None
            if w is not None and not pd.isna(w):
                w = float(w) * 100 if w <= 1 else float(w)
            holdings.append({'symbol': str(sym), 'name': str(r[ncol]) if ncol else str(sym),
                             'weight': w})
    sectors = []
    for k, v in (fund.get('sectors') or {}).items():
        if v is None or pd.isna(v) or v <= 0:
            continue
        sectors.append({'sector': SECTOR_NAMES.get(k, k.replace('_', ' ').capitalize()),
                        'weight': float(v) * 100 if v <= 1 else float(v)})
    sectors.sort(key=lambda x: -x['weight'])
    y = info.get('yield')
    return {
        'name': info.get('longName') or info.get('shortName'),
        'family': info.get('fundFamily'), 'category': info.get('category'),
        'ccy': info.get('currency'), 'aum': info.get('totalAssets'),
        'expense_pct': expense_pct(info),
        'yield_pct': (y * 100 if y is not None and y < 1 else y),
        'pe': info.get('trailingPE'), 'pb': info.get('priceToBook'),
        'inception': info.get('fundInceptionDate'),
        'holdings': holdings, 'top10_pct': (sum(h['weight'] or 0 for h in holdings[:10])
                                            if holdings else None),
        'sectors': sectors,
    }


def compute(entry, index_hist, etf_hist, fund, bench_hist, spy_fund=None):
    idx, etf, bench = _close(index_hist), _close(etf_hist), _close(bench_hist)
    primary = idx if idx is not None else etf
    ctx = {'entry': entry, 'idx': idx, 'etf': etf, 'bench': bench, 'primary': primary,
           'primary_is_index': idx is not None, 'fund': fund_summary(fund),
           'spy_pe': ((spy_fund or {}).get('info') or {}).get('trailingPE'),
           'is_bench': entry.get('index') == rk.BENCH_SYMBOL or entry.get('id') == 'spx'}
    if primary is None:
        return ctx
    ccy = entry.get('ccy') if idx is not None else (ctx['fund']['ccy'] or 'USD')
    ctx['ccy'] = ccy
    us = entry.get('region') == 'United States' or (idx is None and str(ccy).upper() == 'USD'
                                                    and entry.get('region') == 'United States')
    spans = [k for k, n in rk.SPANS.items() if n is None or len(primary) >= n * 0.6]
    windows = rk.all_windows(primary, bench, spans, us_listed=us)
    ma50, ma200 = primary.rolling(50).mean(), primary.rolling(200).mean()
    charts = []
    for lab in spans:
        n = rk.SPANS[lab]
        w = primary if n is None else primary.tail(n)
        w = rk.thin_series(w)
        charts.append((lab, w, ma50.reindex(w.index), ma200.reindex(w.index),
                       windows.get(lab) or {}))
    last = float(primary.iloc[-1])
    hi52, lo52 = float(primary.tail(252).max()), float(primary.tail(252).min())
    ctx.update({
        'spans': spans, 'windows': windows, 'charts': charts,
        'ret_idx': rk.trailing_returns(idx) if idx is not None else {},
        'ret_etf': rk.trailing_returns(etf) if etf is not None else {},
        'ret_bench': rk.trailing_returns(bench) if bench is not None else {},
        'dd_full': rk.drawdown(primary), 'last': last, 'hi52': hi52, 'lo52': lo52,
        'vs50': (last / float(ma50.iloc[-1]) - 1) * 100 if len(primary) >= 50 else None,
        'vs200': (last / float(ma200.iloc[-1]) - 1) * 100 if len(primary) >= 200 else None,
        'from_hi52': (last / hi52 - 1) * 100,
        'start': primary.index[0], 'end': primary.index[-1],
    })
    return ctx


# ---------------------------------------------------------------------- the reading -----
def reading(ctx):
    e, fd = ctx['entry'], ctx['fund']
    s, c, v = [], [], []
    w5 = (ctx.get('windows') or {}).get('5Y') or {}
    w1 = (ctx.get('windows') or {}).get('1Y') or {}
    if not ctx.get('is_bench'):
        rel5 = w5.get('relative_pts')
        if rel5 is not None:
            ccy = str(ctx.get('ccy') or '').upper()
            where = ('' if ccy in ('', 'USD') else
                     f' (measured in {ccy} against the index in US dollars, so currency is '
                     f'part of the gap)')
            (s if rel5 > 0 else c).append(
                f'Over five years it finished {abs(rel5):.0f} percentage points '
                f'{"ahead of" if rel5 > 0 else "behind"} the S&P 500{where}.')
    vs200 = ctx.get('vs200')
    if vs200 is not None:
        (s if vs200 > 0 else c).append(
            f'The level is {abs(vs200):.1f}% {"above" if vs200 > 0 else "below"} its 200 day '
            f'average, so the longer trend is {"up" if vs200 > 0 else "down"}.')
    dd = ctx.get('dd_full') or {}
    if dd.get('recovered') is None and (dd.get('now_below_high_pct') or 0) < -15 and \
            hasattr(dd.get('peak'), 'strftime'):
        v.append(f'It is still {abs(dd["now_below_high_pct"]):.0f}% below its '
                 f'{dd["peak"].strftime("%b %Y")} high. What would bring the earnings or the '
                 f'multiple back to that level.')
    b = (w5.get('bench') or {})
    if not ctx.get('is_bench') and b.get('corr') is not None:
        if b['corr'] < 0.5:
            s.append(f'Correlation with the S&P 500 of {b["corr"]:.2f} over five years: it has '
                     f'added genuine diversification to a US portfolio.')
        elif b['corr'] > 0.85:
            c.append(f'Correlation with the S&P 500 of {b["corr"]:.2f}: it adds little '
                     f'diversification to a US portfolio.')
    ri, re_ = ctx.get('ret_idx') or {}, ctx.get('ret_etf') or {}
    fccy = fd.get('ccy')
    if ri.get('1Y') is not None and re_.get('1Y') is not None and fccy and \
            str(fccy).upper() != str(e.get('ccy') or '').upper():
        gap = re_['1Y'] - ri['1Y']
        if abs(gap) >= 5:
            (s if gap > 0 else c).append(
                f'Over the last year a {fccy} investor in {e.get("etf")} made '
                f'{re_["1Y"]:.1f}% against {ri["1Y"]:.1f}% for the index in {e.get("ccy")}. '
                f'Most of the {abs(gap):.0f} point gap is the currency, '
                f'{"helping" if gap > 0 else "hurting"} the dollar investor.')
    if fd.get('pe') and ctx.get('spy_pe') and not ctx.get('is_bench'):
        ratio = fd['pe'] / ctx['spy_pe']
        if ratio < 0.75:
            s.append(f'The fund trades on {fd["pe"]:.1f} times trailing earnings against '
                     f'{ctx["spy_pe"]:.1f} for the S&P 500, a clear discount.')
            v.append('Why the market is cheaper: lower growth, sector mix (banks and energy '
                     'trade on low multiples) or country risk.')
        elif ratio > 1.15:
            c.append(f'The fund trades on {fd["pe"]:.1f} times trailing earnings, above the '
                     f'S&P 500 at {ctx["spy_pe"]:.1f}.')
    if fd.get('top10_pct') and fd['top10_pct'] > 45:
        c.append(f'The ten largest holdings make up {fd["top10_pct"]:.0f}% of the fund, so a '
                 f'few companies drive the result.')
        v.append('The outlook for the largest holdings, since they decide most of the return.')
    if fd.get('expense_pct') and fd['expense_pct'] > 0.5:
        c.append(f'The fund costs {fd["expense_pct"]:.2f}% a year, on the high side for an index fund.')
    if e.get('ccy') in ('ARS', 'TRY', 'EGP'):
        v.append(f'Local returns in {e["ccy"]} are swollen by inflation; judge it on the '
                 f'US dollar return of the fund.')
    v.append('Earnings revisions and the policy outlook for this market, which price data '
             'alone cannot show.')
    dedupe = lambda xs: list(dict.fromkeys(xs))[:4]
    return dedupe(s), dedupe(c), dedupe(v)


# ---------------------------------------------------------------------- HTML ------------
def _ret_cell(v):
    if v is None:
        return '<td class="val num">n/a</td>'
    cls = 'up' if v > 0 else 'down' if v < 0 else ''
    return f'<td class="val num {cls}">{minus(f(v, "pct"))}</td>'


def build(ctx):
    e, fd = ctx['entry'], ctx['fund']
    H = [pg.CSS, '<div class="an">']
    as_of = ctx['end'].strftime('%d %B %Y').lstrip('0') if ctx.get('end') is not None else ''
    H.append(f'<div class="printhead"><span>MICS International, internal research</span>'
             f'<span>Data as at {esc(as_of)}</span></div>')
    bits = [b for b in [e.get('region'), e.get('country'),
                        e.get('index') and f'Index {e["index"]}',
                        e.get('etf') and f'Fund {e["etf"]}'] if b]
    meta = '<span class="sep">/</span>'.join(esc(b) for b in bits)
    ytd = (ctx.get('ret_idx') or ctx.get('ret_etf') or {}).get('YTD')
    cls = 'up' if (ytd or 0) > 0 else 'down' if (ytd or 0) < 0 else ''
    lvl_lab = 'Index level' if ctx['primary_is_index'] else f'{e.get("etf")} price'
    H.append(
        f'<div class="mast"><div><div class="eyebrow">Index analysis, {esc(as_of)}</div>'
        f'<h1>{esc(e["name"])}</h1><div class="meta">{meta}</div></div>'
        f'<div class="quote"><div class="eyebrow"><a class="back" href="?view=indexes">'
        f'All indexes</a></div><div class="eyebrow" style="margin-top:6px">{esc(lvl_lab)}</div>'
        f'<div class="px num">{f(ctx["last"])}<span>{esc(ctx.get("ccy") or "")}</span></div>'
        f'<div class="chg {cls} num">{minus(f(ytd, "pct"))} year to date</div>'
        f'<div class="rng">{abs(ctx["from_hi52"]):.1f}% below its 52 week high</div></div></div>')
    H.append(f'<div class="card" style="margin-top:12px;margin-bottom:0"><h2>What it covers</h2>'
             f'<div class="body-text">{esc(e.get("about") or "")}</div></div>')

    # ---- strip
    def cell(k, v, n):
        return f'<div><div class="k">{k}</div><div class="v num">{v}</div><div class="n">{n}</div></div>'
    ri, re_ = ctx.get('ret_idx') or {}, ctx.get('ret_etf') or {}
    main = ri if ctx['primary_is_index'] else re_
    w1 = ctx['windows'].get('1Y') or {}
    w5 = ctx['windows'].get('5Y') or {}
    b5 = w5.get('bench') or {}
    one_note = (f'{e.get("ccy") or ""}, price only' if ctx['primary_is_index']
                else f'{fd.get("ccy") or ""} fund, with dividends')
    cells = [cell('One year', minus(f(main.get('1Y'), 'pct')), esc(one_note)),
             cell('Five years, a year', minus(f(main.get('5Y'), 'pct')), 'annualised'),
             cell('Volatility', f(w1.get('vol_pct'), 'pct'), 'one year, annualised'),
             cell('Below its high', minus(f((ctx.get('dd_full') or {}).get('now_below_high_pct'),
                                            'pct')), 'against the record high'),
             cell('Beta, five years', 'n/a' if b5.get('beta') is None else f'{b5["beta"]:.2f}',
                  'against the S&P 500'),
             cell('Fund cost', 'n/a' if fd.get('expense_pct') is None
                  else f'{fd["expense_pct"]:.2f}%', f'a year, {esc(e.get("etf") or "")}')]
    H.append(f'<div class="strip">{"".join(cells)}</div>')

    LEFT, RAIL = [], []
    # ---- level and risk
    risk_ctx = {'ccy': ctx.get('ccy'), 'bench_ok': ctx.get('bench') is not None,
                'noun': 'the index' if ctx['primary_is_index'] else 'the fund'}
    start_txt = ctx['start'].strftime('%B %Y')
    src = (f'Yahoo, {e["index"]}, price only' if ctx['primary_is_index']
           else f'Yahoo, {e.get("etf")}, adjusted close')
    current = '5Y' if '5Y' in ctx['spans'] else ctx['spans'][-1]
    ddf = ctx.get('dd_full') or {}
    LEFT.append(
        f'<div class="card"><span class="src y">{esc(src)}</span>'
        f'<h2>Level, drawdown and risk</h2>'
        f'<div class="sub">History from {esc(start_txt)}. Navy is the level, the lighter lines '
        f'its 50 and 200 day averages, and the lower panel how far it sat below its high at '
        f'each date. Beta and correlation are against the S&amp;P 500.'
        + (' This is the benchmark itself, so its beta is 1 by definition.'
           if ctx.get('is_bench') else '') + '</div>'
        + pg.span_panels(ctx['charts'], current, risk_ctx)
        + (read(esc(rk.drawdown_sentence(ddf, where='in the full record'))) if ddf else '')
        + '</div>')

    # ---- returns table
    rb = ctx.get('ret_bench') or {}
    has_idx, has_etf = bool(ri), bool(re_)
    heads = ['Period'] + (['Index, ' + str(e.get('ccy') or '') + ', price'] if has_idx else []) \
        + ([f'{e.get("etf")}, {fd.get("ccy") or ""}, with dividends'] if has_etf else []) \
        + ([] if ctx.get('is_bench') else ['S&amp;P 500, price'])
    rows = ''
    for lab, _ in rk.PERIODS:
        vals = ([ri.get(lab)] if has_idx else []) + ([re_.get(lab)] if has_etf else []) + \
            ([] if ctx.get('is_bench') else [rb.get(lab)])
        if all(x is None for x in vals):
            continue
        name = {'YTD': 'Year to date'}.get(lab, lab) + (' a year' if lab in ('3Y', '5Y', '10Y') else '')
        rows += f'<tr><td>{name}</td>' + ''.join(_ret_cell(x) for x in vals) + '</tr>'
    gap_note = ''
    if has_idx and has_etf and fd.get('ccy') and str(fd['ccy']).upper() != str(e.get('ccy')).upper():
        gap_note = (f'The index is in {e.get("ccy")} and excludes dividends; the fund is in '
                    f'{fd["ccy"]} and includes them. The difference between the two columns is '
                    f'mostly the currency, plus dividends, less the fund\'s costs.')
    elif has_idx and has_etf:
        gap_note = ('The index excludes dividends and the fund includes them, so the fund '
                    'column normally runs ahead by roughly the dividend yield, less costs.')
    LEFT.append(
        f'<div class="card"><span class="src y">Yahoo</span><h2>Returns over time</h2>'
        f'<div class="sub">Three years and longer are annualised.</div>'
        f'<table><thead><tr>{"".join(f"<th>{h}</th>" for h in heads)}</tr></thead>'
        f'<tbody>{rows}</tbody></table>' + (read(esc(gap_note)) if gap_note else '') + '</div>')

    # ---- holdings and sectors
    if fd['holdings'] or fd['sectors']:
        body = ''
        if fd['holdings']:
            top = max(h['weight'] or 0 for h in fd['holdings']) or 1
            body += ''.join(
                f'<div class="brow"><div class="bl">{esc(h["name"])}</div>'
                f'<div class="bt"><i style="width:{(h["weight"] or 0)/top*100:.0f}%"></i></div>'
                f'<div class="bv num">{f(h["weight"], "pct")}</div>'
                f'<div class="bp num">{esc(h["symbol"])}</div></div>' for h in fd['holdings'][:10])
        sec = ''
        if fd['sectors']:
            top = fd['sectors'][0]['weight'] or 1
            sec = ('<div style="margin-top:18px;padding-top:16px;border-top:1px solid #d8dee9">'
                   + ''.join(f'<div class="brow"><div class="bl">{esc(x["sector"])}</div>'
                             f'<div class="bt"><i style="width:{x["weight"]/top*100:.0f}%"></i></div>'
                             f'<div class="bv num">{f(x["weight"], "pct")}</div><div class="bp"></div></div>'
                             for x in fd['sectors']) + '</div>')
        conc = (f'The ten largest holdings are {fd["top10_pct"]:.0f}% of the fund.'
                if fd.get('top10_pct') else '')
        LEFT.append(f'<div class="card"><span class="src y">Yahoo, {esc(e.get("etf") or "")}</span>'
                    f'<h2>What the fund holds</h2><div class="sub">Largest holdings, then the '
                    f'split by sector.</div>{body}{sec}' + (read(esc(conc)) if conc else '')
                    + '</div>')

    # ---- rail: the fund
    kv = lambda k, v: f'<div class="kv"><span class="k">{k}</span><span class="v num">{v}</span></div>'
    if e.get('etf'):
        rows_f = kv('Fund', esc(fd.get('name') or e['etf']))
        rows_f += kv('Ticker', esc(e['etf']))
        if fd.get('family'):
            rows_f += kv('Manager', esc(fd['family']))
        rows_f += kv('Cost a year', 'n/a' if fd.get('expense_pct') is None else f'{fd["expense_pct"]:.2f}%')
        rows_f += kv('Assets', f'{f(fd.get("aum"), "money")} {esc(fd.get("ccy") or "")}')
        rows_f += kv('Distribution yield', f(fd.get('yield_pct'), 'pct'))
        alt = ', '.join(e.get('alt') or [])
        RAIL.append(f'<div class="card"><span class="src y">Yahoo</span><h2>The fund that tracks it</h2>'
                    f'{rows_f}' + (note(f'Other funds on the same or a close index: {esc(alt)}.')
                                   if alt else '') + '</div>')
    if fd.get('pe') or fd.get('pb'):
        rows_v = kv('P/E, trailing', f(fd.get('pe'), 'x')) + kv('Price / book', f(fd.get('pb'), 'x'))
        if ctx.get('spy_pe') and not ctx.get('is_bench'):
            rows_v += kv('S&amp;P 500, P/E', f(ctx['spy_pe'], 'x'))
        say = ''
        if fd.get('pe') and ctx.get('spy_pe') and not ctx.get('is_bench'):
            r = fd['pe'] / ctx['spy_pe']
            say = (f'At {r:.2f} times the S&amp;P 500\'s multiple, ' +
                   ('it is priced at a clear discount to US equities.' if r < 0.75 else
                    'it is priced close to US equities.' if r <= 1.15 else
                    'it is priced above US equities.'))
        RAIL.append(f'<div class="card"><span class="src y">Yahoo, {esc(e.get("etf") or "")}</span>'
                    f'<h2>Valuation</h2><div class="sub">Of the fund\'s holdings</div>{rows_v}'
                    + (note(say) if say else '') + '</div>')
    trend = ''
    for lab, val in (('Against the 50 day average', ctx.get('vs50')),
                     ('Against the 200 day average', ctx.get('vs200')),
                     ('From the 52 week high', ctx.get('from_hi52'))):
        if val is not None:
            c_ = 'up' if val > 0 else 'down'
            trend += f'<div class="kv"><span class="k">{lab}</span><span class="v num {c_}">{minus(f(val, "pct"))}</span></div>'
    if trend:
        v50, v200 = ctx.get('vs50'), ctx.get('vs200')
        say = ('Above both averages, so the trend is up.' if (v50 or 0) > 0 and (v200 or 0) > 0 else
               'Below both averages, so the trend is down.' if (v50 or 0) < 0 and (v200 or 0) < 0 else
               'Between its two averages, with no clear trend.')
        RAIL.append(f'<div class="card"><span class="src y">Yahoo</span><h2>Trend</h2>{trend}{note(say)}</div>')

    H.append('<div class="grid"><div>' + ''.join(LEFT) + '</div><div>' + ''.join(RAIL) + '</div></div>')

    s, c, v = reading(ctx)
    def col(cls_, title, items):
        lis = ''.join(f'<li>{esc(x)}</li>' for x in items) or '<li>Nothing material from these figures.</li>'
        return f'<div class="vcol {cls_}"><h3>{title}</h3><ul>{lis}</ul></div>'
    H.append('<div class="view"><span class="src">Drawn from the figures above</span>'
             '<h2>Where the numbers point</h2><div class="vcols">'
             + col('s', 'Supported by the data', s) + col('c', 'Cuts against it', c)
             + col('v', 'Verify before acting', v) +
             '</div><div class="disc"><b>For internal research.</b> Generated from the figures on '
             'this page. Not investment advice or a recommendation, and it takes no account of any '
             'person\'s objectives or circumstances.</div></div>')
    H.append('<div class="foot"><b>Sources.</b> Yahoo, live: the index level (price only, local '
             'currency), the tracking fund (adjusted for dividends, in its own currency), its '
             'holdings, sector split, costs and valuation, and the S&amp;P 500 for beta, '
             'correlation and relative return. Index levels and fund prices can differ in '
             'currency, in dividends and in the exact index tracked, so the two are shown side '
             'by side rather than blended.</div>')
    H.append('</div>')
    return ''.join(H)
