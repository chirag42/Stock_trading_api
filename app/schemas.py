"""schemas.py — Pydantic request/response models."""
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field


# ── Market (Phase 1) ──────────────────────────────────────────────
class Opportunity(BaseModel):
    ticker: str
    price: Optional[float] = None
    rsi: Optional[float] = None
    indicator: str                 # BUY or WAIT (unbought)
    reason: str
    error: Optional[str] = None


class OpportunitiesResponse(BaseModel):
    count: int
    opportunities: List[Opportunity]


class ChartPoint(BaseModel):
    date: str
    close: float


class ChartResponse(BaseModel):
    ticker: str
    period: str
    points: List[ChartPoint]


class NewsItem(BaseModel):
    title: str
    description: str = ""
    url: str = ""


class NewsResponse(BaseModel):
    ticker: str
    articles: List[NewsItem]


class AnalysisResponse(BaseModel):
    ticker: str
    decision: str
    reasoning: str
    backend: str


# ── Auth (Phase 2) ────────────────────────────────────────────────
class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, description="At least 8 characters")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str


class WatchQuote(BaseModel):
    ticker: str
    price: Optional[float] = None
    change_pct: Optional[float] = None
    error: Optional[str] = None


class WatchlistResponse(BaseModel):
    items: List[WatchQuote]


# ── Holdings (Phase 3) ────────────────────────────────────────────
class BuyRequest(BaseModel):
    ticker: str
    shares: float = Field(gt=0, description="Number of shares to buy")


class SellRequest(BaseModel):
    ticker: str
    shares: float = Field(gt=0, description="Number of shares to sell")


class HoldingItem(BaseModel):
    ticker: str
    shares: float
    avg_price: float
    current_price: Optional[float] = None
    pnl_pct: Optional[float] = None
    indicator: str                 # SELL or HOLD (owned)
    reason: str


class HoldingsResponse(BaseModel):
    holdings: List[HoldingItem]


class HoldingAnalysisResponse(BaseModel):
    ticker: str
    decision: str                  # SELL or HOLD
    reasoning: str
    pnl_pct: float
    current_price: float
    backend: str


class SummaryResponse(BaseModel):
    ticker: str
    price: float
    rsi: float
    rsi_signal: str
    macd: float
    macd_signal: str
