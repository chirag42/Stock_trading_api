# Stock Trading API

A FastAPI service that exposes the Agentic AI Stock Trading System over HTTP for a
user-facing app. It imports the existing trading repo (does not duplicate it), adds
users/auth/portfolio, and serves market data, news, and LLM analysis.

## Structure

```
backend/
├── app/
│   ├── main.py            # FastAPI app + router wiring
│   ├── config.py          # LLM backend, repo path, 20-ticker universe
│   ├── database.py        # SQLite engine/session
│   ├── models.py          # users, holdings, watchlist tables
│   ├── schemas.py         # request/response models
│   ├── auth.py            # bcrypt hashing + JWT + get_current_user
│   ├── bridge.py          # the only file that imports the trading repo
│   └── routers/
│       ├── auth.py        # /auth/*
│       ├── market.py      # /opportunities, /stocks/*
│       ├── watchlist.py   # /watchlist/*
│       └── holdings.py    # /holdings/*  (Phase 3)
├── requirements.txt
└── .gitignore
```

## Endpoints

**Market (open)**
| Endpoint | Purpose |
|----------|---------|
| `GET /opportunities` | 20-ticker universe, each **BUY** or **WAIT** (unbought; fast, no LLM) |
| `GET /stocks/{ticker}/chart?period=3mo` | price history |
| `GET /stocks/{ticker}/news` | headlines |
| `GET /stocks/{ticker}/analysis` | full LLM decision + reasoning |

**Auth**
| Endpoint | Purpose |
|----------|---------|
| `POST /auth/signup` / `POST /auth/login` | returns JWT |
| `GET /auth/profile` | current user (protected) |

**Watchlist (protected):** `GET /watchlist`, `POST /watchlist/{ticker}`, `DELETE /watchlist/{ticker}`

**Holdings — Phase 3 (protected)**
| Endpoint | Purpose |
|----------|---------|
| `GET /holdings` | owned stocks with current price, P/L, and **SELL/HOLD** indicator |
| `POST /holdings/buy` `{ticker, shares}` | record a buy (weighted-average cost) |
| `POST /holdings/sell` `{ticker, shares}` | reduce/close a position |
| `GET /holdings/{ticker}/analysis` | position-aware LLM **SELL/HOLD** analysis (uses P/L, indicators, sentiment, fundamentals) |

The two-list design is intentional: **Opportunities** (unbought → BUY/WAIT) vs
**Holdings** (owned → SELL/HOLD). You can only sell what you own.

## Setup & run

Run in the **same venv** as your trading repo (so its deps are available), then:

```bash
cd backend
pip install -r requirements.txt

export TRADING_REPO_PATH="/Users/you/.../Stock_trading_Agentic_AI_Setup"
export LLM_BACKEND="claude"                 # or "ollama"
export ANTHROPIC_API_KEY="sk-ant-..."       # if claude
export BRAVE_API_KEY="..."                  # for news/sentiment
export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"

uvicorn app.main:app --reload --port 8000
```

Note the run target is now **`app.main:app`** (the app moved into the `app/` package).

Open the interactive docs: **http://localhost:8000/docs**
In `/docs`: sign up → copy the token → click **Authorize** → paste it → protected routes work.

## Notes / honest scope

- Auth is correct but **capstone-grade, not hardened** (no email verification, password
  reset, or refresh tokens).
- `buy`/`sell` are a **simulated** portfolio (records in SQLite at the current market
  price) — no real brokerage or money.
- `stocktrading.db` and secrets are gitignored — never commit them.
- **Next (Phase 4+):** React frontend — auth pages, the Opportunities and Holdings lists,
  and the stock-detail view (chart + news + LLM analysis).
