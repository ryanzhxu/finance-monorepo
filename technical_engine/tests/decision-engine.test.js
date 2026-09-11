const assert = require("node:assert/strict");
const path = require("node:path");

for (const file of [
  "config.js", "technical-engine.js", "exhaustion-engine.js", "market-engine.js", "etf-profile.js", "company-profile.js",
  "execution-engine.js", "confidence-engine.js", "stability-engine.js", "decision-engine.js",
]) require(path.join(__dirname, "..", "decision-engine", file));

const engine = globalThis.DecisionEngine;
const profiles = require("../profile-definitions.js");
const watchlist = require("../watchlist.shared.json").watchlist;
const unavailable = { availability: "unavailable" };
const clone = (value) => JSON.parse(JSON.stringify(value));

function ma(value, period, interval, slope = "rising") {
  return { availability: "available", indicator: "ema", period, interval, value, price_state: "above", slope: { state: slope } };
}

function macd(mode = "bull") {
  if (mode === "neutral") {
    return { availability: "available", macd_line: 0, signal_line: 0, histogram: 0, histogram_change_1: 0, histogram_change_3: 0, histogram_change_5: 0, above_or_below_zero: "at_zero", crossover_state: "none", improving_or_deteriorating: "stable", state: "neutral" };
  }
  const bull = mode === "bull" || mode === "recover";
  const recovering = mode === "recover";
  return {
    availability: "available", macd_line: bull ? 1.1 : -1.1, signal_line: bull ? 0.35 : -0.35,
    histogram: bull ? 0.75 : -0.75, histogram_change_1: recovering ? 0.20 : bull ? 0.12 : -0.12,
    histogram_change_3: recovering ? 0.34 : bull ? 0.18 : -0.18, histogram_change_5: recovering ? 0.42 : bull ? 0.22 : -0.22,
    above_or_below_zero: bull ? "above_zero" : "below_zero", crossover_state: recovering ? "bullish_cross" : bull ? "bullish_cross" : "bearish_cross",
    improving_or_deteriorating: recovering || bull ? "improving" : "deteriorating", state: recovering ? "recovering_bearish" : bull ? "accelerating_bullish" : "accelerating_bearish",
  };
}

function horizon(mode = "bull", options = {}) {
  const bull = mode === "bull" || mode === "recover";
  const neutral = mode === "neutral";
  const price = 100;
  const maValues = neutral ? [100.1, 100, 99.9] : bull ? [99, 97.8, 96.5] : [101, 102.2, 103.5];
  const slope = neutral ? "flat" : bull ? "rising" : "falling";
  const rsiValue = options.rsi ?? (neutral ? 50 : bull ? (mode === "recover" ? 54 : 63) : 37);
  const kdjValue = options.kdj ?? (neutral ? 50 : bull ? 66 : 34);
  const percentB = options.percentB ?? (neutral ? 0.5 : bull ? 0.55 : 0.42);
  const trend = neutral ? "stable" : bull ? "rising" : "falling";
  const divergence = options.divergence ?? "none";
  const participationTrend = options.participationTrend ?? trend;
  const adverse = options.adverse === true;
  const primaryInterval = options.primaryInterval || "1d";
  const earlyInterval = options.earlyInterval || "4h";
  const primaryMacd = options.macd || macd(mode);
  const earlyMacd = options.earlyMacd || macd(mode);
  return {
    trend: {
      moving_averages: {
        [`ema_20_${primaryInterval}`]: ma(maValues[0], 20, primaryInterval, slope),
        [`ema_50_${primaryInterval}`]: ma(maValues[1], 50, primaryInterval, slope),
        [`sma_100_${primaryInterval}`]: ma(maValues[2], 100, primaryInterval, slope),
        [`ema_20_${earlyInterval}`]: ma(maValues[0], 20, earlyInterval, slope),
        [`ema_50_${earlyInterval}`]: ma(maValues[1], 50, earlyInterval, slope),
      },
      ma_structure: { alignment: neutral ? "mixed" : bull ? (mode === "recover" ? "recovering" : "bullish") : "bearish" },
      adx: { [`adx_14_${primaryInterval}`]: neutral ? { availability: "available", adx: 13, plus_di: 20, minus_di: 20, slope: { state: "flat" } } : { availability: "available", adx: bull ? 37 : 41, plus_di: bull ? 39 : 9, minus_di: bull ? 10 : 40, slope: { state: slope } } },
    },
    momentum: {
      rsi: { [`rsi_${options.rsiPeriod || 14}_${primaryInterval}`]: { availability: "available", value: rsiValue, slope: { state: slope }, divergence: adverse ? (bull ? "bearish_divergence" : "bullish_divergence") : "none" }, [`rsi_6_4h`]: { availability: "available", value: rsiValue, slope: { state: slope }, divergence: "none" }, [`rsi_14_4h`]: { availability: "available", value: rsiValue, slope: { state: slope }, divergence: "none" }, [`rsi_21_1w`]: { availability: "available", value: rsiValue, slope: { state: slope }, divergence: "none" } },
      macd: { [`macd_${primaryInterval}`]: primaryMacd, [`macd_${earlyInterval}`]: earlyMacd, macd_4h: primaryMacd, macd_1h: earlyMacd, macd_1d: earlyMacd, macd_1w: primaryMacd },
      kdj: { [`kdj_9_${primaryInterval}`]: { availability: "available", k: kdjValue - 2, d: kdjValue - 4, j: kdjValue, state: trend, crossover_state: bull ? "bullish_cross" : "bearish_cross", slope: { state: slope } }, kdj_9_4h: { availability: "available", k: kdjValue - 2, d: kdjValue - 4, j: kdjValue, state: trend } },
    },
    volatility: {
      atr: { [`atr_14_${primaryInterval}`]: { availability: "available", value: options.atr ?? 1, atr_pct: options.atrPct ?? 1.1, atr_percentile_pct: options.atrPercentile ?? 42, volatility_regime: options.atrPct > 7 ? "high" : "normal", expansion_state: options.atrPct > 7 ? "expanding" : "stable", slope: { state: options.atrPct > 7 ? "rising" : "flat" } } },
      bollinger: { [`bollinger_${primaryInterval}`]: { availability: "available", lower_band: 98, middle_band: 100, upper_band: 102, percent_b: percentB, width: 4, width_percentile_pct: 45, squeeze_state: "normal" } },
    },
    participation: { obv: { [`obv_${primaryInterval}`]: { availability: "available", trend: participationTrend, divergence, price_obv_confirmation: participationTrend === "rising" ? "confirming_uptrend" : participationTrend === "falling" ? "confirming_downtrend" : "mixed" } } },
    relative_strength: {
      availability: "available", primary: { stock_return: options.stockReturn ?? (bull ? 12 : neutral ? 0 : -12), vs_spy: options.vsSpy ?? (bull ? 9 : neutral ? 0 : -9), vs_qqq: options.vsQqq ?? (bull ? 8 : neutral ? 0 : -8) },
      consistency: { state: options.rsConsistency ?? (bull ? "improving" : neutral ? "stable" : "deteriorating") },
    },
  };
}

function featureSet({ short = "bull", mid = "bull", long = "bull", options = {} } = {}) {
  const shortSet = horizon(short, { ...options.short, primaryInterval: "4h", earlyInterval: "1h", rsiPeriod: 6 });
  const mediumSet = horizon(mid, { ...options.mid, primaryInterval: "1d", earlyInterval: "4h", rsiPeriod: 14 });
  const longSet = horizon(long, { ...options.long, primaryInterval: "1w", earlyInterval: "1d", rsiPeriod: 21 });
  // The canonical long MA family is intentionally Daily while MACD/ADX/RSI are Weekly.
  longSet.trend.moving_averages = { ...horizon(long, { ...options.long, primaryInterval: "1d", earlyInterval: "1d", rsiPeriod: 21 }).trend.moving_averages };
  return {
    availability: "available", horizons: { short: shortSet, medium: mediumSet, long: longSet },
    volume: { availability: "available", current_volume: 1_500_000, average_volume: 1_000_000, relative_volume: { displayed_rvol: options.rvol ?? 1.45, rvol_20d: options.rvol ?? 1.45 }, trend: { volume_trend: "expanding", price_volume_confirmation: "bullish_confirmation" } },
    price_position: { availability: "available", high_52w: 120, low_52w: 80, position_52w_pct: 50, state: "mid_range" },
    fibonacci_structure: {
      short_term: { status: "available", swing_low: 97, swing_high: 112, retracement_levels: { r382: { price: 99, label: "38.2%" }, r618: { price: 98.5, label: "61.8%" } }, extension_levels: { e127: { price: 116, label: "127.2%" } } },
      mid_term: { status: "available", swing_low: 94, swing_high: 120, retracement_levels: { r382: { price: 99, label: "38.2%" }, r618: { price: 97.5, label: "61.8%" } }, extension_levels: { e127: { price: 126, label: "127.2%" } } },
      long_term: { status: "available", swing_low: 82, swing_high: 125, retracement_levels: { r382: { price: 99, label: "38.2%" }, r618: { price: 96, label: "61.8%" } }, extension_levels: { e127: { price: 136, label: "127.2%" } } },
    },
  };
}

function market({ regime = "normal", fearGreed = 50, vix = 18 } = {}) {
  const falling = regime === "risk_off" || regime === "shock";
  const rising = regime === "risk_on";
  return { market_context: {
    vix: { value: regime === "shock" ? Math.max(40, vix) : regime === "risk_off" ? Math.max(30, vix) : vix, change_5d: regime === "shock" ? 12 : 0, change_20d: regime === "shock" ? 18 : 0, trend: falling ? "rising" : "neutral" },
    equity_trend: { spy: { trend: falling ? "falling" : rising ? "rising" : "neutral", change_5d_pct: falling ? -4 : rising ? 3 : 0, change_20d_pct: falling ? -8 : rising ? 5 : 0, change_60d_pct: falling ? -12 : rising ? 8 : 0, change_120d_pct: falling ? -15 : rising ? 12 : 0 }, qqq: { trend: falling ? "falling" : rising ? "rising" : "neutral", change_5d_pct: falling ? -5 : rising ? 4 : 0, change_20d_pct: falling ? -9 : rising ? 6 : 0, change_60d_pct: falling ? -13 : rising ? 10 : 0, change_120d_pct: falling ? -16 : rising ? 14 : 0 } },
    fear_greed: { value: fearGreed, label: fearGreed >= 80 ? "Extreme Greed" : fearGreed <= 20 ? "Extreme Fear" : "Neutral" }, ten_year_yield: { value: 4.2, change_5d_bps: 0, change_20d_bps: 0, trend: "neutral" },
  } };
}

function decide(features, marketInput = market(), ticker = "TEST", classification = { tags: ["MegaCap"] }) {
  return engine.decide({ ticker, price: 100, technicalFeatures: features, marketContext: marketInput, classification, metadata: {}, language: "en" });
}

function action(decision, horizon = "short") { return decision.horizons[horizon].action; }

// 1. Strong bullish + confirmation + attractive price => Buy / Strong Buy candidate.
engine.stability.clear();
let result = decide(featureSet(), market({ regime: "risk_on" }), "BULL");
assert(!["trim", "sell", "avoid"].includes(action(result)), "strong bullish input must not become defensive before its price state allows it");

// 2. Extreme extension plus deterioration may only soften an opportunity-zone
// action to Accumulate; it cannot cross the Price State family into Trim/Sell.
engine.stability.clear();
const tiringMacd = { ...macd("bull"), histogram: 0.12, histogram_change_1: -0.32, histogram_change_3: -0.42, histogram_change_5: -0.50, crossover_state: "bearish_cross", improving_or_deteriorating: "deteriorating", state: "decelerating_bullish" };
const extendedFeatures = featureSet({ options: { short: { rsi: 88, kdj: 112, percentB: 1.42, adverse: true, participationTrend: "falling", divergence: "bearish_divergence", rvol: 3.6, macd: tiringMacd, earlyMacd: tiringMacd } } });
extendedFeatures.volume.trend = { volume_trend: "expanding", price_volume_confirmation: "bearish_confirmation" };
result = decide(extendedFeatures, market(), "EXT");
assert(!["strong_buy", "buy", "trim", "sell"].includes(action(result)), "bullish exhaustion cannot manufacture a chase Buy or contradictory defensive action");

// 3. Bearish direction plus repaired downside exhaustion can Accumulate.
engine.stability.clear();
const washoutFeatures = featureSet({ short: "bear", options: { short: { rsi: 14, kdj: -8, percentB: -0.22, macd: macd("recover"), participationTrend: "rising", divergence: "bullish_divergence", rsConsistency: "stable", rvol: 3.4 } } });
washoutFeatures.price_position.low_52w = 99;
washoutFeatures.fibonacci_structure.short_term.retracement_levels.r382.price = 99;
washoutFeatures.fibonacci_structure.short_term.retracement_levels.r618.price = 98.9;
washoutFeatures.fibonacci_structure.short_term.extension_levels.e127.price = 110;
washoutFeatures.horizons.short.volatility.bollinger.bollinger_4h.lower_band = 99;
washoutFeatures.horizons.short.volatility.bollinger.bollinger_4h.middle_band = 105;
washoutFeatures.horizons.short.volatility.bollinger.bollinger_4h.upper_band = 110;
result = decide(washoutFeatures, market({ fearGreed: 15 }), "WASHOUT");
assert(!["trim", "sell", "avoid"].includes(result.horizons.short.debug.candidateAction), "bearish exhaustion cannot create a defensive action before its price state permits it");
const validContrarianAccumulate = engine.execution.build({ price: 100, horizon: "short", action: "accumulate", technical: { atr: 1, directionScore: -40, executionContext: { support: { center: 100, members: [], confluence: 3 }, resistance: { center: 108, members: [], confluence: 3 }, levels: [] } } });
assert.equal(validContrarianAccumulate.actionFamily, "opportunity", "bearish exhaustion Accumulate remains executable only inside the opportunity family");

// 4. Clear bearish breakdown sells; extreme ATR does not decide Action Family.
engine.stability.clear();
result = decide(featureSet({ short: "bear" }), market(), "BREAK");
assert.equal(action(result), "sell");
engine.stability.clear();
result = decide(featureSet({ short: "neutral", options: { short: { atrPct: 12, atrPercentile: 97, percentB: 1.4, rvol: 4.2 } } }), market(), "RISK");
assert.notEqual(result.horizons.short.states.direction.label, "Bearish", "extreme ATR alone cannot create a defensive Action Family");

// 6. A recovering structure can reach Buy with confirmation and confluence.
engine.stability.clear();
result = decide(featureSet({ short: "recover" }), market({ regime: "risk_on" }), "RECOVER");
assert(!["trim", "sell", "avoid"].includes(action(result)), "recovering structure remains non-defensive until the price state reaches Reduce or Breakdown");

// 7–8. Market cannot overwrite stock direction; Shock blocks Strong Buy.
engine.stability.clear();
result = decide(featureSet(), market({ regime: "shock" }), "SHOCK");
assert.notEqual(action(result), "strong_buy");
engine.stability.clear();
result = decide(featureSet({ short: "bear" }), market({ regime: "risk_on" }), "WEAK");
assert(!["strong_buy", "buy", "accumulate"].includes(action(result)), "Risk-On does not turn a weak stock into Buy");

// 9. Horizons are independent, with no voting/averaging.
engine.stability.clear();
result = decide(featureSet({ short: "bear", mid: "bull", long: "bull" }), market(), "MIXED");
assert.equal(action(result, "short"), "sell");
assert(!["trim", "sell", "avoid"].includes(action(result, "mid")));
assert(!["trim", "sell", "avoid"].includes(action(result, "long")));

// 10–11. Hysteresis holds through a small in-family move but material shock may flip immediately.
engine.stability.clear();
let stable = engine.stability.evaluate({ ticker: "STABLE", horizon: "short", candidateAction: "buy", allowedActions: ["buy", "accumulate"], actionFamily: "opportunity", edge: 60, confidence: 72 });
stable = engine.stability.evaluate({ ticker: "STABLE", horizon: "short", candidateAction: "accumulate", allowedActions: ["buy", "accumulate"], actionFamily: "opportunity", edge: 36, confidence: 70 });
assert.equal(stable.finalAction, "buy");
stable = engine.stability.evaluate({ ticker: "STABLE", horizon: "short", candidateAction: "sell", allowedActions: ["sell", "avoid"], actionFamily: "defensive", edge: -72, confidence: 81, materialChangeReasons: ["market_shock"] });
assert.equal(stable.finalAction, "sell");

// 12–14. Individual RSI, ATR, or Fear & Greed cannot decide direction/action alone.
engine.stability.clear();
result = decide(featureSet({ short: "neutral", options: { short: { rsi: 88 } } }), market(), "RSI");
assert(!["buy", "sell"].includes(action(result)), "RSI extreme alone cannot create Buy/Sell");
engine.stability.clear();
result = decide(featureSet({ short: "neutral", options: { short: { atrPct: 9, atrPercentile: 94 } } }), market(), "ATR");
assert.equal(result.horizons.short.states.direction.label, "Neutral", "ATR alone cannot be bearish direction");
engine.stability.clear();
const fear = decide(featureSet({ short: "neutral" }), market({ fearGreed: 95 }), "FEAR_A");
engine.stability.clear();
const normalFear = decide(featureSet({ short: "neutral" }), market({ fearGreed: 50 }), "FEAR_B");
assert.equal(fear.horizons.short.states.direction.score, normalFear.horizons.short.states.direction.score, "Fear & Greed has no direction vote");

// 15. Missing structural clusters cannot manufacture a stale entry plan.
const staleExecution = engine.execution.build({ price: 100, horizon: "short", action: "avoid", technical: { atr: 1, directionScore: 70, executionContext: { support: { center: 60, members: [] }, resistance: null, levels: [] } } });
assert.equal(staleExecution.priceState, "INVALID_LANDSCAPE");

// 16. Missing core inputs reduce genuine data quality and confidence.
engine.stability.clear();
const complete = decide(featureSet(), market(), "QUALITY_A");
const missingFeatures = featureSet();
missingFeatures.horizons.short.momentum.macd = { macd_4h: unavailable, macd_1h: unavailable };
missingFeatures.horizons.short.trend.adx = { adx_14_4h: unavailable };
missingFeatures.horizons.short.momentum.rsi = { rsi_6_4h: unavailable };
const missing = decide(missingFeatures, market(), "QUALITY_B");
assert(missing.horizons.short.debug.dataQuality.score < complete.horizons.short.debug.dataQuality.score);
assert(missing.horizons.short.confidence < complete.horizons.short.confidence);

// 17. Trait aggregation stays bounded; profile review is annual and changes
// the modifier pipeline only after the next eligible review.
const profile = engine.profile.build({ primaryClassification: "Test", companyTraits: ["HighGrowth", "HighBeta", "HighVolatility", "CrowdedLeader", "CashCow", "MarketLeader"], lifecycle: "EstablishedLeader" }, "CAP");
assert(profile.effectiveModifiers.riskSensitivity <= 1.15 && profile.effectiveModifiers.riskSensitivity >= 0.85);
assert(profile.effectiveModifiers.marketSensitivity <= 1.2 && profile.effectiveModifiers.marketSensitivity >= 0.8);
engine.profile.clearReviews();
const firstReview = engine.profile.review({ ticker: "REVIEW", profile: { primaryClassification: "Enterprise Software", companyTraits: ["Cloud", "HighGrowth", "LargeCap"], lifecycle: "Scaling", profileConfidence: 0.8 }, now: new Date("2025-01-01T00:00:00Z") });
const earlyReview = engine.profile.review({ ticker: "REVIEW", profile: { primaryClassification: "Enterprise Software", companyTraits: ["Cloud", "CashCow", "LargeCap"], lifecycle: "MatureLeader" }, now: new Date("2025-05-01T00:00:00Z") });
const annualReview = engine.profile.review({ ticker: "REVIEW", profile: { primaryClassification: "Enterprise Software", companyTraits: ["Cloud", "CashCow", "LargeCap"], lifecycle: "MatureLeader", profileConfidence: 0.86 }, now: new Date("2026-01-02T00:00:00Z") });
assert.deepEqual(earlyReview.companyTraits, firstReview.companyTraits, "profile cannot churn before annual review");
assert(annualReview.companyTraits.includes("CashCow") && annualReview.lifecycle === "MatureLeader");
const reviewedProfile = engine.profile.build({ primaryClassification: "Enterprise Software", companyTraits: ["Cloud", "HighGrowth", "LargeCap"], lifecycle: "Scaling" }, "REVIEW");
assert(reviewedProfile.appliedModifiers.includes("CashCow"), "annual profile update changes modifier inputs");

// 18. Short fast noise changes Short, while Long ignores it because its inputs are Daily/Weekly.
engine.stability.clear();
const calm = featureSet({ short: "bull", mid: "bull", long: "bull" });
const noisy = clone(calm);
noisy.horizons.short.momentum.macd.macd_1h = macd("bear");
noisy.horizons.short.trend.moving_averages.ema_20_1h = ma(105, 20, "1h", "falling");
const calmDecision = decide(calm, market(), "LONG_NOISE_A");
engine.stability.clear();
const noisyDecision = decide(noisy, market(), "LONG_NOISE_B");
assert.notEqual(noisyDecision.horizons.short.states.direction.score, calmDecision.horizons.short.states.direction.score);
assert.equal(noisyDecision.horizons.long.states.direction.score, calmDecision.horizons.long.states.direction.score);

// 19. Correlated volatility observations are grouped: a wide band, high ATR
// percentile, and regime flag do not become independent extreme penalties.
const correlated = featureSet({ short: "neutral", options: { short: { atrPct: 6, atrPercentile: 95, rvol: 1.1 } } });
correlated.horizons.short.volatility.atr.atr_14_4h.volatility_regime = "high";
correlated.horizons.short.volatility.bollinger.bollinger_4h.bandwidth_percentile = 100;
engine.stability.clear();
const correlatedDecision = decide(correlated, market(), "CORRELATED_RISK");
assert(correlatedDecision.horizons.short.debug.riskComponents.volatility < 60, "correlated volatility group should not become extreme from percentile/width alone");
assert(correlatedDecision.horizons.short.states.risk.score < 50, "grouped volatility should not over-penalize one volatility episode");

// 20. First observation derives stability from canonical signal persistence,
// rather than treating no prior cached action as fully stable or unstable.
engine.stability.clear();
const weakFirst = engine.stability.evaluate({ ticker: "FIRST_WEAK", horizon: "short", candidateAction: "hold", edge: 0, confidence: 50, technical: { signalPersistence: { score: 43, components: { ma: 43 } } } });
const strongFirst = engine.stability.evaluate({ ticker: "FIRST_STRONG", horizon: "short", candidateAction: "hold", edge: 0, confidence: 50, technical: { signalPersistence: { score: 74, components: { ma: 74 } } } });
assert.equal(weakFirst.score, 43);
assert.equal(strongFirst.score, 74);
assert(weakFirst.score < strongFirst.score && weakFirst.firstObservation && strongFirst.firstObservation);

// 21–25. Price Landscape uses executable zones only. Hold stays neutral;
// Avoid never becomes a synthetic exit plan.
const holdExecution = engine.execution.build({ price: 100, horizon: "short", action: "hold", technical: { atr: 2, executionContext: { support: { center: 98, members: [], confluence: 2 }, resistance: { center: 103, members: [], confluence: 2 }, levels: [] } } });
assert.equal(holdExecution.executionIntent, "hold");
assert(holdExecution.priceLandscape.opportunityRange.high < 100);
assert(holdExecution.priceLandscape.reduceRange.low > 100);
assert(Number.isFinite(holdExecution.priceLandscape.invalidation));
const avoidExecution = engine.execution.build({ price: 100, horizon: "short", action: "avoid", technical: { atr: 2, executionContext: { support: null, resistance: null, levels: [] } } });
assert.equal(avoidExecution.executionIntent, "avoid");
assert.equal(avoidExecution.priceLandscape.reduceRange, null);
assert.equal(avoidExecution.priceLandscape.invalidation, null);

const trimExecution = engine.execution.build({ price: 108, horizon: "short", action: "trim", exhaustionScore: -20, technical: { atr: 2, executionContext: { support: { center: 96, members: [], confluence: 2 }, resistance: { center: 109, members: [], confluence: 3 }, levels: [] } } });
assert.equal(trimExecution.actionFamily, "reduce", "Trim is valid only in the reduce family");
const betweenSell = engine.execution.build({ price: 100, horizon: "short", action: "hold", technical: { atr: 2, directionScore: -30, executionContext: { support: { center: 92, members: [], confluence: 2 }, resistance: { center: 108, members: [], confluence: 2 }, levels: [] } } });
assert.equal(betweenSell.actionFamily, "neutral", "neutral structure has a Hold execution plan rather than a deferred Sell");
const breakdownSell = engine.execution.build({ price: 100, horizon: "short", action: "sell", technical: { atr: 2, directionScore: -70, confirmationScore: 70, executionContext: { support: { center: 92, members: [], confluence: 2 }, resistance: { center: 114, members: [], confluence: 2 }, levels: [] } } });
assert(Math.abs((breakdownSell.priceLandscape.reduceRange.low + breakdownSell.priceLandscape.reduceRange.high) / 2 - 100) < 1, "breakdown exit is anchored to executable current structure");

// 26–27. Zone centres remain structural while widths are ATR-based but bounded;
// weak confluence cannot manufacture a giant, falsely precise zone.
const wideLong = engine.execution.build({ price: 100, horizon: "long", action: "accumulate", technical: { atr: 30, directionScore: 55, executionContext: { support: { center: 70, members: [], confluence: 8 }, resistance: { center: 140, members: [], confluence: 5 }, levels: [] } } });
assert((wideLong.priceLandscape.opportunityRange.high - wideLong.priceLandscape.opportunityRange.low) / 100 <= engine.config.execution.maxHalfWidthPct.long * 2 + 0.0001);
const weakConfluence = engine.execution.build({ price: 100, horizon: "mid", action: "buy", technical: { atr: 12, directionScore: 65, executionContext: { support: { center: 96, members: [], confluence: 0 }, resistance: null, levels: [] } } });
assert.equal(weakConfluence.priceState, "INVALID_LANDSCAPE", "weak unsupported structure does not manufacture a fake precision zone");

// 28–45. Exact range membership defines the final Action Family. Near-zone
// proximity is diagnostic only: it is deliberately Hold until price enters an
// actionable range. Technical evidence selects only strength within a family.
function jointLandscape({ price = 100, opportunity = { low: 97, high: 99 }, reduce = { low: 104, high: 106 }, atr = 1, horizon = "short", invalidation = 95, breakdown = false } = {}) {
  const priceState = engine.execution.priceStateFor({ price, horizon, atr, opportunityRange: opportunity, reduceRange: reduce, invalidation, breakdown });
  return { priceLandscape: { opportunityRange: opportunity, reduceRange: reduce, invalidation, currentPrice: price }, priceState, actionFamily: engine.execution.actionFamilyForState(priceState), landscapeQuality: { state: "high", score: 3, penalty: 0 }, debug: { guardrails: [] } };
}
function decisionAt(landscape, technical, options = {}) {
  return engine.execution.decisionForPriceState({ landscape, technical, risk: options.risk ?? 14, exhaustionScore: options.exhaustionScore ?? 0, edge: options.edge ?? 70, marketModifiers: options.marketModifiers || {}, profile: options.profile || {} });
}
const bullishTechnical = { atr: 1, directionScore: 74, confirmationScore: 76, priceOpportunityScore: 44, dataQuality: { score: 92 }, materialSignals: [] };
const moderateTechnical = { atr: 1, directionScore: 30, confirmationScore: 48, priceOpportunityScore: 18, dataQuality: { score: 92 }, materialSignals: [] };
const bearishTechnical = { atr: 1, directionScore: -62, confirmationScore: 70, priceOpportunityScore: -20, dataQuality: { score: 92 }, materialSignals: [] };
const inOpportunityLandscape = jointLandscape({ price: 98 });
const neutralLandscape = jointLandscape({ price: 101 });
const inReduceLandscape = jointLandscape({ price: 105 });
const nearOpportunityLandscape = jointLandscape({ price: 99.4 });
const nearReduceLandscape = jointLandscape({ price: 103.4 });
assert.equal(inOpportunityLandscape.actionFamily, "opportunity");
assert(["strong_buy", "buy"].includes(decisionAt(inOpportunityLandscape, bullishTechnical).action), "bullish evidence inside Opportunity stays in the Buy family");
assert.equal(decisionAt(inOpportunityLandscape, moderateTechnical, { edge: 24 }).action, "accumulate", "moderate evidence inside Opportunity becomes Accumulate");
assert.equal(decisionAt(inOpportunityLandscape, bearishTechnical, { edge: 32, exhaustionScore: 70 }).action, "accumulate", "bearish exhaustion can be an Accumulate only at a valid opportunity zone");
assert.equal(nearOpportunityLandscape.priceState, "NEAR_OPPORTUNITY_ZONE", "a price just above Opportunity is Near, not inside");
assert.equal(nearOpportunityLandscape.actionFamily, "neutral", "Near Opportunity uses the Hold family");
assert.equal(decisionAt(nearOpportunityLandscape, bullishTechnical).action, "hold", "strong Direction cannot enter early while only Near Opportunity");
assert.equal(jointLandscape({ price: 99.01 }).priceState, "NEAR_OPPORTUNITY_ZONE", "$0.01 above Opportunity.high is not inside the opportunity range");
assert.equal(decisionAt(jointLandscape({ price: 99.01 }), bullishTechnical).action, "hold", "$0.01 above Opportunity.high cannot remain positive");
assert.equal(decisionAt(neutralLandscape, bullishTechnical).action, "hold", "strong Direction alone cannot create Buy in Neutral");
assert.equal(decisionAt(neutralLandscape, bearishTechnical).action, "hold", "ordinary bearish bias cannot create Sell in Neutral");
assert.equal(decisionAt(inReduceLandscape, bullishTechnical).action, "trim", "strong trend inside Reduce is Trim, never Hold");
assert.equal(decisionAt(inReduceLandscape, bearishTechnical).action, "sell", "bearish deterioration inside Reduce is Sell");
assert.equal(nearReduceLandscape.priceState, "NEAR_REDUCE_ZONE", "a price just below Reduce remains Near, not inside");
assert.equal(nearReduceLandscape.actionFamily, "neutral", "Near Reduce uses the Hold family");
assert.equal(decisionAt(nearReduceLandscape, bullishTechnical).action, "hold", "strong Direction cannot reduce early while only Near Reduce");
assert.equal(decisionAt(nearReduceLandscape, bearishTechnical).action, "hold", "bearish Direction still waits for Reduce entry absent breakdown");
assert.equal(jointLandscape({ price: 103.99 }).priceState, "NEAR_REDUCE_ZONE", "$0.01 below Reduce.low is not inside the reduce range");
assert.equal(decisionAt(jointLandscape({ price: 103.99 }), bearishTechnical).action, "hold", "$0.01 below Reduce.low cannot sell early");
assert.equal(jointLandscape({ price: 103, atr: 4 }).priceState, "NEAR_REDUCE_ZONE", "closest real zone wins when ATR proximity bands meet");
assert.equal(decisionAt(jointLandscape({ price: 94 }), bearishTechnical).action, "sell", "a confirmed invalidation/breakdown permits Sell");

engine.stability.clear();
let stateful = engine.stability.evaluate({ ticker: "FAMILY_BOUNDARY", horizon: "short", candidateAction: "hold", allowedActions: ["hold"], actionFamily: "neutral", edge: 18, confidence: 64, technical: { signalPersistence: { score: 66 } } });
stateful = engine.stability.evaluate({ ticker: "FAMILY_BOUNDARY", horizon: "short", candidateAction: "trim", allowedActions: ["trim", "sell"], actionFamily: "reduce", edge: 18, confidence: 64, technical: { signalPersistence: { score: 66 } } });
assert.equal(stateful.finalAction, "trim", "previous Hold cannot survive entering Reduce");
assert(stateful.familyBoundaryOverride, "Price State boundary is explicit in stability debug");
stateful = engine.stability.evaluate({ ticker: "FAMILY_BOUNDARY", horizon: "short", candidateAction: "hold", allowedActions: ["hold"], actionFamily: "neutral", edge: 18, confidence: 64, technical: { signalPersistence: { score: 66 } } });
assert.equal(stateful.finalAction, "hold", "previous Trim cannot survive a return to Neutral");
engine.stability.clear();
stateful = engine.stability.evaluate({ ticker: "NEAR_BOUNDARY", horizon: "short", candidateAction: "buy", allowedActions: ["strong_buy", "buy", "accumulate"], actionFamily: "opportunity", edge: 62, confidence: 72, technical: { signalPersistence: { score: 66 } } });
stateful = engine.stability.evaluate({ ticker: "NEAR_BOUNDARY", horizon: "short", candidateAction: "hold", allowedActions: ["hold"], actionFamily: "neutral", edge: 62, confidence: 66, technical: { signalPersistence: { score: 66 } } });
assert.equal(stateful.finalAction, "hold", "previous Buy cannot survive moving only Near Opportunity");
engine.stability.clear();
stateful = engine.stability.evaluate({ ticker: "NEAR_REDUCE_BOUNDARY", horizon: "short", candidateAction: "trim", allowedActions: ["trim", "sell"], actionFamily: "reduce", edge: -44, confidence: 72, technical: { signalPersistence: { score: 66 } } });
stateful = engine.stability.evaluate({ ticker: "NEAR_REDUCE_BOUNDARY", horizon: "short", candidateAction: "hold", allowedActions: ["hold"], actionFamily: "neutral", edge: -44, confidence: 66, technical: { signalPersistence: { score: 66 } } });
assert.equal(stateful.finalAction, "hold", "previous Trim cannot survive moving only Near Reduce");
const breakdownTechnical = { ...bearishTechnical, directionScore: -75, executionContext: { support: { center: 92, members: [], confluence: 2, quality: 2 }, resistance: { center: 114, members: [], confluence: 2, quality: 2 }, levels: [] } };
const rebuiltBreakdown = engine.execution.buildLandscape({ price: 100, horizon: "short", technical: breakdownTechnical, context: { risk: 18, exhaustionScore: 0 } });
const breakdownDecision = decisionAt(rebuiltBreakdown, breakdownTechnical);
assert.equal(rebuiltBreakdown.priceState, "BREAKDOWN_ZONE", "confirmed breakdown becomes a defensive Price State");
assert.equal(breakdownDecision.action, "sell", "a previous Neutral may flip to Sell for a confirmed breakdown");
assert(Math.abs((rebuiltBreakdown.priceLandscape.reduceRange.low + rebuiltBreakdown.priceLandscape.reduceRange.high) / 2 - 100) < 1, "breakdown reduce range is re-anchored near the executable current area");

const rawOverlapLandscape = engine.execution.buildLandscape({
  price: 100, horizon: "short", technical: { atr: 1, directionScore: 20, executionContext: {
    supportClusters: [{ center: 99, confluence: 3, quality: 3, members: [], independentStructures: 2 }],
    resistanceClusters: [{ center: 100, confluence: 3, quality: 3, members: [], independentStructures: 2 }], levels: [],
  } },
});
assert.notEqual(rawOverlapLandscape.priceState, "INVALID_LANDSCAPE", "a raw overlap is rebuilt when a feasible neutral buffer exists");
assert(rawOverlapLandscape.priceLandscape.opportunityRange.high < rawOverlapLandscape.priceLandscape.reduceRange.low, "Opportunity and Reduce ranges never overlap");
assert(rawOverlapLandscape.landscapeQuality.separation > rawOverlapLandscape.landscapeQuality.neutralBuffer, "a dynamic neutral buffer remains between ranges");
const impossibleLandscape = engine.execution.buildLandscape({ price: 100, horizon: "short", technical: { atr: 2, executionContext: { support: { center: 99.9, confluence: 0.1, members: [] }, resistance: { center: 100.1, confluence: 0.1, members: [] }, levels: [] } } });
assert.equal(impossibleLandscape.priceState, "INVALID_LANDSCAPE", "weak overlapping clusters are not emitted as fake zones");

engine.stability.clear();
const confidenceReconciled = decide(featureSet(), market({ regime: "risk_on" }), "FINAL_CONFIDENCE");
const confidenceHorizon = confidenceReconciled.horizons.short;
assert.equal(confidenceHorizon.debug.confidenceComponents.action, confidenceHorizon.action, "confidence is recomputed for the final action");
const finalFamilyDecision = decisionAt(neutralLandscape, bullishTechnical);
const familyConfidence = engine.confidence.calculate({
  action: finalFamilyDecision.action, edge: 72,
  technical: { ...bullishTechnical, signalAgreement: 82, signalPersistence: { score: 68 }, dataQuality: { score: 92 } },
  marketModifiers: {}, exhaustion: {}, profile: { profileConfidence: 0.9 },
  finalDecision: finalFamilyDecision, landscapeQuality: neutralLandscape.landscapeQuality,
});
assert.equal(familyConfidence.action, "hold", "confidence follows the final Price-State action");
assert(familyConfidence.penalties.priceStateTension > 0, "Neutral-vs-strong-direction tension lowers confidence without changing family");

// 28–29. A normal small edge move remains hysteretic; a material shock bypasses
// it immediately instead of leaving a stale Buy locked in cache.
engine.stability.clear();
let perturbed = engine.stability.evaluate({ ticker: "PERTURB", horizon: "mid", candidateAction: "buy", allowedActions: ["buy", "accumulate"], actionFamily: "opportunity", edge: 60, confidence: 70, technical: { signalPersistence: { score: 66 } } });
perturbed = engine.stability.evaluate({ ticker: "PERTURB", horizon: "mid", candidateAction: "accumulate", allowedActions: ["buy", "accumulate"], actionFamily: "opportunity", edge: 37, confidence: 68, technical: { signalPersistence: { score: 65 } } });
assert.equal(perturbed.finalAction, "buy");
perturbed = engine.stability.evaluate({ ticker: "PERTURB", horizon: "mid", candidateAction: "sell", allowedActions: ["sell", "avoid"], actionFamily: "defensive", edge: -72, confidence: 80, materialChangeReasons: ["atr_volume_shock"], technical: { signalPersistence: { score: 65 } } });
assert.equal(perturbed.finalAction, "sell");

// 30–31. Market and trait modifiers are capped centrally, even if several tags
// or an event coincide.
const cappedMarket = engine.market.forHorizon({ regime: "shock", riskAddBase: 38, yield: { riskAdd: 12 }, earnings: { riskAdd: 20, confidencePenalty: 10 } }, "long", { effectiveModifiers: { marketSensitivity: 1.2, rateSensitivity: 1.15, eventSensitivity: 1.12 } });
assert(cappedMarket.riskAdd <= engine.config.market.maxRiskAdd.long);
const capProfile = engine.profile.build({ primaryClassification: "Test", companyTraits: ["HighGrowth", "HighBeta", "HighVolatility", "CrowdedLeader", "CashCow", "MarketLeader", "RegulatoryRisk"], lifecycle: "EstablishedLeader" }, "CAP_ALL");
for (const key of ["riskSensitivity", "marketSensitivity", "exhaustionSensitivity", "normalAtrTolerance", "strongBuyOpportunity", "eventSensitivity"]) {
  const [low, high] = engine.config.profile.modifierCaps[["marketSensitivity", "exhaustionSensitivity"].includes(key) ? "special" : "normal"];
  assert(capProfile.effectiveModifiers[key] >= low && capProfile.effectiveModifiers[key] <= high, `${key} must remain capped`);
}

// 32–36. ETF profiles do not borrow Company Traits. Leveraged funds use
// stricter gates/sensitivity, and inverse underlying context is bounded.
for (const [ticker, expected] of Object.entries({ QQQ: [false, "long"], TQQQ: [true, "long"], SQQQ: [true, "inverse"], SOXL: [true, "long"], SOXS: [true, "inverse"] })) {
  const definition = profiles.profileFor(ticker);
  assert.equal(definition.isETF, true);
  assert.equal(definition.leveraged, expected[0]);
  assert.equal(definition.direction, expected[1]);
  assert.equal(engine.profile.build(definition, ticker).companyTraits.length, 0);
}
const oneX = engine.profile.build(profiles.profileFor("QQQ"), "QQQ");
const leveraged = engine.profile.forHorizon(engine.profile.build(profiles.profileFor("TQQQ"), "TQQQ"), "long");
assert(leveraged.effectiveModifiers.riskSensitivity > oneX.effectiveModifiers.riskSensitivity);
assert(leveraged.effectiveModifiers.marketSensitivity > oneX.effectiveModifiers.marketSensitivity);
const inverseFeatures = featureSet({ short: "bull", mid: "bull", long: "bear" });
const underlyingFeatures = featureSet({ short: "bear", mid: "bear", long: "bull" });
engine.stability.clear();
const inverseDecision = engine.decide({ ticker: "SQQQ", price: 100, technicalFeatures: inverseFeatures, underlyingTechnicalFeatures: underlyingFeatures, underlyingPrice: 100, marketContext: market(), classification: profiles.profileFor("SQQQ"), metadata: {}, language: "en" });
assert.equal(inverseDecision.horizons.short.debug.etfUnderlying.alignment, "supporting");
assert.equal(inverseDecision.horizons.long.debug.etfUnderlying.alignment, "supporting");
assert.equal(engine.etfProfile.underlyingContext({ profile: engine.profile.build(profiles.profileFor("SQQQ"), "SQQQ"), ownDirection: 60, underlyingDirection: 60 }).alignment, "limiting");
assert.notEqual(inverseDecision.horizons.short.states.direction.score, -underlyingFeatures.horizons.short.trend.moving_averages.ema_20_4h.value, "underlying cannot replace ETF Direction");

// 37. Every individual stock has a reviewed specific classification and at
// least three Company Traits; ETFs are deliberately excluded from this rule.
for (const ticker of watchlist) {
  const definition = profiles.profileFor(ticker);
  if (definition.isETF) continue;
  assert(definition.primaryClassification && definition.primaryClassification !== "Unclassified Equity", `${ticker} needs a primary classification`);
  assert((definition.companyTraits || []).length >= 3, `${ticker} needs at least three Company Traits`);
}

for (const decision of [complete, missing, calmDecision, noisyDecision]) {
  for (const horizonDecision of Object.values(decision.horizons)) {
    assert(engine.config.actions.includes(horizonDecision.action));
    assert.equal(typeof horizonDecision.confidence, "number");
    assert(["enter", "add", "hold", "reduce", "exit", "avoid"].includes(horizonDecision.executionIntent));
    assert.deepEqual(Object.keys(horizonDecision.states), ["direction", "confirmation", "risk", "priceOpportunity", "exhaustion"]);
    assert.equal(Object.hasOwn(horizonDecision, "score_breakdown"), false);
    assert.equal(Object.hasOwn(horizonDecision, "action_recommendation_score"), false);
    assert.equal(Object.hasOwn(horizonDecision.debug, "finalScore"), false);
    assert(Object.hasOwn(horizonDecision, "priceLandscape"));
    for (const key of ["directionComponents", "confirmationComponents", "riskComponents", "priceComponents", "exhaustionComponents", "marketRegime", "marketModifiers", "appliedTraits", "appliedModifiers", "effectiveProfileModifiers", "rawEdge", "adjustedEdge", "edgeBeforeMarket", "edgeAfterMarket", "candidateAction", "actionBeforeStability", "finalAction", "priceState", "actionFamily", "landscapeQuality", "finalDecision", "stability", "guardrails", "materialChangeReasons", "confidenceComponents", "priceLandscapeInputs", "invalidationInputs", "dataQuality"]) assert(Object.hasOwn(horizonDecision.debug, key), `V1 debug field missing: ${key}`);
  }
}

// Performance guardrails: large raw indicator series remain in the canonical
// feature source, not in decisions or the bounded hysteresis cache.
const seriesFeatures = featureSet();
seriesFeatures.horizons.short.momentum.macd.macd_4h.macd_series = Array(20_000).fill(1);
engine.stability.clear();
const compactDecision = decide(seriesFeatures, market(), "SERIES_GUARD");
assert(Buffer.byteLength(JSON.stringify(compactDecision)) < 60_000, "decision output must not clone raw indicator history");
for (let index = 0; index < engine.config.stability.cacheLimit + 5; index += 1) engine.stability.evaluate({ ticker: `BOUND_${index}`, horizon: "short", candidateAction: "hold", edge: 0, confidence: 50 });
assert(engine.stability._cache.size <= engine.config.stability.cacheLimit, "stability cache must remain bounded");

// Refresh contract. The Price Landscape is recomputed from the current
// canonical structure every time: it has no range/cluster cache and no
// preference for a previous selection. Same-category density localises a
// zone but cannot inflate its evidence as if it were independent proof.
const supportMAs = [98.00, 98.08, 98.14, 98.22, 98.28].map((price, index) => ({
  price, type: "moving_average", category: "moving_average", role: "support", weight: 0.80, label: `EMA ${index + 1}`,
}));
const supportOneMa = [supportMAs[0]];
const supportCrossCategory = [
  supportMAs[0],
  { price: 98.06, type: "fib", category: "fibonacci", role: "support", weight: 0.65, label: "Fib retracement" },
  { price: 97.98, type: "swing", category: "swing", role: "support", weight: 1.0, label: "Swing low" },
  { price: 98.12, type: "bollinger", category: "bollinger", role: "support", weight: 0.65, label: "Bollinger lower" },
];
const resistanceCrossCategory = [
  { price: 106.0, type: "fib", category: "fibonacci", role: "reduce", weight: 0.65, label: "Fib extension" },
  { price: 106.08, type: "swing", category: "swing", role: "reduce", weight: 1.0, label: "Swing high" },
  { price: 106.15, type: "moving_average", category: "moving_average", role: "reduce", weight: 0.80, label: "EMA resistance" },
];
const maOnlyCluster = engine.technical.clusterLevels(supportOneMa, 100, 1, "support")[0];
const maDenseCluster = engine.technical.clusterLevels(supportMAs, 100, 1, "support")[0];
const crossCategoryCluster = engine.technical.clusterLevels(supportCrossCategory, 100, 1, "support")[0];
assert.equal(maDenseCluster.independentStructures, 1, "five moving averages remain one structural category");
assert(maDenseCluster.quality <= maOnlyCluster.quality + 0.03, "same-category duplicate levels cannot multiply confluence quality");
assert(crossCategoryCluster.quality > maDenseCluster.quality, "cross-category agreement increases confluence quality");
assert.deepEqual(new Set(crossCategoryCluster.categoryBreakdown.map((item) => item.category)), new Set(["moving_average", "fibonacci", "swing", "bollinger"]));

function structureTechnical({ atr = 1, supports = supportCrossCategory, resistances = resistanceCrossCategory, directionScore = 45, confirmationScore = 62, materialSignals = [] } = {}) {
  return {
    atr, directionScore, confirmationScore, materialSignals,
    executionContext: {
      levels: [...supports, ...resistances],
      supportClusters: engine.technical.clusterLevels(supports, 100, atr, "support"),
      resistanceClusters: engine.technical.clusterLevels(resistances, 100, atr, "reduce"),
      atr, structureModel: "unified_category_confluence",
    },
  };
}
const refreshTechnical = structureTechnical();
const refreshOne = engine.execution.buildLandscape({ price: 100, horizon: "short", technical: refreshTechnical, context: { risk: 18, exhaustionScore: 0 } });
const refreshOneRepeat = engine.execution.buildLandscape({ price: 100, horizon: "short", technical: refreshTechnical, context: { risk: 18, exhaustionScore: 0 } });
assert.deepEqual(refreshOne.priceLandscape, refreshOneRepeat.priceLandscape, "identical refresh inputs deterministically recompute the same landscape");
const minorPriceRefresh = engine.execution.buildLandscape({ price: 100.25, horizon: "short", technical: refreshTechnical, context: { risk: 18, exhaustionScore: 0 } });
assert.equal(minorPriceRefresh.debug.priceLandscapeInputs.selectedSupport.center, refreshOne.debug.priceLandscapeInputs.selectedSupport.center, "current price alone cannot drag the opportunity centre upward");
const widerAtrTechnical = structureTechnical({ atr: 2 });
const widerAtrRefresh = engine.execution.buildLandscape({ price: 100, horizon: "short", technical: widerAtrTechnical, context: { risk: 18, exhaustionScore: 0 } });
assert.equal(widerAtrRefresh.debug.priceLandscapeInputs.selectedSupport.center, refreshOne.debug.priceLandscapeInputs.selectedSupport.center, "ATR changes range width, not the structural zone centre");
assert(widerAtrRefresh.debug.priceLandscapeInputs.opportunity.width > refreshOne.debug.priceLandscapeInputs.opportunity.width, "higher ATR expands the zone width inside its existing bounds");

const refreshedSupports = supportCrossCategory.map((level) => ({ ...level, price: level.price + 1.1, label: `${level.label} refreshed` }));
const refreshedResistances = resistanceCrossCategory.map((level) => ({ ...level, price: level.price + 2.2, label: `${level.label} refreshed` }));
const refreshTwoTechnical = structureTechnical({ supports: refreshedSupports, resistances: refreshedResistances });
const refreshTwo = engine.execution.buildLandscape({ price: 100, horizon: "short", technical: refreshTwoTechnical, context: { risk: 18, exhaustionScore: 0 } });
assert.notEqual(refreshTwo.debug.priceLandscapeInputs.selectedSupport.center, refreshOne.debug.priceLandscapeInputs.selectedSupport.center, "new confirmed structure replaces the old opportunity cluster without a switching lock");
assert(refreshTwo.priceLandscape.opportunityRange.low > refreshOne.priceLandscape.opportunityRange.low, "new support structure can move the recomputed opportunity range");
assert.equal(Object.hasOwn(engine.execution, "_landscapeCache"), false, "execution engine intentionally has no Landscape cache");
assert.equal(Object.hasOwn(refreshOne.debug.priceLandscapeInputs, "opportunityCandidates"), false, "final decision debug does not retain temporary candidate clusters");
assert.equal(Object.hasOwn(refreshOne.debug.priceLandscapeInputs, "reduceCandidates"), false, "final decision debug does not retain temporary candidate clusters");

const breakdownRefresh = engine.execution.buildLandscape({
  price: 100, horizon: "short",
  technical: structureTechnical({ directionScore: -78, confirmationScore: 74, materialSignals: ["major_support_breakdown"] }),
  context: { risk: 66, exhaustionScore: -12 },
});
assert.equal(breakdownRefresh.priceState, "BREAKDOWN_ZONE", "a material breakdown invalidates the prior opportunity landscape in the same refresh");
assert(Math.abs((breakdownRefresh.priceLandscape.reduceRange.low + breakdownRefresh.priceLandscape.reduceRange.high) / 2 - 100) < 1, "material breakdown re-anchors the executable reduce range immediately");

engine.stability.clear();
for (let refresh = 0; refresh < 5; refresh += 1) decide(featureSet(), market(), "REPEATED_REFRESH");
assert(engine.stability._cache.size <= 3, "five refreshes retain only compact per-horizon stability state for one ticker");

console.log("decision-engine.test.js: V1 scenarios, Price Landscape, profile, and ETF assertions passed");
