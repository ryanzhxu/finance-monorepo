import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  fetchTrackRecordCoverage,
  fetchTrackRecordPerformance,
  fetchTrackRecordTimeline,
} from '../api/client'
import type {
  PerformanceBucket,
  TrackRecordEntry,
  TrackRecordPerformance,
  TrackRecordTimeline,
} from '../api/types'
import { formatDirection, formatEntryAssessment } from '../formatters'
import type { Locale } from '../i18n'
import { useI18n } from '../i18n'

function formatDate(value: string | null | undefined, locale: string): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(locale === 'en' ? undefined : locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function formatPercent(value: number | null | undefined): string {
  if (value == null) return '—'
  return `${(value * 100).toFixed(1)}%`
}

function formatPrice(value: number | null | undefined): string {
  if (value == null) return '—'
  return value.toFixed(2)
}

function hitGlyph(hit: boolean | null | undefined): string {
  if (hit == null) return '—'
  return hit ? '✓' : '✗'
}

const cardClass =
  'rounded-3xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-[#0d0f14]'
const labelClass =
  'text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400'

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className={labelClass}>{label}</p>
      <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-slate-100">{value}</p>
    </div>
  )
}

function BucketTable({ title, buckets }: { title: string; buckets: PerformanceBucket[] }) {
  const { t } = useI18n()
  if (buckets.length === 0) return null
  return (
    <div>
      <p className={labelClass}>{title}</p>
      <div className="mt-2 space-y-1">
        {buckets.map((bucket) => (
          <div
            key={bucket.label}
            className="flex items-center justify-between gap-4 text-sm text-slate-700 dark:text-slate-300"
          >
            <span className="font-medium">{bucket.label}</span>
            <span className="tabular-nums text-slate-500 dark:text-slate-400">
              {formatPercent(bucket.hit_rate)} · {bucket.evaluated_count}/{bucket.decision_count}{' '}
              {t('evaluatedCount').toLowerCase()}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function TimelineRow({ entry, locale }: { entry: TrackRecordEntry; locale: Locale }) {
  const { t } = useI18n()
  return (
    <tr className="border-t border-slate-100 dark:border-slate-800">
      <td className="py-2 pr-3 text-slate-600 dark:text-slate-400">
        {formatDate(entry.generated_at, locale)}
      </td>
      <td className="py-2 pr-3 font-medium text-slate-900 dark:text-slate-100">
        {formatDirection(entry.direction, locale)}
      </td>
      <td className="py-2 pr-3 tabular-nums">{formatPercent(entry.confidence)}</td>
      <td className="py-2 pr-3 text-slate-600 dark:text-slate-400">
        {formatEntryAssessment(entry.entry_assessment, locale)}
      </td>
      <td className="py-2 pr-3 tabular-nums">{formatPrice(entry.price_at_call)}</td>
      <td className="py-2 pr-3 text-slate-600 dark:text-slate-400">{entry.target_window}</td>
      <td className="py-2 text-center">
        {entry.skipped_reason ? (
          <span className="text-xs text-slate-400" title={entry.skipped_reason}>
            {t('skippedLabel')}
          </span>
        ) : (
          <span
            className={
              entry.hit == null
                ? 'text-slate-400'
                : entry.hit
                  ? 'text-green-600 dark:text-green-400'
                  : 'text-red-600 dark:text-red-400'
            }
          >
            {hitGlyph(entry.hit)}
          </span>
        )}
      </td>
    </tr>
  )
}

export default function TrackRecord() {
  const { t, locale } = useI18n()
  const coverageQuery = useQuery({
    queryKey: ['track-record', 'coverage'],
    queryFn: fetchTrackRecordCoverage,
    refetchOnWindowFocus: false,
  })

  const [symbolInput, setSymbolInput] = useState('')
  const [timeline, setTimeline] = useState<TrackRecordTimeline | null>(null)
  const [timelineLoading, setTimelineLoading] = useState(false)
  const [timelineError, setTimelineError] = useState<string | null>(null)

  const [performance, setPerformance] = useState<TrackRecordPerformance | null>(null)
  const [performanceLoading, setPerformanceLoading] = useState(false)
  const [performanceError, setPerformanceError] = useState<string | null>(null)

  async function handleLoadTimeline() {
    const symbol = symbolInput.trim().toUpperCase()
    if (!symbol) return
    setTimelineLoading(true)
    setTimelineError(null)
    try {
      setTimeline(await fetchTrackRecordTimeline(symbol))
    } catch (error) {
      setTimeline(null)
      setTimelineError(error instanceof Error ? error.message : String(error))
    } finally {
      setTimelineLoading(false)
    }
  }

  async function handleLoadPerformance() {
    setPerformanceLoading(true)
    setPerformanceError(null)
    try {
      setPerformance(await fetchTrackRecordPerformance())
    } catch (error) {
      setPerformance(null)
      setPerformanceError(error instanceof Error ? error.message : String(error))
    } finally {
      setPerformanceLoading(false)
    }
  }

  const coverage = coverageQuery.data
  const hasRecords = (coverage?.record_count ?? 0) > 0

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-stone-50 p-4 shadow-sm dark:border-slate-800 dark:bg-[#0d0f14] sm:p-5">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
          {t('trackRecord')}
        </p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">
          {t('trackRecordTitle')}
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-500 dark:text-slate-400">
          {t('trackRecordDescription')}
        </p>
      </section>

      <section className={cardClass}>
        {coverageQuery.isLoading ? (
          <p className="text-sm text-slate-500 dark:text-slate-400">{t('loadingResults')}</p>
        ) : coverageQuery.error ? (
          <p className="text-sm text-red-600 dark:text-red-400">
            {(coverageQuery.error as Error).message}
          </p>
        ) : hasRecords ? (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <Stat label={t('coverageRecords')} value={String(coverage?.record_count ?? 0)} />
            <Stat label={t('coverageSymbols')} value={String(coverage?.distinct_symbols ?? 0)} />
            <Stat
              label={t('coverageRange')}
              value={`${formatDate(coverage?.earliest, locale)} – ${formatDate(coverage?.latest, locale)}`}
            />
          </div>
        ) : (
          <p className="text-sm text-slate-500 dark:text-slate-400">{t('noTrackRecord')}</p>
        )}
      </section>

      <section className={cardClass}>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <p className={labelClass}>{t('symbolTimeline')}</p>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <input
            value={symbolInput}
            onChange={(event) => setSymbolInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void handleLoadTimeline()
            }}
            placeholder={t('symbol')}
            className="w-40 rounded-2xl border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-slate-200"
          />
          <button
            type="button"
            onClick={() => void handleLoadTimeline()}
            disabled={timelineLoading || symbolInput.trim().length === 0}
            className="rounded-2xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-900 hover:text-slate-950 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:border-slate-200 dark:hover:text-slate-100"
          >
            {timelineLoading ? t('loadingResults') : t('loadTimeline')}
          </button>
        </div>
        {timelineError ? (
          <p className="mt-3 text-sm text-red-600 dark:text-red-400">{timelineError}</p>
        ) : timeline ? (
          timeline.entries.length === 0 ? (
            <p className="mt-3 text-sm text-slate-500 dark:text-slate-400">
              {t('noCallsForSymbol', { symbol: timeline.symbol })}
            </p>
          ) : (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[560px] text-left text-sm">
                <thead>
                  <tr className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
                    <th className="pb-2 pr-3 font-semibold">{t('when')}</th>
                    <th className="pb-2 pr-3 font-semibold">{t('direction')}</th>
                    <th className="pb-2 pr-3 font-semibold">{t('confidence')}</th>
                    <th className="pb-2 pr-3 font-semibold">{t('entryAssessment')}</th>
                    <th className="pb-2 pr-3 font-semibold">{t('priceAtCall')}</th>
                    <th className="pb-2 pr-3 font-semibold">{t('targetWindow')}</th>
                    <th className="pb-2 text-center font-semibold">{t('hit')}</th>
                  </tr>
                </thead>
                <tbody>
                  {timeline.entries.map((entry) => (
                    <TimelineRow
                      key={`${entry.symbol}-${entry.generated_at}`}
                      entry={entry}
                      locale={locale}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : null}
      </section>

      <section className={cardClass}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className={labelClass}>{t('performance')}</p>
          <button
            type="button"
            onClick={() => void handleLoadPerformance()}
            disabled={performanceLoading}
            className="rounded-2xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-900 hover:text-slate-950 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:border-slate-200 dark:hover:text-slate-100"
          >
            {performanceLoading ? t('loadingResults') : t('loadPerformance')}
          </button>
        </div>
        {performanceError ? (
          <p className="mt-3 text-sm text-red-600 dark:text-red-400">{performanceError}</p>
        ) : performance ? (
          <div className="mt-4 space-y-5">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Stat label={t('hitRate')} value={formatPercent(performance.hit_rate)} />
              <Stat label={t('evaluatedCount')} value={String(performance.evaluated_count)} />
              <Stat label={t('decisionCount')} value={String(performance.decision_count)} />
              <Stat
                label={t('avgForwardReturn')}
                value={formatPercent(performance.average_forward_return)}
              />
              <Stat
                label={t('avgVsBenchmark')}
                value={formatPercent(performance.average_benchmark_relative_return)}
              />
            </div>
            <BucketTable title={t('byDirection')} buckets={performance.by_direction} />
            <BucketTable title={t('byConfidence')} buckets={performance.by_confidence} />
            <BucketTable title={t('byEntryAssessment')} buckets={performance.by_entry_assessment} />
            {performance.advisory.length > 0 ? (
              <div>
                <p className={labelClass}>{t('advisoryLabel')}</p>
                <ul className="mt-2 space-y-1 text-sm text-slate-600 dark:text-slate-400">
                  {performance.advisory.map((note) => (
                    <li key={note}>• {note}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>
    </div>
  )
}
