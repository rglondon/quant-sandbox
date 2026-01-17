# Quant Sandbox – Project Context (Refreshed)

## Identity & Purpose
Built by a **hedge fund PM / trader** as a **personal quantitative research + decision-support platform**.

Acts as a **quant assistant**:
- Cross-asset analysis (equities, FX, indices, futures)
- Regime awareness
- Trade sizing & risk diagnostics
- Portfolio & exposure understanding
- Idea validation before execution

**Not** a retail trading app.
Designed to replicate/extend workflows seen in Bloomberg/Koyfin/SpotGamma with **transparent, composable backend control**.

Subscriber model may exist later, but is **not a priority**.

---

## High-Level Goal
**Python-first** research platform with:
- Backend-first architecture (FastAPI)
- Frontend-agnostic analytics
- Chart-ready APIs usable by Web UI / Excel / TradingView-style frontends

---

## Current Stage
- Backend analytics engine is production-grade
- UI work so far is exploratory/disposable
- IBKR integration via `ib_insync` + background worker thread
- Futures expiry discovery + caching is robust
- Cash index mapping has been painful; acceptable to move on and widen focus

---

## Environment
- macOS
- Python 3.12 + venv
- FastAPI
- Market data: IBKR (ib_insync)

---

## Core Design Principles
- PM-first: every output answers “what decision does this help me make?”
- Composable pipeline: Series → Indicators → Diagnostics → Orchestration
- Cross-asset by default
- Frontend-agnostic backend
- Prefer best-in-class libraries; orchestrate rather than reinvent

---

## Canonical Symbol Grammar
- Equities: `EQ:SPY`, `EQ:700.HK`, `EQ:SAP.GY`, `EQ:VOD.LN`
- FX: `FX:EURUSD`
- Indices/spot: `IX:DAX`, `IX:SX7E`, `IX:N225`
- Futures continuous/positional: `IX:ES.A`, `IX:ES1`, `IX:DAX.A`
- Futures explicit codes: `IX:ESU26`

Expressions support `+ - * /` and parentheses.

---

## What Works Today
### APIs
- `POST /expr/series` expression evaluation + alignment
- `POST /expr/chart` canonical chart contract (frontend source of truth)
- Indicators: RSI/MA/Bollinger/Drawdown/Sharpe/Zscore/Stats
- `POST /expr/pack` orchestrates price + overlays + panels + stats

Everything is chart-ready (series points payload format).

---

## Immediate Product Requirements (Next Build)
### Charting v2 (must-have)
- Multi-security charting (multiple series per pane)
- Left/right axes per series
- Axis inversion
- Normalization (base100, zscore)
- Candlesticks (OHLC)
- Volume (where available)
- Volume distribution (volume profile / value area)

### Navigation & Pages
- Landing page: **Markets Today** (Koyfin-style overview dashboard)
- Left-nav or dropdown:
  - Markets Today
  - Tools: Charting / Seasonality / Trade Sizing / Tear Sheets
  - Portfolio Analysis: Holdings / Exposure / Performance / Risk

### Portfolio Analysis (Koyfin-inspired)
- CSV upload + portfolio currency base
- Holdings table with computed columns
- Exposure breakdowns (sector/industry/country/currency)
- P/L + performance time series + attribution
- Risk: beta/vol/correlation (factor-lite later)

### TradingView Parallel Path
- Add a TradingView-compatible OHLCV + symbol resolution adapter for best-in-class chart UX.

---

## Near-Term Roadmap (Ordered)
1) Chart contract v2 + OHLCV + volume + multi-axis + invert
2) Volume profile endpoint
3) Markets Today page schema + UI navigation shell
4) Seasonality tab wired to existing code
5) Portfolio ingestion + exposure/PnL/performance/risk
6) TradingView integration path (chart replacement option)

---

## Not in Scope (Yet)
- Hand-built Bloomberg-quality UI from scratch
- Auth/subscriptions
- Full portfolio optimization
- Economic data connectors (FRED etc.) until core UX is stable
