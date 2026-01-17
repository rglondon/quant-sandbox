from __future__ import annotations

import asyncio
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd
from ib_insync import IB, Future, util  # type: ignore

from quant_sandbox.config.settings import IBKR_CLIENT_ID, IBKR_HOST, IBKR_PORT
from quant_sandbox.data.contracts import make_contract


class IBKRWorkerError(RuntimeError):
    pass


@dataclass
class IBKRWorker:
    # --- public readiness surface expected by server.py ---
    ready: threading.Event = field(default_factory=threading.Event, init=False)

    # --- internals ---
    _thread: Optional[threading.Thread] = None
    _ib: Optional[IB] = None
    _loop: Optional[asyncio.AbstractEventLoop] = None

    _startup_done: threading.Event = field(default_factory=threading.Event, init=False)
    _stop_flag: threading.Event = field(default_factory=threading.Event, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    _startup_error: Optional[str] = None

    # Cache: (localSymbol, exchange) -> (ts, [YYYYMMDD...])
    _expiry_cache: Dict[Tuple[str, str], Tuple[float, List[str]]] = field(default_factory=dict, init=False)

    # (UNDERLYING, VENUE) -> (product_key, exchange)
    # NOTE: product_key is what futures_registry knows (e.g. FDAX, ES, MNQ).
    _futures_map: Dict[Tuple[str, str], Tuple[str, str]] = field(
        default_factory=lambda: {
            # ---------- AUTO routing (default behavior) ----------
            ("ES", "AUTO"): ("ES", "CME"),
            ("MNQ", "AUTO"): ("MNQ", "CME"),
            ("NQ", "AUTO"): ("NQ", "CME"),
            ("MES", "AUTO"): ("MES", "CME"),
            ("DAX", "AUTO"): ("FDAX", "EUREX"),
            # ---------- Explicit venue overrides (ONLY where needed) ----------
            ("ES", "CME"): ("ES", "CME"),
            ("MNQ", "CME"): ("MNQ", "CME"),
            ("NQ", "CME"): ("NQ", "CME"),
            ("DAX", "EUREX"): ("FDAX", "EUREX"),
        },
        init=False,
    )

    # Capture last IB error (to stop guessing when history returns empty)
    _last_ib_error: Optional[str] = None
    _last_ib_error_ts: float = 0.0

    # Month code mapping for futureCode: ROOT + (H/M/U/Z etc.) + YY
    _FUT_MONTH_CODE = {
        "F": "01",
        "G": "02",
        "H": "03",
        "J": "04",
        "K": "05",
        "M": "06",
        "N": "07",
        "Q": "08",
        "U": "09",
        "V": "10",
        "X": "11",
        "Z": "12",
    }

    # ----------------------------
    # Startup / shutdown
    # ----------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive() and self.ready.is_set():
            return

        self.ready.clear()
        self._startup_done.clear()
        self._stop_flag.clear()
        self._startup_error = None

        def _run() -> None:
            try:
                util.startLoop()
                self._loop = asyncio.get_event_loop()

                ib = IB()
                ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID, timeout=10)

                # Attach error handler so we can surface IBKR error codes/messages
                def _on_error(reqId, errorCode, errorString, contract):
                    self._last_ib_error_ts = time.time()
                    self._last_ib_error = (
                        f"IB error {errorCode} (reqId={reqId}): {errorString} | contract={contract!r}"
                    )

                ib.errorEvent += _on_error

                self._ib = ib
                self.ready.set()
            except Exception:
                self._startup_error = traceback.format_exc()
            finally:
                self._startup_done.set()

            if self.ready.is_set() and self._ib:
                self._ib.run()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

        if not self._startup_done.wait(timeout=15):
            raise IBKRWorkerError("IBKR startup timeout")

        if not self.ready.is_set():
            raise IBKRWorkerError(self._startup_error or "IBKR startup failed")

    def stop(self) -> None:
        if self._ib and self._loop:
            self._loop.call_soon_threadsafe(self._ib.disconnect)
        self.ready.clear()

    # ----------------------------
    # Futures selector resolution
    # ----------------------------

    async def _discover_future_product_async(self, root: str, venue: str) -> Tuple[str, str]:
        """
        Auto-discover an unknown futures root by probing IBKR contractDetails.

        Returns: (product_key, exchange)
        - product_key is the canonical root (e.g. "CL", "GC")
        - exchange is the best exchange discovered (e.g. "NYMEX", "COMEX", "CME")

        Also writes a record to futures_discovered.json so futures_registry.get_future_product()
        can build a template for make_contract().
        """
        if not self._ib:
            raise IBKRWorkerError("Worker IB instance not available")

        root = root.upper().strip()
        venue = venue.upper().strip()

        # ✅ NEW: if already discovered, do NOT hit IBKR again
        from quant_sandbox.data.futures_discovered import load_discovered, DiscoveredFutureProduct, save_discovered

        existing = load_discovered(root)
        if existing:
            print(f"[IBKRWorker] Using cached discovered futures product {root}: exchange={existing.exchange}")
            return existing.canonical.upper(), existing.exchange

        # Small deterministic list; expand later if needed.
        candidates: List[str] = []
        if venue != "AUTO":
            candidates.append(venue)

        candidates += [
            "CME",
            "CBOT",
            "NYMEX",
            "COMEX",
            "ICEUS",
            "ICEEU",
            "EUREX",
            "DTB",
            "SGX",
            "OSE.JPN",
            "HKFE",
        ]

        # Deduplicate preserving order
        seen = set()
        exchanges_to_try: List[str] = []
        for ex in candidates:
            exu = ex.upper()
            if exu not in seen:
                seen.add(exu)
                exchanges_to_try.append(exu)

        debug: List[str] = []

        for ex in exchanges_to_try:
            templates = [
                Future(symbol=root, exchange=ex),
                Future(localSymbol=root, exchange=ex),
            ]

            for tmpl in templates:
                try:
                    details = await self._ib.reqContractDetailsAsync(tmpl)
                except Exception as e:
                    debug.append(f"{tmpl!r} -> EXC {type(e).__name__}: {e}")
                    continue

                if not details:
                    debug.append(f"{tmpl!r} -> 0 details")
                    continue

                c = details[0].contract

                symbol = (getattr(c, "symbol", None) or root) or root
                symbol = str(symbol).strip()

                exchange = (getattr(c, "exchange", None) or ex) or ex
                exchange = str(exchange).strip()

                currency = getattr(c, "currency", None) or None
                tradingClass = getattr(c, "tradingClass", None) or None
                multiplier = getattr(c, "multiplier", None) or None

                save_discovered(
                    DiscoveredFutureProduct(
                        canonical=root,
                        symbol=symbol,
                        exchange=exchange,
                        currency=currency,
                        tradingClass=tradingClass,
                        multiplier=multiplier,
                    )
                )

                print(
                    f"[IBKRWorker] Discovered futures product {root}: "
                    f"symbol={symbol} exchange={exchange} currency={currency} "
                    f"tradingClass={tradingClass} multiplier={multiplier}"
                )

                return root, exchange

        raise IBKRWorkerError(
            f"Could not auto-discover futures product '{root}' (venue={venue}). Tried:\n"
            + "\n".join("  - " + x for x in debug[:60])
        )


    def resolve_future_selector(self, underlying: str, venue: str, n: int) -> str:
        """
        Resolve:
          futureSel:<UNDERLYING>:<VENUE>:<N>
        into:
          future:<product_key>:<exchange>:<YYYYMMDD>
        """
        underlying = underlying.strip().upper()
        venue = venue.strip().upper()

        if n < 1:
            raise IBKRWorkerError("Future selector must be >= 1")

        # 1) mapping if present
        if venue != "AUTO" and (underlying, venue) in self._futures_map:
            product_key, exchange = self._futures_map[(underlying, venue)]
        elif (underlying, "AUTO") in self._futures_map:
            product_key, exchange = self._futures_map[(underlying, "AUTO")]
        else:
            # 2) auto-discover if not mapped
            if not self._loop or not self.ready.is_set():
                raise IBKRWorkerError("Worker not ready")

            fut = asyncio.run_coroutine_threadsafe(
                self._discover_future_product_async(underlying, venue),
                self._loop,
            )
            product_key, exchange = fut.result(timeout=30.0)

            # cache mapping so next call is instant
            self._futures_map[(underlying, "AUTO")] = (product_key, exchange)


        expiries = self._get_expiries_cached(product_key, exchange)

        if n > len(expiries):
            raise IBKRWorkerError(
                f"Not enough expiries for {product_key}@{exchange}: requested {n}, got {len(expiries)}"
            )

        return f"future:{product_key}:{exchange}:{expiries[n - 1]}"

    def _resolve_futureSel_spec(self, spec: str) -> str:
        # futureSel:UNDERLYING:VENUE:N
        parts = spec.split(":")
        if len(parts) != 4:
            raise IBKRWorkerError("Bad futureSel spec. Expected futureSel:UNDERLYING:VENUE:N")
        _, underlying, venue, n = parts
        try:
            nn = int(n)
        except ValueError:
            raise IBKRWorkerError("Bad futureSel spec: N must be an integer")
        return self.resolve_future_selector(underlying, venue, nn)

    def _resolve_futureCode_spec(self, spec: str) -> str:
        # futureCode:ROOT:VENUE:U25
        parts = spec.split(":")
        if len(parts) != 4:
            raise IBKRWorkerError("Bad futureCode spec. Expected futureCode:ROOT:VENUE:CODE")

        _, root, venue, code = parts
        root = root.strip().upper()
        venue = venue.strip().upper()
        code = code.strip().upper()

        if len(code) != 3:
            raise IBKRWorkerError(f"Bad futureCode '{code}'. Expected like U25")

        m = code[0]
        yy = code[1:]
        if m not in self._FUT_MONTH_CODE or not yy.isdigit():
            raise IBKRWorkerError(f"Bad futureCode '{code}'. Expected like U25")

        y = int(yy)
        year = 2000 + y if y < 70 else 1900 + y
        yyyymm = f"{year}{self._FUT_MONTH_CODE[m]}"

        # Use mapping if available, else auto-discover
        if venue != "AUTO" and (root, venue) in self._futures_map:
            product_key, exchange = self._futures_map[(root, venue)]
        elif (root, "AUTO") in self._futures_map:
            product_key, exchange = self._futures_map[(root, "AUTO")]
        else:
            if not self._loop or not self.ready.is_set():
                raise IBKRWorkerError("Worker not ready")

            fut = asyncio.run_coroutine_threadsafe(
                self._discover_future_product_async(root, venue),
                self._loop,
            )
            product_key, exchange = fut.result(timeout=30.0)

            self._futures_map[(root, "AUTO")] = (product_key, exchange)

        expiries = self._get_expiries_cached(product_key, exchange)

        match = None
        for e in expiries:
            if e.startswith(yyyymm):
                match = e
                break

        if not match:
            raise IBKRWorkerError(
                f"No expiry found for {root}@{venue} matching {yyyymm}. Available (first 12): {expiries[:12]}"
            )

        return f"future:{product_key}:{exchange}:{match}"

    def _get_expiries_cached(self, product_key: str, exchange: str) -> List[str]:
        product_key = product_key.upper().strip()
        exchange = exchange.upper().strip()
        key = (product_key, exchange)
        now = time.time()

        hit = self._expiry_cache.get(key)
        if hit and (now - hit[0]) < 60:
            return hit[1]

        if not self._loop or not self.ready.is_set():
            raise IBKRWorkerError("Worker not ready")

        fut = asyncio.run_coroutine_threadsafe(
            self._fetch_expiries_async(product_key, exchange),
            self._loop,
        )
        expiries = fut.result(timeout=30)
        self._expiry_cache[key] = (now, expiries)
        return expiries

    async def _fetch_expiries_async(self, product_key: str, exchange: str) -> List[str]:
        """
        Fetch valid expiries for a futures product by asking IBKR for contractDetails
        on a "family" template contract, then extracting lastTradeDateOrContractMonth.

        Returns a sorted unique list of expiries (YYYYMMDD preferred, otherwise YYYYMM).
        """
        if not self._ib:
            raise IBKRWorkerError("Worker IB instance not available")

        from quant_sandbox.data.futures_registry import get_future_product

        product_key = product_key.upper().strip()
        exchange = exchange.upper().strip()

        prod = get_future_product(product_key)

        # For some venues IB routes EUREX as DTB; keep deterministic.
        exchanges_to_try = [exchange]
        if exchange.upper() == "EUREX":
            exchanges_to_try = ["EUREX", "DTB"]

        today_yyyymmdd = time.strftime("%Y%m%d", time.gmtime())
        today_yyyymm = time.strftime("%Y%m", time.gmtime())

        last_debug: List[str] = []

        for ex in exchanges_to_try:
            template_kwargs = dict(symbol=prod.symbol, exchange=ex)
            if prod.currency:
                template_kwargs["currency"] = prod.currency
            if prod.tradingClass:
                template_kwargs["tradingClass"] = prod.tradingClass
            if prod.multiplier:
                template_kwargs["multiplier"] = prod.multiplier

            template = Future(**template_kwargs)

            details = await self._ib.reqContractDetailsAsync(template)
            if not details:
                last_debug.append(f"{template!r} -> contractDetails: 0")
                continue

            expiries: List[str] = []
            for d in details:
                c = d.contract
                ltd = (getattr(c, "lastTradeDateOrContractMonth", "") or "").strip()
                if len(ltd) >= 8 and ltd[:8].isdigit():
                    expiries.append(ltd[:8])  # YYYYMMDD
                elif len(ltd) >= 6 and ltd[:6].isdigit():
                    expiries.append(ltd[:6])  # YYYYMM

            expiries = sorted(set(expiries))

            # Filter expired
            filtered: List[str] = []
            for e in expiries:
                if len(e) == 8:
                    if e >= today_yyyymmdd:
                        filtered.append(e)
                else:
                    if e >= today_yyyymm:
                        filtered.append(e)

            print(f"[IBKRWorker] Template={template!r}")
            print(f"[IBKRWorker] Expiries for {product_key}@{ex}: {filtered}")

            if filtered:
                return filtered

            last_debug.append(f"{template!r} -> extracted {len(expiries)} but all filtered out")

        raise IBKRWorkerError(
            f"No expiries extracted for {product_key}. Tried:\n" + "\n".join("  - " + x for x in last_debug)
        )

       # ----------------------------
    # Historical data
    # ----------------------------

    def fetch_close_series(
        self,
        spec: str,
        *,
        duration: str,
        bar_size: str,
        use_rth: bool,
    ) -> pd.Series:
        spec = spec.strip()
        spec_l = spec.lower()

        if spec_l.startswith("futuresel:"):
            spec = self._resolve_futureSel_spec(spec)
        elif spec_l.startswith("futurecode:"):
            spec = self._resolve_futureCode_spec(spec)

        if not self._loop or not self.ready.is_set():
            raise IBKRWorkerError("Worker not ready")

        fut = asyncio.run_coroutine_threadsafe(
            self._fetch_close_series_async(spec, duration, bar_size, use_rth),
            self._loop,
        )
        return fut.result(timeout=60)

    async def _fetch_close_series_async(
        self,
        spec: str,
        duration: str,
        bar_size: str,
        use_rth: bool,
    ) -> pd.Series:
        if not self._ib:
            raise IBKRWorkerError("Worker IB instance not available")

        with self._lock:
            contract = make_contract(spec)
            q = await self._ib.qualifyContractsAsync(contract)
            if q:
                contract = q[0]

            is_fx = spec.lower().startswith("fx:")
            is_fut = spec.lower().startswith(("future:", "futuresel:", "futurecode:"))

            what = "MIDPOINT" if is_fx else "TRADES"
            useRTH = False if (is_fx or is_fut) else use_rth

            bars = await self._ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=what,
                useRTH=useRTH,
                formatDate=1,
            )

        if not bars:
            return pd.Series(dtype="float64")

        df = util.df(bars)
        if df is None or df.empty or "close" not in df.columns:
            return pd.Series(dtype="float64")

        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date")["close"].astype("float64")

    # ----------------------------
    # NEW: OHLCV bars
    # ----------------------------

    def get_ohlcv(
        self,
        symbol: str,
        start: str,
        end: str,
        resolution: str,
        tz: str = "UTC",
        max_bars: int = 5000,
        include_volume: bool = True,
        adjust: str = "none",
        timeout_s: float = 30.0,
    ) -> List[Dict]:

        if not self.ready.is_set():
            raise IBKRWorkerError("IBKRWorker not ready")

        if self._loop is None or self._ib is None:
            raise IBKRWorkerError("IBKRWorker loop/IB not initialized")

        fut = asyncio.run_coroutine_threadsafe(
            self._get_ohlcv_async(
                symbol=symbol,
                start=start,
                end=end,
                resolution=resolution,
                tz=tz,
                max_bars=max_bars,
                include_volume=include_volume,
                adjust=adjust,
            ),
            self._loop,
        )
        return fut.result(timeout=timeout_s)

    async def _get_ohlcv_async(
        self,
        symbol: str,
        start: str,
        end: str,
        resolution: str,
        tz: str,
        max_bars: int,
        include_volume: bool,
        adjust: str,
    ) -> List[Dict]:

        assert self._ib is not None

        bar_size = {
            "1min": "1 min",
            "5min": "5 mins",
            "15min": "15 mins",
            "30min": "30 mins",
            "1H": "1 hour",
            "4H": "4 hours",
            "1D": "1 day",
            "1W": "1 week",
            "1M": "1 month",
        }.get(resolution)

        if bar_size is None:
            raise IBKRWorkerError(f"Unsupported resolution: {resolution}")

        start_ts = pd.Timestamp(start).tz_localize(None)
        end_ts = pd.Timestamp(end).tz_localize(None)

        if end_ts <= start_ts:
            raise IBKRWorkerError("Invalid date range")

        end_dt = end_ts.to_pydatetime()
        days = max(1, (end_ts - start_ts).days)


        if days > 365:
            years = max(1, int((days + 364) // 365))  # ceiling division
            duration_str = f"{years} Y"
        else:
            duration_str = f"{days} D"

        contract = make_contract(symbol)
        self._ib.qualifyContracts(contract)

        what_list = ["MIDPOINT", "TRADES"] if symbol.startswith("FX:") else ["TRADES"]

        bars = None
        for what in what_list:
            bars = await self._ib.reqHistoricalDataAsync(
                contract,
                endDateTime=end_dt,
                durationStr=duration_str,
                barSizeSetting=bar_size,
                whatToShow=what,
                useRTH=False,
                formatDate=1,
            )
            if bars:
                break

        if not bars:
            raise IBKRWorkerError("No OHLCV bars returned")

        out: List[Dict] = []
        for b in bars[-max_bars:]:
            out.append(
                {
                    "t": pd.Timestamp(b.date).isoformat(),
                    "o": float(b.open),
                    "h": float(b.high),
                    "l": float(b.low),
                    "c": float(b.close),
                    "v": float(b.volume) if include_volume and b.volume is not None else None,
                }
            )

        return out
