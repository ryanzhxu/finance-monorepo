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

export function decideTechnical({ ticker, quote, market }) {
  const inputs = globalThis.DecisionFeatureInputs
  return globalThis.DecisionEngine.decide({
    ticker,
    price: finite(quote.price),
    technicalFeatures: globalThis.CanonicalTechnicalFeatures.buildTechnicalFeatures(inputs.featureInputs(quote, market)),
    marketContext: market,
    classification: classificationFor(ticker, quote.metadata || quote),
    metadata: quote.metadata || {},
    language: 'en',
    underlyingTechnicalFeatures: null,
    underlyingPrice: null,
  })
}

// One horizon, in this Worker's snake_case vocabulary. An unusable landscape
// emits null bands on purpose rather than a fake range.
export function horizonSummary(decision, horizon, currentPrice = null) {
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
  const decision = decideTechnical({ ticker: symbol, quote, market })
  const generatedAt = new Date().toISOString()
  const horizons = Object.fromEntries(HORIZONS.map((horizon) => [horizon, horizonSummary(decision, horizon, quote.price)]))
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
  }
}
