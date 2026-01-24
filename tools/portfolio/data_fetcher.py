from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

try:  # prefer ib_async if available
    from ib_async import IB, util  # type: ignore
except Exception:  # fallback to ib_insync
    from ib_insync import IB, util  # type: ignore


@dataclass
class IBKRConfig:
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 7
    timeout: float = 5.0


def connect_ibkr(cfg: IBKRConfig) -> IB:
    ib = IB()
    if not ib.isConnected():
        ib.connect(cfg.host, cfg.port, clientId=cfg.client_id, timeout=cfg.timeout)
    return ib


def _safe_float(val, default: float = 0.0) -> float:
    try:
        f = float(val)
        if f == f:
            return f
    except Exception:
        pass
    return default


def fetch_positions(ib: IB) -> pd.DataFrame:
    positions = ib.positions()
    rows = []
    for p in positions:
        c = p.contract
        rows.append(
            {
                "symbol": getattr(c, "symbol", None),
                "secType": getattr(c, "secType", None),
                "exchange": getattr(c, "exchange", None),
                "currency": getattr(c, "currency", None),
                "conId": getattr(c, "conId", None),
                "qty": _safe_float(getattr(p, "position", 0.0)),
                "avgCost": _safe_float(getattr(p, "avgCost", 0.0)),
                "contract": c,
            }
        )

    if not rows:
        return pd.DataFrame(columns=["symbol", "secType", "exchange", "currency", "conId", "qty", "avgCost", "marketPrice", "marketValue"])

    df = pd.DataFrame(rows)

    # Pull last prices to compute market value
    contracts = [r["contract"] for r in rows]
    tickers = [ib.reqMktData(c, "", False, False) for c in contracts]
    ib.sleep(1.0)

    prices: List[float] = []
    for t in tickers:
        last = getattr(t, "last", None)
        if last is None or last != last:
            last = getattr(t, "close", None)
        if last is None or last != last:
            last = t.marketPrice() if hasattr(t, "marketPrice") else None
        prices.append(_safe_float(last, default=0.0))

    df["marketPrice"] = prices
    df["marketValue"] = df["marketPrice"] * df["qty"]
    return df.drop(columns=["contract"], errors="ignore")


def fetch_account_summary(ib: IB) -> Dict[str, float]:
    summary = ib.accountSummary()
    out: Dict[str, float] = {}
    for s in summary:
        tag = getattr(s, "tag", "")
        val = getattr(s, "value", None)
        if not tag:
            continue
        out[tag] = _safe_float(val)

    # common keys
    return {
        "NetLiquidation": out.get("NetLiquidation", 0.0),
        "DailyPnL": out.get("DailyPnL", 0.0),
        "UnrealizedPnL": out.get("UnrealizedPnL", 0.0),
        "RealizedPnL": out.get("RealizedPnL", 0.0),
    }


def fetch_pnl(ib: IB, account: Optional[str] = None, model_code: str = "") -> Dict[str, float]:
    """Best-effort PnL stream snapshot (requires market data permissions)."""
    try:
        pnl = ib.reqPnL(account or "", model_code)
        ib.sleep(0.5)
        return {
            "DailyPnL": _safe_float(getattr(pnl, "dailyPnL", None)),
            "UnrealizedPnL": _safe_float(getattr(pnl, "unrealizedPnL", None)),
            "RealizedPnL": _safe_float(getattr(pnl, "realizedPnL", None)),
        }
    except Exception:
        return {"DailyPnL": 0.0, "UnrealizedPnL": 0.0, "RealizedPnL": 0.0}


def fetch_option_greeks(ib: IB, positions_df: pd.DataFrame) -> pd.DataFrame:
    if positions_df.empty:
        return pd.DataFrame(columns=["symbol", "delta", "gamma", "theta"])

    opt = positions_df[positions_df["secType"] == "OPT"].copy()
    if opt.empty:
        return pd.DataFrame(columns=["symbol", "delta", "gamma", "theta"])

    # Need original contracts; rebuild minimal contracts via conId
    greeks_rows = []
    for _, row in opt.iterrows():
        con_id = int(row.get("conId", 0) or 0)
        if con_id <= 0:
            continue
        contract = ib.contract(con_id)
        ticker = ib.reqMktData(contract, "", False, False)
        ib.sleep(0.5)
        g = getattr(ticker, "modelGreeks", None) or getattr(ticker, "optionGreeks", None)
        if not g:
            continue
        greeks_rows.append(
            {
                "symbol": row.get("symbol"),
                "delta": _safe_float(getattr(g, "delta", None)),
                "gamma": _safe_float(getattr(g, "gamma", None)),
                "theta": _safe_float(getattr(g, "theta", None)),
            }
        )

    return pd.DataFrame(greeks_rows)


def fetch_executions(ib: IB) -> pd.DataFrame:
    """Fetch executions (fills) from IBKR to approximate lots."""
    try:
        exec_details = ib.reqExecutions()
    except Exception:
        exec_details = []
    rows = []
    for ed in exec_details:
        c = getattr(ed, "contract", None)
        e = getattr(ed, "execution", None)
        if not c or not e:
            continue
        rows.append(
            {
                "symbol": getattr(c, "symbol", None),
                "secType": getattr(c, "secType", None),
                "currency": getattr(c, "currency", None),
                "time": pd.to_datetime(getattr(ed, "time", None)),
                "side": getattr(e, "side", None),
                "qty": _safe_float(getattr(e, "shares", None)),
                "price": _safe_float(getattr(e, "price", None)),
                "execId": getattr(e, "execId", None),
                "permId": getattr(e, "permId", None),
                "orderId": getattr(e, "orderId", None),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("time")
    return df


def fetch_history(
    ib: IB,
    contract,
    duration: str = "3 Y",
    bar_size: str = "1 day",
    what_to_show: str = "TRADES",
    use_rth: bool = True,
) -> pd.DataFrame:
    ib.qualifyContracts(contract)
    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow=what_to_show,
        useRTH=use_rth,
        formatDate=1,
    )
    if not bars:
        return pd.DataFrame()
    df = util.df(bars)
    if df is None or df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def fetch_adv20(ib: IB, contract) -> float:
    """20-day average daily volume."""
    df = fetch_history(ib, contract, duration="1 M", bar_size="1 day", what_to_show="TRADES", use_rth=True)
    if df.empty or "volume" not in df.columns:
        return 0.0
    return float(df["volume"].tail(20).mean())


def fetch_history_bulk(
    ib: IB,
    contracts: Dict[str, object],
    duration: str = "3 Y",
    bar_size: str = "1 day",
    use_rth: bool = True,
) -> pd.DataFrame:
    series = {}
    for label, contract in contracts.items():
        df = fetch_history(ib, contract, duration=duration, bar_size=bar_size, use_rth=use_rth)
        if df.empty or "close" not in df.columns:
            continue
        series[label] = df["close"]
    return pd.DataFrame(series).dropna(how="all")
