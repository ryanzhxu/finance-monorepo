import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'

import {
  addSharedWatchlistSymbol,
  fetchAnalyzeBundle,
  fetchSharedSpaceSession,
  fetchSharedWatchlist,
  loginToSharedSpace,
  logoutFromSharedSpace,
  removeSharedWatchlistSymbol,
} from '../api/client'
import type { AnalysisResponse, EntryConfluenceResponse, SharedSpaceSessionResponse } from '../api/types'
import Watchlist from '../components/Watchlist'
import {
  isStale,
  loadSharedSpaceSessionToken,
  loadWatchlist,
  saveWatchlist,
  storageKeyForSharedSpace,
  storageKeyForSharedSpaceSession,
  saveSharedSpaceSessionToken,
  syncSymbols,
  updateEntry,
  type CachedAnalyzeBundle,
  type WatchlistEntry,
} from '../watchlist'
import Analyze from './Analyze'

type SharedSpaceProps = {
  slug: string
}

type AnalyzeSelection = {
  value: string
  nonce: number
  cachedBundle?: {
    analysis: AnalysisResponse
    confluence: EntryConfluenceResponse
  } | null
}

const PRIVATE_SPACE_TITLE = 'Private watchlist'
const PRIVATE_SPACE_LABEL = 'Private watchlist'
const PRIVATE_SPACE_LOADING = 'Loading private watchlist...'
const PRIVATE_SPACE_LOGIN_HELP = 'Enter the shared passcode to access your private stock pool.'
const PRIVATE_SPACE_LOGIN_CTA = 'Unlock private watchlist'
const PRIVATE_SPACE_LOAD_ERROR = 'Unable to load private watchlist'
const RETRY_DELAY_MS = [150, 500, 1000] as const

function withFreshness(entry: WatchlistEntry): WatchlistEntry {
  return {
    ...entry,
    freshness: entry.lastAnalyzedAt ? (isStale(entry) ? 'stale' : 'live') : 'never',
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

function isAuthRaceError(error: unknown): boolean {
  return error instanceof Error && error.message.includes('Authentication required')
}

function SharedSpace({ slug }: SharedSpaceProps) {
  const storageKey = storageKeyForSharedSpace(slug)
  const sessionTokenStorageKey = storageKeyForSharedSpaceSession(slug)
  const [session, setSession] = useState<SharedSpaceSessionResponse | null>(null)
  const [sessionToken, setSessionToken] = useState<string | null>(() => loadSharedSpaceSessionToken(sessionTokenStorageKey))
  const [sessionError, setSessionError] = useState<string | null>(null)
  const [passcode, setPasscode] = useState('')
  const [authSubmitting, setAuthSubmitting] = useState(false)
  const [requestedSymbol, setRequestedSymbol] = useState<AnalyzeSelection | null>(null)
  const [watchlistEntries, setWatchlistEntries] = useState<WatchlistEntry[]>(() =>
    loadWatchlist(storageKey).map(withFreshness),
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

  const updateStoredSessionToken = useCallback(
    (nextSessionToken: string | null) => {
      setSessionToken(nextSessionToken)
      saveSharedSpaceSessionToken(nextSessionToken, sessionTokenStorageKey)
    },
    [sessionTokenStorageKey],
  )

  const applySharedSymbols = useCallback(
    (symbols: string[], patchSymbol?: string, cachedBundle?: CachedAnalyzeBundle | null) => {
      setWatchlistEntries((current) => {
        let next = syncSymbols(current, symbols).map(withFreshness)
        if (patchSymbol && cachedBundle) {
          const classicalEntry = cachedBundle.confluence.classical
          const fallbackEntry = cachedBundle.analysis.entry
          next = updateEntry(next, patchSymbol, {
            direction: cachedBundle.analysis.recommendation.direction,
            confidence: cachedBundle.analysis.confidence,
            dataQualityScore: cachedBundle.analysis.data_quality_score,
            currentPrice: classicalEntry.current_price ?? fallbackEntry?.current_price ?? null,
            entryAssessment: classicalEntry.entry_assessment ?? fallbackEntry?.entry_assessment ?? null,
            lastAnalyzedAt: new Date().toISOString(),
            freshness: 'live',
            cachedBundle,
          })
        }
        watchlistRef.current = next
        saveWatchlist(next, storageKey)
        return next
      })
    },
    [storageKey],
  )

  const refreshRemoteWatchlist = useCallback(async (overrideSessionToken?: string | null) => {
    const activeSessionToken = overrideSessionToken ?? sessionToken
    for (let attempt = 0; attempt < RETRY_DELAY_MS.length + 1; attempt += 1) {
      try {
        const response = await fetchSharedWatchlist(slug, activeSessionToken ?? undefined)
        applySharedSymbols(response.symbols)
        setSessionError(null)
        return response
      } catch (error) {
        if (attempt < RETRY_DELAY_MS.length && isAuthRaceError(error)) {
          await delay(RETRY_DELAY_MS[attempt])
          continue
        }
        throw error
      }
    }

    throw new Error(PRIVATE_SPACE_LOAD_ERROR)
  }, [applySharedSymbols, sessionToken, slug])

  const processRefreshQueue = useCallback(async () => {
    if (refreshInFlightRef.current || !session?.authenticated) {
      return
    }

    refreshInFlightRef.current = true

    while (refreshQueueRef.current.length > 0) {
      const symbol = refreshQueueRef.current.shift()
      if (!symbol) {
        continue
      }
      const currentEntry = watchlistRef.current.find((entry) => entry.symbol === symbol)
      if (!currentEntry || currentEntry.freshness === 'live') {
        continue
      }
      const activeRequestedSymbol = requestedSymbolRef.current
      if (activeRequestedSymbol?.value === symbol && Date.now() - activeRequestedSymbol.nonce <= 5000) {
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
          saveWatchlist(next, storageKey)
          return next
        })
      } catch {
        setWatchlistEntries((current) => {
          const next = updateEntry(current, symbol, { freshness: 'stale' })
          watchlistRef.current = next
          saveWatchlist(next, storageKey)
          return next
        })
      }

      await new Promise((resolve) => setTimeout(resolve, 500))
      setRefreshingSymbol(null)
    }

    refreshInFlightRef.current = false
    setRefreshingSymbol(null)
  }, [session?.authenticated, storageKey])

  const enqueueSymbols = useCallback(
    (symbols: string[]) => {
      const nextSymbols = symbols
        .map((value) => value.trim().toUpperCase())
        .filter(Boolean)
        .filter((symbol, index, all) => all.indexOf(symbol) === index)
        .filter((symbol) => !refreshQueueRef.current.includes(symbol))

      if (nextSymbols.length === 0) {
        return
      }
      refreshQueueRef.current.push(...nextSymbols)
      void processRefreshQueue()
    },
    [processRefreshQueue],
  )

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const nextSession = await fetchSharedSpaceSession(slug, sessionToken ?? undefined)
        if (cancelled) {
          return
        }
        setSession(nextSession)
        const nextSessionToken = nextSession.authenticated ? (nextSession.session_token ?? sessionToken ?? null) : null
        updateStoredSessionToken(nextSessionToken)
        if (nextSession.authenticated) {
          try {
            await refreshRemoteWatchlist(nextSessionToken)
          } catch (error) {
            if (cancelled) {
              return
            }
            setSessionError(error instanceof Error ? error.message : PRIVATE_SPACE_LOAD_ERROR)
          }
        } else {
          setSessionError(null)
        }
      } catch (error) {
        if (cancelled) {
          return
        }
        updateStoredSessionToken(null)
        setSession({ authenticated: false, slug, display_name: PRIVATE_SPACE_TITLE })
        setSessionError(error instanceof Error ? error.message : PRIVATE_SPACE_LOAD_ERROR)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [refreshRemoteWatchlist, sessionToken, slug, updateStoredSessionToken])

  useEffect(() => {
    if (!session?.authenticated) {
      return
    }
    const staleSymbols = watchlistRef.current
      .filter((entry) => entry.freshness === 'never' || isStale(entry))
      .map((entry) => entry.symbol)
    if (staleSymbols.length > 0) {
      enqueueSymbols(staleSymbols)
    }
  }, [enqueueSymbols, session?.authenticated])

  const handleLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setAuthSubmitting(true)
    setSessionError(null)
    try {
      const nextSession = await loginToSharedSpace(slug, passcode)
      setSession(nextSession)
      const nextSessionToken = nextSession.session_token ?? null
      updateStoredSessionToken(nextSessionToken)
      setPasscode('')
      await refreshRemoteWatchlist(nextSessionToken)
    } catch (error) {
      setSessionError(error instanceof Error ? error.message : 'Unable to authenticate')
    } finally {
      setAuthSubmitting(false)
    }
  }

  const handleLogout = async () => {
    try {
      const nextSession = await logoutFromSharedSpace(slug, sessionToken ?? undefined)
      setSession(nextSession)
      updateStoredSessionToken(null)
      setSessionError(null)
      setRequestedSymbol(null)
    } catch (error) {
      setSessionError(error instanceof Error ? error.message : 'Unable to log out')
    }
  }

  const handleAddToWatchlist = (symbol: string, cachedBundle?: CachedAnalyzeBundle | null) => {
    const normalized = symbol.trim().toUpperCase()
    if (!normalized) {
      return
    }
    void (async () => {
      try {
        const response = await addSharedWatchlistSymbol(slug, normalized, sessionToken ?? undefined)
        applySharedSymbols(response.symbols, normalized, cachedBundle)
        if (!cachedBundle) {
          enqueueSymbols([normalized])
        }
      } catch (error) {
        setSessionError(error instanceof Error ? error.message : 'Unable to update shared watchlist')
      }
    })()
  }

  const handleRemoveFromWatchlist = (symbol: string) => {
    void (async () => {
      try {
        const response = await removeSharedWatchlistSymbol(slug, symbol, sessionToken ?? undefined)
        applySharedSymbols(response.symbols)
        refreshQueueRef.current = refreshQueueRef.current.filter((queuedSymbol) => queuedSymbol !== symbol)
        if (refreshingSymbol === symbol) {
          setRefreshingSymbol(null)
        }
      } catch (error) {
        setSessionError(error instanceof Error ? error.message : 'Unable to update shared watchlist')
      }
    })()
  }

  const handleWatchlistAnalyze = (symbol: string) => {
    const entry = watchlistRef.current.find((watchlistEntry) => watchlistEntry.symbol === symbol)
    setRequestedSymbol({
      value: symbol,
      nonce: Date.now(),
      cachedBundle: entry?.freshness === 'live' ? entry.cachedBundle : null,
    })
  }

  if (session == null) {
    return (
      <div className="min-h-screen bg-slate-50 px-4 py-6 dark:bg-[#090c12] sm:px-6 lg:px-8">
        <div className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-4xl items-center justify-center rounded-[2rem] border border-slate-200 bg-white p-8 shadow-[0_30px_80px_rgba(15,23,42,0.12)] dark:border-slate-800 dark:bg-[#0d0f14]">
          <p className="text-sm text-slate-600 dark:text-slate-400">{PRIVATE_SPACE_LOADING}</p>
        </div>
      </div>
    )
  }

  if (!session.authenticated) {
    return (
      <div className="min-h-screen bg-slate-50 px-4 py-6 dark:bg-[#090c12] sm:px-6 lg:px-8">
        <div className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-4xl items-center justify-center rounded-[2rem] border border-slate-200 bg-white p-8 shadow-[0_30px_80px_rgba(15,23,42,0.12)] dark:border-slate-800 dark:bg-[#0d0f14]">
          <div className="w-full max-w-md space-y-6">
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500 dark:text-slate-400">
                {PRIVATE_SPACE_LABEL}
              </p>
              <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-slate-100">
                {PRIVATE_SPACE_TITLE}
              </h1>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {PRIVATE_SPACE_LOGIN_HELP}
              </p>
            </div>
            <form onSubmit={handleLogin} className="space-y-3">
              <input
                type="password"
                value={passcode}
                onChange={(event) => setPasscode(event.target.value)}
                placeholder="Passcode"
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition dark:border-white/10 dark:bg-[#161a23] dark:text-slate-100"
              />
              <button
                type="submit"
                disabled={authSubmitting}
                className="w-full rounded-xl bg-slate-900 px-4 py-3 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200"
              >
                {authSubmitting ? 'Checking passcode...' : PRIVATE_SPACE_LOGIN_CTA}
              </button>
            </form>
            {sessionError ? (
              <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
                {sessionError}
              </p>
            ) : null}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-6 transition-colors duration-150 dark:bg-[#090c12] sm:px-6 lg:px-8">
      <div className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-7xl flex-col overflow-hidden rounded-[2rem] border border-slate-200 bg-white shadow-[0_30px_80px_rgba(15,23,42,0.12)] transition-colors duration-150 dark:border-slate-800 dark:bg-[#0d0f14]">
        <header className="border-b border-slate-200 bg-white px-6 py-6 dark:border-slate-800 dark:bg-[#0d0f14] sm:px-8">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500 dark:text-slate-400">
                {PRIVATE_SPACE_LABEL}
              </p>
              <div>
                <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-slate-100 sm:text-4xl">
                  {PRIVATE_SPACE_TITLE}
                </h1>
                <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400 sm:text-base">
                  Shared symbol pool for private collaboration. Membership is shared, analysis stays fast per device.
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={handleLogout}
              className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-950 dark:border-white/10 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-slate-100"
            >
              Log out
            </button>
          </div>
          {sessionError ? (
            <p className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
              {sessionError}
            </p>
          ) : null}
        </header>

        <div className="flex flex-1 overflow-hidden">
          <aside className="w-56 shrink-0 overflow-y-auto border-r border-slate-200 p-3 transition-colors duration-150 dark:border-slate-800">
            <Watchlist
              entries={watchlistEntries}
              refreshingSymbol={refreshingSymbol}
              onAdd={(symbol) => handleAddToWatchlist(symbol, null)}
              onRemove={handleRemoveFromWatchlist}
              onAnalyze={handleWatchlistAnalyze}
            />
          </aside>
          <main className="flex-1 overflow-y-auto p-6 transition-colors duration-150 sm:p-8">
            <Analyze
              key={requestedSymbol?.nonce ?? 'shared-analyze-default'}
              requestedSymbol={requestedSymbol}
              onAddToWatchlist={handleAddToWatchlist}
              watchlistSymbols={watchlistEntries.map((entry) => entry.symbol)}
            />
          </main>
        </div>
      </div>
    </div>
  )
}

export default SharedSpace
