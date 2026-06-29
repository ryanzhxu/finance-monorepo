import type {
  AnalysisResponse,
  EntryConfluenceResponse,
  SharedWatchlistEntryResponse,
  SharedWatchlistSummaryUpdateRequest,
} from './api/types'

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

function emptyEntry(symbol: string): WatchlistEntry {
  return {
    symbol,
    direction: null,
    confidence: null,
    dataQualityScore: null,
    currentPrice: null,
    entryAssessment: null,
    lastAnalyzedAt: null,
    freshness: 'never',
    cachedBundle: null,
  }
}

export function storageKeyForSharedSpace(slug: string): string {
  return `watchlist_shared_${slug}_v1`
}

export function storageKeyForSharedSpaceSession(slug: string): string {
  return `watchlist_shared_${slug}_session_v1`
}

export function loadSharedSpaceSessionToken(storageKey: string): string | null {
  try {
    const value = localStorage.getItem(storageKey)?.trim()
    return value ? value : null
  } catch {
    return null
  }
}

export function saveSharedSpaceSessionToken(token: string | null, storageKey: string): void {
  if (token) {
    localStorage.setItem(storageKey, token)
    return
  }
  localStorage.removeItem(storageKey)
}

export function loadWatchlist(storageKey: string = KEY): WatchlistEntry[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey) ?? '[]')
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

export function saveWatchlist(entries: WatchlistEntry[], storageKey: string = KEY): void {
  localStorage.setItem(storageKey, JSON.stringify(entries))
}

export function watchlistFreshness(entry: Pick<WatchlistEntry, 'lastAnalyzedAt'>): WatchlistEntry['freshness'] {
  if (!entry.lastAnalyzedAt) {
    return 'never'
  }
  return isStale(entry) ? 'stale' : 'live'
}

export function withFreshness(entry: WatchlistEntry): WatchlistEntry {
  return {
    ...entry,
    freshness: watchlistFreshness(entry),
  }
}

export function addSymbol(entries: WatchlistEntry[], symbol: string): WatchlistEntry[] {
  const upper = symbol.trim().toUpperCase()
  if (!upper || entries.some((entry) => entry.symbol === upper)) {
    return entries
  }
  return [...entries, emptyEntry(upper)]
}

export function removeSymbol(entries: WatchlistEntry[], symbol: string): WatchlistEntry[] {
  return entries.filter((entry) => entry.symbol !== symbol)
}

export function syncSymbols(entries: WatchlistEntry[], symbols: string[]): WatchlistEntry[] {
  const existing = new Map(entries.map((entry) => [entry.symbol, entry]))
  return symbols
    .map((symbol) => symbol.trim().toUpperCase())
    .filter(Boolean)
    .filter((symbol, index, all) => all.indexOf(symbol) === index)
    .map((symbol) => existing.get(symbol) ?? emptyEntry(symbol))
}

export function isStale(entry: Pick<WatchlistEntry, 'lastAnalyzedAt'>): boolean {
  if (!entry.lastAnalyzedAt) {
    return true
  }
  return Date.now() - new Date(entry.lastAnalyzedAt).getTime() > STALE_MS
}

export function refreshableSymbols(entries: WatchlistEntry[]): string[] {
  return entries
    .filter((entry) => entry.freshness === 'never' || isStale(entry))
    .map((entry) => entry.symbol)
}

export function analyzedEntryPatch(
  cachedBundle: CachedAnalyzeBundle,
  analyzedAt: string,
): Partial<WatchlistEntry> {
  const summary = sharedWatchlistSummaryFromAnalyzeBundle(cachedBundle, analyzedAt)
  return {
    direction: summary.direction ?? null,
    confidence: summary.confidence ?? null,
    dataQualityScore: summary.data_quality_score ?? null,
    currentPrice: summary.current_price ?? null,
    entryAssessment: summary.entry_assessment ?? null,
    lastAnalyzedAt: summary.last_analyzed_at ?? null,
    freshness: 'live',
    cachedBundle,
  }
}

export function sharedWatchlistSummaryFromAnalyzeBundle(
  cachedBundle: CachedAnalyzeBundle,
  analyzedAt: string,
): SharedWatchlistSummaryUpdateRequest {
  const classicalEntry = cachedBundle.confluence.classical
  const fallbackEntry = cachedBundle.analysis.entry
  return {
    direction: cachedBundle.analysis.recommendation.direction,
    confidence: cachedBundle.analysis.confidence,
    data_quality_score: cachedBundle.analysis.data_quality_score,
    current_price: classicalEntry.current_price ?? fallbackEntry?.current_price ?? null,
    entry_assessment: classicalEntry.entry_assessment ?? fallbackEntry?.entry_assessment ?? null,
    last_analyzed_at: analyzedAt,
  }
}

export function watchlistEntryFromSharedEntry(
  entry: SharedWatchlistEntryResponse,
  cachedBundle: CachedAnalyzeBundle | null = null,
): WatchlistEntry {
  return withFreshness({
    symbol: entry.symbol,
    direction: entry.direction ?? null,
    confidence: entry.confidence ?? null,
    dataQualityScore: entry.data_quality_score ?? null,
    currentPrice: entry.current_price ?? null,
    entryAssessment: entry.entry_assessment ?? null,
    lastAnalyzedAt: entry.last_analyzed_at ?? null,
    freshness: 'never',
    cachedBundle,
  })
}

export function updateEntry(
  entries: WatchlistEntry[],
  symbol: string,
  patch: Partial<WatchlistEntry>,
): WatchlistEntry[] {
  return entries.map((entry) => (entry.symbol === symbol ? { ...entry, ...patch } : entry))
}
