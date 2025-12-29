from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ib_insync import Stock, Index, Forex, Future, Contract


@dataclass(frozen=True)
class Instr:
    asset: str
    symbol: str
    exchange: Optional[str] = None
    currency: Optional[str] = None
    expiry: Optional[str] = None  # YYYYMM or YYYYMMDD


def parse_spec(spec: str) -> Instr:
    parts = spec.split(":")
    if len(parts) < 2:
        raise ValueError(f"Bad spec '{spec}'. Expected like stock:AAPL or index:DAX:EUREX or fx:EURUSD")

    asset = parts[0].strip().lower()
    symbol = parts[1].strip().upper()

    exchange = None
    expiry = None
    currency = None

    if asset in ("stock", "etf"):
        if len(parts) >= 3:
            exchange = parts[2].strip().upper()
        if len(parts) >= 4:
            currency = parts[3].strip().upper()
        return Instr(asset=asset, symbol=symbol, exchange=exchange, currency=currency)

    if asset == "index":
        if len(parts) >= 3:
            exchange = parts[2].strip().upper()
        if len(parts) >= 4:
            currency = parts[3].strip().upper()
        return Instr(asset=asset, symbol=symbol, exchange=exchange, currency=currency)

    if asset == "fx":
        if len(parts) >= 3:
            exchange = parts[2].strip().upper()
        return Instr(asset=asset, symbol=symbol, exchange=exchange)

    if asset in ("future", "fut"):
        if len(parts) >= 3:
            exchange = parts[2].strip().upper()
        if len(parts) >= 4:
            expiry = parts[3].strip()
        if len(parts) >= 5:
            currency = parts[4].strip().upper()
        return Instr(asset="future", symbol=symbol, exchange=exchange, expiry=expiry, currency=currency)

    # Fallback: treat unknown as stock-like
    if len(parts) >= 3:
        exchange = parts[2].strip().upper()
    if len(parts) >= 4:
        currency = parts[3].strip().upper()
    return Instr(asset=asset, symbol=symbol, exchange=exchange, currency=currency)


def make_contract(spec: str) -> Contract:
    i = parse_spec(spec)

    if i.asset in ("stock", "etf"):
        exch = i.exchange or "SMART"
        ccy = i.currency or "USD"
        return Stock(i.symbol, exch, ccy)

    if i.asset == "index":
        exch = i.exchange or "SMART"
        ccy = i.currency or "EUR"
        return Index(i.symbol, exch, ccy)

    if i.asset == "fx":
        if i.exchange:
            return Forex(i.symbol, exchange=i.exchange)
        return Forex(i.symbol)

    if i.asset == "future":
        if not i.expiry:
            raise ValueError("Future requires expiry YYYYMM or YYYYMMDD")

        from quant_sandbox.data.futures_registry import get_future_product

        # i.symbol is now a PRODUCT KEY (ES, MES, NQ, MNQ, FDAX, etc.)
        prod = get_future_product(i.symbol)

        kwargs = dict(
            symbol=prod.symbol,                 # e.g. DAX, ES, NQ
            lastTradeDateOrContractMonth=i.expiry,          # YYYYMM or YYYYMMDD
            exchange=prod.exchange,                         # authoritative
        )

    if prod.currency:
        kwargs["currency"] = prod.currency

    if prod.tradingClass:
        kwargs["tradingClass"] = prod.tradingClass

    c = Future(**kwargs)

    if prod.multiplier:
        c.multiplier = prod.multiplier

    return c



    raise ValueError(f"Unsupported asset in spec '{spec}'")
