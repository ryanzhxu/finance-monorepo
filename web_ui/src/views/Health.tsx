import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAnalystHealth, fetchScreenerHealth } from '../api/client'
import type { AnalystHealthResponse, ScreenerHealthResponse } from '../api/types'

function providerDot(value: string): string {
  const v = value.toLowerCase()
  if (['ok', 'true', 'available', 'live', 'reachable', 'fresh', 'file', 'redis', 'configured'].some((k) => v.includes(k)))
    return 'bg-green-500'
  if (['degraded', 'delayed', 'no key', 'estimated', 'stale', 'optional', 'not_configured'].some((k) => v.includes(k)))
    return 'bg-amber-500'
  if (['missing', 'false', 'unavailable', 'unreachable', 'error'].some((k) => v.includes(k)))
    return 'bg-red-500'
  return 'bg-slate-400'
}

function providerIcon(label: string): ReactNode {
  const l = label.toLowerCase()
  const cls = 'h-3.5 w-3.5 flex-shrink-0 text-slate-400 dark:text-slate-500'
  const icon = (path: ReactNode) => (
    <svg xmlns="http://www.w3.org/2000/svg" className={cls} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      {path}
    </svg>
  )
  if (l.includes('status'))
    return icon(<><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></>)
  if (l.includes('config'))
    return icon(<><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/></>)
  if (l.includes('cache'))
    return icon(<><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></>)
  if (l.includes('llm') || l.includes('model'))
    return icon(<><path d="M12 2a5 5 0 0 1 5 5v3a5 5 0 0 1-10 0V7a5 5 0 0 1 5-5z"/><path d="M15 17h.01M12 21v-4M9 17h.01"/></>)
  if (l.includes('yfinance') || l.includes('price') || l.includes('candlestick'))
    return icon(<><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></>)
  if (l.includes('edgar') || l.includes('sec') || l.includes('13f'))
    return icon(<><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></>)
  if (l.includes('alpha') || l.includes('vantage'))
    return icon(<><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></>)
  if (l.includes('fomc') || l.includes('macro') || l.includes('treasury') || l.includes('vix'))
    return icon(<><polyline points="22 7 13.5 15.5 8.5 10.5 1 17"/></>)
  if (l.includes('tiingo') || l.includes('news') || l.includes('rss'))
    return icon(<><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8M15 18h-5M10 6h8v4h-8z"/></>)
  if (l.includes('reddit') || l.includes('stocktwits') || l.includes('social'))
    return icon(<><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></>)
  if (l.includes('analyst') || l.includes('reachable'))
    return icon(<><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></>)
  if (l.includes('universe') || l.includes('world'))
    return icon(<><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></>)
  return icon(<><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></>)
}

function ProviderRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-[5px]">
      <span className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
        {providerIcon(label)}
        {label}
      </span>
      <span className="flex items-center gap-2 text-sm font-medium text-slate-900 dark:text-slate-100">
        <span className={['h-2 w-2 flex-shrink-0 rounded-full', providerDot(value)].join(' ')} />
        {value}
      </span>
    </div>
  )
}

function ServiceCard({
  title,
  portLabel,
  data,
  error,
  loading,
}: {
  title: string
  portLabel: string
  data: AnalystHealthResponse | ScreenerHealthResponse | undefined
  error: Error | null
  loading: boolean
}) {
  const isUp = !!data && data.status === 'ok'
  const coreRows = [
    { label: 'Status', value: data?.status ?? 'unreachable' },
    { label: 'Config valid', value: data?.config_valid != null ? String(data.config_valid) : '—' },
    { label: 'Cache', value: data?.cache_backend ?? '—' },
    ...(data?.llm_available != null
      ? [{ label: 'LLM', value: data.llm_available ? 'available' : 'unavailable' }]
      : []),
  ]

  return (
    <article className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-[#0d0f14]">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
            {portLabel}
          </p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">
            {data?.service ?? title}
          </h2>
        </div>
        <span
          className={[
            'rounded-full px-3 py-1 text-sm font-semibold',
            isUp
              ? 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-400'
              : 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-400',
          ].join(' ')}
        >
          {isUp ? 'Healthy' : 'Down'}
        </span>
      </div>

      <hr className="my-4 border-slate-200 dark:border-slate-800" />

      <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
        Core
      </p>
      {coreRows.map(({ label, value }) => (
        <ProviderRow key={label} label={label} value={value} />
      ))}

      {data?.providers && Object.keys(data.providers).length > 0 ? (
        <>
          <p className="mb-1 mt-4 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
            Data providers
          </p>
          {Object.entries(data.providers).map(([provider, status]) => (
            <ProviderRow key={provider} label={provider} value={status} />
          ))}
        </>
      ) : null}

      {loading ? (
        <p className="mt-4 text-xs text-slate-400 dark:text-slate-500">Checking…</p>
      ) : null}
      {error ? (
        <p className="mt-4 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-400">
          {error.message}
        </p>
      ) : null}
    </article>
  )
}

function Health() {
  const analystQuery = useQuery({
    queryKey: ['health', 'analyst'],
    queryFn: fetchAnalystHealth,
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
  })

  const screenerQuery = useQuery({
    queryKey: ['health', 'screener'],
    queryFn: fetchScreenerHealth,
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
  })

  const lastChecked = Math.max(analystQuery.dataUpdatedAt ?? 0, screenerQuery.dataUpdatedAt ?? 0)
  const lastCheckedLabel =
    lastChecked > 0
      ? new Date(lastChecked).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
      : null

  function handleRefresh() {
    void analystQuery.refetch()
    void screenerQuery.refetch()
  }

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-stone-50 p-5 shadow-sm dark:border-slate-800 dark:bg-[#0d0f14]">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
              Health
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">
              Service heartbeat
            </h1>
            {lastCheckedLabel ? (
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Last checked: {lastCheckedLabel} · auto-refresh 30s
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={handleRefresh}
            className="flex items-center gap-2 rounded-2xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-900 hover:text-slate-950 dark:border-slate-700 dark:text-slate-300 dark:hover:border-slate-200 dark:hover:text-slate-100"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M21 2v6h-6M3 12a9 9 0 0 1 15-6.7L21 8M3 22v-6h6M21 12a9 9 0 0 1-15 6.7L3 16"/>
            </svg>
            Refresh
          </button>
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
        <ServiceCard
          title="Analyst"
          portLabel="Analyst service · :8001"
          data={analystQuery.data}
          error={analystQuery.error ?? null}
          loading={analystQuery.isLoading}
        />
        <ServiceCard
          title="Screener"
          portLabel="Screener service · :8002"
          data={screenerQuery.data}
          error={screenerQuery.error ?? null}
          loading={screenerQuery.isLoading}
        />
      </div>

      <div className="flex gap-3 items-start rounded-2xl bg-slate-50 px-4 py-3 dark:bg-[#161a23]">
        <svg xmlns="http://www.w3.org/2000/svg" className="mt-0.5 h-4 w-4 flex-shrink-0 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
        </svg>
        <p className="text-xs leading-relaxed text-slate-500 dark:text-slate-400">
          Degraded providers lower <code className="font-mono">data_quality_score</code> and confidence on each analysis.
          Missing credentials (Reddit, StockTwits) are expected until API keys are added to <code className="font-mono">.env</code>.
        </p>
      </div>
    </div>
  )
}

export default Health
