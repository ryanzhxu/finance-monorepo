#!/usr/bin/env node
"use strict";

// The decision.v1 serializer must emit a payload Ryan's finance-monorepo can
// consume without knowing anything about this engine's internals. Deterministic
// synthetic bars only - never a provider, cache or network call.
//
// Fixture helpers are the same ones tests/eod-history-node.test.js uses, so
// both tests exercise the engine on identical inputs.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const ROOT = path.resolve(__dirname, "..");
const runner = path.join(ROOT, "decision-v1", "emit-decision-v1.js");

const HORIZONS = ["short", "mid", "long"];
const ACTIONS = new Set(["strong_buy", "buy", "accumulate", "hold", "trim", "sell", "avoid"]);
const INTENTS = new Set(["enter", "add", "hold", "reduce", "exit", "avoid"]);
const PRICE_STATES = new Set([
  "IN_OPPORTUNITY_ZONE", "NEAR_OPPORTUNITY_ZONE", "NEUTRAL_ZONE", "NEAR_REDUCE_ZONE",
  "IN_REDUCE_ZONE", "BEYOND_REDUCE_ZONE", "BREAKDOWN_ZONE", "INVALID_LANDSCAPE",
]);
// The legality table, from execution-engine.js actionFamilyForState.
const LEGAL = {
  IN_OPPORTUNITY_ZONE: ["strong_buy", "buy", "accumulate"],
  NEAR_OPPORTUNITY_ZONE: ["hold"],
  NEUTRAL_ZONE: ["hold"],
  NEAR_REDUCE_ZONE: ["hold"],
  IN_REDUCE_ZONE: ["trim", "sell"],
  BEYOND_REDUCE_ZONE: ["trim", "sell"],
  BREAKDOWN_ZONE: ["sell", "avoid"],
  INVALID_LANDSCAPE: ["hold", "avoid"],
};

function bars(count, start, increment, timestampStart = "2025-01-02") {
  const timestamps = [];
  const opens = [];
  const highs = [];
  const lows = [];
  const closes = [];
  const volumes = [];
  let value = start;
  let date = new Date(`${timestampStart}T16:00:00Z`);
  for (let index = 0; index < count; index += 1) {
    value += increment + Math.sin(index / 7) * 0.25;
    timestamps.push(date.toISOString().slice(0, 10));
    opens.push(value - 0.45); highs.push(value + 1.2); lows.push(value - 1.1); closes.push(value); volumes.push(1_000_000 + index * 5000);
    date.setUTCDate(date.getUTCDate() + 1);
  }
  return { timestamps, opens, highs, lows, closes, volumes, availability: "available", available: true, lookback: "2y" };
}

function intradayBars(count, start, increment, hoursPerBar) {
  const result = bars(count, start, increment);
  result.timestamps = result.timestamps.map((date, index) => `${date}T${String(9 + ((index * hoursPerBar) % 7)).padStart(2, "0")}:30:00-0400`);
  result.interval = hoursPerBar === 4 ? "4h" : "1h";
  result.source = "test";
  result.regular_hours_only = true;
  return result;
}

function quote(ticker, price = 180) {
  const end = new Date("2026-08-18T16:00:00Z");
  end.setUTCDate(end.getUTCDate() - 319);
  const daily = bars(320, price - 100, 0.32, end.toISOString().slice(0, 10));
  const oneHour = intradayBars(180, price - 20, 0.10, 1);
  const fourHour = intradayBars(150, price - 40, 0.18, 4);
  return {
    ticker, price: daily.closes.at(-1), quote_status: "available",
    history: { ...daily, intervals: { "1h": oneHour, "4h": fourHour }, daily_history_metadata: { lookback: "2y" } },
    metadata: { quoteType: ticker === "TQQQ" ? "ETF" : "EQUITY", sharesOutstanding: 1_000_000_000 },
    technical: { fibonacci_structure: {} },
  };
}

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "decision-v1-"));
try {
  const nvda = quote("NVDA", 180);
  const unavailable = { ticker: "NOPE", price: null, quote_status: "unavailable", history: { timestamps: [], closes: [], availability: "unavailable" }, metadata: { quoteType: "EQUITY" } };
  const input = {
    items: [{ ticker: "NVDA", analysis: nvda }, { ticker: "NOPE", analysis: unavailable }],
    marketContext: { market_context: { regime: "normal", equity_trend: { spy: { change_20d_pct: 1.5 }, qqq: { change_20d_pct: 2.1 } }, vix: { current: 18 } } },
  };
  const inputPath = path.join(temporary, "input.json");
  const outputPath = path.join(temporary, "output.json");
  fs.writeFileSync(inputPath, JSON.stringify(input));

  const run = spawnSync(process.execPath, [runner, inputPath, outputPath], { encoding: "utf8" });
  assert.equal(run.status, 0, run.stderr || run.stdout);
  const output = JSON.parse(fs.readFileSync(outputPath, "utf8"));

  const nvdaDecision = output.decisions.NVDA;
  assert.ok(nvdaDecision, "NVDA must produce a decision");
  assert.equal(nvdaDecision.contractVersion, "decision.v1");
  assert.equal(nvdaDecision.producer, "vincent-stock-decision-dashboard");
  assert.equal(nvdaDecision.ticker, "NVDA");
  assert.ok(Number.isFinite(nvdaDecision.currentPrice));

  // All three horizons, independently. Never averaged into an overall action.
  assert.deepEqual(Object.keys(nvdaDecision.horizons).sort(), [...HORIZONS].sort());
  assert.equal(nvdaDecision.action, undefined, "there is no overall action");

  for (const horizon of HORIZONS) {
    const value = nvdaDecision.horizons[horizon];
    assert.ok(ACTIONS.has(value.action), `${horizon} action: ${value.action}`);
    assert.ok(PRICE_STATES.has(value.priceState), `${horizon} priceState: ${value.priceState}`);
    assert.ok(value.executionIntent == null || INTENTS.has(value.executionIntent), `${horizon} intent`);

    // Confidence stays on the engine's own 0-100 scale.
    assert.ok(value.confidence >= 0 && value.confidence <= 100, `${horizon} confidence ${value.confidence}`);

    // The action must be legal for its price state.
    assert.ok(LEGAL[value.priceState].includes(value.action),
      `${horizon}: ${value.action} is not legal for ${value.priceState}`);

    // Zone separation, and no half-known bands.
    for (const key of ["opportunityRange", "reduceRange"]) {
      const band = value[key];
      if (band !== null) {
        assert.ok(Number.isFinite(band.low) && Number.isFinite(band.high), `${horizon} ${key} edges`);
        assert.ok(band.low < band.high, `${horizon} ${key} low < high`);
      }
    }
    if (value.opportunityRange && value.reduceRange) {
      assert.ok(value.opportunityRange.high < value.reduceRange.low,
        `${horizon}: opportunityRange.high must be below reduceRange.low`);
    }

    // An unusable landscape must not carry bands.
    if (value.priceState === "INVALID_LANDSCAPE") {
      assert.equal(value.opportunityRange, null, `${horizon} invalid landscape opportunityRange`);
      assert.equal(value.reduceRange, null, `${horizon} invalid landscape reduceRange`);
      assert.equal(value.invalidation, null, `${horizon} invalid landscape invalidation`);
    }
  }

  // A ticker with no usable data must not fail the whole request.
  assert.ok(output.decisions.NOPE || output.errors.NOPE, "NOPE must be reported one way or the other");
  if (output.decisions.NOPE) {
    for (const horizon of HORIZONS) {
      assert.equal(output.decisions.NOPE.horizons[horizon].priceState, "INVALID_LANDSCAPE");
    }
  }

  console.log("decision.v1 serializer: all assertions passed");
} finally {
  fs.rmSync(temporary, { recursive: true, force: true });
}
