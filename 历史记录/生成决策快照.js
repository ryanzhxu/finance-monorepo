#!/usr/bin/env node
"use strict";

// This process deliberately loads the same browser/Node V1 modules used by
// audits and the Dashboard.  It is a one-shot EOD serializer, not a second
// recommendation implementation.  Its process lifetime bounds all temporary
// canonical features and Confluence candidates.
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const { buildTechnicalFeatures } = require(path.join(ROOT, "technical-features.js"));
const { marketCore, returnPct, relativeStrength, featureInputs, quoteFromItem } = require(path.join(ROOT, "decision-engine", "feature-inputs.js"));
const profiles = require(path.join(ROOT, "profile-definitions.js"));

for (const file of [
  "config.js", "technical-engine.js", "exhaustion-engine.js", "market-engine.js", "etf-profile.js", "company-profile.js",
  "execution-engine.js", "confidence-engine.js", "stability-engine.js", "decision-engine.js",
]) require(path.join(ROOT, "decision-engine", file));

const engine = globalThis.DecisionEngine;
const HORIZONS = ["short", "mid", "long"];
const RAW_SERIES_KEYS = new Set([
  "timestamps", "opens", "highs", "lows", "closes", "volumes", "bars", "series", "macd_series", "signal_series", "histogram_series",
]);
const finite = (value) => value == null || value === "" ? null : Number.isFinite(Number(value)) ? Number(value) : null;
const round = (value, digits = 6) => Number.isFinite(Number(value)) ? Number(Number(value).toFixed(digits)) : null;
const rangeFields = (range) => ({ low: finite(range?.low), high: finite(range?.high) });

function latestDailyDate(quote) {
  const values = quote?.history?.timestamps || [];
  return values.length ? String(values.at(-1)).slice(0, 10) : null;
}

function availableQuote(quote, marketDate) {
  return Number.isFinite(finite(quote?.price))
    && quote?.quote_status !== "unavailable"
    && quote?.history?.availability !== "unavailable"
    && latestDailyDate(quote) === marketDate;
}

function featureFor(quote, market) {
  return buildTechnicalFeatures(featureInputs(quote, market));
}

function compact(value, depth = 0) {
  if (value == null || typeof value === "string" || typeof value === "boolean" || Number.isFinite(value)) return value;
  if (depth > 9) return undefined;
  if (Array.isArray(value)) {
    // Technical feature arrays are calculation series.  No raw OHLCV or long
    // indicator series belongs in the history database.
    if (value.length > 32) return undefined;
    return value.map((item) => compact(item, depth + 1)).filter((item) => item !== undefined);
  }
  if (typeof value !== "object") return undefined;
  const result = {};
  for (const [key, item] of Object.entries(value)) {
    if (RAW_SERIES_KEYS.has(key) || /_series$/i.test(key) || /(^|_)raw(_|$)/i.test(key)) continue;
    const next = compact(item, depth + 1);
    if (next !== undefined) result[key] = next;
  }
  return result;
}

function horizonFeature(features, horizon) {
  const technicalKey = engine.config.horizons[horizon]?.technicalKey;
  const set = features?.horizons?.[technicalKey] || {};
  const fibonacciKey = { short: "short_term", mid: "mid_term", long: "long_term" }[horizon];
  const fib = features?.fibonacci_structure?.[fibonacciKey] || set.fibonacci || {};
  return compact({
    schema_version: features?.schema_version,
    calculated_at: features?.calculated_at,
    horizon,
    availability: set.availability,
    primary_intervals: set.primary_intervals,
    supporting_intervals: set.supporting_intervals,
    source_intervals: features?.source_intervals,
    trend: set.trend,
    momentum: set.momentum,
    volatility: set.volatility,
    participation: set.participation,
    relative_strength: set.relative_strength,
    volume: features?.volume,
    price_position: features?.price_position,
    fibonacci: fib,
    missing_families: set.missing_families,
  });
}

function compactMarket(market, decision) {
  const core = marketCore(market);
  const equity = core.equity_trend || { spy: core.spy_trend, qqq: core.qqq_trend };
  const modifiers = decision?.market?.horizonModifiers || {};
  return compact({
    regime: decision?.market?.regime || core.regime || modifiers.regime,
    impact: modifiers.impact || modifiers.context || null,
    vix: core.vix || core.vix_context || null,
    equity_trend: { spy: equity.spy || null, qqq: equity.qqq || null },
    fear_greed: core.fear_greed || core.fearGreed || null,
    us_10y: core.us_10y || core.ten_year_yield || core.yield_10y || null,
    earnings: core.earnings || decision?.market?.earnings || null,
    market_modifiers: modifiers,
    material_change: decision?.debug?.materialChangeReasons || [],
  });
}

function profileContext(classification, horizonProfile) {
  const profile = horizonProfile || classification || {};
  const isETF = Boolean(classification?.isETF || profile.isETF);
  return {
    asset_type: isETF ? "ETF" : "stock",
    primary_classification: isETF ? null : (profile.primaryClassification || classification?.primaryClassification || null),
    lifecycle: isETF ? null : (profile.lifecycle || classification?.lifecycle || null),
    company_traits: isETF ? null : (profile.companyTraits || classification?.companyTraits || []),
    applied_profile_modifiers: isETF ? null : {
      applied: profile.appliedModifiers || [],
      effective: profile.effectiveModifiers || {},
      profile_confidence: profile.profileConfidence ?? classification?.profileConfidence ?? null,
      last_profile_review: profile.lastProfileReview || classification?.lastProfileReview || null,
    },
    leveraged: isETF ? Boolean(profile.leveraged ?? classification?.leveraged) : null,
    etf_direction: isETF ? (profile.direction || classification?.direction || null) : null,
    underlying: isETF ? (profile.underlying || classification?.underlying || null) : null,
    etf_modifiers: isETF ? {
      applied: profile.appliedModifiers || [],
      effective: profile.effectiveModifiers || {},
      underlying_ticker: profile.underlyingTicker || classification?.underlyingTicker || null,
    } : null,
  };
}

function unavailableRecord({ marketDate, recordedAtEt, ticker, classification, horizon }) {
  return {
    market_date: marketDate, recorded_at_et: recordedAtEt, ticker, horizon,
    data_status: "unavailable", action: null, confidence: null, price_state: "INVALID_LANDSCAPE", current_price: null,
    opportunity_low: null, opportunity_high: null, reduce_low: null, reduce_high: null, invalidation: null,
    landscape_quality: null, direction: null, confirmation: null, risk: null, exhaustion: null, market_regime: null,
    market_context: null, technical_features: null, supporting_reasons: [], limiting_reasons: [], material_change: [],
    ...profileContext(classification, classification),
  };
}

function recordFor({ marketDate, recordedAtEt, ticker, quote, classification, features, decision, horizon, market }) {
  const value = decision.horizons[horizon];
  const landscape = value.priceLandscape || {};
  const opportunity = rangeFields(landscape.opportunityRange);
  const reduce = rangeFields(landscape.reduceRange);
  return {
    market_date: marketDate,
    recorded_at_et: recordedAtEt,
    ticker,
    horizon,
    data_status: value.debug?.dataQuality?.missingCore?.length ? "partial" : "available",
    action: value.action,
    confidence: finite(value.confidence),
    price_state: value.debug?.priceState || null,
    current_price: finite(landscape.currentPrice ?? quote.price),
    opportunity_low: opportunity.low,
    opportunity_high: opportunity.high,
    reduce_low: reduce.low,
    reduce_high: reduce.high,
    invalidation: finite(landscape.invalidation),
    landscape_quality: finite(value.debug?.landscapeQuality?.score),
    direction: finite(value.states?.direction?.score),
    confirmation: finite(value.states?.confirmation?.score),
    risk: finite(value.states?.risk?.score),
    exhaustion: finite(value.states?.exhaustion?.score),
    market_regime: value.market?.regime || value.debug?.marketRegime || null,
    market_context: compactMarket(market, value),
    technical_features: horizonFeature(features, horizon),
    supporting_reasons: value.reasons?.supporting || [],
    limiting_reasons: value.reasons?.limiting || [],
    material_change: value.debug?.materialChangeReasons || [],
    ...profileContext(classification, value.profile),
  };
}

function buildRecords(input) {
  const marketDate = input.marketDate;
  const recordedAtEt = input.recordedAtEt;
  const payload = input.payload || {};
  const market = payload.marketContext || payload.market_context || {};
  const items = Array.isArray(payload.items) ? payload.items : Object.entries(payload.quotes || {}).map(([ticker, quote]) => ({ ticker, analysis: quote }));
  const byTicker = new Map(items.map((item) => [String(item.ticker || "").toUpperCase(), quoteFromItem(item)]));
  const records = [];
  for (const item of items) {
    const ticker = String(item.ticker || "").toUpperCase();
    if (!ticker) continue;
    const quote = quoteFromItem(item);
    const classification = profiles.profileFor(ticker, quote.metadata || quote);
    if (!availableQuote(quote, marketDate)) {
      HORIZONS.forEach((horizon) => records.push(unavailableRecord({ marketDate, recordedAtEt, ticker, classification, horizon })));
      continue;
    }
    const ownFeatures = featureFor(quote, market);
    let underlying = null;
    const underlyingTicker = classification?.underlyingTicker || null;
    if (classification?.isETF && underlyingTicker) {
      const underlyingQuote = underlyingTicker === ticker ? quote : byTicker.get(String(underlyingTicker).toUpperCase());
      if (availableQuote(underlyingQuote, marketDate)) {
        underlying = {
          features: underlyingTicker === ticker ? ownFeatures : featureFor(underlyingQuote, market),
          price: finite(underlyingQuote.price),
        };
      }
    }
    const decision = engine.decide({
      ticker, price: finite(quote.price), technicalFeatures: ownFeatures, marketContext: market,
      classification, metadata: quote.metadata || {}, language: "en",
      underlyingTechnicalFeatures: underlying?.features || null,
      underlyingPrice: underlying?.price ?? null,
    });
    HORIZONS.forEach((horizon) => records.push(recordFor({ marketDate, recordedAtEt, ticker, quote, classification, features: ownFeatures, decision, horizon, market })));
  }
  return records;
}

function main() {
  const [inputPath, outputPath] = process.argv.slice(2);
  if (!inputPath || !outputPath) throw new Error("Usage: 生成决策快照.js <input.json> <output.json>");
  const input = JSON.parse(fs.readFileSync(inputPath, "utf8"));
  const records = buildRecords(input);
  fs.writeFileSync(outputPath, JSON.stringify({ marketDate: input.marketDate, recordedAtEt: input.recordedAtEt, records }), "utf8");
}

try {
  main();
} catch (error) {
  console.error(`[EOD HISTORY] snapshot generation failed: ${error?.stack || error}`);
  process.exitCode = 1;
}
