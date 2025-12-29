from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class FutureProduct:
    # canonical root the user types after IX: (e.g. "NQ", "MNQ", "DAX", "CL")
    canonical: str

    # IB contract fields
    symbol: str                  # IB "symbol" (sometimes underlying, e.g. FDAX uses "DAX")
    tradingClass: Optional[str]  # often equals the product root ("NQ", "MNQ", "FDAX")
    exchange: str                # "CME", "EUREX", "NYMEX", etc.
    currency: Optional[str] = None
    multiplier: Optional[str] = None

    def exchanges_to_try(self) -> List[str]:
        """
        Exchanges to try for contractDetails. Keep deterministic.
        """
        ex = (self.exchange or "").upper()
        if ex == "EUREX":
            # IB sometimes routes Eurex as DTB
            return ["EUREX", "DTB"]
        return [ex] if ex else []


# Minimal starter set; extend as you add products
REGISTRY: Dict[str, FutureProduct] = {
    # US Equity index futures
    "ES": FutureProduct(
        canonical="ES",
        symbol="ES",
        tradingClass="ES",
        exchange="CME",
        currency="USD",
        multiplier="50",
    ),
    "MES": FutureProduct(
        canonical="MES",
        symbol="MES",
        tradingClass="MES",
        exchange="CME",
        currency="USD",
        multiplier="5",
    ),
    "NQ": FutureProduct(
        canonical="NQ",
        symbol="NQ",
        tradingClass="NQ",
        exchange="CME",
        currency="USD",
        multiplier="20",
    ),
    "MNQ": FutureProduct(
        canonical="MNQ",
        symbol="MNQ",
        tradingClass="MNQ",
        exchange="CME",
        currency="USD",
        multiplier="2",
    ),
    # Germany DAX
    "DAX": FutureProduct(
        canonical="DAX",
        symbol="DAX",
        tradingClass="FDAX",
        exchange="EUREX",
        currency="EUR",
        multiplier="25",
    ),
    "FDAX": FutureProduct(
        canonical="FDAX",
        symbol="DAX",
        tradingClass="FDAX",
        exchange="EUREX",
        currency="EUR",
        multiplier="25",
    ),
}


def get_future_product(canonical: str) -> FutureProduct:
    """
    Lookup a futures product by canonical key.

    Order:
      1) Built-in REGISTRY
      2) Discovered cache (futures_discovered.json via futures_discovered.py)

    This is what allows IX:CL.A (or any unknown future) to work after auto-discovery,
    without you hardcoding every product in REGISTRY.
    """
    key = canonical.upper().strip()

    if key in REGISTRY:
       
        return REGISTRY[key]

    # Fallback to discovered cache
    from quant_sandbox.data.futures_discovered import load_discovered

    d = load_discovered(key)
    if d:
        
        return FutureProduct(
            canonical=d.canonical.upper(),
            symbol=d.symbol,
            tradingClass=d.tradingClass,
            exchange=d.exchange,
            currency=d.currency,
            multiplier=d.multiplier,
        )

    raise KeyError(f"Unknown futures product '{key}'. Add it to futures_registry.REGISTRY.")
