"""
bridge.py — the only file that talks to the existing trading system.
Adds the trading repo to sys.path, builds heavy singletons once, and exposes
small functions the routers call (market data, news, analysis, holdings analysis).
"""

import json
import logging
import os
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


def holding_row(ticker: str) -> dict:
    """Price, today's change %, and SELL/HOLD indicator for a held stock."""
    q = safe_quote(ticker)
    try:
        m = _data.get_latest_summary(ticker)
        if m["rsi"] > 65 and m["macd"] < m["signal"]:
            indicator, reason = "SELL", "Overbought with bearish MACD — consider taking profit."
        else:
            indicator, reason = "HOLD", "No exit signal — position looks fine."
    except Exception:
        indicator, reason = "HOLD", "Data unavailable."
    return {"price": q.get("price"), "change_pct": q.get("change_pct"),
            "indicator": indicator, "reason": reason}


def chat(message: str, history: list, holdings_ctx: list, watchlist: list) -> str:
    """Answer a user's free-form question grounded in THEIR portfolio data.
    Stateless: all context is passed in per call, so users never mix."""
    if holdings_ctx:
        hold_lines = "\n".join(
            f"- {h['ticker']}: {h['shares']} shares, bought at ${h['avg_price']}, "
            f"now ${h.get('price','?')} ({h.get('pnl_pct','?')}% P/L, {h.get('change_pct','?')}% today)"
            for h in holdings_ctx
        )
    else:
        hold_lines = "(the user owns no stocks yet)"

    wl = ", ".join(watchlist) if watchlist else "(empty)"

    convo = ""
    for turn in history[-10:]:  # cap history to control token size
        role = "User" if turn.get("role") == "user" else "Assistant"
        convo += f"{role}: {turn.get('content','')}\n"

    prompt = (
        "You are a helpful assistant inside a stock-trading simulation app.\n"
        "Use ONLY the portfolio data provided below. Do not invent prices or figures. "
        "If asked about something not in the data, say you don't have that information. "
        "Keep answers concise and practical. This is a simulation, not financial advice.\n\n"
        f"USER'S HOLDINGS:\n{hold_lines}\n\n"
        f"USER'S WATCHLIST: {wl}\n\n"
        f"{'CONVERSATION SO FAR:\n' + convo + '\n' if convo else ''}"
        f"User: {message}\n"
        "Assistant:"
    )
    return _agent.llm_client.query(prompt)


# ── Agentic chat: tool definitions + tool-use loop ────────────────
import anthropic as _anthropic_sdk

_anthropic_key = os.getenv("ANTHROPIC_API_KEY")
_anthropic_client = _anthropic_sdk.Anthropic(api_key=_anthropic_key) if _anthropic_key else None

CHAT_TOOLS = [
    {
        "name": "get_stock_data",
        "description": ("Get current price, day change, RSI, MACD, and news sentiment for "
                        "ANY stock ticker — including ones the user does NOT own. Use this for "
                        "questions about a stock's current state, recent movement, or forward "
                        "outlook, and to check whether a ticker is valid."),
        "input_schema": {"type": "object",
                         "properties": {"ticker": {"type": "string", "description": "Stock ticker symbol, e.g. AAPL"}},
                         "required": ["ticker"]},
    },
    {
        "name": "get_my_holdings",
        "description": ("Get the user's CURRENT stock holdings: shares owned and average cost per "
                        "stock. Use for questions about what the user currently owns."),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_my_transactions",
        "description": ("Get the user's buy/sell transaction HISTORY, optionally filtered by ticker. "
                        "Use for questions like 'when did I buy X', 'how many times did I buy X', or "
                        "'show my trade history'."),
        "input_schema": {"type": "object",
                         "properties": {"ticker": {"type": "string", "description": "Optional ticker to filter by"}}},
    },
    {
        "name": "get_my_watchlist",
        "description": "Get the tickers on the user's watchlist. Use for questions about what they are watching.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

CHAT_SYSTEM = (
    "You are a portfolio assistant inside a stock-trading SIMULATION app.\n"
    "- Use the tools to fetch real data. NEVER invent prices, numbers, dates, or holdings.\n"
    "- For a stock's current state or outlook, or to validate a ticker, call get_stock_data.\n"
    "- For 'when/how many times did I buy or sell', call get_my_transactions.\n"
    "- For what the user owns now, call get_my_holdings; for their watchlist, get_my_watchlist.\n"
    "- If a ticker is invalid, say so plainly.\n"
    "- Be concise. This is a simulation, not financial advice. Frame any forward-looking view as "
    "scenarios and uncertainty, never as a definite prediction.\n"
    "Format every answer for readability:\n"
    "- Lead with a one-sentence direct answer.\n"
    "- Use a Markdown table when presenting holdings, transactions, or multiple stocks.\n"
    "- Use short bullet points for lists of facts.\n"
    "- Bold the key number or decision.\n"
    "- Keep it concise — no long paragraphs."
    
)


def tool_stock_data(ticker: str) -> dict:
    """Tool body for get_stock_data — validates and fetches live context for any ticker."""
    ticker = (ticker or "").upper().strip()
    if not ticker:
        return {"error": "no ticker provided"}
    try:
        q = get_quote(ticker)  # raises if invalid
    except Exception:
        return {"error": f"'{ticker}' is not a valid ticker or has no market data."}
    out = {"ticker": ticker, "price": q["price"], "day_change_pct": q["change_pct"]}
    try:
        m = _data.get_latest_summary(ticker)
        out.update({"rsi": round(float(m["rsi"]), 1), "rsi_signal": m.get("rsi_signal", ""),
                    "macd": round(float(m["macd"]), 3), "macd_signal": m.get("macd_signal", "")})
    except Exception:
        out["indicators"] = "unavailable"
    try:
        s = _sentiment.get_aggregated_sentiment(ticker)
        out.update({"sentiment": s["overall"], "positive_articles": s["positive"],
                    "negative_articles": s["negative"]})
    except Exception:
        out["sentiment"] = "unavailable"
    return out


def run_agentic_chat(message: str, history: list, handlers: dict, max_iters: int = 5) -> str:
    """Runs the Claude tool-use loop. `handlers` maps tool name -> callable (user-scoped)."""
    if _anthropic_client is None:
        return "Chat requires the Claude backend — set ANTHROPIC_API_KEY on the server."

    messages = [{"role": t["role"], "content": t["content"]} for t in history[-10:]]
    messages.append({"role": "user", "content": message})

    for _ in range(max_iters):
        resp = _anthropic_client.messages.create(
            model="claude-sonnet-4-6", max_tokens=1024,
            system=CHAT_SYSTEM, tools=CHAT_TOOLS, messages=messages,
        )
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use":
                    fn = handlers.get(block.name)
                    try:
                        data = fn(**block.input) if fn else {"error": "unknown tool"}
                    except Exception as exc:  # noqa: BLE001
                        data = {"error": str(exc)}
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": json.dumps(data)})
            messages.append({"role": "user", "content": results})
            continue
        # Final answer
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()

    return "I could not complete that request in time — please try rephrasing."
