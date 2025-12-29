from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, Optional, Tuple

# ----------------------------
# Bar sizes (IBKR barSizeSetting)
# ----------------------------
Bar = Literal[
    "1 min",
    "5 mins",
    "15 mins",
    "30 mins",
    "1 hour",
    "1 day",
    "1 week",
    "1 month",
]

Unit = Literal["d", "w", "m", "y"]

# For rolling-window math -> convert bar size to approximate "days per bar"
_BAR_TO_DAYS = {
    "1 day": 1.0,
    "1 week": 7.0,
    "1 month": 30.0,  # approximation (good enough for window sizing)
}

# intraday approximation (US trading day)
_INTRADAY_TO_DAYS = {
    "1 min": 1.0 / 390.0,
    "5 mins": 5.0 / 390.0,
    "15 mins": 15.0 / 390.0,
    "30 mins": 30.0 / 390.0,
    "1 hour": 60.0 / 390.0,
}


# ----------------------------
# Rolling-window helpers (for rolling Sharpe, rolling vol, etc.)
# ----------------------------
@dataclass(frozen=True)
class HumanWindow:
    n: int
    unit: Unit


def parse_window(s: str) -> HumanWindow:
    """
    Parse rolling window strings: 10d, 3w, 2m, 5y (case-insensitive).
    """
    s = s.strip().lower()
    m = re.fullmatch(r"(\d+)\s*([dwmy])", s)
    if not m:
        raise ValueError(f"Invalid window '{s}'. Use like 10d, 3w, 2m, 5y.")
    return HumanWindow(n=int(m.group(1)), unit=m.group(2))  # type: ignore


def window_to_periods(window: str, *, bar: Bar) -> int:
    """
    Convert rolling window (e.g. 2m) into number of bars for a given bar size.
    Used for rolling indicators / rolling metrics.
    """
    w = parse_window(window)

    # Convert window to "days"
    if w.unit == "d":
        days = float(w.n)
    elif w.unit == "w":
        days = float(w.n) * 7.0
    elif w.unit == "m":
        days = float(w.n) * 30.0
    else:  # "y"
        days = float(w.n) * 365.0

    # Convert bar to days-per-bar
    if bar in _BAR_TO_DAYS:
        days_per_bar = _BAR_TO_DAYS[bar]
    elif bar in _INTRADAY_TO_DAYS:
        days_per_bar = _INTRADAY_TO_DAYS[bar]
    else:
        raise ValueError(f"Unsupported bar: {bar}")

    periods = int(round(days / days_per_bar))
    return max(periods, 2)  # minimum 2 periods for std dev


def ensure_min_periods(periods: int, *, frac: float = 1.0) -> int:
    """
    Optional helper if you want min_periods < window (e.g. 0.7*window).
    """
    return max(3, int(round(periods * frac)))


# ----------------------------
# Chart/history window resolver (for API/charting)
# ----------------------------
@dataclass(frozen=True)
class ResolvedWindow:
    """
    A "history request" window for IBKR.

    - duration: IBKR durationStr e.g. "1 D", "1 M", "5 Y"
    - start/end: optional explicit date bounds (for custom ranges / MTD/YTD)
      (server/chart can choose to use these or ignore them)
    """
    duration: str
    start: Optional[date] = None
    end: Optional[date] = None


def resolve_bar_size(bar: str) -> Bar:
    """
    Validate/normalize bar size strings.
    Accepts friendly aliases: daily/weekly/monthly.
    """
    b = bar.strip().lower()

    alias = {
        "daily": "1 day",
        "weekly": "1 week",
        "monthly": "1 month",
    }
    b = alias.get(b, bar.strip())

    allowed: Tuple[str, ...] = (
        "1 min", "5 mins", "15 mins", "30 mins", "1 hour",
        "1 day", "1 week", "1 month",
    )
    if b not in allowed:
        raise ValueError(f"Invalid bar '{bar}'. Use one of: {list(allowed)} or daily/weekly/monthly")
    return b  # type: ignore



def _parse_eu_date(s: str) -> date:
    """
    Parse European date format DD/MM/YYYY (also accepts DD-MM-YYYY).
    """
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Invalid date '{s}'. Use DD/MM/YYYY (e.g. 23/12/2025).")


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _year_start(d: date) -> date:
    return d.replace(month=1, day=1)


def _duration_from_days(days: int) -> str:
    """
    Convert an approximate day count to an IBKR durationStr.
    IBKR supports units: S, D, W, M, Y. We'll use D/W/M/Y.
    """
    if days <= 1:
        return "1 D"
    if days <= 7:
        return f"{days} D"
    if days <= 31:
        weeks = max(1, round(days / 7))
        return f"{weeks} W"
    if days <= 365 * 2:
        months = max(1, round(days / 30))
        return f"{months} M"
    years = max(1, round(days / 365))
    return f"{years} Y"


def resolve_window(
    tf: str,
    bar: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> ResolvedWindow:
    """
    Resolve "tf" (timeframe/lookback) into an IBKR durationStr + optional explicit bounds.

    Supported tf presets:
      - intraday
      - 2d, 5d
      - 1m, 3m, 6m
      - 1y, 3y, 5y, 10y
      - MTD, YTD

    Custom range:
      - provide date_from/date_to in DD/MM/YYYY (European format)
      - tf can be anything (ignored) when custom dates are provided

    Notes:
      - For daily/weekly/monthly bars, these windows work naturally.
      - For intraday bars, IBKR has practical limits; your data permissions also matter.
    """
    _ = resolve_bar_size(bar)  # validate bar even if we don't use it here

    # Custom dates override presets
    if date_from or date_to:
        if not (date_from and date_to):
            raise ValueError("If using custom dates, provide BOTH --from and --to (DD/MM/YYYY).")
        start = _parse_eu_date(date_from)
        end = _parse_eu_date(date_to)
        if end < start:
            raise ValueError("--to must be >= --from")
        days = (end - start).days + 1
        return ResolvedWindow(duration=_duration_from_days(days), start=start, end=end)

    key = tf.strip().upper()

    today = date.today()

    # Presets
    if key == "MTD":
        start = _month_start(today)
        days = (today - start).days + 1
        return ResolvedWindow(duration=_duration_from_days(days), start=start, end=today)

    if key == "YTD":
        start = _year_start(today)
        days = (today - start).days + 1
        return ResolvedWindow(duration=_duration_from_days(days), start=start, end=today)

    # Lowercase presets like 1m/3y/5d etc.
    tfl = tf.strip().lower()

    if tfl == "intraday":
        # a sane default (most people mean "today")
        return ResolvedWindow(duration="1 D")

    m = re.fullmatch(r"(\d+)\s*([dwmy])", tfl)
    if m:
        n = int(m.group(1))
        unit = m.group(2)

        if unit == "d":
            return ResolvedWindow(duration=f"{n} D")
        if unit == "w":
            return ResolvedWindow(duration=f"{n} W")
        if unit == "m":
            return ResolvedWindow(duration=f"{n} M")
        if unit == "y":
            return ResolvedWindow(duration=f"{n} Y")

    raise ValueError(
        f"Unknown tf '{tf}'. Use MTD, YTD, intraday, or one of: "
        f"2d, 5d, 1m, 3m, 6m, 1y, 3y, 5y, 10y; or provide --from/--to."
    )
