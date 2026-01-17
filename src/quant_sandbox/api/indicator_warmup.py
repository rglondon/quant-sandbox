# src/quant_sandbox/api/indicator_warmup.py
from __future__ import annotations
import re
from dataclasses import dataclass

@dataclass(frozen=True)
class IbDuration:
    n: int
    unit: str  # "D" | "W" | "M" | "Y"

_DUR_RE = re.compile(r"^\s*(\d+)\s*([DWMY])\s*$", re.I)

def parse_ib_duration(s: str) -> IbDuration:
    m = _DUR_RE.match(str(s or "").strip())
    if not m:
        # fallback – keep behavior predictable
        return IbDuration(3, "Y")
    return IbDuration(int(m.group(1)), m.group(2).upper())

def add_days_to_ib_duration(base: str, extra_days: int) -> str:
    """
    IB duration strings are coarse; easiest safe strategy:
    - convert everything to DAYS approximation and return "X D"
    This avoids mixing units (and avoids month-length ambiguity).
    """
    d = parse_ib_duration(base)
    # approximate units into days (good enough for warmup)
    base_days = {
        "D": d.n,
        "W": d.n * 7,
        "M": d.n * 30,
        "Y": d.n * 365,
    }[d.unit]
    total = max(1, base_days + max(0, int(extra_days)))
    return f"{total} D"

def warmup_days_for_rsi(period: int, bar_size: str) -> int:
    # RSI stabilizes after ~ a few windows; 5x is a good practical warmup
    return max(20, int(period) * 5)

def warmup_days_for_ma(window: int, bar_size: str) -> int:
    return max(20, int(window) * 3)

def warmup_days_for_rolling_window(window_str: str, bar_size: str) -> int:
    """
    window_str examples: "63D", "90D", "3M", "1Y"
    We warm up by ~2x the window.
    """
    m = re.match(r"^\s*(\d+)\s*([DWMY])\s*$", str(window_str).strip(), re.I)
    if not m:
        return 90
    n = int(m.group(1))
    u = m.group(2).upper()
    days = {"D": n, "W": n * 7, "M": n * 30, "Y": n * 365}[u]
    return max(30, days * 2)
