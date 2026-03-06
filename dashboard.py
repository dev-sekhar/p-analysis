import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
import numpy as np
import contextlib, io
from datetime import date

st.set_page_config(page_title="Portfolio Dashboard", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
/* Spacing overrides */
.block-container { padding: 2.5rem 1.5rem 1.5rem !important; }
h1 { font-size: 1.8rem !important; margin-bottom: 0.8rem !important; padding-top: 0.2rem !important; line-height: 1.2 !important; }
h2, h3 { font-size: 1.1rem !important; margin: 0.8rem 0 0.4rem !important; }
[data-testid="stMetric"] { padding: 0.5rem !important; }
[data-testid="stMetricValue"] { font-size: 1.4rem !important; }
[data-testid="stMetricLabel"] { font-size: 0.9rem !important; }
/* Big drop zone */
[data-testid="stFileUploaderDropzone"] {
    min-height: 90px !important; padding: 1rem !important;
    border: 2px dashed #4a90d9 !important; border-radius: 10px !important;
    background: #f0f7ff !important; cursor: pointer !important;
    transition: background .2s !important;
}
[data-testid="stFileUploaderDropzone"]:hover { background: #dceeff !important; }
[data-testid="stFileUploaderDropzoneInput"] { min-height: 90px !important; }
/* Tabs compact */
.stTabs [data-baseweb="tab"] { font-size: 0.82rem !important; padding: 4px 10px !important; }
div[data-testid="stDataFrame"] { margin-bottom: 2rem !important; }
</style>
""", unsafe_allow_html=True)

# ── HELPERS ───────────────────────────────────────────────────────────────────

def find_col(df, *candidates):
    lm = {c.lower(): c for c in df.columns}
    for n in candidates:
        if n in df.columns: return n
        if n.lower() in lm: return lm[n.lower()]
    return None

def safe_sum(df, col):
    return float(df[col].fillna(0).sum()) if col and col in df.columns else 0.0

def clean_num(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(
                df[c].astype(str).str.replace(",","").str.replace("₹","").str.strip(),
                errors="coerce")
    return df

import json
import os

MAP_FILE = "ticker_map.json"

def load_map():
    if os.path.exists(MAP_FILE):
        try: return json.load(open(MAP_FILE))
        except: pass
    return {}

def save_map(m):
    with open(MAP_FILE, "w") as f:
        json.dump(m, f, indent=2)

SYM_MAP = load_map()

def ns(sym): 
    s = str(sym).upper().strip()
    if s in SYM_MAP: return SYM_MAP[s]
    return s if s.endswith((".NS",".BO")) else s + ".NS"

def bucket(d): 
    return "< 1yr" if d < 365 else ("1–3yr" if d < 1095 else "> 3yr")

@st.cache_data(ttl=3600, show_spinner=False)
def get_hist(ticker, start, end):
    """Fetch OHLCV history from yfinance, silencing stderr noise for missing/delisted tickers."""
    try:
        _buf = io.StringIO()
        with contextlib.redirect_stderr(_buf):
            h = yf.download(ticker, start=start, end=end,
                            progress=False, auto_adjust=True)
        if h.empty: return pd.DataFrame()
        if isinstance(h.columns, pd.MultiIndex): h.columns = h.columns.get_level_values(0)
        h.index = pd.to_datetime(h.index)
        return h
    except Exception: return pd.DataFrame()

def idx_ret(start, end, ticker):
    h = get_hist(ticker, start, end)
    if h.empty or "Close" not in h.columns or len(h) < 2: return None
    f, l = float(h["Close"].iloc[0]), float(h["Close"].iloc[-1])
    return (l - f) / f * 100 if f else None

@st.cache_data(ttl=86400, show_spinner=False)
def verify_ticker(sym):
    import urllib.request
    try:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status == 200
    except: return False

@st.cache_data(ttl=86400, show_spinner=False)
def search_yahoo(cname):
    import urllib.request, json, urllib.parse
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(str(cname))}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
            for q in data.get('quotes', []):
                if q.get('exchange') in ['NSI', 'BSE'] and q.get('symbol'):
                    return q['symbol']
    except: pass
    return None

@st.cache_data(ttl=86400, show_spinner=False)

def fetch_india_cpi() -> dict:
    """Fetch annual India CPI inflation (%) from World Bank API. Returns {year: pct}."""
    try:
        import urllib.request, json
        url = ("https://api.worldbank.org/v2/country/IN/indicator/FP.CPI.TOTL.ZG"
               "?format=json&per_page=20&mrv=15")
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read())
        return {int(item["date"]): float(item["value"])
                for item in data[1] if item.get("value") is not None}
    except Exception:
        return {}   # caller will use a fallback rate

def cumulative_inflation(start_d, end_d, annual_rates: dict, fallback: float) -> float:
    """Return cumulative inflation % between two dates using annual CPI rates."""
    cum = 1.0
    for yr in range(start_d.year, end_d.year + 1):
        rate = annual_rates.get(yr, fallback) / 100
        if start_d.year == end_d.year:
            frac = (end_d - start_d).days / 365
        elif yr == start_d.year:
            frac = (date(yr + 1, 1, 1) - start_d).days / 365
        elif yr == end_d.year:
            frac = (end_d - date(yr, 1, 1)).days / 365
        else:
            frac = 1.0
        cum *= (1 + rate) ** frac
    return (cum - 1) * 100

# ── SIDEBAR ───────────────────────────────────────────────────────────────────

IDX = {"NIFTY 50 (^NSEI)":"^NSEI","NIFTY 500 (^CRSLDX)":"^CRSLDX","SENSEX (^BSESN)":"^BSESN"}
with st.sidebar:
    st.header("⚙️ Settings")
    il = st.selectbox("Benchmark", list(IDX))
    it = IDX[il]; ish = il.split("(")[0].strip()
    st.divider()

    with st.expander("🔄 Ticker Corrections (Fix missing downloads)"):
        st.write("Map broker symbols to Yahoo Finance symbols (e.g. `BRASOL` → `BRASAN.NS` or `.BO` for BSE).")
        st.caption("Press Enter to save a cell. Empty cells are ignored.")
        
        map_df = pd.DataFrame(list(SYM_MAP.items()), columns=["Broker Symbol (e.g. HINCOP)", "Yahoo Symbol (e.g. HINDCOPPER.NS)"])
        # Add 3 empty rows so user can easily add new mappings
        map_df = pd.concat([map_df, pd.DataFrame([["",""]]*3, columns=map_df.columns)], ignore_index=True)
        
        edited_df = st.data_editor(map_df, num_rows="dynamic", use_container_width=True)
        
        if st.button("Save Symbol Mapping"):
            new_map = {}
            for _, row in edited_df.iterrows():
                b = str(row.iloc[0]).strip().upper()
                y = str(row.iloc[1]).strip().upper()
                if b and y: new_map[b] = y
            save_map(new_map)
            # clear fetch cache so missing symbols get downloaded again
            get_hist.clear()
            st.rerun()

    st.divider()
    with st.expander("📖 Definitions"):
        st.markdown("""
**Nominal Return %**  
Simple total return: `(Market Value − Cost) / Cost × 100`

**Real Return %**  
Inflation-adjusted return: `((1 + Nominal) / (1 + Inflation) − 1) × 100`  
Tells you the true purchasing-power gain after stripping out price-level changes.

**CAGR %** (Compound Annual Growth Rate)  
`((1 + Nominal/100)^(365/days) − 1) × 100`  
Annualises the total return so you can compare stocks held for different periods on equal terms.

**Alpha %**  
`Stock Return % − Index Return %` for the *same* holding period.  
Positive → stock outperformed the benchmark; negative → underperformed.

**Index Return %**  
Total return of the selected benchmark (NIFTY 50 / NIFTY 500 / SENSEX) from the stock’s first purchase date to today, fetched from Yahoo Finance.

**Peak Return %**  
The *maximum achievable* return had you sold at the highest closing price since purchase.  
`(Highest Close − Avg Cost per Share) / Avg Cost per Share × 100`  
⚠️ Requires Yahoo Finance (yfinance) to find the stock using its NSE symbol (e.g. RELIANCE.NS).  
Shows **N/A** when: the symbol is not on NSE, or the ticker format used in your CSV doesn’t match Yahoo Finance’s NSE listing.

**Inflation (period) %**  
Cumulative price-level rise over the holding period, using India CPI data from the World Bank API, applied year-by-year.

**Holding Bucket**  
Groups stocks by age: `< 1yr` / `1–3yr` / `> 3yr`.
        """)

TODAY = date.today().strftime("%Y-%m-%d")

# ── UPLOADERS ─────────────────────────────────────────────────────────────────

st.title("Portfolio Dashboard")
uc1, uc2 = st.columns(2)
with uc1: summary_file = st.file_uploader("📂 Summary CSV", type="csv")
with uc2: all_file     = st.file_uploader("📂 Transactions CSV", type="csv")

# ── LOAD ──────────────────────────────────────────────────────────────────────

df = tx = None
cs = cn = cq = cc = cm = cp = cpp = None
td = ts = tt = tq = tpr = None

if summary_file:
    df = clean_num(pd.read_csv(summary_file),
                   ["Qty","Value At Cost","Value At Market Price",
                    "Unrealized Profit Loss","Unrealized ProfitLoss %"])
    cs  = find_col(df,"Stock Symbol","Symbol","Ticker","Scrip","Scrip Name",
                   "Script","Script Name","NSE Symbol","BSE Symbol","Trading Symbol","Instrument")
    cn  = find_col(df,"Company Name","Name","Stock Name","Company")
    cq  = find_col(df,"Qty","Quantity","Shares","No. of Shares")
    cc  = find_col(df,"Value At Cost","Cost Value","Cost","Investment Value","Avg Cost","Buy Value")
    cm  = find_col(df,"Value At Market Price","Market Value","Current Value","Present Value","LTP Value")
    cp  = find_col(df,"Unrealized Profit Loss","Unrealized Profit/Loss",
                   "P/L","Profit Loss","P&L","Gain/Loss","Unrealised P&L")
    cpp = find_col(df,"Unrealized ProfitLoss %","Unrealised ProfitLoss %",
                   "Unrealized Profit/Loss %","Unrealised Profit/Loss %",
                   "P/L %","Return %","Gain %","P&L %",
                   "Net chg.","% Chg","% Change","Chg %",
                   "Gain/Loss %","ROI %","PnL %","Unrealized P&L %")
    # Force-convert all detected numeric columns
    # Handles: "15.3%", "(5.3)" (broker parenthesis negatives), "₹1,00,000"
    def _to_num(s):
        s = str(s).strip().replace("%","").replace("₹","").replace(",","")
        if s.startswith("(") and s.endswith(")"):   # (5.3) → -5.3
            s = "-" + s[1:-1]
        try:    return float(s)
        except: return float("nan")
    for _c in [cq, cc, cm, cp, cpp]:
        if _c and _c in df.columns:
            df[_c] = df[_c].apply(_to_num)

if all_file:
    try:
        tx  = pd.read_csv(all_file)
        td  = find_col(tx,"Date","Trade Date","Transaction Date","Order Date","Settlement Date")
        ts  = find_col(tx,"Stock Symbol","Symbol","Ticker","Scrip","Scrip Name",
                       "Instrument","Trading Symbol","NSE Symbol","Script","Script Name")
        tt  = find_col(tx,"Type","Action","Trade Type","Order Type","Trade","Transaction Type","B/S")
        tq  = find_col(tx,"Qty","Quantity","Shares","Volume","No. of Shares")
        tpr = find_col(tx,"Price","Trade Price","Rate","Cost Price","Avg Price","Average Price","LTP")
        if td: tx[td] = pd.to_datetime(tx[td], errors="coerce", dayfirst=True)
        for c in [tq, tpr]:
            if c: tx[c] = pd.to_numeric(tx[c].astype(str).str.replace(",","").str.replace("₹",""), errors="coerce")
        if ts: tx[ts] = tx[ts].astype(str).str.upper().str.strip()
    except Exception as e:
        st.error(f"Transactions CSV error: {e}"); tx = None

# ── SIDEBAR: COLUMN MAPPING (shown after CSVs are loaded) ─────────────────────

_NA = "— not mapped —"

with st.sidebar:
    st.divider()
    with st.expander("🗂️ Column Mapping", expanded=(df is not None and not all([cs,cm,cpp]))):
        st.caption("Auto-detected from your CSVs. Edit any field to override.")

        if df is not None:
            sum_opts = [_NA] + list(df.columns)
            def _si(v): return sum_opts.index(v) if v in sum_opts else 0

            st.markdown("**📂 Summary CSV**")
            cs  = st.selectbox("Symbol",         sum_opts, index=_si(cs),  key="m_cs")
            cn  = st.selectbox("Company Name",   sum_opts, index=_si(cn),  key="m_cn")
            cq  = st.selectbox("Quantity",       sum_opts, index=_si(cq),  key="m_cq")
            cc  = st.selectbox("Cost Value (₹)", sum_opts, index=_si(cc),  key="m_cc")
            cm  = st.selectbox("Market Value (₹)",sum_opts,index=_si(cm),  key="m_cm")
            cp  = st.selectbox("P/L Absolute",   sum_opts, index=_si(cp),  key="m_cp")
            cpp = st.selectbox("P/L %",          sum_opts, index=_si(cpp), key="m_cpp")
            cs  = None if cs  == _NA else cs
            cn  = None if cn  == _NA else cn
            cq  = None if cq  == _NA else cq
            cc  = None if cc  == _NA else cc
            cm  = None if cm  == _NA else cm
            cp  = None if cp  == _NA else cp
            cpp = None if cpp == _NA else cpp
            # Re-apply numeric coercion on any user-selected columns
            for _c in [cq, cc, cm, cp, cpp]:
                if _c and _c in df.columns and df[_c].dtype == object:
                    df[_c] = df[_c].apply(_to_num)
            st.json({"symbol": cs, "company_name": cn, "quantity": cq,
                     "cost_value": cc, "market_value": cm,
                     "pl_absolute": cp, "pl_pct": cpp})

        if tx is not None:
            tx_opts = [_NA] + list(tx.columns)
            def _ti(v): return tx_opts.index(v) if v in tx_opts else 0

            st.markdown("**📂 Transactions CSV**")
            td  = st.selectbox("Date",           tx_opts, index=_ti(td),  key="m_td")
            ts  = st.selectbox("Symbol",         tx_opts, index=_ti(ts),  key="m_ts")
            tt  = st.selectbox("Type (BUY/SELL)",tx_opts, index=_ti(tt),  key="m_tt")
            tq  = st.selectbox("Quantity",       tx_opts, index=_ti(tq),  key="m_tq")
            tpr = st.selectbox("Price",          tx_opts, index=_ti(tpr), key="m_tpr")
            td  = None if td  == _NA else td
            ts  = None if ts  == _NA else ts
            tt  = None if tt  == _NA else tt
            tq  = None if tq  == _NA else tq
            tpr = None if tpr == _NA else tpr
            # Re-parse date & numeric if mapping changed
            if td and tx[td].dtype == object:
                tx[td] = pd.to_datetime(tx[td], errors="coerce", dayfirst=True)
            if ts: tx[ts] = tx[ts].astype(str).str.upper().str.strip()
            for _c in [tq, tpr]:
                if _c and _c in tx.columns and tx[_c].dtype == object:
                    tx[_c] = pd.to_numeric(tx[_c].astype(str).str.replace(",","").str.replace("₹",""), errors="coerce")
            st.json({"date": td, "symbol": ts, "type": tt,
                     "quantity": tq, "price": tpr})

# ── AUTO-MAP MISSING TICKERS ──────────────────────────────────────────────────

if df is not None and cs and cn:
    unmapped = [s for s in df[cs].dropna().unique() if str(s).upper().strip() not in SYM_MAP]
    if unmapped:
        changes = 0
        pb = st.progress(0, text="Verifying missing symbols...")
        for i, s in enumerate(unmapped):
            n_s = ns(s)
            if not verify_ticker(n_s):
                cname = df[df[cs] == s][cn].iloc[0]
                pb.progress((i+1)/len(unmapped), text=f"Auto-mapping '{s}' ({cname}) via Yahoo...")
                found = search_yahoo(cname)
                if found:
                    SYM_MAP[str(s).upper().strip()] = found
                    changes += 1
            else:
                # the standard .NS fallback works fine
                pb.progress((i+1)/len(unmapped), text=f"Auto-mapping '{s}'...")
                
        pb.empty()
        if changes > 0:
            save_map(SYM_MAP)
            get_hist.clear()
            st.rerun()

# ── TABS ──────────────────────────────────────────────────────────────────────

if df is None and tx is None:
    st.info("👆 Upload CSVs above to start. Summary CSV is required for most sections.")
    st.stop()

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Overview", "🕐 Aging Returns", "📊 Stock vs Index", "📅 Buy Heatmap", "🌡️ Perf Heatmap", "📈 Growth"
])


# ══════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════
with tab1:
    if df is None:
        st.info("Upload Summary CSV to see portfolio overview.")
    else:
        c1,c2,c3,c4 = st.columns(4)
        pl = safe_sum(df, cp)
        with c1: st.metric("Total Cost",    f"₹{safe_sum(df,cc):,.0f}" if cc else "N/A")
        with c2: st.metric("Market Value",  f"₹{safe_sum(df,cm):,.0f}" if cm else "N/A")
        with c3: st.metric("P/L",           f"₹{pl:,.0f}", delta=f"₹{pl:,.0f}")
        with c4: st.metric("Holdings",      len(df))

        left, right = st.columns([1, 1])

        # Gainers / Losers table
        with left:
            if cpp and cs:
                valid = df.dropna(subset=[cpp])
                gcols = [c for c in [cs, cn, cpp] if c]
                st.markdown("**🚀 Top Gainers**")
                st.dataframe(valid.nlargest(5, cpp)[gcols], hide_index=True, use_container_width=True)
                st.markdown("**📉 Top Losers**")
                st.dataframe(valid.nsmallest(5, cpp)[gcols], hide_index=True, use_container_width=True)

        # Pie chart: slice = % contribution to total portfolio by market value
        with right:
            if cm and cs and df[cm].notna().any():
                # Keep original index so pl_vals lookup stays correctly aligned
                chart_df = df[[cs, cm]].dropna().copy()
                total_mkt = chart_df[cm].sum()
                chart_df["_contrib"] = chart_df[cm] / total_mkt * 100   # % of total portfolio

                if cpp and cpp in df.columns:
                    pl_vals = df.loc[chart_df.index, cpp]
                    def pick_color(pct):
                        if pd.isna(pct): return "#d0d0d0"
                        if pct > 0:
                            intensity = min(pct / 50, 1)
                            g = int(120 + 135 * intensity)
                            return f"rgb(30,{g},60)"
                        elif pct < 0:
                            intensity = min(abs(pct) / 50, 1)
                            r = int(150 + 105 * intensity)
                            return f"rgb({r},40,40)"
                        return "#d0d0d0"
                    colors    = pl_vals.apply(pick_color).tolist()
                    pl_labels = pl_vals.tolist()
                else:
                    colors    = px.colors.sequential.Blues_r[:len(chart_df)]
                    pl_labels = [None] * len(chart_df)

                # Custom hover: Stock | ₹ value | % of portfolio | P/L%
                custom = [[f"₹{row[cm]:,.0f}",
                           f"{row['_contrib']:.1f}% of portfolio",
                           f"P/L: {pl_labels[i]:+.2f}%" if pl_labels[i] is not None and not pd.isna(pl_labels[i]) else ""]
                          for i, (_, row) in enumerate(chart_df.iterrows())]

                fig = go.Figure(go.Pie(
                    labels=chart_df[cs],
                    values=chart_df["_contrib"],   # size = % contribution
                    customdata=custom,
                    hole=0.42,
                    marker_colors=colors,
                    texttemplate="%{label}<br>%{value:.1f}%",
                    textposition="inside",
                    textfont_size=9,
                    hovertemplate=(
                        "<b>%{label}</b><br>"
                        "%{customdata[0]}<br>"
                        "<b>%{customdata[1]}</b><br>"
                        "%{customdata[2]}"
                        "<extra></extra>"
                    ),
                ))
                fig.update_layout(
                    showlegend=False,
                    margin=dict(t=10, b=5, l=5, r=5),
                    height=320,
                    annotations=[dict(
                        text=f"₹{total_mkt:,.0f}<br><span style='font-size:10px'>Total</span>",
                        x=0.5, y=0.5, showarrow=False, font_size=13, align="center"
                    )]
                )
                st.markdown("**🥧 Portfolio Allocation** — slice = % contribution to total market value · colour = P/L%")
                st.plotly_chart(fig, use_container_width=True)


        # Holdings table
        show_cols = [c for c in [cs, cn, cq, cpp] if c]
        st.markdown("<br>**📋 All Holdings**", unsafe_allow_html=True)
        st.dataframe(df[show_cols] if show_cols else df, use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════
# TAB 2 — AGING RETURNS (inflation-adjusted real returns)
# ══════════════════════════════════════════════════════════════
with tab2:
    if df is None or tx is None or not ts or not td:
        st.info("Upload both CSVs to unlock. Needs Symbol & Date in Transactions CSV.")
    else:
        # ── Inflation control ──
        cpi_data = fetch_india_cpi()
        latest_cpi_yr  = max(cpi_data) if cpi_data else None
        latest_cpi_val = cpi_data[latest_cpi_yr] if cpi_data else 6.0
        use_hist = st.checkbox(
            f"Use historical India CPI year-by-year (World Bank data, latest {latest_cpi_yr}: {latest_cpi_val:.1f}%)",
            value=bool(cpi_data), help="Unchecked = use the flat rate below for all years")
        inf_rate = st.number_input(
            "Annual inflation rate % (used when historical CPI is off, or as fallback)",
            min_value=0.1, max_value=30.0,
            value=round(latest_cpi_val, 1), step=0.1, format="%.1f")

        tw = tx.dropna(subset=[td, ts]).copy()
        if tt:
            mask = tw[tt].astype(str).str.upper().str.contains("BUY|PURCHASE", regex=True, na=False)
            if mask.any(): tw = tw[mask]
        first_buys = tw.groupby(ts)[td].min()

        rows_age = []
        for _, row in df.iterrows():
            sym = str(row[cs]).upper().strip() if cs else None
            if not sym or sym not in first_buys.index: continue
            fb = first_buys[sym]
            if pd.isna(fb): continue
            hdays = (date.today() - fb.date()).days
            if hdays <= 0: continue
            cv = float(row[cc]) if cc and pd.notna(row.get(cc)) else None
            mv = float(row[cm]) if cm and pd.notna(row.get(cm)) else None
            sret = (mv - cv) / cv * 100 if cv and mv and cv > 0 else None
            cagr = None
            if sret is not None:
                try: cagr = ((1 + sret/100)**(365/hdays) - 1)*100
                except: pass
            # Inflation for holding period
            inf_pct = cumulative_inflation(
                fb.date(), date.today(),
                cpi_data if use_hist else {},
                inf_rate
            )
            real_ret = None
            if sret is not None:
                try: real_ret = ((1 + sret/100) / (1 + inf_pct/100) - 1) * 100
                except: pass
            rows_age.append({
                "Stock": sym,
                "First Buy": fb.strftime("%d %b %Y"),
                "Holding": f"{hdays}d / {hdays//365}yr {(hdays%365)//30}mo",
                "Nominal Return %": round(sret, 2)    if sret     is not None else None,
                "CAGR %":           round(cagr, 2)    if cagr     is not None else None,
                "Inflation (period) %": round(inf_pct, 2),
                "Real Return %":    round(real_ret, 2) if real_ret is not None else None,
            })

        if rows_age:
            age_df = pd.DataFrame(rows_age)
            def _col(v):
                if not isinstance(v, (int, float)): return ""
                return "color:#27ae60;font-weight:bold" if v >= 0 else "color:#e74c3c;font-weight:bold"
            styled_age = age_df.style.applymap(_col,
                subset=[c for c in ["Nominal Return %","Real Return %","CAGR %"] if c in age_df.columns])
            st.markdown("**⏳ Aging Returns (Inflation-adjusted)**")
            st.dataframe(styled_age, use_container_width=True, hide_index=True)

            st.markdown("<br>", unsafe_allow_html=True)
            # Bar chart: nominal vs real return per stock
            plot_df = age_df.dropna(subset=["Nominal Return %","Real Return %"])[["Stock","Nominal Return %","Real Return %"]]
            plot_melt = plot_df.melt(id_vars="Stock", var_name="Type", value_name="Return %")
            fig_age = px.bar(plot_melt, x="Stock", y="Return %", color="Type", barmode="group",
                             color_discrete_map={"Nominal Return %":"#2980b9","Real Return %":"#e67e22"},
                             title="Nominal vs Real (inflation-adjusted) Return per Stock")
            fig_age.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
            fig_age.update_layout(margin=dict(t=40,b=20), height=300, legend_title="")
            st.plotly_chart(fig_age, use_container_width=True)
        else:
            st.warning("Could not match symbols between Summary and Transactions CSVs.")

# ══════════════════════════════════════════════════════════════
# TAB 3 — STOCK vs INDEX (since purchase date)
# ══════════════════════════════════════════════════════════════
with tab3:
    if df is None or tx is None or not ts or not td:
        st.info("Upload both CSVs to unlock. Needs Symbol & Date in Transactions CSV.")
    else:
        with st.spinner(f"Comparing stock returns vs {ish} since each purchase date…"):
            tw2 = tx.dropna(subset=[td, ts]).copy()
            if tt:
                mask2 = tw2[tt].astype(str).str.upper().str.contains("BUY|PURCHASE", regex=True, na=False)
                if mask2.any(): tw2 = tw2[mask2]
            first_buys2 = tw2.groupby(ts)[td].min()

            rows_idx = []
            for _, row in df.iterrows():
                sym = str(row[cs]).upper().strip() if cs else None
                if not sym or sym not in first_buys2.index: continue
                fb = first_buys2[sym]
                if pd.isna(fb): continue
                hdays = (date.today() - fb.date()).days
                if hdays <= 0: continue
                cv = float(row[cc]) if cc and pd.notna(row.get(cc)) else None
                mv = float(row[cm]) if cm and pd.notna(row.get(cm)) else None
                qv = float(row[cq]) if cq and pd.notna(row.get(cq)) else None
                sret = (mv - cv) / cv * 100 if cv and mv and cv > 0 else None
                ss   = fb.strftime("%Y-%m-%d")
                ir   = idx_ret(ss, TODAY, it)
                alpha = sret - ir if sret is not None and ir is not None else None
                # Peak price since buy
                pr = pdt = None
                try:
                    h = get_hist(ns(sym), ss, TODAY)
                    if not h.empty and "Close" in h.columns and cv and qv and qv > 0:
                        cps = cv / qv
                        pr  = (float(h["Close"].max()) - cps) / cps * 100
                        pdt = h["Close"].idxmax().strftime("%d %b %Y")
                except: pass
                rows_idx.append({
                    "Stock":         sym,
                    "Bought":        fb.strftime("%d %b %Y"),
                    "Days Held":     hdays,
                    "Bucket":        bucket(hdays),
                    "Stock Return %": round(sret,2) if sret is not None else None,
                    f"{ish} Return %": round(ir,2)  if ir   is not None else None,
                    "Alpha %":       round(alpha,2) if alpha is not None else None,
                    "Peak Return %": round(pr,2)    if pr   is not None else None,
                    "Peak Date":     pdt,
                })

        if rows_idx:
            idx_df = pd.DataFrame(rows_idx)
            def _col2(v):
                if not isinstance(v, (int, float)): return ""
                return "color:#27ae60;font-weight:bold" if v >= 0 else "color:#e74c3c;font-weight:bold"
            scols = [c for c in ["Stock Return %", f"{ish} Return %", "Alpha %"] if c in idx_df.columns]
            st.markdown(f"**📊 Stock Returns vs {ish} (Since Purchase)**")
            st.dataframe(idx_df.style.applymap(_col2, subset=scols),
                         use_container_width=True, hide_index=True)

            st.markdown("<br>", unsafe_allow_html=True)
            c_left, c_right = st.columns(2)
            with c_left:
                # Grouped bar: stock return vs index return per stock
                bar_df = idx_df.dropna(subset=["Stock Return %", f"{ish} Return %"])[
                    ["Stock", "Stock Return %", f"{ish} Return %"]]
                bar_melt = bar_df.melt(id_vars="Stock", var_name="Type", value_name="Return %")
                fig_bar = px.bar(bar_melt, x="Stock", y="Return %", color="Type", barmode="group",
                                 color_discrete_map={"Stock Return %":"#2980b9", f"{ish} Return %":"#e67e22"},
                                 title=f"Stock vs {ish} Return Since Purchase")
                fig_bar.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.4)
                fig_bar.update_layout(margin=dict(t=40,b=10), height=300, legend_title="")
                st.plotly_chart(fig_bar, use_container_width=True)
            with c_right:
                # Alpha by holding bucket
                bdf2 = idx_df.dropna(subset=["Alpha %"]).groupby("Bucket")["Alpha %"].mean().reset_index()
                bdf2["Bucket"] = pd.Categorical(bdf2["Bucket"],["< 1yr","1–3yr","> 3yr"],ordered=True)
                fig_b2 = px.bar(bdf2.sort_values("Bucket"), x="Bucket", y="Alpha %",
                                color="Alpha %", color_continuous_scale=["#e74c3c","#f5f5f5","#27ae60"],
                                text_auto=".1f", title=f"Avg Alpha vs {ish} by Holding Period")
                fig_b2.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.4)
                fig_b2.update_layout(coloraxis_showscale=False, margin=dict(t=40,b=10), height=300)
                st.plotly_chart(fig_b2, use_container_width=True)
        else:
            st.warning("Could not match symbols between Summary and Transactions CSVs.")

# ══════════════════════════════════════════════════════════════
# TAB 4 — BUY TIMELINE HEATMAP
# ══════════════════════════════════════════════════════════════
with tab4:
    if tx is None or not td:
        st.info("Upload Transactions CSV with a Date column.")
    else:
        bh = tx.dropna(subset=[td]).copy()
        if tt:
            m = bh[tt].astype(str).str.upper().str.contains("BUY|PURCHASE", regex=True, na=False)
            if m.any(): bh = bh[m]
        bh["Year"]  = bh[td].dt.year.astype(str)
        bh["Month"] = bh[td].dt.month
        heat = bh.groupby(["Year","Month"]).size().reset_index(name="Count")
        piv  = heat.pivot(index="Year", columns="Month", values="Count").fillna(0)
        mnames = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        piv.columns = [mnames[m-1] for m in piv.columns]
        piv = piv.reindex(columns=mnames, fill_value=0)

        # Build stock-name matrix for tooltip (one string per cell)
        if ts:
            sym_grp = bh.groupby(["Year","Month"])[ts].apply(
                lambda x: "<br>".join(sorted(set(x.dropna().astype(str))))
            ).reset_index(name="Stocks")
            sym_piv = sym_grp.pivot(index="Year", columns="Month", values="Stocks").fillna("")
            sym_piv.columns = [mnames[m-1] for m in sym_piv.columns]
            sym_piv = sym_piv.reindex(index=piv.index, columns=mnames, fill_value="")
            customdata = sym_piv.values.tolist()
            htmpl = ("<b>%{y} – %{x}</b><br>"
                     "Trades: <b>%{z}</b><br><br>"
                     "Stocks bought:<br>%{customdata}<extra></extra>")
        else:
            customdata = None
            htmpl = "<b>%{y} – %{x}</b><br>Trades: <b>%{z}</b><extra></extra>"

        # ── Decide metric: amount invested (Qty×Price) or count fallback ──
        has_amount = tq and tpr and tq in bh.columns and tpr in bh.columns
        if has_amount:
            bh["_amt"] = pd.to_numeric(bh[tq], errors="coerce") * pd.to_numeric(bh[tpr], errors="coerce")
            amt_grp    = bh.groupby(["Year","Month"])["_amt"].sum().reset_index(name="Amount")
            amt_piv    = amt_grp.pivot(index="Year", columns="Month", values="Amount").fillna(0)
            amt_piv.columns = [mnames[m-1] for m in amt_piv.columns]
            amt_piv    = amt_piv.reindex(columns=mnames, fill_value=0)
            z_data     = amt_piv.values
            z_text     = [[f"₹{amt_piv.values[i,j]/1e5:.1f}L" if amt_piv.values[i,j]>0 else ""
                           for j in range(12)] for i in range(len(amt_piv))]
            cb_title   = "Invested (₹)"
            chart_title = "Amount Invested per Month (₹)  |  colour = ₹ deployed"
            amt_fmt    = True
        else:
            z_data     = piv.values
            z_text     = piv.values.astype(int)
            cb_title   = "Trades"
            chart_title = "Purchase Frequency — Month × Year  |  colour = # trades"
            amt_fmt    = False

        # ── Tooltip: stocks bought per cell ──
        if ts:
            sym_grp = bh.groupby(["Year","Month"])[ts].apply(
                lambda x: "<br>".join(sorted(set(x.dropna().astype(str))))
            ).reset_index(name="Stocks")
            sym_piv = sym_grp.pivot(index="Year", columns="Month", values="Stocks").fillna("")
            sym_piv.columns = [mnames[m-1] for m in sym_piv.columns]
            sym_piv = sym_piv.reindex(index=piv.index, columns=mnames, fill_value="")
            customdata = sym_piv.values.tolist()
            if amt_fmt:
                htmpl = ("<b>%{y} – %{x}</b><br>"
                         "Invested: <b>₹%{z:,.0f}</b><br><br>"
                         "Stocks bought:<br>%{customdata}<extra></extra>")
            else:
                htmpl = ("<b>%{y} – %{x}</b><br>"
                         "Trades: <b>%{z}</b><br><br>"
                         "Stocks bought:<br>%{customdata}<extra></extra>")
        else:
            customdata = None
            htmpl = ("<b>%{y} – %{x}</b><br>Invested: <b>₹%{z:,.0f}</b><extra></extra>"
                     if amt_fmt else
                     "<b>%{y} – %{x}</b><br>Trades: <b>%{z}</b><extra></extra>")

        fig_h = go.Figure(go.Heatmap(
            z=z_data, x=piv.columns.tolist(), y=piv.index.tolist(),
            colorscale="Blues",
            text=z_text, texttemplate="%{text}", showscale=True,
            colorbar=dict(title=cb_title), xgap=2, ygap=2,
            customdata=customdata, hovertemplate=htmpl,
        ))
        fig_h.update_layout(title=chart_title,
                            xaxis_title="Month", yaxis_title="Year",
                            margin=dict(t=45,b=20), height=350)
        st.plotly_chart(fig_h, use_container_width=True)
        if not has_amount:
            st.caption("⚠️ Price column not detected in Transactions CSV — showing trade count instead of ₹ invested.")

        with st.expander("🗒️ Raw transactions"):
            st.dataframe(tx.sort_values(td, ascending=False) if td else tx,
                         use_container_width=True, height=180)

# ══════════════════════════════════════════════════════════════
# TAB 5 — PERFORMANCE HEATMAP
# ══════════════════════════════════════════════════════════════
with tab5:
    if df is None:
        st.info("Upload Summary CSV to see the performance heatmap.")
    else:
        # ── Manual column override when auto-detect fails ──
        all_cols    = list(df.columns)
        str_cols    = [c for c in all_cols if df[c].dtype == object]
        num_cols    = [c for c in all_cols if pd.api.types.is_numeric_dtype(df[c])]

        with st.expander("🔎 Column mapping", expanded=(not cpp or not cs)):
            st.caption(f"Auto-detected → Symbol: `{cs}` | P/L %: `{cpp}`")
            if not cs or not cpp:
                st.warning("Auto-detection failed. Select the correct columns below:")
            col_a, col_b = st.columns(2)
            with col_a:
                sym_opts = ["— auto —"] + all_cols
                sym_sel  = st.selectbox("Symbol column", sym_opts,
                                        index=sym_opts.index(cs) if cs in sym_opts else 0,
                                        key="ph_sym")
            with col_b:
                pl_opts  = ["— auto —"] + all_cols
                pl_sel   = st.selectbox("P/L % column", pl_opts,
                                        index=pl_opts.index(cpp) if cpp in pl_opts else 0,
                                        key="ph_pl")
            _cs  = (sym_sel if sym_sel != "— auto —" else cs)  or next((c for c in str_cols), None)
            _cpp = (pl_sel  if pl_sel  != "— auto —" else cpp) or next((c for c in num_cols), None)

        if _cs and _cpp:
            perf = df[[_cs, _cpp]].dropna().sort_values(_cpp, ascending=False).reset_index(drop=True)
            N = 8
            stocks = perf[_cs].tolist(); vals = perf[_cpp].tolist()
            pad = (-len(stocks)) % N
            stocks += [""]*pad; vals += [None]*pad
            nr = len(stocks)//N
            z    = [[vals[i*N+j] for j in range(N)] for i in range(nr)]
            def _fmt(sym, v):
                if not sym or v is None: return ""
                try:    return f"{sym}\n{float(v):+.1f}%"
                except: return str(sym)
            text = [[_fmt(stocks[i*N+j], vals[i*N+j]) for j in range(N)] for i in range(nr)]
            ma = max((abs(v) for v in vals if v is not None), default=1)
            fig_p = go.Figure(go.Heatmap(
                z=z, text=text, texttemplate="%{text}", textfont=dict(size=9),
                colorscale=[[0,"#c0392b"],[0.5,"#f5f5f5"],[1,"#27ae60"]],
                zmin=-ma, zmax=ma, showscale=True,
                colorbar=dict(title="P/L %"), xgap=3, ygap=3,
            ))
            fig_p.update_layout(
                title=f"Stock Performance — {_cpp} (green=gain, red=loss)",
                xaxis=dict(showticklabels=False), yaxis=dict(showticklabels=False),
                margin=dict(t=40,b=10,l=10,r=10), height=max(200, nr*80),
            )
            st.plotly_chart(fig_p, use_container_width=True)
        else:
            st.error("Cannot render heatmap — no usable columns found in Summary CSV.")

# ══════════════════════════════════════════════════════════════
# TAB 6 — PORTFOLIO GROWTH OVER TIME
# ══════════════════════════════════════════════════════════════
with tab6:
    # Price column is not needed — we fetch closing prices from yfinance instead
    missing = [n for n,c in [("Symbol",ts),("Date",td),("Qty",tq)] if not c]
    if tx is None or missing:
        st.info(f"Upload Transactions CSV. Missing columns: **{', '.join(missing)}**")
        if tx is not None:
            with st.expander("🔎 Detected Transactions CSV columns"):
                st.write(list(tx.columns))
                st.write(f"Symbol→`{ts}` | Date→`{td}` | Qty→`{tq}` | Type→`{tt}`")
    else:
        with st.spinner("Reconstructing portfolio value from transaction history…"):
            tw2 = tx.dropna(subset=[td, ts, tq]).copy().sort_values(td)
            tw2["signed"] = np.where(
                tw2[tt].astype(str).str.upper().str.contains("SELL", na=False) if tt else False,
                -tw2[tq], tw2[tq])
            start_str = tw2[td].min().strftime("%Y-%m-%d")

            # Fetch price history per stock
            syms = tw2[ts].unique()
            price_d = {}
            prog = st.progress(0, text="Fetching stock prices…")
            for i, sym in enumerate(syms):
                h = get_hist(ns(sym), start_str, TODAY)
                if not h.empty and "Close" in h.columns:
                    price_d[sym] = h["Close"].rename(sym)
                prog.progress((i+1)/len(syms), text=f"Fetching {sym}…")
            prog.empty()

            if price_d:
                price_df = pd.concat(price_d.values(), axis=1).ffill()
                # Build daily cumulative holdings using resample
                chg = tw2.groupby([td, ts])["signed"].sum().unstack(fill_value=0)
                chg = chg.resample("B").sum().reindex(price_df.index, fill_value=0)
                hold = chg.cumsum().reindex(columns=price_df.columns, fill_value=0)
                port_val = (hold * price_df).sum(axis=1)
                port_val = port_val[port_val > 0]

                idx_h = get_hist(it, start_str, TODAY)
                fig_g = make_subplots(specs=[[{"secondary_y": True}]])
                
                fig_g.add_trace(go.Scatter(
                    x=port_val.index, y=port_val.values,
                    name="Portfolio Value (₹)", mode="lines", fill="tozeroy",
                    line=dict(color="#2980b9", width=2.5),
                    fillcolor="rgba(41,128,185,0.12)",
                ), secondary_y=False)
                
                if not idx_h.empty and "Close" in idx_h.columns:
                    fig_g.add_trace(go.Scatter(
                        x=idx_h.index, y=idx_h["Close"],
                        name=f"{ish} Index", mode="lines",
                        line=dict(color="#e67e22", width=1.8, dash="dot"),
                    ), secondary_y=True)

                fig_g.update_layout(
                    title=f"Portfolio Value vs {ish} (Dual Axis)",
                    hovermode="x unified",
                    margin=dict(t=40,b=10),
                )
                fig_g.update_yaxes(title_text="Portfolio Value (₹)", secondary_y=False)
                fig_g.update_yaxes(title_text=f"{ish} Value", showgrid=False, secondary_y=True)

                # Buy/sell markers
                for _, r in tw2.iterrows():
                    sym = r[ts]; d_ts = r[td]; is_buy = r["signed"] > 0
                    near = port_val[port_val.index <= d_ts]
                    if near.empty: continue
                    fig_g.add_trace(go.Scatter(
                        x=[d_ts], y=[float(near.iloc[-1])], mode="markers",
                        marker=dict(symbol="triangle-up" if is_buy else "triangle-down",
                                    size=9, color="#27ae60" if is_buy else "#e74c3c",
                                    line=dict(width=1, color="white")),
                        showlegend=False,
                        hovertemplate=f"{'BUY' if is_buy else 'SELL'} {sym}<br>%{{x|%d %b %Y}}<extra></extra>",
                    ))
                fig_g.update_layout(
                    title="Portfolio Value Over Time vs Index (normalised)",
                    xaxis_title="Date", yaxis_title="Value (₹)",
                    hovermode="x unified", height=400,
                    legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
                    margin=dict(t=40,b=20),
                )
                st.plotly_chart(fig_g, use_container_width=True)
            else:
                st.warning("Could not fetch price history for any holdings from yfinance. "
                           "Check that symbols match NSE tickers (e.g. RELIANCE, TCS, INFY).")
