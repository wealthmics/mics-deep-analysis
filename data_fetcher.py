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
    """
    Fetches raw financial and price data for a ticker from yfinance,
    caching it locally to speed up subsequent loads.
    """
    ticker_symbol = ticker_symbol.strip().upper()
    cache_path = os.path.join(CACHE_DIR, f"{ticker_symbol}.pkl")
    
    # Check cache validity (24 hours expiry)
    if not force_refresh and os.path.exists(cache_path):
        try:
            file_age = time.time() - os.path.getmtime(cache_path)
            if file_age < 86400: # 24 hours
                with open(cache_path, "rb") as f:
                    data = pickle.load(f)
                    # Simple validation to ensure it has required structure
                    if isinstance(data, dict) and "info" in data:
                        return data
        except Exception as e:
            print(f"Error reading cache for {ticker_symbol}: {e}")
            
    # Fetch fresh data
    print(f"Fetching live data for {ticker_symbol}...")
    try:
        # yfinance moved from requests to curl_cffi around 0.2.5x, and newer versions
        # reject a plain requests Session. Try it, fall back to no session rather than
        # letting the whole fetch fail on a library detail.
        try:
            ticker = yf.Ticker(ticker_symbol, session=get_session())
            _ = ticker.fast_info            # forces the session to be exercised now
        except Exception:
            ticker = yf.Ticker(ticker_symbol)
        
        # 1. Info
        info = ticker.info
        if not info or len(info) < 5:
            # If yfinance returned empty or invalid info
            raise ValueError("No info returned from yfinance")
            
        # 2. Financials
        financials = ticker.financials
        balance_sheet = ticker.balance_sheet
        cashflow = ticker.cashflow
        
        # 3. Price History (2 years for beta, volatility, 200 SMA, drawdowns)
        history = ticker.history(period="2y")
        
        # 4. Institutional Holders
        try:
            inst_holders = ticker.institutional_holders
            if inst_holders is not None and not isinstance(inst_holders, pd.DataFrame):
                inst_holders = pd.DataFrame(inst_holders)
        except Exception:
            inst_holders = None
            
        # 5. Options data for Implied Volatility & Skew
        options_data = {}
        try:
            expirations = ticker.options
            if expirations:
                # Get nearest expiration
                near_exp = expirations[0]
                chain = ticker.option_chain(near_exp)
                options_data = {
                    "expiration": near_exp,
                    "calls": chain.calls,
                    "puts": chain.puts
                }
        except Exception as e:
            print(f"Could not fetch options for {ticker_symbol}: {e}")
            
        # 6. News
        news = []
        try:
            news = ticker.news
        except Exception:
            pass
            
        data = {
            "symbol": ticker_symbol,
            "fetched_at": datetime.datetime.now(),
            "info": info,
            "financials": financials,
            "balance_sheet": balance_sheet,
            "cashflow": cashflow,
            "history": history,
            "institutional_holders": inst_holders,
            "options": options_data,
            "news": news
        }
        
        # Save to cache
        with open(cache_path, "wb") as f:
            pickle.dump(data, f)
            
        return data
        
    except Exception as e:
        print(f"Error fetching data for {ticker_symbol}: {e}")
        # Try loading expired cache as fallback if yfinance fails
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "rb") as f:
                    data = pickle.load(f)
                    data["fallback_stale"] = True
                    return data
            except Exception:
                pass
        return {"symbol": ticker_symbol, "error": str(e)}

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


def resolve_isin(isin: str, expect_currency: str = None, force_refresh: bool = False) -> dict:
    """ISIN -> {'symbol', 'exchange', 'currency', 'name', 'note'} or {'error': ...}.

    Results are cached to disk permanently, because an ISIN's Yahoo symbol does not change.
    """
    isin = str(isin).strip().upper()
    if not looks_like_isin(isin):
        return {"error": f"{isin} is not shaped like an ISIN"}

    cache = _load_isin_cache()
    if not force_refresh and isin in cache and "symbol" in cache[isin]:
        return dict(cache[isin], note=cache[isin].get("note", "") + " (cached)")

    quotes = []
    # newer yfinance ships its own search wrapper; fall back to the raw endpoint
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
        out = {"error": "Yahoo returned no security for this ISIN"}
        cache[isin] = out
        _save_isin_cache(cache)
        return out

    chosen, note = equities[0], "first match from Yahoo search"
    if expect_currency:
        want = str(expect_currency).upper()
        want = {"GBX": "GBP", "ZAC": "ZAR", "ILA": "ILS"}.get(want, want)
        same = [q for q in equities
                if str(q.get("currency", "")).upper() == want]
        if same:
            chosen, note = same[0], f"matched on expected currency {want}"
        else:
            note = (f"no listing in {want} was offered, so this is Yahoo's most prominent "
                    f"line and may be an ADR - check the currency before trusting "
                    f"per-share figures")

    out = {"symbol": chosen.get("symbol"),
           "exchange": chosen.get("exchDisp") or chosen.get("exchange"),
           "currency": chosen.get("currency"),
           "name": chosen.get("shortname") or chosen.get("longname"),
           "note": note}
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
