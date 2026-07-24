"""Market routes: opportunities list + per-stock chart, news, analysis."""
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException

from app import bridge
from app.config import TICKERS
from app.schemas import (
    OpportunitiesResponse, ChartResponse, NewsResponse, AnalysisResponse, Opportunity, SummaryResponse,
)

router = APIRouter(tags=["market"])


@router.get("/opportunities", response_model=OpportunitiesResponse)
def opportunities():
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(bridge.classify_opportunity, TICKERS))
    return {"count": len(results), "opportunities": results}


@router.get("/stocks/{ticker}/chart", response_model=ChartResponse)
def chart(ticker: str, period: str = "3mo"):
    ticker = ticker.upper()
    points = bridge.get_chart(ticker, period)
    if not points:
        raise HTTPException(status_code=404, detail=f"No price data for {ticker}")
    return {"ticker": ticker, "period": period, "points": points}


@router.get("/stocks/{ticker}/news", response_model=NewsResponse)
def news(ticker: str):
    ticker = ticker.upper()
    return {"ticker": ticker, "articles": bridge.get_news(ticker)}


@router.get("/stocks/{ticker}/analysis", response_model=AnalysisResponse)
def analysis(ticker: str):
    ticker = ticker.upper()
    try:
        return bridge.get_analysis(ticker)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Analysis failed: {exc}")


@router.get("/stocks/{ticker}/summary", response_model=SummaryResponse)
def summary(ticker: str):
    ticker = ticker.upper()
    try:
        return bridge.get_summary(ticker)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"No data for {ticker}: {exc}")
