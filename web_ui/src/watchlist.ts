import type { AnalysisResponse, EntryConfluenceResponse } from './api/types'

export type CachedAnalyzeBundle = {
  analysis: AnalysisResponse
  confluence: EntryConfluenceResponse
}

export type WatchlistEntry = {
  symbol: string
  direction: 'BUY' | 'HOLD' | 'SELL' | null
  confidence: number | null
  dataQualityScore: number | null
  currentPrice: number | null
  entryAssessment: string | null
  lastAnalyzedAt: string | null
  freshness: 'live' | 'stale' | 'never'
  cachedBundle: CachedAnalyzeBundle | null
}

const KEY = 'watchlist_v1'
const STALE_MS = 60 * 60 * 1000

export function loadWatchlist(): WatchlistEntry[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    if (!Array.isArray(parsed)) {
      return []
    }
    return parsed.map((entry) => ({
      ...entry,
      cachedBundle: entry?.cachedBundle ?? null,
    }))
  } catch {
    return []
  }
}

export function saveWatchlist(entries: WatchlistEntry[]): void {
  localStorage.setItem(KEY, JSON.stringify(entries))
}

export function addSymbol(entries: WatchlistEntry[], symbol: string): WatchlistEntry[] {
  const upper = symbol.trim().toUpperCase()
  if (!upper || entries.some((entry) => entry.symbol === upper)) {
    return entries
  }
  return [
    ...entries,
    {
      symbol: upper,
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
}

export function removeSymbol(entries: WatchlistEntry[], symbol: string): WatchlistEntry[] {
  return entries.filter((entry) => entry.symbol !== symbol)
}

export function isStale(entry: WatchlistEntry): boolean {
  if (!entry.lastAnalyzedAt) {
    return true
  }
  return Date.now() - new Date(entry.lastAnalyzedAt).getTime() > STALE_MS
}

export function updateEntry(
  entries: WatchlistEntry[],
  symbol: string,
  patch: Partial<WatchlistEntry>,
): WatchlistEntry[] {
  return entries.map((entry) => (entry.symbol === symbol ? { ...entry, ...patch } : entry))
}
