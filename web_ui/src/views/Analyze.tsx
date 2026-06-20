import { useEffect, useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { fetchAnalyzeBundle } from '../api/client'
import type {
  ConfluenceZone,
  Direction,
  EntryBlock,
  EntryConfluenceResponse,
  FibonacciLevels,
  Signal,
} from '../api/types'

type AnalyzeProps = {
  requestedSymbol: { value: string; nonce: number } | null
}

type LadderLine = {
  key: string
  label: string
  price: number | null
  color: string
  dash?: string
  strokeWidth?: number
}

const directionTone: Record<Direction, string> = {
  BUY: 'text-green-700 bg-green-100',
  HOLD: 'text-amber-700 bg-amber-100',
  SELL: 'text-red-700 bg-red-100',
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

function qualityTone(score: number): string {
  if (score >= 80) {
    return 'text-green-700 bg-green-100'
  }
  if (score >= 60) {
    return 'text-amber-700 bg-amber-100'
  }
  return 'text-red-700 bg-red-100'
}

function parseFreshness(value: string | undefined): { label: string; tone: string } {
  const normalized = (value ?? 'missing').trim().toLowerCase()
  if (normalized.startsWith('last_close')) {
    return { label: 'LAST_CLOSE', tone: 'text-blue-600 bg-blue-50' }
  }
  if (normalized.startsWith('live')) {
    return { label: 'LIVE', tone: 'text-green-600 bg-green-50' }
  }
  if (normalized.startsWith('delayed')) {
    return { label: 'DELAYED', tone: 'text-amber-600 bg-amber-50' }
  }
  if (normalized.startsWith('missing')) {
    return { label: 'MISSING', tone: 'text-red-600 bg-red-50' }
  }
  if (/^\d{4}-\d{2}-\d{2}/.test(normalized)) {
    return { label: 'DELAYED', tone: 'text-amber-600 bg-amber-50' }
  }
  return { label: value?.toUpperCase() ?? 'MISSING', tone: 'text-slate-600 bg-slate-100' }
}

function getVoteCount(signals: Signal[], direction: Direction): number {
  return signals.filter((signal) => signal.signal === direction).length
}

function Ladder({
  entry,
  fibonacci,
  confluence,
}: {
  entry: EntryBlock
  fibonacci: FibonacciLevels | null
  confluence: ConfluenceZone | null
}) {
  const topResistance = entry.resistance_levels[0] ?? Math.max(...entry.ideal_buy_zone)
  const baseMin = Math.min(entry.invalidation_level, entry.stop_loss_suggestion)
  const numericCandidates = [
    topResistance,
    entry.breakout_buy_level,
    entry.current_price,
    entry.ideal_buy_zone[0],
    entry.ideal_buy_zone[1],
    entry.conservative_entry_price,
    entry.stop_loss_suggestion,
    entry.invalidation_level,
    ...(entry.support_levels ?? []),
    ...(entry.resistance_levels ?? []),
    fibonacci?.golden_pocket_low,
    fibonacci?.golden_pocket_high,
  ].filter((value): value is number => typeof value === 'number' && Number.isFinite(value))

  const rangeHigh = Math.max(topResistance, ...numericCandidates)
  const rangeLow = Math.min(baseMin, ...numericCandidates)
  const span = Math.max(rangeHigh - rangeLow, 1)
  const padding = span * 0.1
  const chartTop = 36
  const chartBottom = 444

  const toY = (price: number) => {
    const paddedHigh = rangeHigh + padding
    const paddedLow = rangeLow - padding
    const usableSpan = paddedHigh - paddedLow
    return chartTop + ((paddedHigh - price) / usableSpan) * (chartBottom - chartTop)
  }

  const lines: LadderLine[] = [
    ...entry.resistance_levels.map((price, index) => ({
      key: `resistance-${index}`,
      label: `Resistance ${index + 1}`,
      price,
      color: '#94a3b8',
    })),
    {
      key: 'breakout',
      label: 'Breakout',
      price: entry.breakout_buy_level,
      color: '#7c3aed',
      dash: '6 6',
    },
    {
      key: 'current',
      label: 'Current',
      price: entry.current_price,
      color: '#111827',
      strokeWidth: 2.5,
    },
    {
      key: 'conservative',
      label: 'Conservative entry',
      price: entry.conservative_entry_price,
      color: '#15803d',
      dash: '8 4',
    },
    {
      key: 'stop',
      label: 'Stop loss',
      price: entry.stop_loss_suggestion,
      color: '#ea580c',
      dash: '8 4',
    },
    {
      key: 'invalidation',
      label: 'Invalidation',
      price: entry.invalidation_level,
      color: '#dc2626',
      dash: '8 4',
    },
    ...entry.support_levels.map((price, index) => ({
      key: `support-${index}`,
      label: `Support ${index + 1}`,
      price,
      color: '#94a3b8',
    })),
  ]

  const idealTop = Math.max(...entry.ideal_buy_zone)
  const idealBottom = Math.min(...entry.ideal_buy_zone)

  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-3xl border border-slate-200 bg-stone-50 p-4">
        <svg viewBox="0 0 320 480" className="h-auto w-full">
          <rect x="20" y="16" width="280" height="448" rx="18" fill="#ffffff" />
          <line x1="32" y1="36" x2="32" y2="444" stroke="#cbd5e1" strokeWidth="1" />

          {fibonacci ? (
            <rect
              x="36"
              y={toY(Math.max(fibonacci.golden_pocket_low, fibonacci.golden_pocket_high))}
              width="184"
              height={
                toY(Math.min(fibonacci.golden_pocket_low, fibonacci.golden_pocket_high)) -
                toY(Math.max(fibonacci.golden_pocket_low, fibonacci.golden_pocket_high))
              }
              fill="#2563eb"
              opacity="0.15"
            />
          ) : null}

          <rect
            x="36"
            y={toY(idealTop)}
            width="184"
            height={toY(idealBottom) - toY(idealTop)}
            fill="#16a34a"
            opacity="0.15"
          />
          <text x="230" y={toY(idealTop) - 6} fontSize="11" fill="#15803d">
            Ideal buy zone
          </text>

          {lines.map((line) =>
            line.price == null ? null : (
              <g key={line.key}>
                <line
                  x1="36"
                  x2="220"
                  y1={toY(line.price)}
                  y2={toY(line.price)}
                  stroke={line.color}
                  strokeWidth={line.strokeWidth ?? 1}
                  strokeDasharray={line.dash}
                />
                <text
                  x="230"
                  y={toY(line.price) + 4}
                  fontSize="11"
                  fill={line.color}
                >
                  {line.label} {formatPrice(line.price)}
                </text>
              </g>
            ),
          )}

          {entry.current_price == null ? (
            <text x="230" y="58" fontSize="11" fill="#64748b">
              Current —
            </text>
          ) : null}

          {fibonacci ? (
            <text x="230" y={toY(fibonacci.golden_pocket_low) + 18} fontSize="11" fill="#2563eb">
              Fib Golden Pocket
            </text>
          ) : null}
        </svg>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-full bg-slate-900 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-white">
          {entry.entry_assessment}
        </span>
        {confluence?.overlap ? (
          <span className="rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide text-green-800 bg-green-200">
            HIGH CONVICTION ZONE
          </span>
        ) : null}
        {!confluence?.overlap && confluence?.divergence_note ? (
          <span className="rounded-full px-3 py-1 text-xs font-medium text-amber-800 bg-amber-100">
            {confluence.divergence_note}
          </span>
        ) : null}
      </div>

      <p className="text-sm leading-6 text-slate-700">{entry.reason}</p>
      {entry.current_price == null ? (
        <p className="text-sm text-slate-500">Current price unavailable from the live entry response.</p>
      ) : null}
    </div>
  )
}

function Analyze({ requestedSymbol }: AnalyzeProps) {
  const initialSymbol = requestedSymbol?.value.trim().toUpperCase() || 'NVDA'
  const [symbolInput, setSymbolInput] = useState(initialSymbol)
  const [signalsOpen, setSignalsOpen] = useState(false)
  const analysisMutation = useMutation({
    mutationFn: async (symbol: string) => fetchAnalyzeBundle(symbol),
  })
  const { mutate } = analysisMutation

  useEffect(() => {
    if (!requestedSymbol?.value) {
      return
    }
    const normalized = requestedSymbol.value.trim().toUpperCase()
    mutate(normalized)
  }, [mutate, requestedSymbol])

  const entryBundle = analysisMutation.data
  const analysis = entryBundle?.analysis
  const confluenceResponse: EntryConfluenceResponse | undefined = entryBundle?.confluence
  const entry = (confluenceResponse?.classical ?? analysis?.entry) as EntryBlock | null | undefined

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

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-stone-50 p-5 shadow-sm">
        <form
          className="flex flex-col gap-3 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault()
            const normalized = symbolInput.trim().toUpperCase()
            if (!normalized) {
              return
            }
            mutate(normalized)
          }}
        >
          <div className="flex-1">
            <label htmlFor="symbol" className="mb-2 block text-sm font-medium text-slate-700">
              Symbol
            </label>
            <input
              id="symbol"
              value={symbolInput}
              onChange={(event) => setSymbolInput(event.target.value.toUpperCase())}
              placeholder="NVDA"
              className="w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-base outline-none ring-0 transition focus:border-slate-900"
            />
          </div>
          <div className="sm:self-end">
            <button
              type="submit"
              disabled={analysisMutation.isPending}
              className="w-full rounded-2xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400 sm:w-auto"
            >
              {analysisMutation.isPending ? 'Analyzing...' : 'Analyze'}
            </button>
          </div>
        </form>
        {analysisMutation.isError ? (
          <p className="mt-3 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">
            {analysisMutation.error.message}
          </p>
        ) : null}
      </section>

      {analysis ? (
        <>
          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
                    Summary
                  </p>
                  <div className="flex flex-wrap items-center gap-3">
                    <h2 className="text-3xl font-semibold tracking-tight text-slate-950">
                      {analysis.symbol}
                    </h2>
                    <span
                      className={[
                        'rounded-full px-3 py-1 text-sm font-semibold',
                        directionTone[analysis.recommendation.direction],
                      ].join(' ')}
                    >
                      {analysis.recommendation.direction}
                    </span>
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-medium text-slate-700">
                      Confidence {formatPercent(analysis.confidence * 100)}
                    </span>
                    <span
                      className={[
                        'rounded-full px-3 py-1 text-sm font-semibold',
                        qualityTone(analysis.data_quality_score),
                      ].join(' ')}
                    >
                      Data quality {analysis.data_quality_score}
                    </span>
                  </div>
                </div>
                <div className="rounded-3xl border border-slate-200 bg-stone-50 px-4 py-3 text-sm text-slate-600">
                  <p>Generated {new Date(analysis.generated_at).toLocaleString()}</p>
                  <p>Weighted score {formatNumber(analysis.recommendation.weighted_score)}</p>
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
                        'rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide',
                        freshness.tone,
                      ].join(' ')}
                    >
                      {item.label}: {freshness.label}
                    </span>
                  )
                })}
              </div>

              {analysis.recommendation.risk_flags.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {analysis.recommendation.risk_flags.map((flag) => (
                    <span
                      key={flag}
                      className="rounded-full bg-red-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-red-700"
                    >
                      {flag}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          </section>

          {entry ? (
            <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
                    Entry Zone Ladder
                  </p>
                  <h3 className="mt-2 text-xl font-semibold tracking-tight text-slate-950">
                    Classical entry structure with Fibonacci confluence
                  </h3>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-stone-50 px-4 py-3 text-sm text-slate-600">
                  <p>Current {formatPrice(entry.current_price)}</p>
                  <p>
                    Zone {formatPrice(Math.min(...entry.ideal_buy_zone))} -{' '}
                    {formatPrice(Math.max(...entry.ideal_buy_zone))}
                  </p>
                </div>
              </div>
              <Ladder
                entry={entry}
                fibonacci={confluenceResponse?.fibonacci ?? null}
                confluence={confluenceResponse?.confluence ?? null}
              />
            </section>
          ) : null}

          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
                  Signals
                </p>
                <div className="mt-2 flex flex-wrap gap-3 text-sm text-slate-600">
                  <span>BUY: {signalVote.BUY}</span>
                  <span>HOLD: {signalVote.HOLD}</span>
                  <span>SELL: {signalVote.SELL}</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setSignalsOpen((value) => !value)}
                className="rounded-full border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-900 hover:text-slate-950"
              >
                {signalsOpen ? 'Hide signals' : 'Show signals'}
              </button>
            </div>

            {signalsOpen ? (
              <div className="mt-5 overflow-x-auto">
                <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                  <thead>
                    <tr className="text-slate-500">
                      <th className="pb-3 pr-4 font-medium">Dimension</th>
                      <th className="pb-3 pr-4 font-medium">Signal</th>
                      <th className="pb-3 pr-4 font-medium">Weight</th>
                      <th className="pb-3 font-medium">Note</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {analysis.signals.map((signal) => (
                      <tr key={`${signal.dimension}-${signal.note}`}>
                        <td className="py-3 pr-4 font-medium text-slate-900">{signal.dimension}</td>
                        <td className="py-3 pr-4">
                          <span
                            className={[
                              'rounded-full px-3 py-1 text-xs font-semibold',
                              directionTone[signal.signal],
                            ].join(' ')}
                          >
                            {signal.signal}
                          </span>
                        </td>
                        <td className="py-3 pr-4 text-slate-700">{formatNumber(signal.weight)}</td>
                        <td className="py-3 text-slate-600">{signal.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>
        </>
      ) : (
        <section className="rounded-3xl border border-dashed border-slate-300 bg-white/60 px-6 py-10 text-center shadow-sm">
          <p className="text-lg font-medium text-slate-700">Run an analysis to populate the console.</p>
          <p className="mt-2 text-sm text-slate-500">
            The client will call <code className="rounded bg-slate-100 px-2 py-1">/analyze</code> and{' '}
            <code className="rounded bg-slate-100 px-2 py-1">/entry/confluence</code> in parallel.
          </p>
        </section>
      )}
    </div>
  )
}

export default Analyze
