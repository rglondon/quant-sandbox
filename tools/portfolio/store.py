from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class SnapshotStore:
    path: str = "portfolio_snapshots.db"

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, check_same_thread=False)

    def init(self) -> None:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    ts TEXT PRIMARY KEY,
                    net_liq REAL,
                    daily_pnl REAL,
                    unreal_pnl REAL,
                    realized_pnl REAL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    ts TEXT,
                    symbol TEXT,
                    secType TEXT,
                    exchange TEXT,
                    currency TEXT,
                    qty REAL,
                    avgCost REAL,
                    marketPrice REAL,
                    marketValue REAL,
                    sector TEXT,
                    country TEXT,
                    PRIMARY KEY (ts, symbol)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS lots (
                    ts TEXT,
                    symbol TEXT,
                    time TEXT,
                    side TEXT,
                    qty REAL,
                    price REAL,
                    remaining_qty REAL,
                    PRIMARY KEY (ts, symbol, time, price, side)
                )
                """
            )
            conn.commit()

    def write_snapshot(self, ts: str, summary: dict, positions: pd.DataFrame) -> None:
        self.init()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO snapshots (ts, net_liq, daily_pnl, unreal_pnl, realized_pnl) VALUES (?, ?, ?, ?, ?)",
                (
                    ts,
                    float(summary.get("NetLiquidation", 0.0)),
                    float(summary.get("DailyPnL", 0.0)),
                    float(summary.get("UnrealizedPnL", 0.0)),
                    float(summary.get("RealizedPnL", 0.0)),
                ),
            )

            if not positions.empty:
                cols = [
                    "symbol",
                    "secType",
                    "exchange",
                    "currency",
                    "qty",
                    "avgCost",
                    "marketPrice",
                    "marketValue",
                    "sector",
                    "country",
                ]
                for _, row in positions[cols].iterrows():
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO positions
                        (ts, symbol, secType, exchange, currency, qty, avgCost, marketPrice, marketValue, sector, country)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ts,
                            row.get("symbol"),
                            row.get("secType"),
                            row.get("exchange"),
                            row.get("currency"),
                            float(row.get("qty", 0.0) or 0.0),
                            float(row.get("avgCost", 0.0) or 0.0),
                            float(row.get("marketPrice", 0.0) or 0.0),
                            float(row.get("marketValue", 0.0) or 0.0),
                            row.get("sector"),
                            row.get("country"),
                        ),
                    )
            conn.commit()

    def write_lots(self, ts: str, lots: pd.DataFrame) -> None:
        self.init()
        if lots.empty:
            return
        with self._conn() as conn:
            for _, row in lots.iterrows():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO lots
                    (ts, symbol, time, side, qty, price, remaining_qty)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ts,
                        row.get("symbol"),
                        str(row.get("time")),
                        row.get("side"),
                        float(row.get("qty", 0.0) or 0.0),
                        float(row.get("price", 0.0) or 0.0),
                        float(row.get("remaining_qty", 0.0) or 0.0),
                    ),
                )
            conn.commit()

    def read_snapshots(self) -> pd.DataFrame:
        self.init()
        with self._conn() as conn:
            return pd.read_sql_query("SELECT * FROM snapshots ORDER BY ts", conn)

    def read_positions(self, ts: Optional[str] = None) -> pd.DataFrame:
        self.init()
        with self._conn() as conn:
            if ts:
                return pd.read_sql_query("SELECT * FROM positions WHERE ts = ?", conn, params=(ts,))
            return pd.read_sql_query("SELECT * FROM positions", conn)

    def read_lots(self, ts: Optional[str] = None) -> pd.DataFrame:
        self.init()
        with self._conn() as conn:
            if ts:
                return pd.read_sql_query("SELECT * FROM lots WHERE ts = ?", conn, params=(ts,))
            return pd.read_sql_query("SELECT * FROM lots", conn)
