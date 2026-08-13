import os
import pickle
import time
import datetime
import yfinance as yf
import pandas as pd
import numpy as np
import json
import re
import requests

def get_session():
    """
    Creates a requests Session with a standard browser User-Agent 
    to prevent Yahoo Finance from blocking cloud hosting IPs.
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive'
    })
    return session

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

DEFAULT_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B", 
    "JPM", "V", "JNJ", "WMT", "UNH", "XOM", "LLY", "AVGO", "COST", "PG"
]

def get_ticker_data(ticker_symbol: str, force_refresh: bool = False) -> dict:
    """Fetch everything Yahoo has for one ticker, keeping whatever arrives.

    This used to raise as soon as ticker.info came back thin, which threw away the
    statements and the price history along with it - and those are usually fine. On a
    hosted app the info endpoint is the first thing Yahoo throttles, so an all-or-nothing
    fetch means the whole page goes dark because one call was rate limited.

    Now every piece is fetched independently and kept on its own. A 'fetch_status' dict
    records what arrived and what did not, so the page can say which sections are missing
    and why instead of showing a blank.
    """
    ticker_symbol = ticker_symbol.strip().upper()
    cache_path = os.path.join(CACHE_DIR, f"{ticker_symbol}.pkl")

    if not force_refresh and os.path.exists(cache_path):
        try:
            if (time.time() - os.path.getmtime(cache_path)) < 86400:
                with open(cache_path, "rb") as f:
                    data = pickle.load(f)
                if isinstance(data, dict) and data.get('_any'):
                    return data
        except Exception as e:
            print(f"Error reading cache for {ticker_symbol}: {e}")

    print(f"Fetching live data for {ticker_symbol}...")
    # yfinance 1.x dropped the requests Session argument, so try it and fall back rather
    # than letting a library detail take the whole fetch down
    try:
        ticker = yf.Ticker(ticker_symbol, session=get_session())
        _ = ticker.fast_info
    except Exception:
        ticker = yf.Ticker(ticker_symbol)

    status, data = {}, {"symbol": ticker_symbol, "fetched_at": datetime.datetime.now()}

    def grab(name, fn, required_len=None):
        try:
            value = fn()
            if value is None:
                status[name] = 'Yahoo returned nothing'
                return None
            if required_len is not None and len(value) < required_len:
                status[name] = f'only {len(value)} fields returned, likely rate limited'
                return value or None
            if hasattr(value, 'empty') and value.empty:
                status[name] = 'Yahoo returned an empty table'
                return None
            status[name] = 'ok'
            return value
        except Exception as e:
            status[name] = f'{e.__class__.__name__}: {str(e)[:90]}'
            return None

    data['info'] = grab('info', lambda: ticker.info, required_len=5) or {}
    if not data['info']:
        # fast_info survives throttling more often and still carries price and share count,
        # which is enough for several things on the page
        try:
            fi = ticker.fast_info
            data['info'] = {k: v for k, v in {
                'currentPrice': getattr(fi, 'last_price', None),
                'sharesOutstanding': getattr(fi, 'shares', None),
                'currency': getattr(fi, 'currency', None),
                'marketCap': getattr(fi, 'market_cap', None),
                'fiftyTwoWeekLow': getattr(fi, 'year_low', None),
                'fiftyTwoWeekHigh': getattr(fi, 'year_high', None),
            }.items() if v is not None}
            if data['info']:
                status['info'] += ' - fell back to fast_info'
        except Exception:
            pass

    data['financials'] = grab('financials', lambda: ticker.financials)
    data['balance_sheet'] = grab('balance_sheet', lambda: ticker.balance_sheet)
    data['cashflow'] = grab('cashflow', lambda: ticker.cashflow)
    data['quarterly_financials'] = grab('quarterly_financials',
                                        lambda: ticker.quarterly_financials)
    # the full history Yahoo holds, not two years. The drawdown that matters is usually
    # older than any two year window - First Solar fell 91% from its 2008 peak, and a 2y
    # chart hides that completely. Fetched once and cached, so the cost is paid once.
    data['history'] = grab('history', lambda: ticker.history(period="max",
                                                             auto_adjust=True))
    if data['history'] is None:
        data['history'] = grab('history_5y',
                               lambda: ticker.history(period="5y", auto_adjust=True))
    if data['history'] is None:
        data['history'] = grab('history_1y',
                               lambda: ticker.history(period="1y", auto_adjust=True))

    holders = grab('institutional_holders', lambda: ticker.institutional_holders)
    if holders is not None and not isinstance(holders, pd.DataFrame):
        holders = pd.DataFrame(holders)
    data['institutional_holders'] = holders

    data['news'] = grab('news', lambda: ticker.news) or []

    options = {}
    try:
        expirations = ticker.options
        if expirations:
            chain = ticker.option_chain(expirations[0])
            options = {"expiration": expirations[0], "calls": chain.calls,
                       "puts": chain.puts}
            status['options'] = 'ok'
        else:
            status['options'] = 'no expirations listed'
    except Exception as e:
        status['options'] = f'{e.__class__.__name__}: {str(e)[:60]}'
    data['options'] = options

    data['fetch_status'] = status
    # anything at all is worth keeping and worth caching
    data['_any'] = any(data.get(k) is not None and (
        not hasattr(data[k], 'empty') or not data[k].empty)
        for k in ('financials', 'balance_sheet', 'cashflow', 'history')) or bool(data['info'])

    if data['_any']:
        try:
            with open(cache_path, "wb") as f:
                pickle.dump(data, f)
        except Exception as e:
            print(f"Could not cache {ticker_symbol}: {e}")
        return data

    # nothing arrived - fall back to a stale cache if one exists
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "rb") as f:
                stale = pickle.load(f)
            stale["fallback_stale"] = True
            return stale
        except Exception:
            pass
    data['error'] = ('Yahoo returned nothing usable. '
                     + '; '.join(f'{k}: {v}' for k, v in status.items() if v != 'ok')[:400])
    return data


def fetch_universe_data(tickers=None, progress_callback=None) -> dict:
    """
    Fetches data for a list of tickers, using cache where possible.
    """
    if tickers is None:
        tickers = DEFAULT_TICKERS
        
    results = {}
    total = len(tickers)
    for i, symbol in enumerate(tickers):
        if progress_callback:
            progress_callback(i / total, f"Loading {symbol} ({i+1}/{total})...")
        results[symbol] = get_ticker_data(symbol)
        
    if progress_callback:
        progress_callback(1.0, "Completed Loading Database!")
    return results


# ----------------------------------------------------------------- ISIN resolution ----
# An ISIN identifies a security but not the exchange it trades on, and Yahoo needs its own
# symbol with the venue suffix baked in (2330.TW, NOVO-B.CO, 1155.KL). Rather than guessing
# that suffix from the currency, this asks Yahoo's own search endpoint what it calls the
# security. That is authoritative, and it is the only way to reach markets where Yahoo uses
# a numeric code the source data does not carry - Malaysia writes MAYBANK, Yahoo says
# 1155.KL, and no suffix rule can bridge that.
#
# The catch worth knowing: one ISIN can have several listings, and search returns the most
# prominent one. For a European company that is often the US ADR rather than the primary
# line, which quotes in dollars and carries different per-share figures. So the result is
# checked against an expected currency whenever the caller can supply one.

ISIN_CACHE_PATH = os.path.join(CACHE_DIR, "isin_map.json")

# Bump this whenever the resolution logic changes. Entries stored under an older version
# are ignored and re-resolved, so a fix here reaches the app without anyone having to find
# and delete a cache file - which is not something you can easily do on a hosted app.
#   1: first version, compared currencies that Yahoo's search never returns
#   2: verifies the venue through the exchange code instead
ISIN_CACHE_VERSION = 2
_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def _load_isin_cache() -> dict:
    try:
        with open(ISIN_CACHE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_isin_cache(cache: dict) -> None:
    try:
        with open(ISIN_CACHE_PATH, "w") as f:
            json.dump(cache, f, indent=1, sort_keys=True)
    except Exception as e:
        print(f"Could not write the ISIN cache: {e}")


def looks_like_isin(text: str) -> bool:
    """Two letters, nine alphanumerics, one check digit."""
    return bool(_ISIN_RE.match(str(text).strip().upper()))


# Yahoo's search response carries an exchange code but no currency field, so a currency
# comparison can never succeed. These map the codes we actually see back to a currency,
# which is what makes a sanity check possible at all.
EXCHANGE_CURRENCY = {
    'NMS': 'USD', 'NGM': 'USD', 'NCM': 'USD', 'NYQ': 'USD', 'ASE': 'USD', 'BTS': 'USD',
    'PCX': 'USD', 'PNK': 'USD', 'OTC': 'USD',
    'EBS': 'CHF', 'GER': 'EUR', 'FRA': 'EUR', 'PAR': 'EUR', 'AMS': 'EUR', 'BRU': 'EUR',
    'MIL': 'EUR', 'MCE': 'EUR', 'LIS': 'EUR', 'VIE': 'EUR', 'DUB': 'EUR', 'HEL': 'EUR',
    'ATH': 'EUR', 'TAL': 'EUR', 'RIS': 'EUR', 'LIT': 'EUR',
    'LSE': 'GBP', 'IOB': 'USD',
    'STO': 'SEK', 'CPH': 'DKK', 'OSL': 'NOK', 'ICE': 'ISK',
    'TOR': 'CAD', 'VAN': 'CAD', 'CNQ': 'CAD',
    'JPX': 'JPY', 'HKG': 'HKD', 'TAI': 'TWD', 'TWO': 'TWD', 'KSC': 'KRW', 'KOE': 'KRW',
    'NSI': 'INR', 'BSE': 'INR', 'SES': 'SGD', 'KLS': 'MYR', 'JKT': 'IDR', 'SET': 'THB',
    'PHS': 'PHP', 'HSX': 'VND', 'SHH': 'CNY', 'SHZ': 'CNY',
    'ASX': 'AUD', 'NZE': 'NZD',
    'SAO': 'BRL', 'MEX': 'MXN', 'SGO': 'CLP', 'BUE': 'ARS', 'LIM': 'PEN',
    'JNB': 'ZAR', 'TLV': 'ILS', 'IST': 'TRY', 'WSE': 'PLN', 'SAU': 'SAR', 'DOH': 'QAR',
    'PRA': 'CZK', 'BUD': 'HUF', 'CAI': 'EGP',
}
# a US over-the-counter venue holding a foreign company is the classic ADR signature
US_OTC = {'PNK', 'OTC', 'IOB'}


def resolve_isin(isin: str, expect_currency: str = None, force_refresh: bool = False) -> dict:
    """ISIN -> {'symbol', 'exchange', 'currency', 'name', 'note'} or {'error': ...}.

    Cached to disk permanently, because an ISIN's Yahoo symbol does not change.

    A note on the ADR question. An ADR carries its own ISIN, normally a US one, so a
    single ISIN almost always maps to exactly one Yahoo symbol - the diagnostic returned
    count:1 for every ISIN tested, including Nestle, where the Swiss line came back and
    the ADR did not. So this no longer warns on every lookup. It warns only when the
    resolved venue genuinely disagrees with what the screener expected, which in practice
    means a foreign company resolving onto a US over-the-counter desk.
    """
    isin = str(isin).strip().upper()
    if not looks_like_isin(isin):
        return {"error": f"{isin} is not shaped like an ISIN"}

    cache = _load_isin_cache()
    hit = cache.get(isin)
    if (not force_refresh and hit and "symbol" in hit
            and hit.get("_v") == ISIN_CACHE_VERSION):
        return dict(hit, note=(hit.get("note", "") + " (cached)"))

    quotes = []
    try:
        quotes = list(getattr(yf, "Search")(isin, max_results=8).quotes or [])
    except Exception:
        try:
            r = get_session().get(
                "https://query2.finance.yahoo.com/v1/finance/search",
                params={"q": isin, "quotesCount": 8, "newsCount": 0}, timeout=15)
            r.raise_for_status()
            quotes = r.json().get("quotes", []) or []
        except Exception as e:
            return {"error": f"Yahoo search failed: {e}"}

    equities = [q for q in quotes
                if str(q.get("quoteType", "")).upper() in ("EQUITY", "ETF", "MUTUALFUND")
                and q.get("symbol")]
    if not equities:
        out = {"error": "Yahoo returned no security for this ISIN",
               "_v": ISIN_CACHE_VERSION}
        cache[isin] = out
        _save_isin_cache(cache)
        return out

    def ccy_of(quote):
        """The currency, from the response if present, otherwise from the venue code."""
        direct = quote.get("currency")
        if direct:
            return str(direct).upper()
        return EXCHANGE_CURRENCY.get(str(quote.get("exchange", "")).upper())

    want = None
    if expect_currency:
        want = str(expect_currency).upper()
        want = {"GBX": "GBP", "ZAC": "ZAR", "ILA": "ILS"}.get(want, want)

    chosen = equities[0]
    if want:
        match = [q for q in equities if ccy_of(q) == want]
        if match:
            chosen = match[0]

    venue = str(chosen.get("exchange", "")).upper()
    resolved_ccy = ccy_of(chosen)

    if len(equities) == 1:
        note = f"single match on {chosen.get('exchDisp') or venue}"
    elif want and resolved_ccy == want:
        note = f"picked the {want} listing out of {len(equities)} matches"
    else:
        note = f"first of {len(equities)} matches"

    # the only case that deserves a warning
    if want and venue in US_OTC and want != "USD":
        note = (f"resolved onto a US over-the-counter venue while the screener expected "
                f"{want}. This is very likely an ADR, so treat the per-share figures with "
                f"care - the ratios are still comparable")
    elif want and resolved_ccy and resolved_ccy != want:
        note = (f"resolved to a {resolved_ccy} listing though the screener expected {want}. "
                f"Ratios remain comparable, per-share figures are in {resolved_ccy}")

    out = {"symbol": chosen.get("symbol"),
           "exchange": chosen.get("exchDisp") or venue,
           "currency": resolved_ccy,
           "name": chosen.get("shortname") or chosen.get("longname"),
           "note": note,
           "_v": ISIN_CACHE_VERSION}
    cache[isin] = out
    _save_isin_cache(cache)
    return out


def get_ticker_data_by_isin(isin: str, expect_currency: str = None) -> dict:
    """Resolve an ISIN, then fetch that ticker the normal way."""
    res = resolve_isin(isin, expect_currency)
    if res.get("error"):
        return {"symbol": isin, "error": res["error"]}
    data = get_ticker_data(res["symbol"])
    data["resolved_from_isin"] = isin
    data["isin_resolution"] = res
    return data
