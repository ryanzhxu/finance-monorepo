# Market-context data strategy

This is the no-new-spend MVP for the event library, shock context, sector rotation, and alerting work. It is a source decision, not permission to download a bulk dataset or add a provider to production.

## Decision

Use official or already-configured sources first. Keep all raw downloads and generated manifests private. Treat current-listing price data as experimental unless the manifest proves point-in-time coverage.

| Data need | MVP source | Use | Limitation / status |
| --- | --- | --- | --- |
| Issuer filings and company facts | [SEC EDGAR APIs](https://www.sec.gov/submit-filings/filer-support-resources/how-do-i-guides/understand-edgar-application-programming-interfaces-apis) | Filings, issuer events, XBRL facts, submission dates | Rate limits and missing tags; improves fundamentals but does not certify price-universe history |
| Macro releases and vintages | [FRED/ALFRED API](https://fred.stlouisfed.org/docs/api/fred/fred/overview.html) | Inflation, employment, credit, recession context, real-time-period checks | Free registration/key required; series revisions must be retained |
| Treasury curve | [U.S. Treasury daily rates](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_) | Yield curve, rate shock, real-yield context | Daily observations; methodology changes require source metadata |
| Business-cycle chronology | [NBER chronology](https://www.nber.org/research/business-cycle-dating) | Event boundary and recession labels | Not a real-time signal and not a price-impact dataset |
| Broad volatility | [Cboe VIX historical data](https://www.cboe.com/tradable_products/vix/vix_historical_data) | Volatility regime and shock-window context | Daily index history; custom option history is a separate licensed/product decision |
| Equity OHLCV | Existing configured market-data path | Benchmark-relative returns, drawdown, recovery, sector ETF strength | Current Yahoo/yfinance listing cache remains research-only and `point_in_time_certified=false` |
| Social/news event streams | None in MVP | Keep out until licensing, evidence identity, and historical replay are solved | No silent scraping or unbounded provider calls |
| Historical options chains | None in MVP | Keep out of decision logic | Requires a separate provider/licensing decision; use a contract and fixtures first |

## Promotion rules

A source may be used in production context only when its observation time, revision behavior, failure mode, retention rights, and freshness tag are recorded. A source may be used in research only when its limitations are explicitly carried in the manifest. No source is promoted because it is merely convenient or free.

## Paid-provider trigger

Evaluate a paid provider only when a fixture-backed experiment demonstrates that the missing data changes a ranking, risk flag, or alert decision in a way that the MVP cannot support. The evaluation must record coverage, point-in-time semantics, historical depth, rate limits, redistribution/retention terms, and expected monthly cost before any live bulk call.

## What this does not do

- It does not download market data.
- It does not call Cursor/OpenAI.
- It does not expose forecasts or alerts.
- It does not treat event context as a BUY/SELL signal.
