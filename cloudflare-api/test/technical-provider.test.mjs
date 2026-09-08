import test from 'node:test'
import assert from 'node:assert/strict'
import {
  ACTION_TO_DIRECTION,
  EXTERNAL_TECHNICAL_WEIGHT,
  LEGAL_ACTIONS,
  SHORT_MID_LONG_HORIZONS,
  TechnicalVerdictError,
  resolveTechnicalVerdict,
  resolveTechnicalVerdictsByHorizon,
  substituteTechnicalSignals,
  verdictFromExternal,
  verdictFromLocal,
} from '../src/technical-provider.js'

// These tests mirror analyst_service/tests/test_technical_provider.py. The two
// implementations must agree, or the Worker and the Python service will give
// different answers for the same decision.v1 payload.

const payload = (overrides = {}) => ({
  contractVersion: 'decision.v1',
  producer: 'vincent-stock-decision-dashboard',
  action: 'buy',
  confidence: 70,
  priceState: 'IN_OPPORTUNITY_ZONE',
  opportunityRange: { low: 100, high: 110 },
  reduceRange: { low: 140, high: 150 },
  invalidation: 95,
  reasons: ['Weekly trend intact'],
  dataQuality: 88,
  ...overrides,
})

const landscapeFree = (overrides = {}) => {
  const base = payload(overrides)
  delete base.priceState
  delete base.opportunityRange
  delete base.reduceRange
  return base
}

const localTechnicals = () => [
  { dimension: 'RSI_14', signal: 'BUY', weight: 1.0, note: 'oversold' },
  { dimension: 'MACD', signal: 'BUY', weight: 1.0, note: 'histogram positive' },
  { dimension: 'MA_50_200', signal: 'BUY', weight: 1.5, note: 'golden cross' },
]

const nonTechnicals = () => [
  { dimension: 'PE_Percentile', signal: 'HOLD', weight: 1.0, note: 'mid range' },
  { dimension: 'News_Sentiment', signal: 'HOLD', weight: 0.5, note: 'neutral' },
]

test('every decision.v1 action maps to a direction', () => {
  const expected = {
    strong_buy: 'BUY',
    buy: 'BUY',
    accumulate: 'BUY',
    hold: 'HOLD',
    trim: 'SELL',
    sell: 'SELL',
    avoid: 'SELL',
  }
  for (const [action, direction] of Object.entries(expected)) {
    assert.equal(verdictFromExternal(landscapeFree({ action })).direction, direction)
  }
  // The map must stay exhaustive over the contract vocabulary.
  assert.deepEqual(Object.keys(ACTION_TO_DIRECTION).sort(), Object.keys(expected).sort())
})

test('an unknown action is rejected, not defaulted to HOLD', () => {
  assert.throws(() => verdictFromExternal(payload({ action: 'moon' })), TechnicalVerdictError)
})

test('a missing action is rejected', () => {
  const body = payload()
  delete body.action
  assert.throws(() => verdictFromExternal(body), TechnicalVerdictError)
})

test('confidence rescales from 0-100 to 0.0-1.0', () => {
  // The exact trap logged as open question 16 on consolidation/decision-v1.
  assert.equal(verdictFromExternal(landscapeFree({ confidence: 70 })).confidence, 0.7)
  assert.equal(verdictFromExternal(landscapeFree({ confidence: 0 })).confidence, 0)
  assert.equal(verdictFromExternal(landscapeFree({ confidence: 100 })).confidence, 1)
})

test('confidence outside the contract range is rejected', () => {
  assert.throws(() => verdictFromExternal(payload({ confidence: 101 })), TechnicalVerdictError)
  assert.throws(() => verdictFromExternal(payload({ confidence: -1 })), TechnicalVerdictError)
})

test('data quality outside the contract range is rejected', () => {
  assert.throws(() => verdictFromExternal(payload({ dataQuality: 101 })), TechnicalVerdictError)
  assert.throws(() => verdictFromExternal(payload({ dataQuality: -1 })), TechnicalVerdictError)
})

test('the legality table matches the decision.v1 contract exactly', () => {
  assert.deepEqual(LEGAL_ACTIONS.IN_OPPORTUNITY_ZONE, ['strong_buy', 'buy', 'accumulate'])
  assert.deepEqual(LEGAL_ACTIONS.IN_REDUCE_ZONE, ['trim', 'sell'])
  assert.deepEqual(LEGAL_ACTIONS.BREAKDOWN_ZONE, ['sell', 'avoid'])
  assert.deepEqual(LEGAL_ACTIONS.INVALID_LANDSCAPE, ['hold', 'avoid'])
})

test('an action illegal for its price state is rejected', () => {
  assert.throws(() => verdictFromExternal(payload({ action: 'buy', priceState: 'IN_REDUCE_ZONE' })), TechnicalVerdictError)
})

test('a legal action for its price state is accepted', () => {
  const verdict = verdictFromExternal(payload({ action: 'trim', priceState: 'IN_REDUCE_ZONE' }))
  assert.equal(verdict.direction, 'SELL')
})

test('overlapping opportunity and reduce zones are rejected', () => {
  assert.throws(
    () =>
      verdictFromExternal(
        payload({ opportunityRange: { low: 100, high: 150 }, reduceRange: { low: 140, high: 160 } }),
      ),
    TechnicalVerdictError,
  )
})

test('missing optional landscape stays null rather than zero', () => {
  const verdict = verdictFromExternal(landscapeFree({ invalidation: undefined, dataQuality: undefined }))
  assert.equal(verdict.price_state, null)
  assert.equal(verdict.opportunity_range, null)
  assert.equal(verdict.reduce_range, null)
  assert.equal(verdict.invalidation, null)
  assert.equal(verdict.data_quality, null)
})

test('local verdict summarizes the local technical signals', () => {
  const verdict = verdictFromLocal(localTechnicals())
  assert.equal(verdict.direction, 'BUY')
  assert.equal(verdict.source, 'local')
})

test('local verdict is null when no technical signal exists', () => {
  assert.equal(verdictFromLocal(nonTechnicals()), null)
})

test('substitution replaces the local technicals and reports what it displaced', () => {
  const verdict = verdictFromExternal(payload({ action: 'sell', priceState: 'BREAKDOWN_ZONE' }))
  const { signals, displaced } = substituteTechnicalSignals([...localTechnicals(), ...nonTechnicals()], verdict)

  const technical = signals.filter((signal) => signal.dimension === 'Technical_External')
  assert.equal(technical.length, 1)
  assert.equal(technical[0].signal, 'SELL')
  assert.equal(technical[0].weight, EXTERNAL_TECHNICAL_WEIGHT)
  // No local technical dimension survives into the voting set.
  assert.equal(signals.filter((signal) => signal.dimension === 'RSI_14').length, 0)
  // The displaced local opinion is still available for comparison.
  assert.equal(displaced.direction, 'BUY')
})

test('the external weight equals the local technical block total', () => {
  // RSI_14 1.0 + MACD 1.0 + Bollinger_Bands 0.8 + Volume 1.0
  // + MA_50_200 1.5 + RSI_Weekly 1.5 + Support_Resistance 0.8
  assert.equal(EXTERNAL_TECHNICAL_WEIGHT, 7.6)
})

test('resolve degrades to local with a visible flag on a contract violation', () => {
  const { verdict, riskFlags } = resolveTechnicalVerdict(payload({ action: 'buy', priceState: 'IN_REDUCE_ZONE' }))
  assert.equal(verdict, null)
  assert.deepEqual(riskFlags, ['external_technical_rejected'])
})

test('resolve returns nothing and no flags when no verdict is supplied', () => {
  const { verdict, riskFlags } = resolveTechnicalVerdict(null)
  assert.equal(verdict, null)
  assert.deepEqual(riskFlags, [])
})

// --- per-horizon verdicts ----------------------------------------------------

test('resolve by horizon carries each horizon independently', () => {
  const payloads = {
    '1W': payload({ action: 'buy', confidence: 60 }),
    '2-4W': payload({ action: 'hold', priceState: 'NEUTRAL_ZONE', confidence: 50 }),
    '3-6M': payload({ action: 'sell', priceState: 'BREAKDOWN_ZONE', confidence: 80 }),
  }

  const resolved = resolveTechnicalVerdictsByHorizon(payloads)

  const byHorizon = Object.fromEntries(resolved.map((entry) => [entry.horizon, entry.verdict]))
  assert.deepEqual(Object.keys(byHorizon).sort(), Object.keys(payloads).sort())
  assert.equal(byHorizon['1W'].direction, 'BUY')
  assert.equal(byHorizon['2-4W'].direction, 'HOLD')
  assert.equal(byHorizon['3-6M'].direction, 'SELL')
  // None of the three moves toward a shared average.
  assert.equal(byHorizon['1W'].confidence, 0.6)
  assert.equal(byHorizon['3-6M'].confidence, 0.8)
})

test('resolve by horizon omits a horizon missing from the batch', () => {
  const payloads = { '1W': payload() }

  const resolved = resolveTechnicalVerdictsByHorizon(payloads)

  assert.deepEqual(resolved.map((entry) => entry.horizon), ['1W'])
})

test('resolve by horizon drops an invalid payload rather than failing the batch', () => {
  const payloads = {
    '1W': payload({ action: 'buy' }),
    // SELL is illegal in an opportunity zone: this horizon must be dropped,
    // not defaulted, and must not take the other horizons down with it.
    '2-4W': payload({ action: 'sell' }),
    '3-6M': payload({ action: 'sell', priceState: 'BREAKDOWN_ZONE' }),
  }

  const resolved = resolveTechnicalVerdictsByHorizon(payloads)

  assert.deepEqual(new Set(resolved.map((entry) => entry.horizon)), new Set(['1W', '3-6M']))
})

test('SHORT_MID_LONG_HORIZONS excludes 1D, Ryan\'s day-trade horizon', () => {
  assert.deepEqual(SHORT_MID_LONG_HORIZONS, ['1W', '2-4W', '3-6M'])
})
