import { useState, type FormEvent } from 'react'
import type { WatchlistEntry } from '../watchlist'

type WatchlistProps = {
  entries: WatchlistEntry[]
  refreshingSymbol: string | null
  onAdd: (symbol: string) => void
  onRemove: (symbol: string) => void
  onAnalyze: (symbol: string) => void
}

function timeAgo(iso: string): string {
  const timestamp = new Date(iso).getTime()
  if (Number.isNaN(timestamp)) {
    return 'just now'
  }
  const deltaMs = Math.max(0, Date.now() - timestamp)
  const minutes = Math.floor(deltaMs / 60000)
  if (minutes < 1) {
    return 'just now'
  }
  if (minutes < 60) {
    return `${minutes}m ago`
  }
  const hours = Math.floor(minutes / 60)
  if (hours < 24) {
    return `${hours}h ago`
  }
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

function RefreshIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-3.5 w-3.5 animate-spin text-slate-500 dark:text-slate-400"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M20 11a8 8 0 1 0 2 5.3" />
      <path d="M20 4v7h-7" />
    </svg>
  )
}

function directionTone(direction: WatchlistEntry['direction']): string {
  if (direction === 'BUY') {
    return 'border border-green-200 bg-green-50 text-green-800 dark:border-green-800 dark:bg-green-950 dark:text-green-400'
  }
  if (direction === 'HOLD') {
    return 'border border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-400'
  }
  if (direction === 'SELL') {
    return 'border border-red-200 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-400'
  }
  return 'border border-slate-200 bg-slate-100 text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400'
}

function formatPrice(value: number | null): string {
  if (value == null || Number.isNaN(value)) {
    return '—'
  }
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function Watchlist({ entries, refreshingSymbol, onAdd, onRemove, onAnalyze }: WatchlistProps) {
  const [inputValue, setInputValue] = useState('')

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onAdd(inputValue)
    setInputValue('')
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
            Watchlist
          </p>
        </div>
        <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          {entries.length}
        </span>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {entries.map((entry) => (
          <div
            key={entry.symbol}
            className="relative rounded-lg border border-slate-200 bg-slate-50 px-[10px] py-2 transition hover:border-slate-300 dark:border-white/5 dark:bg-[#161a23] dark:hover:border-slate-700"
          >
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                onRemove(entry.symbol)
              }}
              className="absolute right-2 top-2 text-base leading-none text-slate-400 transition hover:text-red-500"
              aria-label={`Remove ${entry.symbol}`}
            >
              ×
            </button>

            <button
              type="button"
              onClick={() => onAnalyze(entry.symbol)}
              className="flex w-full items-start justify-between gap-2 pr-5 text-left"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium text-slate-900 dark:text-slate-100">
                    {entry.symbol}
                  </span>
                  <span
                    className={[
                      'rounded-full px-2 py-0.5 text-[10px] font-semibold',
                      directionTone(entry.direction),
                    ].join(' ')}
                  >
                    {entry.direction ?? '—'}
                  </span>
                </div>
                <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                  {formatPrice(entry.currentPrice)}
                </p>
                {entry.entryAssessment ? (
                  <p className="mt-1 truncate text-[10px] italic text-slate-500 dark:text-slate-400">
                    {entry.entryAssessment}
                  </p>
                ) : null}
              </div>

              <div className="flex shrink-0 items-center gap-1 text-[10px] text-slate-500 dark:text-slate-400">
                {refreshingSymbol === entry.symbol ? (
                  <RefreshIcon />
                ) : entry.freshness === 'never' ? (
                  <span>never run</span>
                ) : (
                  <>
                    <span
                      className={[
                        'h-2 w-2 rounded-full',
                        entry.freshness === 'live' ? 'bg-green-500' : 'bg-amber-500',
                      ].join(' ')}
                    />
                    <span>{entry.lastAnalyzedAt ? timeAgo(entry.lastAnalyzedAt) : 'stale'}</span>
                  </>
                )}
              </div>
            </button>
          </div>
        ))}

        {entries.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-[11px] text-slate-500 dark:border-slate-700 dark:text-slate-400">
            Add a symbol to start a lightweight watchlist.
          </div>
        ) : null}
      </div>

      <form onSubmit={handleSubmit} className="mt-3 space-y-2 border-t border-slate-200 pt-3 dark:border-slate-800">
        <input
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value.toUpperCase())}
          placeholder="Symbol…"
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition placeholder:text-slate-500 focus:border-slate-400 dark:border-white/10 dark:bg-[#161a23] dark:text-slate-100 dark:placeholder:text-slate-500"
        />
        <button
          type="submit"
          className="w-full rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200"
        >
          Add
        </button>
      </form>
    </div>
  )
}

export default Watchlist
