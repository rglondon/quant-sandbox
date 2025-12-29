from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class RollingBetaResult:
    beta: pd.Series
    alpha: pd.Series
    r2: pd.Series
    n: pd.Series


def _align_xy(x: pd.Series, y: pd.Series) -> Tuple[pd.Series, pd.Series]:
    x, y = x.align(y, join="inner")
    x = x.dropna()
    y = y.reindex(x.index).dropna()
    x = x.reindex(y.index)
    return x, y


def rolling_beta(
    x_returns: pd.Series,
    y_returns: pd.Series,
    window: int,
    min_periods: Optional[int] = None,
) -> RollingBetaResult:
    """
    Rolling OLS: y = alpha + beta*x
    Inputs are returns series (e.g. daily returns).

    Returns beta/alpha/R^2/N as Series aligned to the end-of-window timestamp.
    """
    if min_periods is None:
        min_periods = window

    x, y = _align_xy(x_returns, y_returns)
    df = pd.DataFrame({"x": x, "y": y}).dropna()

    betas = []
    alphas = []
    r2s = []
    ns = []
    idx = []

    values = df.values
    for i in range(len(df)):
        end = i + 1
        start = max(0, end - window)
        chunk = values[start:end]
        if chunk.shape[0] < min_periods:
            continue
        xs = chunk[:, 0]
        ys = chunk[:, 1]
        n = xs.size

        x_mean = xs.mean()
        y_mean = ys.mean()
        x_var = ((xs - x_mean) ** 2).sum()
        if x_var == 0:
            beta = np.nan
            alpha = np.nan
            r2 = np.nan
        else:
            cov = ((xs - x_mean) * (ys - y_mean)).sum()
            beta = cov / x_var
            alpha = y_mean - beta * x_mean
            y_hat = alpha + beta * xs
            ss_res = ((ys - y_hat) ** 2).sum()
            ss_tot = ((ys - y_mean) ** 2).sum()
            r2 = 1.0 - (ss_res / ss_tot) if ss_tot != 0 else np.nan

        idx.append(df.index[i])
        betas.append(beta)
        alphas.append(alpha)
        r2s.append(r2)
        ns.append(n)

    return RollingBetaResult(
        beta=pd.Series(betas, index=idx, name=f"beta_{window}"),
        alpha=pd.Series(alphas, index=idx, name=f"alpha_{window}"),
        r2=pd.Series(r2s, index=idx, name=f"r2_{window}"),
        n=pd.Series(ns, index=idx, name=f"n_{window}"),
    )


def scatter_points(
    x_returns: pd.Series,
    y_returns: pd.Series,
    window: Optional[int] = None,
) -> pd.DataFrame:
    """
    Returns a DataFrame with aligned x/y points suitable for scatter plots.
    If window is provided, returns only the last `window` points.
    """
    x, y = _align_xy(x_returns, y_returns)
    df = pd.DataFrame({"x": x, "y": y}).dropna()
    if window is not None:
        df = df.tail(int(window))
    return df
