"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { buildTechnicalFeatures, AVAILABILITY_REASONS, HORIZON_CONFIG, _test } = require("../technical-features.js");

function dailyHistory(count = 420) {
  const timestamps = []; const opens = []; const highs = []; const lows = []; const closes = []; const volumes = [];
  const start = Date.UTC(2024, 0, 2);
  for (let index = 0; index < count; index += 1) {
    const date = new Date(start + index * 86400000);
    const close = 100 + index * 0.15 + Math.sin(index / 9) * 2;
    const previous = index ? closes[index - 1] : close - 0.4;
    timestamps.push(date.toISOString().slice(0, 10));
    opens.push(index === count - 1 ? previous * 1.02 : close - 0.35);
    closes.push(close);
    highs.push(close + 1.5);
    lows.push(close - 1.25);
    volumes.push(index === count - 1 ? 2_000_000 : 1_000_000 + (index % 7) * 10_000);
  }
  // An ATH outside the 52-week sample proves that ATH uses all supplied data.
  highs[0] = 250;
  return { timestamps, opens, highs, lows, closes, volumes };
}

function hourlyHistory(count = 240) {
  const timestamps = []; const opens = []; const highs = []; const lows = []; const closes = []; const volumes = [];
  let index = 0; let day = 0;
  while (index < count) {
    const date = new Date(Date.UTC(2026, 5, 1 + day)).toISOString().slice(0, 10);
    for (let hour = 9; hour <= 15 && index < count; hour += 1) {
      const close = 180 - index * 0.05 + Math.sin(index / 3);
      timestamps.push(`${date}T${String(hour).padStart(2, "0")}:30:00-0400`);
      opens.push(close + 0.2); closes.push(close); highs.push(close + 0.7); lows.push(close - 0.8); volumes.push(100_000 + index * 50);
      index += 1;
    }
    day += 1;
  }
  return { timestamps, opens, highs, lows, closes, volumes };
}

function nativeFourHourHistory(count = 240) {
  const timestamps = []; const opens = []; const highs = []; const lows = []; const closes = []; const volumes = [];
  let index = 0; let day = 0;
  while (index < count) {
    const date = new Date(Date.UTC(2026, 5, 1 + day)).toISOString().slice(0, 10);
    for (const hour of [9, 13]) {
      if (index >= count) break;
      const close = 180 - index * 0.11 + Math.sin(index / 4);
      timestamps.push(`${date}T${String(hour).padStart(2, "0")}:30:00-0400`);
      opens.push(close + 0.24); closes.push(close); highs.push(close + 0.82); lows.push(close - 0.91); volumes.push(250_000 + index * 100);
      index += 1;
    }
    day += 1;
  }
  return {
    timestamps, opens, highs, lows, closes, volumes,
    availability: "available", available: true,
    source: "yfinance", bar_method: "provider_native_v1",
    regular_hours_only: true, timezone: "America/New_York", lookback: "120d",
  };
}

function fibonacciFixture(price) {
  const level = (label, ratio, value) => ({ label, ratio, price: value, distance_from_current_pct: (value / price - 1) * 100, valid_for_display: true });
  return {
    short_term: { status: "available", horizon: "short_term", current_price: price, pivot_method: "confirmed daily pivots (2/2)", data_quality: "high", swing_low: 100, swing_low_date: "2026-01-02", swing_high: 130, swing_high_date: "2026-02-02", swing_direction: "up_swing", current_position_label: "between 38.2 and 50.0", retracement_levels: { "38.2": level("38.2%", 38.2, 118.54), "50.0": level("50.0%", 50, 115), "61.8": level("61.8%", 61.8, 111.46) }, extension_levels: { "127.2": level("127.2%", 127.2, 138.16), "161.8": level("161.8%", 161.8, 148.54) } },
    mid_term: { status: "unavailable" },
    long_term: { status: "unavailable" },
  };
}

const daily = dailyHistory();
const hourly = hourlyHistory();
const fourHour = nativeFourHourHistory();
const price = daily.closes.at(-1);
const features = buildTechnicalFeatures({
  history: { ...daily, intervals: { "1h": hourly, "4h": fourHour } },
  currentPrice: price,
  shareBase: 100_000_000,
  relativeStrength: { stock_return_20d: 4, stock_vs_spy_20d: 3, stock_vs_qqq_20d: 1, stock_return_60d: 8, stock_vs_spy_60d: 6, stock_vs_qqq_60d: 4, stock_return_120d: 10, stock_vs_spy_120d: 8, stock_vs_qqq_120d: 6 },
  fibonacciStructure: fibonacciFixture(price),
  calculatedAt: "2026-08-09T00:00:00.000Z",
});

// Horizon labels are investment windows, not candle intervals.
assert.equal(HORIZON_CONFIG.short.label, "1–30 days");
assert.equal(HORIZON_CONFIG.medium.label, "1–6 months");
assert.equal(HORIZON_CONFIG.long.label, "> 6 months");

// Interval/period identity and timeframe isolation.
const rsi4h = features.horizons.short.momentum.rsi.rsi_6_4h;
const rsi1h = features.horizons.short.momentum.rsi.rsi_6_1h;
assert.equal(rsi4h.interval, "4h");
assert.equal(rsi4h.period, 6);
assert.equal(rsi1h.interval, "1h");
assert.notEqual(rsi1h.last_bar_timestamp, daily.timestamps.at(-1));
assert.equal(features.horizons.medium.momentum.rsi.rsi_14_1d.period, 14);
assert.equal(features.horizons.long.momentum.rsi.rsi_21_1w.interval, "1w");
assert.equal(features.horizons.long.momentum.rsi.rsi_21_1w.period, 21);

// MA types stay explicit, and MACD keeps the correct primary interval per horizon.
const shortEma = features.horizons.short.trend.moving_averages.ema_9_4h;
const mediumEma = features.horizons.medium.trend.moving_averages.ema_20_1d;
const mediumSma = features.horizons.medium.trend.moving_averages.sma_100_1d;
const longSma = features.horizons.long.trend.moving_averages.sma_200_1d;
assert.equal(shortEma.indicator, "ema");
assert.equal(shortEma.interval, "4h");
assert.equal(mediumEma.indicator, "ema");
assert.equal(mediumSma.indicator, "sma");
assert.equal(mediumSma.period, 100);
assert.equal(longSma.indicator, "sma");
assert.equal(longSma.period, 200);
assert(Number.isFinite(shortEma.value));
assert(Number.isFinite(features.horizons.medium.momentum.macd.macd_1d.macd_line));
assert(Number.isFinite(features.horizons.medium.momentum.macd.macd_1d.histogram));
assert.equal(features.horizons.short.momentum.macd.macd_4h.interval, "4h");
assert.equal(features.horizons.medium.momentum.macd.macd_1d.interval, "1d");
assert.equal(features.horizons.long.momentum.macd.macd_1w.interval, "1w");
assert.equal(features.horizons.long.momentum.macd.macd_1w.period, "12/26/9");
assert.equal(features.horizons.short.momentum.kdj.kdj_9_4h.interval, "4h");
assert.equal(features.horizons.medium.momentum.kdj.kdj_9_1d.interval, "1d");

// Completeness contract: the Technical tab may choose how to group fields,
// but the canonical object must keep every raw/interpreted technical input.
// Values can be null when a provider has insufficient bars; field removal is
// a regression because it silently makes the UI and future decision engine
// less informative.
const canonicalPrimary = [
  ["short", "4h", 6],
  ["medium", "1d", 14],
  ["long", "1w", 21],
];
for (const [horizonKey, interval, rsiPeriod] of canonicalPrimary) {
  const horizon = features.horizons[horizonKey];
  const macd = horizon.momentum.macd[`macd_${interval}`];
  const adx = horizon.trend.adx[`adx_14_${interval}`];
  const atr = horizon.volatility.atr[`atr_14_${interval}`];
  const bollinger = horizon.volatility.bollinger[`bollinger_${interval}`];
  const obv = horizon.participation.obv[`obv_${interval}`];
  const rs = horizon.relative_strength;

  assert(Object.keys(horizon.trend.moving_averages).length > 0, `${horizonKey} MA/EMA/SMA family is missing`);
  assert(Object.hasOwn(horizon.momentum.rsi, `rsi_${rsiPeriod}_${interval}`), `${horizonKey} RSI is missing`);
  for (const key of ["macd_line", "signal_line", "histogram", "histogram_change_1", "histogram_change_3", "histogram_change_5", "above_or_below_zero", "improving_or_deteriorating", "crossover_state"]) assert(Object.hasOwn(macd, key), `${horizonKey} MACD field is missing: ${key}`);
  for (const key of ["adx", "plus_di", "minus_di", "trend_strength", "directional_bias", "slope"]) assert(Object.hasOwn(adx, key), `${horizonKey} ADX/DI field is missing: ${key}`);
  for (const key of ["value", "atr_pct", "atr_percentile_pct", "atr_percentile", "volatility_regime", "expansion_state"]) assert(Object.hasOwn(atr, key), `${horizonKey} ATR field is missing: ${key}`);
  for (const key of ["upper_band", "middle_band", "lower_band", "percent_b", "bandwidth_pct", "bandwidth_percentile", "squeeze_state", "price_position"]) assert(Object.hasOwn(bollinger, key), `${horizonKey} Bollinger field is missing: ${key}`);
  for (const key of ["raw_value", "trend", "divergence", "price_obv_confirmation", "slope"]) assert(Object.hasOwn(obv, key), `${horizonKey} OBV field is missing: ${key}`);
  for (const key of ["returns", "vs_spy", "vs_qqq", "primary", "state", "consistency"]) assert(Object.hasOwn(rs, key), `${horizonKey} Relative Strength field is missing: ${key}`);
}
for (const [horizonKey, interval] of [["short", "4h"], ["medium", "1d"]]) {
  const kdj = features.horizons[horizonKey].momentum.kdj[`kdj_9_${interval}`];
  for (const key of ["k", "d", "j", "crossover_state", "direction", "k_slope", "d_slope", "j_slope"]) assert(Object.hasOwn(kdj, key), `${horizonKey} KDJ field is missing: ${key}`);
}
for (const fibKey of ["short_term", "mid_term", "long_term"]) {
  const fib = features.fibonacci_structure[fibKey];
  for (const key of ["status", "swing_high", "swing_low", "retracement_levels", "extension_levels", "current_position_label"]) assert(Object.hasOwn(fib, key), `${fibKey} Fibonacci field is missing: ${key}`);
}
for (const key of ["high_52w", "low_52w", "position_52w_pct", "all_time_high", "all_time_history_coverage"]) assert(Object.hasOwn(features.price_position, key), `price-structure field is missing: ${key}`);
for (const key of ["current_volume", "moving_average_volume", "relative_volume", "obv", "trend", "accumulation_distribution"]) assert(Object.hasOwn(features.volume, key), `volume field is missing: ${key}`);

// ATR% is the normalized primary volatility value, with raw ATR retained internally.
const atr = features.horizons.medium.volatility.atr.atr_14_1d;
assert(Math.abs(atr.atr_pct - (atr.value / price * 100)) < 1e-10);
assert(Number.isFinite(atr.value));
assert.equal(atr.interval, "1d");
assert.equal(atr.period, 14);

// RVOL is calculated once from the canonical current-volume / average-volume formula.
for (const period of [5, 20, 60]) {
  const expected = daily.volumes.at(-1) / (daily.volumes.slice(-period).reduce((sum, value) => sum + value, 0) / period);
  assert(Math.abs(features.volume.relative_volume[`rvol_${period}d`] - expected) < 1e-12);
}
assert.equal(features.volume.relative_volume.state, "high");
assert.equal(Object.hasOwn(features, "legacy"), false);

// OBV is one canonical family; its 5D/20D/60D views are child context.
assert.equal(features.volume.obv.interval, "1d");
assert(Number.isFinite(features.volume.obv.raw_value));
assert.equal(features.volume.obv.trends.d5.trend, "rising");
assert.equal(features.volume.obv.trends.d20.trend, "rising");
assert.equal(features.volume.obv.trends.d60.trend, "rising");

// All relative-strength series remain available while each horizon selects one primary lookback.
assert.equal(features.horizons.short.relative_strength.primary_lookback_days, 20);
assert.equal(features.horizons.medium.relative_strength.primary_lookback_days, 60);
assert.equal(features.horizons.long.relative_strength.primary_lookback_days, 120);
assert.equal(features.horizons.short.relative_strength.returns.stock_20d, 4);
assert.equal(features.horizons.medium.relative_strength.vs_spy.d60, 6);
assert.equal(features.horizons.long.relative_strength.vs_qqq.d120, 6);

// Availability reasons are explicit, distinguish missing history from a valid
// zero/neutral result, and do not substitute another timeframe.
assert(AVAILABILITY_REASONS.includes("insufficient_history"));
assert(AVAILABILITY_REASONS.includes("dependency_unavailable"));
const shortHistory = buildTechnicalFeatures({
  history: { ...daily, intervals: { "1h": hourlyHistory(210), "4h": nativeFourHourHistory(30) } },
  currentPrice: price,
  calculatedAt: "2026-08-09T00:00:00.000Z",
});
const shortEma50 = shortHistory.horizons.short.trend.moving_averages.ema_50_4h;
const shortMacd = shortHistory.horizons.short.momentum.macd.macd_4h;
const shortAtr = shortHistory.horizons.short.volatility.atr.atr_14_4h;
const shortBollinger = shortHistory.horizons.short.volatility.bollinger.bollinger_4h;
assert.equal(shortHistory.source_intervals["4h"].bar_count, 30);
assert.equal(shortEma50.value, null);
assert.equal(shortEma50.unavailable_reason, "insufficient_history");
assert.equal(shortEma50.available_bars, 30);
assert.equal(shortEma50.required_bars, 50);
assert.equal(shortMacd.macd_line, null);
assert.equal(shortMacd.crossover_state, "unavailable");
assert.equal(shortMacd.unavailable_reason, "insufficient_history");
assert.equal(shortMacd.child_availability.histogram.unavailable_reason, "dependency_unavailable");
assert.equal(shortAtr.atr_percentile_pct, null);
assert.equal(shortAtr.atr_percentile.unavailable_reason, "insufficient_history");
assert.equal(shortAtr.atr_percentile.available_observations, 17);
assert.equal(shortAtr.atr_percentile.required_observations, 60);
assert.equal(shortAtr.volatility_regime, "unavailable");
assert.equal(shortAtr.volatility_regime_availability.unavailable_reason, "dependency_unavailable");
assert.equal(shortBollinger.bandwidth_percentile, null);
assert.equal(shortBollinger.bandwidth_percentile_availability.available_observations, 11);
assert.equal(shortBollinger.bandwidth_percentile_availability.required_observations, 60);
assert.equal(shortBollinger.squeeze_state, "unavailable");
assert.equal(shortHistory.horizons.short.trend.adx.adx_14_4h.slope.state, "unavailable");
assert.equal(shortHistory.horizons.short.trend.adx.adx_14_4h.slope.unavailable_reason, "insufficient_history");
assert.equal(shortHistory.horizons.short.trend.adx.adx_14_4h.slope.required_observations, 4);

// Production technical features require provider-native 4H input and never
// reconstruct it from 1H.
const legacyHourly = hourlyHistory(7);
const nativeMissing = buildTechnicalFeatures({
  history: { ...daily, intervals: { "1h": legacyHourly } },
  currentPrice: price,
  calculatedAt: "2026-08-09T00:00:00.000Z",
});
assert.equal(nativeMissing.source_intervals["4h"].availability, "unavailable");
assert.equal(nativeMissing.horizons.short.momentum.rsi.rsi_6_4h.value, null);
assert.equal(nativeMissing.horizons.short.momentum.macd.macd_4h.macd_line, null);

// A larger native-provider 4H history restores indicators only after enough
// real 4H bars exist; their raw calculations remain unchanged.
const longIntradayHistory = buildTechnicalFeatures({
  history: { ...daily, intervals: { "1h": hourlyHistory(840), "4h": nativeFourHourHistory(240) } },
  currentPrice: price,
  calculatedAt: "2026-08-09T00:00:00.000Z",
});
assert.equal(longIntradayHistory.source_intervals["4h"].bar_count, 240);
assert.equal(longIntradayHistory.source_intervals["4h"].source, "yfinance");
assert.equal(longIntradayHistory.source_intervals["4h"].bar_method, "provider_native_v1");
assert.equal(longIntradayHistory.source_intervals["4h"].regular_hours_only, true);
assert(Number.isFinite(longIntradayHistory.horizons.short.trend.moving_averages.ema_50_4h.value));
assert(Number.isFinite(longIntradayHistory.horizons.short.momentum.macd.macd_4h.macd_line));
assert.equal(longIntradayHistory.horizons.short.volatility.atr.atr_14_4h.atr_percentile.available, true);
assert.equal(longIntradayHistory.horizons.short.volatility.bollinger.bollinger_4h.bandwidth_percentile_availability.available, true);
assert.equal(longIntradayHistory.fibonacci_structure.short_term.source_timeframe, "4h", "Short Fibonacci uses native 4H when available");
assert.equal(longIntradayHistory.fibonacci_structure.short_term.fallback_used, false);
assert.equal(longIntradayHistory.fibonacci_structure.mid_term.source_timeframe, "1d", "Mid Fibonacci uses Daily");
assert.equal(longIntradayHistory.fibonacci_structure.long_term.source_timeframe, "1w", "Long Fibonacci uses completed Weekly bars");
assert.notEqual(longIntradayHistory.fibonacci_structure.short_term, longIntradayHistory.fibonacci_structure.mid_term, "Short and Mid Fibonacci must never share an object");
assert.notEqual(longIntradayHistory.fibonacci_structure.mid_term, longIntradayHistory.fibonacci_structure.long_term, "Mid and Long Fibonacci must never share an object");

// 52-week and ATH calculations retain the correct historical windows.
assert.equal(features.price_position.high_52w, Math.max(...daily.highs.slice(-252)));
assert.equal(features.price_position.low_52w, Math.min(...daily.lows.slice(-252)));
assert.equal(features.price_position.all_time_high, 250);
assert(features.price_position.distance_to_ath_pct < 0);
assert(features.price_position.position_52w_pct >= 0 && features.price_position.position_52w_pct <= 100);

// Gap and canonical market-breadth payloads are intentionally absent.
assert.equal(Object.hasOwn(features, "gaps"), false);
assert.equal(Object.hasOwn(features, "market_" + "breadth"), false);

// Fibonacci is always independently derived from the intended horizon source.
// A pre-V1 server display object cannot silently replace the Short 4H source.
assert.equal(features.fibonacci.short.source_timeframe, "4h");
assert.equal(features.fibonacci.short.fallback_used, false);
assert.equal(features.fibonacci.medium.source_timeframe, "1d");
assert.equal(features.fibonacci.long.source_timeframe, "1w");
assert.notEqual(features.fibonacci_structure.short_term, features.fibonacci_structure.mid_term);
assert.notEqual(features.fibonacci_structure.mid_term, features.fibonacci_structure.long_term);
assert.notEqual(features.fibonacci_structure.short_term.derivation_id, features.fibonacci_structure.mid_term.derivation_id);
assert(features.fibonacci.short.nearest_fib_level || features.fibonacci.short.status !== "available");

// The canonical layer also rebuilds the original display-only Fibonacci
// structure when an API payload does not carry a precomputed structure.
const generatedFibonacci = buildTechnicalFeatures({
  history: daily,
  currentPrice: price,
  calculatedAt: "2026-08-09T00:00:00.000Z",
});
assert(["available", "stale_swing", "no_valid_swing"].includes(generatedFibonacci.fibonacci_structure.short_term.status));
assert(["available", "stale_swing", "no_valid_swing"].includes(generatedFibonacci.fibonacci_structure.mid_term.status));
assert(["available", "stale_swing", "no_valid_swing"].includes(generatedFibonacci.fibonacci_structure.long_term.status));
assert.equal(generatedFibonacci.fibonacci_structure.short_term.current_price, price);
assert.equal(generatedFibonacci.fibonacci_structure.short_term.source_timeframe, "1d");
assert.equal(generatedFibonacci.fibonacci_structure.short_term.fallback_used, true);
assert.equal(generatedFibonacci.fibonacci_structure.long_term.source_timeframe, "1w");
assert.equal(Object.hasOwn(generatedFibonacci.fibonacci_structure.short_term, "selected_candidate_score"), false);

// Missing bars never become numeric zero, and insufficient history remains explicit.
const unavailable = buildTechnicalFeatures({ history: { closes: [1], highs: [1], lows: [1], volumes: [0], opens: [1], timestamps: ["2026-01-01"] }, currentPrice: 1 });
assert.equal(unavailable.horizons.medium.momentum.rsi.rsi_14_1d.value, null);
assert.equal(unavailable.volume.current_volume, 0);
assert.equal(unavailable.price_position.position_52w_pct, null);

// A missing native 4H source remains unavailable: it never falls back to 1H
// aggregation, daily bars, or any other interval.
const noIntraday = buildTechnicalFeatures({ history: daily, currentPrice: price });
assert.equal(noIntraday.source_intervals["1h"].availability, "unavailable");
assert.equal(noIntraday.horizons.short.momentum.rsi.rsi_6_4h.value, null);
assert.equal(noIntraday.horizons.short.momentum.macd.macd_4h.macd_line, null);
assert.equal(noIntraday.horizons.short.trend.moving_averages.ema_50_4h.value, null);
assert(Number.isFinite(noIntraday.horizons.medium.trend.moving_averages.ema_50_1d.value));

// The new dashboard renders canonical technical features directly and keeps
// recommendation logic outside this raw feature layer.
const mainSource = fs.readFileSync(path.join(__dirname, "..", "main.js"), "utf8");
const serverSource = fs.readFileSync(path.join(__dirname, "..", "server.py"), "utf8");
const canonicalSource = fs.readFileSync(path.join(__dirname, "..", "technical-features.js"), "utf8");
for (const forbidden of ["action_recommendation_score", "score_breakdown", "final_score", "baseline_score", "recommendation_confidence"]) {
  assert.equal(mainSource.includes(forbidden), false, `legacy decision field remains: ${forbidden}`);
}
assert(mainSource.includes("CanonicalTechnicalFeatures.buildTechnicalFeatures"));
assert(mainSource.includes("technicalFeatures"));
assert(mainSource.includes("renderFibonacciStructure"));
assert(mainSource.includes("VIX"));
assert(mainSource.includes("Fear & Greed"));
assert(mainSource.includes("US 10Y Yield"));
assert(mainSource.includes("Earnings"));
assert(serverSource.includes('TECHNICAL_INTRADAY_HISTORY_PERIOD = os.environ.get("TECHNICAL_INTRADAY_HISTORY_PERIOD", "120d")'));
assert(serverSource.includes("interval=interval, limit=6000"));
assert(serverSource.includes('interval="4h"'));
assert(serverSource.includes('TECHNICAL_FOUR_HOUR_BAR_METHOD = "provider_native_v1"'));
assert.equal(canonicalSource.includes("const fourHour = aggregateFourHourBarsLegacy(hourly);"), false);
assert(canonicalSource.includes('const fourHour = pickBars(history, "4h");'));
assert.equal(serverSource.includes('row.get("volume") or 0'), false);
assert(serverSource.includes('"marketContext": market_context'));
assert(serverSource.includes('"market_context": flatten_market_context_payload(market_context, market_context_meta)'));
assert.equal(serverSource.includes('"final_score"'), false);
assert.equal(canonicalSource.includes("toLegacyTechnicalStructure"), false);
assert.equal(canonicalSource.includes("aggregateFourHourBarsLegacy"), false);

console.log("technical-features.test.js: all assertions passed");
