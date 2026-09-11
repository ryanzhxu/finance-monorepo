import test from 'node:test'
import assert from 'node:assert/strict'
import { buildConsolidatedDecision, composeHorizon, fundamentalStance } from '../src/consolidated/final-decision.js'

const technical = (action) => ({ available: true, action, confidence: 70, price_state: 'IN_OPPORTUNITY_ZONE' })
const PASS = { status: 'pass', lagging: [], benchmarks: [], earnings_guard: { status: 'clear' } }
const FAIL = { status: 'fail', lagging: ['QQQ', 'SMH'], benchmarks: [], earnings_guard: { status: 'clear' } }
const WEAK = { stance: 'weak' }
const SUPPORTIVE = { stance: 'supportive' }

test('weak fundamentals step a mid or long buy down exactly one step', () => {
  assert.equal(composeHorizon('mid', technical('strong_buy'), WEAK, PASS).final_action, 'buy')
  assert.equal(composeHorizon('long', technical('buy'), WEAK, PASS).final_action, 'accumulate')
  const blocked = composeHorizon('mid', technical('accumulate'), WEAK, PASS)
  assert.equal(blocked.final_action, 'hold')
  assert.deepEqual(blocked.adjustments.map((item) => item.reason), ['fundamentals_weak'])
})

test('fundamentals never touch the short horizon', () => {
  const result = composeHorizon('short', technical('buy'), WEAK, PASS)
  assert.equal(result.final_action, 'buy')
  assert.equal(result.fundamentals.applied, false)
  assert.equal(result.fundamentals.stance, 'weak')
})

test('fundamentals can neither create a buy nor a sell', () => {
  assert.equal(composeHorizon('long', technical('hold'), SUPPORTIVE, PASS).final_action, 'hold')
  assert.equal(composeHorizon('long', technical('sell'), WEAK, PASS).final_action, 'sell')
  assert.equal(composeHorizon('long', technical('buy'), SUPPORTIVE, PASS).final_action, 'buy')
})

test('a buy that fails the index hurdle is capped at hold and names the benchmarks', () => {
  const result = composeHorizon('short', technical('strong_buy'), SUPPORTIVE, FAIL)
  assert.equal(result.final_action, 'hold')
  assert.equal(result.technical.action, 'strong_buy')
  assert.deepEqual(result.adjustments, [
    { layer: 'index_hurdle', from: 'strong_buy', to: 'hold', reason: 'index_hurdle_failed', detail: 'does not beat QQQ, SMH' },
  ])
})

test('the hurdle never changes a non-buy action', () => {
  for (const action of ['hold', 'trim', 'sell', 'avoid']) {
    assert.equal(composeHorizon('mid', technical(action), SUPPORTIVE, FAIL).final_action, action)
  }
})

test('both layers apply in order: fundamentals first, then the hurdle', () => {
  const result = composeHorizon('long', technical('strong_buy'), WEAK, FAIL)
  assert.equal(result.final_action, 'hold')
  assert.deepEqual(result.adjustments.map((item) => [item.layer, item.from, item.to]), [
    ['fundamentals', 'strong_buy', 'buy'],
    ['index_hurdle', 'buy', 'hold'],
  ])
})

test('a missing hurdle fails closed, and a not-applicable one lets the buy through', () => {
  const missing = composeHorizon('mid', technical('buy'), SUPPORTIVE, null)
  assert.equal(missing.final_action, 'hold')
  assert.equal(missing.adjustments[0].reason, 'index_hurdle_unavailable')
  assert.equal(composeHorizon('mid', technical('buy'), SUPPORTIVE, { status: 'not_applicable' }).final_action, 'buy')
})

test('an unavailable technical horizon has no final action rather than a fake one', () => {
  const result = composeHorizon('short', { available: false, action: null }, SUPPORTIVE, PASS)
  assert.equal(result.final_action, null)
  assert.equal(result.adjustments[0].reason, 'technical_unavailable')
})

test('fundamental stance needs at least two signals and follows the weighted vote', () => {
  assert.equal(fundamentalStance([{ signal: 'SELL', weight: 2 }]).stance, 'unavailable')
  assert.equal(fundamentalStance([{ signal: 'SELL', weight: 2 }, { signal: 'BUY', weight: 1.5 }]).stance, 'weak')
  assert.equal(fundamentalStance([{ signal: 'BUY', weight: 1 }, { signal: 'HOLD', weight: 1 }]).stance, 'supportive')
  assert.equal(fundamentalStance([{ signal: 'HOLD', weight: 2 }, { signal: 'BUY', weight: 1 }]).stance, 'neutral')
})

test('the consolidated decision keeps three independent horizons', () => {
  const decision = buildConsolidatedDecision({
    technical: {
      producer: 'vincent-stock-decision-dashboard',
      currentPrice: 10,
      horizons: { short: technical('buy'), mid: technical('hold'), long: technical('accumulate') },
      dataQuality: { four_hour: 'available' },
    },
    fundamentals: SUPPORTIVE,
    hurdle: PASS,
  })
  assert.equal(decision.version, 'consolidated.v1')
  assert.deepEqual(Object.keys(decision.horizons), ['short', 'mid', 'long'])
  assert.deepEqual(
    Object.values(decision.horizons).map((item) => item.final_action),
    ['buy', 'hold', 'accumulate'],
  )
})
