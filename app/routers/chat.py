"""Agentic chat (protected): Claude decides which tools to call, all user-scoped.
No cross-user mixing — every handler queries by current_user.id."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, bridge
from app.auth import get_current_user
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


def _handlers(user, db):
    """Build the tool handlers, each closed over the current user + db session."""

    def get_stock_data(ticker):
        return bridge.tool_stock_data(ticker)

    def get_my_holdings():
        rows = db.query(models.Holding).filter(models.Holding.user_id == user.id).all()
        if not rows:
            return {"holdings": [], "note": "user owns no stocks"}
        return {"holdings": [
            {"ticker": h.ticker, "shares": h.shares, "avg_price": round(h.avg_price, 2)}
            for h in rows
        ]}

    def get_my_transactions(ticker=None):
        q = db.query(models.Transaction).filter(models.Transaction.user_id == user.id)
        if ticker:
            q = q.filter(models.Transaction.ticker == ticker.upper().strip())
        rows = q.order_by(models.Transaction.timestamp).all()
        if not rows:
            return {"transactions": [], "note": "no transactions found"}
        return {"transactions": [
            {"action": t.action, "ticker": t.ticker, "shares": t.shares,
             "price": round(t.price, 2), "date": t.timestamp.strftime("%Y-%m-%d %H:%M")}
            for t in rows
        ]}

    def get_my_watchlist():
        rows = db.query(models.WatchlistItem).filter(
            models.WatchlistItem.user_id == user.id).all()
        return {"watchlist": [w.ticker for w in rows]}

    return {
        "get_stock_data": get_stock_data,
        "get_my_holdings": get_my_holdings,
        "get_my_transactions": get_my_transactions,
        "get_my_watchlist": get_my_watchlist,
    }


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest,
         current_user: models.User = Depends(get_current_user),
         db: Session = Depends(get_db)):
    handlers = _handlers(current_user, db)
    history = [m.dict() for m in req.history]
    answer = bridge.run_agentic_chat(req.message, history, handlers)
    return {"answer": answer}
