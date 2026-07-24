"""
bridge.py — the only file that talks to the existing trading system.
Adds the trading repo to sys.path, builds heavy singletons once, and exposes
small functions the routers call (market data, news, analysis, holdings analysis).
"""

import logging
import sys

from app.config import LLM_BACKEND, TRADING_REPO_PATH

logger = logging.getLogger("bridge")

if TRADING_REPO_PATH and TRADING_REPO_PATH not in sys.path:
    sys.path.insert(0, TRADING_REPO_PATH)

import yfinance as yf
from services.data_ingestion import DataIngestionService
from services.sentiment_analysis import SentimentAnalysisService
from services.sentiment_analysis.fetcher import NewsFetcher
from agents.strategy_agent import StrategyAgent

try:
    from services.data_ingestion.fundamentals import (
        FundamentalsFetcher, format_fundamentals_for_prompt
    )
    _HAS_FUNDAMENTALS = True
except Exception:  # noqa: BLE001
    _HAS_FUNDAMENTALS = False

_data = DataIngestionService(cache_ttl=240)
_sentiment = SentimentAnalysisService()
_news = NewsFetcher()
_agent = StrategyAgent(backend=LLM_BACKEND)
_fundamentals = FundamentalsFetcher() if _HAS_FUNDAMENTALS else None


def _fund_block(ticker: str):
    if _fundamentals is None:
        return None
    try:
        return format_fundamentals_for_prompt(_fundamentals.fetch(ticker))
    except Exception:  # noqa: BLE001
        return None


# ── Opportunities (unbought → BUY / WAIT, fast, no LLM) ────────────
def _opportunity_indicator(rsi, macd, signal):
    if rsi < 35 and macd > signal:
        return "BUY", "Oversold RSI with bullish MACD — potential entry."
    if rsi > 65:
        return "WAIT", "Overbought — not a good entry right now."
    return "WAIT", "No strong entry signal yet."


def classify_opportunity(ticker: str) -> dict:
    try:
        m = _data.get_latest_summary(ticker)
        indicator, reason = _opportunity_indicator(m["rsi"], m["macd"], m["signal"])
        return {"ticker": ticker, "price": round(float(m["close_price"]), 2),
                "rsi": round(float(m["rsi"]), 1), "indicator": indicator, "reason": reason}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"opportunity failed for {ticker}: {exc}")
        return {"ticker": ticker, "indicator": "WAIT",
                "reason": "Data unavailable.", "error": type(exc).__name__}


# ── Chart / news / analysis (unbought detail) ─────────────────────
def get_chart(ticker: str, period: str = "3mo") -> list:
    df = yf.Ticker(ticker).history(period=period)
    if df is None or df.empty:
        return []
    return [{"date": idx.strftime("%Y-%m-%d"), "close": round(float(row), 2)}
            for idx, row in df["Close"].items()]


def get_news(ticker: str, count: int = 8) -> list:
    try:
        articles = _news.fetch(ticker, count)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"news failed for {ticker}: {exc}")
        return []
    return [{"title": a.get("title", ""), "description": a.get("description", ""),
             "url": a.get("url", "")} for a in articles]


def get_analysis(ticker: str) -> dict:
    market = _data.get_latest_summary(ticker)
    sentiment = _sentiment.get_aggregated_sentiment(ticker)
    result = _agent.decide(market, sentiment, _fund_block(ticker))
    return {"ticker": ticker, "decision": result["decision"],
            "reasoning": result["llm_reasoning"], "backend": LLM_BACKEND}


# ── Holdings (owned → SELL / HOLD, position-aware) ────────────────
def current_price(ticker: str) -> float:
    return round(float(_data.get_latest_summary(ticker)["close_price"]), 2)


def holding_indicator(ticker: str):
    """Fast, no-LLM exit indicator for the holdings list: SELL or HOLD."""
    try:
        m = _data.get_latest_summary(ticker)
        price = round(float(m["close_price"]), 2)
        if m["rsi"] > 65 and m["macd"] < m["signal"]:
            return price, "SELL", "Overbought with bearish MACD — consider taking profit."
        return price, "HOLD", "No exit signal — position looks fine."
    except Exception as exc:  # noqa: BLE001
        return None, "HOLD", f"Data unavailable ({type(exc).__name__})."


def _parse_sell_hold(text: str) -> str:
    first = text.strip().split()[0].upper().strip(".,!?") if text.strip() else ""
    if first in {"SELL", "HOLD"}:
        return first
    for w in text.upper().split():
        if w.strip(".,!?") in {"SELL", "HOLD"}:
            return w.strip(".,!?")
    return "HOLD"


def analyze_holding(ticker: str, shares: float, avg_price: float) -> dict:
    """Full position-aware LLM analysis for an owned stock (SELL or HOLD only)."""
    m = _data.get_latest_summary(ticker)
    price = round(float(m["close_price"]), 2)
    pnl = ((price - avg_price) / avg_price * 100) if avg_price else 0.0
    sentiment = _sentiment.get_aggregated_sentiment(ticker)
    fund = _fund_block(ticker)

    prompt = "\n".join([
        "You are a portfolio advisor. The user ALREADY OWNS this position.",
        f"POSITION: {shares} shares of {ticker}, bought at ${avg_price}, "
        f"now ${price} ({pnl:+.1f}% profit/loss).",
        "",
        "TECHNICAL INDICATORS",
        f"RSI: {m['rsi']}   MACD: {m['macd']} vs Signal {m['signal']}",
        "",
        "MARKET SENTIMENT",
        f"Overall: {sentiment['overall'].upper()} "
        f"({sentiment['positive']}+/{sentiment['negative']}- of {sentiment['articles_analyzed']})",
        "",
        (fund or "FUNDAMENTALS\n(unavailable)"),
        "",
        "DECISION RULES",
        "- Recommend SELL to exit the position if indicators, sentiment, or risk suggest it.",
        "- Recommend HOLD to keep the position otherwise.",
        "- Only SELL or HOLD — the user already owns this; BUY is not an option.",
        "",
        "YOUR TASK",
        "1. First line must be exactly one word: SELL or HOLD",
        "2. Give 2-3 short reasons (mention the profit/loss where relevant)",
        "3. Mention one key risk",
    ])
    resp = _agent.llm_client.query(prompt)
    return {"ticker": ticker, "decision": _parse_sell_hold(resp), "reasoning": resp,
            "pnl_pct": round(pnl, 2), "current_price": price, "backend": LLM_BACKEND}


def get_summary(ticker: str) -> dict:
    """Fast key stats for the stock header (no LLM, no news fetch)."""
    m = _data.get_latest_summary(ticker)
    return {
        "ticker": ticker,
        "price": round(float(m["close_price"]), 2),
        "rsi": round(float(m["rsi"]), 1),
        "rsi_signal": m.get("rsi_signal", ""),
        "macd": round(float(m["macd"]), 3),
        "macd_signal": m.get("macd_signal", ""),
    }


def get_quote(ticker: str) -> dict:
    """Current price + day change % (one yfinance call). Raises if invalid."""
    h = yf.Ticker(ticker).history(period="2d")
    if h is None or h.empty:
        raise ValueError(f"No data for {ticker}")
    closes = [float(x) for x in h["Close"].tolist() if x == x]
    if not closes:
        raise ValueError(f"No data for {ticker}")
    price = round(closes[-1], 2)
    prev = closes[-2] if len(closes) >= 2 else price
    change_pct = round((price - prev) / prev * 100, 2) if prev else 0.0
    return {"ticker": ticker, "price": price, "change_pct": change_pct}


def safe_quote(ticker: str) -> dict:
    try:
        return get_quote(ticker)
    except Exception as exc:  # noqa: BLE001
        return {"ticker": ticker, "price": None, "change_pct": None, "error": type(exc).__name__}
