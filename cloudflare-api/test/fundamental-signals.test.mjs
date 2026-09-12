import test from 'node:test'
import assert from 'node:assert/strict'
import { __testOnly } from '../src/index.js'

const { buildFundamentalSignals } = __testOnly

const byDimension = (signals) => Object.fromEntries(signals.map((item) => [item.dimension, item]))

test('EPS surprise, PE percentile and analyst revisions vote with the Python thresholds', () => {
  const signals = byDimension(
    buildFundamentalSignals({ eps_surprise_pct: 6.2, pe_percentile_5y: 35, analyst_upgrades_30d: 0, analyst_downgrades_30d: 2 }),
  )
  assert.equal(signals.EPS_Surprise.signal, 'BUY')
  assert.equal(signals.EPS_Surprise.weight, 2.0)
  assert.equal(signals.PE_Percentile.signal, 'BUY')
  assert.equal(signals.Analyst_Ratings.signal, 'SELL')
  assert.equal(signals.Analyst_Ratings.weight, 1.5)
})

test('threshold edges match signals.py: eps >= 5 buys, pe > 70 sells, pe of exactly 40 or 70 holds', () => {
  const at = (fundamentals) => byDimension(buildFundamentalSignals(fundamentals))
  assert.equal(at({ eps_surprise_pct: 5 }).EPS_Surprise.signal, 'BUY')
  assert.equal(at({ eps_surprise_pct: -5 }).EPS_Surprise.signal, 'SELL')
  assert.equal(at({ eps_surprise_pct: 4.9 }).EPS_Surprise.signal, 'HOLD')
  assert.equal(at({ pe_percentile_5y: 40 }).PE_Percentile.signal, 'HOLD')
  assert.equal(at({ pe_percentile_5y: 70 }).PE_Percentile.signal, 'HOLD')
  assert.equal(at({ pe_percentile_5y: 70.1 }).PE_Percentile.signal, 'SELL')
  assert.equal(at({ analyst_upgrades_30d: 1, analyst_downgrades_30d: 1 }).Analyst_Ratings.signal, 'HOLD')
})

test('a fundamental with no data does not vote at all', () => {
  assert.deepEqual(buildFundamentalSignals({ eps_surprise_pct: null, pe_percentile_5y: null, analyst_upgrades_30d: null }), [])
  // One side of the analyst pair missing is no revision count.
  assert.deepEqual(buildFundamentalSignals({ analyst_upgrades_30d: 3, analyst_downgrades_30d: null }), [])
})
