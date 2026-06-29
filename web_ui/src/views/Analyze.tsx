import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { fetchAnalyzeBundle, fetchSymbolSearch } from '../api/client'
import type {
  AnalysisResponse,
  ConfluenceZone,
  Direction,
  EntryBlock,
  EntryConfluenceResponse,
  FibonacciLevels,
  Signal,
} from '../api/types'

type AnalyzeProps = {
  requestedSymbol: {
    value: string
    nonce: number
    cachedBundle?: {
      analysis: AnalysisResponse
      confluence: EntryConfluenceResponse
    } | null
  } | null
  onAnalyzeResult?: (symbol: string, cachedBundle: AnalyzeBundle) => void
  onAddToWatchlist: (
    symbol: string,
    cachedBundle?: {
      analysis: AnalysisResponse
      confluence: EntryConfluenceResponse
    } | null,
  ) => void
  watchlistSymbols: string[]
}

type AnalyzeMutationInput =
  | string
  | {
      symbol: string
      signal?: AbortSignal
      cachedBundle?: {
        analysis: AnalysisResponse
        confluence: EntryConfluenceResponse
      } | null
    }

type AnalyzeBundle = {
  analysis: AnalysisResponse
  confluence: EntryConfluenceResponse
}

type SymbolSuggestion = {
  symbol: string
  name: string
}

type AnalyzeViewState =
  | {
      phase: 'idle'
      bundle: null
      error: string | null
      activeSymbol: string
    }
  | {
      phase: 'loading'
      bundle: null
      error: null
      activeSymbol: string
    }
  | {
      phase: 'cancelled'
      bundle: null
      error: null
      activeSymbol: string
    }
  | {
      phase: 'ready'
      bundle: AnalyzeBundle
      error: null
      activeSymbol: string
    }

const recommendationTone: Record<Direction, string> = {
  BUY: 'border border-green-200 bg-green-50 text-green-800 dark:border-green-800 dark:bg-green-950 dark:text-green-400',
  HOLD: 'border border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-400',
  SELL: 'border border-red-200 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-400',
}

const signalTone: Record<Direction, string> = {
  BUY: 'text-green-700 bg-green-100 dark:bg-green-950 dark:text-green-400',
  HOLD: 'text-amber-700 bg-amber-100 dark:bg-amber-950 dark:text-amber-400',
  SELL: 'text-red-700 bg-red-100 dark:bg-red-950 dark:text-red-400',
}

const signalBarTone: Record<Direction, string> = {
  BUY: 'bg-green-500',
  HOLD: 'bg-amber-500',
  SELL: 'bg-red-500',
}

function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) {
    return '—'
  }
  return `${value.toFixed(digits)}%`
}

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) {
    return '—'
  }
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

function formatPrice(value: number | null | undefined): string {
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

function formatDateLabel(value: string | null | undefined): string {
  if (!value) {
    return '—'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '—'
  }
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function parseFreshness(value: string | undefined): { label: string; tone: string } {
  const normalized = (value ?? 'missing').trim().toLowerCase()
  if (normalized.startsWith('last_close')) {
    return {
      label: 'LAST_CLOSE',
      tone: 'bg-blue-50 text-blue-800 dark:bg-blue-950 dark:text-blue-400',
    }
  }
  if (normalized.startsWith('live')) {
    return {
      label: 'LIVE',
      tone: 'bg-green-50 text-green-800 dark:bg-green-950 dark:text-green-400',
    }
  }
  if (normalized.startsWith('delayed')) {
    return {
      label: 'DELAYED',
      tone: 'bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-400',
    }
  }
  if (normalized.startsWith('missing')) {
    return {
      label: 'MISSING',
      tone: 'bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-400',
    }
  }
  if (/^\d{4}-\d{2}-\d{2}/.test(normalized)) {
    return {
      label: 'DELAYED',
      tone: 'bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-400',
    }
  }
  return {
    label: value?.toUpperCase() ?? 'MISSING',
    tone: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  }
}

function getVoteCount(signals: Signal[], direction: Direction): number {
  return signals.filter((signal) => signal.signal === direction).length
}

function LevelRow({
  label,
  value,
  dotClassName,
  labelClassName,
  valueClassName,
  hollow = false,
}: {
  label: string
  value: string
  dotClassName: string
  labelClassName?: string
  valueClassName?: string
  hollow?: boolean
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <div className="flex min-w-0 items-center gap-2">
        <span
          className={[
            'h-2.5 w-2.5 rounded-full border',
            hollow ? 'bg-transparent' : '',
            dotClassName,
          ].join(' ')}
        />
        <span
          className={[
            'truncate text-[12px] font-medium',
            labelClassName ?? 'text-slate-500 dark:text-slate-400',
          ].join(' ')}
        >
          {label}
        </span>
      </div>
      <span
        className={[
          'text-right text-[12px] tabular-nums',
          valueClassName ?? 'text-slate-500 dark:text-slate-400',
        ].join(' ')}
      >
        {value}
      </span>
    </div>
  )
}

function StatCard({
  label,
  value,
  valueClassName,
  children,
}: {
  label: string
  value?: string
  valueClassName?: string
  children?: ReactNode
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-[11px] py-[9px] text-slate-900 dark:border-white/5 dark:bg-[#161a23] dark:text-slate-100">
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
        {label}
      </p>
      {value ? (
        <p className={['mt-1 text-sm font-medium', valueClassName ?? ''].join(' ')}>{value}</p>
      ) : null}
      {children}
    </div>
  )
}

function DetailRow({
  label,
  value,
  valueClassName,
  children,
}: {
  label: string
  value?: string
  valueClassName?: string
  children?: ReactNode
}) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-2">
      <span className="text-sm text-slate-500 dark:text-slate-400">{label}</span>
      <div className="text-right">
        {value ? (
          <span className={['text-sm font-medium', valueClassName ?? 'text-slate-900 dark:text-slate-100'].join(' ')}>
            {value}
          </span>
        ) : null}
        {children}
      </div>
    </div>
  )
}

function clampPercent(value: number | null | undefined): number {
  if (value == null || Number.isNaN(value)) {
    return 0
  }
  return Math.max(0, Math.min(100, value))
}

function ordinalLabel(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return '—'
  }
  return `${Math.round(value)}th`
}

function ratioLabel(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return '—'
  }
  return `${value.toFixed(2)}×`
}

function barTone(value: number | null | undefined, greenCeiling: number, amberCeiling: number): string {
  if (value == null || Number.isNaN(value)) {
    return 'bg-slate-300 dark:bg-slate-700'
  }
  if (value < greenCeiling) {
    return 'bg-green-500'
  }
  if (value <= amberCeiling) {
    return 'bg-amber-500'
  }
  return 'bg-red-500'
}

function formatDateTimeSmall(value: string | null | undefined): string {
  if (!value) {
    return '—'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '—'
  }
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function formatShares(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return '—'
  }
  return Math.round(value).toLocaleString()
}

function sentimentTone(value: number | null | undefined, buyCeiling: number, sellFloor: number): string {
  if (value == null || Number.isNaN(value)) {
    return 'text-slate-500 dark:text-slate-400'
  }
  if (value < buyCeiling) {
    return 'text-green-600 dark:text-green-400'
  }
  if (value > sellFloor) {
    return 'text-red-600 dark:text-red-400'
  }
  return 'text-slate-600 dark:text-slate-300'
}

const loaderStages = [
  { key: 'price', label: 'Fetch price data' },
  { key: 'technicals', label: 'Compute technicals' },
  { key: 'fundamentals', label: 'Load fundamentals' },
  { key: 'signals', label: 'Assemble signals' },
  { key: 'confluence', label: 'Build confluence' },
] as const

type LoaderStageKey = (typeof loaderStages)[number]['key']

function AnalysisLoader({ symbol }: { symbol: string }) {
  const [activeStageIndex, setActiveStageIndex] = useState(0)
  const [stageTimes, setStageTimes] = useState<Partial<Record<LoaderStageKey, string>>>({})
  const startTimeRef = useRef<number>(0)

  useEffect(() => {
    startTimeRef.current = Date.now()

    const interval = window.setInterval(() => {
      setActiveStageIndex((current) => {
        if (current >= loaderStages.length - 1) {
          return current
        }

        const finishedStage = loaderStages[current]
        setStageTimes((existing) => ({
          ...existing,
          [finishedStage.key]: `${((Date.now() - startTimeRef.current) / 1000).toFixed(1)}s`,
        }))
        return current + 1
      })
    }, 800)

    return () => window.clearInterval(interval)
  }, [])

  const activeStageLabel = loaderStages[activeStageIndex]?.label ?? 'Loading analysis'

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-7 dark:border-white/5 dark:bg-[#0d0f14]">
      <style>{`
        @keyframes progFill {
          0% { width: 5%; }
          30% { width: 42%; }
          60% { width: 68%; }
          85% { width: 85%; }
          100% { width: 91%; }
        }
      `}</style>
      <div className="flex items-start justify-between gap-4">
        <h2 className="text-3xl font-medium text-slate-950 dark:text-slate-50">{symbol || '—'}</h2>
        <span className="rounded border border-slate-200 px-2 py-0.5 text-[10px] text-slate-400 dark:border-[#1e2330] dark:text-slate-500">
          analyzing
        </span>
      </div>

      <div className="mb-5 mt-1 flex items-center gap-1.5">
        {loaderStages.map((stage, index) => {
          const state =
            index < activeStageIndex ? 'done' : index === activeStageIndex ? 'active' : 'waiting'
          return (
            <span
              key={stage.key}
              className={[
                'h-1.5 w-1.5 rounded-full',
                state === 'done'
                  ? 'bg-slate-900 dark:bg-[#3dd68c]'
                  : state === 'active'
                    ? 'bg-slate-500 animate-pulse'
                    : 'bg-slate-200 dark:bg-[#1e2330]',
              ].join(' ')}
            />
          )
        })}
        <span className="ml-2 text-xs text-slate-500 dark:text-slate-500">{activeStageLabel}…</span>
      </div>

      <div className="mb-5 h-px w-full bg-slate-200 dark:bg-[#1e2330]">
        <div
          className="h-px bg-slate-900 dark:bg-[#3dd68c]"
          style={{ animation: 'progFill 3.2s ease-in-out infinite' }}
        />
      </div>
      <div className="mb-4 h-px bg-slate-200 dark:bg-[#1e2330]" />

      <div>
        {loaderStages.map((stage, index) => {
          const state =
            index < activeStageIndex ? 'done' : index === activeStageIndex ? 'active' : 'waiting'

          return (
            <div key={stage.key} className="flex items-center gap-2.5 py-1.5">
              {state === 'done' ? (
                <span className="flex h-[15px] w-[15px] items-center justify-center rounded-full bg-slate-100 text-[9px] text-slate-500 dark:bg-[#1a3d2b] dark:text-[#3dd68c]">
                  ✓
                </span>
              ) : state === 'active' ? (
                <span className="h-[15px] w-[15px] animate-spin rounded-full border border-slate-300 border-t-slate-500 dark:border-[#3a4050] dark:border-t-slate-200" />
              ) : (
                <span className="h-[15px] w-[15px] rounded-full bg-slate-100 dark:bg-[#161a23]" />
              )}

              <span
                className={[
                  'text-xs',
                  state === 'done'
                    ? 'text-slate-400 dark:text-[#3a4a3a]'
                    : state === 'active'
                      ? 'font-medium text-slate-900 dark:text-slate-50'
                      : 'text-slate-200 dark:text-[#1e2330]',
                ].join(' ')}
              >
                {stage.label}
              </span>

              <span
                className={[
                  'ml-auto text-xs',
                  state === 'done'
                    ? 'text-slate-400 dark:text-[#3dd68c]'
                    : state === 'active'
                      ? 'text-slate-400 dark:text-slate-500'
                      : 'invisible',
                ].join(' ')}
              >
                {state === 'done' ? stageTimes[stage.key] ?? '—' : '—'}
              </span>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function SignalVoteCard({ signalVote }: { signalVote: Record<Direction, number> }) {
  const maxCount = Math.max(signalVote.BUY, signalVote.HOLD, signalVote.SELL, 1)

  return (
    <StatCard label="Signal vote">
      <div className="mt-2 space-y-2">
        {(['BUY', 'HOLD', 'SELL'] as Direction[]).map((direction) => (
          <div key={direction} className="space-y-1">
            <div className="flex items-center justify-between text-[11px]">
              <span className="font-medium text-slate-600 dark:text-slate-300">{direction}</span>
              <span className="tabular-nums text-slate-500 dark:text-slate-400">
                {signalVote[direction]}
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
              <div
                className={['h-full rounded-full', signalBarTone[direction]].join(' ')}
                style={{ width: `${(signalVote[direction] / maxCount) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </StatCard>
  )
}

function ResultsPanel({
  entry,
  fibonacci,
  confluence,
  signalVote,
  macro,
}: {
  entry: EntryBlock
  fibonacci: FibonacciLevels | null
  confluence: ConfluenceZone | null
  signalVote: Record<Direction, number>
  macro: EntryConfluenceResponse['classical'] extends never ? never : {
    next_fomc_date?: string | null
    days_to_next_fomc?: number | null
    rate_cut_probability_pct?: number | null
    treasury_10y?: number | null
    vix?: number | null
  }
}) {
  const nextFomc =
    macro.next_fomc_date && macro.days_to_next_fomc != null
      ? `${formatDateLabel(macro.next_fomc_date)} · ${macro.days_to_next_fomc}d`
      : '—'
  const rateCut =
    macro.rate_cut_probability_pct == null ? '—' : `${macro.rate_cut_probability_pct.toFixed(1)}%`
  const rateCutTone =
    macro.rate_cut_probability_pct == null
      ? 'text-slate-500 dark:text-slate-400'
      : macro.rate_cut_probability_pct > 50
        ? 'text-green-600 dark:text-green-400'
        : macro.rate_cut_probability_pct < 30
          ? 'text-red-600 dark:text-red-400'
          : 'text-slate-600 dark:text-slate-300'
  const vixAnd10Y = `${formatNumber(macro.vix, 1)} · ${
    macro.treasury_10y == null ? '—' : `${macro.treasury_10y.toFixed(2)}%`
  }`

  return (
    <div className="grid gap-[14px] xl:grid-cols-[1fr_196px]">
      <div className="rounded-[18px] border border-slate-200 bg-white p-4 text-slate-900 dark:border-white/5 dark:bg-[#161a23] dark:text-slate-100">
        <div className="space-y-1">
          {entry.resistance_levels.map((price, index) => (
            <LevelRow
              key={`resistance-${index}`}
              label={`Resistance ${index + 1}`}
              value={formatPrice(price)}
              dotClassName="border-slate-300 bg-slate-300 dark:border-[#2a3040] dark:bg-[#2a3040]"
            />
          ))}

          <LevelRow
            label="Breakout buy level"
            value={formatPrice(entry.breakout_buy_level)}
            dotClassName="border-violet-500 bg-violet-500"
          />

          <div className="flex items-center justify-between gap-3 border-y border-slate-200 py-3 dark:border-white/5">
            <div className="flex min-w-0 items-center gap-2">
              <span className="h-3 w-3 rounded-full border border-slate-950 bg-slate-950 dark:border-slate-100 dark:bg-slate-100" />
              <span className="truncate text-[13px] font-semibold text-slate-950 dark:text-slate-50">
                Current price
              </span>
            </div>
            <span className="text-right text-base font-semibold tabular-nums text-slate-950 dark:text-slate-50">
              {formatPrice(entry.current_price)}
            </span>
          </div>

          <div className="rounded-xl bg-green-50 px-3 py-3 text-green-800 dark:bg-green-950/40 dark:text-green-400">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em]">Ideal buy zone</p>
            <p className="mt-1 text-sm font-medium">
              {formatPrice(Math.min(...entry.ideal_buy_zone))} - {formatPrice(Math.max(...entry.ideal_buy_zone))}
            </p>
          </div>

          {fibonacci ? (
            <div className="rounded-xl bg-blue-50 px-3 py-3 text-blue-800 dark:bg-blue-950/40 dark:text-blue-400">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em]">Fib golden pocket</p>
              <p className="mt-1 text-sm font-medium">
                {formatPrice(Math.min(fibonacci.golden_pocket_low, fibonacci.golden_pocket_high))} -{' '}
                {formatPrice(Math.max(fibonacci.golden_pocket_low, fibonacci.golden_pocket_high))}
              </p>
            </div>
          ) : null}

          <LevelRow
            label="Conservative entry"
            value={formatPrice(entry.conservative_entry_price)}
            dotClassName="border-amber-500 bg-amber-500"
            valueClassName="text-amber-600 dark:text-amber-400"
          />
          <LevelRow
            label="Stop loss"
            value={formatPrice(entry.stop_loss_suggestion)}
            dotClassName="border-red-500 bg-red-500"
            valueClassName="text-red-600 dark:text-red-400"
          />
          <LevelRow
            label="Invalidation"
            value={formatPrice(entry.invalidation_level)}
            dotClassName="border-red-500"
            valueClassName="text-red-600 dark:text-red-400"
            hollow
          />

          {entry.support_levels.map((price, index) => (
            <LevelRow
              key={`support-${index}`}
              label={`Support ${index + 1}`}
              value={formatPrice(price)}
              dotClassName="border-slate-300 bg-slate-300 dark:border-[#2a3040] dark:bg-[#2a3040]"
            />
          ))}
        </div>

        <div className="mt-4 space-y-3">
          {confluence?.overlap ? (
            <span className="inline-flex rounded-full bg-green-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-green-800 dark:bg-green-950 dark:text-green-400">
              High conviction zone
            </span>
          ) : null}
          {!confluence?.overlap && confluence?.divergence_note ? (
            <div className="border-l-2 border-amber-500 bg-amber-50/80 px-3 py-2 text-[12px] text-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
              {confluence.divergence_note}
            </div>
          ) : null}
          <div className="flex flex-wrap items-center gap-3">
            <span className="rounded-full bg-amber-100 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-800 dark:bg-amber-950 dark:text-amber-400">
              {entry.entry_assessment}
            </span>
            <span className="text-[12px] leading-5 text-slate-500 dark:text-slate-400">{entry.reason}</span>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <SignalVoteCard signalVote={signalVote} />
        <StatCard
          label="Conservative entry"
          value={formatPrice(entry.conservative_entry_price)}
          valueClassName="text-green-600 dark:text-green-400"
        />
        <StatCard
          label="Stop loss"
          value={formatPrice(entry.stop_loss_suggestion)}
          valueClassName="text-red-600 dark:text-red-400"
        />
        <StatCard label="Next FOMC" value={nextFomc} />
        <StatCard label="Rate cut prob" value={rateCut} valueClassName={rateCutTone} />
        <StatCard label="VIX · 10Y" value={vixAnd10Y} />
      </div>
    </div>
  )
}

function isAbortError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false
  }
  const cause = error.cause
  if (cause && typeof cause === 'object') {
    if ('code' in cause && cause.code === 'ERR_CANCELED') {
      return true
    }
    if ('name' in cause && cause.name === 'CanceledError') {
      return true
    }
  }
  return error.name === 'AbortError' || error.message.toLowerCase() === 'canceled'
}

function normalizeSymbol(value: string): string {
  return value.trim().toUpperCase()
}

function Analyze({ requestedSymbol, onAnalyzeResult, onAddToWatchlist, watchlistSymbols }: AnalyzeProps) {
  const initialSymbol = normalizeSymbol(requestedSymbol?.value ?? '') || 'NVDA'
  const [symbolInput, setSymbolInput] = useState(initialSymbol)
  const [signalsOpen, setSignalsOpen] = useState(false)
  const [fundamentalsOpen, setFundamentalsOpen] = useState(true)
  const [sentimentOpen, setSentimentOpen] = useState(true)
  const [watchlistConfirmation, setWatchlistConfirmation] = useState<string | null>(null)
  const lastFiredNonce = useRef<number | null>(null)
  const abortedRef = useRef<boolean>(false)
  const fetchIdRef = useRef<number>(0)
  const controllerRef = useRef<AbortController | null>(null)
  const [suggestions, setSuggestions] = useState<SymbolSuggestion[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [activeSuggestionIndex, setActiveSuggestionIndex] = useState(-1)
  const [companyNameCache, setCompanyNameCache] = useState<Record<string, string>>({})
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const suggestionsRef = useRef<HTMLDivElement>(null)
  const [viewState, setViewState] = useState<AnalyzeViewState>(() =>
    requestedSymbol?.cachedBundle
      ? {
          phase: 'ready',
          bundle: requestedSymbol.cachedBundle,
          error: null,
          activeSymbol: normalizeSymbol(requestedSymbol.value),
        }
      : requestedSymbol?.value
        ? {
            phase: 'loading',
            bundle: null,
            error: null,
            activeSymbol: normalizeSymbol(requestedSymbol.value),
          }
      : {
          phase: 'idle',
          bundle: null,
          error: null,
          activeSymbol: initialSymbol,
        },
  )
  const rememberSuggestionNames = useCallback((results: SymbolSuggestion[]) => {
    if (results.length === 0) {
      return
    }
    setCompanyNameCache((current) => {
      let changed = false
      const next = { ...current }
      for (const result of results) {
        const normalized = normalizeSymbol(result.symbol)
        const name = result.name.trim()
        if (!normalized || !name || next[normalized] === name) {
          continue
        }
        next[normalized] = name
        changed = true
      }
      return changed ? next : current
    })
  }, [])

  const handleSymbolChange = (value: string) => {
    setSymbolInput(value.toUpperCase())
    setActiveSuggestionIndex(-1)
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current)
    if (value.trim().length < 1) {
      setSuggestions([])
      setShowSuggestions(false)
      return
    }
    searchDebounceRef.current = setTimeout(async () => {
      const results = await fetchSymbolSearch(value.trim())
      rememberSuggestionNames(results)
      setSuggestions(results)
      setActiveSuggestionIndex(results.length > 0 ? 0 : -1)
      setShowSuggestions(results.length > 0)
    }, 300)
  }

  const runAnalysis = useCallback(async (input: AnalyzeMutationInput) => {
    const normalized = typeof input === 'string' ? input : input.symbol

    if (typeof input === 'object' && input.cachedBundle) {
      setViewState({
        phase: 'ready',
        bundle: input.cachedBundle,
        error: null,
        activeSymbol: normalized,
      })
      return
    }

    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    abortedRef.current = false
    const fetchId = ++fetchIdRef.current

    setViewState({
      phase: 'loading',
      bundle: null,
      error: null,
      activeSymbol: normalized,
    })

    try {
      const [bundle, searchResults] = await Promise.all([
        fetchAnalyzeBundle(normalized, controller.signal),
        fetchSymbolSearch(normalized),
      ])
      if (abortedRef.current || fetchIdRef.current !== fetchId) {
        return
      }
      rememberSuggestionNames(searchResults)
      setViewState({
        phase: 'ready',
        bundle,
        error: null,
        activeSymbol: normalized,
      })
      onAnalyzeResult?.(normalized, bundle)
    } catch (error) {
      if (abortedRef.current || fetchIdRef.current !== fetchId) {
        return
      }
      if (isAbortError(error)) {
        setViewState({
          phase: 'cancelled',
          bundle: null,
          error: null,
          activeSymbol: normalized,
        })
        return
      }
      setViewState({
        phase: 'idle',
        bundle: null,
        error: error instanceof Error ? error.message : 'Unexpected request failure',
        activeSymbol: normalized,
      })
    } finally {
      if (fetchIdRef.current === fetchId) {
        controllerRef.current = null
      }
    }
  }, [onAnalyzeResult, rememberSuggestionNames])

  useEffect(() => {
    return () => {
      controllerRef.current?.abort()
    }
  }, [])

  useEffect(() => {
    if (!requestedSymbol?.value) {
      return
    }
    if (lastFiredNonce.current === requestedSymbol.nonce) {
      return
    }
    lastFiredNonce.current = requestedSymbol.nonce
    if (requestedSymbol.cachedBundle) {
      return
    }
    let cancelled = false
    const normalized = normalizeSymbol(requestedSymbol.value)
    queueMicrotask(() => {
      if (!cancelled) {
        void runAnalysis(normalized)
      }
    })
    return () => {
      cancelled = true
    }
  }, [requestedSymbol, runAnalysis])

  const entryBundle = viewState.bundle
  const analysis = entryBundle?.analysis
  const confluenceResponse: EntryConfluenceResponse | undefined = entryBundle?.confluence
  const entry = (confluenceResponse?.classical ?? analysis?.entry) as EntryBlock | null | undefined
  const showLoader = viewState.phase === 'loading'
  const showCancelled = viewState.phase === 'cancelled'
  const showResults = viewState.phase === 'ready' && !!entryBundle
  const resultSymbol = analysis?.symbol ?? viewState.activeSymbol
  const displayCompanyName =
    analysis?.company_name ??
    (analysis?.symbol ? companyNameCache[normalizeSymbol(analysis.symbol)] ?? null : null)
  const isInWatchlist = !!resultSymbol && watchlistSymbols.includes(resultSymbol)
  const watchlistButtonLabel = isInWatchlist || watchlistConfirmation === resultSymbol ? 'Added ✓' : 'Add to Watchlist'

  const signalVote = useMemo(() => {
    const signals = analysis?.signals ?? []
    return {
      BUY: getVoteCount(signals, 'BUY'),
      HOLD: getVoteCount(signals, 'HOLD'),
      SELL: getVoteCount(signals, 'SELL'),
    }
  }, [analysis?.signals])

  const freshnessItems = analysis
    ? [
        { label: 'Price', value: analysis.data_freshness.price },
        { label: 'Fundamentals', value: analysis.data_freshness.fundamentals },
        { label: 'Sentiment', value: analysis.data_freshness.sentiment },
        { label: 'Macro', value: analysis.data_freshness.macro },
      ]
    : []

  const fundamentalsSummary = analysis
    ? `${analysis.fundamentals.eps_surprise_pct == null ? '—' : `${analysis.fundamentals.eps_surprise_pct > 0 ? '+' : ''}${analysis.fundamentals.eps_surprise_pct.toFixed(1)}%`} EPS · PE ${
        analysis.fundamentals.pe_percentile_5y == null ? '—' : `${Math.round(analysis.fundamentals.pe_percentile_5y)}th pct`
      } · FCF ${analysis.fundamentals.fcf_trend ?? '—'}`
    : '—'

  const sentimentSummary = analysis
    ? `P/C ${analysis.sentiment.put_call_ratio == null ? '—' : analysis.sentiment.put_call_ratio.toFixed(2)} · IV ${
        analysis.sentiment.iv_rank_approx == null ? '—' : Math.round(analysis.sentiment.iv_rank_approx)
      } · Short ${analysis.sentiment.short_interest_pct == null ? '—' : `${analysis.sentiment.short_interest_pct.toFixed(1)}%`}`
    : '—'

  useEffect(() => {
    if (!watchlistConfirmation) {
      return
    }
    const timeout = window.setTimeout(() => setWatchlistConfirmation(null), 2000)
    return () => window.clearTimeout(timeout)
  }, [watchlistConfirmation])

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        suggestionsRef.current &&
        !suggestionsRef.current.contains(e.target as Node)
      ) {
        setShowSuggestions(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  useEffect(() => {
    if (!analysis?.symbol || analysis.company_name || companyNameCache[normalizeSymbol(analysis.symbol)]) {
      return
    }

    let cancelled = false

    void (async () => {
      const results = await fetchSymbolSearch(analysis.symbol)
      if (cancelled) {
        return
      }
      rememberSuggestionNames(results)
    })()

    return () => {
      cancelled = true
    }
  }, [analysis?.company_name, analysis?.symbol, companyNameCache, rememberSuggestionNames])

  const stopAnalysis = () => {
    abortedRef.current = true
    fetchIdRef.current++
    controllerRef.current?.abort()
    controllerRef.current = null
    lastFiredNonce.current = requestedSymbol?.nonce ?? lastFiredNonce.current
    setViewState((current) => ({
      phase: 'cancelled',
      bundle: null,
      error: null,
      activeSymbol: current.activeSymbol,
    }))
  }

  const handlePrimaryAction = () => {
    if (showLoader) {
      stopAnalysis()
      return
    }
    const normalized = normalizeSymbol(symbolInput)
    if (!normalized) {
      return
    }
    void runAnalysis(normalized)
  }

  const applySuggestion = (suggestion: SymbolSuggestion) => {
    setSymbolInput(suggestion.symbol)
    setSuggestions([])
    setActiveSuggestionIndex(-1)
    setShowSuggestions(false)
  }

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-stone-50 p-5 shadow-sm">
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="relative flex-1">
            <label htmlFor="symbol" className="mb-2 block text-sm font-medium text-slate-700">
              Symbol
            </label>
            <input
              id="symbol"
              value={symbolInput}
              onChange={(event) => handleSymbolChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  setShowSuggestions(false)
                  setActiveSuggestionIndex(-1)
                  return
                }
                if (event.key === 'ArrowDown' && suggestions.length > 0) {
                  event.preventDefault()
                  setShowSuggestions(true)
                  setActiveSuggestionIndex((current) => (current + 1) % suggestions.length)
                  return
                }
                if (event.key === 'ArrowUp' && suggestions.length > 0) {
                  event.preventDefault()
                  setShowSuggestions(true)
                  setActiveSuggestionIndex((current) =>
                    current <= 0 ? suggestions.length - 1 : current - 1,
                  )
                  return
                }
                if (event.key === 'Enter') {
                  event.preventDefault()
                  if (showSuggestions && activeSuggestionIndex >= 0 && suggestions[activeSuggestionIndex]) {
                    applySuggestion(suggestions[activeSuggestionIndex])
                    return
                  }
                  setShowSuggestions(false)
                  setActiveSuggestionIndex(-1)
                  handlePrimaryAction()
                }
              }}
              onFocus={() => {
                if (suggestions.length > 0) {
                  setShowSuggestions(true)
                  setActiveSuggestionIndex((current) => (current >= 0 ? current : 0))
                }
              }}
              placeholder="NVDA"
              className="w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-base outline-none ring-0 transition transition-colors duration-150 focus:border-slate-900 dark:border-white/10 dark:bg-[#161a23] dark:text-slate-100 dark:placeholder-slate-500"
            />
            {showSuggestions && suggestions.length > 0 ? (
              <div
                ref={suggestionsRef}
                className="absolute left-0 right-0 top-full z-50 mt-1 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-[#161a23]"
              >
                {suggestions.map((s, index) => (
                  <button
                    key={s.symbol}
                    type="button"
                    onMouseEnter={() => setActiveSuggestionIndex(index)}
                    onClick={() => applySuggestion(s)}
                    className={[
                      'flex w-full items-center gap-3 px-4 py-2.5 text-left transition',
                      activeSuggestionIndex === index
                        ? 'bg-slate-100 dark:bg-slate-800'
                        : 'hover:bg-slate-50 dark:hover:bg-slate-800',
                    ].join(' ')}
                  >
                    <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {s.symbol}
                    </span>
                    <span className="truncate text-sm text-slate-500 dark:text-slate-400">
                      {s.name}
                    </span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <div className="sm:self-end">
            {showLoader ? (
              <button
                type="button"
                onClick={stopAnalysis}
                className="w-full rounded-2xl bg-red-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-red-500 sm:w-auto"
              >
                Stop
              </button>
            ) : (
              <button
                type="button"
                onClick={handlePrimaryAction}
                className="flex w-full items-center gap-2 rounded-2xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 sm:w-auto"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 24 24"
                  fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <line x1="18" y1="20" x2="18" y2="10"/>
                  <line x1="12" y1="20" x2="12" y2="4"/>
                  <line x1="6" y1="20" x2="6" y2="14"/>
                </svg>
                Analyze
              </button>
            )}
          </div>
        </div>
        {viewState.error ? (
          <p className="mt-3 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">
            {viewState.error}
          </p>
        ) : null}
      </section>

      {showLoader ? (
        <AnalysisLoader
          key={viewState.activeSymbol || String(requestedSymbol?.nonce ?? 'loader')}
          symbol={viewState.activeSymbol || symbolInput.trim().toUpperCase() || 'NVDA'}
        />
      ) : showResults ? (
        <>
          <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-[#0d0f14]">
            <div className="space-y-5">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                <div>
                  <div className="flex items-baseline gap-3 flex-wrap">
                    <h2 className="text-[26px] font-medium text-slate-950 dark:text-slate-50">
                      {analysis!.symbol}
                    </h2>
                    {displayCompanyName ? (
                      <span className="text-base text-slate-500 dark:text-slate-400">
                        {displayCompanyName}
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-3">
                    <p className="text-[20px] text-slate-500 dark:text-slate-400">
                      {formatPrice(entry?.current_price ?? confluenceResponse?.current_price ?? null)}
                    </p>
                    <span
                      className={[
                        'rounded-full px-3 py-1 text-sm font-semibold',
                        recommendationTone[analysis!.recommendation.direction],
                      ].join(' ')}
                    >
                      {analysis!.recommendation.direction}
                    </span>
                    <button
                      type="button"
                      disabled={isInWatchlist}
                      onClick={() => {
                        if (!entryBundle || !analysis) {
                          return
                        }
                        onAddToWatchlist(analysis.symbol, entryBundle)
                        setWatchlistConfirmation(analysis.symbol)
                      }}
                      className={[
                        'rounded-full px-3 py-1 text-sm font-semibold transition',
                        isInWatchlist
                          ? 'cursor-not-allowed bg-slate-200 text-slate-500 dark:bg-slate-800 dark:text-slate-400'
                          : 'bg-slate-900 text-white hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200',
                      ].join(' ')}
                    >
                      {watchlistButtonLabel}
                    </button>
                  </div>
                </div>

                <div className="flex items-end gap-6">
                  <div className="text-right">
                    <p className="text-[18px] font-medium text-slate-950 dark:text-slate-50">
                      {formatPercent(analysis!.confidence * 100)}
                    </p>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      confidence
                    </p>
                  </div>
                  <div className="text-right">
                    <div className="flex justify-end">
                      <div className="h-[3px] w-12 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                        <div
                          className="h-full rounded-full bg-green-500"
                          style={{ width: `${Math.max(0, Math.min(100, analysis!.data_quality_score))}%` }}
                        />
                      </div>
                    </div>
                    <p className="mt-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      DQ {analysis!.data_quality_score}
                    </p>
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                {freshnessItems.map((item) => {
                  const freshness = parseFreshness(item.value)
                  return (
                    <span
                      key={item.label}
                      title={item.value}
                      className={[
                        'rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]',
                        freshness.tone,
                      ].join(' ')}
                    >
                      {item.label}: {freshness.label}
                    </span>
                  )
                })}
              </div>

              {entry ? (
                <ResultsPanel
                  entry={entry}
                  fibonacci={confluenceResponse?.fibonacci ?? null}
                  confluence={confluenceResponse?.confluence ?? null}
                  signalVote={signalVote}
                  macro={analysis!.macro}
                />
              ) : (
                <div className="rounded-[18px] border border-dashed border-slate-300 px-4 py-8 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
                  Entry structure unavailable for this response.
                </div>
              )}
            </div>
          </section>

          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-[#0d0f14]">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
                  Signals
                </p>
                <div className="mt-2 flex flex-wrap gap-3 text-sm text-slate-600 dark:text-slate-300">
                  <span>BUY: {signalVote.BUY}</span>
                  <span>HOLD: {signalVote.HOLD}</span>
                  <span>SELL: {signalVote.SELL}</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setSignalsOpen((value) => !value)}
                className="rounded-full border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-900 hover:text-slate-950 dark:border-slate-700 dark:text-slate-300 dark:hover:border-slate-200 dark:hover:text-slate-100"
              >
                {signalsOpen ? 'Hide signals' : 'Show signals'}
              </button>
            </div>

            {signalsOpen ? (
              <div className="mt-5 overflow-x-auto">
                <table className="min-w-full divide-y divide-slate-200 text-left text-sm dark:divide-slate-800">
                  <thead>
                    <tr className="text-slate-500 dark:text-slate-400">
                      <th className="pb-3 pr-4 font-medium">Dimension</th>
                      <th className="pb-3 pr-4 font-medium">Signal</th>
                      <th className="pb-3 pr-4 font-medium">Weight</th>
                      <th className="pb-3 font-medium">Note</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-900">
                    {analysis!.signals.map((signal) => (
                      <tr key={`${signal.dimension}-${signal.note}`}>
                        <td className="py-3 pr-4 font-medium text-slate-900 dark:text-slate-100">
                          {signal.dimension}
                        </td>
                        <td className="py-3 pr-4">
                          <span
                            className={[
                              'rounded-full px-3 py-1 text-xs font-semibold',
                              signalTone[signal.signal],
                            ].join(' ')}
                          >
                            {signal.signal}
                          </span>
                        </td>
                        <td className="py-3 pr-4 text-slate-700 dark:text-slate-300">
                          {formatNumber(signal.weight)}
                        </td>
                        <td className="py-3 text-slate-600 dark:text-slate-400">{signal.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>

          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-[#0d0f14]">
            <button
              type="button"
              onClick={() => setFundamentalsOpen((value) => !value)}
              className="flex w-full items-start justify-between gap-4 text-left"
            >
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
                  Fundamentals
                </p>
                <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{fundamentalsSummary}</p>
              </div>
              <span className="pt-1 text-sm text-slate-500 dark:text-slate-400">
                {fundamentalsOpen ? '▲' : '▼'}
              </span>
            </button>

            {fundamentalsOpen && analysis ? (
              <div className="mt-6 grid gap-x-6 gap-y-0 md:grid-cols-2">
                <div>
                  <DetailRow
                    label="EPS surprise"
                    value={formatPercent(analysis.fundamentals.eps_surprise_pct)}
                    valueClassName={
                      analysis.fundamentals.eps_surprise_pct == null
                        ? 'text-slate-500 dark:text-slate-400'
                        : analysis.fundamentals.eps_surprise_pct > 5
                          ? 'text-green-600 dark:text-green-400'
                          : analysis.fundamentals.eps_surprise_pct < -5
                            ? 'text-red-600 dark:text-red-400'
                            : 'text-slate-600 dark:text-slate-300'
                    }
                  />
                  <DetailRow label="PE ratio" value={ratioLabel(analysis.fundamentals.pe_ratio)} />
                  <DetailRow label="PE percentile (5y)">
                    <div className="flex items-center justify-end gap-3">
                      <div className="h-2 w-24 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                        <div
                          className={['h-full rounded-full', barTone(analysis.fundamentals.pe_percentile_5y, 40, 70)].join(' ')}
                          style={{ width: `${clampPercent(analysis.fundamentals.pe_percentile_5y)}%` }}
                        />
                      </div>
                      <span className="text-sm font-medium text-slate-900 dark:text-slate-100">
                        {ordinalLabel(analysis.fundamentals.pe_percentile_5y)}
                      </span>
                    </div>
                  </DetailRow>
                  <DetailRow label="FCF trend">
                    {analysis.fundamentals.fcf_trend ? (
                      <span
                        className={[
                          'rounded-full px-2.5 py-1 text-xs font-semibold',
                          analysis.fundamentals.fcf_trend === 'improving'
                            ? 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-400'
                            : analysis.fundamentals.fcf_trend === 'deteriorating'
                              ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-400'
                              : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
                        ].join(' ')}
                      >
                        {analysis.fundamentals.fcf_trend}
                      </span>
                    ) : (
                      <span className="text-sm text-slate-500 dark:text-slate-400">—</span>
                    )}
                  </DetailRow>
                  <DetailRow
                    label="Analyst upgrades (30d)"
                    value={
                      analysis.fundamentals.analyst_upgrades_30d == null
                        ? '—'
                        : String(analysis.fundamentals.analyst_upgrades_30d)
                    }
                    valueClassName="text-green-600 dark:text-green-400"
                  />
                  <DetailRow
                    label="Analyst downgrades (30d)"
                    value={
                      analysis.fundamentals.analyst_downgrades_30d == null
                        ? '—'
                        : String(analysis.fundamentals.analyst_downgrades_30d)
                    }
                    valueClassName="text-red-600 dark:text-red-400"
                  />
                </div>

                <div>
                  <DetailRow
                    label="Revenue growth YoY"
                    value={formatPercent(analysis.fundamentals.revenue_growth_yoy_pct)}
                    valueClassName={
                      analysis.fundamentals.revenue_growth_yoy_pct == null
                        ? 'text-slate-500 dark:text-slate-400'
                        : analysis.fundamentals.revenue_growth_yoy_pct >= 0
                          ? 'text-green-600 dark:text-green-400'
                          : 'text-red-600 dark:text-red-400'
                    }
                  />
                  <DetailRow
                    label="Gross margin"
                    value={formatPercent(analysis.fundamentals.gross_margin_pct)}
                  />
                  <DetailRow label="P/B ratio" value={ratioLabel(analysis.fundamentals.pb_ratio)} />
                  <DetailRow label="P/S ratio" value={ratioLabel(analysis.fundamentals.ps_ratio)} />
                  <DetailRow label="EV/EBITDA" value={ratioLabel(analysis.fundamentals.ev_ebitda)} />
                  <DetailRow label="As-of date">
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {formatDateTimeSmall(analysis.fundamentals.as_of)}
                    </span>
                  </DetailRow>
                </div>
              </div>
            ) : null}
          </section>

          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-[#0d0f14]">
            <button
              type="button"
              onClick={() => setSentimentOpen((value) => !value)}
              className="flex w-full items-start justify-between gap-4 text-left"
            >
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
                  Sentiment
                </p>
                <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{sentimentSummary}</p>
              </div>
              <span className="pt-1 text-sm text-slate-500 dark:text-slate-400">
                {sentimentOpen ? '▲' : '▼'}
              </span>
            </button>

            {sentimentOpen && analysis ? (
              <div className="mt-6 grid gap-x-6 gap-y-0 md:grid-cols-2">
                <div>
                  <DetailRow
                    label="Put/call ratio"
                    value={
                      analysis.sentiment.put_call_ratio == null
                        ? '—'
                        : `${analysis.sentiment.put_call_ratio.toFixed(2)} ${
                            analysis.sentiment.put_call_ratio < 0.7
                              ? 'bullish'
                              : analysis.sentiment.put_call_ratio > 1.0
                                ? 'bearish'
                                : 'neutral'
                          }`
                    }
                    valueClassName={sentimentTone(analysis.sentiment.put_call_ratio, 0.7, 1.0)}
                  />
                  <DetailRow label="IV rank (approx)">
                    <div className="space-y-1">
                      <div className="flex items-center justify-end gap-3">
                        <div className="h-2 w-24 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                          <div
                            className={[
                              'h-full rounded-full',
                              barTone(analysis.sentiment.iv_rank_approx, 30, 70),
                            ].join(' ')}
                            style={{ width: `${clampPercent(analysis.sentiment.iv_rank_approx)}%` }}
                          />
                        </div>
                        <span className="text-sm font-medium text-slate-900 dark:text-slate-100">
                          {analysis.sentiment.iv_rank_approx == null
                            ? '—'
                            : Math.round(analysis.sentiment.iv_rank_approx)}
                        </span>
                      </div>
                      <p className="text-[10px] text-slate-500 dark:text-slate-400">(HV approx)</p>
                    </div>
                  </DetailRow>
                  <DetailRow
                    label="Short interest"
                    value={formatPercent(analysis.sentiment.short_interest_pct)}
                    valueClassName={
                      analysis.sentiment.short_interest_pct == null
                        ? 'text-slate-500 dark:text-slate-400'
                        : analysis.sentiment.short_interest_pct < 5
                          ? 'text-green-600 dark:text-green-400'
                          : analysis.sentiment.short_interest_pct <= 15
                            ? 'text-amber-600 dark:text-amber-400'
                            : 'text-red-600 dark:text-red-400'
                    }
                  />
                  <DetailRow
                    label="Reddit mentions"
                    value={
                      analysis.sentiment.reddit_mention_spike_24h_pct == null
                        ? '— missing'
                        : formatPercent(analysis.sentiment.reddit_mention_spike_24h_pct)
                    }
                    valueClassName="text-slate-600 dark:text-slate-300"
                  />
                </div>

                <div>
                  <DetailRow
                    label="Reddit sentiment"
                    value={
                      analysis.sentiment.reddit_positive_pct == null
                        ? '— missing'
                        : `${analysis.sentiment.reddit_positive_pct.toFixed(1)}% positive`
                    }
                    valueClassName="text-slate-600 dark:text-slate-300"
                  />
                  <DetailRow
                    label="Institutional 13F"
                    value={
                      analysis.sentiment.institutional_net_shares_last_13f == null
                        ? '— delayed 45d'
                        : `${formatShares(analysis.sentiment.institutional_net_shares_last_13f)} shares`
                    }
                    valueClassName="text-slate-600 dark:text-slate-300"
                  />
                  <DetailRow label="13F as-of">
                    <span className="text-sm text-slate-900 dark:text-slate-100">
                      {formatDateTimeSmall(analysis.sentiment.institutional_13f_as_of)}
                    </span>
                  </DetailRow>
                  <DetailRow
                    label="Freshness"
                    value={analysis.sentiment.freshness ?? '—'}
                    valueClassName="text-slate-600 dark:text-slate-300"
                  />
                </div>
              </div>
            ) : null}
          </section>
        </>
      ) : showCancelled ? (
        <section className="flex flex-col items-center gap-4 rounded-3xl border border-slate-200 bg-white p-8 text-center shadow-sm dark:border-slate-800 dark:bg-[#0d0f14]">
          <div className="flex h-11 w-11 items-center justify-center rounded-full bg-slate-100 dark:bg-slate-800">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-5 w-5 text-slate-500"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <rect x="3" y="3" width="18" height="18" rx="2" />
            </svg>
          </div>
          <div>
            <p className="text-base font-medium text-slate-900 dark:text-slate-50">Analysis stopped</p>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {viewState.activeSymbol} · request cancelled
            </p>
          </div>
          <button
            type="button"
            onClick={handlePrimaryAction}
            className="rounded-2xl bg-slate-950 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200"
          >
            Run again
          </button>
        </section>
      ) : (
        <p className="text-sm text-slate-500 dark:text-slate-400">Enter a symbol above to begin.</p>
      )}
    </div>
  )
}

export default Analyze
