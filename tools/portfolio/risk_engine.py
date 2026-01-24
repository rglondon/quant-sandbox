from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np
import pandas as pd


@dataclass
class VaRResult:
    hist_95_1d: float
    hist_99_1d: float
    hist_95_10d: float
    hist_99_10d: float
    param_95_1d: float
    param_99_1d: float
    param_95_10d: float
    param_99_10d: float


def compute_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change().dropna(how="all")


def _historical_var(returns: pd.Series, alpha: float, horizon: int = 1) -> float:
    if returns.empty:
        return 0.0
    if horizon > 1:
        agg = (1 + returns).rolling(horizon).apply(np.prod, raw=True) - 1
        agg = agg.dropna()
    else:
        agg = returns
    return float(np.quantile(agg, 1 - alpha))


def _parametric_var(returns: pd.Series, alpha: float, horizon: int = 1) -> float:
    if returns.empty:
        return 0.0
    mu = returns.mean()
    sigma = returns.std(ddof=1)
    z = np.quantile(np.random.normal(size=200000), 1 - alpha)
    return float(mu * horizon + z * sigma * np.sqrt(horizon))


def compute_var(returns: pd.Series) -> VaRResult:
    return VaRResult(
        hist_95_1d=_historical_var(returns, 0.95, 1),
        hist_99_1d=_historical_var(returns, 0.99, 1),
        hist_95_10d=_historical_var(returns, 0.95, 10),
        hist_99_10d=_historical_var(returns, 0.99, 10),
        param_95_1d=_parametric_var(returns, 0.95, 1),
        param_99_1d=_parametric_var(returns, 0.99, 1),
        param_95_10d=_parametric_var(returns, 0.95, 10),
        param_99_10d=_parametric_var(returns, 0.99, 10),
    )


def rolling_vol(returns: pd.Series, window: int, ann_factor: int = 252) -> pd.Series:
    return returns.rolling(window).std(ddof=1) * np.sqrt(ann_factor)


def sharpe_ratio(returns: pd.Series, rf: float = 0.0, ann_factor: int = 252) -> float:
    if returns.empty:
        return 0.0
    excess = returns - rf / ann_factor
    return float(excess.mean() / excess.std(ddof=1) * np.sqrt(ann_factor))


def sortino_ratio(returns: pd.Series, rf: float = 0.0, ann_factor: int = 252) -> float:
    if returns.empty:
        return 0.0
    excess = returns - rf / ann_factor
    downside = excess[excess < 0]
    if downside.empty:
        return 0.0
    dd = np.sqrt((downside ** 2).mean())
    return float(excess.mean() / dd * np.sqrt(ann_factor))


def max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    equity = (1 + returns).cumprod()
    peak = equity.cummax()
    dd = (equity / peak) - 1
    return float(dd.min())


def factor_exposure(returns: pd.Series, factors: pd.DataFrame) -> Dict[str, float]:
    """Rolling regression against factor proxies. Returns static betas using OLS."""
    if returns.empty or factors.empty:
        return {c: 0.0 for c in factors.columns}
    df = pd.concat([returns, factors], axis=1, join="inner").dropna()
    if df.empty:
        return {c: 0.0 for c in factors.columns}
    y = df.iloc[:, 0].values
    X = df.iloc[:, 1:].values
    X = np.c_[np.ones(len(X)), X]
    betas, *_ = np.linalg.lstsq(X, y, rcond=None)
    out = {f"beta_{f}": float(b) for f, b in zip(factors.columns, betas[1:])}
    return out


def beta_vs_benchmark(returns: pd.Series, benchmark: pd.Series) -> float:
    df = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
    if df.empty:
        return 0.0
    cov = np.cov(df.iloc[:, 0].values, df.iloc[:, 1].values)[0, 1]
    var = np.var(df.iloc[:, 1].values)
    return float(cov / var) if var > 0 else 0.0


def rolling_beta(returns: pd.Series, benchmark: pd.Series, window: int = 63) -> pd.Series:
    df = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
    if df.empty:
        return pd.Series(dtype=float)
    r = df.iloc[:, 0]
    b = df.iloc[:, 1]
    cov = r.rolling(window).cov(b)
    var = b.rolling(window).var()
    return cov / var


def rolling_corr(returns: pd.Series, benchmark: pd.Series, window: int = 63) -> pd.Series:
    df = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
    if df.empty:
        return pd.Series(dtype=float)
    return df.iloc[:, 0].rolling(window).corr(df.iloc[:, 1])


def portfolio_returns(returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    w = weights.reindex(returns.columns).fillna(0.0)
    return (returns * w).sum(axis=1)
