import test from 'node:test'
import assert from 'node:assert/strict'
import { atr, clamp, ema, macd, mean, pctChange, rsi, sma, stdev } from '../src/indicators.js'

test('clamp keeps values inside bounds', () => {
  assert.equal(clamp(5, 0, 10), 5)
  assert.equal(clamp(-1, 0, 10), 0)
  assert.equal(clamp(25, 0, 10), 10)
})

test('mean, sma, and stdev work on simple samples', () => {
  const values = [1, 2, 3, 4, 5]
  assert.equal(mean(values), 3)
  assert.equal(sma(values, 3), 4)
  assert.ok(Math.abs(stdev(values) - 1.5811) < 0.0005)
})

test('pctChange and ema return expected values', () => {
  assert.equal(pctChange(110, 100), 10)
  assert.equal(Math.round(ema([1, 2, 3, 4, 5], 3) * 100) / 100, 4.06)
})

test('rsi and macd produce finite signals for an upward series', () => {
  const closes = Array.from({ length: 60 }, (_, index) => 100 + index)
  const highs = closes.map((value) => value + 1)
  const lows = closes.map((value) => value - 1)
  assert.ok(rsi(closes, 14) > 70)
  assert.ok(macd(closes).histogram > 0)
  assert.ok(atr(highs, lows, closes, 14) > 0)
})
