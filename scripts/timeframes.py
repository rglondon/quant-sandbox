from dataclasses import dataclass
from datetime import datetime
from typing import Optional

EU_FMT = "%d/%m/%Y"


def parse_eu_date(s: str) -> datetime:
    return datetime.strptime(s, EU_FMT)


def month_start(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def year_start(dt: datetime) -> datetime:
    return dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)


@dataclass
class Window:
    duration: str  # IBKR durationStr, e.g. "10 D", "1 M", "3 Y"


def resolve_window(tf: str, date_from: Optional[str] = None, date_to: Optional[str] = None) -> Window:
    """
    Supports:
      tf: INTRADAY, MTD, YTD, 1m/3m/6m/1y/3y/5y/10y, or rolling windows like 10D, 4W, 2M, 1Y
      date_from/date_to: EU DD/MM/YYYY overrides tf
    """
    if date_from and date_to:
        start = parse_eu_date(date_from)
        end = parse_eu_date(date_to)
        days = max(1, (end - start).days)
        if days <= 365:
            return Window(duration=f"{days} D")
        years = max(1, int(round(days / 365)))
        return Window(duration=f"{years} Y")

    if date_from and not date_to:
        start = parse_eu_date(date_from)
        end = datetime.now()
        days = max(1, (end - start).days)
        if days <= 365:
            return Window(duration=f"{days} D")
        years = max(1, int(round(days / 365)))
        return Window(duration=f"{years} Y")

    now = datetime.now()
    key = tf.strip().upper()

    if key == "INTRADAY":
        return Window(duration="1 D")
    if key == "MTD":
        days = max(1, (now - month_start(now)).days)
        return Window(duration=f"{days} D")
    if key == "YTD":
        days = max(1, (now - year_start(now)).days)
        return Window(duration=f"{days} D")

    allowed = {
        "1M": "1 M",
        "3M": "3 M",
        "6M": "6 M",
        "1Y": "1 Y",
        "3Y": "3 Y",
        "5Y": "5 Y",
        "10Y": "10 Y",
    }
    if key in allowed:
        return Window(duration=allowed[key])

    # rolling windows: 10D, 4W, 2M, 1Y
    if len(key) >= 2 and key[:-1].isdigit() and key[-1] in ("D", "W", "M", "Y"):
        n = int(key[:-1])
        unit = key[-1]
        return Window(duration=f"{n} {unit}")

    raise ValueError(
        f"Unknown tf '{tf}'. Use INTRADAY, MTD, YTD, 1m/3m/6m/1y/3y/5y/10y, or rolling 10D/4W/2M/1Y. "
        f"Or use from/to in DD/MM/YYYY."
    )


def resolve_bar_size(bar: str) -> str:
    """
    Convenience aliases.
    Accepts IBKR-compatible barSizeSetting strings too.
    """
    b = bar.strip().lower()
    m = {"daily": "1 day", "weekly": "1 week", "monthly": "1 month"}
    return m.get(b, bar)
