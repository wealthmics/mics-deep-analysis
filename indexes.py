"""
The index list for the deep analysis app: global, regional and single country benchmarks,
each with the Yahoo symbol for the index itself and the ETFs that track it.

index   Yahoo symbol for the index level (price only, local currency). None where Yahoo has
        no reliable series; the page then works from the ETF alone.
etf     The main proxy ETF, used for holdings, valuation, costs and the return a US dollar
        investor actually got. Prefer the US listed fund where one exists.
alt     Other funds that track the same index, shown as alternatives.
ccy     Currency the index is quoted in.

Every symbol here is fetched live; if Yahoo ever renames one, the page says which symbol
failed and the fix is one line in this file. Add an index by adding one entry.
"""

REGIONS = ['Global', 'United States', 'Americas', 'Europe', 'Asia Pacific',
           'Middle East and Africa']

INDEXES = [
    # ---------------------------------------------------------------- global and regional
    dict(id='acwi', name='MSCI ACWI', region='Global', country='World', ccy='USD', index=None,
         etf='ACWI', alt=['VT'], about='Large and mid caps across 23 developed and 24 '
         'emerging markets, about 85% of the world\'s listed equity by value.'),
    dict(id='world', name='MSCI World', region='Global', country='Developed markets',
         ccy='USD', index=None, etf='URTH', alt=[], about='Large and mid caps across 23 '
         'developed markets.'),
    dict(id='eafe', name='MSCI EAFE', region='Global', country='Developed ex US and Canada',
         ccy='USD', index=None, etf='EFA', alt=['IEFA', 'VEA'], about='Developed markets in '
         'Europe, Australasia and the Far East, excluding the US and Canada.'),
    dict(id='em', name='MSCI Emerging Markets', region='Global', country='Emerging markets',
         ccy='USD', index=None, etf='EEM', alt=['IEMG', 'VWO'], about='Large and mid caps '
         'across 24 emerging markets.'),
    dict(id='stoxx600', name='STOXX Europe 600', region='Europe', country='Europe',
         ccy='EUR', index='^STOXX', etf='EXSA.DE', alt=['VGK'], about='600 large, mid and '
         'small caps across 17 European countries.'),
    dict(id='sx5e', name='EURO STOXX 50', region='Europe', country='Eurozone', ccy='EUR',
         index='^STOXX50E', etf='FEZ', alt=['EXW1.DE'], about='The 50 largest companies in '
         'the eurozone.'),
    dict(id='asiaxj', name='MSCI AC Asia ex Japan', region='Asia Pacific',
         country='Asia ex Japan', ccy='USD', index=None, etf='AAXJ', alt=[],
         about='Large and mid caps across developed and emerging Asia, excluding Japan.'),
    dict(id='latam40', name='S&P Latin America 40', region='Americas', country='Latin America',
         ccy='USD', index=None, etf='ILF', alt=[], about='40 large companies from Brazil, '
         'Mexico, Chile, Colombia and Peru.'),

    # ---------------------------------------------------------------- United States
    dict(id='spx', name='S&P 500', region='United States', country='United States',
         ccy='USD', index='^GSPC', etf='SPY', alt=['IVV', 'VOO'], about='500 leading US '
         'companies, weighted by free float market cap.'),
    dict(id='ndx', name='Nasdaq 100', region='United States', country='United States',
         ccy='USD', index='^NDX', etf='QQQ', alt=['QQQM'], about='The 100 largest non '
         'financial companies listed on Nasdaq.'),
    dict(id='ccmp', name='Nasdaq Composite', region='United States', country='United States',
         ccy='USD', index='^IXIC', etf='ONEQ', alt=[], about='Every common stock listed on '
         'Nasdaq.'),
    dict(id='dji', name='Dow Jones Industrial Average', region='United States',
         country='United States', ccy='USD', index='^DJI', etf='DIA', alt=[],
         about='30 large US companies, weighted by share price rather than market cap.'),
    dict(id='rui', name='Russell 1000', region='United States', country='United States',
         ccy='USD', index='^RUI', etf='IWB', alt=[], about='The 1,000 largest US companies.'),
    dict(id='rut', name='Russell 2000', region='United States', country='United States',
         ccy='USD', index='^RUT', etf='IWM', alt=['VTWO'], about='US small caps: the 2,000 '
         'companies ranked below the Russell 1000.'),
    dict(id='rua', name='Russell 3000', region='United States', country='United States',
         ccy='USD', index='^RUA', etf='IWV', alt=['VTI'], about='The 3,000 largest US '
         'companies, close to the whole investable US market.'),
    dict(id='mid', name='S&P MidCap 400', region='United States', country='United States',
         ccy='USD', index=None, etf='MDY', alt=['IJH'], about='400 US mid caps.'),

    # ---------------------------------------------------------------- Americas
    dict(id='tsx', name='S&P/TSX Composite', region='Americas', country='Canada', ccy='CAD',
         index='^GSPTSE', etf='EWC', alt=['XIC.TO'], about='The main Canadian benchmark, '
         'about 220 companies on the Toronto Stock Exchange.'),
    dict(id='mxx', name='S&P/BMV IPC', region='Americas', country='Mexico', ccy='MXN',
         index='^MXX', etf='EWW', alt=[], about='The 35 most traded stocks on the Mexican '
         'Stock Exchange.'),
    dict(id='bvsp', name='Ibovespa', region='Americas', country='Brazil', ccy='BRL',
         index='^BVSP', etf='EWZ', alt=['BOVA11.SA'], about='The main Brazilian benchmark, '
         'the most traded stocks on B3.'),
    dict(id='merv', name='S&P Merval', region='Americas', country='Argentina', ccy='ARS',
         index='^MERV', etf='ARGT', alt=[], about='The leading stocks on the Buenos Aires '
         'exchange. Peso inflation makes local currency returns hard to read.'),
    dict(id='chile', name='MSCI Chile', region='Americas', country='Chile', ccy='USD',
         index=None, etf='ECH', alt=[], about='Large and mid caps listed in Chile.'),
    dict(id='colombia', name='MSCI All Colombia', region='Americas', country='Colombia',
         ccy='USD', index=None, etf='GXG', alt=[], about='The largest companies listed in '
         'Colombia.'),
    dict(id='peru', name='MSCI All Peru', region='Americas', country='Peru', ccy='USD',
         index=None, etf='EPU', alt=[], about='Companies listed in Peru or with most of '
         'their business there.'),

    # ---------------------------------------------------------------- Europe
    dict(id='ukx', name='FTSE 100', region='Europe', country='United Kingdom', ccy='GBP',
         index='^FTSE', etf='EWU', alt=['ISF.L'], about='The 100 largest companies on the '
         'London Stock Exchange, most of whose revenue is earned abroad.'),
    dict(id='mcx', name='FTSE 250', region='Europe', country='United Kingdom', ccy='GBP',
         index='^FTMC', etf='VMID.L', alt=[], about='The next 250 UK companies after the '
         'FTSE 100, more tied to the domestic economy.'),
    dict(id='dax', name='DAX', region='Europe', country='Germany', ccy='EUR', index='^GDAXI',
         etf='EWG', alt=['EXS1.DE'], about='40 large German companies. A total return '
         'index, so dividends are already in the level.'),
    dict(id='cac', name='CAC 40', region='Europe', country='France', ccy='EUR',
         index='^FCHI', etf='EWQ', alt=['CAC.PA'], about='40 large companies on Euronext '
         'Paris.'),
    dict(id='aex', name='AEX', region='Europe', country='Netherlands', ccy='EUR',
         index='^AEX', etf='EWN', alt=[], about='The 25 most traded stocks on Euronext '
         'Amsterdam.'),
    dict(id='ibex', name='IBEX 35', region='Europe', country='Spain', ccy='EUR',
         index='^IBEX', etf='EWP', alt=[], about='The 35 most liquid Spanish stocks.'),
    dict(id='ftsemib', name='FTSE MIB', region='Europe', country='Italy', ccy='EUR',
         index='FTSEMIB.MI', etf='EWI', alt=[], about='The 40 most traded stocks on Borsa '
         'Italiana.'),
    dict(id='smi', name='Swiss Market Index', region='Europe', country='Switzerland',
         ccy='CHF', index='^SSMI', etf='EWL', alt=[], about='The 20 largest Swiss '
         'companies.'),
    dict(id='omx', name='OMX Stockholm 30', region='Europe', country='Sweden', ccy='SEK',
         index='^OMX', etf='EWD', alt=[], about='The 30 most traded stocks in Stockholm.'),
    dict(id='omxc25', name='OMX Copenhagen 25', region='Europe', country='Denmark',
         ccy='DKK', index='^OMXC25', etf='EDEN', alt=[], about='The 25 most traded Danish '
         'stocks.'),
    dict(id='omxh25', name='OMX Helsinki 25', region='Europe', country='Finland', ccy='EUR',
         index='^OMXH25', etf='EFNL', alt=[], about='The 25 most traded Finnish stocks.'),
    dict(id='norway', name='MSCI Norway', region='Europe', country='Norway', ccy='USD',
         index=None, etf='ENOR', alt=[], about='Large and mid caps listed in Norway.'),
    dict(id='bel20', name='BEL 20', region='Europe', country='Belgium', ccy='EUR',
         index='^BFX', etf='EWK', alt=[], about='The 20 largest companies on Euronext '
         'Brussels.'),
    dict(id='atx', name='ATX', region='Europe', country='Austria', ccy='EUR', index='^ATX',
         etf='EWO', alt=[], about='The 20 largest companies on the Vienna Stock Exchange.'),
    dict(id='ireland', name='MSCI Ireland', region='Europe', country='Ireland', ccy='USD',
         index=None, etf='EIRL', alt=[], about='Large, mid and small caps listed in '
         'Ireland.'),
    dict(id='poland', name='MSCI Poland', region='Europe', country='Poland', ccy='USD',
         index=None, etf='EPOL', alt=[], about='Large and mid caps listed in Poland.'),
    dict(id='xu100', name='BIST 100', region='Europe', country='Turkey', ccy='TRY',
         index='XU100.IS', etf='TUR', alt=[], about='The 100 largest stocks on Borsa '
         'Istanbul. Lira weakness makes local currency returns hard to read.'),
    dict(id='greece', name='MSCI All Greece', region='Europe', country='Greece', ccy='USD',
         index=None, etf='GREK', alt=[], about='Companies listed in Greece or with most of '
         'their business there.'),

    # ---------------------------------------------------------------- Asia Pacific
    dict(id='n225', name='Nikkei 225', region='Asia Pacific', country='Japan', ccy='JPY',
         index='^N225', etf='EWJ', alt=['1321.T'], about='225 large Japanese companies, '
         'weighted by share price. EWJ tracks MSCI Japan, a market cap weighted cousin; '
         '1321.T tracks the Nikkei itself.'),
    dict(id='topix', name='TOPIX', region='Asia Pacific', country='Japan', ccy='JPY',
         index=None, etf='1306.T', alt=['EWJ'], about='Nearly every company on the Tokyo '
         'Stock Exchange Prime market, weighted by market cap.'),
    dict(id='csi300', name='CSI 300', region='Asia Pacific', country='China', ccy='CNY',
         index='000300.SS', etf='ASHR', alt=[], about='300 large A shares listed in Shanghai '
         'and Shenzhen.'),
    dict(id='sse', name='SSE Composite', region='Asia Pacific', country='China', ccy='CNY',
         index='000001.SS', etf='ASHR', alt=[], about='Every stock on the Shanghai Stock '
         'Exchange. ASHR tracks the CSI 300, the closest liquid proxy.'),
    dict(id='szse', name='Shenzhen Component', region='Asia Pacific', country='China',
         ccy='CNY', index='399001.SZ', etf='ASHR', alt=[], about='500 leading Shenzhen '
         'stocks. ASHR tracks the CSI 300, the closest liquid proxy.'),
    dict(id='mchi', name='MSCI China', region='Asia Pacific', country='China', ccy='USD',
         index=None, etf='MCHI', alt=['FXI'], about='Chinese companies across Hong Kong, '
         'mainland and US listings.'),
    dict(id='hsi', name='Hang Seng', region='Asia Pacific', country='Hong Kong', ccy='HKD',
         index='^HSI', etf='2800.HK', alt=['EWH'], about='The largest companies listed in '
         'Hong Kong.'),
    dict(id='hscei', name='Hang Seng China Enterprises', region='Asia Pacific',
         country='China', ccy='HKD', index='^HSCE', etf='2828.HK', alt=[],
         about='Mainland Chinese companies listed in Hong Kong.'),
    dict(id='twii', name='TAIEX', region='Asia Pacific', country='Taiwan', ccy='TWD',
         index='^TWII', etf='EWT', alt=['0050.TW'], about='Every common stock on the Taiwan '
         'Stock Exchange; semiconductors dominate.'),
    dict(id='kospi', name='KOSPI', region='Asia Pacific', country='South Korea', ccy='KRW',
         index='^KS11', etf='EWY', alt=[], about='Every common stock on the Korea Exchange '
         'main board.'),
    dict(id='kosdaq', name='KOSDAQ', region='Asia Pacific', country='South Korea',
         ccy='KRW', index='^KQ11', etf=None, alt=[], about='Korea\'s growth and technology '
         'market.'),
    dict(id='nifty', name='Nifty 50', region='Asia Pacific', country='India', ccy='INR',
         index='^NSEI', etf='INDA', alt=['NIFTYBEES.NS'], about='50 large companies on the '
         'National Stock Exchange of India. INDA tracks MSCI India, a broader cousin; '
         'NIFTYBEES tracks the Nifty itself.'),
    dict(id='sensex', name='BSE Sensex', region='Asia Pacific', country='India', ccy='INR',
         index='^BSESN', etf='INDA', alt=[], about='30 large companies on the BSE.'),
    dict(id='niftybank', name='Nifty Bank', region='Asia Pacific', country='India',
         ccy='INR', index='^NSEBANK', etf=None, alt=[], about='The most liquid Indian bank '
         'stocks.'),
    dict(id='jkse', name='Jakarta Composite', region='Asia Pacific', country='Indonesia',
         ccy='IDR', index='^JKSE', etf='EIDO', alt=[], about='Every stock on the Indonesia '
         'Stock Exchange.'),
    dict(id='klci', name='FTSE Bursa Malaysia KLCI', region='Asia Pacific',
         country='Malaysia', ccy='MYR', index='^KLSE', etf='EWM', alt=[],
         about='The 30 largest companies on Bursa Malaysia.'),
    dict(id='sti', name='Straits Times Index', region='Asia Pacific', country='Singapore',
         ccy='SGD', index='^STI', etf='EWS', alt=['ES3.SI'], about='The 30 largest companies '
         'on the Singapore Exchange; banks dominate.'),
    dict(id='set', name='SET Index', region='Asia Pacific', country='Thailand', ccy='THB',
         index='^SET.BK', etf='THD', alt=[], about='Every stock on the Stock Exchange of '
         'Thailand.'),
    dict(id='psei', name='PSEi', region='Asia Pacific', country='Philippines', ccy='PHP',
         index='PSEI.PS', etf='EPHE', alt=[], about='30 large companies on the Philippine '
         'Stock Exchange.'),
    dict(id='vietnam', name='MarketVector Vietnam Local', region='Asia Pacific',
         country='Vietnam', ccy='USD', index=None, etf='VNM', alt=[], about='Vietnamese '
         'companies and those with most of their revenue in Vietnam.'),
    dict(id='asx200', name='S&P/ASX 200', region='Asia Pacific', country='Australia',
         ccy='AUD', index='^AXJO', etf='EWA', alt=['STW.AX'], about='The 200 largest '
         'companies on the ASX; banks and miners dominate.'),
    dict(id='aord', name='All Ordinaries', region='Asia Pacific', country='Australia',
         ccy='AUD', index='^AORD', etf='EWA', alt=[], about='The 500 largest companies on '
         'the ASX.'),
    dict(id='nz50', name='S&P/NZX 50', region='Asia Pacific', country='New Zealand',
         ccy='NZD', index='^NZ50', etf='ENZL', alt=[], about='The 50 largest companies on '
         'the NZX. A gross index, so dividends are included.'),

    # ---------------------------------------------------------------- Middle East and Africa
    dict(id='tasi', name='Tadawul All Share', region='Middle East and Africa',
         country='Saudi Arabia', ccy='SAR', index='^TASI.SR', etf='KSA', alt=[],
         about='Every stock on the Saudi Exchange.'),
    dict(id='uae', name='MSCI UAE', region='Middle East and Africa',
         country='United Arab Emirates', ccy='USD', index=None, etf='UAE', alt=[],
         about='Large and mid caps listed in Abu Dhabi and Dubai.'),
    dict(id='qatar', name='MSCI All Qatar', region='Middle East and Africa', country='Qatar',
         ccy='USD', index=None, etf='QAT', alt=[], about='Companies listed in Qatar.'),
    dict(id='ta35', name='TA-35', region='Middle East and Africa', country='Israel',
         ccy='ILS', index='TA35.TA', etf='EIS', alt=[], about='The 35 largest companies on '
         'the Tel Aviv Stock Exchange.'),
    dict(id='southafrica', name='MSCI South Africa', region='Middle East and Africa',
         country='South Africa', ccy='USD', index=None, etf='EZA', alt=[],
         about='Large and mid caps listed in South Africa.'),
    dict(id='egx30', name='EGX 30', region='Middle East and Africa', country='Egypt',
         ccy='EGP', index='^CASE30', etf=None, alt=[], about='The 30 largest companies on '
         'the Egyptian Exchange. Pound devaluations make local returns hard to read.'),
]

BY_ID = {x['id']: x for x in INDEXES}


def find(key):
    """An entry by id, or a custom entry for any Yahoo symbol typed in.

    A symbol starting with ^ is treated as an index, anything else as a fund.
    """
    if not key:
        return None
    key = str(key).strip()
    if key in BY_ID:
        return BY_ID[key]
    sym = key.upper()
    for x in INDEXES:
        if sym in {str(x.get('index') or '').upper(), str(x.get('etf') or '').upper()}:
            return x
    is_index = sym.startswith('^')
    return dict(id=sym, name=sym, region='Custom', country='', ccy=None,
                index=sym if is_index else None, etf=None if is_index else sym, alt=[],
                about='A symbol typed in directly, not one of the indexes in the list.',
                custom=True)


def label(x):
    where = x['country'] if x['country'] and x['country'] != x['name'] else ''
    return f'{x["name"]}' + (f', {where}' if where and where not in x['name'] else '')
