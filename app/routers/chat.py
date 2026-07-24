"""Chat route (protected): ask questions about YOUR portfolio.
Context is built strictly from current_user, and the call is stateless —
no cross-user mixing is possible."""
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, bridge
from app.auth import get_current_user
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest,
         current_user: models.User = Depends(get_current_user),
         db: Session = Depends(get_db)):
    # Gather THIS user's holdings + live quote
    rows = db.query(models.Holding).filter(models.Holding.user_id == current_user.id).all()
    tickers = [h.ticker for h in rows]
    quotes = {}
    if tickers:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for q in pool.map(bridge.safe_quote, tickers):
                quotes[q["ticker"]] = q

    holdings_ctx = []
    for h in rows:
        q = quotes.get(h.ticker, {})
        price = q.get("price")
        pnl = round((price - h.avg_price) / h.avg_price * 100, 2) if (price and h.avg_price) else None
        holdings_ctx.append({
            "ticker": h.ticker, "shares": h.shares, "avg_price": round(h.avg_price, 2),
            "price": price, "pnl_pct": pnl, "change_pct": q.get("change_pct"),
        })

    watchlist = [w.ticker for w in db.query(models.WatchlistItem)
                 .filter(models.WatchlistItem.user_id == current_user.id).all()]

    history = [m.dict() for m in req.history]
    answer = bridge.chat(req.message, history, holdings_ctx, watchlist)
    return {"answer": answer}
