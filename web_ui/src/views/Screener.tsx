import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchDemandShockScreen, fetchTrendingScreen, fetchUndervaluedScreen } from '../api/client'
import type { ScreenResultItem, TrendingResultItem } from '../api/types'

type ScreenerProps = {
  onAnalyzeSymbol: (symbol: string) => void
}

type TabKey = 'undervalued' | 'demand_shock' | 'trending'

type ScreenerRow = {
  symbol: string
  score: number | null
  direction: string | null
  confidence: number | null
  entryAssessment: string | null
  dataQuality: number | null
}

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: 'undervalued', label: 'Undervalued' },
  { key: 'demand_shock', label: 'Demand Shock' },
  { key: 'trending', label: 'Trending' },
]

function formatScore(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return '—'
  }
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })
}

function mapUndervaluedRow(item: ScreenResultItem): ScreenerRow {
  return {
    symbol: item.symbol,
    score: item.opportunity_score,
    direction: item.recommendation ?? null,
    confidence: item.confidence,
    entryAssessment: item.entry_assessment ?? null,
    dataQuality: item.data_quality_score,
  }
}

function mapTrendingRow(item: TrendingResultItem): ScreenerRow {
  const trendScore = item.score_breakdown?.trend_score
  return {
    symbol: item.symbol,
    score: typeof trendScore === 'number' ? trendScore : null,
    direction: null,
    confidence: item.confidence,
    entryAssessment: item.buyability?.entry_assessment ?? null,
    dataQuality: item.data_quality_score,
  }
}

function Screener({ onAnalyzeSymbol }: ScreenerProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('undervalued')

  const undervaluedQuery = useQuery({
    queryKey: ['screen', 'undervalued'],
    queryFn: fetchUndervaluedScreen,
    enabled: activeTab === 'undervalued',
  })

  const demandShockQuery = useQuery({
    queryKey: ['screen', 'demand-shock'],
    queryFn: fetchDemandShockScreen,
    enabled: activeTab === 'demand_shock',
  })

  const trendingQuery = useQuery({
    queryKey: ['screen', 'trending'],
    queryFn: fetchTrendingScreen,
    enabled: activeTab === 'trending',
  })

  const activeQuery =
    activeTab === 'undervalued'
      ? undervaluedQuery
      : activeTab === 'demand_shock'
        ? demandShockQuery
        : trendingQuery
  const rows =
    activeTab === 'undervalued'
      ? undervaluedQuery.data?.results.map(mapUndervaluedRow) ?? []
      : activeTab === 'demand_shock'
        ? demandShockQuery.data?.results.map(mapUndervaluedRow) ?? []
      : trendingQuery.data?.results.map(mapTrendingRow) ?? []

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
              Screener
            </p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">
              Live screen results by strategy
            </h2>
            <p className="mt-2 text-sm text-slate-600">
              Endpoints are called directly from the browser with the repo&apos;s actual POST contracts.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 rounded-full border border-slate-200 bg-stone-50 p-1">
            {tabs.map((tab) => {
              const isActive = tab.key === activeTab
              return (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setActiveTab(tab.key)}
                  className={[
                    'rounded-full px-4 py-2 text-sm font-medium transition',
                    isActive
                      ? 'bg-slate-900 text-white'
                      : 'text-slate-600 hover:bg-white hover:text-slate-900',
                  ].join(' ')}
                >
                  {tab.label}
                </button>
              )
            })}
          </div>
        </div>

        {activeQuery.isLoading ? (
          <p className="mt-6 rounded-2xl bg-stone-50 px-4 py-3 text-sm text-slate-600">Loading results...</p>
        ) : null}

        {activeQuery.isError ? (
          <p className="mt-6 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">
            {activeQuery.error.message}
          </p>
        ) : null}

        {!activeQuery.isLoading && !activeQuery.isError ? (
          <div className="mt-6 space-y-4">
            <div className="flex flex-wrap gap-3 text-sm text-slate-600">
              <span className="rounded-full bg-stone-50 px-3 py-1">
                Universe {activeQuery.data?.universe ?? '—'}
              </span>
              <span className="rounded-full bg-stone-50 px-3 py-1">
                Regime {activeQuery.data?.market_regime ?? '—'}
              </span>
              <span className="rounded-full bg-stone-50 px-3 py-1">
                Quality {activeQuery.data?.data_quality_score ?? '—'}
              </span>
            </div>

            <div className="overflow-x-auto rounded-3xl border border-slate-200">
              <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                <thead className="bg-stone-50 text-slate-500">
                  <tr>
                    <th className="px-4 py-3 font-medium">Symbol</th>
                    <th className="px-4 py-3 font-medium">Score</th>
                    <th className="px-4 py-3 font-medium">Direction</th>
                    <th className="px-4 py-3 font-medium">Confidence</th>
                    <th className="px-4 py-3 font-medium">Entry Assessment</th>
                    <th className="px-4 py-3 font-medium">Data Quality</th>
                    <th className="px-4 py-3 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {rows.map((row) => (
                    <tr key={`${activeTab}-${row.symbol}`}>
                      <td className="px-4 py-3 font-semibold text-slate-950">{row.symbol}</td>
                      <td className="px-4 py-3 text-slate-700">{formatScore(row.score)}</td>
                      <td className="px-4 py-3 text-slate-700">{row.direction ?? '—'}</td>
                      <td className="px-4 py-3 text-slate-700">
                        {row.confidence == null ? '—' : `${(row.confidence * 100).toFixed(1)}%`}
                      </td>
                      <td className="px-4 py-3 text-slate-700">{row.entryAssessment ?? '—'}</td>
                      <td className="px-4 py-3 text-slate-700">{row.dataQuality ?? '—'}</td>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => onAnalyzeSymbol(row.symbol)}
                          className="rounded-full border border-slate-300 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-slate-700 transition hover:border-slate-900 hover:text-slate-950"
                        >
                          Analyze →
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {activeQuery.data?.notes.length ? (
              <div className="rounded-2xl bg-stone-50 px-4 py-3 text-sm text-slate-600">
                {activeQuery.data.notes.join(' ')}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>
    </div>
  )
}

export default Screener
