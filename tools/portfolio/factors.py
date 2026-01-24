from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd

try:
    import requests  # type: ignore
except Exception:
    requests = None  # type: ignore


@dataclass
class FactorSeries:
    name: str
    series: pd.Series


def _factor_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "data", "factors")


def load_local_series(name: str) -> Optional[pd.Series]:
    path = os.path.join(_factor_dir(), f"{name}.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    if "date" not in df.columns or "value" not in df.columns:
        return None
    df["date"] = pd.to_datetime(df["date"])
    s = pd.Series(df["value"].values, index=df["date"])
    return s.sort_index()


def save_local_series(name: str, series: pd.Series) -> None:
    os.makedirs(_factor_dir(), exist_ok=True)
    df = pd.DataFrame({"date": series.index, "value": series.values})
    df.to_csv(os.path.join(_factor_dir(), f"{name}.csv"), index=False)


def fetch_fred_series(series_id: str, api_key: str, start: str = "2000-01-01") -> Optional[pd.Series]:
    if requests is None:
        return None
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start,
    }
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()
    obs = data.get("observations", [])
    rows = []
    for o in obs:
        try:
            val = float(o.get("value"))
        except Exception:
            continue
        rows.append((pd.to_datetime(o.get("date")), val))
    if not rows:
        return None
    idx, vals = zip(*rows)
    return pd.Series(vals, index=pd.to_datetime(list(idx))).sort_index()


def update_fred_cache(series_map: Dict[str, str], api_key: str) -> None:
    """Fetch series from FRED and store in local CSV cache.
    series_map: {"rates_10y": "DGS10", "infl_5y": "T5YIE", ...}
    """
    for name, fred_id in series_map.items():
        s = fetch_fred_series(fred_id, api_key)
        if s is not None:
            save_local_series(name, s)
