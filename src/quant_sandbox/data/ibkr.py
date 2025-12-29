from __future__ import annotations

import pandas as pd
from ib_insync import IB, util, Stock, Contract


# =========================
# CONNECTION
# =========================

def connect_ibkr(host: str, port: int, client_id: int) -> IB:
    ib = IB()
    ib.connect(host, port, clientId=client_id)
    return ib


# =========================
# GENERIC HISTORICAL DATA
# =========================

def get_bars(
    ib: IB,
    contract: Contract,
    duration: str,
    bar_size: str,
    what_to_show: str,
    use_rth: bool,
    end_datetime: str = "",
) -> pd.DataFrame:
    """
    Generic IBKR historical data fetcher.
    Works for stocks, indices, FX, futures, ETFs, etc.
    """

    # Ensure contract is valid
    ib.qualifyContracts(contract)

    bars = ib.reqHistoricalData(
        contract,
        endDateTime=end_datetime,   # "" means now
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


# =========================
# CONVENIENCE WRAPPERS
# =========================

def get_stock_intraday_1min(
    ib: IB,
    symbol: str,
    exchange: str = "SMART",
    currency: str = "USD",
) -> pd.DataFrame:
    """
    Simple helper used by early prototypes.
    """
    contract = Stock(symbol, exchange, currency)
    return get_bars(
        ib=ib,
        contract=contract,
        duration="1 D",
        bar_size="1 min",
        what_to_show="TRADES",
        use_rth=True,
        end_datetime="",
    )


# =========================
# CONTRACT DISCOVERY
# =========================

def search_contracts(
    ib: IB,
    query: str,
    max_results: int = 10,
):
    """
    Discover valid IBKR contracts for a symbol or keyword.
    Extremely useful for indices like DAX, SPX, etc.
    """
    matches = ib.reqMatchingSymbols(query)

    results = []
    for m in matches[:max_results]:
        c = m.contract
        results.append(
            {
                "symbol": getattr(c, "symbol", None),
                "name": getattr(m, "description", None),
                "secType": getattr(c, "secType", None),
                "exchange": getattr(c, "primaryExchange", None) or getattr(c, "exchange", None),
                "currency": getattr(c, "currency", None),
                "conId": getattr(c, "conId", None),
            }
        )

    return results
