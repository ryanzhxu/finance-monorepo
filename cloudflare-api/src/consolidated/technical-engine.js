// Vincent's decision engine, run in process.
//
// The modules below are technical_engine/'s production engine, imported for
// their side effects: each attaches its API to globalThis (DecisionEngine,
// CanonicalTechnicalFeatures, ProfileDefinitions, DecisionFeatureInputs), the
// same way his Dashboard loads them. Nothing in this file scores, thresholds,
// or computes a price level. That stays inside his engine
// (technical_engine/AGENTS.md). This file only feeds inputs and reshapes output.

import '../../../technical_engine/technical-features.js'
import '../../../technical_engine/profile-definitions.js'
import '../../../technical_engine/decision-engine/feature-inputs.js'
import '../../../technical_engine/decision-engine/config.js'
import '../../../technical_engine/decision-engine/technical-engine.js'
import '../../../technical_engine/decision-engine/exhaustion-engine.js'
import '../../../technical_engine/decision-engine/market-engine.js'
import '../../../technical_engine/decision-engine/etf-profile.js'
import '../../../technical_engine/decision-engine/company-profile.js'
import '../../../technical_engine/decision-engine/execution-engine.js'
import '../../../technical_engine/decision-engine/confidence-engine.js'
import '../../../technical_engine/decision-engine/stability-engine.js'
import '../../../technical_engine/decision-engine/decision-engine.js'

import { loadMarketContext, loadQuoteInputs } from './market-data.js'

export const CONTRACT_VERSION = 'decision.v1'
export const PRODUCER = 'vincent-stock-decision-dashboard'
export const HORIZONS = ['short', 'mid', 'long']
// The analyst side of this Worker keys horizons by its own enum.
export const HORIZON_TO_ANALYST = { short: '1W', mid: '2-4W', long: '3-6M' }

const finite = (value) =>
  value == null || value === '' ? null : Number.isFinite(Number(value)) ? Number(value) : null

function band(range) {
  const low = finite(range?.low)
  const high = finite(range?.high)
  return low != null && high != null ? { low, high } : null
}

export function classificationFor(ticker, metadata = {}) {
  return globalThis.ProfileDefinitions.profileFor(ticker, metadata)
}

// Returns both the decision and the canonical technical features it decided
// from, so a caller can show the underlying indicators without asking the
// engine to compute them a second time.
//
// Leveraged and inverse ETFs (profile-definitions.js `underlyingTicker`) feed
// his engine their underlying's technical features and price too, the same
// way his dashboard's applySnapshot does (technical_engine/main.js) — never a
// second decision, just the extra input his engine already knows how to use.
export async function decideTechnical({ ticker, quote, market, fetchImpl = fetch }) {
  const inputs = globalThis.DecisionFeatureInputs
  const technicalFeatures = globalThis.CanonicalTechnicalFeatures.buildTechnicalFeatures(inputs.featureInputs(quote, market))
  const classification = classificationFor(ticker, quote.metadata || quote)
  let underlyingTechnicalFeatures = null
  let underlyingPrice = null
  const underlyingTicker = classification.isETF ? classification.underlyingTicker : null
  if (underlyingTicker && underlyingTicker !== ticker) {
    const underlyingQuote = await loadQuoteInputs(underlyingTicker, { fetchImpl }).catch(() => null)
    if (underlyingQuote) {
      underlyingTechnicalFeatures = globalThis.CanonicalTechnicalFeatures.buildTechnicalFeatures(inputs.featureInputs(underlyingQuote, market))
      underlyingPrice = finite(underlyingQuote.price)
    }
  }
  const decision = globalThis.DecisionEngine.decide({
    ticker,
    price: finite(quote.price),
    technicalFeatures,
    marketContext: market,
    classification,
    metadata: quote.metadata || {},
    language: 'en',
    underlyingTechnicalFeatures,
    underlyingPrice,
  })
  return { decision, technicalFeatures }
}

// This Worker's horizon keys (short/mid/long) vs. the canonical feature
// layer's own keys (short/medium/long).
const FEATURE_HORIZON = { short: 'short', mid: 'medium', long: 'long' }
const DETAILS_PRIMARY_INTERVAL = { short: '4h', mid: '1d', long: '1w' }

function pickPrimary(group, primaryInterval) {
  const entries = Object.values(group || {})
  return entries.find((feature) => feature?.interval === primaryInterval) || entries[0] || null
}

function compactIndicator(feature, keys) {
  if (!feature || feature.available === false) return { available: false }
  const picked = { available: true }
  for (const key of keys) picked[key] = feature[key] ?? null
  return picked
}

// A compact, read-only subset of Vincent's canonical technical features for
// one horizon: enough for a UI "technical details" section, without a second
// computation and without his engine's full derivation metadata.
export function technicalDetails(technicalFeatures, horizon) {
  const set = technicalFeatures?.horizons?.[FEATURE_HORIZON[horizon]]
  if (!set) return null
  const primaryInterval = DETAILS_PRIMARY_INTERVAL[horizon]
  const rs = set.relative_strength || null
  const fib = set.fibonacci || null
  return {
    moving_averages: {
      alignment: set.trend?.ma_structure?.alignment ?? 'unavailable',
      compression_state: set.trend?.ma_structure?.compression_state ?? 'unavailable',
    },
    rsi: compactIndicator(pickPrimary(set.momentum?.rsi, primaryInterval), ['value', 'state']),
    macd: compactIndicator(pickPrimary(set.momentum?.macd, primaryInterval), ['macd_line', 'signal_line', 'histogram', 'crossover_state', 'state']),
    kdj: compactIndicator(pickPrimary(set.momentum?.kdj, primaryInterval), ['k', 'd', 'j', 'crossover_state']),
    adx: compactIndicator(pickPrimary(set.trend?.adx, primaryInterval), ['adx', 'plus_di', 'minus_di', 'trend_strength', 'directional_bias']),
    atr: compactIndicator(pickPrimary(set.volatility?.atr, primaryInterval), ['value', 'atr_pct', 'volatility_regime']),
    bollinger: compactIndicator(pickPrimary(set.volatility?.bollinger, primaryInterval), ['upper_band', 'middle_band', 'lower_band', 'price_position', 'squeeze_state']),
    obv: compactIndicator(pickPrimary(set.participation?.obv, primaryInterval), ['trend', 'divergence']),
    relative_strength: rs ? { state: rs.state ?? 'unavailable', vs_spy: rs.primary?.vs_spy ?? null, vs_qqq: rs.primary?.vs_qqq ?? null } : null,
    fibonacci: fib
      ? {
          availability: fib.availability ?? 'unavailable',
          direction: fib.direction ?? null,
          fib_zone: fib.fib_zone ?? 'unavailable',
          nearest_fib_level: fib.nearest_fib_level ?? null,
          distance_to_nearest_fib_pct: fib.distance_to_nearest_fib_pct ?? null,
        }
      : null,
  }
}

// Symbol-level context that does not vary by horizon: relative volume and the
// 52-week structure.
export function marketStructureDetails(technicalFeatures) {
  const volume = technicalFeatures?.volume
  const pricePosition = technicalFeatures?.price_position
  return {
    relative_volume:
      volume?.availability === 'available'
        ? { state: volume.relative_volume?.state ?? 'unavailable', displayed_rvol: volume.relative_volume?.displayed_rvol ?? null }
        : { state: 'unavailable', displayed_rvol: null },
    fifty_two_week:
      pricePosition && pricePosition.availability && pricePosition.availability !== 'unavailable'
        ? {
            high: finite(pricePosition.high_52w),
            low: finite(pricePosition.low_52w),
            position_pct: finite(pricePosition.position_52w_pct),
            distance_to_high_pct: finite(pricePosition.distance_to_52w_high_pct),
            distance_to_low_pct: finite(pricePosition.distance_to_52w_low_pct),
          }
        : null,
  }
}

// One horizon, in this Worker's snake_case vocabulary. An unusable landscape
// emits null bands on purpose rather than a fake range.
export function horizonSummary(decision, horizon, currentPrice = null, details = null) {
  const value = decision?.horizons?.[horizon]
  if (!value) {
    return {
      available: false,
      action: null,
      confidence: null,
      price_state: 'INVALID_LANDSCAPE',
      execution_intent: null,
      opportunity_range: null,
      reduce_range: null,
      invalidation: null,
      current_price: finite(currentPrice),
      reasons: ['Horizon unavailable'],
      data_quality: null,
      technical_details: details,
    }
  }
  const landscape = value.priceLandscape || {}
  const priceState = value.debug?.priceState || 'INVALID_LANDSCAPE'
  const usable = priceState !== 'INVALID_LANDSCAPE'
  return {
    available: true,
    action: value.action,
    confidence: finite(value.confidence),
    price_state: priceState,
    execution_intent: value.executionIntent || null,
    opportunity_range: usable ? band(landscape.opportunityRange) : null,
    reduce_range: usable ? band(landscape.reduceRange) : null,
    invalidation: usable ? finite(landscape.invalidation) : null,
    current_price: finite(landscape.currentPrice ?? currentPrice),
    reasons: (value.reasons?.supporting || []).slice(0, 5),
    data_quality: finite(value.debug?.dataQuality?.score),
    technical_details: details,
  }
}

// The flattened decision.v1 object the decision-v1 Worker used to serve, so the
// existing validation seam (technical-provider.js) trusts it no more than a
// verdict pulled over the network.
export function toDecisionV1(summary, { ticker, horizon, generatedAt }) {
  return {
    contractVersion: CONTRACT_VERSION,
    producer: PRODUCER,
    ticker,
    horizon,
    generatedAt,
    action: summary.action ?? 'avoid',
    confidence: summary.confidence ?? 0,
    priceState: summary.price_state,
    executionIntent: summary.execution_intent ?? 'avoid',
    opportunityRange: summary.opportunity_range,
    reduceRange: summary.reduce_range,
    invalidation: summary.invalidation,
    currentPrice: summary.current_price,
    reasons: summary.reasons,
    dataQuality: summary.data_quality,
  }
}

export async function runTechnicalEngine(symbol, { fetchImpl = fetch, metadata = {} } = {}) {
  const [quote, market] = await Promise.all([
    loadQuoteInputs(symbol, { fetchImpl, metadata }),
    loadMarketContext({ fetchImpl }),
  ])
  const { decision, technicalFeatures } = await decideTechnical({ ticker: symbol, quote, market, fetchImpl })
  const generatedAt = new Date().toISOString()
  const horizons = Object.fromEntries(
    HORIZONS.map((horizon) => [horizon, horizonSummary(decision, horizon, quote.price, technicalDetails(technicalFeatures, horizon))]),
  )
  const decisionV1 = Object.fromEntries(
    HORIZONS.filter((horizon) => horizons[horizon].available).map((horizon) => [
      HORIZON_TO_ANALYST[horizon],
      toDecisionV1(horizons[horizon], { ticker: symbol, horizon, generatedAt }),
    ]),
  )
  const marketQuality = globalThis.DecisionEngine.market.evaluate(market, {}).dataQuality
  return {
    producer: PRODUCER,
    generatedAt,
    currentPrice: finite(quote.price),
    classification: classificationFor(symbol, quote.metadata || {}),
    horizons,
    decisionV1,
    dataQuality: { ...quote.dataQuality, market: marketQuality },
    marketStructure: marketStructureDetails(technicalFeatures),
  }
}
