#!/usr/bin/env node
"use strict";

// Read-only calibration audit.  This script builds the same canonical feature
// objects as the dashboard, asks the existing engine for decisions, prints a
// compact JSON report, and exits.  It never refreshes the provider, mutates the
// watchlist, or persists recommendation history.
const path = require("node:path");
const { buildTechnicalFeatures } = require("../technical-features.js");
const profiles = require("../profile-definitions.js");

for (const file of [
  "config.js", "technical-engine.js", "exhaustion-engine.js", "market-engine.js", "etf-profile.js", "company-profile.js",
  "execution-engine.js", "confidence-engine.js", "stability-engine.js", "decision-engine.js",
]) require(path.join(__dirname, "..", "decision-engine", file));

const decisionEngine = globalThis.DecisionEngine;
const ACTIONS = [...decisionEngine.config.actions];
const HORIZONS = ["short", "mid", "long"];
const finite = (value) => value == null || value === "" ? null : Number.isFinite(Number(value)) ? Number(value) : null;
const clone = (value) => JSON.parse(JSON.stringify(value));
const mean = (values) => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
const round = (value, digits = 2) => Number.isFinite(value) ? Number(value.toFixed(digits)) : null;
const quantile = (values, fraction) => {
  const sorted = values.filter(Number.isFinite).sort((left, right) => left - right);
  if (!sorted.length) return null;
  const position = (sorted.length - 1) * fraction;
  const low = Math.floor(position);
  const high = Math.ceil(position);
  return sorted[low] + (sorted[high] - sorted[low]) * (position - low);
};
const distribution = (values) => {
  const valid = values.filter(Number.isFinite);
  return valid.length ? Object.fromEntries([
    ["count", valid.length], ["min", round(Math.min(...valid))], ["p10", round(quantile(valid, 0.10))],
    ["p25", round(quantile(valid, 0.25))], ["median", round(quantile(valid, 0.50))],
    ["p75", round(quantile(valid, 0.75))], ["p90", round(quantile(valid, 0.90))],
    ["max", round(Math.max(...valid))], ["mean", round(mean(valid))],
  ]) : { count: 0, min: null, p10: null, p25: null, median: null, p75: null, p90: null, max: null, mean: null };
};

const returnPct = (closes, lookback) => {
  const values = (closes || []).map(finite).filter((value) => value != null);
  const latest = values.at(-1);
  const base = values.at(-1 - lookback);
  return Number.isFinite(latest) && Number.isFinite(base) && base !== 0 ? (latest / base - 1) * 100 : null;
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
function profileFor(ticker, quote = {}) {
  return profiles.profileFor(ticker, quote.metadata || quote);
}
function featureFor(quote, market) {
  const price = finite(quote.price);
  return buildTechnicalFeatures({
    history: quote.history || {}, currentPrice: price, relativeStrength: relativeStrength(quote, market),
    fibonacciStructure: quote.technical?.fibonacci_structure || {}, shareBase: quote.metadata?.sharesOutstanding || null,
  });
}
function decisionFor(ticker, quote, market, technicalFeatures = featureFor(quote, market), price = finite(quote.price), underlying = null) {
  return decisionEngine.decide({ ticker, price, technicalFeatures, marketContext: market, classification: profileFor(ticker, quote), metadata: quote.metadata || {}, language: "en", underlyingTechnicalFeatures: underlying?.features || null, underlyingPrice: underlying?.price ?? null });
}

function indicator(features, horizon, group, key) {
  const config = decisionEngine.config.horizons[horizon];
  const set = features?.horizons?.[config.technicalKey] || {};
  const interval = key === "ma" && config.maInterval ? config.maInterval : config.primaryInterval;
  if (group === "rsi") return set.momentum?.rsi?.[`rsi_${config.rsiPeriod}_${config.primaryInterval}`];
  if (group === "macd") return set.momentum?.macd?.[`macd_${config.primaryInterval}`];
  if (group === "atr") return set.volatility?.atr?.[`atr_14_${config.primaryInterval}`];
  if (group === "rs") return set.relative_strength?.primary;
  if (group === "ma") return Object.values(set.trend?.moving_averages || {}).filter((item) => item?.interval === interval);
  return null;
}
function nudge(features, horizon, kind) {
  const copy = clone(features);
  if (kind === "rsi") {
    const item = indicator(copy, horizon, "rsi");
    if (Number.isFinite(item?.value)) item.value += 2;
  } else if (kind === "macd") {
    const item = indicator(copy, horizon, "macd");
    if (item) ["histogram", "histogram_change_1", "histogram_change_3", "histogram_change_5"].forEach((key) => { if (Number.isFinite(item[key])) item[key] += Math.max(0.002, Math.abs(item[key]) * 0.05); });
  } else if (kind === "atr") {
    const item = indicator(copy, horizon, "atr");
    if (item) { if (Number.isFinite(item.value)) item.value *= 1.05; if (Number.isFinite(item.atr_pct)) item.atr_pct *= 1.05; if (Number.isFinite(item.atr_percentile_pct)) item.atr_percentile_pct = Math.min(100, item.atr_percentile_pct + 2); }
  } else if (kind === "rs") {
    const item = indicator(copy, horizon, "rs");
    if (item) ["stock_return", "vs_spy", "vs_qqq"].forEach((key) => { if (Number.isFinite(item[key])) item[key] += 1; });
  }
  return copy;
}
function rangeWidthPct(value, price) {
  const range = value?.priceLandscape?.opportunityRange;
  return Number.isFinite(range?.low) && Number.isFinite(range?.high) && Number.isFinite(price) && price > 0
    ? (range.high - range.low) / price * 100 : null;
}
function fibMeta(features, horizon) {
  const key = decisionEngine.config.horizons[horizon]?.fibonacciKey;
  const fib = features?.fibonacci_structure?.[key] || {};
  return {
    sourceTimeframe: fib.source_timeframe || null,
    fallbackReason: fib.fallback_reason || null,
    sourceBarCount: fib.source_bar_count ?? null,
    lookback: fib.lookback_bars ?? null,
    sourceObjectId: fib.source_object_id || fib.source_id || null,
  };
}
function concise(value, price, features, horizon) {
  const opportunity = value.priceLandscape?.opportunityRange;
  const reduce = value.priceLandscape?.reduceRange;
  return {
    action: value.action, candidateAction: value.debug.candidateAction, finalAction: value.debug.finalAction,
    priceState: value.debug.priceState, actionFamily: value.debug.actionFamily, landscapeQuality: value.debug.landscapeQuality,
    finalDecision: value.debug.finalDecision, stability: value.debug.stability, confidence: value.confidence, direction: value.states.direction.score,
    confirmation: value.states.confirmation.score, risk: value.states.risk.score,
    priceOpportunity: value.states.priceOpportunity.score, exhaustion: value.states.exhaustion.score,
    marketRegime: value.market.regime, executionIntent: value.executionIntent || null,
    priceLandscape: value.priceLandscape,
    supporting: value.reasons.supporting, limiting: value.reasons.limiting,
    rangeWidthPct: round(rangeWidthPct(value, price)), rawEdge: value.debug.rawEdge,
    edgeBeforeMarket: value.debug.edgeBeforeMarket ?? null, edgeAfterMarket: value.debug.edgeAfterMarket ?? value.debug.adjustedEdge,
    marketRiskAdd: value.debug.marketModifiers?.riskAdd ?? null, riskComponents: value.debug.riskComponents,
    exhaustionComponents: value.debug.exhaustionComponents, confidenceComponents: value.debug.confidenceComponents,
    appliedTraits: value.debug.appliedTraits,
    effectiveProfileModifiers: value.debug.effectiveProfileModifiers,
    neutralBoundaries: { low: opportunity?.high ?? null, high: reduce?.low ?? null },
    priceStructure: {
      model: value.debug.priceLandscapeInputs?.structureModel || null,
      selectedOpportunity: value.debug.priceLandscapeInputs?.selectedSupport || null,
      selectedReduce: value.debug.priceLandscapeInputs?.selectedReduce || null,
    },
    fibonacci: fibMeta(features, horizon),
  };
}
function emptyActions() { return Object.fromEntries([...ACTIONS, "unavailable"].map((action) => [action, 0])); }
function validRange(range) { return Number.isFinite(range?.low) && Number.isFinite(range?.high) && range.low <= range.high; }
function landscapeViolations(value, price) {
  const landscape = value.priceLandscape || {};
  const opportunity = landscape.opportunityRange;
  const reduce = landscape.reduceRange;
  const state = value.debug.priceState;
  const action = value.action;
  const breakdown = Boolean(value.debug.finalDecision?.breakdown);
  const bearishEvidence = Boolean(value.debug.finalDecision?.bearishEvidence);
  const positive = ["strong_buy", "buy", "accumulate"].includes(action);
  const negative = ["trim", "sell"].includes(action);
  const opportunityState = state === "IN_OPPORTUNITY_ZONE";
  const nearOpportunity = state === "NEAR_OPPORTUNITY_ZONE";
  const neutralState = state === "NEUTRAL_ZONE";
  const nearReduce = state === "NEAR_REDUCE_ZONE";
  const reduceState = ["IN_REDUCE_ZONE", "BEYOND_REDUCE_ZONE"].includes(state);
  const midpoint = validRange(reduce) ? (reduce.low + reduce.high) / 2 : null;
  return {
    positiveActionOutsideOpportunity: positive && !opportunityState,
    trimSellOutsideReduceWithoutBreakdown: negative && !reduceState && state !== "BREAKDOWN_ZONE" && !breakdown,
    nearOpportunityNonHold: nearOpportunity && action !== "hold",
    nearReduceNonHold: nearReduce && action !== "hold",
    opportunityNegativeAction: opportunityState && !positive,
    neutralNonHold: neutralState && action !== "hold",
    reduceHoldOrPositiveAction: reduceState && (!negative || action === "hold"),
    breakdownSellWithoutExecutableReanchor: action === "sell" && (state === "BREAKDOWN_ZONE" || breakdown) && Number.isFinite(midpoint) && Number.isFinite(price) && Math.abs(midpoint - price) > Math.max(1, Math.abs(price) * 0.02),
    overlap: validRange(opportunity) && validRange(reduce) && opportunity.high >= reduce.low,
    invertedRange: [opportunity, reduce].some((range) => range && Number.isFinite(range.low) && Number.isFinite(range.high) && range.low > range.high),
    invalidRange: [opportunity, reduce].some((range) => range && !validRange(range)),
    hysteresisFamilyViolation: Boolean(value.debug.stability?.heldPrevious && !value.debug.stability?.allowedActions?.includes(value.action)),
    priceStateActionMismatch: opportunityState ? !positive : (nearOpportunity || neutralState || nearReduce) ? action !== "hold" : reduceState ? !negative : state === "BREAKDOWN_ZONE" ? !["sell", "avoid"].includes(action) : action !== "avoid",
  };
}

async function main() {
  const base = process.env.DECISION_AUDIT_API || "http://127.0.0.1:4174";
  const watchlistResponse = await fetch(`${base}/api/watchlist`);
  if (!watchlistResponse.ok) throw new Error(`Watchlist API returned ${watchlistResponse.status}`);
  const watchlistPayload = await watchlistResponse.json();
  const tickers = (watchlistPayload.items || watchlistPayload.watchlist || []).map((item) => typeof item === "string" ? item : item.ticker).filter(Boolean).map((ticker) => String(ticker).toUpperCase());
  const requestedSix = ["META", "MSFT", "NVDA", "MU", "AMZN", "GOOGL"];
  const priceLandscapeTickers = ["ZETA", "BABA", "MSFT", "SOFI", "HIMS", "NVDA", "GOOGL", "META", "NOW", "AMD", "QQQ", "TQQQ", "SQQQ", "SOXL", "SOXS"];
  const etfTickers = ["QQQ", "SPMO", "TQQQ", "SQQQ", "SOXL", "SOXS"];
  const auditTickers = [...new Set([...tickers, ...requestedSix, ...priceLandscapeTickers, ...etfTickers])];
  const response = await fetch(`${base}/api/market-data?tickers=${encodeURIComponent(auditTickers.join(","))}&cache_only=1`);
  if (!response.ok) throw new Error(`Market-data API returned ${response.status}`);
  const payload = await response.json();
  const market = payload.marketContext || payload.market_context || {};
  const rows = Object.fromEntries((payload.items || []).map((item) => [item.ticker, item.analysis || item]));
  const prepared = Object.fromEntries(auditTickers.map((ticker) => {
    const quote = rows[ticker] || {};
    const price = finite(quote.price);
    return [ticker, { quote, price, features: Number.isFinite(price) && quote.history?.availability !== "unavailable" ? featureFor(quote, market) : null }];
  }));
  const actionDistribution = Object.fromEntries(HORIZONS.map((horizon) => [horizon, emptyActions()]));
  const priceStateDistribution = Object.fromEntries(HORIZONS.map((horizon) => [horizon, Object.fromEntries(decisionEngine.execution.PRICE_STATES.map((state) => [state, 0]))]));
  const stateValues = Object.fromEntries(HORIZONS.map((horizon) => [horizon, { direction: [], confirmation: [], risk: [], priceOpportunity: [], exhaustion: [], confidence: [], rangeWidthPct: [] }]));
  const highRisk = [];
  const highExhaustion = [];
  const landscapeViolationRows = [];
  const statelessRecomputationMismatches = [];
  const perTicker = {};
  const valid = [];
  for (const ticker of auditTickers) {
    const onWatchlist = tickers.includes(ticker);
    const quote = rows[ticker] || {};
    const price = finite(quote.price);
    if (!Number.isFinite(price) || quote.history?.availability === "unavailable") {
      if (onWatchlist) HORIZONS.forEach((horizon) => { actionDistribution[horizon].unavailable += 1; });
      perTicker[ticker] = { status: "unavailable", reason: quote.history?.unavailable_reason || quote.error || "No cached quote/history." };
      continue;
    }
    decisionEngine.stability.clear();
    const features = prepared[ticker]?.features || featureFor(quote, market);
    const classification = profileFor(ticker, quote);
    const underlying = classification.isETF && classification.underlyingTicker ? prepared[classification.underlyingTicker] : null;
    const decision = decisionFor(ticker, quote, market, features, price, underlying);
    // No prior landscape is supplied to either run.  Clearing compact action
    // state makes this a direct refresh-contract check rather than a test of
    // hysteresis: identical canonical input must rebuild the same landscape.
    decisionEngine.stability.clear();
    const repeatedDecision = decisionFor(ticker, quote, market, features, price, underlying);
    HORIZONS.forEach((horizon) => {
      const first = decision.horizons[horizon];
      const repeated = repeatedDecision.horizons[horizon];
      const left = JSON.stringify({ action: first.action, priceState: first.debug.priceState, landscape: first.priceLandscape });
      const right = JSON.stringify({ action: repeated.action, priceState: repeated.debug.priceState, landscape: repeated.priceLandscape });
      if (left !== right) statelessRecomputationMismatches.push({ ticker, horizon, first: { action: first.action, priceState: first.debug.priceState, landscape: first.priceLandscape }, repeated: { action: repeated.action, priceState: repeated.debug.priceState, landscape: repeated.priceLandscape } });
    });
    const horizons = {};
    HORIZONS.forEach((horizon) => {
      const value = decision.horizons[horizon];
      if (onWatchlist) actionDistribution[horizon][value.action] += 1;
      horizons[horizon] = concise(value, price, features, horizon);
      const violations = landscapeViolations(value, price);
      Object.entries(violations).filter(([, violated]) => violated).forEach(([rule]) => landscapeViolationRows.push({ ticker, horizon, rule, action: value.action, priceState: value.debug.priceState, actionFamily: value.debug.actionFamily, price, landscape: value.priceLandscape, candidateAction: value.debug.candidateAction, breakdown: value.debug.finalDecision?.breakdown || false, bearishEvidence: value.debug.finalDecision?.bearishEvidence || false }));
      if (onWatchlist) {
        if (Object.hasOwn(priceStateDistribution[horizon], value.debug.priceState)) priceStateDistribution[horizon][value.debug.priceState] += 1;
        ["direction", "confirmation", "risk", "priceOpportunity", "exhaustion"].forEach((state) => stateValues[horizon][state].push(value.states[state].score));
        stateValues[horizon].confidence.push(value.confidence);
        const width = rangeWidthPct(value, price);
        if (Number.isFinite(width)) stateValues[horizon].rangeWidthPct.push(width);
        if (value.states.risk.score >= 70) highRisk.push({ ticker, horizon, price, risk: value.states.risk.score, components: value.debug.riskComponents, market: value.debug.marketModifiers, profile: value.debug.effectiveProfileModifiers });
        if (Math.abs(value.states.exhaustion.score) >= 50) highExhaustion.push({ ticker, horizon, price, exhaustion: value.states.exhaustion.score, action: value.action, components: value.debug.exhaustionComponents, direction: value.states.direction.score, priceOpportunity: value.states.priceOpportunity.score });
      }
    });
    perTicker[ticker] = { status: "available", price, horizons };
    if (onWatchlist) valid.push({ ticker, quote, price, features, decision });
  }
  const perturbation = Object.fromEntries(HORIZONS.map((horizon) => [horizon, { tests: 0, flips: 0, flipRatePct: null }]));
  const kinds = ["price", "rsi", "macd", "atr", "rs"];
  for (const item of valid) {
    for (const horizon of HORIZONS) {
      for (const kind of kinds) {
        decisionEngine.stability.clear();
        const baseDecision = decisionFor(item.ticker, item.quote, market, item.features, item.price);
        const movedPrice = kind === "price" ? item.price * 1.005 : item.price;
        const moved = decisionFor(item.ticker, item.quote, market, nudge(item.features, horizon, kind), movedPrice);
        perturbation[horizon].tests += 1;
        if (baseDecision.horizons[horizon].action !== moved.horizons[horizon].action) perturbation[horizon].flips += 1;
      }
    }
  }
  Object.values(perturbation).forEach((entry) => { entry.flipRatePct = entry.tests ? round(entry.flips / entry.tests * 100) : null; });
  const marketAudit = valid.flatMap((item) => HORIZONS.map((horizon) => {
    const value = item.decision.horizons[horizon];
    return { ticker: item.ticker, horizon, edgeBeforeMarket: value.debug.edgeBeforeMarket ?? null, edgeAfterMarket: value.debug.edgeAfterMarket ?? value.debug.adjustedEdge, difference: value.debug.edgeBeforeMarket == null ? null : round((value.debug.edgeAfterMarket ?? value.debug.adjustedEdge) - value.debug.edgeBeforeMarket), marketRiskAdd: value.debug.marketModifiers?.riskAdd, regime: value.market.regime };
  }));
  const marketImpactDistribution = Object.fromEntries(HORIZONS.map((horizon) => {
    const values = marketAudit.filter((item) => item.horizon === horizon);
    return [horizon, { edgeDifference: distribution(values.map((item) => item.difference)), riskAdd: distribution(values.map((item) => item.marketRiskAdd)) }];
  }));
  const summary = Object.fromEntries(HORIZONS.map((horizon) => [horizon, Object.fromEntries(Object.entries(stateValues[horizon]).map(([key, values]) => [key, distribution(values)]))]));
  const requestedTickers = Object.fromEntries(requestedSix.filter((ticker) => perTicker[ticker]).map((ticker) => [ticker, perTicker[ticker]]));
  const tagAudit = Object.fromEntries(["META", "MSFT", "NVDA", "AMZN", "GOOGL"].filter((ticker) => perTicker[ticker]?.status === "available").map((ticker) => {
    const value = perTicker[ticker].horizons.short;
    return [ticker, { appliedTraits: value.appliedTraits, effectiveProfileModifiers: value.effectiveProfileModifiers }];
  }));
  const companyCoverage = tickers.map((ticker) => {
    const profile = profiles.profileFor(ticker);
    return profile.isETF
      ? { ticker, type: "ETF", primaryClassification: null, traitsCount: 0, lifecycle: null, leveraged: profile.leveraged, direction: profile.direction, underlying: profile.underlying }
      : { ticker, type: "stock", primaryClassification: profile.primaryClassification, traitsCount: profile.companyTraits.length, lifecycle: profile.lifecycle };
  });
  const etfAudit = etfTickers.map((ticker) => {
    const profile = profiles.profileFor(ticker);
    const record = perTicker[ticker];
    return { ticker, leveraged: profile.leveraged, direction: profile.direction, underlying: profile.underlying, status: record?.status || "unavailable", horizons: record?.horizons || null };
  });
  const priceLandscapeAudit = Object.fromEntries(priceLandscapeTickers.filter((ticker) => perTicker[ticker]).map((ticker) => [ticker, perTicker[ticker]]));
  const violationRules = ["positiveActionOutsideOpportunity", "trimSellOutsideReduceWithoutBreakdown", "nearOpportunityNonHold", "nearReduceNonHold", "neutralNonHold", "opportunityNegativeAction", "reduceHoldOrPositiveAction", "breakdownSellWithoutExecutableReanchor", "overlap", "invertedRange", "invalidRange", "hysteresisFamilyViolation", "priceStateActionMismatch"];
  const landscapeViolationCounts = Object.fromEntries(violationRules.map((rule) => [rule, landscapeViolationRows.filter((entry) => entry.rule === rule).length]));
  console.log(JSON.stringify({
    generatedAt: new Date().toISOString(), cacheOnly: true, watchlistTickers: tickers, validTickerCount: valid.length,
    unavailableTickerCount: tickers.length - valid.length, actionDistribution, priceStateDistribution, distributions: summary,
    riskAtLeast70: highRisk, exhaustionAbsoluteAtLeast50: highExhaustion,
    perturbation, marketAudit, marketImpactDistribution, tagAudit, companyCoverage, etfAudit, priceLandscapeAudit,
    refreshContractAudit: { statelessRecomputationMismatchCount: statelessRecomputationMismatches.length, mismatches: statelessRecomputationMismatches },
    landscapeViolationAudit: { counts: landscapeViolationCounts, violations: landscapeViolationRows }, requestedTickers, perTicker,
  }, null, 2));
}

main().catch((error) => { console.error(error.stack || error.message); process.exitCode = 1; });
