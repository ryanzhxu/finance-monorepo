#!/usr/bin/env node
"use strict";

// Read-only, cache-only development audit. It intentionally retains only five
// scalar heap samples plus compact fingerprints; decision candidates and zone
// clusters are allowed to become garbage after each refresh iteration.
const path = require("node:path");
const { buildTechnicalFeatures } = require("../technical-features.js");
const profiles = require("../profile-definitions.js");

for (const file of [
  "config.js", "technical-engine.js", "exhaustion-engine.js", "market-engine.js", "etf-profile.js", "company-profile.js",
  "execution-engine.js", "confidence-engine.js", "stability-engine.js", "decision-engine.js",
]) require(path.join(__dirname, "..", "decision-engine", file));

const engine = globalThis.DecisionEngine;
const HORIZONS = ["short", "mid", "long"];
const finite = (value) => value == null || value === "" ? null : Number.isFinite(Number(value)) ? Number(value) : null;
const mb = (value) => Number((value / 1024 / 1024).toFixed(2));

function marketCore(market = {}) { return market.market_context || market.market_engine || market; }
function returnPct(closes, lookback) {
  const values = (closes || []).map(finite).filter(Number.isFinite);
  const latest = values.at(-1);
  const base = values.at(-1 - lookback);
  return Number.isFinite(latest) && Number.isFinite(base) && base !== 0 ? (latest / base - 1) * 100 : null;
}
function relativeStrength(quote, market) {
  const core = marketCore(market);
  const equity = core.equity_trend || { spy: core.spy_trend, qqq: core.qqq_trend };
  return Object.fromEntries([20, 60, 120].flatMap((days) => {
    const stock = returnPct(quote.history?.closes, days);
    const versus = (benchmark) => stock != null && finite(benchmark?.[`change_${days}d_pct`]) != null ? stock - finite(benchmark[`change_${days}d_pct`]) : null;
    return [[`stock_return_${days}d`, stock], [`stock_vs_spy_${days}d`, versus(equity.spy)], [`stock_vs_qqq_${days}d`, versus(equity.qqq)]];
  }));
}
function featuresFor(quote, market) {
  return buildTechnicalFeatures({
    history: quote.history || {}, currentPrice: finite(quote.price), relativeStrength: relativeStrength(quote, market),
    fibonacciStructure: quote.technical?.fibonacci_structure || {}, shareBase: quote.metadata?.sharesOutstanding || null,
  });
}
function fingerprint(value) {
  return JSON.stringify(HORIZONS.map((horizon) => {
    const decision = value.horizons[horizon];
    return { horizon, priceState: decision.debug.priceState, landscape: decision.priceLandscape };
  }));
}

async function main() {
  const base = process.env.REFRESH_MEMORY_AUDIT_API || "http://127.0.0.1:4174";
  const requestedRefreshes = Number(process.env.REFRESH_MEMORY_AUDIT_RUNS || 5);
  const refreshCount = Number.isInteger(requestedRefreshes) ? Math.min(20, Math.max(1, requestedRefreshes)) : 5;
  const watchlistResponse = await fetch(`${base}/api/watchlist`);
  if (!watchlistResponse.ok) throw new Error(`Watchlist API returned ${watchlistResponse.status}`);
  const watchlistPayload = await watchlistResponse.json();
  const tickers = (watchlistPayload.items || watchlistPayload.watchlist || []).map((item) => typeof item === "string" ? item : item.ticker).filter(Boolean).map((ticker) => String(ticker).toUpperCase());
  const response = await fetch(`${base}/api/market-data?tickers=${encodeURIComponent(tickers.join(","))}&cache_only=1`);
  if (!response.ok) throw new Error(`Market-data API returned ${response.status}`);
  const payload = await response.json();
  const market = payload.marketContext || payload.market_context || {};
  const quotes = Object.fromEntries((payload.items || []).map((item) => [item.ticker, item.analysis || item]));
  // Keep only raw cache payloads between refreshes. Canonical Technical input
  // is rebuilt once per ticker on every simulated dashboard refresh, then the
  // three horizons share that one current-normalization result.
  const prepared = Object.fromEntries(tickers.map((ticker) => {
    const quote = quotes[ticker] || {};
    const price = finite(quote.price);
    return [ticker, { quote, price, valid: Number.isFinite(price) && quote.history?.availability !== "unavailable" }];
  }));
  const valid = tickers.filter((ticker) => prepared[ticker]?.valid);
  const baseline = new Map();
  const mismatches = [];
  const samples = [];

  engine.stability.clear();
  for (let refresh = 1; refresh <= refreshCount; refresh += 1) {
    const featuresByTicker = Object.fromEntries(valid.map((ticker) => [ticker, featuresFor(prepared[ticker].quote, market)]));
    for (const ticker of valid) {
      const item = prepared[ticker];
      const classification = profiles.profileFor(ticker, item.quote.metadata || item.quote);
      const underlying = classification.isETF && classification.underlyingTicker ? prepared[classification.underlyingTicker] : null;
      const decision = engine.decide({
        ticker, price: item.price, technicalFeatures: featuresByTicker[ticker], marketContext: market,
        classification, metadata: item.quote.metadata || {}, language: "en",
        underlyingTechnicalFeatures: underlying?.valid ? featuresByTicker[classification.underlyingTicker] : null, underlyingPrice: underlying?.price ?? null,
      });
      const key = ticker;
      const current = fingerprint(decision);
      if (refresh === 1) baseline.set(key, current);
      else if (baseline.get(key) !== current) mismatches.push({ refresh, ticker });
      // `decision` deliberately goes out of scope here. Do not accumulate it.
    }
    if (typeof global.gc === "function") global.gc();
    const usage = process.memoryUsage();
    samples.push({ refresh, heapUsedMB: mb(usage.heapUsed), rssMB: mb(usage.rss), stabilityEntries: engine.stability._cache.size, profileReviewEntries: engine.profile._reviewCache.size });
  }
  const heapValues = samples.map((sample) => sample.heapUsedMB);
  const first = heapValues[0] || 0;
  const last = heapValues.at(-1) || 0;
  console.log(JSON.stringify({
    generatedAt: new Date().toISOString(), cacheOnly: true, refreshes: refreshCount, validTickerCount: valid.length,
    canonicalNormalization: "once_per_ticker_per_refresh", priorLandscapeReuse: false,
    landscapeFingerprintMismatchCount: mismatches.length, mismatches,
    memory: { samples, firstHeapUsedMB: first, lastHeapUsedMB: last, deltaHeapMB: Number((last - first).toFixed(2)), maxHeapUsedMB: Math.max(...heapValues) },
    boundedState: { stabilityCacheLimit: engine.config.stability.cacheLimit, stabilityEntries: engine.stability._cache.size, profileReviewCacheLimit: engine.config.profile.review.cacheLimit, profileReviewEntries: engine.profile._reviewCache.size },
  }, null, 2));
}

main().catch((error) => { console.error(error.stack || error.message); process.exitCode = 1; });
