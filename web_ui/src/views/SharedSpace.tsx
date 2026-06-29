import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'

import {
  addSharedWatchlistSymbol,
  fetchAnalyzeBundle,
  fetchSharedSpaceSession,
  fetchSharedWatchlist,
  loginToSharedSpace,
  logoutFromSharedSpace,
  removeSharedWatchlistSymbol,
  updateSharedWatchlistSummary,
} from '../api/client'
import type {
  AnalysisResponse,
  EntryConfluenceResponse,
  SharedSpaceSessionResponse,
  SharedWatchlistResponse,
} from '../api/types'
import Watchlist from '../components/Watchlist'
import {
  analyzedEntryPatch,
  loadSharedSpaceSessionToken,
  refreshableSymbols,
  saveSharedSpaceSessionToken,
  storageKeyForSharedSpaceSession,
  sharedWatchlistSummaryFromAnalyzeBundle,
  updateEntry,
  watchlistEntryFromSharedEntry,
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

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

function isAuthRaceError(error: unknown): boolean {
  return error instanceof Error && error.message.includes('Authentication required')
}

function normalizedTimestamp(value: string | null | undefined): string | null {
  if (!value) {
    return null
  }
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString()
}

function SharedSpace({ slug }: SharedSpaceProps) {
  const sessionTokenStorageKey = storageKeyForSharedSpaceSession(slug)
  const [session, setSession] = useState<SharedSpaceSessionResponse | null>(null)
  const [sessionToken, setSessionToken] = useState<string | null>(() => loadSharedSpaceSessionToken(sessionTokenStorageKey))
  const [sessionError, setSessionError] = useState<string | null>(null)
  const [passcode, setPasscode] = useState('')
  const [authSubmitting, setAuthSubmitting] = useState(false)
  const [requestedSymbol, setRequestedSymbol] = useState<AnalyzeSelection | null>(null)
  const [watchlistEntries, setWatchlistEntries] = useState<WatchlistEntry[]>([])
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

  const applySharedWatchlist = useCallback(
    (response: SharedWatchlistResponse) => {
      setWatchlistEntries((current) => {
        const currentBySymbol = new Map(current.map((entry) => [entry.symbol, entry]))
        const next = response.entries.map((entry) => {
          const existingEntry = currentBySymbol.get(entry.symbol)
          const cachedBundle =
            existingEntry?.cachedBundle &&
            normalizedTimestamp(existingEntry.lastAnalyzedAt) === normalizedTimestamp(entry.last_analyzed_at)
              ? existingEntry.cachedBundle
              : null
          return watchlistEntryFromSharedEntry(entry, cachedBundle)
        })
        watchlistRef.current = next
        return next
      })
    },
    [],
  )

  const refreshRemoteWatchlist = useCallback(async (overrideSessionToken?: string | null) => {
    const activeSessionToken = overrideSessionToken ?? sessionToken
    for (let attempt = 0; attempt < RETRY_DELAY_MS.length + 1; attempt += 1) {
      try {
        const response = await fetchSharedWatchlist(slug, activeSessionToken ?? undefined)
        applySharedWatchlist(response)
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
  }, [applySharedWatchlist, sessionToken, slug])

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

        setWatchlistEntries((current) => {
          const next = updateEntry(current, symbol, analyzedEntryPatch(bundle, currentTimestamp))
          watchlistRef.current = next
          return next
        })
        void (async () => {
          try {
            const response = await updateSharedWatchlistSummary(
              slug,
              symbol,
              sharedWatchlistSummaryFromAnalyzeBundle(bundle, currentTimestamp),
              sessionToken ?? undefined,
            )
            applySharedWatchlist(response)
          } catch (error) {
            setSessionError(error instanceof Error ? error.message : 'Unable to update shared watchlist')
          }
        })()
      } catch {
        setWatchlistEntries((current) => {
          const next = updateEntry(current, symbol, { freshness: 'stale' })
          watchlistRef.current = next
          return next
        })
      }

      await new Promise((resolve) => setTimeout(resolve, 500))
      setRefreshingSymbol(null)
    }

    refreshInFlightRef.current = false
    setRefreshingSymbol(null)
  }, [applySharedWatchlist, session?.authenticated, sessionToken, slug])

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
          setWatchlistEntries([])
        }
      } catch (error) {
        if (cancelled) {
          return
        }
        updateStoredSessionToken(null)
        setSession({ authenticated: false, slug, display_name: PRIVATE_SPACE_TITLE })
        setWatchlistEntries([])
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
    const staleSymbols = refreshableSymbols(watchlistRef.current)
    if (staleSymbols.length > 0) {
      enqueueSymbols(staleSymbols)
    }
  }, [enqueueSymbols, session?.authenticated])

  useEffect(() => {
    if (!session?.authenticated) {
      return
    }
    const neverRunSymbols = watchlistEntries
      .filter((entry) => entry.freshness === 'never')
      .map((entry) => entry.symbol)
    if (neverRunSymbols.length > 0) {
      enqueueSymbols(neverRunSymbols)
    }
  }, [enqueueSymbols, session?.authenticated, watchlistEntries])

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
      setWatchlistEntries([])
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
        const analyzedAt = cachedBundle ? new Date().toISOString() : null
        const response = await addSharedWatchlistSymbol(
          slug,
          normalized,
          sessionToken ?? undefined,
          cachedBundle && analyzedAt ? sharedWatchlistSummaryFromAnalyzeBundle(cachedBundle, analyzedAt) : undefined,
        )
        applySharedWatchlist(response)
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
        applySharedWatchlist(response)
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

  const handleAnalyzeResult = useCallback(
    (symbol: string, cachedBundle: CachedAnalyzeBundle) => {
      const analyzedAt = new Date().toISOString()
      setWatchlistEntries((current) => {
        const existingEntry = current.find((entry) => entry.symbol === symbol)
        if (!existingEntry) {
          return current
        }
        const next = updateEntry(current, symbol, analyzedEntryPatch(cachedBundle, analyzedAt))
        watchlistRef.current = next
        return next
      })
      void (async () => {
        try {
          const response = await updateSharedWatchlistSummary(
            slug,
            symbol,
            sharedWatchlistSummaryFromAnalyzeBundle(cachedBundle, analyzedAt),
            sessionToken ?? undefined,
          )
          applySharedWatchlist(response)
        } catch (error) {
          setSessionError(error instanceof Error ? error.message : 'Unable to update shared watchlist')
        }
      })()
    },
    [applySharedWatchlist, sessionToken, slug],
  )

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
                  Shared symbol pool for private collaboration. Membership and latest analysis snapshots stay in sync across browsers.
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
              onAnalyzeResult={handleAnalyzeResult}
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
