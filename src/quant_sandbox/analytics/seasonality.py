from __future__ import annotations

import pandas as pd


def daily_returns(prices: pd.Series) -> pd.Series:
    s = prices.dropna().sort_index()
    r = s.pct_change().dropna()
    r.name = "ret"
    return r


def seasonality_day_of_year(prices: pd.Series) -> pd.DataFrame:
    """
    Average daily return by day-of-year across all years.
    Returns DataFrame with columns: mean, median, count.
    """
    r = daily_returns(prices)
    doy = r.index.dayofyear
    g = r.groupby(doy)
    out = pd.DataFrame({"mean": g.mean(), "median": g.median(), "count": g.count()})
    out.index.name = "day_of_year"
    return out


def seasonality_month_heatmap(prices: pd.Series) -> pd.DataFrame:
    """
    Heatmap table: rows=year, cols=month, values=monthly return.
    Useful for a “year x month” heatmap.
    """
    s = prices.dropna().sort_index()
    monthly = s.resample("M").last().pct_change().dropna()
    df = pd.DataFrame({"ret": monthly})
    df["year"] = df.index.year
    df["month"] = df.index.month
    pivot = df.pivot_table(index="year", columns="month", values="ret", aggfunc="mean").sort_index()
    pivot.columns = [f"{c:02d}" for c in pivot.columns]
    return pivot


def seasonality_weekday(prices: pd.Series) -> pd.DataFrame:
    """
    Average daily return by weekday (Mon..Fri).
    """
    r = daily_returns(prices)
    wd = r.index.weekday
    g = r.groupby(wd)
    out = pd.DataFrame({"mean": g.mean(), "median": g.median(), "count": g.count()})
    out.index = out.index.map({0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"})
    out.index.name = "weekday"
    return out
