"""
Excel and PowerPoint exports of one company's deep analysis.

Both are built from the same context the page is built from, so the three can never
disagree. Tables carry the content; the only drawn elements are a thin gold rule on the
cover and one native line chart of the price against the S&P 500.

    build_xlsx(ctx) -> bytes
    build_pptx(ctx) -> bytes
"""

import datetime
import html
import io
import re

import pandas as pd

import page as pg
import risk as rk

NAVY, NAVY2, GOLD, BAND, LINE, INK, WHITE, PALE = (
    '1F3864', '2E4A7D', 'BF8F00', 'F2F5FA', 'D8DEE9', '1A1A1A', 'FFFFFF', 'E9EEF6')
FINANCIAL = ('Financials', 'Real Estate')


# ====================================================================== shared content ==
def plain(text):
    """Page commentary carries <b> tags and entities; exports want clean text."""
    return html.unescape(re.sub(r'<[^>]+>', '', str(text or ''))).replace('\u2212', '-').strip()


def fnum(v, kind='num'):
    out = pg.f(v, kind)
    return '-' if out == 'n/a' else out


def _date(ts, fmt='%d %b %Y'):
    return ts.strftime(fmt).lstrip('0') if hasattr(ts, 'strftime') else ''


def snapshot(ctx):
    tv, info = ctx['tv'], ctx['info']
    ccy = tv.get('ccy') or info.get('currency') or ''
    mcap = tv.get('mcap')
    rows = [
        ('Last price', f'{fnum(tv.get("price") or info.get("currentPrice"))} {ccy}'.strip()),
        ('Market cap', (f'{fnum(mcap, "money")} {tv.get("mcap_ccy") or ""}'.strip()
                        if mcap else fnum(info.get('marketCap'), 'money'))),
        ('P/E, trailing', fnum(tv.get('pe'), 'x') if (tv.get('pe') or 0) > 0 else
         ('loss making' if tv.get('pe') is not None else '-')),
        ('P/E, forward', fnum(tv.get('fpe'), 'x')),
        ('Return on equity', fnum(tv.get('roe'), 'pct')),
        ('Operating margin', fnum(tv.get('op_margin'), 'pct')),
        ('Net margin', fnum(tv.get('net_margin'), 'pct')),
        ('Debt to equity', fnum(tv.get('debt_equity'), 'x')),
        ('Year to date', fnum(tv.get('perf_ytd'), 'pct')),
        ('One year', fnum(tv.get('perf_1y'), 'pct')),
    ]
    dy = info.get('dividendYield')
    if dy is not None:
        rows.append(('Dividend yield', fnum(dy * 100 if dy < 1 else dy, 'pct')))
    return rows


def scores(ctx):
    """The forensic strip, as rows of (measure, value, reading, what it means)."""
    tv, fo, gics = ctx['tv'], ctx.get('forensics') or {}, ctx['tv'].get('gics')
    out = []
    z = tv.get('altman_z')
    if gics in FINANCIAL:
        out.append(('Altman Z', '-', 'Not applicable', 'The model does not fit a bank, insurer '
                    'or REIT balance sheet.'))
    elif z is not None:
        out.append(('Altman Z', fnum(z), 'Distress' if z < 1.8 else 'Grey zone' if z < 3
                    else 'Safe', 'Bankruptcy risk model. Below 1.8 is distress, above 3 safe.'))
    pf = tv.get('piotroski_f')
    if pf is not None:
        out.append(('Piotroski F', f'{pf:.0f} / 9', 'Strong' if pf >= 7 else 'Middling'
                    if pf >= 4 else 'Weak', 'Nine tests of improving fundamentals.'))
    bm = (fo.get('beneish') or {}).get('score')
    if bm is not None:
        out.append(('Beneish M', fnum(bm), 'Flagged' if bm > -1.78 else 'Clean',
                    'Earnings manipulation screen. Above -1.78 is flagged.'))
    oh = fo.get('ohlson') or {}
    if oh.get('score') is not None:
        p = oh['score'] * 100 if oh.get('as_pct') else oh['score']
        out.append(('Ohlson distress probability', fnum(p, 'pct'),
                    'High' if p > 10 else 'Watch' if p > 5 else 'Low',
                    'Probability of financial distress within two years.'))
    sl = (fo.get('sloan') or {}).get('score')
    if sl is not None:
        pct = sl * 100
        out.append(('Sloan accruals', fnum(pct, 'pct'), 'Profit ahead of cash' if pct > 5 else
                    'Cash ahead of profit' if pct < -5 else 'Neutral',
                    'Share of profit not backed by cash.'))
    usable = [r['cfo_to_ni'] for r in (ctx.get('qoe_rows') or []) if r.get('cfo_to_ni') is not None]
    if usable and gics not in FINANCIAL:
        avg = sum(usable) / len(usable)
        out.append(('Cash conversion', fnum(avg, 'x'), 'Backed' if avg >= 1.1 else 'In line'
                    if avg >= 0.9 else 'Thin', f'Operating cash flow over profit, '
                    f'{len(usable)} year average.'))
    return out


def peer_rows(ctx):
    tv, stats, po = ctx['tv'], ctx.get('stats') or {}, ctx.get('percentile_of')
    rows = []
    for key, label in pg.LABELS.items():
        v = tv.get(key)
        block = stats.get(key) or {}
        if v is None:
            continue
        kind = 'pct' if key in pg.PERCENT_METRICS else 'x' if key in (
            'pe', 'fpe', 'current_ratio', 'interest_cover', 'ebitda_cover', 'debt_equity') else 'num'
        if key in ('pe', 'fpe') and v <= 0:
            band = 'loss making'
        else:
            peer = po(v, stats, key) if po else None
            band = peer['band'] if peer else '-'
        rows.append((label, fnum(v, kind), fnum(block.get('p25'), kind),
                     fnum(block.get('median'), kind), fnum(block.get('p75'), kind), band))
    return rows


def window_rows(ctx):
    rows = []
    for lab in ctx.get('spans') or []:
        st = (ctx['risk'].get('windows') or {}).get(lab) or {}
        if not st:
            continue
        b, dd = st.get('bench') or {}, st.get('dd') or {}
        rows.append({
            'Window': lab, 'From': _date(st.get('start')), 'To': _date(st.get('end')),
            'Change': st.get('change_pct'), 'S&P 500': b.get('bench_change_pct'),
            'Relative (pts)': st.get('relative_pts'), 'Worst fall': dd.get('worst_pct'),
            'High before the fall': _date(dd.get('peak')), 'Low': _date(dd.get('trough')),
            'Back at the high': (_date(dd.get('recovered')) if dd.get('recovered') is not None
                                 else ('not yet' if dd else '')),
            'Volatility': st.get('vol_pct'), 'Beta': b.get('beta'), 'Correlation': b.get('corr'),
            'Returns used': f'{b.get("freq", "")}, {b.get("obs", "")}' if b else '',
        })
    return rows


def reading(ctx):
    tv = ctx['tv']
    s, c, v = pg.assessment(tv, ctx.get('stats') or {}, ctx.get('forensics'), ctx['risk'],
                            ctx.get('dupont'), ctx.get('qoe_rows'), ctx.get('capital'),
                            ctx.get('per_share'), ctx['info'])
    return [plain(x) for x in s], [plain(x) for x in c], [plain(x) for x in v]


def valuation_rows(ctx):
    info = ctx['info']
    rows = []
    for k, lbl in (('enterpriseToEbitda', 'EV / EBITDA'), ('priceToBook', 'Price / book'),
                   ('priceToSalesTrailing12Months', 'Price / sales'),
                   ('enterpriseToRevenue', 'EV / revenue'), ('trailingPegRatio', 'PEG')):
        if info.get(k) is not None:
            rows.append((lbl, fnum(info[k], 'x'), 'Yahoo'))
    for k, lbl in (('heldPercentInstitutions', 'Held by institutions'),
                   ('heldPercentInsiders', 'Held by insiders'),
                   ('shortPercentOfFloat', 'Short interest, % of float')):
        if info.get(k) is not None:
            rows.append((lbl, fnum(info[k] * 100, 'pct'), 'Yahoo'))
    tv = ctx['tv']
    if tv.get('marquee'):
        rows.append(('Superinvestors holding', fnum(tv.get('marquee_investors'), 'int'),
                     f'Dataroma, {tv.get("_marquee_as_of", "")}'))
    if info.get('targetMeanPrice'):
        ypx = pg._yahoo_price(info, tv)
        up = (info['targetMeanPrice'] / ypx - 1) * 100 if ypx else None
        rows.append(('Analyst mean target', f'{fnum(info["targetMeanPrice"])} '
                     f'{info.get("currency") or ""}'.strip(), 'Yahoo'))
        rows.append(('Implied change to target', fnum(up, 'pct'), 'Yahoo'))
        if info.get('numberOfAnalystOpinions'):
            rows.append(('Analysts covering', fnum(info['numberOfAnalystOpinions'], 'int'), 'Yahoo'))
    return rows


def rebased(ctx, years=5, freq='W-FRI'):
    """Weekly closes for the stock and the S&P 500, both rebased to 100."""
    hist = ctx.get('hist')
    if hist is None or 'Close' not in hist:
        return None
    a = rk.dated(hist['Close'])
    if a is None or len(a) < 30:
        return None
    a = a.loc[a.index[-1] - pd.DateOffset(years=years):]
    a = a.resample(freq).last().dropna()
    out = pd.DataFrame({'stock': a / a.iloc[0] * 100})
    b = rk.dated(ctx.get('bench')) if ctx.get('bench') is not None else None
    if b is not None:
        b = b.loc[a.index[0] - pd.Timedelta(days=40):a.index[-1]].resample(freq).last()
        b = b.reindex(out.index).ffill()
        if b.notna().sum() > 10:
            first = b.dropna().iloc[0]
            out['bench'] = b / first * 100
    return out.dropna(how='all')


def headline(ctx):
    good, bad = pg.peer_summary(ctx['tv'], ctx.get('stats') or {}, detail=True)
    total = len(good) + len(bad)
    if not total:
        return 'Company snapshot'
    if not bad:
        return f'Ahead of the sector median on all {total} measures compared'
    if not good:
        return f'Behind the sector median on all {total} measures compared'
    if len(good) >= len(bad):
        return f'Ahead of the sector median on {len(good)} of {total} measures compared'
    return f'Behind the sector median on {len(bad)} of {total} measures compared'


def meta_line(ctx):
    tv, info = ctx['tv'], ctx['info']
    bits = [tv.get('ticker'), tv.get('gics'), info.get('industry') or tv.get('industry'),
            tv.get('country'), ctx.get('isin')]
    return '  |  '.join(str(b) for b in bits if b)


# ====================================================================== EXCEL ==========
def build_xlsx(ctx):
    from openpyxl import Workbook
    from openpyxl.chart import LineChart, Reference
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    tv, info = ctx['tv'], ctx['info']
    name = tv.get('name') or info.get('longName') or tv.get('ticker') or 'Company'
    as_of = tv.get('_as_of') or ''

    def font(**k):
        base = dict(name='Arial', size=10, color=INK)
        base.update(k)
        return Font(**base)
    fill = lambda c: PatternFill('solid', fgColor=c)
    hair = Side(style='thin', color=LINE)
    gold = Side(style='medium', color=GOLD)

    wb = Workbook()

    def sheet(title, first=False, widths=()):
        ws = wb.active if first else wb.create_sheet()
        ws.title = title
        ws.sheet_view.showGridLines = False
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.page_setup.orientation = 'landscape'
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.oddFooter.left.text = 'MICS International, internal research'
        ws.oddFooter.right.text = 'Page &P of &N'
        return ws

    def title(ws, text, sub):
        ws['A1'] = text
        ws['A1'].font = font(size=18, bold=True, color=NAVY)
        ws['A2'] = sub
        ws['A2'].font = font(size=10, color=NAVY)
        return 4

    def heading(ws, r, text):
        ws.cell(r, 1, text).font = font(size=12, bold=True, color=NAVY)
        return r + 1

    def table(ws, r, head, rows, aligns=None, wrap_cols=(), num_fmt=None):
        aligns = aligns or (['left'] + ['right'] * (len(head) - 1))
        for j, h in enumerate(head, 1):
            c = ws.cell(r, j, h)
            c.font = font(bold=True, size=9, color=WHITE)
            c.fill = fill(NAVY)
            c.alignment = Alignment(horizontal=aligns[j - 1], vertical='center', wrap_text=True)
            c.border = Border(bottom=gold)
        ws.row_dimensions[r].height = 28
        r += 1
        for i, row in enumerate(rows):
            for j, val in enumerate(row, 1):
                c = ws.cell(r, j, val)
                c.font = font(bold=(j == 1), color=NAVY if j == 1 else INK)
                c.alignment = Alignment(horizontal=aligns[j - 1], vertical='top',
                                        wrap_text=(j - 1) in wrap_cols,
                                        indent=1 if (j > 1 and aligns[j - 1] == 'left') else 0)
                c.border = Border(bottom=hair)
                if num_fmt and num_fmt.get(j - 1) and isinstance(val, (int, float)):
                    c.number_format = num_fmt[j - 1]
                if i % 2:
                    c.fill = fill(BAND)
            r += 1
        return r + 1

    # ---- Overview
    ws = sheet('Overview', first=True, widths=(30, 22, 18, 52))
    r = title(ws, name, f'{meta_line(ctx)}   |   TradingView data as at {as_of}')
    ws.cell(r, 1, headline(ctx)).font = font(size=12, bold=True, color=GOLD)
    r += 2
    r = heading(ws, r, 'Snapshot')
    r = table(ws, r, ['Measure', 'Value'], snapshot(ctx))
    sc = scores(ctx)
    if sc:
        r = heading(ws, r, 'Quality and forensic scores')
        r = table(ws, r, ['Score', 'Value', 'Reading', 'What it measures'], sc,
                  aligns=['left', 'right', 'left', 'left'], wrap_cols=(3,))
    s, c, v = reading(ctx)
    r = heading(ws, r, 'Where the numbers point')
    if ctx.get('lede'):
        ws.cell(r, 1, ctx['lede']).font = font(italic=True)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
        ws.cell(r, 1).alignment = Alignment(wrap_text=True, vertical='top')
        ws.row_dimensions[r].height = 15 * max(2, len(ctx['lede']) // 110 + 1)
        r += 2
    rows = [('Supported by the data', x) for x in s] + \
           [('Cuts against it', x) for x in c] + [('Verify before acting', x) for x in v]
    for i, (k, t) in enumerate(rows):
        ws.cell(r, 1, k).font = font(bold=True, color=NAVY)
        ws.cell(r, 2, t).font = font()
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
        ws.cell(r, 2).alignment = Alignment(wrap_text=True, vertical='top')
        ws.cell(r, 1).alignment = Alignment(vertical='top')
        ws.row_dimensions[r].height = 15 * max(1, len(t) // 95 + 1)
        for j in range(1, 5):
            ws.cell(r, j).border = Border(bottom=hair)
            if i % 2:
                ws.cell(r, j).fill = fill(BAND)
        r += 1

    # ---- Sector comparison
    ws = sheet('Against the sector', widths=(24, 14, 14, 14, 14, 24))
    r = title(ws, f'Against the {tv.get("gics") or "sector"} median',
              'Medians and quartiles across every company in the sector in the TradingView '
              'universe, not only those that passed a screen.')
    r = table(ws, r, ['Ratio', 'Company', 'Lower quartile', 'Median', 'Upper quartile',
                      'Position in sector'], peer_rows(ctx),
              aligns=['left', 'right', 'right', 'right', 'right', 'left'])
    ws.cell(r, 1, plain(pg._sector_reading(tv, ctx.get('stats') or {}))).font = font(color=NAVY)
    ws.merge_cells(start_row=r, start_column=1, end_row=r + 1, end_column=6)
    ws.cell(r, 1).alignment = Alignment(wrap_text=True, vertical='top')

    # ---- Price and risk
    wr = window_rows(ctx)
    ws = sheet('Price and risk', widths=(9, 12, 12, 10, 10, 11, 10, 14, 13, 14, 10, 8, 11, 13))
    r = title(ws, 'Price, drawdown and risk against the S&P 500',
              'Adjusted daily closes from Yahoo. Beta and correlation use weekly returns for '
              'windows of a year or more and for every non-US listing, daily returns otherwise.')
    if wr:
        head = list(wr[0].keys())
        fm = {3: '0.0"%";-0.0"%"', 4: '0.0"%";-0.0"%"', 5: '+0.0;-0.0', 6: '0.0"%";-0.0"%"',
              10: '0.0"%"', 11: '0.00', 12: '0.00'}
        r = table(ws, r, head, [list(x.values()) for x in wr],
                  aligns=['left', 'left', 'left'] + ['right'] * 4 + ['left'] * 3 + ['right'] * 3
                  + ['left'], num_fmt=fm)
    ddf = ctx['risk'].get('dd_full') or {}
    if ddf:
        r = heading(ws, r, 'Deepest fall in the full record')
        ws.cell(r, 1, plain(rk.drawdown_sentence(ddf, where='in the full record'))).font = font()
        ws.merge_cells(start_row=r, start_column=1, end_row=r + 1, end_column=14)
        ws.cell(r, 1).alignment = Alignment(wrap_text=True, vertical='top')
        r += 3
    chart_anchor = r

    # ---- Price history, feeding the chart
    rb = rebased(ctx)
    if rb is not None and len(rb) > 10:
        hs = sheet('Price history', widths=(14, 16, 16))
        hs['A1'] = 'Weekly close, rebased to 100 five years ago'
        hs['A1'].font = font(size=12, bold=True, color=NAVY)
        heads = ['Week ending', tv.get('ticker') or 'Stock'] + (['S&P 500'] if 'bench' in rb else [])
        for j, h in enumerate(heads, 1):
            c = hs.cell(3, j, h)
            c.font = font(bold=True, color=WHITE, size=9)
            c.fill = fill(NAVY)
        for i, (d, row) in enumerate(rb.iterrows(), 4):
            hs.cell(i, 1, d.date()).number_format = 'dd mmm yyyy'
            hs.cell(i, 2, round(float(row['stock']), 2) if pd.notna(row['stock']) else None)
            if 'bench' in rb:
                hs.cell(i, 3, round(float(row['bench']), 2) if pd.notna(row['bench']) else None)
        last = 3 + len(rb)
        ch = LineChart()
        ch.title = f'{tv.get("ticker") or "Stock"} against the S&P 500, rebased to 100'
        ch.height, ch.width = 8.5, 24
        ch.y_axis.title = 'Rebased to 100'
        ch.y_axis.majorGridlines = None
        data = Reference(hs, min_col=2, max_col=2 + ('bench' in rb), min_row=3, max_row=last)
        ch.add_data(data, titles_from_data=True)
        ch.set_categories(Reference(hs, min_col=1, min_row=4, max_row=last))
        ch.x_axis.number_format = 'mmm yy'
        ch.series[0].graphicalProperties.line.solidFill = NAVY
        ch.series[0].graphicalProperties.line.width = 22000
        ch.series[0].smooth = False
        if len(ch.series) > 1:
            ch.series[1].graphicalProperties.line.solidFill = GOLD
            ch.series[1].graphicalProperties.line.width = 15000
            ch.series[1].smooth = False
        wb['Price and risk'].add_chart(ch, f'A{chart_anchor}')

    # ---- Financials
    ws = sheet('Financials', widths=(26, 18, 18, 18, 14))
    r = title(ws, 'Returns, cash and growth', 'Annual statements from Yahoo, oldest first.')
    if ctx.get('dupont'):
        r = heading(ws, r, 'What drives the return on equity (DuPont)')
        r = table(ws, r, ['Year', 'Net margin', 'Asset turnover', 'Equity multiplier', 'ROE'],
                  [(d['period'], d['net_margin_pct'] / 100, d['asset_turnover'],
                    d['equity_multiplier'], d['roe_pct'] / 100) for d in ctx['dupont']],
                  num_fmt={1: '0.0%', 2: '0.00', 3: '0.00', 4: '0.0%'})
    if ctx.get('qoe_rows'):
        r = heading(ws, r, 'Does the profit arrive as cash')
        r = table(ws, r, ['Year', 'Net income', 'Operating cash flow', 'Cash / profit'],
                  [(q['period'], q['net_income'], q['cfo'], q['cfo_to_ni'])
                   for q in ctx['qoe_rows']],
                  num_fmt={1: '#,##0,,"m";-#,##0,,"m"', 2: '#,##0,,"m";-#,##0,,"m"', 3: '0.00"x"'})
        if ctx.get('qoe_verdict'):
            ws.cell(r - 1, 1, plain(ctx['qoe_verdict'])).font = font(color=NAVY)
            ws.merge_cells(start_row=r - 1, start_column=1, end_row=r, end_column=5)
            ws.cell(r - 1, 1).alignment = Alignment(wrap_text=True, vertical='top')
            r += 2
    cap = ctx.get('capital') or {}
    if cap.get('uses'):
        r = heading(ws, r, f'Where the operating cash went, {cap.get("period_from")} to '
                           f'{cap.get("period_to")}')
        r = table(ws, r, ['Use', 'Amount', 'Share of operating cash flow'],
                  [(u['use'], u['amount'], (u['pct_of_cfo'] or 0) / 100) for u in cap['uses']],
                  num_fmt={1: '#,##0,,"m"', 2: '0.0%'})
    ps = ctx.get('per_share') or {}
    if ps.get('revenue_cagr_pct') is not None:
        r = heading(ws, r, f'Growth a year, {ps.get("from")} to {ps.get("to")}')
        rows = [('Revenue', ps.get('revenue_cagr_pct'), ps.get('revenue_per_share_cagr_pct')),
                ('Net income', ps.get('net_income_cagr_pct'), ps.get('eps_cagr_pct')),
                ('Share count', ps.get('share_count_cagr_pct'), None)]
        r = table(ws, r, ['Line', 'Total', 'Per share'],
                  [(a, None if b is None else b / 100, None if c is None else c / 100)
                   for a, b, c in rows], num_fmt={1: '0.0%', 2: '0.0%'})

    # ---- Valuation and ownership
    vr = valuation_rows(ctx)
    if vr:
        ws = sheet('Valuation and ownership', widths=(30, 22, 26))
        r = title(ws, 'Valuation, ownership and the analyst view', '')
        table(ws, r, ['Measure', 'Value', 'Source'], vr, aligns=['left', 'right', 'left'])

    # ---- Notes
    ws = sheet('Notes', widths=(24, 100))
    r = title(ws, 'Notes and sources', f'Prepared {datetime.date.today():%d %B %Y}')
    notes = [
        ('TradingView', f'Ratios, scores and returns from the TradingView screener export as at '
                        f'{as_of}, so they agree with the screen.'),
        ('Yahoo', 'Business description, statements, price history, valuation multiples, '
                  'ownership and analyst targets, fetched live.'),
        ('S&P 500', 'Benchmark for beta, correlation and relative performance. Price index in '
                    'US dollars; for a listing in another currency, currency moves are part of '
                    'the comparison.'),
        ('Beta', 'Covariance of the stock with the index divided by the variance of the index, '
                 'on weekly returns for a year or more and for non-US listings, daily otherwise. '
                 'A low correlation means the beta explains little.'),
        ('Use', 'For internal research. Not investment advice or a recommendation, and it takes '
                'no account of any person\'s objectives or circumstances.'),
    ]
    table(ws, r, ['Item', 'Note'], notes, aligns=['left', 'left'], wrap_cols=(1,))

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ====================================================================== POWERPOINT =====
def build_pptx(ctx):
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Emu, Inches, Pt

    tv, info = ctx['tv'], ctx['info']
    name = tv.get('name') or info.get('longName') or tv.get('ticker') or 'Company'
    as_of = tv.get('_as_of') or ''
    HEAD, BODY = 'Georgia', 'Calibri'
    rgb = lambda h: RGBColor.from_string(h)

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    X0, CW = 0.6, 12.133
    footer = f'MICS International   |   {name}   |   Data as at {as_of}'
    count = {'n': 0}

    def text(slide, x, y, w, h, t, size=12, bold=False, color=INK, face=BODY, align=None,
             anchor=None, italic=False):
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        if anchor:
            tf.vertical_anchor = anchor
        lines = t if isinstance(t, list) else [t]
        for i, ln in enumerate(lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            if isinstance(ln, tuple):
                ln, o = ln
            else:
                o = {}
            r = p.add_run()
            r.text = ln
            r.font.size = Pt(o.get('size', size))
            r.font.bold = o.get('bold', bold)
            r.font.italic = italic
            r.font.name = o.get('face', face)
            r.font.color.rgb = rgb(o.get('color', color))
            if align:
                p.alignment = align
            if o.get('space'):
                p.space_before = Pt(o['space'])
        return tb

    def content(title_text, sub=None):
        count['n'] += 1
        s = prs.slides.add_slide(blank)
        text(s, X0, 0.38, CW, 0.75, title_text, size=24, color=NAVY, face=HEAD,
             anchor=MSO_ANCHOR.BOTTOM)
        ln = s.shapes.add_connector(1, Inches(X0), Inches(1.22), Inches(X0 + CW), Inches(1.22))
        ln.line.color.rgb = rgb(LINE)
        ln.line.width = Pt(0.75)
        if sub:
            text(s, X0, 1.3, CW, 0.3, sub, size=11, color=NAVY)
        text(s, X0, 7.0, 9, 0.3, footer, size=9, color=NAVY)
        text(s, 12.1, 7.0, 0.63, 0.3, str(count['n'] + 1), size=9, color=NAVY,
             align=PP_ALIGN.RIGHT)
        return s

    def table(slide, x, y, colw, rows, head=True, size=10.5, rowh=0.32, aligns=None,
              first_bold=True):
        nr, nc = len(rows), len(rows[0])
        shp = slide.shapes.add_table(nr, nc, Inches(x), Inches(y), Inches(sum(colw)),
                                     Inches(rowh * nr))
        tbl = shp.table
        # plain styling: no banded style from the default theme
        tblPr = shp._element.graphic.graphicData.tbl.tblPr
        tblPr.set('bandRow', '0')
        tblPr.set('firstRow', '0')
        style_id = tblPr.find('{http://schemas.openxmlformats.org/drawingml/2006/main}tableStyleId')
        if style_id is not None:
            style_id.text = '{5940675A-B579-460E-94D1-54222C63F5DA}'   # "No Style, Table Grid"
        for j, w in enumerate(colw):
            tbl.columns[j].width = Inches(w)
        aligns = aligns or (['l'] + ['r'] * (nc - 1))
        amap = {'l': PP_ALIGN.LEFT, 'r': PP_ALIGN.RIGHT, 'c': PP_ALIGN.CENTER}
        for i in range(nr):
            tbl.rows[i].height = Inches(rowh)
            for j in range(nc):
                cell = tbl.cell(i, j)
                val = rows[i][j]
                cell.margin_left = cell.margin_right = Inches(0.08)
                cell.margin_top = cell.margin_bottom = Inches(0.03)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                tf = cell.text_frame
                tf.word_wrap = True
                p = tf.paragraphs[0]
                p.alignment = amap[aligns[j]]
                r = p.add_run()
                r.text = '' if val is None else str(val)
                r.font.name = BODY
                r.font.size = Pt(size)
                is_head = head and i == 0
                r.font.bold = is_head or (first_bold and j == 0)
                r.font.color.rgb = rgb(WHITE if is_head else (NAVY if j == 0 and first_bold
                                                               else INK))
                cell.fill.solid()
                cell.fill.fore_color.rgb = rgb(NAVY if is_head else
                                               (BAND if (i - (1 if head else 0)) % 2 else WHITE))
        return shp

    # 1. cover
    s = prs.slides.add_slide(blank)
    bg = s.background.fill
    bg.solid()
    bg.fore_color.rgb = rgb(NAVY)
    text(s, X0, 1.6, 11.8, 1.8, name, size=40, color=WHITE, face=HEAD, anchor=MSO_ANCHOR.BOTTOM)
    rule = s.shapes.add_connector(1, Inches(X0), Inches(3.75), Inches(X0 + 1.4), Inches(3.75))
    rule.line.color.rgb = rgb(GOLD)
    rule.line.width = Pt(2)
    text(s, X0, 4.0, 11.8, 1.6, [
        (meta_line(ctx), {'color': WHITE, 'size': 16}),
        (headline(ctx), {'color': 'C9D3E3', 'size': 14, 'space': 6}),
        (f'Equity analysis, data as at {as_of}   |   Prepared by MICS International',
         {'color': 'C9D3E3', 'size': 12, 'space': 6}),
    ])

    # 2. at a glance
    hl = headline(ctx)
    s = content(f'{name} at a glance',
                hl + '.' if hl != 'Company snapshot' else None)
    snap = [['Measure', 'Value']] + [list(x) for x in snapshot(ctx)]
    table(s, X0, 1.75, [2.6, 2.0], snap, size=11, rowh=0.36)
    sc = scores(ctx)
    if sc:
        rows = [['Quality and forensic scores', 'Value', 'Reading']] + [[a, b, c] for a, b, c, _ in sc]
        table(s, 5.6, 1.75, [3.1, 1.5, 2.53], rows, size=11, rowh=0.36,
              aligns=['l', 'r', 'l'])
        text(s, 5.6, 1.75 + 0.36 * len(rows) + 0.2, 7.13, 1.0,
             'Altman and Piotroski from TradingView; Beneish, Ohlson, Sloan and cash '
             'conversion computed from Yahoo statements.', size=10, color=NAVY)

    # 3. against the sector
    pr = peer_rows(ctx)
    if pr:
        s = content(f'Against the {tv.get("gics") or "sector"} median',
                    plain(pg._sector_reading(tv, ctx.get('stats') or {})))
        rows = [['Ratio', 'Company', 'Lower quartile', 'Median', 'Upper quartile',
                 'Position in sector']] + [list(x) for x in pr]
        rh = min(0.34, (6.8 - 1.75) / len(rows))
        table(s, X0, 1.75, [2.8, 1.6, 1.7, 1.6, 1.7, 2.73], rows,
              size=10.5 if rh >= 0.3 else 9.5, rowh=rh, aligns=['l', 'r', 'r', 'r', 'r', 'l'])

    # 4. price against the S&P 500, month end points so the date axis stays readable
    rb = rebased(ctx, freq='ME')
    wr = window_rows(ctx)
    if rb is not None and len(rb) > 10:
        yrs = max(1, round((rb.index[-1] - rb.index[0]).days / 365.25))
        s = content(f'Price against the S&P 500 over {yrs} year{"s" if yrs > 1 else ""}',
                    'Month end closes, both rebased to 100 at the start')
        cd = CategoryChartData()
        cd.categories = [d.date() for d in rb.index]
        cd.add_series(tv.get('ticker') or 'Stock', [None if pd.isna(x) else round(float(x), 2)
                                                    for x in rb['stock']])
        if 'bench' in rb:
            cd.add_series('S&P 500', [None if pd.isna(x) else round(float(x), 2)
                                      for x in rb['bench']])
        gf = s.shapes.add_chart(XL_CHART_TYPE.LINE, Inches(X0), Inches(1.7), Inches(8.0),
                                Inches(4.9), cd)
        ch = gf.chart
        ch.has_legend = True
        ch.legend.position = XL_LEGEND_POSITION.TOP
        ch.legend.include_in_layout = False
        ch.legend.font.size = Pt(10)
        ch.legend.font.name = BODY
        for i, ser in enumerate(ch.series):
            ser.smooth = False
            ser.format.line.color.rgb = rgb(NAVY if i == 0 else GOLD)
            ser.format.line.width = Pt(2 if i == 0 else 1.5)
        ca, va = ch.category_axis, ch.value_axis
        # one date label every couple of months rather than every week
        from pptx.oxml.ns import qn
        skip = str(max(1, len(rb) // 8))
        cax = ca._element
        anchor = cax.find(qn('c:noMultiLvlLbl'))       # schema order: skips sit before it
        for tag in ('c:tickLblSkip', 'c:tickMarkSkip'):
            el = cax.find(qn(tag))
            if el is None:
                el = cax.makeelement(qn(tag), {})
                if anchor is not None:
                    anchor.addprevious(el)
                else:
                    cax.append(el)
            el.set('val', skip)
        ca.tick_labels.font.size = Pt(9)
        ca.tick_labels.number_format = 'mmm yy'
        ca.tick_labels.number_format_is_linked = False
        va.tick_labels.font.size = Pt(9)
        va.has_major_gridlines = True
        va.major_gridlines.format.line.color.rgb = rgb(LINE)
        ca.format.line.color.rgb = rgb(LINE)
        va.format.line.color.rgb = rgb(LINE)
        # the figures beside the chart, for the same window when we have it
        key = '5Y' if any(w['Window'] == '5Y' for w in wr) else (wr[-1]['Window'] if wr else None)
        w = next((x for x in wr if x['Window'] == key), None)
        if w:
            side = [[f'Over {rk.SPAN_WORDS.get(key, key)}', '']] + [
                ['Stock', fnum(w['Change'], 'pct')], ['S&P 500', fnum(w['S&P 500'], 'pct')],
                ['Difference', '-' if w['Relative (pts)'] is None
                 else f'{w["Relative (pts)"]:+.1f} pts'],
                ['Worst fall', fnum(w['Worst fall'], 'pct')],
                ['Volatility', fnum(w['Volatility'], 'pct')],
                ['Beta', fnum(w['Beta'])], ['Correlation', fnum(w['Correlation'])]]
            table(s, 9.0, 1.75, [2.2, 1.53], side, size=11, rowh=0.38)
            st = (ctx['risk'].get('windows') or {}).get(key) or {}
            note = rk.beta_sentence(st.get('bench'), ctx['risk'].get('ccy'))
            if note:
                text(s, 9.0, 1.75 + 0.38 * len(side) + 0.15, 3.73, 1.6, note, size=9.5,
                     color=NAVY)

    # 5. every window
    if wr:
        s = content('Return, drawdown and beta by time window',
                    'Each row measured on daily closes for that window; beta against the '
                    'S&P 500')
        rows = [['Window', 'Change', 'S&P 500', 'Difference', 'Worst fall', 'High before',
                 'Low', 'Back at high', 'Volatility', 'Beta', 'Corr.']]
        for x in wr:
            rows.append([x['Window'], fnum(x['Change'], 'pct'), fnum(x['S&P 500'], 'pct'),
                         '-' if x['Relative (pts)'] is None else f'{x["Relative (pts)"]:+.1f} pts',
                         fnum(x['Worst fall'], 'pct'), x['High before the fall'], x['Low'],
                         x['Back at the high'], fnum(x['Volatility'], 'pct'), fnum(x['Beta']),
                         fnum(x['Correlation'])])
        table(s, X0, 1.75, [0.85, 1.0, 1.0, 1.15, 1.05, 1.45, 1.45, 1.45, 1.05, 0.8, 0.88],
              rows, size=10.5, rowh=0.38, aligns=['l'] + ['r'] * 4 + ['l'] * 3 + ['r'] * 3)
        ddf = ctx['risk'].get('dd_full') or {}
        if ddf:
            text(s, X0, 1.75 + 0.38 * len(rows) + 0.25, CW, 0.8,
                 rk.drawdown_sentence(ddf, where='in the full record'), size=11, color=NAVY)

    # 6. returns, cash and growth
    dup, qoe = ctx.get('dupont') or [], ctx.get('qoe_rows') or []
    if dup or qoe:
        s = content('How the return is earned, and whether it arrives as cash',
                    'Annual statements from Yahoo, oldest first')
        y = 1.75
        if dup:
            rows = [['Year', 'Net margin', 'Turnover', 'Leverage', 'ROE']] + [
                [d['period'], fnum(d['net_margin_pct'], 'pct'), fnum(d['asset_turnover']),
                 fnum(d['equity_multiplier']), fnum(d['roe_pct'], 'pct')] for d in dup]
            table(s, X0, y, [1.3, 1.15, 1.05, 1.05, 1.05], rows, size=10.5, rowh=0.36)
        if qoe:
            rows = [['Year', 'Net income', 'Operating cash', 'Cash / profit']] + [
                [q['period'], fnum(q['net_income'], 'money'), fnum(q['cfo'], 'money'),
                 fnum(q['cfo_to_ni'], 'x')] for q in qoe]
            table(s, 7.0, y, [1.3, 1.5, 1.6, 1.33], rows, size=10.5, rowh=0.36)
        lines = []
        if ctx.get('qoe_verdict'):
            lines.append(plain(ctx['qoe_verdict']))
        ps = ctx.get('per_share') or {}
        if ps.get('revenue_cagr_pct') is not None:
            lines.append(f'Over {ps.get("years")} years revenue grew '
                         f'{fnum(ps.get("revenue_cagr_pct"), "pct")} a year and revenue per share '
                         f'{fnum(ps.get("revenue_per_share_cagr_pct"), "pct")}; the share count '
                         f'changed {fnum(ps.get("share_count_cagr_pct"), "pct")} a year.')
        cap = ctx.get('capital') or {}
        if cap.get('uses'):
            top = cap['uses'][0]
            lines.append(f'The largest use of operating cash was {top["use"].lower()}, '
                         f'{fnum(top["pct_of_cfo"], "pct")} of the total over '
                         f'{cap.get("years")} years.')
        if lines:
            yy = y + 0.36 * (max(len(dup), len(qoe)) + 1) + 0.35
            text(s, X0, yy, CW, 6.8 - yy, [(t, {'space': 6 if i else 0})
                                           for i, t in enumerate(lines)], size=11, color=NAVY)

    # 7. valuation and ownership
    vr = valuation_rows(ctx)
    if vr:
        s = content('Valuation, ownership and the analyst view')
        rows = [['Measure', 'Value', 'Source']] + [list(x) for x in vr]
        table(s, X0, 1.5, [3.4, 2.2, 2.6], rows, size=11, rowh=0.36, aligns=['l', 'r', 'l'])

    # 8. where the numbers point
    sup, cut, ver = reading(ctx)
    s = content('Where the numbers point',
                'Generated from the figures in this pack' +
                (', with the analyst\'s note' if ctx.get('lede') else ''))
    y = 1.75
    if ctx.get('lede'):
        text(s, X0, y, CW, 0.9, ctx['lede'], size=12, color=INK, italic=True)
        y += 1.0
    n = max(len(sup), len(cut), len(ver), 1)
    rows = [['Supported by the data', 'Cuts against it', 'Verify before acting']]
    none = 'Nothing material from these figures.'
    sup, cut, ver = sup or [none], cut or [none], ver or [none]
    n = max(len(sup), len(cut), len(ver))
    for i in range(n):
        rows.append([sup[i] if i < len(sup) else '', cut[i] if i < len(cut) else '',
                     ver[i] if i < len(ver) else ''])
    table(s, X0, y, [CW / 3] * 3, rows, size=10.5, rowh=min(0.85, (6.75 - y) / (n + 1)),
          aligns=['l', 'l', 'l'], first_bold=False)

    # 9. notes
    s = content('Notes and sources')
    notes = [['Item', 'Note'],
             ['TradingView', f'Ratios, scores and returns as at {as_of}, the same export the '
                             f'screener uses.'],
             ['Yahoo', 'Statements, price history, valuation multiples, ownership and analyst '
                       'targets, fetched live.'],
             ['S&P 500', 'Benchmark for beta, correlation and relative performance, in US '
                         'dollars. Weekly returns for a year or more and for non-US listings.'],
             ['Use', 'For discussion and internal research. Not investment advice or a '
                     'recommendation; every figure is an input to a decision, not the '
                     'decision.']]
    table(s, X0, 1.5, [2.2, CW - 2.2], notes, size=11.5, rowh=0.6, aligns=['l', 'l'])

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
