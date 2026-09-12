import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  fetchDemandShockScreen,
  fetchOpportunitiesScreen,
  fetchTrendingScreen,
  fetchUndervaluedScreen,
} from '../api/client'
import type { ScreenResultItem, TrendingResultItem } from '../api/types'
import { formatDirection, formatEntryAssessment } from '../formatters'
import { useI18n } from '../i18n'

type ScreenerProps = {
  onAnalyzeSymbol: (symbol: string) => void
}

type TabKey = 'undervalued' | 'demand_shock' | 'trending' | 'opportunities'

type ScreenerRow = {
  symbol: string
  score: number | null
  direction: string | null
  confidence: number | null
  entryAssessment: string | null
  dataQuality: number | null
  heldByIndexHurdle: boolean
  masterDirection: string | null
  masterConfirms: boolean | null
}

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
    heldByIndexHurdle: item.held_by_index_hurdle ?? false,
    masterDirection: null,
    masterConfirms: null,
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
    heldByIndexHurdle: item.held_by_index_hurdle ?? false,
    masterDirection: null,
    masterConfirms: null,
  }
}

function mapOpportunitiesRow(item: ScreenResultItem): ScreenerRow {
  return {
    ...mapUndervaluedRow(item),
    masterDirection: item.master_direction ?? null,
    masterConfirms: item.master_confirms ?? null,
  }
}

function Screener({ onAnalyzeSymbol }: ScreenerProps) {
  const { locale, t } = useI18n()
  const [activeTab, setActiveTab] = useState<TabKey>('undervalued')
  const tabs: Array<{ key: TabKey; label: string }> = [
    { key: 'undervalued', label: t('undervalued') },
    { key: 'demand_shock', label: t('demandShock') },
    { key: 'trending', label: t('trending') },
    { key: 'opportunities', label: t('opportunities') },
  ]

  const undervaluedQuery = useQuery({
    queryKey: ['screen', 'undervalued'],
    queryFn: fetchUndervaluedScreen,
    enabled: false,
  })

  const demandShockQuery = useQuery({
    queryKey: ['screen', 'demand-shock'],
    queryFn: fetchDemandShockScreen,
    enabled: false,
  })

  const trendingQuery = useQuery({
    queryKey: ['screen', 'trending'],
    queryFn: fetchTrendingScreen,
    enabled: false,
  })

  const opportunitiesQuery = useQuery({
    queryKey: ['screen', 'opportunities'],
    queryFn: fetchOpportunitiesScreen,
    enabled: false,
  })

  const activeQuery =
    activeTab === 'undervalued'
      ? undervaluedQuery
      : activeTab === 'demand_shock'
        ? demandShockQuery
        : activeTab === 'trending'
          ? trendingQuery
          : opportunitiesQuery
  const rows =
    activeTab === 'undervalued'
      ? undervaluedQuery.data?.results.map(mapUndervaluedRow) ?? []
      : activeTab === 'demand_shock'
        ? demandShockQuery.data?.results.map(mapUndervaluedRow) ?? []
        : activeTab === 'trending'
          ? trendingQuery.data?.results.map(mapTrendingRow) ?? []
          : opportunitiesQuery.data?.results.map(mapOpportunitiesRow) ?? []
  const activeTabLabel = tabs.find((tab) => tab.key === activeTab)?.label ?? t('screener')

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
              {t('screener')}
            </p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">
              {t('screenerTitle')}
            </h2>
            <p className="mt-2 text-sm text-slate-600">
              {t('screenerDescription')}
            </p>
          </div>
          <div className="flex flex-wrap gap-2 rounded-2xl border border-slate-200 bg-stone-50 p-1">
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

        <button
          type="button"
          onClick={() => void activeQuery.refetch()}
          disabled={activeQuery.isFetching}
          className="mt-4 rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          {activeQuery.isFetching ? t('running') : t('run', { screen: activeTabLabel })}
        </button>

        {activeQuery.isFetching ? (
          <p className="mt-6 rounded-2xl bg-stone-50 px-4 py-3 text-sm text-slate-600">{t('loadingResults')}</p>
        ) : null}

        {activeQuery.isError ? (
          <p className="mt-6 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">
            {activeQuery.error.message}
          </p>
        ) : null}

        {!activeQuery.isFetching && !activeQuery.isError && !activeQuery.isFetched ? (
          <p className="mt-6 rounded-2xl bg-stone-50 px-4 py-3 text-sm text-slate-600">
            {t('runScreenHint')}
          </p>
        ) : null}

        {!activeQuery.isFetching && !activeQuery.isError && activeQuery.data ? (
          <div className="mt-6 space-y-4">
            <div className="flex flex-wrap gap-3 text-sm text-slate-600">
              <span className="rounded-full bg-stone-50 px-3 py-1">
                {t('universe')} {activeQuery.data?.universe ?? '—'}
              </span>
              <span className="rounded-full bg-stone-50 px-3 py-1">
                {t('regime')} {activeQuery.data?.market_regime ?? '—'}
              </span>
              <span className="rounded-full bg-stone-50 px-3 py-1">
                {t('quality')} {activeQuery.data?.data_quality_score ?? '—'}
              </span>
            </div>

            <div className="overflow-x-auto rounded-3xl border border-slate-200">
              <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                <thead className="bg-stone-50 text-slate-500">
                  <tr>
                    <th className="px-4 py-3 font-medium">{t('symbol')}</th>
                    <th className="px-4 py-3 font-medium">{t('score')}</th>
                    <th className="px-4 py-3 font-medium">{t('direction')}</th>
                    <th className="px-4 py-3 font-medium">{t('confidence')}</th>
                    <th className="px-4 py-3 font-medium">{t('entryAssessment')}</th>
                    <th className="px-4 py-3 font-medium">{t('dataQuality')}</th>
                    <th className="px-4 py-3 font-medium">{t('masterVerdict')}</th>
                    <th className="px-4 py-3 font-medium">{t('actions')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {rows.map((row) => (
                    <tr key={`${activeTab}-${row.symbol}`}>
                      <td className="px-4 py-3 font-semibold text-slate-950">{row.symbol}</td>
                      <td className="px-4 py-3 text-slate-700">{formatScore(row.score)}</td>
                      <td className="px-4 py-3 text-slate-700">{formatDirection(row.direction, locale)}</td>
                      <td className="px-4 py-3 text-slate-700">
                        {row.confidence == null ? '—' : `${(row.confidence * 100).toFixed(1)}%`}
                      </td>
                      <td className="px-4 py-3 text-slate-700">
                        {row.heldByIndexHurdle
                          ? t('screenerHeldByHurdle')
                          : formatEntryAssessment(row.entryAssessment, locale)}
                      </td>
                      <td className="px-4 py-3 text-slate-700">{row.dataQuality ?? '—'}</td>
                      <td className="px-4 py-3 text-slate-700">
                        {row.masterDirection == null ? (
                          '—'
                        ) : (
                          <span className="inline-flex items-center gap-1">
                            <span>{formatDirection(row.masterDirection, locale)}</span>
                            {row.masterConfirms === true ? (
                              <span className="text-emerald-600" title={t('masterVerdictConfirms')}>
                                ✓
                              </span>
                            ) : row.masterConfirms === false ? (
                              <span className="text-amber-600" title={t('masterVerdictDiffers')}>
                                ⚠
                              </span>
                            ) : null}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => onAnalyzeSymbol(row.symbol)}
                          className="rounded-full border border-slate-300 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-slate-700 transition hover:border-slate-900 hover:text-slate-950"
                        >
                          {t('analyze')} →
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
