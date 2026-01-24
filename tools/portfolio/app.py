from __future__ import annotations

import datetime as dt
from typing import Dict, Tuple

import numpy as np
import pandas as pd
import streamlit as st

try:
    from st_aggrid import AgGrid, GridOptionsBuilder  # type: ignore
    _HAS_AGGRID = True
except Exception:
    _HAS_AGGRID = False

try:
    import yfinance as yf  # type: ignore
    _HAS_YF = True
except Exception:
    _HAS_YF = False

try:
    import plotly.express as px
    import plotly.graph_objects as go
    _HAS_PLOTLY = True
except Exception:
    _HAS_PLOTLY = False

try:
    from ib_async import Contract  # type: ignore
except Exception:
    try:
        from ib_insync import Contract  # type: ignore
    except Exception:
        Contract = None  # type: ignore

from .data_fetcher import (
    IBKRConfig,
    connect_ibkr,
    fetch_account_summary,
    fetch_positions,
    fetch_history_bulk,
    fetch_adv20,
    fetch_executions,
)
from .risk_engine import (
    compute_returns,
    compute_var,
    max_drawdown,
    portfolio_returns,
    rolling_vol,
    sharpe_ratio,
    sortino_ratio,
    beta_vs_benchmark,
    rolling_beta,
    rolling_corr,
    factor_exposure,
)
from .store import SnapshotStore
from .factors import load_local_series, save_local_series
from .ledger import build_lots_from_fills


st.set_page_config(page_title="Quant Sandbox Portfolio", layout="wide")

st.markdown(
    """
    <style>
    :root { --qs-font: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; }
    html, body, [class*="css"]  { font-family: var(--qs-font); }
    .summary-card { padding: 10px 14px; border: 1px solid rgba(0,0,0,0.15); border-radius: 8px; }
    .summary-title { font-size: 12px; color: rgba(0,0,0,0.55); }
    .summary-value { font-size: 20px; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)


st.title("Portfolio Analysis")

with st.sidebar:
    st.subheader("IBKR Connection")
    host = st.text_input("Host", "127.0.0.1")
    port = st.number_input("Port", value=7497, step=1)
    client_id = st.number_input("Client ID", value=7, step=1)
    base_ccy = st.selectbox("Base Currency", ["USD", "EUR", "GBP", "JPY"], index=0)
    connect_btn = st.button("Connect")
    disconnect_btn = st.button("Disconnect")

if "ib" not in st.session_state:
    st.session_state.ib = None

if connect_btn:
    try:
        st.session_state.ib = connect_ibkr(IBKRConfig(host=host, port=int(port), client_id=int(client_id)))
        st.success("Connected to IBKR")
    except Exception as e:
        st.error(f"IBKR connect failed: {e}")

if disconnect_btn and st.session_state.ib is not None:
    try:
        st.session_state.ib.disconnect()
    except Exception:
        pass
    st.session_state.ib = None

ib = st.session_state.ib
if ib is None:
    st.info("Connect to IBKR to load positions and risk analytics.")
    st.stop()

# =====================
# DATA FETCH
# =====================
positions = fetch_positions(ib)
acct = fetch_account_summary(ib)

if positions.empty:
    st.warning("No positions returned from IBKR.")
    st.stop()

# Enrich sector/geo

def _lookup_sector_geo(symbol: str) -> Tuple[str, str]:
    if not symbol:
        return "Unknown", "Unknown"
    if _HAS_YF:
        try:
            info = yf.Ticker(symbol).info
            return info.get("sector", "Unknown"), info.get("country", "Unknown")
        except Exception:
            return "Unknown", "Unknown"
    return "Unknown", "Unknown"

positions["sector"], positions["country"] = zip(*[ _lookup_sector_geo(s) for s in positions["symbol"].astype(str).tolist() ])

# =====================
# SNAPSHOTS
# =====================
store = SnapshotStore(path="portfolio_snapshots.db")
snap_cols = st.columns([1, 2, 2])
if snap_cols[0].button("Snapshot now"):
    ts = dt.datetime.utcnow().isoformat(timespec="seconds")
    store.write_snapshot(ts, acct, positions)
    fills = fetch_executions(ib)
    lots = build_lots_from_fills(fills)
    store.write_lots(ts, lots)
    st.success(f"Snapshot saved: {ts}")
if snap_cols[1].button("Show snapshots"):
    st.dataframe(store.read_snapshots())

# =====================
# SUMMARY RIBBON
# =====================
col1, col2, col3, col4 = st.columns(4)
col1.markdown(f"<div class='summary-card'><div class='summary-title'>Net Liq</div><div class='summary-value'>{acct.get('NetLiquidation', 0):,.0f}</div></div>", unsafe_allow_html=True)
col2.markdown(f"<div class='summary-card'><div class='summary-title'>Daily PnL</div><div class='summary-value'>{acct.get('DailyPnL', 0):,.0f}</div></div>", unsafe_allow_html=True)
col3.markdown(f"<div class='summary-card'><div class='summary-title'>Unrealized PnL</div><div class='summary-value'>{acct.get('UnrealizedPnL', 0):,.0f}</div></div>", unsafe_allow_html=True)
col4.markdown(f"<div class='summary-card'><div class='summary-title'>Realized PnL</div><div class='summary-value'>{acct.get('RealizedPnL', 0):,.0f}</div></div>", unsafe_allow_html=True)

# =====================
# HOLDINGS TABLE
# =====================
st.subheader("Holdings")
if _HAS_AGGRID:
    gb = GridOptionsBuilder.from_dataframe(positions.drop(columns=["conId"], errors="ignore"))
    gb.configure_default_column(filterable=True, sortable=True, resizable=True)
    gb.configure_column("sector", rowGroup=True)
    AgGrid(positions, gridOptions=gb.build(), theme="streamlit")
else:
    st.dataframe(positions)

with st.expander("Lot-level view (approx from executions)", expanded=False):
    fills = fetch_executions(ib)
    lots = build_lots_from_fills(fills)
    if lots.empty:
        st.info("No executions returned. Check TWS/Gateway trade history permissions.")
    else:
        st.dataframe(lots)

# =====================
# RISK METRICS
# =====================
st.subheader("Risk Metrics")

# Build contracts from conId for history
contracts: Dict[str, object] = {}
if Contract is not None:
    for _, row in positions.iterrows():
        con_id = int(row.get("conId", 0) or 0)
        if con_id <= 0:
            continue
        contracts[str(row.get("symbol"))] = Contract(conId=con_id)

prices = fetch_history_bulk(ib, contracts, duration="3 Y", bar_size="1 day", use_rth=True)
if prices.empty:
    st.warning("Unable to fetch history for risk metrics. Check IBKR market data permissions.")
    st.stop()

rets = compute_returns(prices)
weights = positions.set_index("symbol")["marketValue"].replace(0, np.nan).dropna()
weights = weights / weights.sum()
port_ret = portfolio_returns(rets, weights)

var = compute_var(port_ret)

risk_cols = st.columns(3)
risk_cols[0].metric("Hist VaR 95% (1d)", f"{var.hist_95_1d:.2%}")
risk_cols[0].metric("Hist VaR 99% (1d)", f"{var.hist_99_1d:.2%}")
risk_cols[1].metric("Param VaR 95% (1d)", f"{var.param_95_1d:.2%}")
risk_cols[1].metric("Param VaR 99% (1d)", f"{var.param_99_1d:.2%}")
risk_cols[2].metric("Sharpe", f"{sharpe_ratio(port_ret):.2f}")
risk_cols[2].metric("Sortino", f"{sortino_ratio(port_ret):.2f}")
risk_cols[2].metric("Max Drawdown", f"{max_drawdown(port_ret):.2%}")

# =====================
# BENCHMARK & FACTORS
# =====================
st.subheader("Benchmark & Factor Exposure")
bench_cols = st.columns(2)
benchmarks = st.multiselect("Benchmarks", ["SPY", "ACWI"], default=["SPY", "ACWI"])

factor_defaults = {
    "beta": "SPY",
    "value": "IWD",
    "momentum": "MTUM",
    "growth": "IWF",
    "rates_10y": "DGS10",
    "fx_dxy": "DTWEXBGS",
    "infl_5y": "T5YIE",
}
st.caption("Macro series will use cached FRED CSVs if available.")
factor_inputs = {k: st.text_input(k, v) for k, v in factor_defaults.items()}

# CSV upload fallback for macro factors
with st.expander("Upload macro factor CSV (fallback)", expanded=False):
    st.caption("Expected columns: date,value (date parseable).")
    target = st.selectbox("Store as", ["rates_10y", "fx_dxy", "infl_5y"], index=0)
    file = st.file_uploader("CSV file", type=["csv"])
    if file is not None:
        try:
            dfu = pd.read_csv(file)
            if "date" not in dfu.columns or "value" not in dfu.columns:
                # fallback: first two columns
                dfu = dfu.iloc[:, :2]
                dfu.columns = ["date", "value"]
            dfu["date"] = pd.to_datetime(dfu["date"])
            s = pd.Series(dfu["value"].astype(float).values, index=dfu["date"])
            save_local_series(target, s)
            st.success(f"Saved {target} to local cache.")
        except Exception as e:
            st.error(f"Failed to load CSV: {e}")

bench_returns = {}
if _HAS_YF and benchmarks:
    try:
        b_prices = yf.download(benchmarks, period="3y", auto_adjust=True, progress=False)["Close"]
        if isinstance(b_prices, pd.Series):
            b_prices = b_prices.to_frame()
        b_rets = compute_returns(b_prices)
        for b in b_rets.columns:
            bench_returns[b] = b_rets[b]
    except Exception:
        st.warning("Unable to pull benchmark data via yfinance.")

if bench_returns:
    for b, bret in bench_returns.items():
        bench_cols[0].metric(f"Beta vs {b}", f"{beta_vs_benchmark(port_ret, bret):.2f}")
        corr = rolling_corr(port_ret, bret, window=63)
        beta = rolling_beta(port_ret, bret, window=63)
        if _HAS_PLOTLY:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=corr.index, y=corr.values, name=f\"{b} Corr (63D)\"))
            fig.add_trace(go.Scatter(x=beta.index, y=beta.values, name=f\"{b} Beta (63D)\"))
            bench_cols[1].plotly_chart(fig, use_container_width=True)
        else:
            bench_cols[1].line_chart(pd.DataFrame({\"corr\": corr, \"beta\": beta}).dropna(), height=180)

# Factor regression (market + macro)
factor_series = {}
for name, ticker in factor_inputs.items():
    # Try local cached FRED series for macro factors
    if name in {"rates_10y", "fx_dxy", "infl_5y"}:
        cached = load_local_series(name)
        if cached is not None:
            factor_series[name] = cached.pct_change().dropna()
            continue

    # Fallback to yfinance for market proxies (if available)
    if _HAS_YF:
        try:
            p = yf.download(ticker, period="3y", auto_adjust=True, progress=False)["Close"]
            if isinstance(p, pd.Series):
                factor_series[name] = p.pct_change().dropna()
        except Exception:
            continue

if factor_series:
    factors_df = pd.DataFrame(factor_series).dropna(how="all")
    betas = factor_exposure(port_ret, factors_df)
    st.dataframe(pd.DataFrame.from_dict(betas, orient="index", columns=["beta"]).sort_index())

# =====================
# LIQUIDITY RISK
# =====================
st.subheader("Liquidity Risk")
adv_vals = []
for _, row in positions.iterrows():
    sym = str(row.get("symbol"))
    con_id = int(row.get("conId", 0) or 0)
    adv = 0.0
    if Contract is not None and con_id > 0:
        adv = fetch_adv20(ib, Contract(conId=con_id))
    if adv <= 0 and _HAS_YF:
        try:
            info = yf.Ticker(sym).info
            adv = float(info.get("averageVolume", 0.0) or 0.0)
        except Exception:
            adv = 0.0
    adv_vals.append(adv)
positions["adv20"] = adv_vals
positions["days_to_liquidate"] = positions.apply(
    lambda r: (abs(r["qty"]) / r["adv20"]) if r.get("adv20", 0) > 0 else np.nan, axis=1
)
st.dataframe(positions[["symbol", "qty", "adv20", "days_to_liquidate"]])

# =====================
# SHADOW ACCOUNTING (FX vs Asset PnL)
# =====================
st.subheader("Shadow Accounting (FX vs Asset PnL)")
fx_rows = []
for _, row in positions.iterrows():
    sym = str(row.get("symbol"))
    ccy = str(row.get("currency") or base_ccy)
    if ccy == base_ccy:
        continue
    # Try to fetch FX rate via yfinance if available
    fx_rate = np.nan
    fx_sym = f"{ccy}{base_ccy}=X"
    if _HAS_YF:
        try:
            fx_prices = yf.download(fx_sym, period="5d", auto_adjust=True, progress=False)["Close"]
            fx_rate = float(fx_prices.dropna().iloc[-1]) if not fx_prices.empty else np.nan
        except Exception:
            fx_rate = np.nan
    mv_local = float(row.get("marketPrice", 0.0) or 0.0) * float(row.get("qty", 0.0) or 0.0)
    mv_base = mv_local * (fx_rate if fx_rate == fx_rate else 0.0)
    fx_rows.append(
        {
            "symbol": sym,
            "currency": ccy,
            "fx_rate": fx_rate,
            "mv_local": mv_local,
            "mv_base": mv_base,
        }
    )
if fx_rows:
    st.dataframe(pd.DataFrame(fx_rows))
else:
    st.caption("No non-base currency positions detected.")

# =====================
# PLOTS
# =====================
if _HAS_PLOTLY:
    st.subheader("Exposure")
    exp_cols = st.columns(2)

    sector_exp = positions.groupby("sector")["marketValue"].sum().sort_values(ascending=False)
    geo_exp = positions.groupby("country")["marketValue"].sum().sort_values(ascending=False)

    exp_cols[0].plotly_chart(px.pie(values=sector_exp.values, names=sector_exp.index, hole=0.5, title="Sector Exposure"), use_container_width=True)
    exp_cols[1].plotly_chart(px.sunburst(names=geo_exp.index, values=geo_exp.values, title="Geographic Exposure"), use_container_width=True)

    st.subheader("Rolling Volatility")
    vol30 = rolling_vol(port_ret, 30)
    vol90 = rolling_vol(port_ret, 90)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=vol30.index, y=vol30.values, name="30D Vol"))
    fig.add_trace(go.Scatter(x=vol90.index, y=vol90.values, name="90D Vol"))
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Plotly not installed; skipping charts.")
