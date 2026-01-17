# src/quant_sandbox/data/contracts.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ib_insync import Stock, Index, Forex, Future, Contract


# ----------------------------
# Index defaults typing
# ----------------------------
IndexDefault = tuple[str, str, str] | tuple[str, str, str, int]


@dataclass(frozen=True)
class Instr:
    asset: str
    symbol: str
    region: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    expiry: Optional[str] = None  # YYYYMM or YYYYMMDD (futures)


# ----------------------------
# Equity mapping (IBKR-oriented)
# ----------------------------
# Region -> (currency, primaryExchange)
_REGION_MAP: dict[str, tuple[str, Optional[str]]] = {
    "US": ("USD", None),
    "HK": ("HKD", "SEHK"),
    "JP": ("JPY", "TSEJ"),
    "SG": ("SGD", "SGX"),
    "AU": ("AUD", "ASX"),
    "IN": ("INR", "NSE"),
    "LN": ("GBP", "LSE"),
    "GY": ("EUR", "IBIS"),
    "FR": ("EUR", "SBF"),
    "SW": ("CHF", "SWX"),
    "NL": ("EUR", "AEB"),
    "SK": ("SEK", "SFB"),
    "NO": ("NOK", "OSE"),
    "IT": ("EUR", "BVME"),
    "SP": ("EUR", "BME"),
    "CA": ("CAD", "TSE"),
    "BZ": ("BRL", "BVMF"),
    "SA": ("ZAR", "JSE"),
}

_NUMERIC_PAD: dict[str, int] = {"HK": 4, "JP": 4}


def _maybe_pad_numeric(symbol: str, region: str) -> str:
    s = (symbol or "").strip().upper()
    r = (region or "").strip().upper()
    if not s.isdigit():
        return s
    width = _NUMERIC_PAD.get(r)
    if not width or len(s) >= width:
        return s
    return s.zfill(width)


# ----------------------------
# Index mapping (IBKR-oriented)
# ----------------------------
# NOTE: These are DEFAULTS only. Users can override with IX:SYM@EXCHANGE.
# You will still hit IB permission issues if you don’t subscribe to the index feed.
_INDEX_DEFAULTS: dict[str, IndexDefault] = {
    # US
    "SPX": ("SPX", "CBOE", "USD"),
    "NDX": ("NDX", "NASDAQ", "USD"),
    "RUT": ("RUT", "RUSSELL", "USD"),
    "VIX": ("VIX", "CBOE", "USD"),
    "COR1M": ("COR1M", "CBOE", "USD"),

    # Europe
    "DAX": ("DAX", "EUREX", "EUR"),
    "MDAX": ("MDAX", "EUREX", "EUR"),
    "SDAX": ("SDAX", "EUREX", "EUR"),
    "DJ600": ("DJ600", "EUREX", "EUR"),

    # Euro STOXX 50: user might type ESTX50 but IB cash symbol is SX5E
    "ESTX50": ("SX5E", "EUREX", "EUR", 4356500),
    "SX5E": ("SX5E", "EUREX", "EUR", 4356500),

    # STOXX / sectors (cash)
    "SX7E": ("SX7E", "EUREX", "EUR"),
    "SX7P": ("SX7P", "EUREX", "EUR"),
    "SXNP": ("SXNP", "EUREX", "EUR"),
    "SXEP": ("SXEP", "EUREX", "EUR"),
    "SXKP": ("SXKP", "EUREX", "EUR"),
    "SXPP": ("SXPP", "EUREX", "EUR"),
    "SXAP": ("SXAP", "EUREX", "EUR"),
    "SXDE": ("SXDE", "EUREX", "EUR"),
    "SXDP": ("SXDP", "EUREX", "EUR"),
    "SX3E": ("SX3E", "EUREX", "EUR"),
    "SX3P": ("SX3P", "EUREX", "EUR"),
    "SX4E": ("SX4E", "EUREX", "EUR"),
    "SX4P": ("SX4P", "EUREX", "EUR"),
    "V2X": ("V2X", "EUREX", "EUR"),
    "V2TX": ("V2TX", "EUREX", "EUR"),

    # UK / CH / others
    "FTSE": ("FTSE", "LSE", "GBP"),
    "UKX": ("UKX", "LSE", "GBP"),
    "SMI": ("SMI", "SWX", "CHF"),
    "FTMIB": ("FTMIB", "IDEM", "EUR"),
    "IBEX": ("IBEX", "MEFFRV", "EUR"),

    # Japan
    "N225": ("N225", "OSE.JPN", "JPY"),
    "TOPX": ("TOPX", "OSE.JPN", "JPY"),
    "TPNBNK": ("TPNBNK", "OSE.JPN", "JPY"),

    # Hong Kong
    "HSI": ("HSI", "HKFE", "HKD"),
    "HHI": ("HHI", "HKFE", "HKD"),
    "HSTECH": ("HSTECH", "HKFE", "HKD"),

    # Placeholders (override if needed)
    "K200": ("K200", "KSE", "KRW"),
    "XFL": ("XFL", "ASX", "AUD"),
    "NIFTY50": ("NIFTY50", "NSE", "INR"),
    "JSE40": ("JSE40", "JSE", "ZAR"),
    "IBOV": ("IBOV", "BVMF", "BRL"),
}

_INDEX_ALIASES: dict[str, str] = {
    "ESTX50": "SX5E",
    "HSCEI": "HHI",
    "HSCEI.HK": "HHI",
    "HHI.HK": "HHI",
}


def parse_spec(spec: str) -> Instr:
    parts = [p.strip() for p in spec.split(":")]
    if len(parts) < 2:
        raise ValueError(
            f"Bad spec '{spec}'. Expected like stock:AAPL or fx:EURUSD or future:ES:CME:YYYYMMDD"
        )

    asset = parts[0].strip().lower()
    symbol = parts[1].strip().upper()

    # normalize synonyms (defensive)
    if asset in ("eq", "equity", "stock"):
        asset = "stock"
    elif asset in ("ix", "index", "indices"):
        asset = "index"
    elif asset in ("fx", "forex"):
        asset = "fx"
    elif asset in ("fut", "future"):
        asset = "future"
    elif asset in ("etf",):
        asset = "etf"

    region: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    expiry: Optional[str] = None

    if asset in ("stock", "etf"):
        # stock:SAP:GY or stock:700:HK or stock:SAP:IBIS (exchange override stored here)
        if len(parts) >= 3:
            region = parts[2].upper() if parts[2] else None
        if len(parts) >= 4:
            currency = parts[3].upper() if parts[3] else None
        return Instr(asset=asset, symbol=symbol, region=region, exchange=None, currency=currency)

    if asset == "index":
        # index:DAX
        # index:DAX:EUREX
        # index:N225:OSE.JPN
        if len(parts) >= 3:
            exchange = parts[2].upper() if parts[2] else None
        if len(parts) >= 4:
            currency = parts[3].upper() if parts[3] else None
        return Instr(asset=asset, symbol=symbol, exchange=exchange, currency=currency)

    if asset == "fx":
        if len(parts) >= 3:
            exchange = parts[2].upper() if parts[2] else None
        return Instr(asset=asset, symbol=symbol, exchange=exchange)

    if asset == "future":
        # future:ES:CME:YYYYMMDD[:CCY]
        if len(parts) >= 3:
            exchange = parts[2].upper() if parts[2] else None
        if len(parts) >= 4:
            expiry = parts[3] if parts[3] else None
        if len(parts) >= 5:
            currency = parts[4].upper() if parts[4] else None
        return Instr(asset="future", symbol=symbol, exchange=exchange, expiry=expiry, currency=currency)

    return Instr(asset=asset, symbol=symbol, region=None, exchange=None, currency=None)


def make_contract(spec: str) -> Contract:
    i = parse_spec(spec)

    # ---------- Stocks / ETFs ----------
    if i.asset in ("stock", "etf"):
        region = (i.region or "US").upper()

        # Exchange override via EQ:SAP@IBIS becomes stock:SAP:IBIS (region holds IBIS)
        if region and len(region) > 2:
            exch = region
            currency = i.currency or "USD"
            return Stock(i.symbol, exch, currency)

        ccy, primary = _REGION_MAP.get(region, ("USD", None))
        currency = i.currency or ccy

        sym = _maybe_pad_numeric(i.symbol, region)

        if region == "HK":
            return Stock(sym, "SEHK", currency)

        exch = "SMART"
        if primary:
            return Stock(sym, exch, currency, primaryExchange=primary)
        return Stock(sym, exch, currency)

    # ---------- Indices ----------
    if i.asset == "index":
        sym = (i.symbol or "").strip().upper()
        if not sym:
            raise ValueError("Index requires a symbol")

        sym = _INDEX_ALIASES.get(sym, sym)

        # explicit override: index:SYM:EXCHANGE[:CCY]
        if i.exchange:
            exch = i.exchange.upper()
            ccy = i.currency.upper() if i.currency else _INDEX_DEFAULTS.get(sym, (sym, exch, "USD"))[2]

            c = Index(sym, exch, ccy)
            t = _INDEX_DEFAULTS.get(sym)
            if t and len(t) >= 4 and t[3]:
                c.conId = int(t[3])
            return c

        # defaults: index:SYM
        if sym in _INDEX_DEFAULTS:
            t = _INDEX_DEFAULTS[sym]
            ib_sym, exch, ccy = t[0], t[1], t[2]
            c = Index(ib_sym, exch, ccy)
            if len(t) >= 4 and t[3]:
                c.conId = int(t[3])
            return c

        raise ValueError(
            f"Unknown index '{sym}'. "
            f"Try specifying the exchange explicitly: IX:{sym}@<EXCHANGE> (e.g. IX:{sym}@EUREX) "
            f"or if cash index isn’t available on your IB permissions, try the futures: IX:{sym}.1 or IX:{sym}.A"
        )

    # ---------- FX ----------
    if i.asset == "fx":
        if i.exchange:
            return Forex(i.symbol, exchange=i.exchange)
        return Forex(i.symbol)

    # ---------- Futures ----------
    if i.asset == "future":
        if not i.expiry:
            raise ValueError("Future requires expiry YYYYMM or YYYYMMDD")

        from quant_sandbox.data.futures_registry import get_future_product
        prod = get_future_product(i.symbol)

        kwargs = dict(
            symbol=prod.symbol,
            lastTradeDateOrContractMonth=i.expiry,
            exchange=prod.exchange,
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
