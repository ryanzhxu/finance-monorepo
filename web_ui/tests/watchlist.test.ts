import assert from 'node:assert/strict'
import test from 'node:test'

import {
  analyzedEntryPatch,
  refreshableSymbols,
  syncSymbols,
  updateEntry,
  withFreshness,
  type CachedAnalyzeBundle,
  type WatchlistEntry,
} from '../src/watchlist.ts'

function makeBundle(overrides?: {
  currentPrice?: number | null
  entryAssessment?: string | null
}): CachedAnalyzeBundle {
  return {
    analysis: {
      symbol: 'NVDA',
      recommendation: { direction: 'BUY' },
      confidence: 87,
      data_quality_score: 91,
      entry: {
        current_price: overrides?.currentPrice ?? 152.34,
        entry_assessment: overrides?.entryAssessment ?? 'Constructive setup',
      },
    },
    confluence: {
      classical: {
        current_price: overrides?.currentPrice ?? 152.34,
        entry_assessment: overrides?.entryAssessment ?? 'Constructive setup',
      },
    },
  } as CachedAnalyzeBundle
}

test('fresh private-tab symbols are marked refreshable after shared watchlist sync', () => {
  const entries = syncSymbols([], ['nvda', 'aapl']).map(withFreshness)

  assert.deepEqual(
    entries.map((entry) => ({ symbol: entry.symbol, freshness: entry.freshness })),
    [
      { symbol: 'NVDA', freshness: 'never' },
      { symbol: 'AAPL', freshness: 'never' },
    ],
  )
  assert.deepEqual(refreshableSymbols(entries), ['NVDA', 'AAPL'])
})

test('analyze results patch a watchlist entry with live price and timestamp', () => {
  const entries: WatchlistEntry[] = [
    {
      symbol: 'NVDA',
      direction: null,
      confidence: null,
      dataQualityScore: null,
      currentPrice: null,
      entryAssessment: null,
      lastAnalyzedAt: null,
      freshness: 'never',
      cachedBundle: null,
    },
  ]

  const bundle = makeBundle()
  const analyzedAt = '2026-06-28T12:34:56.000Z'
  const next = updateEntry(entries, 'NVDA', analyzedEntryPatch(bundle, analyzedAt))

  assert.deepEqual(next[0], {
    symbol: 'NVDA',
    direction: 'BUY',
    confidence: 87,
    dataQualityScore: 91,
    currentPrice: 152.34,
    entryAssessment: 'Constructive setup',
    lastAnalyzedAt: analyzedAt,
    freshness: 'live',
    cachedBundle: bundle,
  })
})
