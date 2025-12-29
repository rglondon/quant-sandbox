from __future__ import annotations

import pandas as pd

from quant_sandbox.data.ibkr import get_bars
from quant_sandbox.data.contracts import make_contract


def infer_what_to_show(spec: str, force_midpoint: bool = False) -> str:
    if force_midpoint:
        return "MIDPOINT"
    # FX requires MIDPOINT usually
    if spec.lower().startswith("fx:"):
        return "MIDPOINT"
    return "TRADES"


def fetch_close_series(
    ib,
    spec: str,
    duration: str,
    bar_size: str,
    use_rth: bool,
    force_midpoint: bool = False,
) -> pd.Series:
    contract = make_contract(spec)
    what = infer_what_to_show(spec, force_midpoint)

    df = get_bars(
        ib=ib,
        contract=contract,
        duration=duration,
        bar_size=bar_size,
        what_to_show=what,
        use_rth=use_rth,
        end_datetime="",
    )

    if df is None or df.empty or "close" not in df.columns:
        return pd.Series(dtype=float)

    s = df["close"].dropna()
    # Ensure monotonic index
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s
