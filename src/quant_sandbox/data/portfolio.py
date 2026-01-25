# src/quant_sandbox/data/portfolio.py

from __future__ import annotations

import pandas as pd
from ib_insync import IB


def get_positions(ib: IB) -> pd.DataFrame:
    """
    Fetch all current positions from IBKR account.
    """
    positions = ib.positions()
    
    if not positions:
        return pd.DataFrame()
    
    data = []
    for pos in positions:
        contract = pos.contract
        data.append({
            "symbol": contract.symbol,
            "secType": contract.secType,
            "exchange": contract.exchange,
            "currency": contract.currency,
            "position": pos.position,
            "avgCost": pos.avgCost,
            "marketPrice": pos.marketPrice if hasattr(pos, 'marketPrice') else None,
            "marketValue": pos.marketValue if hasattr(pos, 'marketValue') else None,
            "unrealizedPNL": pos.unrealizedPNL if hasattr(pos, 'unrealizedPNL') else None,
            "realizedPNL": pos.realizedPNL if hasattr(pos, 'realizedPNL') else None,
        })
    
    return pd.DataFrame(data)


def get_account_summary(ib: IB) -> dict:
    """
    Fetch account summary (NetLiquidation, Available Funds, etc.)
    """
    summary = ib.accountSummary()
    
    if not summary:
        return {}
    
    result = {}
    for item in summary:
        result[item.tag] = {
            "value": item.value,
            "currency": item.currency,
        }
    
    return result


def get_portfolio_items(ib: IB) -> pd.DataFrame:
    """
    Fetch portfolio items (more detailed than positions).
    """
    portfolio = ib.portfolio()
    
    if not portfolio:
        return pd.DataFrame()
    
    data = []
    for item in portfolio:
        contract = item.contract
        data.append({
            "symbol": contract.symbol,
            "secType": contract.secType,
            "exchange": contract.exchange,
            "currency": contract.currency,
            "position": item.position,
            "marketPrice": item.marketPrice,
            "marketValue": item.marketValue,
            "averageCost": item.averageCost,
            "unrealizedPNL": item.unrealizedPNL,
            "realizedPNL": item.realizedPNL,
            "account": item.account,
        })
    
    return pd.DataFrame(data)


def get_pnl(ib: IB) -> dict:
    """
    Fetch daily and unrealized PnL.
    """
    return {
        "dailyPnL": ib.pnl(),
        "account": ib.accountSummary(),
    }
