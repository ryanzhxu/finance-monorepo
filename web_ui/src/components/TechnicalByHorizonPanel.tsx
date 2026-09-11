import type { Recommendation, TechnicalVerdict } from '../api/types'
import { useI18n, type MessageKey } from '../i18n'

type TechnicalByHorizonPanelProps = {
  recommendation: Recommendation
}

/** His horizons, in his own terms. The API keys are the consumer's enum. */
const HORIZON_LABEL_KEYS: Record<string, { title: MessageKey; window: MessageKey }> = {
  '1D': { title: 'horizonShort', window: 'horizonShortWindow' },
  '1W': { title: 'horizonShort', window: 'horizonShortWindow' },
  '2-4W': { title: 'horizonMid', window: 'horizonMidWindow' },
  '3-6M': { title: 'horizonLong', window: 'horizonLongWindow' },
}

/**
 * His seven actions, not the three-way Direction projection.
 *
 * This distinction is the reason the panel shows `action` rather than
 * `direction`: `avoid` and `hold` both project to HOLD, but "do not enter" and
 * "keep holding" are different instructions for someone already in the
 * position. His AGENTS.md is explicit that avoid is not sell either.
 */
const ACTION_TONE: Record<string, string> = {
  strong_buy: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200',
  buy: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200',
  accumulate: 'bg-emerald-50 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-300',
  hold: 'bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200',
  trim: 'bg-orange-100 text-orange-900 dark:bg-orange-500/20 dark:text-orange-200',
  sell: 'bg-rose-100 text-rose-900 dark:bg-rose-500/20 dark:text-rose-200',
  avoid: 'bg-slate-200 text-slate-700 dark:bg-slate-700/50 dark:text-slate-300',
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

function Landscape({ verdict }: { verdict: TechnicalVerdict }) {
  const { t } = useI18n()
  const opportunity = verdict.opportunity_range
  const reduce = verdict.reduce_range

  // An unusable landscape is stated, not dressed up as a weak opinion. His
  // engine emits null bands here deliberately rather than a fake range.
  if (verdict.price_state === 'INVALID_LANDSCAPE' || (!opportunity && !reduce)) {
    return (
      <p className="mt-2 text-[11px] italic text-slate-500 dark:text-slate-400">
        {t('noPriceLandscape')}
      </p>
    )
  }

  return (
    <dl className="mt-2 space-y-1 text-[11px]">
      <div className="flex justify-between gap-2">
        <dt className="text-emerald-700 dark:text-emerald-400">{t('opportunity')}</dt>
        <dd className="tabular-nums text-slate-700 dark:text-slate-300">
          {opportunity ? `${money(opportunity.low)}–${money(opportunity.high)}` : '—'}
        </dd>
      </div>
      <div className="flex justify-between gap-2">
        <dt className="text-orange-700 dark:text-orange-400">{t('reduce')}</dt>
        <dd className="tabular-nums text-slate-700 dark:text-slate-300">
          {reduce ? `${money(reduce.low)}–${money(reduce.high)}` : '—'}
        </dd>
      </div>
      <div className="flex justify-between gap-2">
        <dt className="text-slate-500 dark:text-slate-400">{t('invalidation')}</dt>
        <dd className="tabular-nums text-slate-700 dark:text-slate-300">{money(verdict.invalidation)}</dd>
      </div>
    </dl>
  )
}

/**
 * Vincent's short / mid / long verdicts, side by side.
 *
 * His engine emits these independently and states there is no overall action,
 * so they are rendered as three peers rather than reduced to one number. Each
 * column carries his action, his execution intent, and the price landscape that
 * produced them — the levels are the point of his engine, not a detail.
 */
export function TechnicalByHorizonPanel({ recommendation }: TechnicalByHorizonPanelProps) {
  const { t } = useI18n()
  const entries = recommendation.technical_by_horizon
  if (!entries || entries.length === 0) {
    return null
  }

  const producer = recommendation.technical_producer

  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/40">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-600 dark:text-slate-300">
          {t('technicalByHorizon')}
        </p>
        {producer ? (
          <p className="text-[11px] text-slate-500 dark:text-slate-400">{producer}</p>
        ) : null}
      </div>
      <p className="mt-1 text-[12px] text-slate-600 dark:text-slate-400">
        {t('technicalByHorizonHint')}
      </p>

      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
        {entries.map(({ horizon, verdict }) => {
          const labelKeys = HORIZON_LABEL_KEYS[horizon]
          const label = labelKeys ? { title: t(labelKeys.title), window: t(labelKeys.window) } : { title: horizon, window: '' }
          const action = verdict.action ?? verdict.direction.toLowerCase()
          const tone = ACTION_TONE[action] ?? 'bg-slate-200 text-slate-700 dark:bg-slate-700/50 dark:text-slate-300'

          return (
            <div
              key={horizon}
              className="rounded-md border border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-[#0d0f14]"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[11px] font-semibold text-slate-700 dark:text-slate-200">
                  {label.title}
                </span>
                <span className="text-[10px] text-slate-500 dark:text-slate-400">{label.window}</span>
              </div>

              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <span className={`rounded px-2 py-0.5 text-[12px] font-semibold ${tone}`}>
                  {actionLabel(t, action)}
                </span>
                {verdict.execution_intent ? (
                  <span className="text-[11px] text-slate-500 dark:text-slate-400">
                    → {verdict.execution_intent}
                  </span>
                ) : null}
              </div>

              <p className="mt-1.5 text-[11px] text-slate-600 dark:text-slate-400">
                {t('percentConfidence', { percent: (verdict.confidence * 100).toFixed(0) })}
                {verdict.data_quality != null ? ` · ${t('data')} ${verdict.data_quality}` : ''}
              </p>
              <p className="text-[11px] text-slate-500 dark:text-slate-400">{readable(verdict.price_state)}</p>

              <Landscape verdict={verdict} />

              {verdict.reasons?.length ? (
                <p
                  className="mt-2 line-clamp-2 text-[11px] text-slate-500 dark:text-slate-400"
                  title={verdict.reasons.join('\n')}
                >
                  {verdict.reasons[0]}
                </p>
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}
