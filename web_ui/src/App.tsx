import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchAnalyzeBundle } from './api/client'
import Watchlist from './components/Watchlist'
import type { AnalysisResponse, EntryConfluenceResponse } from './api/types'
import Analyze from './views/Analyze'
import Health from './views/Health'
import Screener from './views/Screener'
import { applyTheme, getStoredTheme, storeTheme, type Theme } from './theme'
import {
  addSymbol,
  isStale,
  loadWatchlist,
  removeSymbol,
  saveWatchlist,
  updateEntry,
  type WatchlistEntry,
} from './watchlist'

type ViewKey = 'analyze' | 'screener' | 'health'

type AnalyzeSelection = {
  value: string
  nonce: number
  cachedBundle?: {
    analysis: AnalysisResponse
    confluence: EntryConfluenceResponse
  } | null
}

const tabs: Array<{ key: ViewKey; label: string }> = [
  { key: 'analyze', label: 'Analyze' },
  { key: 'screener', label: 'Screener' },
  { key: 'health', label: 'Health' },
]

function ThemeToggle({ theme, onChange }: { theme: Theme; onChange: (theme: Theme) => void }) {
  return (
    <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white p-1 dark:border-slate-700 dark:bg-slate-900">
      {(['light', 'system', 'dark'] as Theme[]).map((itemTheme) => (
        <button
          key={itemTheme}
          type="button"
          onClick={() => onChange(itemTheme)}
          className={[
            'rounded-md px-3 py-1 text-xs font-medium capitalize transition',
            theme === itemTheme
              ? 'bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-100'
              : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200',
          ].join(' ')}
        >
          {itemTheme}
        </button>
      ))}
    </div>
  )
}

function App() {
  const [activeView, setActiveView] = useState<ViewKey>('analyze')
  const [requestedSymbol, setRequestedSymbol] = useState<AnalyzeSelection | null>(null)
  const [theme, setTheme] = useState<Theme>(getStoredTheme)
  const [watchlistEntries, setWatchlistEntries] = useState<WatchlistEntry[]>(() =>
    loadWatchlist().map((entry) => ({
      ...entry,
      freshness: entry.lastAnalyzedAt ? (isStale(entry) ? 'stale' : 'live') : 'never',
    })),
  )
  const [refreshingSymbol, setRefreshingSymbol] = useState<string | null>(null)
  const watchlistRef = useRef(watchlistEntries)
  const requestedSymbolRef = useRef(requestedSymbol)
  const refreshQueueRef = useRef<string[]>([])
  const refreshInFlightRef = useRef(false)

  useEffect(() => {
    watchlistRef.current = watchlistEntries
  }, [watchlistEntries])

  useEffect(() => {
    requestedSymbolRef.current = requestedSymbol
  }, [requestedSymbol])

  useEffect(() => {
    if (theme !== 'system') {
      return
    }
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (event: MediaQueryListEvent) =>
      document.documentElement.classList.toggle('dark', event.matches)
    mediaQuery.addEventListener('change', handler)
    return () => mediaQuery.removeEventListener('change', handler)
  }, [theme])

  const handleThemeChange = (nextTheme: Theme) => {
    storeTheme(nextTheme)
    applyTheme(nextTheme)
    setTheme(nextTheme)
  }

  const processRefreshQueue = useCallback(async () => {
    if (refreshInFlightRef.current) {
      return
    }

    refreshInFlightRef.current = true

    while (refreshQueueRef.current.length > 0) {
      const symbol = refreshQueueRef.current.shift()
      if (!symbol) {
        continue
      }
      const currentEntry = watchlistRef.current.find((entry) => entry.symbol === symbol)
      if (!currentEntry) {
        continue
      }
      if (currentEntry.freshness === 'live') {
        continue
      }
      const activeRequestedSymbol = requestedSymbolRef.current
      if (
        activeRequestedSymbol?.value === symbol &&
        Date.now() - activeRequestedSymbol.nonce <= 5000
      ) {
        continue
      }

      setRefreshingSymbol(symbol)

      try {
        const bundle = await fetchAnalyzeBundle(symbol)
        const currentTimestamp = new Date().toISOString()
        const classicalEntry = bundle.confluence.classical
        const fallbackEntry = bundle.analysis.entry

        setWatchlistEntries((current) => {
          const next = updateEntry(current, symbol, {
            direction: bundle.analysis.recommendation.direction,
            confidence: bundle.analysis.confidence,
            dataQualityScore: bundle.analysis.data_quality_score,
            currentPrice: classicalEntry.current_price ?? fallbackEntry?.current_price ?? null,
            entryAssessment: classicalEntry.entry_assessment ?? fallbackEntry?.entry_assessment ?? null,
            lastAnalyzedAt: currentTimestamp,
            freshness: 'live',
            cachedBundle: bundle,
          })
          watchlistRef.current = next
          saveWatchlist(next)
          return next
        })
      } catch {
        setWatchlistEntries((current) => {
          const currentEntry = current.find((entry) => entry.symbol === symbol)
          if (!currentEntry) {
            return current
          }
          const next = updateEntry(current, symbol, {
            freshness: 'stale',
            lastAnalyzedAt: currentEntry.lastAnalyzedAt,
          })
          watchlistRef.current = next
          saveWatchlist(next)
          return next
        })
      }

      await new Promise((resolve) => setTimeout(resolve, 500))
      setRefreshingSymbol(null)
    }

    refreshInFlightRef.current = false
    setRefreshingSymbol(null)
  }, [])

  const enqueueSymbols = useCallback((symbols: string[]) => {
    const nextSymbols = symbols
      .map((symbol) => symbol.trim().toUpperCase())
      .filter(Boolean)
      .filter((symbol, index, all) => all.indexOf(symbol) === index)
      .filter((symbol) => !refreshQueueRef.current.includes(symbol))

    if (nextSymbols.length === 0) {
      return
    }

    refreshQueueRef.current.push(...nextSymbols)
    void processRefreshQueue()
  }, [processRefreshQueue])

  useEffect(() => {
    const staleSymbols = watchlistRef.current
      .filter((entry) => entry.freshness === 'never' || isStale(entry))
      .map((entry) => entry.symbol)

    if (staleSymbols.length > 0) {
      enqueueSymbols(staleSymbols)
    }
  }, [enqueueSymbols])

  const handleAddToWatchlist = (symbol: string) => {
    const next = addSymbol(watchlistRef.current, symbol)
    if (next === watchlistRef.current) {
      return
    }
    watchlistRef.current = next
    setWatchlistEntries(next)
    saveWatchlist(next)
    enqueueSymbols([symbol])
  }

  const handleRemoveFromWatchlist = (symbol: string) => {
    const next = removeSymbol(watchlistRef.current, symbol)
    watchlistRef.current = next
    setWatchlistEntries(next)
    saveWatchlist(next)
    refreshQueueRef.current = refreshQueueRef.current.filter((queuedSymbol) => queuedSymbol !== symbol)
    if (refreshingSymbol === symbol) {
      setRefreshingSymbol(null)
    }
  }

  const handleWatchlistAnalyze = (symbol: string) => {
    const entry = watchlistRef.current.find((watchlistEntry) => watchlistEntry.symbol === symbol)
    setRequestedSymbol({
      value: symbol,
      nonce: Date.now(),
      cachedBundle: entry?.freshness === 'live' ? entry.cachedBundle : null,
    })
    setActiveView('analyze')
  }

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-6 transition-colors duration-150 dark:bg-[#090c12] sm:px-6 lg:px-8">
      <div className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-7xl flex-col overflow-hidden rounded-[2rem] border border-slate-200 bg-white shadow-[0_30px_80px_rgba(15,23,42,0.12)] transition-colors duration-150 dark:border-slate-800 dark:bg-[#0d0f14]">
        <header className="border-b border-slate-200 bg-white px-6 py-6 dark:border-slate-800 dark:bg-[#0d0f14] sm:px-8">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500 dark:text-slate-400">
                finance-monorepo
              </p>
              <div>
                <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-slate-100 sm:text-4xl">
                  Market Analysis Console
                </h1>
                <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400 sm:text-base">
                  A focused console for single-symbol analysis, screening, and service health checks.
                </p>
              </div>
            </div>
            <div className="flex flex-col gap-3 lg:items-end">
              <ThemeToggle theme={theme} onChange={handleThemeChange} />
              <nav className="flex flex-wrap items-center gap-4">
                {tabs.map((tab) => {
                  const isActive = activeView === tab.key
                  return (
                    <button
                      key={tab.key}
                      type="button"
                      onClick={() => setActiveView(tab.key)}
                      className={[
                        'border-b-2 px-1 pb-2 text-sm font-medium transition',
                        isActive
                          ? 'border-slate-900 text-slate-900 dark:border-slate-100 dark:text-slate-100'
                          : 'border-transparent text-slate-500 dark:text-slate-400',
                      ].join(' ')}
                    >
                      {tab.label}
                    </button>
                  )
                })}
              </nav>
            </div>
          </div>
        </header>

        <div className="flex flex-1 overflow-hidden">
          <aside className="w-56 shrink-0 overflow-y-auto border-r border-slate-200 p-3 transition-colors duration-150 dark:border-slate-800">
            <Watchlist
              entries={watchlistEntries}
              refreshingSymbol={refreshingSymbol}
              onAdd={handleAddToWatchlist}
              onRemove={handleRemoveFromWatchlist}
              onAnalyze={handleWatchlistAnalyze}
            />
          </aside>
          <main className="flex-1 overflow-y-auto p-6 transition-colors duration-150 sm:p-8">
            {activeView === 'analyze' ? (
              <Analyze
                key={requestedSymbol?.nonce ?? 'analyze-default'}
                requestedSymbol={requestedSymbol}
              />
            ) : null}
            {activeView === 'screener' ? (
              <Screener
                onAnalyzeSymbol={(symbol) => {
                  setRequestedSymbol({ value: symbol, nonce: Date.now() })
                  setActiveView('analyze')
                }}
              />
            ) : null}
            {activeView === 'health' ? <Health /> : null}
          </main>
        </div>
      </div>
    </div>
  )
}

export default App
