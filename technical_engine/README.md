# Stock Dashboard Render Deployment

This dashboard uses `server.py` as the single backend. The shared watchlist is stored in a SQLite database on the server, while browser `localStorage` is only used as a fast cache.

## Local Development

```bash
cd "/Users/vincentwang/Documents/Stock Dashboard Project"
python3 server.py
```

Open:

```text
http://localhost:4173
```

Local watchlist database and market-data cache:

```text
data/watchlist.db
data/cache/
```

## Render Deployment

1. Push code to GitHub.
2. In Render, create a new Web Service.
3. Connect the GitHub repo.
4. Runtime: Python.
5. Build Command:

```bash
pip install -r requirements.txt
```

6. Start Command:

```bash
gunicorn --timeout 120 --workers 1 server:app
```

7. Environment Variables:

```text
WATCHLIST_DB_PATH=/var/data/watchlist.db
MARKET_CACHE_DIR=/var/data/cache
```

8. To persist the shared watchlist and market-data cache across redeploys/restarts, add a Render Disk:

```text
Mount Path: /var/data
```

If you do not attach a persistent disk, the default SQLite database and market-data cache can still work, but they may be lost after redeploys or restarts.

## Market Data API

```text
GET /api/market-data?tickers=NVDA,MSFT
GET /api/market-data?tickers=NVDA,MSFT&force=true
GET /api/debug/quote/NVDA
```

`/api/market-data` is cache-first. The `_refresh` query string is only used to bypass browser cache; it does not force a live quote refresh. Use `force=true` only for a manual refresh.

## Shared Watchlist API

```text
GET    /api/watchlist
POST   /api/watchlist
DELETE /api/watchlist?ticker=MSFT&market_type=US
DELETE /api/watchlist/MSFT?market_type=US
```

The API does not require login, authorization headers, admin tokens, or `added_by`.
