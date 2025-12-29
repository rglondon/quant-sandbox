from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
from ib_insync import IB

from quant_sandbox.data.contracts import make_contract
from quant_sandbox.data.ibkr import get_bars


@dataclass(frozen=True)
class FetchResult:
    spec: str
    series: pd.Series


def fetch_close_series(
    ib: IB,
    spec: str,
    *,
    duration: str,
    bar_size: str,
    what_to_show: str = "TRADES",
    use_rth: bool = True,
) -> Optional[pd.Series]:
    """
    Fetch a close series for an instrument spec string like:
      - "stock:AAPL"
      - "fx:EURUSD"
      - "index:DAX;exchange=EUREX"
      - "future:FDAX;exchange=EUREX"
      - You can pass extra key/values using ';' e.g. "index:DAX;exchange=EUREX;currency=EUR"

    Returns pd.Series indexed by datetime, or None if no data.
    """

    # 1) Build IB contract from your existing contract factory
    contract = make_contract(spec)

    # 2) Pull bars via your existing get_bars()
    df = get_bars(
        ib,
        contract,
        duration=duration,
        bar_size=bar_size,
        what_to_show=what_to_show,
        use_rth=use_rth,
    )

    if df is None or len(df) == 0:
        return None

    # Expecting your get_bars() to return a DataFrame with a 'close' column.
    if "close" not in df.columns:
        # Defensive: some IB endpoints / settings might return different shapes
        return None

    s = df["close"].dropna()
    if s.empty:
        return None

    # Ensure datetime index (ib_insync usually gives one already)
    if not isinstance(s.index, pd.DatetimeIndex):
        try:
            s.index = pd.to_datetime(s.index)
        except Exception:
            pass

    return s
