from __future__ import annotations

from typing import List, Optional, Sequence

from quant_sandbox.analytics.series import Series
from quant_sandbox.analytics.ta import rsi_wilder


def rsi(
    series: Series,
    period: int = 14,
    levels: Optional[Sequence[float]] = None,
) -> List[Series]:
    r = rsi_wilder(series.values, period=period)

    out: List[Series] = [
        Series(values=r, name=f"RSI({series.name},{int(period)})", unit="index")
    ]

    if levels:
        for lvl in levels:
            lvl_f = float(lvl)
            out.append(
                Series(
                    values=r * 0 + lvl_f,
                    name=f"RSI level {lvl_f:g}",
                    unit="index",
                )
            )

    return out
