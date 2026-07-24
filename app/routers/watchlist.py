"""Watchlist routes (protected): live quotes, validated add, remove."""
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, bridge
from app.auth import get_current_user
from app.schemas import WatchlistResponse

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def _quotes(user, db):
    tickers = [i.ticker for i in db.query(models.WatchlistItem)
               .filter(models.WatchlistItem.user_id == user.id).all()]
    if not tickers:
        return {"items": []}
    with ThreadPoolExecutor(max_workers=8) as pool:
        items = list(pool.map(bridge.safe_quote, tickers))
    return {"items": items}


@router.get("", response_model=WatchlistResponse)
def get_watchlist(current_user: models.User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    return _quotes(current_user, db)


@router.post("/{ticker}", response_model=WatchlistResponse)
def add_watchlist(ticker: str,
                  current_user: models.User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    ticker = ticker.upper().strip()
    # validate: must be a real, priceable ticker
    try:
        bridge.get_quote(ticker)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"'{ticker}' is not a valid ticker")

    exists = db.query(models.WatchlistItem).filter(
        models.WatchlistItem.user_id == current_user.id,
        models.WatchlistItem.ticker == ticker).first()
    if not exists:
        db.add(models.WatchlistItem(user_id=current_user.id, ticker=ticker)); db.commit()
    return _quotes(current_user, db)


@router.delete("/{ticker}", response_model=WatchlistResponse)
def remove_watchlist(ticker: str,
                     current_user: models.User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    ticker = ticker.upper().strip()
    db.query(models.WatchlistItem).filter(
        models.WatchlistItem.user_id == current_user.id,
        models.WatchlistItem.ticker == ticker).delete()
    db.commit()
    return _quotes(current_user, db)
