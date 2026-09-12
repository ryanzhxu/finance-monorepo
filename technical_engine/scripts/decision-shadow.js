#!/usr/bin/env node
"use strict";

// Read-only audit helper for the V1 decision object. It uses the same cached
// market-data payload and canonical technical normalization as the dashboard;
// it never requests a refresh or writes recommendation history.
const path = require("node:path");
const { buildTechnicalFeatures } = require("../technical-features.js");

for (const file of [
  "config.js", "technical-engine.js", "exhaustion-engine.js", "market-engine.js", "etf-profile.js", "company-profile.js",
  "execution-engine.js", "confidence-engine.js", "stability-engine.js", "decision-engine.js",
]) require(path.join(__dirname, "..", "decision-engine", file));

const DEFAULT_TICKERS = ["META", "MSFT", "NVDA", "MU", "AMZN", "GOOGL"];
const profiles = require("../profile-definitions.js");

const finite = (value) => value == null || value === "" ? null : Number.isFinite(Number(value)) ? Number(value) : null;
const returnPct = (closes, lookback) => {
  const values = (closes || []).map(finite).filter((value) => value != null);
  const last = values.at(-1);
  const base = values.at(-1 - lookback);
  return Number.isFinite(last) && Number.isFinite(base) && base !== 0 ? (last / base - 1) * 100 : null;
};
const marketCore = (market) => market?.market_context || market?.market_engine || market || {};
function relativeStrength(quote, market) {
  const core = marketCore(market);
  const equity = core.equity_trend || { spy: core.spy_trend, qqq: core.qqq_trend };
  return Object.fromEntries([20, 60, 120].flatMap((days) => {
    const stock = returnPct(quote.history?.closes, days);
    const against = (benchmark) => stock != null && finite(benchmark?.[`change_${days}d_pct`]) != null ? stock - finite(benchmark[`change_${days}d_pct`]) : null;
    return [[`stock_return_${days}d`, stock], [`stock_vs_spy_${days}d`, against(equity.spy)], [`stock_vs_qqq_${days}d`, against(equity.qqq)]];
  }));
}

function summary(decision) {
  return Object.fromEntries(Object.entries(decision.horizons).map(([horizon, value]) => [horizon, {
    action: value.action, confidence: value.confidence,
    direction: value.states.direction.score, confirmation: value.states.confirmation.score,
    risk: value.states.risk.score, priceOpportunity: value.states.priceOpportunity.score, exhaustion: value.states.exhaustion.score,
    marketRegime: value.market.regime, candidateAction: value.debug.candidateAction, finalAction: value.debug.finalAction,
    priceState: value.debug.priceState, actionFamily: value.debug.actionFamily, landscapeQuality: value.debug.landscapeQuality,
    finalDecision: value.debug.finalDecision, stability: value.debug.stability, priceLandscape: value.priceLandscape,
    priceStateContract: strictPriceStateContract(value),
    supporting: value.reasons.supporting, limiting: value.reasons.limiting,
  }]));
}

function strictPriceStateContract(value) {
  const state = value.debug?.priceState;
  const action = value.action;
  const positive = ["strong_buy", "buy", "accumulate"].includes(action);
  const defensive = ["trim", "sell"].includes(action);
  if (state === "IN_OPPORTUNITY_ZONE") return { expected: "positive", valid: positive };
  if (["NEAR_OPPORTUNITY_ZONE", "NEUTRAL_ZONE", "NEAR_REDUCE_ZONE"].includes(state)) return { expected: "hold", valid: action === "hold" };
  if (["IN_REDUCE_ZONE", "BEYOND_REDUCE_ZONE"].includes(state)) return { expected: "reduce", valid: defensive };
  if (state === "BREAKDOWN_ZONE") return { expected: "defensive", valid: ["sell", "avoid"].includes(action) };
  return { expected: "avoid", valid: action === "avoid" };
}

async function main() {
  const base = process.env.DECISION_SHADOW_API || "http://127.0.0.1:4174";
  const tickers = process.argv.slice(2).length ? process.argv.slice(2).map((ticker) => ticker.toUpperCase()) : DEFAULT_TICKERS;
  const response = await fetch(`${base}/api/market-data?tickers=${encodeURIComponent(tickers.join(","))}&cache_only=1`);
  if (!response.ok) throw new Error(`Market-data API returned ${response.status}`);
  const payload = await response.json();
  const market = payload.marketContext || payload.market_context || {};
  const rows = Object.fromEntries((payload.items || []).map((item) => [item.ticker, item.analysis || item]));
  const output = {};
  for (const ticker of tickers) {
    const quote = rows[ticker] || {};
    const price = finite(quote.price);
    if (price == null || quote.history?.availability === "unavailable") {
      output[ticker] = { status: "unavailable", reason: quote.history?.unavailable_reason || quote.error || "No cached quote/history for shadow audit." };
      continue;
    }
    const technicalFeatures = buildTechnicalFeatures({
      history: quote.history || {}, currentPrice: price, relativeStrength: relativeStrength(quote, market),
      fibonacciStructure: quote.technical?.fibonacci_structure || {}, shareBase: quote.metadata?.sharesOutstanding || null,
    });
    output[ticker] = { status: "available", price, ...summary(globalThis.DecisionEngine.decide({ ticker, price, technicalFeatures, marketContext: market, classification: profiles.profileFor(ticker, quote.metadata || {}), metadata: quote.metadata || {}, language: "en" })) };
  }
  console.log(JSON.stringify({ generatedAt: new Date().toISOString(), cacheOnly: true, tickers: output }, null, 2));
}

main().catch((error) => { console.error(error.stack || error.message); process.exitCode = 1; });
