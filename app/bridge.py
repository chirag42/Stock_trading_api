"""
Bridge — the middleware layer between the backend API and the Research API.

The backend no longer imports the research code. Instead it calls the Research
API over HTTP (RESEARCH_API_URL). This module owns the ORCHESTRATION: which
research endpoints to call, and how to combine their results into the shapes the
backend routers need. The research service stays the decision-maker; this file
decides what to ask it.
"""
import json
import logging
import os

import httpx

from app.config import RESEARCH_API_URL

logger = logging.getLogger("bridge")

_client = httpx.Client(base_url=RESEARCH_API_URL, timeout=30.0)


class ResearchUnavailable(Exception):
    """Raised when the Research API cannot be reached or returns an error."""


def _get(path: str, **params):
    try:
        r = _client.get(path, params=params)
    except httpx.HTTPError as exc:
        raise ResearchUnavailable(f"Research API unreachable: {exc}") from exc
    if r.status_code == 404:
        raise ValueError(r.json().get("detail", "not found"))
    if r.status_code >= 400:
        raise ResearchUnavailable(f"Research API error {r.status_code}: {r.text}")
    return r.json()


def _post(path: str, payload: dict):
    try:
        r = _client.post(path, json=payload)
    except httpx.HTTPError as exc:
        raise ResearchUnavailable(f"Research API unreachable: {exc}") from exc
    if r.status_code == 404:
        raise ValueError(r.json().get("detail", "not found"))
    if r.status_code >= 400:
        raise ResearchUnavailable(f"Research API error {r.status_code}: {r.text}")
    return r.json()


# ── Quotes ────────────────────────────────────────────────────────
def get_quote(ticker: str) -> dict:
    """Current price + day change %. Raises ValueError if the ticker is invalid."""
    return _get(f"/quote/{ticker}")


def safe_quote(ticker: str) -> dict:
    try:
        return get_quote(ticker)
    except Exception as exc:  # noqa: BLE001
        return {"ticker": ticker, "price": None, "change_pct": None, "error": type(exc).__name__}


def current_price(ticker: str) -> float:
    return round(float(_get(f"/indicators/{ticker}")["close_price"]), 2)


# ── Summary / indicators ──────────────────────────────────────────
def get_summary(ticker: str) -> dict:
    """Fast key stats for the stock header (indicators, no LLM)."""
    m = _get(f"/indicators/{ticker}")
    return {
        "ticker": ticker,
        "price": round(float(m["close_price"]), 2),
        "rsi": round(float(m["rsi"]), 1),
        "rsi_signal": m.get("rsi_signal", ""),
        "macd": round(float(m["macd"]), 3),
        "macd_signal": m.get("macd_signal", ""),
    }


# ── Opportunities (unbought → BUY / WAIT, fast, no LLM) ────────────
def _opportunity_indicator(rsi, macd, signal):
    if rsi < 35 and macd > signal:
        return "BUY", "Oversold RSI with bullish MACD — potential entry."
    if rsi > 65:
        return "WAIT", "Overbought — not a good entry right now."
    return "WAIT", "No strong entry signal yet."


def classify_opportunity(ticker: str) -> dict:
    try:
        m = _get(f"/indicators/{ticker}")
        indicator, reason = _opportunity_indicator(m["rsi"], m["macd"], m["signal"])
        return {"ticker": ticker, "price": round(float(m["close_price"]), 2),
                "rsi": round(float(m["rsi"]), 1), "indicator": indicator, "reason": reason}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"opportunity failed for {ticker}: {exc}")
        return {"ticker": ticker, "indicator": "WAIT",
                "reason": "Data unavailable.", "error": type(exc).__name__}


# ── Chart / news / analysis ───────────────────────────────────────
def get_chart(ticker: str, period: str = "3mo") -> list:
    try:
        return _get(f"/chart/{ticker}", period=period).get("points", [])
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"chart failed for {ticker}: {exc}")
        return []


def get_news(ticker: str, count: int = 8) -> list:
    try:
        return _get(f"/news/{ticker}", count=count).get("articles", [])
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"news failed for {ticker}: {exc}")
        return []


def get_analysis(ticker: str) -> dict:
    """Full opportunity decision (BUY/SELL/HOLD + reasoning) — delegated to research."""
    d = _post("/decision", {"ticker": ticker})
    return {"ticker": ticker, "decision": d["decision"],
            "reasoning": d["reasoning"], "backend": d.get("backend", "research")}


# ── Holdings (owned → SELL / HOLD, position-aware) ────────────────
def holding_indicator(ticker: str):
    """Fast, no-LLM exit indicator for the holdings list: SELL or HOLD."""
    try:
        m = _get(f"/indicators/{ticker}")
        price = round(float(m["close_price"]), 2)
        if m["rsi"] > 65 and m["macd"] < m["signal"]:
            return price, "SELL", "Overbought with bearish MACD — consider taking profit."
        return price, "HOLD", "No exit signal — position looks fine."
    except Exception as exc:  # noqa: BLE001
        return None, "HOLD", f"Data unavailable ({type(exc).__name__})."


def holding_row(ticker: str) -> dict:
    """Price, today's change %, and SELL/HOLD indicator for a held stock."""
    q = safe_quote(ticker)
    try:
        m = _get(f"/indicators/{ticker}")
        if m["rsi"] > 65 and m["macd"] < m["signal"]:
            indicator, reason = "SELL", "Overbought with bearish MACD — consider taking profit."
        else:
            indicator, reason = "HOLD", "No exit signal — position looks fine."
    except Exception:  # noqa: BLE001
        indicator, reason = "HOLD", "Data unavailable."
    return {"price": q.get("price"), "change_pct": q.get("change_pct"),
            "indicator": indicator, "reason": reason}


def analyze_holding(ticker: str, shares: float, avg_price: float) -> dict:
    """Position-aware SELL/HOLD analysis — delegated to research with position context."""
    d = _post("/decision", {"ticker": ticker,
                            "position": {"shares": shares, "avg_price": avg_price}})
    return {"ticker": ticker, "decision": d["decision"], "reasoning": d["reasoning"],
            "pnl_pct": d.get("pnl_pct"), "current_price": d.get("current_price"),
            "backend": d.get("backend", "research")}


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
    """Tool body for get_stock_data — combines research atomic endpoints for any ticker."""
    ticker = (ticker or "").upper().strip()
    if not ticker:
        return {"error": "no ticker provided"}
    try:
        q = get_quote(ticker)  # validates
    except Exception:  # noqa: BLE001
        return {"error": f"'{ticker}' is not a valid ticker or has no market data."}
    out = {"ticker": ticker, "price": q["price"], "day_change_pct": q["change_pct"]}
    try:
        m = _get(f"/indicators/{ticker}")
        out.update({"rsi": round(float(m["rsi"]), 1), "rsi_signal": m.get("rsi_signal", ""),
                    "macd": round(float(m["macd"]), 3), "macd_signal": m.get("macd_signal", "")})
    except Exception:  # noqa: BLE001
        out["indicators"] = "unavailable"
    try:
        s = _get(f"/sentiment/{ticker}")
        out.update({"sentiment": s["overall"], "positive_articles": s["positive"],
                    "negative_articles": s["negative"]})
    except Exception:  # noqa: BLE001
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
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()

    return "I could not complete that request in time — please try rephrasing."
