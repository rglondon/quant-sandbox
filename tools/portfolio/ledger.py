from __future__ import annotations

import pandas as pd


def build_lots_from_fills(fills: pd.DataFrame) -> pd.DataFrame:
    """Approximate lots using FIFO from executions.
    Returns open lots with remaining_qty > 0.
    """
    if fills.empty:
        return pd.DataFrame(columns=["symbol", "time", "side", "qty", "price", "remaining_qty"]) 

    lots = []
    open_lots = {}

    for _, row in fills.iterrows():
        sym = row.get("symbol")
        side = str(row.get("side", "")).upper()
        qty = float(row.get("qty", 0.0) or 0.0)
        price = float(row.get("price", 0.0) or 0.0)
        time = row.get("time")

        if qty == 0 or not sym:
            continue

        if side == "BUY":
            lot = {
                "symbol": sym,
                "time": time,
                "side": "BUY",
                "qty": qty,
                "price": price,
                "remaining_qty": qty,
            }
            open_lots.setdefault(sym, []).append(lot)
        elif side == "SELL":
            remaining = qty
            for lot in open_lots.get(sym, []):
                if remaining <= 0:
                    break
                if lot["remaining_qty"] <= 0:
                    continue
                use = min(lot["remaining_qty"], remaining)
                lot["remaining_qty"] -= use
                remaining -= use

            # If no open lots, treat as short lot
            if remaining > 0:
                lot = {
                    "symbol": sym,
                    "time": time,
                    "side": "SELL",
                    "qty": remaining,
                    "price": price,
                    "remaining_qty": remaining,
                }
                open_lots.setdefault(sym, []).append(lot)

    for sym, sym_lots in open_lots.items():
        for lot in sym_lots:
            if lot["remaining_qty"] > 0:
                lots.append(lot)

    return pd.DataFrame(lots)
