"""main.py — FastAPI application (Phases 1-3)."""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS, LLM_BACKEND, TICKERS
from app.database import init_db
from app.routers import auth, market, watchlist, holdings, chat

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Stock Trading API", version="0.3.0")

app.add_middleware(
    CORSMiddleware, allow_origins=CORS_ORIGINS,
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok", "llm_backend": LLM_BACKEND, "universe": len(TICKERS)}


app.include_router(auth.router)
app.include_router(market.router)
app.include_router(watchlist.router)
app.include_router(holdings.router)
app.include_router(chat.router)
