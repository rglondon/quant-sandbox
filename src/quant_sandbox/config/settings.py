# src/quant_sandbox/config/settings.py

from __future__ import annotations

import os

# IBKR / TWS
IBKR_HOST: str = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT: int = int(os.getenv("IBKR_PORT", "7496"))

# IMPORTANT:
# If multiple Python processes start (e.g., crashes/restarts), a fixed clientId can collide (Error 326).
# We default to a PID-derived client id to avoid collisions, but still allow explicit override via env var.
_base_client_id = int(os.getenv("IBKR_CLIENT_ID", "1"))
IBKR_CLIENT_ID: int = int(os.getenv("IBKR_CLIENT_ID_EFFECTIVE", str(_base_client_id + (os.getpid() % 1000))))
