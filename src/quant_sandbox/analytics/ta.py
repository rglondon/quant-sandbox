from __future__ import annotations

import pandas as pd


def sma(x: pd.Series, window: int) -> pd.Series:
    out = x.rolling(int(window)).mean()
    out.name = f"sma_{window}"
    return out


def ema(x: pd.Series, span: int) -> pd.Series:
    out = x.ewm(span=int(span), adjust=False).mean()
    out.name = f"ema_{span}"
    return out


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    c = close.dropna().sort_index()
    delta = c.diff()
    up = delta.clip(lower=0.0)
    down = (-delta).clip(lower=0.0)
    roll_up = up.ewm(alpha=1 / int(window), adjust=False).mean()
    roll_down = down.ewm(alpha=1 / int(window), adjust=False).mean()
    rs = roll_up / roll_down
    out = 100.0 - (100.0 / (1.0 + rs))
    out.name = f"rsi_{window}"
    return out


def bollinger_bands(close: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.DataFrame:
    m = close.rolling(int(window)).mean()
    s = close.rolling(int(window)).std()
    upper = m + float(n_std) * s
    lower = m - float(n_std) * s
    return pd.DataFrame(
        {
            "bb_mid": m,
            "bb_upper": upper,
            "bb_lower": lower,
        }
    )


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    h, l = high.align(low, join="inner")
    h, c = h.align(close, join="inner")
    l = l.reindex(h.index)
    c = c.reindex(h.index)

    prev_close = c.shift(1)
    tr = pd.concat(
        [
            (h - l).abs(),
            (h - prev_close).abs(),
            (l - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    out = tr.ewm(alpha=1 / int(window), adjust=False).mean()
    out.name = f"atr_{window}"
    return out
