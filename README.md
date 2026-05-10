# DK Investing

Personal stock + crypto sentiment & alert system.

## Phase 1 — Local foundation

Free data sources, SQLite storage, Streamlit dashboard.

### Quick start

```powershell
# from project root
uv sync
uv run python -m dk.jobs.poller          # one-shot data fetch
uv run streamlit run dk/ui/dashboard.py  # launch dashboard
```

### Optional API keys

Copy `config/secrets.env.example` to `config/secrets.env` and fill in:

- `NEWSAPI_KEY` — https://newsapi.org (free 100 req/day)
- `FINNHUB_KEY` — https://finnhub.io (free 60 req/min)

Without keys, the app falls back to free RSS + yfinance only.

### Watchlist

Edit `config/watchlist.yaml`. Tickers marked `verify: true` need user confirmation.

### Layout

```
dk/
  config.py          # paths, env loading, watchlist accessors
  store/db.py        # SQLite schema + upserts
  sources/           # one module per data source
  jobs/poller.py     # fans out to all sources
  ui/dashboard.py    # Streamlit UI
config/
  watchlist.yaml
  secrets.env        # gitignored
data/
  dk.db              # SQLite, gitignored
```

## Roadmap

- **Phase 1** ✅ Foundation: free APIs, SQLite, dashboard
- **Phase 2** Sentiment scoring (FinBERT or Claude API) + alerts (email/Discord)
- **Phase 3** Signal ranking: sentiment + price + earnings proximity + volume
- **Phase 4** Macro/IPO calendars, broker integrations (Schwab/Coinbase/Robinhood/Fidelity/Blofin)
- **Phase 5** 24/7 hosted, HTML frontend
