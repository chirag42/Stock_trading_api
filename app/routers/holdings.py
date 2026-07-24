"""Holdings routes (protected): list, buy, sell, position-aware analysis."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, bridge
from app.auth import get_current_user
from app.schemas import (
    BuyRequest, SellRequest, HoldingsResponse, HoldingAnalysisResponse,
)

router = APIRouter(prefix="/holdings", tags=["holdings"])


def _list_holdings(user, db):
    rows = db.query(models.Holding).filter(models.Holding.user_id == user.id).all()
    out = []
    for h in rows:
        price, indicator, reason = bridge.holding_indicator(h.ticker)
        pnl = round((price - h.avg_price) / h.avg_price * 100, 2) if (price and h.avg_price) else None
        out.append({
            "ticker": h.ticker, "shares": h.shares, "avg_price": round(h.avg_price, 2),
            "current_price": price, "pnl_pct": pnl,
            "indicator": indicator, "reason": reason,
        })
    return {"holdings": out}


@router.get("", response_model=HoldingsResponse)
def list_holdings(current_user: models.User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    return _list_holdings(current_user, db)


@router.post("/buy", response_model=HoldingsResponse)
def buy(req: BuyRequest,
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)):
    ticker = req.ticker.upper()
    try:
        price = bridge.current_price(ticker)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not price {ticker}")

    h = db.query(models.Holding).filter(
        models.Holding.user_id == current_user.id, models.Holding.ticker == ticker).first()
    if h:
        # weighted-average cost basis
        total_cost = h.shares * h.avg_price + req.shares * price
        h.shares += req.shares
        h.avg_price = total_cost / h.shares
    else:
        db.add(models.Holding(user_id=current_user.id, ticker=ticker,
                              shares=req.shares, avg_price=price))
    db.commit()
    return _list_holdings(current_user, db)


@router.post("/sell", response_model=HoldingsResponse)
def sell(req: SellRequest,
         current_user: models.User = Depends(get_current_user),
         db: Session = Depends(get_db)):
    ticker = req.ticker.upper()
    h = db.query(models.Holding).filter(
        models.Holding.user_id == current_user.id, models.Holding.ticker == ticker).first()
    if not h:
        raise HTTPException(status_code=400, detail=f"You do not own {ticker}")
    if req.shares > h.shares:
        raise HTTPException(status_code=400,
                            detail=f"Only {h.shares} shares of {ticker} owned")
    h.shares -= req.shares
    if h.shares <= 0:
        db.delete(h)
    db.commit()
    return _list_holdings(current_user, db)


@router.get("/{ticker}/analysis", response_model=HoldingAnalysisResponse)
def holding_analysis(ticker: str,
                     current_user: models.User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    ticker = ticker.upper()
    h = db.query(models.Holding).filter(
        models.Holding.user_id == current_user.id, models.Holding.ticker == ticker).first()
    if not h:
        raise HTTPException(status_code=404, detail=f"You do not own {ticker}")
    try:
        return bridge.analyze_holding(ticker, h.shares, h.avg_price)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Analysis failed: {exc}")
