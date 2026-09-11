#!/usr/bin/env node
"use strict";

// Serializes the production Decision Engine's output as `decision.v1`, the
// data contract Ryan's finance-monorepo consumes over HTTP.
//
// This is a SERIALIZER, not a second recommendation implementation. It loads
// the same browser/Node V1 modules the Dashboard and the EOD recorder load,
// calls the same `engine.decide`, and only reshapes the result. No scoring,
// thresholds or price levels are computed here — per AGENTS.md, a final
// recommendation may use only Technical, Market and Profile data, and that
// decision has already been made by the time this file sees it.
//
// Shape difference worth naming: the engine nests the bands under
// `priceLandscape`; decision.v1 hoists them to the top of each horizon object
// so a consumer needs no knowledge of the engine's internals.

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const { buildTechnicalFeatures } = require(path.join(ROOT, "technical-features.js"));
const profiles = require(path.join(ROOT, "profile-definitions.js"));
const { finite, featureInputs, quoteFromItem } = require(path.join(ROOT, "decision-engine", "feature-inputs.js"));

for (const file of [
  "config.js", "technical-engine.js", "exhaustion-engine.js", "market-engine.js", "etf-profile.js", "company-profile.js",
  "execution-engine.js", "confidence-engine.js", "stability-engine.js", "decision-engine.js",
]) require(path.join(ROOT, "decision-engine", file));

const engine = globalThis.DecisionEngine;

const CONTRACT_VERSION = "decision.v1";
const PRODUCER = "vincent-stock-decision-dashboard";
const HORIZONS = ["short", "mid", "long"];

// A band is emitted only when both edges are real numbers. A half-known band is
// not a band, and decision.v1 requires every price field to be nullable rather
// than filled with a plausible-looking placeholder.
function band(range) {
  const low = finite(range?.low);
  const high = finite(range?.high);
  return low != null && high != null ? { low, high } : null;
}

function featureFor(quote, market) {
  return buildTechnicalFeatures(featureInputs(quote, market));
}

function horizonPayload(decision, horizon, quote) {
  const value = decision?.horizons?.[horizon];
  if (!value) {
    return {
      action: "avoid",
      confidence: 0,
      priceState: "INVALID_LANDSCAPE",
      executionIntent: "avoid",
      opportunityRange: null,
      reduceRange: null,
      invalidation: null,
      currentPrice: finite(quote?.price),
      reasons: ["Horizon unavailable"],
      dataQuality: null,
    };
  }

  const landscape = value.priceLandscape || {};
  const priceState = value.debug?.priceState || "INVALID_LANDSCAPE";
  const usable = priceState !== "INVALID_LANDSCAPE";

  return {
    action: value.action,
    // The engine's confidence is already 0-100, which is decision.v1's scale.
    // Do not rescale here; consumers on a 0.0-1.0 scale divide on their side.
    confidence: finite(value.confidence),
    priceState,
    executionIntent: value.executionIntent || null,
    // An unusable landscape must carry null bands, not stale ones.
    opportunityRange: usable ? band(landscape.opportunityRange) : null,
    reduceRange: usable ? band(landscape.reduceRange) : null,
    invalidation: usable ? finite(landscape.invalidation) : null,
    currentPrice: finite(landscape.currentPrice ?? quote?.price),
    reasons: (value.reasons?.supporting || []).slice(0, 5),
    dataQuality: finite(value.debug?.dataQuality?.score),
  };
}

function decisionFor({ ticker, quote, market }) {
  const classification = profiles.profileFor(ticker, quote?.metadata || quote || {});
  const features = featureFor(quote, market);
  const decision = engine.decide({
    ticker,
    price: finite(quote?.price),
    technicalFeatures: features,
    marketContext: market,
    classification,
    metadata: quote?.metadata || {},
    language: "en",
    underlyingTechnicalFeatures: null,
    underlyingPrice: null,
  });

  return {
    contractVersion: CONTRACT_VERSION,
    producer: PRODUCER,
    ticker,
    generatedAt: new Date().toISOString(),
    currentPrice: finite(quote?.price),
    horizons: Object.fromEntries(HORIZONS.map((horizon) => [horizon, horizonPayload(decision, horizon, quote)])),
  };
}

function build(input) {
  const market = input.marketContext || input.market_context || {};
  const items = Array.isArray(input.items)
    ? input.items
    : Object.entries(input.quotes || {}).map(([ticker, quote]) => ({ ticker, analysis: quote }));

  const decisions = {};
  const errors = {};
  for (const item of items) {
    const ticker = String(item.ticker || "").toUpperCase();
    if (!ticker) continue;
    try {
      decisions[ticker] = decisionFor({ ticker, quote: quoteFromItem(item), market });
    } catch (error) {
      // One bad ticker must not fail the whole request. The caller sees which
      // failed and why, rather than an opaque 500.
      errors[ticker] = String(error?.message || error).slice(0, 300);
    }
  }
  return { decisions, errors };
}

function main() {
  const [inputPath, outputPath] = process.argv.slice(2);
  if (!inputPath || !outputPath) throw new Error("Usage: emit-decision-v1.js <input.json> <output.json>");
  const input = JSON.parse(fs.readFileSync(inputPath, "utf8"));
  fs.writeFileSync(outputPath, JSON.stringify(build(input)), "utf8");
}

try {
  main();
} catch (error) {
  console.error(`[decision.v1] serialization failed: ${error?.stack || error}`);
  process.exitCode = 1;
}
