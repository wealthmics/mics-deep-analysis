r"""
=====================================================================================
ISIN RESOLUTION DIAGNOSTIC
=====================================================================================
Run this locally to see exactly why ISIN lookups are failing. It tries four different
routes to Yahoo and prints the raw response for each, so we can tell the difference
between "Yahoo blocked us", "Yahoo does not know this ISIN" and "our code is wrong".

    python isin_diagnostic.py

Edit TEST_ISINS below to use real ISINs from your own TradingView export. The ones
listed are well known and should resolve if the route itself works.
=====================================================================================
"""

import json
import sys

TEST_ISINS = [
    ('US0378331005', 'Apple',            'USD'),
    ('CH0038863350', 'Nestle',           'CHF'),
    ('DE000A1EWWW0', 'adidas',           'EUR'),
    ('TW0002330008', 'TSMC',             'TWD'),
    ('MYL1155OO000', 'Malayan Banking',  'MYR'),
]

HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'),
    'Accept': 'application/json,text/plain,*/*',
    'Accept-Language': 'en-US,en;q=0.9',
}


def route_1_plain_requests(isin):
    """The endpoint on query2, no cookies. This is what data_fetcher does today."""
    import requests
    r = requests.get('https://query2.finance.yahoo.com/v1/finance/search',
                     params={'q': isin, 'quotesCount': 8, 'newsCount': 0},
                     headers=HEADERS, timeout=15)
    return r.status_code, r.text[:600]


def route_2_query1(isin):
    """Same call against query1, which is sometimes gated differently."""
    import requests
    r = requests.get('https://query1.finance.yahoo.com/v1/finance/search',
                     params={'q': isin, 'quotesCount': 8, 'newsCount': 0},
                     headers=HEADERS, timeout=15)
    return r.status_code, r.text[:600]


def route_3_with_cookie_and_crumb(isin):
    """Pick up a consent cookie first, then call. Needed when Yahoo returns 401."""
    import requests
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get('https://fc.yahoo.com', timeout=15)               # seeds the cookie jar
    r = s.get('https://query2.finance.yahoo.com/v1/finance/search',
              params={'q': isin, 'quotesCount': 8, 'newsCount': 0}, timeout=15)
    return r.status_code, r.text[:600]


def route_4_yfinance_search(isin):
    """yfinance's own wrapper, which handles cookies and crumbs internally."""
    import yfinance as yf
    if not hasattr(yf, 'Search'):
        return 'n/a', 'this yfinance version has no Search class - pip install -U yfinance'
    res = yf.Search(isin, max_results=8)
    return 'ok', json.dumps(res.quotes, indent=1)[:600]


ROUTES = [
    ('1. plain requests, query2', route_1_plain_requests),
    ('2. plain requests, query1', route_2_query1),
    ('3. cookie first, query2', route_3_with_cookie_and_crumb),
    ('4. yfinance Search', route_4_yfinance_search),
]


def summarise(payload):
    """Pull the useful bits out of a raw response so the output stays readable."""
    try:
        data = json.loads(payload) if payload.strip().startswith('{') else None
    except Exception:
        data = None
    if data is None:
        return None
    quotes = data.get('quotes')
    if quotes is None:
        return None
    return [{'symbol': q.get('symbol'), 'currency': q.get('currency'),
             'exchange': q.get('exchDisp') or q.get('exchange'),
             'type': q.get('quoteType'), 'name': q.get('shortname')} for q in quotes]


def main():
    try:
        import requests  # noqa: F401
    except ImportError:
        sys.exit('pip install requests\n')

    print(f'python {sys.version.split()[0]}')
    try:
        import yfinance as yf
        print(f'yfinance {yf.__version__}, has Search class: {hasattr(yf, "Search")}')
    except ImportError:
        print('yfinance not installed')
    print()

    working = set()
    for isin, name, ccy in TEST_ISINS:
        print('=' * 78)
        print(f'{isin}   {name}   expected currency {ccy}')
        print('=' * 78)
        for label, fn in ROUTES:
            try:
                status, body = fn(isin)
            except Exception as e:
                print(f'  {label:<28} EXCEPTION {e.__class__.__name__}: {str(e)[:90]}')
                continue
            picked = summarise(body)
            if picked:
                working.add(label)
                print(f'  {label:<28} {status}  ->  {len(picked)} results')
                for q in picked[:4]:
                    star = '  <-- matches expected currency' if q['currency'] == ccy else ''
                    print(f'        {str(q["symbol"]):<14} {str(q["currency"]):<5} '
                          f'{str(q["type"]):<12} {str(q["exchange"])[:18]:<18}{star}')
            elif label.startswith('4.') and status == 'ok':
                working.add(label)
                print(f'  {label:<28} ok  ->  {body[:200]}')
            else:
                print(f'  {label:<28} {status}  ->  {body[:160].replace(chr(10), " ")}')
        print()

    print('=' * 78)
    print('WHAT THIS MEANS')
    print('=' * 78)
    if working:
        print('These routes returned data:')
        for w in sorted(working):
            print(f'  {w}')
        print('\nSend me this output and I will switch data_fetcher to whichever route')
        print('works, and drop the ones that do not.')
    else:
        print('No route returned anything. Either this network blocks Yahoo, or Yahoo has')
        print('closed the search endpoint to unauthenticated callers. In that case ISIN')
        print('lookup is not available and we go back to mapping tickers by currency,')
        print('which was already tested and works for 37 currencies.')


if __name__ == '__main__':
    main()
