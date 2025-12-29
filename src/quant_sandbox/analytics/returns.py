from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Union

import numpy as np
import pandas as pd

Annualization = Literal["infer", "daily", "weekly", "monthly", "yearly"]
RfMode = Literal["annual", "per_period"]


# ----------------------------
# Helpers
# ----------------------------

def infer_annualization_from_index(idx: pd.DatetimeIndex) -> Annualization:
    """
    Best-effort frequency inference from datetime index spacing.
    Returns "daily" | "weekly" | "monthly" | "yearly".
    """
    if not isinstance(idx, pd.DatetimeIndex) or len(idx) < 3:
        return "daily"

    # median delta in days
    deltas = np.diff(idx.sort_values().values).astype("timedelta64[D]").astype(int)
    med = np.median(deltas)

    if med <= 2:
        return "daily"
    if 3 <= med <= 10:
        return "weekly"
    if 20 <= med <= 40:
        return "monthly"
    return "yearly"


def annualization_factor(annualization: Annualization) -> float:
    """
    Factor used to annualize volatility and Sharpe:
      Sharpe_annual = mean_excess_per_period / std_per_period * sqrt(factor)
    """
    if annualization == "daily":
        return 252.0
    if annualization == "weekly":
        return 52.0
    if annualization == "monthly":
        return 12.0
    if annualization == "yearly":
        return 1.0
    raise ValueError(f"Unknown annualization: {annualization}")


def _ensure_series(x: Union[pd.Series, pd.DataFrame], col: Optional[str] = None) -> pd.Series:
    if isinstance(x, pd.Series):
        return x.dropna()
    if isinstance(x, pd.DataFrame):
        if col is None:
            if x.shape[1] != 1:
                raise ValueError("DataFrame has multiple columns; pass col=<name>")
            col = x.columns[0]
        return x[col].dropna()
    raise TypeError("Expected pd.Series or pd.DataFrame")


def to_simple_returns(prices: pd.Series) -> pd.Series:
    s = prices.dropna().sort_index()
    r = s.pct_change().dropna()
    r.name = "ret"
    return r


def to_log_returns(prices: pd.Series) -> pd.Series:
    s = prices.dropna().sort_index()
    r = np.log(s).diff().dropna()
    r.name = "logret"
    return r


def _align(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series]:
    a, b = a.align(b, join="inner")
    a = a.dropna()
    b = b.reindex(a.index).dropna()
    a = a.reindex(b.index)
    return a, b


def _rf_to_per_period(
    rf: Union[float, pd.Series],
    *,
    idx: pd.DatetimeIndex,
    annualization: Annualization,
    rf_mode: RfMode,
) -> pd.Series:
    """
    Convert risk-free input to a per-period series aligned to returns index.

    rf_mode:
      - "annual": rf is annualized (e.g. 0.05 for 5%) and converted to per-period
      - "per_period": rf is already per-period (same frequency as returns)
    """
    if isinstance(rf, (int, float, np.floating)):
        rf_val = float(rf)
        if rf_mode == "per_period":
            return pd.Series(rf_val, index=idx, name="rf")
        # annual -> per period
        f = annualization_factor(annualization)
        return pd.Series(rf_val / f, index=idx, name="rf")

    if isinstance(rf, pd.Series):
        s = rf.dropna().sort_index()
        # If annual series (e.g. daily rate but annualized value each day) we still treat by rf_mode.
        s = s.reindex(idx).ffill()  # forward fill for missing days
        if rf_mode == "per_period":
            return s.rename("rf")
        f = annualization_factor(annualization)
        return (s / f).rename("rf")

    raise TypeError("rf must be float or pd.Series")


# ----------------------------
# Core metrics
# ----------------------------

def sharpe_ratio(
    returns: pd.Series,
    *,
    rf: Union[float, pd.Series] = 0.0,
    annualization: Annualization = "infer",
    rf_mode: RfMode = "annual",
    min_periods: int = 3,
) -> float:
    """
    Annualized Sharpe ratio from a returns series.

    returns: per-period returns (daily/weekly/monthly)
    rf:
      - float: either annualized (rf_mode="annual") or per-period (rf_mode="per_period")
      - pd.Series: aligned/ffilled to returns index, treated per rf_mode
    """
    r = returns.dropna().sort_index()
    if len(r) < min_periods:
        return float("nan")

    ann = annualization
    if ann == "infer":
        ann = infer_annualization_from_index(r.index)

    rf_pp = _rf_to_per_period(rf, idx=r.index, annualization=ann, rf_mode=rf_mode)
    r, rf_pp = _align(r, rf_pp)
    ex = (r - rf_pp).dropna()
    if len(ex) < min_periods:
        return float("nan")

    mu = ex.mean()
    sd = ex.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")

    f = annualization_factor(ann)
    return float((mu / sd) * np.sqrt(f))


def rolling_sharpe(
    returns: pd.Series,
    window: int,
    *,
    rf: Union[float, pd.Series] = 0.0,
    annualization: Annualization = "infer",
    rf_mode: RfMode = "annual",
    min_periods: Optional[int] = None,
) -> pd.Series:
    """
    Rolling annualized Sharpe ratio using a fixed-size lookback window.

    window: number of periods (e.g. 40 for ~2 months of daily data)
    """
    r = returns.dropna().sort_index()

    if min_periods is None:
        min_periods = window

    ann = annualization
    if ann == "infer":
        ann = infer_annualization_from_index(r.index)

    rf_pp = _rf_to_per_period(rf, idx=r.index, annualization=ann, rf_mode=rf_mode)
    r, rf_pp = _align(r, rf_pp)
    ex = (r - rf_pp).dropna()

    # rolling mean/std of excess returns
    mu = ex.rolling(window=int(window), min_periods=int(min_periods)).mean()
    sd = ex.rolling(window=int(window), min_periods=int(min_periods)).std(ddof=1)
    f = annualization_factor(ann)

    out = (mu / sd) * np.sqrt(f)
    out.name = f"rolling_sharpe_{window}"
    return out


def annualized_volatility(
    returns: pd.Series,
    *,
    annualization: Annualization = "infer",
    min_periods: int = 3,
) -> float:
    r = returns.dropna().sort_index()
    if len(r) < min_periods:
        return float("nan")

    ann = annualization
    if ann == "infer":
        ann = infer_annualization_from_index(r.index)

    sd = r.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")

    return float(sd * np.sqrt(annualization_factor(ann)))


def rolling_volatility(
    returns: pd.Series,
    window: int,
    *,
    annualization: Annualization = "infer",
    min_periods: Optional[int] = None,
) -> pd.Series:
    r = returns.dropna().sort_index()
    if min_periods is None:
        min_periods = window

    ann = annualization
    if ann == "infer":
        ann = infer_annualization_from_index(r.index)

    sd = r.rolling(window=int(window), min_periods=int(min_periods)).std(ddof=1)
    out = sd * np.sqrt(annualization_factor(ann))
    out.name = f"rolling_vol_{window}"
    return out


# ----------------------------
# Convenience wrappers (prices -> returns -> metric)
# ----------------------------

def sharpe_from_prices(
    prices: pd.Series,
    *,
    rf: Union[float, pd.Series] = 0.0,
    annualization: Annualization = "infer",
    rf_mode: RfMode = "annual",
    use_log_returns: bool = False,
) -> float:
    r = to_log_returns(prices) if use_log_returns else to_simple_returns(prices)
    return sharpe_ratio(r, rf=rf, annualization=annualization, rf_mode=rf_mode)


def rolling_sharpe_from_prices(
    prices: pd.Series,
    window: int,
    *,
    rf: Union[float, pd.Series] = 0.0,
    annualization: Annualization = "infer",
    rf_mode: RfMode = "annual",
    use_log_returns: bool = False,
    min_periods: Optional[int] = None,
) -> pd.Series:
    r = to_log_returns(prices) if use_log_returns else to_simple_returns(prices)
    return rolling_sharpe(
        r,
        window=window,
        rf=rf,
        annualization=annualization,
        rf_mode=rf_mode,
        min_periods=min_periods,
    )
