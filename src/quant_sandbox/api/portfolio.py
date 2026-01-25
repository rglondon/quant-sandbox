# src/quant_sandbox/api/portfolio.py

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from quant_sandbox.providers.ibkr_worker import IBKRWorker

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


class PortfolioSummary(BaseModel):
    total_value: float
    total_pnl: float
    positions_count: int
    cash_balance: float


class PositionItem(BaseModel):
    symbol: str
    secType: str
    exchange: str
    currency: str
    position: float
    avgCost: float
    marketPrice: Optional[float]
    marketValue: Optional[float]
    unrealizedPNL: Optional[float]
    realizedPNL: Optional[float]


class PortfolioResponse(BaseModel):
    summary: PortfolioSummary
    positions: List[PositionItem]
    account: Dict[str, Any]


def get_ibkr_worker() -> IBKRWorker:
    """Get the IBKR worker from app state."""
    from quant_sandbox.api.server import app
    return app.state.ibkr_worker


@router.get("/summary")
def get_portfolio_summary() -> PortfolioResponse:
    """
    Get portfolio summary including positions and P&L.
    """
    worker = get_ibkr_worker()
    
    if not worker.ready.is_set():
        raise HTTPException(status_code=503, detail="IBKR not connected")
    
    try:
        ib = worker._ib
        
        # Get positions
        from quant_sandbox.data.portfolio import get_positions, get_account_summary
        positions_df = get_positions(ib)
        
        # Calculate summary
        total_value = positions_df["marketValue"].sum() if not positions_df.empty else 0
        total_pnl = positions_df["unrealizedPNL"].sum() if not positions_df.empty else 0
        
        # Get account cash
        account = get_account_summary(ib)
        cash_balance = float(account.get("CashBalance", {}).get("value", 0)) if "CashBalance" in account else 0
        
        # Build response
        positions_list = []
        for _, row in positions_df.iterrows():
            positions_list.append(PositionItem(
                symbol=row["symbol"],
                secType=row["secType"],
                exchange=row["exchange"],
                currency=row["currency"],
                position=row["position"],
                avgCost=row["avgCost"],
                marketPrice=row.get("marketPrice"),
                marketValue=row.get("marketValue"),
                unrealizedPNL=row.get("unrealizedPNL"),
                realizedPNL=row.get("realizedPNL"),
            ))
        
        return PortfolioResponse(
            summary=PortfolioSummary(
                total_value=total_value,
                total_pnl=total_pnl,
                positions_count=len(positions_list),
                cash_balance=cash_balance,
            ),
            positions=positions_list,
            account=account,
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions")
def get_positions() -> List[PositionItem]:
    """
    Get all positions.
    """
    worker = get_ibkr_worker()
    
    if not worker.ready.is_set():
        raise HTTPException(status_code=503, detail="IBKR not connected")
    
    try:
        from quant_sandbox.data.portfolio import get_positions
        positions_df = get_positions(worker._ib)
        
        positions_list = []
        for _, row in positions_df.iterrows():
            positions_list.append(PositionItem(
                symbol=row["symbol"],
                secType=row["secType"],
                exchange=row["exchange"],
                currency=row["currency"],
                position=row["position"],
                avgCost=row["avgCost"],
                marketPrice=row.get("marketPrice"),
                marketValue=row.get("marketValue"),
                unrealizedPNL=row.get("unrealizedPNL"),
                realizedPNL=row.get("realizedPNL"),
            ))
        
        return positions_list
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/account")
def get_account() -> Dict[str, Any]:
    """
    Get account summary.
    """
    worker = get_ibkr_worker()
    
    if not worker.ready.is_set():
        raise HTTPException(status_code=503, detail="IBKR not connected")
    
    try:
        from quant_sandbox.data.portfolio import get_account_summary
        return get_account_summary(worker._ib)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
