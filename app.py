import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import os
import datetime

# Import modules from the same folder
import data_fetcher as df_mod
import financial_formulas as ff_mod
from financial_formulas import get_val

# Set Headless / Minimalist Streamlit Page Configuration
st.set_page_config(
    page_title="Stock Selection Quant Screener",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Minimalist Look
st.markdown("""
<style>
    /* Global Styles */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background-color: #0b0c10;
        color: #c5c6c7;
    }
    .main .block-container {
        padding-top: 1.5rem;
        max-width: 95%;
    }
    
    /* Hide default streamlit elements for cleaner look */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Clean Metric Section */
    .funnel-container {
        display: flex;
        justify-content: space-between;
        border-bottom: 1px solid #1f2833;
        padding-bottom: 1rem;
        margin-bottom: 1.5rem;
    }
    .funnel-step {
        text-align: left;
        flex: 1;
    }
    .funnel-label {
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: #66fcf1;
        margin-bottom: 0.25rem;
    }
    .funnel-value {
        font-size: 1.5rem;
        font-weight: 300;
        color: #ffffff;
    }
    
    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background-color: #1f2833;
        border-right: 1px solid #45a29e;
    }
    
    /* Buttons */
    .stButton>button {
        background-color: transparent;
        color: #66fcf1;
        border: 1px solid #66fcf1;
        border-radius: 2px;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #66fcf1;
        color: #0b0c10;
        border: 1px solid #66fcf1;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- SESSION STATE & INITIALIZATION -----------------
if "tickers" not in st.session_state:
    st.session_state.tickers = list(df_mod.DEFAULT_TICKERS)


# ----------------- DEEP LINK FROM THE SCREENER -----------------
# The static screener links here as ?ticker=AAPL. Anything arriving that way is added to
# the watchlist and selected, so the page opens straight on that company's audit.
def _read_deep_link():
    """Read ?ticker=, ?isin= and ?ccy= off the URL, whichever Streamlit API is available."""
    def grab(params, key):
        raw = params.get(key)
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        return str(raw).strip() if raw else None

    params = None
    try:
        params = st.query_params                       # Streamlit 1.30 and newer
        _ = params.get("ticker")
    except Exception:
        try:
            params = st.experimental_get_query_params()
        except Exception:
            return None, None, None
    return (grab(params, "ticker") or None,
            grab(params, "isin") or None,
            grab(params, "ccy") or None)


_link_ticker, _link_isin, _link_ccy = _read_deep_link()
_link_key = f"{_link_ticker}|{_link_isin}|{_link_ccy}"

if (_link_ticker or _link_isin) and _link_key != st.session_state.get("_last_deep_link"):
    st.session_state["_last_deep_link"] = _link_key
    _symbol = None

    # An ISIN is preferred when the screener sends one. Yahoo's own search decides the
    # symbol, which beats guessing a venue suffix from the currency, and it is the only
    # route to exchanges Yahoo keys by numeric code rather than by name.
    if _link_isin and df_mod.looks_like_isin(_link_isin):
        with st.spinner(f"Resolving {_link_isin} on Yahoo..."):
            _res = df_mod.resolve_isin(_link_isin, expect_currency=_link_ccy)
        if _res.get("symbol"):
            _symbol = _res["symbol"]
            _msg = (f"**{_link_isin}** resolved to **{_symbol}** "
                    f"({_res.get('exchange')}, {_res.get('currency')}) - {_res.get('note')}")
            if "may be an ADR" in (_res.get("note") or ""):
                st.warning(_msg)
            else:
                st.caption(_msg)
        else:
            st.warning(f"{_link_isin} could not be resolved on Yahoo: {_res.get('error')}. "
                       f"Falling back to the ticker from the screener.")

    if not _symbol and _link_ticker:
        _symbol = _link_ticker.upper()

    if _symbol:
        if _symbol not in st.session_state.tickers:
            st.session_state.tickers.insert(0, _symbol)
        st.session_state.search_query = _symbol

# ----------------- SIDEBAR CONTROLS -----------------
st.sidebar.title("Screener Settings")

# 1. Universe Custom Tickers
st.sidebar.subheader("Stock Universe")
ticker_input = st.sidebar.text_area("Add Custom Tickers (comma separated):", value="")
if st.sidebar.button("Add Tickers", key="add_t_btn"):
    if ticker_input:
        new_symbols = [s.strip().upper() for s in ticker_input.split(",") if s.strip()]
        for s in new_symbols:
            if s not in st.session_state.tickers:
                st.session_state.tickers.append(s)
        st.success(f"Added {len(new_symbols)} tickers.")
        st.rerun()

if st.sidebar.button("Reset Watchlist", key="reset_w_btn"):
    st.session_state.tickers = list(df_mod.DEFAULT_TICKERS)
    st.rerun()

# 2. Stage 1 Thresholds
st.sidebar.subheader("Integrity Constraints")
beneish_limit = st.sidebar.slider("Beneish M-Score Limit (Fail if >=)", -3.0, -1.5, -2.22, 0.05)
piotroski_limit = st.sidebar.slider("Piotroski F-Score Limit (Fail if <)", 0, 9, 6)
altman_limit = st.sidebar.slider("Altman Z-Score Limit (Fail if <=)", 1.0, 4.0, 2.5, 0.1)
ohlson_limit = st.sidebar.slider("Ohlson O-Score Prob Limit (Fail if >=)", 0.01, 0.20, 0.05, 0.01)

# 3. Cutoff Percentiles for Stages 2-7
st.sidebar.subheader("Funnel Cutoffs")
stage2_pct = st.sidebar.slider("Stage 2 Keep (Quality Top %)", 10, 100, 30)
stage3_pct = st.sidebar.slider("Stage 3 Keep (Capital Alloc Top %)", 10, 100, 40)
stage4_pct = st.sidebar.slider("Stage 4 Keep (Growth Top %)", 10, 100, 50)
stage5_pct = st.sidebar.slider("Stage 5 Keep (Valuation Top %)", 10, 100, 50)
stage6_pct = st.sidebar.slider("Stage 6 Keep (Momentum Top %)", 10, 100, 60)
stage7_pct = st.sidebar.slider("Stage 7 Reject (Worst %)", 5, 50, 25)

# Refresh Button
force_refresh = st.sidebar.button("Force Refresh All Data", key="refresh_all_btn")

# ----------------- DATA LOADING -----------------
@st.cache_data(show_spinner=False)
def load_all_data(tickers, force):
    progress_bar = st.progress(0.0)
    status_text = st.empty()
    
    def update_progress(pct, text):
        progress_bar.progress(pct)
        status_text.text(text)
        
    df_mod.get_ticker_data("SPY", force_refresh=force)
    raw_data = df_mod.fetch_universe_data(tickers, progress_callback=update_progress)
    progress_bar.empty()
    status_text.empty()
    return raw_data

raw_data = load_all_data(st.session_state.tickers, force_refresh)
spy_data = df_mod.get_ticker_data("SPY")
spy_history = spy_data.get("history") if "history" in spy_data else None

# Precompute institutional portfolios dictionary
all_inst_portfolios = {}
for s, data in raw_data.items():
    if "error" in data:
        continue
    inst = data.get("institutional_holders")
    if inst is not None and not inst.empty and "Holder" in inst.columns:
        all_inst_portfolios[s] = set(inst["Holder"].tolist())
    else:
        all_inst_portfolios[s] = set()

# ----------------- MAIN TITLE -----------------
st.title("Stock Selection Screener")
st.markdown("Systematic multi-stage quant screening pipeline.")
st.write("")

# ----------------- MAIN TITLE & SEARCH -----------------
# Google-like live search querying the actual Yahoo Finance database
search_col1, search_col2 = st.columns([2, 3])
with search_col1:
    search_query = st.text_input("Search Ticker or Company Name (e.g. Apple, Reliance, BTC, TSLA):", value="").strip()

if search_query:
    # Query Yahoo Finance Search API dynamically
    with st.spinner("Searching Yahoo Finance..."):
        try:
            import requests
            headers = {'User-Agent': 'Mozilla/5.0'}
            r = requests.get(f"https://query1.finance.yahoo.com/v1/finance/search?q={search_query}", headers=headers, timeout=5)
            if r.status_code == 200:
                results = r.json().get("quotes", [])
                
                # Filter down to entries with valid symbols
                valid_quotes = [q for q in results if q.get("symbol")]
                
                if valid_quotes:
                    options = []
                    symbol_map = {}
                    for q in valid_quotes:
                        sym = q.get("symbol")
                        name = q.get("longname") or q.get("shortname") or "Unknown"
                        exch = q.get("exchDisp") or q.get("exchange") or "Unknown"
                        opt_str = f"{sym} - {name} ({exch})"
                        options.append(opt_str)
                        symbol_map[opt_str] = sym
                        
                    selected_opt = st.selectbox(
                        f"Select from matching results ({len(options)} found):",
                        options=[""] + options,
                        index=0,
                        key="search_results_select"
                    )
                    
                    if selected_opt:
                        selected_symbol = symbol_map[selected_opt]
                        st.session_state.search_query = selected_symbol
                        if selected_symbol not in st.session_state.tickers:
                            with st.spinner(f"Downloading data for {selected_symbol}..."):
                                res = df_mod.get_ticker_data(selected_symbol)
                                if "error" not in res:
                                    st.session_state.tickers.append(selected_symbol)
                                    st.success(f"Added {selected_symbol} to active screening cohort.")
                                    st.rerun()
                                else:
                                    st.error(f"Could not fetch {selected_symbol}: {res['error']}")
                else:
                    st.warning("No matching tickers found on Yahoo Finance.")
            else:
                st.error("Failed to query Yahoo Finance search service.")
        except Exception as e:
            st.error(f"Error querying search service: {e}")


# ----------------- METRIC CALCULATIONS & FUNNEL PIPELINE -----------------
all_metrics = []
for symbol in st.session_state.tickers:
    data = raw_data.get(symbol, {})
    if "error" in data or not data.get("info"):
        continue
        
    info = data.get("info", {})
    history = data.get("history")
    inst = data.get("institutional_holders")
    options = data.get("options")
    
    p_score_res = ff_mod.calc_piotroski_f_score(data)
    m_score_res = ff_mod.calc_beneish_m_score(data)
    dechow_res = ff_mod.calc_dechow_f_score(data)
    z_score_res = ff_mod.calc_altman_z_score(data)
    o_score_res = ff_mod.calc_ohlson_o_score(data)
    sloan_res = ff_mod.calc_sloan_accrual_ratio(data)
    
    quality = ff_mod.calc_quality_score(data)
    cap_alloc = ff_mod.calc_capital_allocation_score(data)
    growth = ff_mod.calc_growth_score(data)
    val = ff_mod.calc_valuation_score(data)
    
    price = info.get("currentPrice") or info.get("previousClose") or 1.0
    skew = ff_mod.calc_options_skew(options, price)
    prc_stats = ff_mod.calc_momentum_and_risk(history, spy_history)
    ownership_score = ff_mod.calc_network_ownership_score(inst, all_inst_portfolios)
    
    total_fields = 20
    available_fields = sum([
        1 if info.get("marketCap") else 0,
        1 if p_score_res.get("score") is not None else 0,
        1 if m_score_res.get("score") is not None else 0,
        1 if z_score_res.get("score") is not None else 0,
        1 if o_score_res.get("score") is not None else 0,
        1 if dechow_res.get("score") is not None else 0,
        1 if sloan_res.get("score") is not None else 0,
        1 if len(quality) > 0 else 0,
        1 if len(cap_alloc) > 0 else 0,
        1 if len(growth) > 0 else 0,
        1 if len(val) > 0 else 0,
        1 if len(prc_stats) > 0 else 0
    ])
    completeness = int((available_fields / 12) * 100)
    
    metric_entry = {
        "symbol": symbol,
        "completeness": completeness,
        "price": price,
        "market_cap": info.get("marketCap") or 0.0,
        "vol_avg": info.get("averageVolume10days") or 0.0,
        "quote_type": info.get("quoteType", "EQUITY"),
        "piotroski": p_score_res.get("score"),
        "beneish": m_score_res.get("score"),
        "dechow": dechow_res.get("score"),
        "altman": z_score_res.get("score"),
        "ohlson": o_score_res.get("score"),
        "sloan": sloan_res.get("score"),
        **quality,
        **cap_alloc,
        **growth,
        **val,
        **prc_stats,
        "skew": skew,
        "ownership": ownership_score
    }
    all_metrics.append(metric_entry)

df_all = pd.DataFrame(all_metrics)

if df_all.empty:
    st.error("No valid ticker data could be loaded. Check connection or input tickers.")
    st.stop()

# Cohort median imputation
numeric_cols = df_all.select_dtypes(include=[np.number]).columns
for col in numeric_cols:
    median_val = df_all[col].median()
    df_all[col] = df_all[col].fillna(median_val)

# ----------------- RUN THE 8 STAGE PIPELINE -----------------
pipeline_tracker = {}

# STAGE 0: Universe Definition
s0_cond = (
    (df_all["quote_type"] == "EQUITY") & 
    (df_all["market_cap"] > 1e9) & 
    (df_all["price"] > 5) & 
    ((df_all["vol_avg"] * df_all["price"]) > 1e7)
)
df_s0 = df_all[s0_cond].copy()
pipeline_tracker["Universe"] = len(df_s0)

# STAGE 1: Financial Integrity
df_s0["fail_beneish"] = (df_s0["beneish"] >= beneish_limit).astype(int)
df_s0["fail_piotroski"] = (df_s0["piotroski"] < piotroski_limit).astype(int)
df_s0["fail_altman"] = (df_s0["altman"] <= altman_limit).astype(int)
df_s0["fail_ohlson"] = (df_s0["ohlson"] >= ohlson_limit).astype(int)

dechow_cutoff = df_s0["dechow"].quantile(0.80)
df_s0["fail_dechow"] = (df_s0["dechow"] >= dechow_cutoff).astype(int)

sloan_cutoff = df_s0["sloan"].quantile(0.70)
df_s0["fail_sloan"] = (df_s0["sloan"] >= sloan_cutoff).astype(int)

df_s0["total_fails"] = (
    df_s0["fail_beneish"] + 
    df_s0["fail_piotroski"] + 
    df_s0["fail_altman"] + 
    df_s0["fail_ohlson"] + 
    df_s0["fail_dechow"] + 
    df_s0["fail_sloan"]
)

df_s1 = df_s0[df_s0["total_fails"] < 2].copy()
pipeline_tracker["Integrity"] = len(df_s1)

def score_cohort(df, columns, score_name):
    ranks = pd.DataFrame(index=df.index)
    for col in columns:
        if col in df.columns:
            ranks[col] = df[col].rank(pct=True) * 100
    df[score_name] = ranks.mean(axis=1)
    return df

# STAGE 2: Quality
q_cols = ["gross_profitability", "roic", "croic", "roe", "operating_margin", "cash_conversion", "qmj_profitability"]
df_s1 = score_cohort(df_s1, q_cols, "quality_score")
q_cutoff = df_s1["quality_score"].quantile(1.0 - (stage2_pct / 100.0)) if not df_s1.empty else 0
df_s2 = df_s1[df_s1["quality_score"] >= q_cutoff].copy() if not df_s1.empty else df_s1
pipeline_tracker["Quality"] = len(df_s2)

# STAGE 3: Capital Allocation
ca_cols = ["shareholder_yield", "buyback_effectiveness", "incremental_roic", "fcf_conversion"]
if not df_s2.empty and "share_count_trend" in df_s2.columns:
    df_s2["share_count_trend_inv"] = -df_s2["share_count_trend"]
    df_s2 = score_cohort(df_s2, ca_cols + ["share_count_trend_inv"], "cap_alloc_score")
else:
    df_s2 = score_cohort(df_s2, ca_cols, "cap_alloc_score")
ca_cutoff = df_s2["cap_alloc_score"].quantile(1.0 - (stage3_pct / 100.0)) if not df_s2.empty else 0
df_s3 = df_s2[df_s2["cap_alloc_score"] >= ca_cutoff].copy() if not df_s2.empty else df_s2
pipeline_tracker["Cap Alloc"] = len(df_s3)

# STAGE 4: Growth
g_cols = ["revenue_cagr", "eps_cagr", "fcf_cagr", "book_value_cagr", "earnings_revision_trend"]
df_s3 = score_cohort(df_s3, g_cols, "growth_score")
g_cutoff = df_s3["growth_score"].quantile(1.0 - (stage4_pct / 100.0)) if not df_s3.empty else 0
df_s4 = df_s3[df_s3["growth_score"] >= g_cutoff].copy() if not df_s3.empty else df_s3
pipeline_tracker["Growth"] = len(df_s4)

# STAGE 5: Valuation
v_cols = ["earnings_yield", "acquirers_multiple", "ev_ebit", "ev_fcf", "buffett_yield", "shareholder_yield"]
df_s4 = score_cohort(df_s4, v_cols, "value_score")
v_cutoff = df_s4["value_score"].quantile(1.0 - (stage5_pct / 100.0)) if not df_s4.empty else 0
df_s5 = df_s4[df_s4["value_score"] >= v_cutoff].copy() if not df_s4.empty else df_s4
pipeline_tracker["Valuation"] = len(df_s5)

# STAGE 6: Momentum
m_cols = ["price_above_200sma", "residual_momentum", "relative_strength", "trend_composite"]
df_s5 = score_cohort(df_s5, m_cols, "momentum_score")
m_cutoff = df_s5["momentum_score"].quantile(1.0 - (stage6_pct / 100.0)) if not df_s5.empty else 0
df_s6 = df_s5[df_s5["momentum_score"] >= m_cutoff].copy() if not df_s5.empty else df_s5
pipeline_tracker["Momentum"] = len(df_s6)

# STAGE 7: Risk Filter
r_cols = ["volatility", "max_drawdown", "beta", "downside_beta", "idiosyncratic_vol"]
df_s6 = score_cohort(df_s6, r_cols, "risk_score")
r_cutoff = df_s6["risk_score"].quantile(stage7_pct / 100.0) if not df_s6.empty else 0
df_s7 = df_s6[df_s6["risk_score"] >= r_cutoff].copy() if not df_s6.empty else df_s6
pipeline_tracker["Risk Filter"] = len(df_s7)

selected_symbols = set(df_s7["symbol"].tolist()) if not df_s7.empty else set()

# ----------------- SCREENER DASHBOARD UI -----------------
# Funnel Step Progress
st.write("Funnel Retention Progress")
metric_html = '<div class="funnel-container">'
for stage, count in pipeline_tracker.items():
    metric_html += f'<div class="funnel-step"><div class="funnel-label">{stage}</div><div class="funnel-value">{count}</div></div>'
metric_html += '</div>'
st.markdown(metric_html, unsafe_allow_html=True)

# Main Screener Results Table
st.write("Screener Output")

df_display = df_all.copy()

# Add placeholders for any missing columns and map calculated scores
for score_col, df_stage in [
    ("quality_score", df_s1),
    ("cap_alloc_score", df_s2),
    ("growth_score", df_s3),
    ("value_score", df_s4),
    ("momentum_score", df_s5),
    ("risk_score", df_s6)
]:
    if df_stage is not None and not df_stage.empty and score_col in df_stage.columns:
        mapping = df_stage.set_index("symbol")[score_col]
        df_display[score_col] = df_display["symbol"].map(mapping)
    else:
        df_display[score_col] = np.nan
        
def get_status(row):
    sym = row["symbol"]
    if sym in selected_symbols:
        return "Selected"
    if sym not in df_s0["symbol"].values:
        return "Stage 0 (Universe)"
    if sym not in df_s1["symbol"].values:
        return "Stage 1 (Integrity)"
    if sym not in df_s2["symbol"].values:
        return "Stage 2 (Quality)"
    if sym not in df_s3["symbol"].values:
        return "Stage 3 (Cap Alloc)"
    if sym not in df_s4["symbol"].values:
        return "Stage 4 (Growth)"
    if sym not in df_s5["symbol"].values:
        return "Stage 5 (Valuation)"
    if sym not in df_s6["symbol"].values:
        return "Stage 6 (Momentum)"
    return "Stage 7 (Risk Filter)"

df_display["Status"] = df_display.apply(get_status, axis=1)
df_display["is_selected"] = df_display["symbol"].apply(lambda x: 1 if x in selected_symbols else 0)
df_display = df_display.sort_values(by=["is_selected", "symbol"], ascending=[False, True]).drop(columns=["is_selected"])

cols_to_show = [
    "symbol", "Status", "price", "market_cap", "completeness",
    "piotroski", "beneish", "altman", "ohlson",
    "quality_score", "cap_alloc_score", "growth_score", "value_score", "momentum_score", "risk_score"
]
df_table = df_display[cols_to_show].copy()
df_table.columns = [
    "Ticker", "Screen Status", "Price", "Market Cap", "Data Complete %",
    "Piotroski F", "Beneish M", "Altman Z", "Ohlson Prob",
    "Quality Score", "Cap Alloc Score", "Growth Score", "Value Score", "Momentum Score", "Risk Score"
]

# Simple styled table (without colorful background gradients to maintain minimalist feel)
styled_df = df_table.style.format({
    "Price": "${:,.2f}",
    "Market Cap": lambda x: f"${x/1e9:.2f}B" if x >= 1e9 else f"${x/1e6:.2f}M",
    "Beneish M": "{:.2f}",
    "Altman Z": "{:.2f}",
    "Ohlson Prob": "{:.2%}",
    "Quality Score": "{:.1f}",
    "Cap Alloc Score": "{:.1f}",
    "Growth Score": "{:.1f}",
    "Value Score": "{:.1f}",
    "Momentum Score": "{:.1f}",
    "Risk Score": "{:.1f}"
})

st.dataframe(styled_df, use_container_width=True)

st.download_button(
    label="Export Full Screen Results to CSV",
    data=df_display.to_csv(index=False),
    file_name=f"screener_results_{datetime.date.today()}.csv",
    mime="text/csv",
    key="download_csv_btn"
)

st.write("")
st.write("")

# ----------------- TICKER DEEP DIVE PANEL -----------------
st.write("Ticker Deep-Dive")
default_idx = 0
if "search_query" in st.session_state and st.session_state.search_query in st.session_state.tickers:
    default_idx = st.session_state.tickers.index(st.session_state.search_query)
active_ticker = st.selectbox("Select Ticker for Detailed Audit:", options=st.session_state.tickers, index=default_idx, label_visibility="collapsed")

if active_ticker:
    ticker_data = raw_data.get(active_ticker, {})
    if "error" in ticker_data:
        st.error(f"Error loading {active_ticker}: {ticker_data['error']}")
    else:
        info = ticker_data.get("info", {})
        
        # Row with Name and Remove Button
        col_name, col_remove = st.columns([5, 1])
        with col_name:
            st.markdown(f"### {info.get('longName', active_ticker)} ({active_ticker})")
        with col_remove:
            if st.button("Remove from Screen", key=f"remove_{active_ticker}"):
                if active_ticker in st.session_state.tickers:
                    st.session_state.tickers.remove(active_ticker)
                    if "search_query" in st.session_state and st.session_state.search_query == active_ticker:
                        st.session_state.search_query = ""
                    st.rerun()
                    
        st.markdown(f"Sector: {info.get('sector')} | Industry: {info.get('industry')}")
        st.markdown(f"{info.get('longBusinessSummary')}")

        st.write("")
        
        tab_audit, tab_charts, tab_news = st.tabs(["Metric Audit Trail", "Charts", "Related News and Announcements"])
        
        with tab_audit:
            st.write("Detailed Calculations and Constraints")
            row_data = df_display[df_display["symbol"] == active_ticker].iloc[0]
            
            # Helper logic for coloring markdown values inside Audit Trail
            def c_text(val_str, is_good):
                return f":green[{val_str}]" if is_good else f":red[{val_str}]"
            
            def c_warn(val_str, is_good):
                return f":green[{val_str}]" if is_good else f":orange[{val_str}]"

            audit_cols = st.columns(3)
            with audit_cols[0]:
                st.markdown("**Financial Integrity Indicators**")
                
                # Piotroski F-Score (good if >= limit)
                p_val = row_data.get('piotroski')
                p_good = p_val >= piotroski_limit if p_val is not None else False
                st.markdown(f"Piotroski F-Score: {c_text(f'{p_val:.0f}/9', p_good) if p_val is not None else 'N/A'} (Limit: >= {piotroski_limit})")
                
                # Beneish M-Score (good if < limit)
                m_val = row_data.get('beneish')
                m_good = m_val < beneish_limit if m_val is not None else False
                st.markdown(f"Beneish M-Score: {c_text(f'{m_val:.2f}', m_good) if m_val is not None else 'N/A'} (Limit: < {beneish_limit})")
                
                # Altman Z-Score (good if > limit)
                z_val = row_data.get('altman')
                z_good = z_val > altman_limit if z_val is not None else False
                st.markdown(f"Altman Z-Score: {c_text(f'{z_val:.2f}', z_good) if z_val is not None else 'N/A'} (Limit: > {altman_limit})")
                
                # Ohlson Bankruptcy Probability (good if < limit)
                o_val = row_data.get('ohlson')
                o_good = o_val < ohlson_limit if o_val is not None else False
                st.markdown(f"Ohlson Bankruptcy Prob: {c_text(f'{o_val:.2%}', o_good) if o_val is not None else 'N/A'} (Limit: < {ohlson_limit:.2%})")
                
                # Dechow F-Score (good if < 1.0)
                d_val = row_data.get('dechow')
                d_good = d_val < 1.0 if d_val is not None else False
                st.markdown(f"Dechow F-Score: {c_warn(f'{d_val:.3f}', d_good) if d_val is not None else 'N/A'} (Threshold: < 1.0)")
                
                # Sloan Accrual Ratio (good if absolute value < 0.05)
                sl_val = row_data.get('sloan')
                sl_good = abs(sl_val) < 0.05 if sl_val is not None else False
                st.markdown(f"Sloan Accrual Ratio: {c_warn(f'{sl_val:.3%}', sl_good) if sl_val is not None else 'N/A'} (Threshold: +/-5%)")
                
            with audit_cols[1]:
                st.markdown("**Business Quality and Capital Alloc**")
                
                gp_val = row_data.get('gross_profitability')
                st.markdown(f"Gross Profitability: {c_warn(f'{gp_val:.2%}', gp_val > 0.33) if gp_val is not None else 'N/A'}")
                
                roic_val = row_data.get('roic')
                st.markdown(f"ROIC: {c_warn(f'{roic_val:.2%}', roic_val > 0.15) if roic_val is not None else 'N/A'}")
                
                croic_val = row_data.get('croic')
                st.markdown(f"CROIC: {c_warn(f'{croic_val:.2%}', croic_val > 0.15) if croic_val is not None else 'N/A'}")
                
                op_val = row_data.get('operating_margin')
                st.markdown(f"Operating Margin: {c_warn(f'{op_val:.2%}', op_val > 0.10) if op_val is not None else 'N/A'}")
                
                sy_val = row_data.get('shareholder_yield')
                st.markdown(f"Shareholder Yield: {c_warn(f'{sy_val:.2%}', sy_val > 0.03) if sy_val is not None else 'N/A'}")
                
                sc_val = row_data.get('share_count_trend')
                st.markdown(f"Share Count Trend (3-Yr): {c_warn(f'{sc_val:.2%}', sc_val <= 0.0) if sc_val is not None else 'N/A'}")
                
            with audit_cols[2]:
                st.markdown("**Growth, Valuation and Risk**")
                
                rev_cagr = row_data.get('revenue_cagr')
                st.markdown(f"Revenue 3-Yr CAGR: {c_warn(f'{rev_cagr:.2%}', rev_cagr > 0.08) if rev_cagr is not None else 'N/A'}")
                
                eps_cagr = row_data.get('eps_cagr')
                st.markdown(f"EPS 3-Yr CAGR: {c_warn(f'{eps_cagr:.2%}', eps_cagr > 0.08) if eps_cagr is not None else 'N/A'}")
                
                bf_yield = row_data.get('buffett_yield')
                st.markdown(f"Buffett Yield: {c_warn(f'{bf_yield:.2%}', bf_yield > 0.05) if bf_yield is not None else 'N/A'}")
                
                vol_val = row_data.get('volatility')
                st.markdown(f"Volatility (Annualized): {c_warn(f'{abs(vol_val):.2%}', abs(vol_val) < 0.25) if vol_val is not None else 'N/A'}")
                
                beta_val = row_data.get('beta')
                st.markdown(f"Beta (vs SPY): {c_warn(f'{abs(beta_val):.2f}', abs(beta_val) < 1.2) if beta_val is not None else 'N/A'}")
                
                skew_val = row_data.get('skew')
                st.markdown(f"Options Skew: {c_warn(f'{skew_val:.2f}', skew_val < 1.2) if skew_val is not None else 'N/A'}")
                
                own_val = row_data.get('ownership')
                st.markdown(f"Network Ownership Score: {c_warn(f'{own_val:.2f}', own_val > 0.6) if own_val is not None else 'N/A'}")


        with tab_charts:
            chart_cols = st.columns(2)
            
            with chart_cols[0]:
                history = ticker_data.get("history")
                if history is not None and not history.empty:
                    fig_price = go.Figure()
                    fig_price.add_trace(go.Scatter(x=history.index, y=history['Close'], name='Price', line=dict(color='#66fcf1', width=1.5)))
                    fig_price.update_layout(
                        title=f"{active_ticker} Price History (2 Year)",
                        template="plotly_dark",
                        xaxis_title="Date",
                        yaxis_title="Stock Price ($)",
                        margin=dict(l=20, r=20, t=40, b=20),
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)',
                    )
                    st.plotly_chart(fig_price, use_container_width=True)
                else:
                    st.info("Price history not available.")
                    
            with chart_cols[1]:
                fin = ticker_data.get("financials")
                if fin is not None and not fin.empty and len(fin.columns) > 0:
                    years = [str(col.date()) for col in fin.columns][::-1]
                    revs = [get_val(fin, ["Total Revenue", "Operating Revenue"], i) for i in range(len(fin.columns))][::-1]
                    nis = [get_val(fin, "Net Income", i) for i in range(len(fin.columns))][::-1]
                    
                    fig_fin = go.Figure()
                    fig_fin.add_trace(go.Bar(x=years, y=revs, name='Total Revenue', marker_color='#45a29e'))
                    fig_fin.add_trace(go.Bar(x=years, y=nis, name='Net Income', marker_color='#c5c6c7'))
                    fig_fin.update_layout(
                        title=f"{active_ticker} Historical Financials (Annual)",
                        template="plotly_dark",
                        barmode='group',
                        xaxis_title="Reporting Year",
                        yaxis_title="Value ($)",
                        margin=dict(l=20, r=20, t=40, b=20),
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)',
                    )
                    st.plotly_chart(fig_fin, use_container_width=True)
                else:
                    st.info("Financial statements history not available.")

        with tab_news:
            st.write("Latest News Headlines and Market Announcements")
            news_items = ticker_data.get("news", [])
            if news_items:
                for item in news_items[:8]:
                    title = "No Title Available"
                    publisher = "Unknown Publisher"
                    link = "#"
                    date_str = ""
                    
                    if "content" in item and isinstance(item["content"], dict):
                        c = item["content"]
                        title = c.get("title", title)
                        if "provider" in c and isinstance(c["provider"], dict):
                            publisher = c["provider"].get("displayName", publisher)
                        if "clickThroughUrl" in c and isinstance(c["clickThroughUrl"], dict):
                            link = c["clickThroughUrl"].get("url", link)
                        elif "canonicalUrl" in c and isinstance(c["canonicalUrl"], dict):
                            link = c["canonicalUrl"].get("url", link)
                        pub_date = c.get("pubDate")
                        if pub_date:
                            try:
                                dt = datetime.datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                                date_str = dt.strftime('%Y-%m-%d %H:%M')
                            except Exception:
                                date_str = str(pub_date)
                    else:
                        title = item.get("title", title)
                        publisher = item.get("publisher", publisher)
                        link = item.get("link", link)
                        pub_time = item.get("providerPublishTime")
                        if pub_time:
                            try:
                                date_str = datetime.datetime.fromtimestamp(pub_time).strftime('%Y-%m-%d %H:%M')
                            except Exception:
                                pass
                                
                    st.markdown(f"[{title}]({link})")
                    st.markdown(f"{publisher} | {date_str}")
                    st.markdown("---")
            else:
                st.info("No recent news or announcements found for this ticker.")

# ----------------- COLLAPSIBLE REFERENCE GUIDE -----------------
st.write("")
st.write("")
with st.expander("Reference Guide: Formulas and Calculations"):
    st.markdown("""
    ### Financial Integrity Ratios (Stage 1)
    
    #### Piotroski F-Score (9-Point Scale)
    A 9-point composite score evaluating fundamental strength. Meeting each criterion awards 1 point:
    - **Profitability**: Positive Net Income, positive Return on Assets (ROA), positive Cash Flow from Operations (CFO), and CFO > Net Income (Accruals check).
    - **Leverage/Liquidity**: Reduction in long-term debt to asset ratio, increase in current ratio, and no new shares issued (no dilution).
    - **Operating Efficiency**: Increase in gross margin and increase in asset turnover.
    
    #### Beneish M-Score (Earnings Manipulation Detector)
    A mathematical model using 8 financial ratios to flag potential accounting anomalies or earnings manipulation:
    - Limit: If the score is **>= -2.22**, the stock is flagged.
    - Variables analyzed: Days Sales in Receivables Index (DSRI), Gross Margin Index (GMI), Asset Quality Index (AQI), Sales Growth Index (SGI), Depreciation Index (DEPI), SG&A Expenses Index (SGAI), Leverage Index (LVGI), and Total Accruals to Total Assets (TATA).
    
    #### Altman Z-Score (Solvency Predictor)
    Measures corporate bankruptcy risk using a combination of five financial ratios:
    - Limit: A score of **<= 2.5** is grey/distress territory. Scores **> 2.5** indicate solid solvency health.
    - Variables: Working Capital/Total Assets, Retained Earnings/Total Assets, EBIT/Total Assets, Market Equity/Total Liabilities, and Sales/Total Assets.
    
    #### Ohlson O-Score (Bankruptcy Probability)
    A logistic model predicting the statistical probability of bankruptcy within two years:
    - Limit: A calculated probability of **>= 5%** is flagged as high risk.
    - Variables: Natural log of Total Assets, Total Liabilities/Total Assets, Working Capital/Total Assets, Current Liabilities/Current Assets, Net Income/Total Assets, CFO/Total Liabilities, recent net loss history, and leverage changes.
    
    #### Sloan Accrual Ratio
    Evaluates earnings quality by comparing net income with actual cash movements:
    - Formula: `(Net Income - Operating Cash Flow) / Total Assets`.
    - High positive values indicate a large share of profits are driven by non-cash accounting adjustments.
    
    ---
    
    ### Business Quality (Stage 2)
    - **Gross Profitability (Novy-Marx)**: `Gross Profit / Total Assets`. Captures pricing power and capital productivity.
    - **ROIC (Return on Invested Capital)**: `EBIT * (1 - Tax Rate) / Invested Capital`. Measures management's capital returns.
    - **CROIC (Cash Return on Invested Capital)**: `Free Cash Flow / Invested Capital`. Cash return equivalent of ROIC.
    - **Operating Margin**: `Operating Income / Total Revenue`.
    
    ---
    
    ### Capital Allocation (Stage 3)
    - **Shareholder Yield**: `(Dividends Paid + Share Repurchases) / Market Cap`. Calculates total cash returned to shareholders.
    - **Buyback Effectiveness**: Net share retirement rate relative to capital spent.
    - **Incremental ROIC**: `(EBIT_t - EBIT_t-2) / (InvestedCapital_t-1 - InvestedCapital_t-3)`. Returns on newly reinvested capital.
    
    ---
    
    ### Momentum & Volatility (Stages 6 & 7)
    - **Relative Strength**: Stock performance compared to the benchmark index (SPY).
    - **Volatility (Annualized)**: Daily price return variance scaled to 252 trading days.
    - **Beta**: Systemic market risk relative to SPY.
    - **Volatility Skew**: Implied Volatility ratio of OTM Put options (strike -10%) to OTM Call options (strike +10%). High skew indicates heavy downside hedging activity.
    - **Network Ownership Score**: Identifies diversified boutique manager conviction vs. crowded passive index fund holding structures.
    """)

