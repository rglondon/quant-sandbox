# Quant Sandbox – Project Context

## High-level goal
Python-first quantitative research & charting platform.
Backend-first (FastAPI), frontend later (TradingView Lightweight Charts).

## Current stage
Backend analytics engine with expression-based market data and indicators.

## Key architectural decisions
- Python 3.12
- FastAPI backend
- IBKR via ib-insync
- Expression grammar for charts (EQ:, FX:, IX:)
- Futures auto-discovery + caching
- Frontend not started yet

## What already works
- /expr/series → expression-based price series
- Futures resolution: spot, continuous (.A), explicit contracts
- Auto-discovery of futures (CL, GC, etc.) with cache
- /expr/rsi:
  - adjustable period
  - bands / levels
  - multi-series output
  - last value returned for axis labeling

## Current API patterns
- Price series: single series
- Indicators: multi-series payload:
  {
    "expr": "...",
    "series": [
      { "label": "...", "points": [...] }
    ]
  }

## Planned next features (in order)
1. Standardized /expr/chart payload
2. Bollinger Bands
3. Drawdowns
4. Rolling Sharpe
5. Regression & cointegration
6. Seasonality
7. Tear sheets (JSON first)

## Things explicitly NOT in scope yet
- Economic data connectors
- Frontend UI
- Portfolio optimization
