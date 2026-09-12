import test from 'node:test'
import assert from 'node:assert/strict'
import { composeHorizonSummary } from '../src/horizonSummary.ts'

const technical = (overrides = {}) => ({
  available: true,
  action: 'accumulate',
  confidence: 70,
  price_state: 'IN_OPPORTUNITY_ZONE',
  execution_intent: null,
  opportunity_range: null,
  reduce_range: null,
  invalidation: null,
  current_price: 100,
  reasons: [],
  data_quality: 90,
  technical_details: null,
  ...overrides,
})

const horizon = (overrides = {}) => ({
  technical: technical(),
  fundamentals: { stance: 'supportive', applied: true },
  final_action: 'accumulate',
  adjustments: [],
  ...overrides,
})

const hurdle = (overrides = {}) => ({
  status: 'pass',
  benchmarks: [
    { symbol: 'SPY', role: 'index', label: 'SPY', rel_12_1_pct: 1, rel_6m_pct: 1, ratio_above_200d: true, evidence_true: 3, evidence_known: 3, sessions: 252, result: 'beats' },
    { symbol: 'QQQ', role: 'index', label: 'QQQ', rel_12_1_pct: 1, rel_6m_pct: 1, ratio_above_200d: true, evidence_true: 3, evidence_known: 3, sessions: 252, result: 'beats' },
  ],
  lagging: [],
  earnings_guard: { status: 'clear', eps_surprise_pct: null, analysts_deteriorating: null },
  ...overrides,
})

test('technical unavailable produces the unavailable part only', () => {
  const summary = composeHorizonSummary(horizon({ technical: technical({ available: false, action: null }), final_action: null }), null)
  assert.deepEqual(summary, { parts: [{ kind: 'unavailable' }], finalAction: null })
})

test('a passing hurdle on a buy action shows what it beats', () => {
  const summary = composeHorizonSummary(horizon(), hurdle())
  assert.deepEqual(summary.parts, [
    { kind: 'technical', action: 'accumulate', priceState: 'IN_OPPORTUNITY_ZONE' },
    { kind: 'fundamentals', stance: 'supportive' },
    { kind: 'hurdle_beats', benchmarks: ['SPY', 'QQQ'] },
  ])
  assert.equal(summary.finalAction, 'accumulate')
})

test('a failing hurdle on a buy action shows what it lags, and the held final action', () => {
  const entry = horizon({
    final_action: 'hold',
    adjustments: [{ layer: 'index_hurdle', from: 'accumulate', to: 'hold', reason: 'index_hurdle_failed', detail: 'does not beat XLK, SMH' }],
  })
  const summary = composeHorizonSummary(entry, hurdle({ status: 'fail', lagging: ['XLK', 'SMH'] }))
  assert.deepEqual(summary.parts.at(-1), { kind: 'hurdle_lags', benchmarks: ['XLK', 'SMH'] })
  assert.equal(summary.finalAction, 'hold')
})

test('a hurdle failure with no lagging benchmarks means the earnings guard fired', () => {
  const entry = horizon({
    final_action: 'hold',
    adjustments: [{ layer: 'index_hurdle', from: 'accumulate', to: 'hold', reason: 'index_hurdle_failed', detail: null }],
  })
  const summary = composeHorizonSummary(entry, hurdle({ status: 'fail', lagging: [] }))
  assert.deepEqual(summary.parts.at(-1), { kind: 'hurdle_earnings_guard' })
})

test('an unavailable hurdle is reported as such, not silently dropped', () => {
  const entry = horizon({
    final_action: 'hold',
    adjustments: [{ layer: 'index_hurdle', from: 'accumulate', to: 'hold', reason: 'index_hurdle_unavailable', detail: null }],
  })
  const summary = composeHorizonSummary(entry, null)
  assert.deepEqual(summary.parts.at(-1), { kind: 'hurdle_unavailable' })
})

test('a non-buy action never shows a hurdle clause, even when a hurdle is present', () => {
  const entry = horizon({ technical: technical({ action: 'hold' }), final_action: 'hold' })
  const summary = composeHorizonSummary(entry, hurdle())
  assert.equal(summary.parts.some((part) => part.kind.startsWith('hurdle')), false)
})

test('fundamentals not applied to this horizon is omitted', () => {
  const entry = horizon({ fundamentals: { stance: 'supportive', applied: false } })
  const summary = composeHorizonSummary(entry, hurdle())
  assert.equal(summary.parts.some((part) => part.kind === 'fundamentals'), false)
})

test('fundamentals unavailable (not enough signals) is omitted rather than shown as a stance', () => {
  const entry = horizon({ fundamentals: { stance: 'unavailable', applied: true } })
  const summary = composeHorizonSummary(entry, hurdle())
  assert.equal(summary.parts.some((part) => part.kind === 'fundamentals'), false)
})

test('a weak-fundamentals step-down uses the stepped-down action to decide whether the hurdle applies', () => {
  // accumulate -> hold via fundamentals means the hurdle should not fire at all (hold is not a buy action).
  const entry = horizon({
    final_action: 'hold',
    adjustments: [{ layer: 'fundamentals', from: 'accumulate', to: 'hold', reason: 'fundamentals_weak', detail: null }],
  })
  const summary = composeHorizonSummary(entry, hurdle())
  assert.equal(summary.parts.some((part) => part.kind.startsWith('hurdle')), false)
})

test('a passing hurdle with nothing beaten yet omits the hurdle clause rather than showing an empty list', () => {
  const summary = composeHorizonSummary(horizon(), hurdle({ benchmarks: [] }))
  assert.equal(summary.parts.some((part) => part.kind === 'hurdle_beats'), false)
})
