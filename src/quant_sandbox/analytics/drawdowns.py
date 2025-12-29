from __future__ import annotations

import pandas as pd


def drawdown_series(prices: pd.Series) -> pd.Series:
    """
    Underwater curve: (price / running_max) - 1
    """
    s = prices.dropna().sort_index()
    peak = s.cummax()
    dd = s / peak - 1.0
    dd.name = "drawdown"
    return dd


def rolling_max_drawdown(prices: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    """
    Rolling max drawdown over a lookback window (window points).
    """
    if min_periods is None:
        min_periods = window
    dd = drawdown_series(prices)

    # max drawdown in a window is the minimum drawdown (most negative) within that window
    out = dd.rolling(window=int(window), min_periods=int(min_periods)).min()
    out.name = f"max_drawdown_{window}"
    return out
