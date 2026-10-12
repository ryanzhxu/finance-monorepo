# finance-monorepo

Market opportunity monorepo with FastAPI analyst/screener service code, a Cloudflare Worker API, shared contracts/utilities, and a deployed React/Vite frontend in `web_ui/`.

## Services

- `analyst_service/` single-symbol analysis, entry/confluence, provider health, and ticker search
- `screener_service/` undervalued/opportunity/trending screens, watchlist/custom screens, regime, and screener health
- `cloudflare-api/` production Worker API and shared-watchlist endpoints
- `shared/` cross-service models, enums, freshness/config helpers
- `web_ui/` production frontend for Analyze, Screener, Health, and Watchlist views
- `backtesting/store.py` append-only logging helpers

`execution_engine/` and `portfolio_dashboard/` are still placeholders.

## Local Run

```bash
uv sync
uv run uvicorn analyst_service.api.main:app --port 8001
uv run uvicorn screener_service.api.main:app --port 8002
cd web_ui && npm install && npm run dev
```

Health endpoints:

```bash
curl -sS http://127.0.0.1:8001/health
curl -sS http://127.0.0.1:8002/screen/health
```

`web_ui` reads:

- `VITE_ANALYST_URL` with fallback `http://localhost:8001`
- `VITE_SCREENER_URL` with fallback `http://localhost:8002`

## Verification

Backend tests:

```bash
uv run pytest
```

Frontend build:

```bash
cd web_ui && npm run build
```

Frontend lint:

```bash
cd web_ui && npm run lint
```

At the time of the latest guidance refresh, the build passed and lint failed on `react-hooks/set-state-in-effect` in `web_ui/src/views/Analyze.tsx`.

## Experimental Stock Research

The local research CLI uses a tool-enabled LLM for candidate discovery, then validates its claims against returned source URLs and the deterministic analyst output. It is research-only: it does not place orders or write recommendations.

For direct OpenAI/Google calls, set `AI_RESEARCH_PROVIDER`, `AI_RESEARCH_API_KEY`, and `AI_RESEARCH_MODEL` in the repo-root `.env`.

For Cursor Cloud Agents as the primary provider, set:

```bash
AI_RESEARCH_PROVIDER=cursor
CURSOR_API_KEY=<Cursor Cloud Agents API key>
CURSOR_RESEARCH_DISCOVERY_MODEL=<Cursor Anthropic model ID>
CURSOR_RESEARCH_VERIFICATION_MODEL=<Cursor Anthropic model ID>
CURSOR_RESEARCH_REVIEW_MODEL=<Cursor Anthropic model ID>
```

List the model IDs available to your Cursor account before filling those values:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/list_cursor_research_models.py
```

Then run a one-candidate research check:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/run_stock_research.py \
  --question "Find one underfollowed US-listed company with a verifiable demand inflection, durable business leverage, and asymmetric upside if the thesis is right. Favor non-obvious names when evidence quality is comparable. Do not promise returns." \
  --universe "US-listed common stocks with market capitalization above USD 10 billion" \
  --market-context-json '{"theme":"AI infrastructure"}' \
  --max-candidates 1 > /private/tmp/stock-research.json
```

The final JSON contains ranked candidates plus decision support for each: thesis, evidence-linked catalysts, risks, entry conditions, reasons to avoid, deterministic entry assessment, confidence, evidence verification, and skeptical review. Provider diagnostics continue to appear in the terminal, while the redirected file remains valid JSON. Cursor source URLs are citations from its agent result; they are not native Cursor tool metadata, so they remain subject to the evidence and skeptic gates.

Advisor-facing async research examples use the Worker `POST /research/jobs` contract:

```json
{
  "question": "Review NVDA as an existing holding. Explain what would strengthen or weaken the thesis, what deserves immediate follow-up, and what the user should verify next. No trade instructions.",
  "mode": "downside_risk_scan",
  "universe": "US-listed common stocks",
  "max_candidates": 1,
  "risk_profile": "Existing holding review triggered by the portfolio advisor."
}
```

```json
{
  "question": "Risk-scan MU as an existing holding. Focus on thesis-break risk, demand deterioration, execution risk, and reasons the user should reduce conviction or investigate further. No trade instructions.",
  "mode": "downside_risk_scan",
  "universe": "US-listed common stocks",
  "max_candidates": 1,
  "risk_profile": "Downside review requested after a concentration or drawdown alert."
}
```

```json
{
  "question": "Find up to three US-listed alternatives to an existing AI infrastructure holding. Favor less-obvious names when evidence quality is comparable, explain why each may fit, and include reasons to avoid. No trade instructions.",
  "mode": "upside_discovery",
  "universe": "US-listed common stocks",
  "max_candidates": 3,
  "risk_profile": "Portfolio advisor requested alternatives to an existing concentrated theme."
}
```

Run the live prompt-contract smoke with the cheapest known model only. This is intentionally separate from production routing and never uses Sonnet or Opus:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/run_stock_research_prompt_smoke.py \
  --output /private/tmp/stock-research-prompt-smoke.json
```

The forecast baseline is deliberately separate from the LLM research path. Build a point-in-time `ForecastObservation` JSONL dataset, then write an auditable calibration report with:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/train_forecast_model.py \
  --observations /path/to/forecast-observations.jsonl \
  --provenance /path/to/forecast-price-provenance.json \
  --output /path/to/forecast-report.json
```

The report stays `unavailable` unless the walk-forward out-of-sample minimums, both Brier-score checks, the configured minimum Brier improvement over base rate, and a point-in-time-certified provenance all pass. The Cloudflare research job is disabled until a validated report is deliberately promoted through Worker configuration; no Research UI is exposed before that gate.

### Free Historical Price Research

Download a reproducible sample of current US common stocks into the local, git-ignored raw-price cache:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/download_free_price_history.py \
  --nasdaq-current-common-stocks \
  --sample-seed free-price-v2 \
  --max-symbols 250 \
  --manifest-output backtesting/cache/free_price/manifest-free-price-v2.json
```

Build a point-in-time research dataset only from that cached data. The builder does not call an LLM or Cursor:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/build_free_price_only_dataset.py \
  --manifest backtesting/cache/free_price/manifest-free-price-v2.json \
  --cache-dir backtesting/cache/free_price \
  --start 2010-01-01 --end 2024-12-31 \
  --snapshots-output /private/tmp/free-v2-snapshots.jsonl \
  --observations-output /private/tmp/free-v2-observations.jsonl \
  --provenance-output /private/tmp/free-v2-provenance.json
```

The Nasdaq source is a current-listings universe, not historical membership. These free data runs have survivorship bias and cannot be used to claim delisted-stock coverage or a 50-year production backtest.

For the full current-US-common-stock research universe, use the adaptive downloader. It freezes the Nasdaq universe before requesting Yahoo data, starts at six workers, adapts between three and twelve workers, writes a local batch manifest every 250 symbols, and can checkpoint each batch to private R2:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/download_free_price_history.py \
  --nasdaq-current-common-stocks \
  --all-symbols \
  --sample-seed full-us-common-v1 \
  --run-id full-us-common-v1 \
  --workers 6 --max-workers 12 --batch-size 250 \
  --r2-checkpoints
```

If interrupted, re-run the same command with `--resume`. It uses the frozen `universe.json` and retries only non-terminal symbols. Each R2 checkpoint stores selected raw CSV files, its batch manifest, and verified SHA-256 metadata. The downloader refuses an upload that would take the private bucket above 8 GB.

Build an in-progress or completed run from local cache only; this never calls Yahoo, Cursor, or another LLM provider:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/build_free_price_only_dataset.py \
  --manifest backtesting/cache/free_price/runs/full-us-common-v1/manifest.json \
  --cache-dir backtesting/cache/free_price \
  --start 2010-01-01 --end 2024-12-31 \
  --workers 4 \
  --snapshot-step-sessions 63 \
  --snapshots-output /private/tmp/full-us-common-snapshots.jsonl \
  --observations-output /private/tmp/full-us-common-observations.jsonl \
  --provenance-output /private/tmp/full-us-common-provenance.json
```

The executable label enters at the next trading-session open, exits at the 63rd session close, and measures downside from the period's intraday low. For 63-session labels, the full-universe command keeps one as-of date every 63 sessions so outcomes do not overlap within a symbol. The free Yahoo auto-adjusted source is explicitly not point-in-time-certified, so its numeric forecast remains unavailable even if calibration improves.

Write the fold and score-bucket diagnostic report with the same provenance gate:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/diagnose_forecast_calibration.py \
  --observations /private/tmp/full-us-common-observations.jsonl \
  --provenance /private/tmp/full-us-common-provenance.json \
  --output /private/tmp/full-us-common-calibration-diagnostics.json
```

## API Artifacts

Dump OpenAPI directly from the FastAPI apps:

```bash
uv run python tools/dump_openapi.py
```

Generate Postman collections and environments:

```bash
make postman
```

This writes:

- `openapi/analyst.json`
- `openapi/screener.json`
- `postman/analyst.postman_collection.json`
- `postman/screener.postman_collection.json`
- `postman/local.postman_environment.json`

`make postman` shells out to `npx -y openapi-to-postmanv2`, so it depends on npm/network access. Do not hand-edit `openapi/` or `postman/`.

If `POSTMAN_API_KEY` is set, you can sync the generated collections and environment:

```bash
make postman-push
```

Set `POSTMAN_WORKSPACE_ID` as well if you want a workspace other than `My Workspace`.

## Deployment

`cloudflare-api/wrangler.toml` is the deploy source of truth for `finance-api`; `web_ui/` deploys to the `finance-web-ui` Cloudflare Pages project, served at `https://stock.ryanxu.dev`. This repository no longer provisions or depends on Render resources.

### Private Research Artifact Storage

Free-price caches and generated evaluation artifacts stay local by default. The private R2 bucket `finance-research-data` is only for explicitly selected backups; it is not bound to the public Worker.

Create an R2 API token scoped to `finance-research-data` with `Object Read & Write`, then keep these values in the ignored root `.env` file:

```dotenv
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
```

Preview an upload without making any network write:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/sync_research_artifacts_to_r2.py \
  --source backtesting/cache/free_price \
  --key-prefix raw/yfinance/current-listings/free-price-v2
```

Add `--upload` only after reviewing the output. The tool stores a SHA-256 checksum with each object and never exposes the bucket through the Worker.
