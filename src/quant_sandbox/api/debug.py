from __future__ import annotations

from fastapi import APIRouter
from quant_sandbox.data.futures_registry import REGISTRY
from quant_sandbox.data.futures_discovered import _DISCOVERED_PATH  # just for path visibility
import json

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/futures")
def debug_futures() -> dict:
    # Static registry
    static = {
        k: {
            "canonical": v.canonical,
            "symbol": v.symbol,
            "exchange": v.exchange,
            "currency": v.currency,
            "tradingClass": v.tradingClass,
            "multiplier": v.multiplier,
        }
        for k, v in REGISTRY.items()
    }

    # Discovered cache
    if _DISCOVERED_PATH.exists():
        try:
            discovered = json.loads(_DISCOVERED_PATH.read_text())
        except Exception:
            discovered = {"_error": "Could not parse futures_discovered.json"}
    else:
        discovered = {}

    return {
        "static_registry_count": len(static),
        "discovered_count": len(discovered),
        "discovered_path": str(_DISCOVERED_PATH),
        "static_registry": static,
        "discovered": discovered,
    }
