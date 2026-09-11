import type {
  ConsolidatedAdjustment,
  ConsolidatedDecision,
  ConsolidatedHorizon,
  IndexHurdle,
  PriceRange,
} from '../api/types'
import { useI18n, type MessageKey } from '../i18n'

type FinalDecisionPanelProps = {
  decision: ConsolidatedDecision
}

const HORIZONS = [
  { key: 'short', title: 'horizonShort', window: 'horizonShortWindow' },
  { key: 'mid', title: 'horizonMid', window: 'horizonMidWindow' },
  { key: 'long', title: 'horizonLong', window: 'horizonLongWindow' },
] as const

const ACTION_TONE: Record<string, string> = {
  strong_buy: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200',
  buy: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200',
  accumulate: 'bg-emerald-50 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-300',
  hold: 'bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200',
  trim: 'bg-orange-100 text-orange-900 dark:bg-orange-500/20 dark:text-orange-200',
  sell: 'bg-rose-100 text-rose-900 dark:bg-rose-500/20 dark:text-rose-200',
  avoid: 'bg-slate-200 text-slate-700 dark:bg-slate-700/50 dark:text-slate-300',
}
const NEUTRAL_TONE = 'bg-slate-200 text-slate-700 dark:bg-slate-700/50 dark:text-slate-300'

const STANCE_KEYS: Record<string, MessageKey> = {
  supportive: 'stanceSupportive',
  neutral: 'stanceNeutral',
  weak: 'stanceWeak',
  unavailable: 'stanceUnavailable',
}
const ROLE_KEYS: Record<string, MessageKey> = {
  index: 'hurdleRoleIndex',
  sector: 'hurdleRoleSector',
  industry: 'hurdleRoleIndustry',
  local_index: 'hurdleRoleLocalIndex',
}
const RESULT_KEYS: Record<string, MessageKey> = {
  beats: 'hurdleBeats',
  lags: 'hurdleLags',
  mixed: 'hurdleMixed',
  insufficient_data: 'hurdleInsufficient',
}
const RESULT_TONE: Record<string, string> = {
  beats: 'text-emerald-700 dark:text-emerald-400',
  lags: 'text-rose-700 dark:text-rose-400',
  mixed: 'text-amber-700 dark:text-amber-400',
  insufficient_data: 'text-slate-500 dark:text-slate-400',
}
const STATUS_KEYS: Record<string, MessageKey> = {
  pass: 'hurdlePass',
  fail: 'hurdleFail',
  not_applicable: 'hurdleNotApplicable',
  unavailable: 'hurdleUnavailable',
}
const STATUS_TONE: Record<string, string> = {
  pass: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200',
  fail: 'bg-rose-100 text-rose-900 dark:bg-rose-500/20 dark:text-rose-200',
  not_applicable: NEUTRAL_TONE,
  unavailable: NEUTRAL_TONE,
}
const GUARD_KEYS: Record<string, MessageKey> = {
  clear: 'guardClear',
  fired: 'guardFired',
  unavailable: 'guardUnavailable',
}
const ACTION_KEYS: Record<string, MessageKey> = {
  strong_buy: 'actionStrongBuy',
  buy: 'actionBuy',
  accumulate: 'actionAccumulate',
  hold: 'actionHold',
  trim: 'actionTrim',
  sell: 'actionSell',
  avoid: 'actionAvoid',
}

const money = (value: number | null | undefined): string =>
  value == null || Number.isNaN(value) ? '—' : `$${value.toFixed(2)}`

const band = (range: PriceRange | null): string => (range ? `${money(range.low)}–${money(range.high)}` : '—')

const readable = (value: string | null | undefined): string =>
  value ? value.toLowerCase().replace(/_/g, ' ') : '—'

const actionLabel = (
  t: (key: MessageKey, values?: Record<string, string | number>) => string,
  value: string | null | undefined,
): string => {
  if (!value) return '—'
  const key = ACTION_KEYS[value]
  return key ? t(key) : readable(value)
}

const signedPct = (value: number | null): string =>
  value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(1)}%`

function useReason() {
  const { t } = useI18n()
  return (adjustment: ConsolidatedAdjustment, hurdle: IndexHurdle | null): string => {
    switch (adjustment.reason) {
      case 'fundamentals_weak':
        return t('reasonFundamentalsWeak')
      case 'index_hurdle_failed':
        return hurdle?.lagging?.length
          ? t('reasonIndexHurdleFailed', { benchmarks: hurdle.lagging.join(', ') })
          : t('reasonEarningsGuard')
      case 'index_hurdle_unavailable':
        return t('reasonIndexHurdleUnavailable')
      case 'technical_unavailable':
        return t('reasonTechnicalUnavailable')
      default:
        return adjustment.reason
    }
  }
}

function HorizonColumn({
  entry,
  titleKey,
  windowKey,
  hurdle,
}: {
  entry: ConsolidatedHorizon
  titleKey: MessageKey
  windowKey: MessageKey
  hurdle: IndexHurdle | null
}) {
  const { t } = useI18n()
  const reason = useReason()
  const technical = entry.technical
  const finalAction = entry.final_action
  const changed = technical?.action != null && finalAction !== technical.action

  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-[#0d0f14]">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-semibold text-slate-700 dark:text-slate-200">{t(titleKey)}</span>
        <span className="text-[10px] text-slate-500 dark:text-slate-400">{t(windowKey)}</span>
      </div>

      <div className="mt-1.5">
        <span
          className={`rounded px-2 py-0.5 text-[13px] font-semibold ${finalAction ? (ACTION_TONE[finalAction] ?? NEUTRAL_TONE) : NEUTRAL_TONE}`}
        >
          {finalAction ? actionLabel(t, finalAction) : t('unavailable')}
        </span>
      </div>

      {changed ? (
        <p className="mt-1.5 text-[11px] text-slate-600 dark:text-slate-400">
          {t('technicalAction')} <span className="line-through">{actionLabel(t, technical!.action)}</span> → {t('finalAction')}{' '}
          {actionLabel(t, finalAction)}
        </p>
      ) : null}
      {entry.adjustments.map((adjustment) => (
        <p key={`${adjustment.layer}-${adjustment.reason}`} className="text-[11px] text-amber-700 dark:text-amber-400">
          {reason(adjustment, hurdle)}
        </p>
      ))}

      {technical?.available ? (
        <>
          <p className="mt-1.5 text-[11px] text-slate-600 dark:text-slate-400">
            {technical.confidence != null ? t('percentConfidence', { percent: Math.round(technical.confidence) }) : ''}
            {technical.data_quality != null ? ` · ${t('data')} ${technical.data_quality}` : ''}
          </p>
          <p className="text-[11px] text-slate-500 dark:text-slate-400">{readable(technical.price_state)}</p>
          {technical.price_state === 'INVALID_LANDSCAPE' ? (
            <p className="mt-2 text-[11px] italic text-slate-500 dark:text-slate-400">{t('noPriceLandscape')}</p>
          ) : (
            <dl className="mt-2 space-y-1 text-[11px]">
              <div className="flex justify-between gap-2">
                <dt className="text-emerald-700 dark:text-emerald-400">{t('opportunity')}</dt>
                <dd className="tabular-nums text-slate-700 dark:text-slate-300">{band(technical.opportunity_range)}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-orange-700 dark:text-orange-400">{t('reduce')}</dt>
                <dd className="tabular-nums text-slate-700 dark:text-slate-300">{band(technical.reduce_range)}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-slate-500 dark:text-slate-400">{t('invalidation')}</dt>
                <dd className="tabular-nums text-slate-700 dark:text-slate-300">{money(technical.invalidation)}</dd>
              </div>
            </dl>
          )}
          {technical.reasons?.length ? (
            <p className="mt-2 line-clamp-2 text-[11px] text-slate-500 dark:text-slate-400" title={technical.reasons.join('\n')}>
              {technical.reasons[0]}
            </p>
          ) : null}
        </>
      ) : null}

      <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">
        {t('fundamentalsStance', { stance: t(STANCE_KEYS[entry.fundamentals.stance] ?? 'stanceUnavailable') })}
        {entry.fundamentals.applied ? '' : ` · ${t('fundamentalsNotApplied')}`}
      </p>
    </div>
  )
}

function HurdleTable({ hurdle }: { hurdle: IndexHurdle | null }) {
  const { t } = useI18n()
  const status = hurdle?.status ?? 'unavailable'

  return (
    <div className="mt-3 rounded-md border border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-[#0d0f14]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-600 dark:text-slate-300">
          {t('indexHurdle')}
        </p>
        <span className={`rounded px-2 py-0.5 text-[11px] font-semibold ${STATUS_TONE[status] ?? NEUTRAL_TONE}`}>
          {t(STATUS_KEYS[status] ?? 'hurdleUnavailable')}
        </span>
      </div>
      <p className="mt-1 text-[12px] text-slate-600 dark:text-slate-400">{t('indexHurdleHint')}</p>

      {hurdle?.benchmarks?.length ? (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[520px] text-left text-[11px]">
            <thead className="text-slate-500 dark:text-slate-400">
              <tr>
                <th className="py-1 pr-2 font-medium">{t('hurdleBenchmark')}</th>
                <th className="py-1 pr-2 font-medium">{t('hurdleRole')}</th>
                <th className="py-1 pr-2 text-right font-medium">{t('hurdleRel121')}</th>
                <th className="py-1 pr-2 text-right font-medium">{t('hurdleRel6m')}</th>
                <th className="py-1 pr-2 text-center font-medium">{t('hurdleTrend')}</th>
                <th className="py-1 font-medium">{t('hurdleResult')}</th>
              </tr>
            </thead>
            <tbody className="text-slate-700 dark:text-slate-300">
              {hurdle.benchmarks.map((row) => (
                <tr key={row.symbol} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="py-1 pr-2 font-semibold" title={row.label}>
                    {row.symbol}
                  </td>
                  <td className="py-1 pr-2">
                    {t(ROLE_KEYS[row.role] ?? 'hurdleRoleIndex')}
                    <span className="text-slate-400"> · {row.label}</span>
                  </td>
                  <td className="py-1 pr-2 text-right tabular-nums">{signedPct(row.rel_12_1_pct)}</td>
                  <td className="py-1 pr-2 text-right tabular-nums">{signedPct(row.rel_6m_pct)}</td>
                  <td className="py-1 pr-2 text-center">
                    {row.ratio_above_200d == null ? '—' : row.ratio_above_200d ? '✓' : '✗'}
                  </td>
                  <td className={`py-1 font-semibold ${RESULT_TONE[row.result] ?? ''}`}>
                    {t(RESULT_KEYS[row.result] ?? 'hurdleInsufficient')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {hurdle ? (
        <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">
          {t('earningsGuardLabel')} · {t(GUARD_KEYS[hurdle.earnings_guard?.status] ?? 'guardUnavailable')}
        </p>
      ) : null}
    </div>
  )
}

/**
 * The consolidated decision: Vincent's technical action per horizon, lowered
 * only by weak fundamentals (mid and long) and capped at hold when the stock is
 * not expected to beat every benchmark. Horizons stay independent; his own
 * action is shown whenever the final one differs.
 */
export function FinalDecisionPanel({ decision }: FinalDecisionPanelProps) {
  const { t } = useI18n()
  const quality = decision.data_quality

  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/40">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-600 dark:text-slate-300">
          {t('finalDecision')}
        </p>
        {decision.producer ? <p className="text-[11px] text-slate-500 dark:text-slate-400">{decision.producer}</p> : null}
      </div>
      <p className="mt-1 text-[12px] text-slate-600 dark:text-slate-400">{t('finalDecisionHint')}</p>
      {quality ? (
        <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
          {t('consolidatedInputs', {
            fourHour: quality.four_hour ?? '—',
            oneHour: quality.one_hour ?? '—',
            market: quality.market ?? '—',
          })}
        </p>
      ) : null}

      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
        {HORIZONS.map(({ key, title, window }) => (
          <HorizonColumn
            key={key}
            entry={decision.horizons[key]}
            titleKey={title}
            windowKey={window}
            hurdle={decision.index_hurdle}
          />
        ))}
      </div>

      <HurdleTable hurdle={decision.index_hurdle} />
    </div>
  )
}
