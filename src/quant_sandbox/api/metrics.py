# src/quant_sandbox/api/metrics.py

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Literal, Tuple
from typing import Literal


from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/expr", tags=["expr"])

# ============================================================
# Helpers (duration + warmup correctness)
# ============================================================

def _normalize_spec(spec: str) -> str:
    """
    Accepts:
      - raw tickers: "SPY" -> "stock:SPY"
      - internal specs: "stock:SAP:DE" (leave as-is)
      - canonical tokens: "EQ:SPY", "FX:EURUSD", "IX:DAX.A" -> internal spec via normalize_canonical_symbol()
    """
    s = (spec or "").strip()
    if not s:
        raise ValueError("Empty spec")

    # If the user passed canonical form, normalize through expressions.py
    if re.match(r"^(EQ|FX|IX|BTC|FI)\:", s.strip(), flags=re.IGNORECASE):
        from quant_sandbox.analytics.expressions import normalize_canonical_symbol
        return normalize_canonical_symbol(s)

    # If no ":" assume stock:<ticker>
    if ":" not in s:
        return f"stock:{s.strip().upper()}"

    # Otherwise assume it's already an internal spec (stock:, index:, fx:, future:, futureSel:, etc.)
    return s



def _to_points(s) -> List[dict]:
    """pandas Series -> [{time,value}, ...]  (drops NaN/inf so warmup never reaches UI)"""
    import pandas as pd
    import numpy as np

    if s is None:
        return []

    if not hasattr(s, "index"):
        raise TypeError(f"_to_points expected pandas Series-like, got: {type(s)}")

    s2 = s.dropna()
    if len(s2) == 0:
        return []

    vals = pd.to_numeric(s2, errors="coerce")
    finite_mask = np.isfinite(vals.values)
    if not finite_mask.all():
        s2 = s2[finite_mask]

    return [{"time": ts.isoformat(), "value": float(v)} for ts, v in zip(s2.index.to_pydatetime(), s2.values)]


def _points_to_series(points: List[dict]):
    """[{time,value}, ...] -> pandas Series"""
    import pandas as pd

    idx = pd.to_datetime([p["time"] for p in points])
    return pd.Series([p["value"] for p in points], index=idx).astype("float64")


def _series_block(
    expr: str,
    label: str,
    points: List[dict],
    *,
    unit: Optional[str] = None,
    kind: Optional[str] = None,
    bounds: Optional[List[float]] = None,
) -> dict:
    return {
        "expr": expr,
        "label": label,
        "unit": unit,
        "kind": kind,
        "bounds": bounds,
        "count": int(len(points)),
        "points": points,
    }


# ----------------------------
# Duration policy (per your rule):
#   - "2M" => calendar months
#   - "1Y" => calendar years
#   - "63D" => trading days (for daily bars)
# ----------------------------

def _parse_token(s: str) -> Tuple[int, str]:
    """
    Accepts: "3 Y", "1Y", "30 D", "6 M", "63D", "12W"
    Returns (n, unit_lower) where unit in {"d","w","m","y"}.
    """
    raw = str(s or "").strip().upper().replace(" ", "")
    m = re.fullmatch(r"(\d+)([DWMY])", raw)
    if not m:
        # conservative default
        return (3, "y")
    return (int(m.group(1)), m.group(2).lower())


def _is_daily_bar(bar_size: str) -> bool:
    bs = (bar_size or "").strip().lower()
    return "day" in bs and not ("hour" in bs or "min" in bs)


def _trading_days_to_calendar_days(td: int) -> int:
    # rough-but-safe overfetch conversion, includes weekends buffer
    if td <= 0:
        return 0
    return int((td * 7) / 5) + 5


def _subtract_trading_days(end_ts, n: int):
    """
    Subtract N trading days (Mon-Fri) from a pandas Timestamp.
    """
    import pandas as pd

    t = pd.Timestamp(end_ts)
    remaining = int(max(0, n))
    while remaining > 0:
        t = t - pd.Timedelta(days=1)
        # Monday=0 ... Sunday=6
        if t.weekday() < 5:
            remaining -= 1
    return t


def _cutoff_from_end(end_ts, duration: str, *, bar_size: str) -> "Any":
    """
    Compute cutoff timestamp for trimming to requested window ending at end_ts.
    - D => trading days (for daily bars)
    - M/Y => calendar offsets
    - W => calendar weeks (consistent with "2m calendar days" rule family)
    """
    import pandas as pd

    n, u = _parse_token(duration)
    end_ts = pd.Timestamp(end_ts)

    if u == "d":
        if _is_daily_bar(bar_size):
            return _subtract_trading_days(end_ts, n)
        # future-proof: if not daily, interpret "D" as calendar days
        return end_ts - pd.Timedelta(days=n)

    if u == "w":
        return end_ts - pd.DateOffset(weeks=n)
    if u == "m":
        return end_ts - pd.DateOffset(months=n)
    if u == "y":
        return end_ts - pd.DateOffset(years=n)

    return end_ts - pd.DateOffset(years=3)


def _duration_fetch_calendar_days(duration: str, *, bar_size: str) -> int:
    """
    Convert requested duration to a conservative *calendar day count* for IB fetch sizing.
    This does NOT define trimming; trimming uses _cutoff_from_end().
    """
    n, u = _parse_token(duration)
    if u == "d":
        if _is_daily_bar(bar_size):
            return _trading_days_to_calendar_days(n)
        return n
    if u == "w":
        return n * 7
    if u == "m":
        return n * 31
    if u == "y":
        return n * 366
    return 3 * 366


def _days_to_ib_duration(days: int) -> str:
    """
    IB duration strings: prefer D for <= ~365, otherwise Y.
    """
    d = int(max(1, days))
    if d <= 365:
        return f"{d} D"
    y = int((d + 364) // 365)
    return f"{y} Y"


def _window_to_warmup_bars(window: str, *, bar_size: str, min_bars: int = 10) -> int:
    """
    Convert rolling window spec to required warmup bars for daily bars:
      - "63D" => 63 bars (trading days)
      - "3M"  => calendar months; approximate to 3*21 trading days for warmup bars
      - "12W" => 12*5 trading days approx
    For non-daily bars, we return a conservative value.
    """
    n, u = _parse_token(window)
    if not _is_daily_bar(bar_size):
        # conservative fallback
        if u == "d":
            return max(min_bars, n)
        if u == "w":
            return max(min_bars, n * 7)
        if u == "m":
            return max(min_bars, n * 31)
        if u == "y":
            return max(min_bars, n * 366)
        return max(min_bars, 90)

    # Daily bar policy (your rule):
    if u == "d":
        return max(min_bars, n)            # trading-day bars
    if u == "w":
        return max(min_bars, n * 5)        # approx trading days
    if u == "m":
        return max(min_bars, n * 21)       # approx trading days
    if u == "y":
        return max(min_bars, n * 252)      # approx trading days
    return max(min_bars, 63)


def _fetch_extended_base_series(
    req: Request,
    *,
    expr: str,
    duration: str,
    bar_size: str,
    use_rth: bool,
    warmup_bars: int = 0,
) -> dict:
    """
    Fetch base price series with extra history for indicator warmup.
    Fetch sizing uses conservative calendar days, then converts to IB duration.
    """
    from datetime import datetime  # noqa: F401  (kept for potential future use)

    req_days_cal = _duration_fetch_calendar_days(duration, bar_size=bar_size)
    warmup_days_cal = 0

    if warmup_bars > 0:
        # For daily bars, warmup_bars is trading days; convert to calendar days for fetch.
        if _is_daily_bar(bar_size):
            warmup_days_cal = _trading_days_to_calendar_days(warmup_bars)
        else:
            # future-proof conservative conversion
            warmup_days_cal = int(max(0, warmup_bars))

    fetch_days = int(req_days_cal + warmup_days_cal)
    fetch_duration = _days_to_ib_duration(fetch_days)

    return expr_series(
        req,
        ExprSeriesRequest(
            expr=expr,
            duration=fetch_duration,
            bar_size=bar_size,
            use_rth=use_rth,
        ),
    )


# ============================================================
# /expr/close
# ============================================================

class CloseSeriesRequest(BaseModel):
    spec: str = Field(..., description="e.g. 'SPY', 'stock:SPY', 'fx:EURUSD'")
    duration: str
    bar_size: str
    use_rth: bool = True


@router.post("/close")
def expr_close(req: Request, payload: CloseSeriesRequest) -> dict:
    worker = req.app.state.ibkr_worker
    spec_in = payload.spec.strip()

    # NEW: accept canonical tokens (EQ:/FX:/IX:/BTC:/FI:) in /close too
    try:
        from quant_sandbox.analytics.expressions import normalize_canonical_symbol

        if re.match(r"^(EQ|FX|IX|BTC|FI)\:", spec_in.strip().upper()):
            internal_spec = normalize_canonical_symbol(spec_in)
        else:
            internal_spec = _normalize_spec(spec_in)
    except Exception:
        internal_spec = _normalize_spec(spec_in)

    try:
        use_rth = payload.use_rth
        if internal_spec.lower().startswith(("future:", "futuresel:", "futurecode:")):
            use_rth = False

        s = worker.fetch_close_series(
            internal_spec,
            duration=payload.duration,
            bar_size=payload.bar_size,
            use_rth=use_rth,
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail={"error": str(e), "spec": payload.spec})

    points = _to_points(s)

    return {
        "spec": payload.spec,
        "internal_spec": internal_spec,
        "count": int(len(points)),
        "points": points,
    }



# ============================================================
# /expr/series
# ============================================================

class ExprSeriesRequest(BaseModel):
    expr: str = Field(..., description="EQ:SPY | (EQ:SPY/EQ:QQQ)")
    duration: str
    bar_size: str
    use_rth: bool = True
    start: Optional[str] = Field(None, description="ISO8601 inclusive")
    end: Optional[str] = Field(None, description="ISO8601 inclusive")


@router.post("/series")
def expr_series(req: Request, payload: ExprSeriesRequest) -> dict:
    worker = req.app.state.ibkr_worker
    expr = payload.expr.strip()

    try:
        from quant_sandbox.analytics.expressions import (
            normalize_expr_symbols,
            normalize_canonical_symbol,
        )
        import pandas as pd

        rewritten, symbols = normalize_expr_symbols(expr)

        if not symbols:
            if expr.lower().startswith(("stock:", "etf:", "index:", "fx:", "future:", "futuresel:")):
                symbols = [expr]
                rewritten = "s0"
            else:
                raise ValueError("No canonical symbols found. Use tokens like EQ:SPY, FX:EURUSD, IX:DAX.1")

        env: dict[str, pd.Series] = {}
        label_parts: list[str] = []

        for i, sym in enumerate(symbols):
            if ":" in sym and sym.split(":", 1)[0].lower() in {"stock", "etf", "index", "fx", "future", "futuresel"}:
                internal_spec = sym
            else:
                internal_spec = normalize_canonical_symbol(sym)

            label_parts.append(internal_spec)

            s = worker.fetch_close_series(
                internal_spec,
                duration=payload.duration,
                bar_size=payload.bar_size,
                use_rth=payload.use_rth,
            )

            if s is None or len(s) == 0:
                raise ValueError(f"No data returned for '{sym}' ({internal_spec})")

            env[f"s{i}"] = s.astype("float64")

        df = None
        for k, s in env.items():
            if df is None:
                df = s.rename(k).to_frame()
            else:
                # inner join ensures valid arithmetic alignment
                df = df.join(s.rename(k).to_frame(), how="inner")

        if df is None or df.empty:
            raise ValueError("No overlapping timestamps across symbols (alignment produced empty series).")

        local_env = {k: df[k] for k in df.columns}
        result = eval(rewritten, {"__builtins__": {}}, local_env)

        if not hasattr(result, "index"):
            raise ValueError("Expression did not produce a time series result.")

        out = result.dropna()

        if payload.start:
            out = out[out.index >= pd.to_datetime(payload.start)]
        if payload.end:
            out = out[out.index <= pd.to_datetime(payload.end)]

        label = rewritten
        for i, internal_spec in enumerate(label_parts):
            label = label.replace(f"s{i}", internal_spec)

    except Exception as e:
        msg = str(e).strip()
        if not msg:
            msg = f"{type(e).__name__}: {repr(e)}"
        raise HTTPException(status_code=400, detail={"error": msg, "expr": expr})

    points = _to_points(out)

    # Unit policy: reliable only for single instrument; otherwise it's an index/expression.
    unit = "price" if len(symbols) == 1 else "index"

    series0 = {
        "expr": expr,
        "label": label,
        "unit": unit,
        "kind": "price" if unit == "price" else "index",
        "bounds": None,
        "count": int(len(points)),
        "points": points,
    }

    return {
        "expr": expr,
        "label": label,
        "unit": unit,
        "count": int(len(points)),
        "points": points,
        "series": [series0],
        "meta": {"unit": unit},
    }


# ============================================================
# /expr/chart
# ============================================================
ChartMode = Literal["line", "ohlc"]

class OHLCVRange(BaseModel):
    start: str
    end: str

class ExprChartRequest(BaseModel):
    expr: str = Field(..., description="Expression like EQ:SPY or (EQ:SPY/EQ:QQQ)")
    # existing (line mode)
    duration: str
    bar_size: str
    use_rth: bool = True
    start: Optional[str] = None
    end: Optional[str] = None
    # NEW (ohlc mode)
    mode: ChartMode = "line"
    ohlcv_range: Optional[OHLCVRange] = None
    resolution: str = "1D"
    include_volume: bool = True
    max_bars: int = 5000
    tz: str = "Europe/London"


@router.post("/chart")
def expr_chart(req: Request, payload: ExprChartRequest) -> dict:
    # -----------------------------
    # NEW: OHLC mode (candles)
    # -----------------------------
    if getattr(payload, "mode", "line") == "ohlc":
        expr = (payload.expr or "").strip()

        # Only allow a single canonical symbol for now (no arithmetic expressions)
        if not re.match(r"^(EQ|FX|IX):[A-Za-z0-9\.\-_]+$", expr):
            raise HTTPException(
                status_code=400,
                detail="mode='ohlc' currently supports only a single symbol like EQ:SPY / FX:EURUSD / IX:ES.A (no arithmetic expressions yet).",
            )

        if payload.ohlcv_range is None:
            raise HTTPException(
                status_code=400,
                detail="mode='ohlc' requires ohlcv_range: {start, end}",
            )

        worker = getattr(req.app.state, "ibkr_worker", None)
        if worker is None:
            raise HTTPException(status_code=500, detail="IBKR worker not initialized (req.app.state.ibkr_worker missing)")

        bars = worker.get_ohlcv(
            symbol=expr,
            start=payload.ohlcv_range.start,
            end=payload.ohlcv_range.end,
            resolution=payload.resolution,
            tz=payload.tz,
            max_bars=payload.max_bars,
            include_volume=payload.include_volume,
        )

        return {
            "mode": "ohlc",
            "expr": expr,
            "resolution": payload.resolution,
            "tz": payload.tz,
            "bars": bars,
        }

    # -----------------------------
    # Existing behavior (line mode)
    # -----------------------------
    return expr_series(
        req,
        ExprSeriesRequest(
            expr=payload.expr,
            duration=payload.duration,
            bar_size=payload.bar_size,
            use_rth=payload.use_rth,
            start=payload.start,
            end=payload.end,
        ),
    )



# ============================================================
# /expr/rsi  (backend-authoritative, with warmup + correct trim)
# ============================================================

class RsiRequest(BaseModel):
    expr: str
    period: int = Field(14, ge=2, le=200)

    levels: Optional[List[float]] = Field(
        default=None,
        description="Optional explicit RSI levels. If provided, 'bands' preset is ignored.",
    )

    bands: Optional[str] = Field(
        default="classic",
        description="classic|strict|full|none (ignored if 'levels' is provided)",
    )

    duration: str
    bar_size: str
    use_rth: bool = True


@router.post("/rsi")
def expr_rsi(req: Request, payload: RsiRequest) -> dict:
    from quant_sandbox.analytics.ta import rsi_wilder
    import pandas as pd

    # Warmup policy: Wilder RSI needs a decent buffer to converge.
    warmup_bars = max(60, int(payload.period) * 10)  # trading-day bars for daily bars

    base = _fetch_extended_base_series(
        req,
        expr=payload.expr,
        duration=payload.duration,
        bar_size=payload.bar_size,
        use_rth=payload.use_rth,
        warmup_bars=warmup_bars,
    )

    values = _points_to_series(base["series"][0]["points"])
    rsi = rsi_wilder(values, payload.period)

    # drop NaN warmup, clip, then trim to requested window (duration semantics)
    rsi_formed = rsi.dropna().astype("float64").clip(lower=0.0, upper=100.0)

    if len(rsi_formed) > 0:
        end_ts = rsi_formed.index[-1]
        cutoff = _cutoff_from_end(end_ts, payload.duration, bar_size=payload.bar_size)
        rsi_formed = rsi_formed[rsi_formed.index >= cutoff]

    rsi_points = _to_points(rsi_formed)

    # resolve levels from explicit list or preset
    if payload.levels is not None:
        levels = [float(x) for x in payload.levels]
    else:
        preset = (payload.bands or "classic").lower()
        if preset == "none":
            levels = []
        elif preset == "classic":
            levels = [70.0, 30.0]
        elif preset == "strict":
            levels = [80.0, 20.0]
        elif preset == "full":
            levels = [80.0, 70.0, 50.0, 30.0, 20.0]
        else:
            raise HTTPException(
                status_code=400,
                detail={"error": f"Unknown bands preset: {payload.bands}. Use classic|strict|full|none."},
            )

    series_out = [
        {
            "expr": payload.expr,
            "label": f"RSI({payload.period}) {base['label']}",
            "unit": "index",
            "kind": "oscillator",
            "bounds": [0.0, 100.0],
            "count": int(len(rsi_points)),
            "points": rsi_points,
        }
    ]

    # Align level lines to trimmed RSI index only
    idx = rsi_formed.index
    for lvl in levels:
        lvl_points = [{"time": ts.isoformat(), "value": float(lvl)} for ts in idx.to_pydatetime()]
        series_out.append(
            {
                "expr": payload.expr,
                "label": f"RSI level {lvl:g}",
                "unit": "index",
                "kind": "overlay",
                "bounds": [0.0, 100.0],
                "count": int(len(lvl_points)),
                "points": lvl_points,
            }
        )

    if len(rsi_formed):
        last_time = rsi_formed.index[-1].isoformat()
        last_value = float(rsi_formed.iloc[-1])
    else:
        last_time = None
        last_value = None

    return {
        "expr": payload.expr,
        "base_label": base["label"],
        "period": payload.period,
        "bands": (payload.bands or "classic"),
        "levels": levels,
        "last": {"time": last_time, "value": last_value},
        "series": series_out,
        "meta": {
            "kind": "panel",
            "panel": "rsi",
            "unit": "index",
            "bounds": [0.0, 100.0],
            "bar_size": payload.bar_size,
            "duration": payload.duration,
            "use_rth": payload.use_rth,
        },
    }


# ============================================================
# /expr/ma  (SMA / EMA overlays)  (warmup + correct trim)
# ============================================================

class MaRequest(BaseModel):
    expr: str
    ma: Literal["sma", "ema"] = Field(..., description="sma|ema")
    window: int = Field(..., ge=2, le=2000)
    duration: str
    bar_size: str
    use_rth: bool = True


@router.post("/ma")
def expr_ma(req: Request, payload: MaRequest) -> dict:
    from quant_sandbox.analytics.ta import sma as _sma, ema as _ema

    # warmup bars roughly equals window for SMA/EMA; add small buffer
    warmup_bars = int(max(20, payload.window + 10))

    base = _fetch_extended_base_series(
        req,
        expr=payload.expr,
        duration=payload.duration,
        bar_size=payload.bar_size,
        use_rth=payload.use_rth,
        warmup_bars=warmup_bars,
    )

    pts = base["series"][0]["points"]
    if not pts:
        raise HTTPException(status_code=400, detail={"error": "No data returned", "expr": payload.expr})

    values = _points_to_series(pts)

    if payload.ma == "sma":
        out = _sma(values, payload.window)
        label = f"SMA ({payload.window})"
    else:
        out = _ema(values, payload.window)
        label = f"EMA ({payload.window})"

    out = out.dropna().astype("float64")

    if len(out) > 0:
        end_ts = out.index[-1]
        cutoff = _cutoff_from_end(end_ts, payload.duration, bar_size=payload.bar_size)
        out = out[out.index >= cutoff]

    out_points = _to_points(out)

    return {
        "expr": payload.expr,
        "base_label": base["series"][0]["label"],
        "ma": payload.ma,
        "window": payload.window,
        "series": [
            _series_block(
                payload.expr,
                label,
                out_points,
                unit="price",
                kind="overlay",
                bounds=None,
            )
        ],
        "meta": {
            "kind": "overlay",
            "overlay_on": "price",
            "bar_size": payload.bar_size,
            "duration": payload.duration,
            "use_rth": payload.use_rth,
        },
    }


# ============================================================
# /expr/bollinger  (BBands)  (FIXED: no raw_points)
# ============================================================

class BollingerRequest(BaseModel):
    expr: str
    period: int = Field(20, ge=2, le=200)
    sigma: float = Field(2.0, ge=0.1, le=10.0)
    duration: str
    bar_size: str
    use_rth: bool = True


@router.post("/bollinger")
def expr_bollinger(req: Request, payload: BollingerRequest) -> dict:
    base = expr_series(
        req,
        ExprSeriesRequest(
            expr=payload.expr,
            duration=payload.duration,
            bar_size=payload.bar_size,
            use_rth=payload.use_rth,
        ),
    )

    import pandas as pd

    # FIX: base has "points" and "series[0].points" — not "raw_points"
    values = _points_to_series(base["series"][0]["points"])

    ma = values.rolling(window=payload.period, min_periods=payload.period).mean()
    sd = values.rolling(window=payload.period, min_periods=payload.period).std()

    upper = ma + payload.sigma * sd
    lower = ma - payload.sigma * sd

    df = pd.DataFrame({"ma": ma, "upper": upper, "lower": lower}).dropna()

    ma_points = _to_points(df["ma"])
    upper_points = _to_points(df["upper"])
    lower_points = _to_points(df["lower"])

    series_out = [
        {"expr": payload.expr, "label": f"BB mid ({payload.period})", "count": int(len(ma_points)), "points": ma_points},
        {"expr": payload.expr, "label": f"BB upper ({payload.period}, {payload.sigma}\u03c3)", "count": int(len(upper_points)), "points": upper_points},
        {"expr": payload.expr, "label": f"BB lower ({payload.period}, {payload.sigma}\u03c3)", "count": int(len(lower_points)), "points": lower_points},
    ]

    return {
        "expr": payload.expr,
        "base_label": base["label"],
        "period": payload.period,
        "sigma": payload.sigma,
        "series": series_out,
        "meta": {
            "kind": "overlay",
            "overlay_on": "price",
            "bar_size": payload.bar_size,
            "duration": payload.duration,
            "use_rth": payload.use_rth,
        },
    }


# ============================================================
# /expr/drawdown
# ============================================================

class DrawdownRequest(BaseModel):
    expr: str
    duration: str
    bar_size: str
    use_rth: bool = True

    mode: str = Field("point", pattern="^(point|rolling_max|worst_n_day)$")
    rolling_window: Optional[str] = None
    n_days: Optional[int] = Field(None, ge=1, le=252)


def _point_drawdown(values):
    running_max = values.cummax()
    return (values / running_max) - 1.0


def _window_mdd(prices):
    import numpy as np

    x = prices.values
    peak = np.maximum.accumulate(x)
    dd = (x / peak) - 1.0
    return float(np.min(dd))


def _rolling_max_drawdown(values, window: str):
    import pandas as pd

    window = window.strip().upper()
    m = re.fullmatch(r"(\d+)\s*M", window)
    if m:
        months = int(m.group(1))
        out: list[float] = []
        idx = values.index
        for t in idx:
            start = t - pd.DateOffset(months=months)
            w = values.loc[start:t]
            if len(w) < 2:
                out.append(float("nan"))
            else:
                out.append(_window_mdd(w))
        return pd.Series(out, index=idx, dtype="float64")

    def apply_mdd(s: pd.Series) -> float:
        if len(s) < 2:
            return float("nan")
        return _window_mdd(s)

    return values.rolling(window=window, min_periods=2).apply(apply_mdd, raw=False)


def _worst_n_day_return(values, n: int):
    ret_n = (values / values.shift(n)) - 1.0
    worst_so_far = ret_n.expanding(min_periods=1).min()
    return worst_so_far


@router.post("/drawdown")
def expr_drawdown(req: Request, payload: DrawdownRequest) -> dict:
    base = expr_chart(
        req,
        ExprChartRequest(
            expr=payload.expr,
            duration=payload.duration,
            bar_size=payload.bar_size,
            use_rth=payload.use_rth,
        ),
    )

    price_points = base["series"][0]["points"]
    if not price_points:
        raise HTTPException(status_code=400, detail={"error": "No data returned", "expr": payload.expr})

    values = _points_to_series(price_points)

    if payload.mode == "rolling_max":
        if not payload.rolling_window:
            raise HTTPException(status_code=400, detail={"error": "rolling_window is required for mode='rolling_max'"})
        dd = _rolling_max_drawdown(values, payload.rolling_window)
        label = f"Rolling Max Drawdown ({payload.rolling_window}) %"
        kind = "rolling_max"

    elif payload.mode == "worst_n_day":
        if not payload.n_days:
            raise HTTPException(status_code=400, detail={"error": "n_days is required for mode='worst_n_day'"})
        dd = _worst_n_day_return(values, payload.n_days)
        label = f"Worst {payload.n_days}D Return (min) %"
        kind = "worst_n_day"

    else:
        dd = _point_drawdown(values)
        label = "Drawdown (%)"
        kind = "point"

    dd_pct = (dd * 100.0).dropna()
    points = _to_points(dd_pct)

    worst_value = float(dd_pct.min()) if len(dd_pct) else 0.0
    worst_time = dd_pct.idxmin().isoformat() if len(dd_pct) else None

    current_value = float(dd_pct.iloc[-1]) if len(dd_pct) else 0.0
    current_time = dd_pct.index[-1].isoformat() if len(dd_pct) else None

    return {
        "expr": payload.expr,
        "base_label": base["series"][0]["label"],
        "mode": payload.mode,
        "rolling_window": payload.rolling_window,
        "n_days": payload.n_days,
        "series": [{"expr": payload.expr, "label": label, "count": int(len(points)), "points": points}],
        "stats": {
            "worst_value_pct": worst_value,
            "worst_time": worst_time,
            "current_value_pct": current_value,
            "current_time": current_time,
        },
        "meta": {
            "kind": "panel",
            "panel": "drawdown",
            "drawdown_kind": kind,
            "bar_size": payload.bar_size,
            "duration": payload.duration,
            "use_rth": payload.use_rth,
        },
    }


# ============================================================
# /expr/sharpe  (warmup + correct trim; 63D means trading-day bars for daily bars)
# ============================================================

class SharpeRequest(BaseModel):
    expr: str

    duration: str = Field("3 Y", description="Defaults to 3 Y")
    bar_size: str = Field("1 day", description="Defaults to 1 day")
    use_rth: bool = True

    window: str = Field("63D", description="Rolling window, e.g. 63D, 12W, 3M")

    clean: bool = Field(True, description="Drop outlier daily returns (bad prints / roll artifacts)")
    max_abs_ret: float = Field(0.15, ge=0.001, le=5.0, description="Max abs daily return allowed when clean=true")

    annualization: Optional[float] = Field(
        None,
        ge=1.0,
        le=2000.0,
        description="Annualization factor override (e.g. 252 for daily). If omitted, inferred from bar_size.",
    )


def _infer_annualization(bar_size: str) -> float:
    s = (bar_size or "").strip().lower()
    if "week" in s:
        return 52.0
    if "month" in s:
        return 12.0
    return 252.0


def _rolling_sharpe(prices, window: str, ann_factor: float, *, bar_size: str):
    import numpy as np
    import pandas as pd

    w_raw = (window or "").strip()
    w = w_raw.upper().replace(" ", "")
    if not w:
        raise ValueError("window must be provided (e.g. 63D, 12W, 3M)")

    ret = prices.pct_change()

    # Monthly window => calendar months (handled by explicit loop)
    m = re.fullmatch(r"(\d+)M", w)
    if m:
        months = int(m.group(1))
        out = []
        idx = ret.index
        for t in idx:
            start = t - pd.DateOffset(months=months)
            r = ret.loc[start:t].dropna()
            if len(r) < 3:
                out.append(float("nan"))
                continue
            mu = float(r.mean())
            sd = float(r.std(ddof=1))
            if (not np.isfinite(sd)) or sd == 0.0:
                out.append(float("nan"))
            else:
                out.append((mu / sd) * float(np.sqrt(ann_factor)))
        return pd.Series(out, index=idx, dtype="float64")

    # 63D policy: trading days (bars) when daily bars
    d = re.fullmatch(r"(\d+)D", w)
    if d and _is_daily_bar(bar_size):
        n = int(d.group(1))
        mu = ret.rolling(window=n, min_periods=3).mean()
        sd = ret.rolling(window=n, min_periods=3).std(ddof=1)
        return ((mu / sd) * float(np.sqrt(ann_factor))).astype("float64")

    # Otherwise use time-based rolling if string looks like offset (e.g. 12W)
    mu = ret.rolling(window=w, min_periods=3).mean()
    sd = ret.rolling(window=w, min_periods=3).std(ddof=1)
    sharpe = (mu / sd) * float(np.sqrt(ann_factor))
    return sharpe.astype("float64")


@router.post("/sharpe")
def expr_sharpe(req: Request, payload: SharpeRequest) -> dict:
    # Warmup: same sizing rule as z-score; buffer is important for stability.
    warmup_bars = _window_to_warmup_bars(payload.window, bar_size=payload.bar_size, min_bars=20) + 40

    base = _fetch_extended_base_series(
        req,
        expr=payload.expr,
        duration=payload.duration,
        bar_size=payload.bar_size,
        use_rth=payload.use_rth,
        warmup_bars=warmup_bars,
    )

    price_points = base["series"][0]["points"]
    if not price_points:
        raise HTTPException(status_code=400, detail={"error": "No data returned", "expr": payload.expr})

    values = _points_to_series(price_points)

    dropped = 0
    if payload.clean:
        r = values.pct_change()
        bad = r.abs() > float(payload.max_abs_ret)
        dropped = int(bad.sum(skipna=True))
        values = values[~bad.fillna(False)]

    ann = float(payload.annualization) if payload.annualization is not None else _infer_annualization(payload.bar_size)

    sharpe = _rolling_sharpe(values, payload.window, ann_factor=ann, bar_size=payload.bar_size).dropna().astype("float64")

    # trim to requested duration
    if len(sharpe) > 0:
        end_ts = sharpe.index[-1]
        cutoff = _cutoff_from_end(end_ts, payload.duration, bar_size=payload.bar_size)
        sharpe = sharpe[sharpe.index >= cutoff]

    points = _to_points(sharpe)

    if len(sharpe):
        last_time = sharpe.index[-1].isoformat()
        last_val = float(sharpe.iloc[-1])
        min_val = float(sharpe.min())
        max_val = float(sharpe.max())
    else:
        last_time = None
        last_val = None
        min_val = None
        max_val = None

    return {
        "expr": payload.expr,
        "base_label": base["series"][0]["label"],
        "window": payload.window,
        "annualization": ann,
        "series": [{"expr": payload.expr, "label": f"Rolling Sharpe ({payload.window})", "count": int(len(points)), "points": points}],
        "stats": {
            "last": last_val,
            "last_time": last_time,
            "min": min_val,
            "max": max_val,
            "clean": {"enabled": bool(payload.clean), "dropped_points": dropped, "max_abs_ret": float(payload.max_abs_ret)},
        },
        "meta": {
            "kind": "panel",
            "panel": "sharpe",
            "bar_size": payload.bar_size,
            "duration": payload.duration,
            "use_rth": payload.use_rth,
        },
    }


# ============================================================
# /expr/analyze  (console + Excel friendly)
# ============================================================

class AnalyzeRequest(BaseModel):
    expr: str
    duration: Optional[str] = Field(None, description="Defaults to '3 Y' if omitted")
    bar_size: Optional[str] = Field(None, description="Defaults to '1 day' if omitted")
    use_rth: Optional[bool] = Field(None, description="Defaults based on whether expr resolves to futures")
    want: List[str] = Field(default_factory=lambda: ["price"])


def _infer_use_rth_for_expr(expr: str, default: bool = True) -> bool:
    e = (expr or "").lower()
    if "ix:" in e:
        if re.search(r"ix:[a-z0-9]+(\.a|\.\d+)", e):
            return False
        if re.search(r"ix:[a-z]+[a-z]\d{2}", e):
            return False
    if "future:" in e or "futuresel:" in e:
        return False
    return default


def _parse_rsi_spec(s: str) -> Dict[str, Any]:
    m = re.fullmatch(r"rsi\((.*)\)", s.strip().lower())
    if not m:
        raise ValueError(f"Bad RSI spec: {s}")

    inner = m.group(1).strip()
    if not inner:
        return {"period": 14, "levels": None, "bands": "classic"}

    parts = [p.strip() for p in inner.split(",") if p.strip()]
    period = 14
    levels = None
    bands = "classic"

    if parts and re.fullmatch(r"\d+", parts[0]):
        period = int(parts[0])
        parts = parts[1:]

    for p in parts:
        if p.startswith("levels="):
            raw = p.split("=", 1)[1].strip()
            lvl = []
            if raw:
                for x in raw.replace("|", ",").split(","):
                    x = x.strip()
                    if x:
                        lvl.append(float(x))
            levels = lvl
        elif p.startswith("bands="):
            bands = p.split("=", 1)[1].strip() or "classic"

    return {"period": period, "levels": levels, "bands": bands}


def _parse_bb_spec(s: str) -> Dict[str, Any]:
    m = re.fullmatch(r"bb\((.*)\)", s.strip().lower())
    if not m:
        raise ValueError(f"Bad BB spec: {s}")

    inner = m.group(1).strip()
    if not inner:
        return {"period": 20, "sigma": 2.0}

    parts = [p.strip() for p in inner.split(",") if p.strip()]
    period = int(parts[0]) if parts and re.fullmatch(r"\d+", parts[0]) else 20
    sigma = float(parts[1]) if len(parts) >= 2 else 2.0
    return {"period": period, "sigma": sigma}


def _parse_maxdd_spec(s: str) -> str:
    m = re.fullmatch(r"maxdd\((.*)\)", s.strip().lower())
    if not m:
        raise ValueError(f"Bad maxdd spec: {s}")
    w = m.group(1).strip().upper()
    return w or "3M"


def _parse_worst_spec(s: str) -> int:
    m = re.fullmatch(r"worst\((.*)\)", s.strip().lower())
    if not m:
        raise ValueError(f"Bad worst spec: {s}")
    inner = m.group(1).strip().upper().replace(" ", "")
    mm = re.fullmatch(r"(\d+)D", inner)
    if not mm:
        raise ValueError(f"Bad worst() window: {s} (use worst(1D), worst(5D), etc.)")
    return int(mm.group(1))


@router.post("/analyze")
def expr_analyze(req: Request, payload: AnalyzeRequest) -> dict:
    expr = payload.expr.strip()

    duration = payload.duration or "3 Y"
    bar_size = payload.bar_size or "1 day"

    use_rth = _infer_use_rth_for_expr(expr, default=True) if payload.use_rth is None else bool(payload.use_rth)
    want = [w.strip() for w in (payload.want or ["price"]) if w.strip()] or ["price"]

    series_out: List[dict] = []
    stats_out: Dict[str, Any] = {}

    base_price = None
    base_label = None

    def ensure_price():
        nonlocal base_price, base_label
        if base_price is None:
            base_price = expr_chart(
                req,
                ExprChartRequest(expr=expr, duration=duration, bar_size=bar_size, use_rth=use_rth),
            )
            base_label = base_price["series"][0]["label"]
        return base_price

    def append_series_block(block: dict):
        if "series" in block:
            series_out.extend(block["series"])
        elif "points" in block:
            series_out.append(
                {
                    "expr": expr,
                    "label": block.get("label", "series"),
                    "count": block.get("count", len(block["points"])),
                    "points": block["points"],
                }
            )

    for w in want:
        wl = w.lower()

        if wl == "price":
            p = ensure_price()
            append_series_block(p)
            continue

        if wl.startswith("rsi("):
            ensure_price()
            rsi_args = _parse_rsi_spec(w)

            # allow extra numeric levels like rsi(14, 80, 20) as convenience
            if rsi_args.get("levels") is not None:
                inner = re.fullmatch(r"rsi\((.*)\)", w.strip(), flags=re.IGNORECASE).group(1)
                parts = [p.strip() for p in inner.split(",") if p.strip()]
                if parts and re.fullmatch(r"\d+", parts[0]):
                    parts = parts[1:]
                extra_nums = []
                for p2 in parts:
                    if re.fullmatch(r"\d+(\.\d+)?", p2) and not p2.startswith("levels=") and not p2.startswith("bands="):
                        extra_nums.append(float(p2))
                if extra_nums:
                    rsi_args["levels"].extend(extra_nums)

            rsi_block = expr_rsi(
                req,
                RsiRequest(
                    expr=expr,
                    period=rsi_args.get("period", 14),
                    levels=rsi_args.get("levels"),
                    bands=rsi_args.get("bands", "classic"),
                    duration=duration,
                    bar_size=bar_size,
                    use_rth=use_rth,
                ),
            )
            append_series_block(rsi_block)

            last = rsi_block.get("last")
            if last and last.get("value") is not None:
                stats_out[f"rsi_{rsi_args.get('period',14)}_last"] = float(last["value"])
                stats_out["rsi_last_time"] = last.get("time")
            continue

        if wl.startswith("bb("):
            ensure_price()
            bb_args = _parse_bb_spec(w)
            boll = expr_bollinger(
                req,
                BollingerRequest(
                    expr=expr,
                    period=bb_args["period"],
                    sigma=bb_args["sigma"],
                    duration=duration,
                    bar_size=bar_size,
                    use_rth=use_rth,
                ),
            )
            append_series_block(boll)
            continue

        if wl.startswith("maxdd("):
            ensure_price()
            window = _parse_maxdd_spec(w)
            dd_block = expr_drawdown(
                req,
                DrawdownRequest(
                    expr=expr,
                    duration=duration,
                    bar_size=bar_size,
                    use_rth=use_rth,
                    mode="rolling_max",
                    rolling_window=window,
                    n_days=None,
                ),
            )
            append_series_block(dd_block)
            st = dd_block.get("stats", {})
            if "worst_value_pct" in st:
                stats_out[f"maxdd_{window}_worst_pct"] = float(st["worst_value_pct"])
            if "current_value_pct" in st:
                stats_out[f"maxdd_{window}_current_pct"] = float(st["current_value_pct"])
            continue

        if wl.startswith("worst("):
            ensure_price()
            n = _parse_worst_spec(w)
            dd_block = expr_drawdown(
                req,
                DrawdownRequest(
                    expr=expr,
                    duration=duration,
                    bar_size=bar_size,
                    use_rth=use_rth,
                    mode="worst_n_day",
                    rolling_window=None,
                    n_days=n,
                ),
            )
            append_series_block(dd_block)
            st = dd_block.get("stats", {})
            if "worst_value_pct" in st:
                stats_out[f"worst_{n}d_return_pct"] = float(st["worst_value_pct"])
                stats_out[f"worst_{n}d_time"] = st.get("worst_time")
            continue

        raise HTTPException(status_code=400, detail={"error": f"Unknown want item: {w}"})

    return {
        "expr": expr,
        "series": series_out,
        "stats": stats_out,
        "meta": {
            "duration": duration,
            "bar_size": bar_size,
            "use_rth": use_rth,
            "base_label": base_label,
            "want": want,
        },
    }


# ============================================================
# Cleaning helpers
# ============================================================

def _clean_bad_prints(values, max_abs_ret: float = 0.25):
    s = values.astype("float64").copy()
    ret = s.pct_change()
    bad = (ret.abs() > float(max_abs_ret)).fillna(False)
    dropped = int(bad.sum())
    s = s[~bad].dropna()
    return s, {"max_abs_ret": float(max_abs_ret), "dropped_points": dropped}


# ============================================================
# /expr/stats
# ============================================================

class ExprStatsRequest(BaseModel):
    expr: str
    duration: str = Field("3 Y", description="Default 3Y")
    bar_size: str = Field("1 day")
    use_rth: bool = True
    clean: bool = Field(True, description="Drop obvious bad prints")
    max_abs_ret: float = Field(0.25, ge=0.01, le=2.0, description="Bad print threshold (abs return)")
    rolling_highlow_days: int = Field(252, ge=5, le=5000)
    worst_return_windows: List[int] = Field(default_factory=lambda: [1, 5])


def _max_drawdown(values):
    running_max = values.cummax()
    dd = (values / running_max) - 1.0
    return dd.min(), dd


@router.post("/stats")
def expr_stats(req: Request, payload: ExprStatsRequest) -> dict:
    import numpy as np

    base = expr_chart(
        req,
        ExprChartRequest(
            expr=payload.expr,
            duration=payload.duration,
            bar_size=payload.bar_size,
            use_rth=payload.use_rth,
        ),
    )

    pts = base["series"][0]["points"]
    if not pts:
        raise HTTPException(status_code=400, detail={"error": "No data returned", "expr": payload.expr})

    values = _points_to_series(pts)

    clean_meta = {"enabled": bool(payload.clean), "dropped_points": 0, "max_abs_ret": payload.max_abs_ret}
    if payload.clean:
        values, cm = _clean_bad_prints(values, max_abs_ret=payload.max_abs_ret)
        clean_meta.update(cm)

    if len(values) < 5:
        raise HTTPException(status_code=400, detail={"error": "Not enough data after cleaning", "expr": payload.expr})

    last = float(values.iloc[-1])
    last_time = values.index[-1].isoformat()
    vmin = float(values.min())
    vmax = float(values.max())

    n = int(payload.rolling_highlow_days)
    roll_hi = float(values.tail(n).max()) if len(values) >= 1 else float("nan")
    roll_lo = float(values.tail(n).min()) if len(values) >= 1 else float("nan")

    rets = values.pct_change().dropna()
    if len(rets) == 0:
        raise HTTPException(status_code=400, detail={"error": "Not enough returns to compute stats", "expr": payload.expr})

    vol_ann = float(rets.std(ddof=0) * np.sqrt(252))

    worst = {}
    for w in payload.worst_return_windows:
        w = int(w)
        r = (values / values.shift(w)) - 1.0
        r = r.dropna()
        worst[f"worst_{w}d_return"] = float(r.min()) if len(r) else None

    mdd, dd_series = _max_drawdown(values)
    current_dd = float(dd_series.iloc[-1])

    return {
        "expr": payload.expr,
        "base_label": base["series"][0]["label"],
        "window": {"duration": payload.duration, "bar_size": payload.bar_size, "use_rth": payload.use_rth},
        "clean": clean_meta,
        "stats": {
            "last": last,
            "last_time": last_time,
            "min": vmin,
            "max": vmax,
            "rolling_high_days": n,
            "rolling_high": roll_hi,
            "rolling_low": roll_lo,
            "vol_ann": vol_ann,
            **worst,
            "current_drawdown": current_dd,
            "max_drawdown": float(mdd),
        },
    }


# ============================================================
# /expr/pack  (SINGLE definition only — no duplicates)
# ============================================================

class ExprPackRequest(BaseModel):
    expr: str
    duration: str = "3 Y"
    bar_size: str = "1 day"
    use_rth: bool = True

    want: List[str] = Field(default=["price"], description="e.g. ['price','rsi','bb','drawdown','sharpe','stats','zscore']")

    rsi_period: int = 14
    rsi_bands: Optional[str] = "classic"
    rsi_levels: Optional[List[float]] = None

    bb_window: int = 20
    bb_sigma: float = 2.0

    drawdown_mode: str = "point"
    drawdown_window: Optional[str] = None
    drawdown_n_days: Optional[int] = None

    sharpe_window: Optional[str] = "63D"
    sharpe_clean: bool = True
    sharpe_max_abs_ret: float = 0.15

    zscore_window: Optional[str] = "3M"
    zscore_levels: Optional[List[float]] = Field(default_factory=lambda: [-2.0, -1.0, 0.0, 1.0, 2.0])


@router.post("/pack")
def expr_pack(req: Request, payload: ExprPackRequest) -> dict:
    out_series: list[dict] = []
    out_stats: dict = {}

    base_label = None

    if "price" in payload.want:
        price = expr_chart(
            req,
            ExprChartRequest(expr=payload.expr, duration=payload.duration, bar_size=payload.bar_size, use_rth=payload.use_rth),
        )
        out_series.extend(price["series"])
        base_label = price["series"][0]["label"]

    if "rsi" in payload.want:
        rsi = expr_rsi(
            req,
            RsiRequest(
                expr=payload.expr,
                duration=payload.duration,
                bar_size=payload.bar_size,
                use_rth=payload.use_rth,
                period=payload.rsi_period,
                bands=payload.rsi_bands,
                levels=payload.rsi_levels,
            ),
        )
        out_series.extend(rsi["series"])
        out_stats["rsi"] = rsi.get("last")

    if "bb" in payload.want:
        boll = expr_bollinger(
            req,
            BollingerRequest(
                expr=payload.expr,
                duration=payload.duration,
                bar_size=payload.bar_size,
                use_rth=payload.use_rth,
                period=payload.bb_window,
                sigma=payload.bb_sigma,
            ),
        )
        out_series.extend(boll["series"])

    if "drawdown" in payload.want:
        dd = expr_drawdown(
            req,
            DrawdownRequest(
                expr=payload.expr,
                duration=payload.duration,
                bar_size=payload.bar_size,
                use_rth=payload.use_rth,
                mode=payload.drawdown_mode,
                rolling_window=payload.drawdown_window,
                n_days=payload.drawdown_n_days,
            ),
        )
        out_series.extend(dd["series"])
        out_stats["drawdown"] = dd["stats"]

    if "sharpe" in payload.want:
        sharpe = expr_sharpe(
            req,
            SharpeRequest(
                expr=payload.expr,
                duration=payload.duration,
                bar_size=payload.bar_size,
                use_rth=payload.use_rth,
                window=payload.sharpe_window,
                clean=payload.sharpe_clean,
                max_abs_ret=payload.sharpe_max_abs_ret,
            ),
        )
        out_series.extend(sharpe["series"])
        out_stats["sharpe"] = sharpe["stats"]

    if "zscore" in payload.want:
        z = expr_zscore(
            req,
            ZScoreRequest(
                expr=payload.expr,
                duration=payload.duration,
                bar_size=payload.bar_size,
                use_rth=payload.use_rth,
                window=payload.zscore_window or "3M",
                levels=payload.zscore_levels,
            ),
        )
        out_series.extend(z["series"])
        out_stats["zscore"] = z["stats"]

    if "stats" in payload.want:
        stats = expr_stats(
            req,
            ExprStatsRequest(
                expr=payload.expr,
                duration=payload.duration,
                bar_size=payload.bar_size,
                use_rth=payload.use_rth,
            ),
        )
        out_stats["summary"] = stats["stats"]

    return {
        "expr": payload.expr,
        "series": out_series,
        "stats": out_stats,
        "meta": {
            "duration": payload.duration,
            "bar_size": payload.bar_size,
            "use_rth": payload.use_rth,
            "base_label": base_label,
            "want": payload.want,
        },
    }


# ============================================================
# /expr/corr (rolling correlation of returns)
# ============================================================

class CorrRequest(BaseModel):
    a: str = Field(..., description="Expression for asset A, e.g. EQ:SPY")
    b: str = Field(..., description="Expression for asset B, e.g. EQ:QQQ")

    duration: str = Field("3 Y")
    bar_size: str = Field("1 day")
    use_rth: bool = True

    ret_horizon: str = Field("1D", description="Return horizon: 1D, 3D, 5D (daily bars => bars)")
    window: str = Field("3M", description="Rolling window: 63D, 12W, 3M")

    clean: bool = True
    max_abs_ret: float = Field(0.25, ge=0.001, le=5.0)


def _parse_horizon_bars(ret_horizon: str, bar_size: str) -> int:
    h = (ret_horizon or "").strip().upper().replace(" ", "")
    if not h:
        return 1
    m = re.fullmatch(r"(\d+)D", h)
    if not m:
        raise ValueError(f"Bad ret_horizon: {ret_horizon} (use 1D, 3D, 5D, etc.)")

    if not _is_daily_bar(bar_size):
        raise ValueError("ret_horizon like '3D' currently supported only for daily bar_size (e.g. '1 day').")

    n = int(m.group(1))
    return max(1, n)


def _rolling_corr_month_window(ra, rb, months: int):
    import pandas as pd
    import numpy as np

    out = []
    idx = ra.index
    for t in idx:
        start = t - pd.DateOffset(months=months)
        a = ra.loc[start:t].dropna()
        b = rb.loc[start:t].dropna()
        df = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
        if len(df) < 5:
            out.append(float("nan"))
            continue
        c = float(df["a"].corr(df["b"]))
        out.append(c if np.isfinite(c) else float("nan"))
    return pd.Series(out, index=idx, dtype="float64")


@router.post("/corr")
def expr_corr(req: Request, payload: CorrRequest) -> dict:
    import numpy as np
    import pandas as pd

    a_chart = expr_chart(
        req,
        ExprChartRequest(expr=payload.a, duration=payload.duration, bar_size=payload.bar_size, use_rth=payload.use_rth),
    )
    b_chart = expr_chart(
        req,
        ExprChartRequest(expr=payload.b, duration=payload.duration, bar_size=payload.bar_size, use_rth=payload.use_rth),
    )

    a_vals = _points_to_series(a_chart["series"][0]["points"])
    b_vals = _points_to_series(b_chart["series"][0]["points"])

    dfp = pd.concat([a_vals.rename("a"), b_vals.rename("b")], axis=1).dropna()
    if dfp.empty or len(dfp) < 10:
        raise HTTPException(status_code=400, detail={"error": "Not enough overlapping data", "a": payload.a, "b": payload.b})

    n = _parse_horizon_bars(payload.ret_horizon, payload.bar_size)

    ra = (dfp["a"] / dfp["a"].shift(n)) - 1.0
    rb = (dfp["b"] / dfp["b"].shift(n)) - 1.0

    if payload.clean:
        bad = (ra.abs() > float(payload.max_abs_ret)) | (rb.abs() > float(payload.max_abs_ret))
        ra = ra[~bad.fillna(False)]
        rb = rb[~bad.fillna(False)]

    dfr = pd.concat([ra.rename("ra"), rb.rename("rb")], axis=1).dropna()
    if dfr.empty or len(dfr) < 10:
        raise HTTPException(status_code=400, detail={"error": "Not enough data after return cleaning", "a": payload.a, "b": payload.b})

    w = (payload.window or "").strip().upper().replace(" ", "")
    if not w:
        raise HTTPException(status_code=400, detail={"error": "window required", "window": payload.window})

    m = re.fullmatch(r"(\d+)M", w)
    if m:
        months = int(m.group(1))
        corr = _rolling_corr_month_window(dfr["ra"], dfr["rb"], months=months)
    else:
        d = re.fullmatch(r"(\d+)D", w)
        if d and _is_daily_bar(payload.bar_size):
            # trading-day bars
            nb = int(d.group(1))
            corr = dfr["ra"].rolling(window=nb, min_periods=5).corr(dfr["rb"])
        else:
            corr = dfr["ra"].rolling(window=w, min_periods=5).corr(dfr["rb"])

    corr = corr.dropna().astype("float64")
    points = _to_points(corr)

    last = float(corr.iloc[-1]) if len(corr) else None
    last_time = corr.index[-1].isoformat() if len(corr) else None

    return {
        "a": payload.a,
        "b": payload.b,
        "series": [
            {
                "expr": f"corr({payload.a},{payload.b})",
                "label": f"Rolling Corr ({payload.ret_horizon} returns, {payload.window})",
                "count": int(len(points)),
                "points": points,
            }
        ],
        "stats": {
            "last": last,
            "last_time": last_time,
            "ret_horizon_bars": int(n),
            "clean": {
                "enabled": bool(payload.clean),
                "max_abs_ret": float(payload.max_abs_ret),
            },
        },
        "meta": {
            "kind": "panel",
            "panel": "corr",
            "duration": payload.duration,
            "bar_size": payload.bar_size,
            "use_rth": payload.use_rth,
            "window": payload.window,
            "ret_horizon": payload.ret_horizon,
        },
    }


# ============================================================
# /expr/zscore (warmup + correct trim; 63D means trading-day bars for daily bars)
# ============================================================

class ZScoreRequest(BaseModel):
    expr: str
    duration: str = Field("3 Y")
    bar_size: str = Field("1 day")
    use_rth: bool = True

    window: str = Field("3M")
    levels: Optional[List[float]] = Field(default_factory=lambda: [-2.0, -1.0, 0.0, 1.0, 2.0])


def _rolling_zscore_month_window(values, months: int):
    import pandas as pd
    import numpy as np

    out = []
    idx = values.index
    for t in idx:
        start = t - pd.DateOffset(months=months)
        s = values.loc[start:t].dropna()
        if len(s) < 10:
            out.append(float("nan"))
            continue
        mu = float(s.mean())
        sd = float(s.std(ddof=1))
        if (not np.isfinite(sd)) or sd == 0.0:
            out.append(float("nan"))
        else:
            out.append((float(values.loc[t]) - mu) / sd if pd.notna(values.loc[t]) else float("nan"))
    return pd.Series(out, index=idx, dtype="float64")


@router.post("/zscore")
def expr_zscore(req: Request, payload: ZScoreRequest) -> dict:
    import numpy as np
    import pandas as pd

    warmup_bars = _window_to_warmup_bars(payload.window, bar_size=payload.bar_size, min_bars=20) + 40

    base = _fetch_extended_base_series(
        req,
        expr=payload.expr,
        duration=payload.duration,
        bar_size=payload.bar_size,
        use_rth=payload.use_rth,
        warmup_bars=warmup_bars,
    )

    pts = base["series"][0]["points"]
    if not pts:
        raise HTTPException(status_code=400, detail={"error": "No data returned", "expr": payload.expr})

    values = _points_to_series(pts)

    w = (payload.window or "").strip().upper().replace(" ", "")
    if not w:
        raise HTTPException(status_code=400, detail={"error": "window required", "window": payload.window})

    m = re.fullmatch(r"(\d+)M", w)
    if m:
        months = int(m.group(1))
        z = _rolling_zscore_month_window(values, months=months)
    else:
        d = re.fullmatch(r"(\d+)D", w)
        if d and _is_daily_bar(payload.bar_size):
            nb = int(d.group(1))
            mu = values.rolling(window=nb, min_periods=10).mean()
            sd = values.rolling(window=nb, min_periods=10).std(ddof=1)
            z = (values - mu) / sd
        else:
            mu = values.rolling(window=w, min_periods=10).mean()
            sd = values.rolling(window=w, min_periods=10).std(ddof=1)
            z = (values - mu) / sd

    z = z.dropna().astype("float64")

    # trim to requested duration
    if len(z) > 0:
        end_ts = z.index[-1]
        cutoff = _cutoff_from_end(end_ts, payload.duration, bar_size=payload.bar_size)
        z = z[z.index >= cutoff]

    z_points = _to_points(z)

    series_out = [
        {
            "expr": payload.expr,
            "label": f"Z-score ({payload.window})",
            "count": int(len(z_points)),
            "points": z_points,
        }
    ]

    lvls = [float(x) for x in (payload.levels or [])]
    for lvl in lvls:
        lvl_points = [{"time": ts.isoformat(), "value": float(lvl)} for ts in z.index.to_pydatetime()]
        series_out.append(
            {
                "expr": payload.expr,
                "label": f"Z level {lvl:g}",
                "count": int(len(lvl_points)),
                "points": lvl_points,
            }
        )

    last = float(z.iloc[-1]) if len(z) else None
    last_time = z.index[-1].isoformat() if len(z) else None

    return {
        "expr": payload.expr,
        "base_label": base["series"][0]["label"],
        "series": series_out,
        "stats": {
            "last": last,
            "last_time": last_time,
            "window": payload.window,
        },
        "meta": {
            "kind": "panel",
            "panel": "zscore",
            "duration": payload.duration,
            "bar_size": payload.bar_size,
            "use_rth": payload.use_rth,
        },
    }


# ============================================================
# /expr/seasonality/years  (overlay multiple years)
# ============================================================

class SeasonalityYearsRequest(BaseModel):
    expr: str
    years: List[int] = Field(..., description="e.g. [2021,2022,2023,2024,2025]")
    duration: str = Field("15 Y")
    bar_size: str = Field("1 day")
    use_rth: bool = True
    rebase: bool = True
    min_points_per_year: int = Field(50, ge=1, le=5000)


def _synthetic_time_index(n: int):
    import pandas as pd

    base = pd.Timestamp("2000-01-01")
    return pd.DatetimeIndex([base + pd.Timedelta(days=i) for i in range(n)])


@router.post("/seasonality/years")
def expr_seasonality_years(req: Request, payload: SeasonalityYearsRequest) -> dict:
    import pandas as pd

    base = expr_chart(
        req,
        ExprChartRequest(
            expr=payload.expr,
            duration=payload.duration,
            bar_size=payload.bar_size,
            use_rth=payload.use_rth,
        ),
    )

    pts = base["series"][0]["points"]
    if not pts:
        raise HTTPException(status_code=400, detail={"error": "No data returned", "expr": payload.expr})

    values = _points_to_series(pts).sort_index()

    years = sorted(set(int(y) for y in payload.years))
    if not years:
        raise HTTPException(status_code=400, detail={"error": "years must be non-empty"})

    series_out: List[dict] = []
    table_out: List[dict] = []

    for y in years:
        ys = values[(values.index.year == y)].dropna()
        if len(ys) < int(payload.min_points_per_year):
            table_out.append({"year": y, "included": False, "reason": f"too_few_points({len(ys)})"})
            continue

        if payload.rebase:
            start_val = float(ys.iloc[0])
            if start_val == 0.0:
                table_out.append({"year": y, "included": False, "reason": "start_val_zero"})
                continue
            yv = (ys / start_val) * 100.0
        else:
            yv = ys.astype("float64")

        yv_daily = yv.groupby(yv.index.dayofyear).last()
        pts = []
        for day, val in yv_daily.items():
            d = int(day) - 1
            if d < 0:
                d = 0
            if d > 364:
                d = 364
            pts.append({"x": d, "y": float(val)})
        pts.sort(key=lambda r: r["x"])

        series_out.append(
            {
                "expr": payload.expr,
                "label": f"{payload.expr} {y}" + (" (rebased=100)" if payload.rebase else ""),
                "count": int(len(pts)),
                "points": pts,
            }
        )

        total_ret = float((ys.iloc[-1] / ys.iloc[0]) - 1.0)
        table_out.append(
            {
                "year": y,
                "included": True,
                "points": int(len(ys)),
                "first_time": ys.index[0].isoformat(),
                "last_time": ys.index[-1].isoformat(),
                "total_return": total_ret,
            }
        )

    if not series_out:
        raise HTTPException(status_code=400, detail={"error": "No years had sufficient data", "years": years})

    return {
        "expr": payload.expr,
        "base_label": base["series"][0]["label"],
        "series": series_out,
        "tables": {"years": table_out},
        "meta": {
            "kind": "panel",
            "panel": "seasonality_years",
            "x_axis": "day_of_year",
            "rebase": bool(payload.rebase),
            "duration": payload.duration,
            "bar_size": payload.bar_size,
            "use_rth": payload.use_rth,
            "min_points_per_year": int(payload.min_points_per_year),
            "years": years,
        },
    }


# ============================================================
# /expr/seasonality/heatmap  (Excel-friendly)
# ============================================================

class SeasonalityHeatmapRequest(BaseModel):
    expr: str
    duration: str = Field("20 Y")
    bar_size: str = Field("1 day")
    use_rth: bool = True

    bucket: str = Field("month", pattern="^(month|week)$")
    years: Optional[List[int]] = Field(None, description="Optional explicit subset of years")


@router.post("/seasonality/heatmap")
def expr_seasonality_heatmap(req: Request, payload: SeasonalityHeatmapRequest) -> dict:
    import pandas as pd
    import numpy as np

    base = expr_chart(
        req,
        ExprChartRequest(
            expr=payload.expr,
            duration=payload.duration,
            bar_size=payload.bar_size,
            use_rth=payload.use_rth,
        ),
    )

    pts = base["series"][0]["points"]
    if not pts:
        raise HTTPException(status_code=400, detail={"error": "No data returned", "expr": payload.expr})

    values = _points_to_series(pts).sort_index().dropna()

    if payload.years:
        years_set = set(int(y) for y in payload.years)
        values = values[values.index.year.isin(years_set)]

    if values.empty or len(values) < 30:
        raise HTTPException(status_code=400, detail={"error": "Not enough data", "expr": payload.expr})

    df = values.rename("px").to_frame()
    rows: List[dict] = []

    if payload.bucket == "month":
        g = df.groupby([df.index.year, df.index.month])["px"]
        first = g.first()
        last = g.last()
        mret = (last / first) - 1.0

        for (yy, mm), r in mret.items():
            rows.append(
                {"year": int(yy), "bucket": "month", "period": int(mm), "return": float(r), "return_pct": float(r * 100.0)}
            )

        heat = pd.DataFrame(rows).pivot(index="year", columns="period", values="return_pct").sort_index()
        for m in range(1, 13):
            if m not in heat.columns:
                heat[m] = np.nan
        heat = heat[sorted(heat.columns)]

        def _stats(s: pd.Series) -> dict:
            s = s.dropna()
            if len(s) == 0:
                return {"n": 0, "mean": None, "median": None, "min": None, "max": None, "hit_rate": None, "stdev": None, "p10": None, "p90": None}
            hit = float((s > 0.0).mean())
            return {
                "n": int(len(s)),
                "mean": float(s.mean()),
                "median": float(s.median()),
                "min": float(s.min()),
                "max": float(s.max()),
                "hit_rate": hit,
                "stdev": float(s.std(ddof=1)) if len(s) >= 2 else 0.0,
                "p10": float(s.quantile(0.10)),
                "p90": float(s.quantile(0.90)),
            }

        monthly_summary = []
        for m in range(1, 13):
            st = _stats(heat[m])
            monthly_summary.append({"bucket": "month", "period": m, **st})

        all_vals = heat.values.reshape(-1)
        all_vals = all_vals[np.isfinite(all_vals)]
        overall = _stats(pd.Series(all_vals, dtype="float64"))
        overall["bucket"] = "month"
        overall["period"] = "ALL"

        matrix_rows = []
        for y in heat.index.tolist():
            row = {"year": int(y)}
            for m in range(1, 13):
                v = heat.loc[y, m]
                row[f"m{m:02d}"] = None if not np.isfinite(v) else float(v)
            matrix_rows.append(row)

        return {
            "expr": payload.expr,
            "base_label": base["series"][0]["label"],
            "tables": {
                "heatmap": rows,
                "matrix": matrix_rows,
                "monthly_summary": monthly_summary,
                "overall_summary": overall,
            },
            "meta": {
                "kind": "table",
                "panel": "seasonality_heatmap",
                "bucket": payload.bucket,
                "duration": payload.duration,
                "bar_size": payload.bar_size,
                "use_rth": payload.use_rth,
                "years_filter": payload.years,
                "units": "return_pct",
            },
        }

    # weekly mode (kept simple)
    iso = df.index.isocalendar()
    df["iso_year"] = iso.year.astype(int)
    df["iso_week"] = iso.week.astype(int)

    g = df.groupby(["iso_year", "iso_week"])["px"]
    first = g.first()
    last = g.last()
    wret = (last / first) - 1.0

    for (yy, ww), r in wret.items():
        rows.append({"year": int(yy), "bucket": "week", "period": int(ww), "return": float(r), "return_pct": float(r * 100.0)})

    return {
        "expr": payload.expr,
        "base_label": base["series"][0]["label"],
        "tables": {"heatmap": rows},
        "meta": {
            "kind": "table",
            "panel": "seasonality_heatmap",
            "bucket": payload.bucket,
            "duration": payload.duration,
            "bar_size": payload.bar_size,
            "use_rth": payload.use_rth,
            "years_filter": payload.years,
            "units": "return_pct",
        },
    }


# ============================================================
# /expr/compare  (compare path shape between two date ranges)
# ============================================================

class ComparePeriodsRequest(BaseModel):
    expr: str

    a_start: str = Field(..., description="ISO date/time inclusive, e.g. 2007-06-01")
    a_end: str = Field(..., description="ISO date/time inclusive, e.g. 2007-12-31")

    b_start: str = Field(..., description="ISO date/time inclusive, e.g. 2025-01-01")
    b_end: str = Field(..., description="ISO date/time inclusive, e.g. 2025-06-30")

    duration: str = Field("30 Y")
    bar_size: str = Field("1 day")
    use_rth: bool = True

    rebase: bool = True


def _slice_series(values, start: str, end: str):
    import pandas as pd

    s = values.copy()
    s = s[(s.index >= pd.to_datetime(start)) & (s.index <= pd.to_datetime(end))]
    return s.dropna()


@router.post("/compare")
def expr_compare(req: Request, payload: ComparePeriodsRequest) -> dict:
    import pandas as pd

    base = expr_chart(
        req,
        ExprChartRequest(
            expr=payload.expr,
            duration=payload.duration,
            bar_size=payload.bar_size,
            use_rth=payload.use_rth,
        ),
    )

    pts = base["series"][0]["points"]
    if not pts:
        raise HTTPException(status_code=400, detail={"error": "No data returned", "expr": payload.expr})

    values = _points_to_series(pts).sort_index()

    a = _slice_series(values, payload.a_start, payload.a_end)
    b = _slice_series(values, payload.b_start, payload.b_end)

    if len(a) < 5:
        raise HTTPException(status_code=400, detail={"error": "Period A has too few points", "a_points": int(len(a))})
    if len(b) < 5:
        raise HTTPException(status_code=400, detail={"error": "Period B has too few points", "b_points": int(len(b))})

    def rebase_to_100(s: pd.Series) -> pd.Series:
        if not payload.rebase:
            return s.astype("float64")
        start_val = float(s.iloc[0])
        if start_val == 0.0:
            raise HTTPException(status_code=400, detail={"error": "Cannot rebase from zero start value"})
        return (s / start_val) * 100.0

    a2 = rebase_to_100(a)
    b2 = rebase_to_100(b)

    a_syn = pd.Series(a2.values, index=_synthetic_time_index(len(a2)))
    b_syn = pd.Series(b2.values, index=_synthetic_time_index(len(b2)))

    a_total = float((a.iloc[-1] / a.iloc[0]) - 1.0)
    b_total = float((b.iloc[-1] / b.iloc[0]) - 1.0)

    return {
        "expr": payload.expr,
        "base_label": base["series"][0]["label"],
        "series": [
            {
                "expr": payload.expr,
                "label": f"A: {payload.a_start} → {payload.a_end}" + (" (rebased=100)" if payload.rebase else ""),
                "count": int(len(a_syn)),
                "points": _to_points(a_syn),
            },
            {
                "expr": payload.expr,
                "label": f"B: {payload.b_start} → {payload.b_end}" + (" (rebased=100)" if payload.rebase else ""),
                "count": int(len(b_syn)),
                "points": _to_points(b_syn),
            },
        ],
        "stats": {
            "a_points": int(len(a)),
            "b_points": int(len(b)),
            "a_total_return": a_total,
            "b_total_return": b_total,
            "a_first_time": a.index[0].isoformat(),
            "a_last_time": a.index[-1].isoformat(),
            "b_first_time": b.index[0].isoformat(),
            "b_last_time": b.index[-1].isoformat(),
        },
        "meta": {
            "kind": "panel",
            "panel": "compare",
            "x_axis": "synthetic_days",
            "rebase": bool(payload.rebase),
            "duration": payload.duration,
            "bar_size": payload.bar_size,
            "use_rth": payload.use_rth,
        },
    }
# Pydantic v2: ensure forward refs are resolved for OpenAPI generation
ExprChartRequest.model_rebuild()
