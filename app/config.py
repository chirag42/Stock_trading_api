"""
config.py — Backend configuration (all overridable via environment variables).
"""

import os

# Which LLM backend the analysis endpoint uses: "claude" or "ollama".
LLM_BACKEND = os.getenv("LLM_BACKEND", "claude")

# Absolute path to your existing trading system repo (the one with agents/,
# services/, pipeline.py). The backend imports that code rather than duplicating it.
# Set this to wherever your repo lives, e.g.:
#   export TRADING_REPO_PATH="/Users/you/.../Stock_trading_Agentic_AI_Setup"
TRADING_REPO_PATH = os.getenv("TRADING_REPO_PATH", "")

# Fixed universe of 20 well-covered tickers for the opportunities list.
TICKERS = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "NFLX", "AMD", "INTC",
    "JPM", "V", "WMT", "DIS", "KO", "XOM", "CVX", "PFE", "NKE", "CSCO",
]

# CORS origins allowed to call this API (React dev servers).
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:5173",
).split(",")
