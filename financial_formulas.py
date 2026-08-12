import numpy as np
import pandas as pd
import os
import yfinance as yf
from scipy.stats import linregress

# Helper to resolve keys from yfinance DataFrames
def get_val(df, keys, col_idx=0):
    if df is None or not hasattr(df, "index") or len(df.columns) <= col_idx:
        return None
    col = df.columns[col_idx]
    if isinstance(keys, str):
        keys = [keys]
    for key in keys:
        if key in df.index:
            val = df.loc[key, col]
            if pd.notna(val):
                return float(val)
    # Case-insensitive & stripped fallback
    for key in keys:
        target = key.lower().strip()
        for idx_name in df.index:
            if idx_name.lower().strip() == target:
                val = df.loc[idx_name, col]
                if pd.notna(val):
                    return float(val)
    return None

def calc_piotroski_f_score(data: dict) -> dict:
    """
    Calculates the 9-point Piotroski F-Score.
    Returns a dict with the subscores and the total score.
    """
    fin = data.get("financials")
    bs = data.get("balance_sheet")
    cf = data.get("cashflow")
    
    score_details = {}
    total = 0
    
    try:
        # Check if we have at least 2 years of data
        if fin is None or bs is None or cf is None or len(fin.columns) < 2 or len(bs.columns) < 2 or len(cf.columns) < 2:
            return {"score": None, "details": "Insufficient historical statements"}
            
        # 1. Net Income > 0
        net_inc = get_val(fin, "Net Income", 0)
        score_details["net_income_positive"] = 1 if net_inc and net_inc > 0 else 0
        
        # 2. ROA > 0
        assets = get_val(bs, "Total Assets", 0)
        roa = (net_inc / assets) if net_inc and assets else 0
        score_details["roa_positive"] = 1 if roa > 0 else 0
        
        # 3. Cash Flow from Operations (CFO) > 0
        cfo = get_val(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"], 0)
        score_details["cfo_positive"] = 1 if cfo and cfo > 0 else 0
        
        # 4. Accruals (CFO > Net Income)
        score_details["accruals"] = 1 if cfo and net_inc and cfo > net_inc else 0
        
        # 5. Delta ROA > 0 (compared to last year)
        net_inc_prev = get_val(fin, "Net Income", 1)
        assets_prev = get_val(bs, "Total Assets", 1)
        roa_prev = (net_inc_prev / assets_prev) if net_inc_prev and assets_prev else 0
        score_details["delta_roa"] = 1 if roa > roa_prev else 0
        
        # 6. Delta Leverage < 0 (LT Debt / Avg Total Assets)
        lt_debt = get_val(bs, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"], 0) or 0.0
        lt_debt_prev = get_val(bs, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"], 1) or 0.0
        leverage = lt_debt / assets if assets else 0
        leverage_prev = lt_debt_prev / assets_prev if assets_prev else 0
        score_details["delta_leverage"] = 1 if leverage < leverage_prev else 0
        
        # 7. Delta Current Ratio > 0
        curr_assets = get_val(bs, "Current Assets", 0)
        curr_liab = get_val(bs, "Current Liabilities", 0)
        cr = (curr_assets / curr_liab) if curr_assets and curr_liab else 0
        
        curr_assets_prev = get_val(bs, "Current Assets", 1)
        curr_liab_prev = get_val(bs, "Current Liabilities", 1)
        cr_prev = (curr_assets_prev / curr_liab_prev) if curr_assets_prev and curr_liab_prev else 0
        score_details["delta_current_ratio"] = 1 if cr > cr_prev else 0
        
        # 8. No dilution (Shares did not increase)
        shares = get_val(fin, ["Basic Average Shares", "Diluted Average Shares"], 0)
        shares_prev = get_val(fin, ["Basic Average Shares", "Diluted Average Shares"], 1)
        score_details["no_dilution"] = 1 if shares and shares_prev and shares <= shares_prev else 0
        
        # 9. Delta Gross Margin > 0
        rev = get_val(fin, ["Total Revenue", "Operating Revenue"], 0)
        gp = get_val(fin, "Gross Profit", 0)
        if gp is None:
            cogs = get_val(fin, "Cost Of Revenue", 0) or 0.0
            gp = rev - cogs if rev else 0.0
        gm = (gp / rev) if gp and rev else 0
        
        rev_prev = get_val(fin, ["Total Revenue", "Operating Revenue"], 1)
        gp_prev = get_val(fin, "Gross Profit", 1)
        if gp_prev is None:
            cogs_prev = get_val(fin, "Cost Of Revenue", 1) or 0.0
            gp_prev = rev_prev - cogs_prev if rev_prev else 0.0
        gm_prev = (gp_prev / rev_prev) if gp_prev and rev_prev else 0
        score_details["delta_gross_margin"] = 1 if gm > gm_prev else 0
        
        total = sum(score_details.values())
        return {"score": total, "details": score_details}
    except Exception as e:
        return {"score": None, "details": f"Error calculating: {e}"}

def calc_beneish_m_score(data: dict) -> dict:
    """
    Beneish M-Score, 8-variable model. Above -1.78 is the usual manipulation flag.

    Two things were wrong in the earlier version of this function:

    1. Every missing input became 0.0, and each index then fell back to a neutral 1.0.
       That produced a confident-looking M-Score built on inputs that were never there.
       A missing term now makes the score None and names what was missing, so a company
       with gaps in its statements is visibly different from one that genuinely scores
       badly.
    2. TATA was computed from operating income. Beneish defines it on income from
       continuing operations, so net income is the right line. Net income was already
       being read into ni_t and then never used.
    """
    fin = data.get("financials")
    bs = data.get("balance_sheet")
    cf = data.get("cashflow")

    try:
        if (fin is None or bs is None or cf is None or len(fin.columns) < 2
                or len(bs.columns) < 2 or len(cf.columns) < 2):
            return {"score": None, "details": "Needs two years of statements"}

        # every one of these is required - no substitutes, no zeros
        need = {
            "revenue t":        get_val(fin, ["Total Revenue", "Operating Revenue"], 0),
            "revenue t-1":      get_val(fin, ["Total Revenue", "Operating Revenue"], 1),
            "COGS t":           get_val(fin, ["Cost Of Revenue", "Cost Of Goods Sold"], 0),
            "COGS t-1":         get_val(fin, ["Cost Of Revenue", "Cost Of Goods Sold"], 1),
            "receivables t":    get_val(bs, ["Accounts Receivable", "Receivables",
                                             "Net Receivables"], 0),
            "receivables t-1":  get_val(bs, ["Accounts Receivable", "Receivables",
                                             "Net Receivables"], 1),
            "assets t":         get_val(bs, "Total Assets", 0),
            "assets t-1":       get_val(bs, "Total Assets", 1),
            "current assets t":   get_val(bs, ["Current Assets", "Total Current Assets"], 0),
            "current assets t-1": get_val(bs, ["Current Assets", "Total Current Assets"], 1),
            "PPE t":            get_val(bs, ["Net PPE", "Property Plant And Equipment Net",
                                             "Properties"], 0),
            "PPE t-1":          get_val(bs, ["Net PPE", "Property Plant And Equipment Net",
                                             "Properties"], 1),
            "depreciation t":   get_val(cf, ["Depreciation Amortization Depletion",
                                             "Depreciation And Amortization",
                                             "Reconciled Depreciation"], 0),
            "depreciation t-1": get_val(cf, ["Depreciation Amortization Depletion",
                                             "Depreciation And Amortization",
                                             "Reconciled Depreciation"], 1),
            "SG&A t":           get_val(fin, ["Selling General And Administration",
                                              "Selling General And Administrative"], 0),
            "SG&A t-1":         get_val(fin, ["Selling General And Administration",
                                              "Selling General And Administrative"], 1),
            "CFO t":            get_val(cf, ["Operating Cash Flow",
                                             "Cash Flow From Continuing Operating Activities",
                                             "Total Cash From Operating Activities"], 0),
            "net income t":     get_val(fin, ["Net Income", "Net Income Common Stockholders",
                                              "Net Income From Continuing Operation Net "
                                              "Minority Interest"], 0),
        }
        # debt can legitimately be absent, so zero is a real answer for these four
        lt_debt_t = get_val(bs, ["Long Term Debt",
                                 "Long Term Debt And Capital Lease Obligation"], 0) or 0.0
        lt_debt_t1 = get_val(bs, ["Long Term Debt",
                                  "Long Term Debt And Capital Lease Obligation"], 1) or 0.0
        curr_debt_t = get_val(bs, ["Current Debt",
                                   "Current Debt And Capital Lease Obligation"], 0) or 0.0
        curr_debt_t1 = get_val(bs, ["Current Debt",
                                    "Current Debt And Capital Lease Obligation"], 1) or 0.0

        missing = [k for k, v in need.items() if v is None]
        coverage = round((len(need) - len(missing)) / len(need) * 100, 1)
        if missing:
            return {"score": None, "coverage": coverage,
                    "details": "Cannot be computed. Yahoo did not report: "
                               + ", ".join(missing)}

        rev_t, rev_t1 = need["revenue t"], need["revenue t-1"]
        cogs_t, cogs_t1 = need["COGS t"], need["COGS t-1"]
        rec_t, rec_t1 = need["receivables t"], need["receivables t-1"]
        at, at1 = need["assets t"], need["assets t-1"]
        ca_t, ca_t1 = need["current assets t"], need["current assets t-1"]
        ppe_t, ppe_t1 = need["PPE t"], need["PPE t-1"]
        dep_t, dep_t1 = need["depreciation t"], need["depreciation t-1"]
        sga_t, sga_t1 = need["SG&A t"], need["SG&A t-1"]
        cfo_t, ni_t = need["CFO t"], need["net income t"]

        def ratio(now, before, name):
            if before in (None, 0) or now is None:
                raise ZeroDivisionError(name)
            return now / before

        try:
            dsri = ratio(rec_t / rev_t, rec_t1 / rev_t1, "DSRI")
            gmi = ratio((rev_t1 - cogs_t1) / rev_t1, (rev_t - cogs_t) / rev_t, "GMI")
            aqi = ratio((at - ca_t - ppe_t) / at, (at1 - ca_t1 - ppe_t1) / at1, "AQI")
            sgi = ratio(rev_t, rev_t1, "SGI")
            depi = ratio(dep_t1 / (ppe_t1 + dep_t1), dep_t / (ppe_t + dep_t), "DEPI")
            sgai = ratio(sga_t / rev_t, sga_t1 / rev_t1, "SGAI")
            lvgi = ratio((lt_debt_t + curr_debt_t) / at,
                         (lt_debt_t1 + curr_debt_t1) / at1, "LVGI")
        except ZeroDivisionError as bad:
            return {"score": None, "coverage": coverage,
                    "details": f"{bad} cannot be formed - its denominator is zero, which "
                               f"usually means the company reports no receivables, no "
                               f"depreciation or no debt in one of the two years"}

        # TATA on net income, which is what Beneish specifies
        tata = (ni_t - cfo_t) / at

        m_score = (-4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi
                   + 0.115 * depi - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)

        return {"score": m_score, "coverage": coverage,
                "details": {"DSRI": dsri, "GMI": gmi, "AQI": aqi, "SGI": sgi,
                            "DEPI": depi, "SGAI": sgai, "LVGI": lvgi, "TATA": tata}}
    except Exception as e:
        return {"score": None, "details": f"Error: {e}"}


def calc_dechow_f_score(data: dict) -> dict:
    """
    Calculates Dechow F-Score (fraud probability ratio).
    """
    fin = data.get("financials")
    bs = data.get("balance_sheet")
    cf = data.get("cashflow")
    
    try:
        if fin is None or bs is None or cf is None or len(fin.columns) < 2 or len(bs.columns) < 2 or len(cf.columns) < 2:
            return {"score": None, "details": "Insufficient data"}
            
        assets_t = get_val(bs, "Total Assets", 0)
        assets_t1 = get_val(bs, "Total Assets", 1)
        avg_assets = 0.5 * (assets_t + assets_t1) if assets_t and assets_t1 else (assets_t or 1.0)
        
        # 1. RSST Accruals
        # NOA = Assets - Cash - Investments - TotalLiabilities
        cash_t = get_val(bs, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"], 0) or 0.0
        cash_t1 = get_val(bs, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"], 1) or 0.0
        
        liab_t = get_val(bs, ["Total Liabilities Net Minority Interest", "Total Liabilities"], 0) or 0.0
        liab_t1 = get_val(bs, ["Total Liabilities Net Minority Interest", "Total Liabilities"], 1) or 0.0
        
        noa_t = assets_t - cash_t - liab_t
        noa_t1 = assets_t1 - cash_t1 - liab_t1
        rsst_accr = (noa_t - noa_t1) / avg_assets if avg_assets else 0.0
        
        # 2. deltaAR
        ar_t = get_val(bs, ["Accounts Receivable", "Receivables"], 0) or 0.0
        ar_t1 = get_val(bs, ["Accounts Receivable", "Receivables"], 1) or 0.0
        delta_ar = (ar_t - ar_t1) / avg_assets if avg_assets else 0.0
        
        # 3. deltaINV
        inv_t = get_val(bs, "Inventory", 0) or 0.0
        inv_t1 = get_val(bs, "Inventory", 1) or 0.0
        delta_inv = (inv_t - inv_t1) / avg_assets if avg_assets else 0.0
        
        # 4. Soft Assets (%SFT)
        ppe_t = get_val(bs, ["Net PPE", "Properties"], 0) or 0.0
        sft = (assets_t - ppe_t - cash_t) / assets_t if assets_t else 0.0
        
        # 5. deltaCashSales
        rev_t = get_val(fin, ["Total Revenue", "Operating Revenue"], 0) or 0.0
        rev_t1 = get_val(fin, ["Total Revenue", "Operating Revenue"], 1) or 0.0
        cash_sales_t = rev_t - (ar_t - ar_t1)
        
        # Prev year AR change
        ar_t2 = get_val(bs, ["Accounts Receivable", "Receivables"], 2) or ar_t1
        cash_sales_t1 = rev_t1 - (ar_t1 - ar_t2)
        delta_cash_sales = (cash_sales_t - cash_sales_t1) / avg_assets if avg_assets else 0.0
        
        # 6. deltaROA
        ni_t = get_val(fin, "Net Income", 0) or 0.0
        ni_t1 = get_val(fin, "Net Income", 1) or 0.0
        roa_t = ni_t / assets_t if assets_t else 0.0
        roa_t1 = ni_t1 / assets_t1 if assets_t1 else 0.0
        delta_roa = roa_t - roa_t1
        
        # 7. Issue (debt/equity issuance indicator)
        iss_debt = get_val(cf, "Issuance Of Debt", 0) or 0.0
        iss_equity = get_val(cf, "Issuance Of Capital Stock", 0) or 0.0
        issue = 1 if (iss_debt > 0 or iss_equity > 0) else 0
        
        # Logit equation
        logit = (
            -7.893 
            + 0.790 * rsst_accr 
            + 2.518 * delta_ar 
            + 1.191 * delta_inv 
            + 1.979 * sft 
            + 0.171 * delta_cash_sales 
            - 0.932 * delta_roa 
            + 1.029 * issue
        )
        
        prob = np.exp(logit) / (1.0 + np.exp(logit))
        # F-score is probability divided by unconditional probability (0.0037)
        f_score = prob / 0.0037
        
        return {"score": f_score, "details": {"RSST": rsst_accr, "prob": prob}}
    except Exception as e:
        return {"score": None, "details": f"Error: {e}"}

def calc_altman_z_score(data: dict) -> dict:
    """
    Altman Z-Score, with the model chosen by sector.

    Three corrections to the earlier version:

    1. Market equity now comes from current shares outstanding. It previously used
       Basic Average Shares off the last annual statement, multiplied by today's price -
       a prior-year average share count against a current price. For any company that
       bought back or issued stock that misstates X4, which carries a 0.6 weight.
    2. Total liabilities no longer fall back to market equity when book equity is
       missing. Mixing a market number into a book calculation is simply wrong.
    3. The 1968 five-variable Z applies to public manufacturers. Everything else uses
       Z'' - four variables, book equity, no asset turnover. Banks, insurers and REITs
       get no score at all, because neither model carries meaning there.
    """
    fin = data.get("financials")
    bs = data.get("balance_sheet")
    info = data.get("info", {}) or {}

    try:
        if fin is None or bs is None:
            return {"score": None, "details": "No statements data"}

        sector = str(info.get("sector") or "").lower()
        industry = str(info.get("industry") or "").lower()
        if any(k in sector for k in ("financial",)) or \
           any(k in industry for k in ("bank", "insurance", "reit", "capital markets",
                                      "real estate")):
            return {"score": None, "model": "not applicable",
                    "details": f"Altman is not meaningful for {info.get('industry') or sector}. "
                               f"Both the Z and Z-double-prime models assume a non-financial "
                               f"balance sheet."}

        assets = get_val(bs, "Total Assets", 0)
        if not assets:
            return {"score": None, "details": "Missing Total Assets"}

        wc = get_val(bs, "Working Capital", 0)
        if wc is None:
            ca = get_val(bs, ["Current Assets", "Total Current Assets"], 0)
            cl = get_val(bs, ["Current Liabilities", "Total Current Liabilities"], 0)
            wc = (ca - cl) if (ca is not None and cl is not None) else None

        retained = get_val(bs, "Retained Earnings", 0)
        ebit = get_val(fin, ["EBIT", "Operating Income",
                             "Total Operating Income As Reported"], 0)
        liab = get_val(bs, ["Total Liabilities Net Minority Interest", "Total Liabilities"], 0)
        if not liab:
            equity_book = get_val(bs, ["Stockholders Equity", "Common Stock Equity",
                                       "Total Equity Gross Minority Interest"], 0)
            liab = (assets - equity_book) if equity_book is not None else None
        equity_book = get_val(bs, ["Stockholders Equity", "Common Stock Equity",
                                   "Total Equity Gross Minority Interest"], 0)
        sales = get_val(fin, ["Total Revenue", "Operating Revenue"], 0)

        # current shares first, statement average only as a last resort
        price = info.get("currentPrice") or info.get("regularMarketPrice") \
            or info.get("previousClose")
        shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding") \
            or get_val(bs, ["Share Issued", "Ordinary Shares Number"], 0) \
            or get_val(fin, ["Basic Average Shares", "Diluted Average Shares"], 0)
        mkt_equity = (price * shares) if (price and shares) else None

        # manufacturers keep the original five-variable model
        MANUFACTURING = ("industrials", "basic materials", "technology", "energy",
                         "consumer cyclical", "healthcare", "consumer defensive")
        is_mfg = any(k in sector for k in MANUFACTURING)

        x1 = wc / assets if wc is not None else None
        x2 = retained / assets if retained is not None else None
        x3 = ebit / assets if ebit is not None else None

        if is_mfg:
            x4 = (mkt_equity / liab) if (mkt_equity is not None and liab) else None
            x5 = (sales / assets) if sales is not None else None
            terms = [(1.2, x1, "X1"), (1.4, x2, "X2"), (3.3, x3, "X3"),
                     (0.6, x4, "X4"), (0.999, x5, "X5")]
            model = "Z (1968 public manufacturing)"
        else:
            x4 = (equity_book / liab) if (equity_book is not None and liab) else None
            terms = [(6.56, x1, "X1"), (3.26, x2, "X2"), (6.72, x3, "X3"), (1.05, x4, "X4")]
            model = "Z'' (non-manufacturing, book equity)"

        gaps = [name for _, v, name in terms if v is None]
        if gaps:
            return {"score": None, "model": model,
                    "details": f"Cannot be computed. Missing: {', '.join(gaps)}"}

        z = sum(w * v for w, v, _ in terms)
        band = "distress" if z < 1.8 else ("grey zone" if z < 3.0 else "safe")
        return {"score": z, "model": model, "band": band,
                "details": {name: v for _, v, name in terms}}
    except Exception as e:
        return {"score": None, "details": f"Error: {e}"}


def calc_ohlson_o_score(data: dict) -> dict:
    """
    Calculates Ohlson O-Score and returns probability of bankruptcy.
    """
    fin = data.get("financials")
    bs = data.get("balance_sheet")
    cf = data.get("cashflow")
    
    try:
        if fin is None or bs is None or cf is None or len(fin.columns) < 2 or len(bs.columns) < 2:
            return {"score": None, "details": "Insufficient data"}
            
        assets_t = get_val(bs, "Total Assets", 0)
        assets_t1 = get_val(bs, "Total Assets", 1)
        if not assets_t or not assets_t1:
            return {"score": None, "details": "Missing Assets"}
            
        # SIZE = log(Total Assets / CPI) or similar. Standard is ln(Total Assets / 1e3) (if scale is in thousands, so raw Total Assets / 1e6)
        # Using ln(Total Assets in millions)
        size = np.log(assets_t / 1e6)
        
        liab_t = get_val(bs, ["Total Liabilities Net Minority Interest", "Total Liabilities"], 0) or 0.0
        tlta = liab_t / assets_t
        
        curr_assets_t = get_val(bs, "Current Assets", 0) or 0.0
        curr_liab_t = get_val(bs, "Current Liabilities", 0) or 0.0
        wc_t = curr_assets_t - curr_liab_t
        wcta = wc_t / assets_t
        
        clca = curr_liab_t / curr_assets_t if curr_assets_t else 0.0
        
        ni_t = get_val(fin, "Net Income", 0) or 0.0
        nita = ni_t / assets_t
        
        cfo_t = get_val(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"], 0) or 0.0
        futl = cfo_t / liab_t if liab_t else 0.0
        
        # INTWO: 1 if Net Income negative for last 2 years, 0 otherwise
        ni_t1 = get_val(fin, "Net Income", 1) or 0.0
        intwo = 1 if (ni_t < 0 and ni_t1 < 0) else 0
        
        # OENEG: 1 if Liabilities > Assets
        oeneg = 1 if liab_t > assets_t else 0
        
        # CHIN
        chin = (ni_t - ni_t1) / (abs(ni_t) + abs(ni_t1)) if (abs(ni_t) + abs(ni_t1)) else 0.0
        
        o_score = -1.32 - 0.407*size + 6.03*tlta - 1.43*wcta + 0.076*clca - 2.37*nita - 1.83*futl + 0.285*intwo - 1.72*oeneg - 0.521*chin
        prob = 1.0 / (1.0 + np.exp(-o_score))
        
        return {"score": prob, "details": {"O-Score": o_score, "prob": prob}}
    except Exception as e:
        return {"score": None, "details": f"Error: {e}"}

def calc_sloan_accrual_ratio(data: dict) -> dict:
    """
    Calculates Sloan Accrual Ratio.
    Sloan = (Net Income - Cash Flow from Operations) / Total Assets
    """
    fin = data.get("financials")
    bs = data.get("balance_sheet")
    cf = data.get("cashflow")
    
    try:
        if fin is None or bs is None or cf is None:
            return {"score": None, "details": "No data"}
            
        ni = get_val(fin, "Net Income", 0) or 0.0
        cfo = get_val(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"], 0) or 0.0
        assets = get_val(bs, "Total Assets", 0)
        
        if not assets:
            return {"score": None, "details": "Missing Assets"}
            
        ratio = (ni - cfo) / assets
        return {"score": ratio, "details": f"NI: {ni}, CFO: {cfo}, Assets: {assets}"}
    except Exception as e:
        return {"score": None, "details": f"Error: {e}"}

def calc_quality_score(data: dict) -> dict:
    """
    Calculates raw metrics for Quality (Stage 2).
    """
    fin = data.get("financials")
    bs = data.get("balance_sheet")
    cf = data.get("cashflow")
    
    metrics = {}
    try:
        # 1. Gross Profitability (Novy-Marx)
        rev = get_val(fin, ["Total Revenue", "Operating Revenue"], 0) or 1.0
        gp = get_val(fin, "Gross Profit", 0)
        if gp is None:
            gp = rev - (get_val(fin, "Cost Of Revenue", 0) or 0.0)
        assets = get_val(bs, "Total Assets", 0) or 1.0
        metrics["gross_profitability"] = gp / assets
        
        # 2. ROIC
        ebit = get_val(fin, ["EBIT", "Operating Income"], 0) or 0.0
        tax = get_val(fin, "Tax Provision", 0) or 0.0
        pretax = get_val(fin, "Pretax Income", 0) or 1.0
        tax_rate = max(0.0, min(0.5, tax / pretax)) if pretax else 0.21
        
        lt_debt = get_val(bs, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"], 0) or 0.0
        curr_debt = get_val(bs, ["Current Debt", "Current Debt And Capital Lease Obligation"], 0) or 0.0
        equity = get_val(bs, ["Common Stock Equity", "Stockholders Equity"], 0) or 0.0
        cash = get_val(bs, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"], 0) or 0.0
        invested_cap = lt_debt + curr_debt + equity - cash
        if invested_cap <= 0:
            invested_cap = assets - cash if assets > cash else 1.0
            
        nopat = ebit * (1 - tax_rate)
        metrics["roic"] = nopat / invested_cap
        
        # 3. CROIC
        fcf = get_val(cf, "Free Cash Flow", 0)
        if fcf is None:
            cfo = get_val(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"], 0) or 0.0
            capex = get_val(cf, "Capital Expenditure", 0) or 0.0
            fcf = cfo + capex # Capex is negative, so adding subtracts it
        metrics["croic"] = fcf / invested_cap
        
        # 4. ROE
        ni = get_val(fin, "Net Income", 0) or 0.0
        metrics["roe"] = ni / equity if equity else 0.0
        
        # 5. Operating Margin
        metrics["operating_margin"] = ebit / rev
        
        # 6. Cash Conversion (OCF / Net Income)
        cfo = get_val(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"], 0) or 0.0
        metrics["cash_conversion"] = cfo / abs(ni) if ni else (1.0 if cfo > 0 else 0.0)
        
        # Composite indicator
        metrics["qmj_profitability"] = (metrics["gross_profitability"] + metrics["roic"] + metrics["operating_margin"]) / 3.0
        
    except Exception as e:
        # Put default/empty if it fails
        pass
        
    return metrics

def calc_capital_allocation_score(data: dict) -> dict:
    """
    Calculates raw metrics for Capital Allocation (Stage 3).
    """
    fin = data.get("financials")
    bs = data.get("balance_sheet")
    cf = data.get("cashflow")
    info = data.get("info", {})
    
    metrics = {}
    try:
        mkt_cap = info.get("marketCap") or 1e9
        
        # 1. Shareholder Yield = (Dividends + Buybacks) / Market Cap
        div_paid = abs(get_val(cf, ["Common Stock Dividend Paid", "Cash Dividends Paid"], 0) or 0.0)
        buybacks = abs(get_val(cf, ["Repurchase Of Capital Stock", "Common Stock Payments"], 0) or 0.0)
        metrics["shareholder_yield"] = (div_paid + buybacks) / mkt_cap
        
        # 2. Buyback Effectiveness: Net buyback divided by market cap (simple approximation)
        metrics["buyback_effectiveness"] = buybacks / mkt_cap
        
        # 3. Incremental ROIC (2-year delta)
        # (EBIT_t - EBIT_t-2) / (InvestedCap_t-1 - InvestedCap_t-3)
        if fin is not None and len(fin.columns) >= 3 and bs is not None and len(bs.columns) >= 4:
            ebit_t = get_val(fin, ["EBIT", "Operating Income"], 0) or 0.0
            ebit_t2 = get_val(fin, ["EBIT", "Operating Income"], 2) or 0.0
            
            def get_ic(idx):
                lt = get_val(bs, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"], idx) or 0.0
                cu = get_val(bs, ["Current Debt", "Current Debt And Capital Lease Obligation"], idx) or 0.0
                eq = get_val(bs, ["Common Stock Equity", "Stockholders Equity"], idx) or 0.0
                ca = get_val(bs, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"], idx) or 0.0
                ic = lt + cu + eq - ca
                return ic if ic > 0 else 1.0
                
            ic_t1 = get_ic(1)
            ic_t3 = get_ic(3)
            
            delta_ebit = ebit_t - ebit_t2
            delta_ic = ic_t1 - ic_t3
            metrics["incremental_roic"] = delta_ebit / delta_ic if delta_ic else 0.0
        else:
            # Fallback to ROIC
            metrics["incremental_roic"] = get_val(fin, ["EBIT", "Operating Income"], 0) / mkt_cap if mkt_cap else 0.0
            
        # 4. FCF Conversion = FCF / Net Income
        ni = get_val(fin, "Net Income", 0) or 0.0
        fcf = get_val(cf, "Free Cash Flow", 0)
        if fcf is None:
            cfo = get_val(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"], 0) or 0.0
            capex = get_val(cf, "Capital Expenditure", 0) or 0.0
            fcf = cfo + capex
        metrics["fcf_conversion"] = fcf / abs(ni) if ni else 1.0
        
        # 5. Share Count Trend: 3-year growth (reverse it later: lower is better)
        shares_t = get_val(fin, ["Basic Average Shares", "Diluted Average Shares"], 0)
        shares_t3 = get_val(fin, ["Basic Average Shares", "Diluted Average Shares"], min(3, len(fin.columns)-1) if fin is not None else 0)
        metrics["share_count_trend"] = (shares_t - shares_t3) / shares_t3 if (shares_t and shares_t3 and shares_t3 > 0) else 0.0
        
    except Exception:
        pass
        
    return metrics

def calc_growth_score(data: dict) -> dict:
    """
    Calculates raw growth metrics (Stage 4).
    """
    fin = data.get("financials")
    bs = data.get("balance_sheet")
    cf = data.get("cashflow")
    
    metrics = {}
    try:
        # Calculate 3-year CAGR for Revenue, EPS, FCF, Book Value
        def get_cagr(df, keys, length=3):
            if df is None or len(df.columns) < length + 1:
                return 0.0
            val_t = get_val(df, keys, 0)
            val_prev = get_val(df, keys, min(length, len(df.columns)-1))
            if val_t and val_prev and val_prev > 0 and val_t > 0:
                return (val_t / val_prev) ** (1.0 / length) - 1.0
            elif val_t and val_prev:
                # Return standard change if negative base
                return (val_t - val_prev) / abs(val_prev) if val_prev else 0.0
            return 0.0
            
        metrics["revenue_cagr"] = get_cagr(fin, ["Total Revenue", "Operating Revenue"])
        metrics["eps_cagr"] = get_cagr(fin, ["Diluted EPS", "Basic EPS"])
        metrics["fcf_cagr"] = get_cagr(cf, "Free Cash Flow")
        metrics["book_value_cagr"] = get_cagr(bs, ["Common Stock Equity", "Stockholders Equity"])
        
        # Earnings Revision Trend: Fallback to trailing growth
        metrics["earnings_revision_trend"] = get_val(data.get("info", {}), "earningsQuarterlyGrowth", 0) or 0.0
        
    except Exception:
        pass
        
    return metrics

def calc_valuation_score(data: dict) -> dict:
    """
    Calculates raw valuation metrics (Stage 5).
    Note: cheap values are ranked higher.
    """
    fin = data.get("financials")
    bs = data.get("balance_sheet")
    cf = data.get("cashflow")
    info = data.get("info", {})
    
    metrics = {}
    try:
        price = info.get("currentPrice") or info.get("previousClose") or 1.0
        shares = info.get("sharesOutstanding") or get_val(fin, ["Basic Average Shares", "Diluted Average Shares"], 0) or 1.0
        mkt_cap = price * shares
        
        # EV = Market Cap + Debt - Cash
        lt_debt = get_val(bs, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"], 0) or 0.0
        curr_debt = get_val(bs, ["Current Debt", "Current Debt And Capital Lease Obligation"], 0) or 0.0
        cash = get_val(bs, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"], 0) or 0.0
        ev = mkt_cap + lt_debt + curr_debt - cash
        if ev <= 0:
            ev = mkt_cap
            
        ebit = get_val(fin, ["EBIT", "Operating Income"], 0) or 0.0
        fcf = get_val(cf, "Free Cash Flow", 0)
        if fcf is None:
            cfo = get_val(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"], 0) or 0.0
            capex = get_val(cf, "Capital Expenditure", 0) or 0.0
            fcf = cfo + capex
            
        # 1. Greenblatt Earnings Yield = EBIT / EV
        metrics["earnings_yield"] = ebit / ev if ev else 0.0
        
        # 2. Acquirer's Multiple = EV / EBIT (lower is better, we store negative to rank higher)
        metrics["acquirers_multiple"] = - (ev / ebit) if ebit else -100.0
        
        # 3. EV/EBIT (we store negative to rank higher)
        metrics["ev_ebit"] = - (ev / ebit) if ebit else -100.0
        
        # 4. EV/FCF (we store negative to rank higher)
        metrics["ev_fcf"] = - (ev / fcf) if fcf else -100.0
        
        # 5. Buffett Yield = FCF / EV
        metrics["buffett_yield"] = fcf / ev if ev else 0.0
        
        # 6. Shareholder Yield
        div_paid = abs(get_val(cf, ["Common Stock Dividend Paid", "Cash Dividends Paid"], 0) or 0.0)
        buybacks = abs(get_val(cf, ["Repurchase Of Capital Stock", "Common Stock Payments"], 0) or 0.0)
        metrics["shareholder_yield"] = (div_paid + buybacks) / mkt_cap
        
        # Magic Formula rank will combine earnings_yield and roic (calculated in quality)
        
    except Exception:
        pass
        
    return metrics

def calc_momentum_and_risk(history: pd.DataFrame, spy_history: pd.DataFrame) -> dict:
    """
    Calculates momentum (Stage 6) and Risk (Stage 7) metrics from price series.
    """
    metrics = {}
    if history is None or history.empty or len(history) < 30:
        return metrics
        
    try:
        # Prepare daily returns
        prices = history["Close"].dropna()
        daily_returns = prices.pct_change().dropna()
        
        current_price = prices.iloc[-1]
        
        # Moving Averages
        sma_200 = prices.rolling(window=min(200, len(prices))).mean().iloc[-1]
        sma_100 = prices.rolling(window=min(100, len(prices))).mean().iloc[-1]
        sma_50 = prices.rolling(window=min(50, len(prices))).mean().iloc[-1]
        sma_20 = prices.rolling(window=min(20, len(prices))).mean().iloc[-1]
        
        # 1. Price > 200 SMA
        metrics["price_above_200sma"] = (current_price / sma_200) - 1.0 if sma_200 else 0.0
        
        # 2. Dual Momentum & Relative Strength (against self & spy)
        ret_12m = (current_price / prices.iloc[-min(252, len(prices))]) - 1.0 if len(prices) >= 252 else 0.0
        ret_6m = (current_price / prices.iloc[-min(126, len(prices))]) - 1.0 if len(prices) >= 126 else 0.0
        ret_3m = (current_price / prices.iloc[-min(63, len(prices))]) - 1.0 if len(prices) >= 63 else 0.0
        
        # Residual Momentum: 12m return excluding the last month (21 trading days)
        if len(prices) >= 252:
            metrics["residual_momentum"] = (prices.iloc[-21] / prices.iloc[-252]) - 1.0
        else:
            metrics["residual_momentum"] = ret_6m
            
        metrics["relative_strength"] = (ret_12m + ret_6m + ret_3m) / 3.0
        
        # Trend Composite: slope and slope sign of SMA lines
        trend = 0
        if sma_20 > prices.rolling(window=min(20, len(prices))).mean().iloc[-min(5, len(prices))]: trend += 1
        if sma_50 > prices.rolling(window=min(50, len(prices))).mean().iloc[-min(5, len(prices))]: trend += 1
        if sma_100 > prices.rolling(window=min(100, len(prices))).mean().iloc[-min(5, len(prices))]: trend += 1
        if sma_200 > prices.rolling(window=min(200, len(prices))).mean().iloc[-min(5, len(prices))]: trend += 1
        metrics["trend_composite"] = trend / 4.0
        
        # RISK METRICS (Stage 7)
        # 1. Low Volatility: Annualized Standard Deviation (lower is better, we store negative to rank higher)
        vol = daily_returns.std() * np.sqrt(252)
        metrics["volatility"] = -vol
        
        # 2. Maximum Drawdown (lower is better, store negative)
        roll_max = prices.cummax()
        drawdowns = (prices - roll_max) / roll_max
        metrics["max_drawdown"] = drawdowns.min() # This is negative, e.g. -0.25 (lower is more risk, so we just store it directly)
        
        # Calculate Beta metrics against SPY if available
        if spy_history is not None and not spy_history.empty:
            spy_prices = spy_history["Close"].dropna()
            spy_returns = spy_prices.pct_change().dropna()
            
            # Align indices
            aligned = pd.concat([daily_returns, spy_returns], axis=1, join="inner").dropna()
            aligned.columns = ["stock", "spy"]
            
            if len(aligned) > 20:
                cov = np.cov(aligned["stock"], aligned["spy"])
                beta = cov[0, 1] / cov[1, 1] if cov[1, 1] else 1.0
                metrics["beta"] = -abs(beta) # Store negative absolute beta (lower systemic risk is better)
                
                # Downside Beta: Beta on days when SPY was negative
                down_aligned = aligned[aligned["spy"] < 0]
                if len(down_aligned) > 5:
                    down_cov = np.cov(down_aligned["stock"], down_aligned["spy"])
                    down_beta = down_cov[0, 1] / down_cov[1, 1] if down_cov[1, 1] else 1.0
                    metrics["downside_beta"] = -down_beta
                else:
                    metrics["downside_beta"] = -beta
                    
                # Idiosyncratic Volatility: Standard deviation of residuals from regression
                slope, intercept, r_val, p_val, std_err = linregress(aligned["spy"], aligned["stock"])
                residuals = aligned["stock"] - (slope * aligned["spy"] + intercept)
                metrics["idiosyncratic_vol"] = -residuals.std() * np.sqrt(252)
            else:
                metrics["beta"] = -1.0
                metrics["downside_beta"] = -1.0
                metrics["idiosyncratic_vol"] = -vol
        else:
            metrics["beta"] = -1.0
            metrics["downside_beta"] = -1.0
            metrics["idiosyncratic_vol"] = -vol
            
    except Exception as e:
        print(f"Error calculating momentum/risk: {e}")
        
    return metrics

def calc_options_skew(options_data: dict, current_price: float) -> float:
    """
    Computes option implied volatility skew from the option chain data.
    Skew = OTM Put IV (strike -10%) / OTM Call IV (strike +10%)
    """
    if not options_data or "calls" not in options_data or "puts" not in options_data:
        return 1.0
        
    calls = options_data["calls"]
    puts = options_data["puts"]
    
    if calls.empty or puts.empty:
        return 1.0
        
    try:
        # Find call near strike = current_price * 1.10
        target_call_strike = current_price * 1.10
        target_put_strike = current_price * 0.90
        
        # Closest strike indices
        call_idx = (calls["strike"] - target_call_strike).abs().idxmin()
        put_idx = (puts["strike"] - target_put_strike).abs().idxmin()
        
        call_iv = calls.loc[call_idx, "impliedVolatility"]
        put_iv = puts.loc[put_idx, "impliedVolatility"]
        
        if call_iv and put_iv and call_iv > 0:
            return float(put_iv / call_iv)
    except Exception:
        pass
    return 1.0

def calc_network_ownership_score(inst_holders, all_inst_portfolios: dict) -> float:
    """
    Calculates ownership score. If we have institutional holders, 
    we measure similarity with other portfolios to assess crowdedness.
    - Diversified Conviction: 1 - Mean Jaccard Similarity to all other stocks in universe
    """
    if inst_holders is None or inst_holders.empty or "Holder" not in inst_holders.columns:
        return 0.5
        
    try:
        current_holders = set(inst_holders["Holder"].tolist())
        if not current_holders:
            return 0.5
            
        similarities = []
        for symbol, other_holders in all_inst_portfolios.items():
            if not other_holders:
                continue
            intersection = len(current_holders.intersection(other_holders))
            union = len(current_holders.union(other_holders))
            jaccard = intersection / union if union else 0.0
            similarities.append(jaccard)
            
        if similarities:
            # 1 minus mean similarity: high score means low crowdedness (diversified active boutique interest)
            return float(1.0 - np.mean(similarities))
    except Exception:
        pass
    return 0.5
