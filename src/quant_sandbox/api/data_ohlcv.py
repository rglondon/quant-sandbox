# src/quant_sandbox/api/data_ohlcv.py

from __future__ import annotations

from typing import Literal, Optional, List
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/data", tags=["data"])

Resolution = Literal["1min", "5min", "15min", "30min", "1H", "4H", "1D", "1W", "1M"]
AdjustMode = Literal["none", "split_div"]


class DateRange(BaseModel):
    start: str = Field(..., description="YYYY-MM-DD or ISO8601")
    end: str = Field(..., description="YYYY-MM-DD or ISO8601")


class OHLCVRequest(BaseModel):
    symbol: str = Field(..., description="Canonical symbol, e.g. EQ:SPY, FX:EURUSD, IX:ES.A")
    resolution: Resolution = "1D"
    range: DateRange
    adjust: AdjustMode = "none"
    include_volume: bool = True
    tz: str = "Europe/London"
    max_bars: int = 5000


class Bar(BaseModel):
    t: str  # ISO timestamp
    o: float
    h: float
    l: float
    c: float
    v: Optional[float] = None


class OHLCVResponse(BaseModel):
    symbol: str
    resolution: Resolution
    tz: str
    bars: List[Bar]


@router.post("/ohlcv", response_model=OHLCVResponse)
def data_ohlcv(req: OHLCVRequest, request: Request) -> OHLCVResponse:
    """
    Returns OHLCV bars for a canonical symbol.

    This calls IBKRWorker.get_ohlcv(), which runs safely on the worker's event loop thread.
    """
    worker = getattr(request.app.state, "ibkr_worker", None)
    if worker is None:
        raise HTTPException(status_code=500, detail="IBKR worker not initialized (app.state.ibkr_worker missing)")

    try:
        # Worker returns a list of dicts: {"t","o","h","l","c","v"}
        bars = worker.get_ohlcv(
            symbol=req.symbol,
            start=req.range.start,
            end=req.range.end,
            resolution=req.resolution,
            tz=req.tz,
            max_bars=req.max_bars,
            include_volume=req.include_volume,
            adjust=req.adjust,
        )

        # Validate/normalize into Pydantic Bars
        out = [Bar(**b) for b in bars]

        return OHLCVResponse(
            symbol=req.symbol,
            resolution=req.resolution,
            tz=req.tz,
            bars=out,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OHLCV error: {e}")
