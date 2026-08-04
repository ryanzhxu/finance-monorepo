# Deterministic regime v2 boundary

`screener_service.core.regime_v2` is a fixture-first calculation seam for sector leadership, breadth, Treasury-curve context, volatility, and risk-on/risk-off classification.

It accepts already-retrieved observations and never calls yfinance or another provider. The existing live `/screen/regime` route remains unchanged until the calculations have a reviewed source adapter and response-contract integration.

The calculation is deterministic and fail-soft:

- sector strength is `60%` one-month return plus `40%` three-month return;
- breadth is the percentage of sectors with positive combined strength;
- regime uses versioned VIX and index-return thresholds;
- missing history becomes an explicit `unknowns` entry and does not create a bullish or bearish classification;
- Treasury spread and freshness metadata are returned for explanation, not automatic trade blocking.
