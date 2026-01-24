from __future__ import annotations

import os

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from factors import update_fred_cache  # noqa: E402

FRED_SERIES = {
    "rates_10y": "DGS10",
    "infl_5y": "T5YIE",
    "fx_dxy": "DTWEXBGS",
}

if __name__ == "__main__":
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise SystemExit("Set FRED_API_KEY in environment")
    update_fred_cache(FRED_SERIES, api_key)
    print("FRED cache updated")
