from __future__ import annotations

import json
import threading
import tempfile
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Stored next to your other data modules
_DISCOVERED_PATH = Path(__file__).resolve().with_name("futures_discovered.json")

# In-process lock to prevent concurrent writes
_DISCOVERED_LOCK = threading.Lock()


@dataclass(frozen=True)
class DiscoveredFutureProduct:
    canonical: str              # e.g. "CL", "GC", "NG", "ZN"
    symbol: str                 # IB "symbol" (often same as canonical)
    exchange: str               # e.g. "NYMEX", "COMEX", "CME", "EUREX"
    currency: Optional[str] = None
    tradingClass: Optional[str] = None
    multiplier: Optional[str] = None


def load_discovered(canonical: str) -> Optional[DiscoveredFutureProduct]:
    canonical = canonical.upper().strip()

    if not _DISCOVERED_PATH.exists():
        return None

    try:
        data = json.loads(_DISCOVERED_PATH.read_text())
    except Exception:
        return None

    row = data.get(canonical)
    if not row:
        return None

    return DiscoveredFutureProduct(
        canonical=canonical,
        symbol=row.get("symbol", canonical),
        exchange=row["exchange"],
        currency=row.get("currency"),
        tradingClass=row.get("tradingClass"),
        multiplier=row.get("multiplier"),
    )


def _atomic_write_json(path: Path, data: dict) -> None:
    """
    Write JSON atomically to avoid corruption if multiple writes occur.
    Safe on macOS and Linux.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=path.name,
        suffix=".tmp"
    )

    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())

        # Atomic replace
        os.replace(tmp, path)

    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def save_discovered(p: DiscoveredFutureProduct) -> None:
    """
    Persist a newly discovered futures product safely.
    """
    with _DISCOVERED_LOCK:
        if _DISCOVERED_PATH.exists():
            try:
                data = json.loads(_DISCOVERED_PATH.read_text())
            except Exception:
                data = {}
        else:
            data = {}

        data[p.canonical] = {
            "symbol": p.symbol,
            "exchange": p.exchange,
            "currency": p.currency,
            "tradingClass": p.tradingClass,
            "multiplier": p.multiplier,
        }

        _atomic_write_json(_DISCOVERED_PATH, data)
