import test from 'node:test'
import assert from 'node:assert/strict'
import { __testOnly } from '../src/index.js'

const { normalizeSymbol } = __testOnly

test('class-share dots become dashes', () => {
  assert.equal(normalizeSymbol('brk.b'), 'BRK-B')
  assert.equal(normalizeSymbol('BF.B'), 'BF-B')
})

test('exchange suffix dots survive so finance-query.com and Yahoo get the dotted symbol', () => {
  assert.equal(normalizeSymbol('0700.hk'), '0700.HK')
  assert.equal(normalizeSymbol('9988.HK'), '9988.HK')
  assert.equal(normalizeSymbol('600519.ss'), '600519.SS')
  assert.equal(normalizeSymbol('000001.sz'), '000001.SZ')
  assert.equal(normalizeSymbol('7203.t'), '7203.T')
  assert.equal(normalizeSymbol('shop.to'), 'SHOP.TO')
  assert.equal(normalizeSymbol('bp.l'), 'BP.L')
  assert.equal(normalizeSymbol('005930.ks'), '005930.KS')
})

test('plain symbols and whitespace are untouched beyond trim/uppercase', () => {
  assert.equal(normalizeSymbol('  aapl  '), 'AAPL')
  assert.equal(normalizeSymbol('spy'), 'SPY')
  assert.equal(normalizeSymbol(''), '')
  assert.equal(normalizeSymbol(null), '')
})
