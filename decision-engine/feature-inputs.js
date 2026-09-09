"use strict";

// Shared inputs for building canonical technical features from a fetched quote.
//
// Extracted verbatim from 历史记录/生成决策快照.js so the EOD recorder and the
// decision.v1 serializer build features from exactly the same code. Two copies
// of this would be a second feature implementation by drift, which AGENTS.md
// rules out — `technical-features.js` must stay the one canonical producer, and
// its inputs have to be assembled identically by every caller.

const finite = (value) => (value == null || value === "" ? null : Number.isFinite(Number(value)) ? Number(value) : null);

function marketCore(market) {
  return market?.market_context || market?.market_engine || market || {};
}

function returnPct(closes, lookback) {
  const values = (closes || []).map(finite).filter((value) => value != null);
  const latest = values.at(-1);
  const base = values.at(-1 - lookback);
  return Number.isFinite(latest) && Number.isFinite(base) && base !== 0 ? (latest / base - 1) * 100 : null;
}

function relativeStrength(quote, market) {
  const core = marketCore(market);
  const equity = core.equity_trend || { spy: core.spy_trend, qqq: core.qqq_trend };
  return Object.fromEntries([20, 60, 120].flatMap((days) => {
    const stock = returnPct(quote.history?.closes, days);
    const against = (benchmark) => stock != null && finite(benchmark?.[`change_${days}d_pct`]) != null
      ? stock - finite(benchmark[`change_${days}d_pct`]) : null;
    return [[`stock_return_${days}d`, stock], [`stock_vs_spy_${days}d`, against(equity.spy)], [`stock_vs_qqq_${days}d`, against(equity.qqq)]];
  }));
}

function featureInputs(quote, market) {
  return {
    history: quote.history || {},
    currentPrice: finite(quote.price),
    relativeStrength: relativeStrength(quote, market),
    fibonacciStructure: quote.technical?.fibonacci_structure || {},
    shareBase: quote.metadata?.sharesOutstanding || null,
  };
}

function quoteFromItem(item) {
  return item?.analysis || item?.quote || item || {};
}

const api = { finite, marketCore, returnPct, relativeStrength, featureInputs, quoteFromItem };

// Attach to the global the way the engine modules do, so this works under a
// Cloudflare Worker bundle where `module` does not exist.
if (typeof globalThis !== "undefined") globalThis.DecisionFeatureInputs = api;
if (typeof module !== "undefined" && module.exports) module.exports = api;
