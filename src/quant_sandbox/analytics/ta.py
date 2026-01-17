from __future__ import annotations

import numpy as np
import pandas as pd


def sma(x: pd.Series, window: int) -> pd.Series:
    w = int(window)
    out = x.rolling(window=w, min_periods=w).mean()
    out.name = f"sma_{w}"
    return out.astype("float64")


def ema(x: pd.Series, span: int) -> pd.Series:
    w = int(span)
    # min_periods enforces warmup trimming (NaN until formed)
    out = x.ewm(span=w, adjust=False, min_periods=w).mean()
    out.name = f"ema_{w}"
    return out.astype("float64")


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Wilder RSI (production-grade):
      - smoothing is EMA-style with alpha=1/period, adjust=False
      - warmup trimmed (NaN) so it never reaches UI when serialized
      - output clipped to [0, 100] for numerical safety
    """
    p = int(period)
    if p < 2:
        raise ValueError("period must be >= 2")

    c = close.astype("float64").dropna().sort_index()
    if c.empty:
        out = pd.Series(dtype="float64", name=f"rsi_{p}")
        return out

    delta = c.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = gain.ewm(alpha=1 / float(p), adjust=False, min_periods=p).mean()
    avg_loss = loss.ewm(alpha=1 / float(p), adjust=False, min_periods=p).mean()

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))

    # Ensure warmup stays out even if pandas forms something early in edge cases
    if len(rsi) > 0:
        rsi = rsi.astype("float64")
        rsi.iloc[:p] = np.nan

    rsi = rsi.clip(lower=0.0, upper=100.0)
    rsi.name = f"rsi_{p}"
    return rsi.astype("float64")


def bollinger_bands(close: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.DataFrame:
    w = int(window)
    m = close.rolling(w, min_periods=w).mean()
    s = close.rolling(w, min_periods=w).std()
    upper = m + float(n_std) * s
    lower = m - float(n_std) * s
    return pd.DataFrame({"bb_mid": m, "bb_upper": upper, "bb_lower": lower}).astype("float64")


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    w = int(window)
    h, l = high.align(low, join="inner")
    h, c = h.align(close, join="inner")
    l = l.reindex(h.index)
    c = c.reindex(h.index)

    prev_close = c.shift(1)
    tr = pd.concat(
        [(h - l).abs(), (h - prev_close).abs(), (l - prev_close).abs()],
        axis=1,
    ).max(axis=1)

    out = tr.ewm(alpha=1 / w, adjust=False, min_periods=w).mean()
    out.name = f"atr_{w}"
    return out.astype("float64")
