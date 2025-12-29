# src/quant_sandbox/api/metrics.py

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/expr", tags=["expr"])


# ----------------------------
# Helpers
# ----------------------------

def _normalize_spec(spec: str) -> str:
    s = spec.strip()
    if ":" not in s:
        return f"stock:{s}"
    return s


# ----------------------------
# /expr/close
# ----------------------------

class CloseSeriesRequest(BaseModel):
    spec: str = Field(..., description="e.g. 'SPY', 'stock:SPY', 'fx:EURUSD'")
    duration: str
    bar_size: str
    use_rth: bool = True


@router.post("/close")
def expr_close(req: Request, payload: CloseSeriesRequest) -> dict:
    worker = req.app.state.ibkr_worker
    print("IBKR worker type:", type(worker), "module:", type(worker).__module__)

    internal_spec = _normalize_spec(payload.spec)

    try:
        use_rth = payload.use_rth
        if internal_spec.lower().startswith(("future:", "futuresel:")):
            use_rth = False

        s = worker.fetch_close_series(
            internal_spec,
            duration=payload.duration,
            bar_size=payload.bar_size,
            use_rth=use_rth,
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail={"error": str(e), "spec": payload.spec})

    points = [
        {"time": ts.isoformat(), "value": float(v)}
        for ts, v in zip(s.index.to_pydatetime(), s.values)
    ]

    return {
        "spec": payload.spec,
        "internal_spec": internal_spec,
        "count": int(len(points)),
        "points": points,
    }


# ----------------------------
# /expr/series
# ----------------------------

class ExprSeriesRequest(BaseModel):
    expr: str = Field(..., description="SPY | SPY/QQQ | (SPY-QQQ)/QQQ")
    duration: str
    bar_size: str
    use_rth: bool = True
    start: Optional[str] = Field(None, description="ISO8601 inclusive, e.g. '2025-11-01T00:00:00'")
    end: Optional[str] = Field(None, description="ISO8601 inclusive, e.g. '2025-12-01T00:00:00'")


@router.post("/series")
def expr_series(req: Request, payload: ExprSeriesRequest) -> dict:
    """
    Expression support (canonical symbols + math):

      Canonical symbols:
        EQ:SPY
        EQ:SAP.DE
        FX:EURUSD
        IX:DAX
        IX:DAX.1
        IX:DAX.A

      Math:
        + - * / and parentheses

      Examples:
        EQ:SPY
        (EQ:EEM * FX:EURUSD) / EQ:SPY
        (IX:DAX.1 - IX:DAX) / IX:DAX
    """
    worker = req.app.state.ibkr_worker
    expr = payload.expr.strip()

    try:
        # Import here to avoid import-time side effects and keep FastAPI startup clean
        from quant_sandbox.analytics.expressions import (
            normalize_expr_symbols,
            normalize_canonical_symbol,
        )
        import pandas as pd

        # 1) Replace canonical symbols with s0, s1, ... and collect raw canonical tokens
        rewritten, symbols = normalize_expr_symbols(expr)

        # Allow passing a single internal spec directly (useful for debugging),
        # e.g. "future:FDAX:EUREX:202503"
        if not symbols:
            if expr.lower().startswith(("stock:", "etf:", "index:", "fx:", "future:", "futuresel:")):
                symbols = [expr]
                rewritten = "s0"
            else:
                raise ValueError(
                    "No canonical symbols found. Use tokens like EQ:SPY, FX:EURUSD, IX:DAX.1"
                )

        # 2) Fetch each symbol as a Series (aligned later)
        env: dict[str, pd.Series] = {}
        label_parts: list[str] = []

        for i, sym in enumerate(symbols):
            # If sym is already an internal spec (e.g. "future:FDAX:EUREX:202503"),
            # skip canonical normalization.
            if ":" in sym and sym.split(":", 1)[0].lower() in {"stock", "etf", "index", "fx", "future", "futuresel"}:
                internal_spec = sym
            else:
                internal_spec = normalize_canonical_symbol(sym)  # e.g. EQ:SPY -> stock:SPY

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

        # 3) Align all series to common timestamps (inner join)
        # Build a single DataFrame with columns s0, s1, ...
        df = None
        for k, s in env.items():
            if df is None:
                df = s.rename(k).to_frame()
            else:
                df = df.join(s.rename(k).to_frame(), how="inner")

        if df is None or df.empty:
            raise ValueError("No overlapping timestamps across symbols (alignment produced empty series).")

        # 4) Evaluate expression safely (no builtins, locals only contain series)
        # After eval, we expect a pandas Series aligned to df.index.
        local_env = {k: df[k] for k in df.columns}
        result = eval(rewritten, {"__builtins__": {}}, local_env)

        if not hasattr(result, "index"):
            raise ValueError("Expression did not produce a time series result.")

        out = result.dropna()

        # 5) Optional windowing (inclusive)
        if payload.start:
            out = out[out.index >= pd.to_datetime(payload.start)]
        if payload.end:
            out = out[out.index <= pd.to_datetime(payload.end)]

        label = rewritten
        # nicer label: substitute s0/s1... back into internal specs
        for i, internal_spec in enumerate(label_parts):
            label = label.replace(f"s{i}", internal_spec)

    except Exception as e:
        raise HTTPException(status_code=400, detail={"error": str(e), "expr": expr})

    points = [
        {"time": ts.isoformat(), "value": float(v)}
        for ts, v in zip(out.index.to_pydatetime(), out.values)
    ]

    return {
        "expr": expr,
        "label": label,
        "count": int(len(points)),
        "points": points,
    }

# ----------------------------
# /expr/rsi  (period + bands/levels + last value)
# ----------------------------

class RsiRequest(BaseModel):
    expr: str
    period: int = Field(14, ge=2, le=200)

    # If provided, these exact levels will be used (e.g. [70,30] or [80,70,50,30,20])
    levels: Optional[List[float]] = Field(
        default=None,
        description="Optional explicit RSI levels. If provided, 'bands' preset is ignored.",
    )

    # Convenience presets if levels is not provided
    bands: Optional[str] = Field(
        default="classic",
        description="classic|strict|full|none (ignored if 'levels' is provided)",
    )

    duration: str
    bar_size: str
    use_rth: bool = True


def _rsi(series, period: int):
    # Wilder-like RSI via EWMA (your existing implementation)
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


@router.post("/rsi")
def expr_rsi(req: Request, payload: RsiRequest) -> dict:
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

    idx = pd.to_datetime([p["time"] for p in base["points"]])
    values = pd.Series([p["value"] for p in base["points"]], index=idx)

    rsi = _rsi(values, payload.period).dropna()

    # RSI points
    rsi_points = [
        {"time": ts.isoformat(), "value": float(v)}
        for ts, v in zip(rsi.index.to_pydatetime(), rsi.values)
    ]

    series_out = [
        {
            "expr": payload.expr,
            "label": f"RSI({payload.period}) {base['label']}",
            "count": int(len(rsi_points)),
            "points": rsi_points,
        }
    ]

    # Resolve levels either from explicit list or from preset
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

    # Add constant level lines
    for lvl in levels:
        lvl_points = [{"time": ts.isoformat(), "value": float(lvl)} for ts in rsi.index.to_pydatetime()]
        series_out.append(
            {
                "expr": payload.expr,
                "label": f"RSI level {lvl:g}",
                "count": int(len(lvl_points)),
                "points": lvl_points,
            }
        )

    # Last value (helps UI print RSI level next to axis)
    if len(rsi) > 0:
        last_time = rsi.index[-1].isoformat()
        last_value = float(rsi.iloc[-1])
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
    }
