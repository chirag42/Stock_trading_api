"""
config.py — Backend (middleware) configuration. All overridable via env vars.

The backend no longer imports the research code. It calls the Research API over
HTTP; RESEARCH_API_URL points at that service.
"""
import os

# Base URL of the Research API (the decision engine). Start that service first:
#   uvicorn api_server:app --port 8001   (in the research repo)
RESEARCH_API_URL = os.getenv("RESEARCH_API_URL", "http://localhost:8001")

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
