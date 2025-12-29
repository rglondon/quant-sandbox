# src/quant_sandbox/api/server.py

from __future__ import annotations

import time
from fastapi import FastAPI

from quant_sandbox.api.debug import router as debug_router
from quant_sandbox.api.metrics import router as metrics_router
from quant_sandbox.providers.ibkr_worker import IBKRWorker


def _wait_for_worker_ready(worker: IBKRWorker, timeout_s: float = 15.0) -> None:
    """
    Blocks until the worker signals readiness, with a hard timeout.
    """
    deadline = time.time() + timeout_s

    # Event-style readiness
    for attr in ("ready", "ready_event"):
        ev = getattr(worker, attr, None)
        if ev is not None and hasattr(ev, "wait"):
            remaining = max(0.0, deadline - time.time())
            if not ev.wait(timeout=remaining):
                raise RuntimeError(f"IBKRWorker did not become ready within {timeout_s:.1f}s")
            return

    # Bool / callable readiness
    while time.time() < deadline:
        is_ready_attr = getattr(worker, "is_ready", None)
        if callable(is_ready_attr):
            if is_ready_attr():
                return
        elif isinstance(is_ready_attr, bool):
            if is_ready_attr:
                return
        time.sleep(0.05)

    raise RuntimeError(f"IBKRWorker did not become ready within {timeout_s:.1f}s")


def create_app() -> FastAPI:
    app = FastAPI()

    # ✅ INCLUDE ROUTERS HERE (ONCE)
    app.include_router(debug_router)
    app.include_router(metrics_router)

    # Construct worker (do NOT start yet)
    app.state.ibkr_worker = IBKRWorker()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.on_event("startup")
    def on_startup() -> None:
        worker: IBKRWorker = app.state.ibkr_worker
        worker.start()
        _wait_for_worker_ready(worker, timeout_s=15.0)

    @app.on_event("shutdown")
    def on_shutdown() -> None:
        worker: IBKRWorker = app.state.ibkr_worker
        try:
            worker.stop()
        except Exception:
            pass

    return app


# ✅ THIS is what uvicorn loads
app = create_app()
